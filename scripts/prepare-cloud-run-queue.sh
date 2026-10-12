#!/usr/bin/env bash
set -euo pipefail

readonly expected_project=samurai-ai-company-2026
readonly expected_region=asia-south1
readonly service=samurai-backend

usage() {
  printf '%s\n' \
    'Usage: PROJECT_ID=samurai-ai-company-2026 REGION=asia-south1 BACKEND_IMAGE=... VPC_NETWORK=... VPC_SUBNET=... REDIS_SECRET=... REDIS_SECRET_VERSION=... bash scripts/prepare-cloud-run-queue.sh (--dry-run|--execute)' \
    '' \
    'Applies the reviewed backend image and queue runtime configuration, then verifies Cloud Run readback.'
}

dry_run=false
case "${1:-}" in
  --help) usage; exit ;;
  --dry-run) dry_run=true ;;
  --execute) ;;
  *) usage >&2; exit 2 ;;
esac
[[ $# -eq 1 ]] || { usage >&2; exit 2; }

: "${PROJECT_ID:?PROJECT_ID is required}"
: "${REGION:?REGION is required}"
: "${BACKEND_IMAGE:?BACKEND_IMAGE is required}"
: "${VPC_NETWORK:?VPC_NETWORK is required}"
: "${VPC_SUBNET:?VPC_SUBNET is required}"
: "${REDIS_SECRET:?REDIS_SECRET is required}"
: "${REDIS_SECRET_VERSION:?REDIS_SECRET_VERSION is required}"
GCLOUD_COMMAND_TIMEOUT_SECONDS=${GCLOUD_COMMAND_TIMEOUT_SECONDS:-1200}

[[ "$PROJECT_ID" == "$expected_project" ]] || { printf 'PROJECT_ID must be %s\n' "$expected_project" >&2; exit 2; }
[[ "$REGION" == "$expected_region" ]] || { printf 'REGION must be %s\n' "$expected_region" >&2; exit 2; }
[[ "$BACKEND_IMAGE" =~ ^asia-south1-docker\.pkg\.dev/samurai-ai-company-2026/samurai/backend@sha256:[a-f0-9]{64}$ ]] || { printf 'BACKEND_IMAGE must be the immutable production backend digest\n' >&2; exit 2; }
[[ "$VPC_NETWORK" =~ ^[a-z]([-a-z0-9]{0,61}[a-z0-9])?$ ]] || { printf 'VPC_NETWORK must be an explicit network name\n' >&2; exit 2; }
[[ "$VPC_SUBNET" =~ ^[a-z]([-a-z0-9]{0,61}[a-z0-9])?$ ]] || { printf 'VPC_SUBNET must be an explicit subnet name\n' >&2; exit 2; }
[[ "$REDIS_SECRET" =~ ^[A-Za-z0-9_-]{1,255}$ ]] || { printf 'REDIS_SECRET must be a Secret Manager secret name\n' >&2; exit 2; }
[[ "$REDIS_SECRET_VERSION" =~ ^[1-9][0-9]*$ ]] || { printf 'REDIS_SECRET_VERSION must be an explicit numeric version\n' >&2; exit 2; }
[[ "$GCLOUD_COMMAND_TIMEOUT_SECONDS" =~ ^[1-9][0-9]*$ ]] && (( GCLOUD_COMMAND_TIMEOUT_SECONDS <= 1800 )) || { printf 'GCLOUD_COMMAND_TIMEOUT_SECONDS must be between 1 and 1800\n' >&2; exit 2; }

cloud=(gcloud --project="$PROJECT_ID" --quiet run)
update=(services update "$service"
  --region="$REGION"
  --image="$BACKEND_IMAGE"
  --update-env-vars=QUEUE_ENABLED=true
  --update-secrets="REDIS_URL=$REDIS_SECRET:$REDIS_SECRET_VERSION"
  --network="$VPC_NETWORK"
  --subnet="$VPC_SUBNET"
  --vpc-egress=private-ranges-only
  --cpu=1
  --memory=2Gi
  --no-cpu-throttling
  --min=1
  --max=2
  --concurrency=8
  --deploy-health-check)
if [[ "$dry_run" == true ]]; then
  printf 'PREPARATION ONLY; no cloud command executed.\n'
  printf '%q ' "${cloud[@]}" "${update[@]}"
  printf '\n'
  exit
fi

run_bounded() {
  perl -e '$seconds = shift @ARGV; alarm $seconds; exec @ARGV; exit 127' "$GCLOUD_COMMAND_TIMEOUT_SECONDS" "$@"
}

before=$(run_bounded "${cloud[@]}" services describe "$service" --region="$REGION" --format=json)
previous_revision=$(jq -er '.status.latestReadyRevisionName' <<< "$before")
if ! preserved=$(jq -ce '
  . as $root |
  $root.spec.template as $template |
  [$template.spec.containers[0].env[] |
    select(.name == "JWT_VERIFICATION_KEY" or .name == "FRONTEND_JWT_VERIFICATION_KEY")] |
  sort_by(.name) as $jwt |
  if ($template.spec.serviceAccountName | length) > 0 and
     ($template.metadata.annotations["run.googleapis.com/cloudsql-instances"] | length) > 0 and
     ($template.spec.containers[0].startupProbe.httpGet.path | length) > 0 and
     ($jwt | length) == 2 and
     ([$root.status.traffic[] | select(.percent > 0)] |
       length == 1 and .[0].revisionName == $root.status.latestReadyRevisionName and .[0].percent == 100)
  then {
    serviceAccountName: $template.spec.serviceAccountName,
    cloudSql: $template.metadata.annotations["run.googleapis.com/cloudsql-instances"],
    startupProbe: $template.spec.containers[0].startupProbe,
    jwt: $jwt
  }
  else error("required deployment guard is absent")
  end
' <<< "$before"); then
  printf 'existing backend identity, Cloud SQL, startup probe, or JWT trust guard is absent\n' >&2
  exit 1
fi

fail_after_mutation() {
  printf 'Cloud Run update may have changed state. Restore prior revision %s through the authorized rollback runbook.\n' "$previous_revision" >&2
  exit 1
}

if ! run_bounded "${cloud[@]}" "${update[@]}" >/dev/null; then
  fail_after_mutation
fi

if ! after=$(run_bounded "${cloud[@]}" services describe "$service" --region="$REGION" --format=json); then
  fail_after_mutation
fi
if ! jq -e \
  --arg image "$BACKEND_IMAGE" \
  --arg network "$VPC_NETWORK" \
  --arg subnet "$VPC_SUBNET" \
  --arg secret "$REDIS_SECRET" \
  --arg version "$REDIS_SECRET_VERSION" \
  --argjson preserved "$preserved" '
  . as $root |
  $root.spec.template as $template |
  [$template.spec.containers[0].env[] |
    select(.name == "JWT_VERIFICATION_KEY" or .name == "FRONTEND_JWT_VERIFICATION_KEY")] |
  sort_by(.name) as $jwt |
  ($template.metadata.annotations["run.googleapis.com/network-interfaces"] | fromjson) as $interfaces |
  ($template.spec.containers[0].env | map({key: .name, value: .}) | from_entries) as $env |
  $template.spec.serviceAccountName == $preserved.serviceAccountName and
  $template.metadata.annotations["run.googleapis.com/cloudsql-instances"] == $preserved.cloudSql and
  $template.spec.containers[0].startupProbe == $preserved.startupProbe and
  $jwt == $preserved.jwt and
  $template.spec.containers[0].image == $image and
  $env.QUEUE_ENABLED.value == "true" and
  $env.REDIS_URL.valueFrom.secretKeyRef.name == $secret and
  $env.REDIS_URL.valueFrom.secretKeyRef.key == $version and
  ($interfaces | length) == 1 and
  $interfaces[0].network == $network and
  $interfaces[0].subnetwork == $subnet and
  $template.metadata.annotations["run.googleapis.com/vpc-access-egress"] == "private-ranges-only" and
  $template.metadata.annotations["run.googleapis.com/cpu-throttling"] == "false" and
  $template.metadata.annotations["autoscaling.knative.dev/minScale"] == "1" and
  $template.metadata.annotations["autoscaling.knative.dev/maxScale"] == "2" and
  $template.spec.containers[0].resources.limits.cpu == "1" and
  $template.spec.containers[0].resources.limits.memory == "2Gi" and
  $template.spec.containerConcurrency == 8 and
  $root.status.latestCreatedRevisionName == $root.status.latestReadyRevisionName and
  any($root.status.conditions[]; .type == "Ready" and .status == "True")
' <<< "$after" >/dev/null; then
  fail_after_mutation
fi

revision=$(jq -er '.status.latestReadyRevisionName' <<< "$after")
printf '%s revision %s configuration readback passed.\n' "$service" "$revision"
