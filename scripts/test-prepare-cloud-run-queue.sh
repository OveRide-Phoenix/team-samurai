#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd "$(dirname "$0")" && pwd)
test_dir=$(mktemp -d)
trap 'rm -rf "$test_dir"' EXIT
mkdir "$test_dir/bin"
export PATH="$test_dir/bin:$PATH"
export TEST_STATE="$test_dir"

cat > "$test_dir/bin/gcloud" <<'MOCK'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$@" >> "$TEST_STATE/gcloud-args"
[[ "$1" == "--project=samurai-ai-company-2026" ]]
[[ "$2" == --quiet ]]
[[ "$3" == run ]]
shift 3
if [[ "$1 $2 $3" == "services describe samurai-backend" ]]; then
  if [[ "${SCENARIO:-}" == post-describe-fails && -f "$TEST_STATE/updated" ]]; then exit 1; fi
  revision=samurai-backend-old
  network=old-network
  subnet=old-subnet
  queue=false
  secret=old-redis-url
  version=1
  min=0
  max=1
  throttling=true
  if [[ -f "$TEST_STATE/updated" ]]; then
    revision=samurai-backend-new
    network=samurai-network
    subnet=samurai-redis-subnet
    queue=true
    secret=samurai-redis-url
    version=7
    min=1
    max=1
    throttling=false
  fi
  if [[ "${SCENARIO:-}" == bad-readback && -f "$TEST_STATE/updated" ]]; then max=3; fi
  jq -n \
    --arg revision "$revision" --arg network "$network" --arg subnet "$subnet" \
    --arg queue "$queue" --arg secret "$secret" --arg version "$version" \
    --arg min "$min" --arg max "$max" --arg throttling "$throttling" '{
      metadata: {annotations: {"run.googleapis.com/minScale": $min, "run.googleapis.com/maxScale": $max}},
      spec: {template: {
        metadata: {annotations: {
          "run.googleapis.com/cloudsql-instances": "samurai-ai-company-2026:asia-south1:samurai-postgres",
          "run.googleapis.com/network-interfaces": ([{network: $network, subnetwork: $subnet}] | tojson),
          "run.googleapis.com/vpc-access-egress": "private-ranges-only",
          "run.googleapis.com/cpu-throttling": $throttling,
          "autoscaling.knative.dev/minScale": $min,
          "autoscaling.knative.dev/maxScale": $max
        }},
        spec: {
          serviceAccountName: "samurai-runtime@samurai-ai-company-2026.iam.gserviceaccount.com",
          containerConcurrency: 8,
          containers: [{
            image: "asia-south1-docker.pkg.dev/samurai-ai-company-2026/samurai/backend@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            resources: {limits: {cpu: "1", memory: "2Gi"}},
            startupProbe: {httpGet: {path: "/agentos/health"}},
            env: [
              {name: "JWT_VERIFICATION_KEY", valueFrom: {secretKeyRef: {name: "samurai-jwt-verification-key", key: "2"}}},
              {name: "FRONTEND_JWT_VERIFICATION_KEY", valueFrom: {secretKeyRef: {name: "samurai-frontend-verification-key", key: "1"}},},
              {name: "QUEUE_ENABLED", value: $queue},
              {name: "REDIS_URL", valueFrom: {secretKeyRef: {name: $secret, key: $version}}}
            ]
          }]
        }
      }},
      status: {latestReadyRevisionName: $revision, latestCreatedRevisionName: $revision,
        conditions: [{type: "Ready", status: "True"}],
        traffic: [{revisionName: $revision, percent: 100}]}
    }'
  exit
fi
if [[ "$1 $2 $3" == "services update samurai-backend" ]]; then
  touch "$TEST_STATE/updated"
  if [[ "${SCENARIO:-}" == update-fails ]]; then exit 1; fi
  if [[ "${SCENARIO:-}" == update-hangs ]]; then sleep 2; fi
  exit
fi
exit 64
MOCK
chmod +x "$test_dir/bin/gcloud"

export PROJECT_ID=samurai-ai-company-2026 REGION=asia-south1
export BACKEND_IMAGE=asia-south1-docker.pkg.dev/samurai-ai-company-2026/samurai/backend@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
export VPC_NETWORK=samurai-network VPC_SUBNET=samurai-redis-subnet
export REDIS_SECRET=samurai-redis-url REDIS_SECRET_VERSION=7

# Given no deployment inputs, when help is requested, then the local contract is available without cloud access.
env -i PATH="$PATH" bash "$script_dir/prepare-cloud-run-queue.sh" --help > "$test_dir/help"
grep -q '^Usage:' "$test_dir/help"
[[ ! -f "$test_dir/gcloud-args" ]]
printf 'PASS: help is local and side-effect free\n'

# Given complete inputs but no explicit action, when preparation runs, then it refuses an implicit mutation.
if bash "$script_dir/prepare-cloud-run-queue.sh" > "$test_dir/action-output" 2>&1; then
  exit 1
fi
grep -q -- '--dry-run|--execute' "$test_dir/action-output"
[[ ! -f "$test_dir/gcloud-args" ]]
printf 'PASS: mutation requires explicit execute acknowledgement\n'

# Given one required network input is absent, when execute is acknowledged, then it fails before invoking gcloud.
if env -u VPC_SUBNET bash "$script_dir/prepare-cloud-run-queue.sh" --execute > "$test_dir/missing-output" 2>&1; then
  exit 1
fi
grep -q 'VPC_SUBNET' "$test_dir/missing-output"
[[ ! -f "$test_dir/gcloud-args" ]]
printf 'PASS: missing configuration fails closed\n'

# Given the fixed project boundary is changed, when execute is acknowledged, then it fails before invoking gcloud.
if PROJECT_ID=another-project bash "$script_dir/prepare-cloud-run-queue.sh" --execute > "$test_dir/project-output" 2>&1; then
  exit 1
fi
grep -q 'PROJECT_ID must be samurai-ai-company-2026' "$test_dir/project-output"
[[ ! -f "$test_dir/gcloud-args" ]]
printf 'PASS: project boundary fails closed\n'

# Given an invalid command timeout, when dry-run is requested, then it fails before invoking gcloud.
if GCLOUD_COMMAND_TIMEOUT_SECONDS=0 bash "$script_dir/prepare-cloud-run-queue.sh" --dry-run > "$test_dir/timeout-output" 2>&1; then
  exit 1
fi
grep -q 'GCLOUD_COMMAND_TIMEOUT_SECONDS must be between 1 and 1800' "$test_dir/timeout-output"
[[ ! -f "$test_dir/gcloud-args" ]]
printf 'PASS: invalid command timeout fails closed\n'

# Given complete inputs, when dry-run is requested, then the exact mutation is previewed without invoking gcloud.
bash "$script_dir/prepare-cloud-run-queue.sh" --dry-run > "$test_dir/dry-run-output"
grep -q '^PREPARATION ONLY; no cloud command executed\.$' "$test_dir/dry-run-output"
grep -q -- '--update-secrets=REDIS_URL=samurai-redis-url:7' "$test_dir/dry-run-output"
grep -q -- '--network=samurai-network' "$test_dir/dry-run-output"
[[ ! -f "$test_dir/gcloud-args" ]]
printf 'PASS: dry-run previews the sanitized mutation without cloud access\n'

# Given complete explicit inputs and a conforming readback, when preparation runs, then every authorized setting is applied.
bash "$script_dir/prepare-cloud-run-queue.sh" --execute > "$test_dir/success-output"
for argument in \
  '--region=asia-south1' \
  '--image=asia-south1-docker.pkg.dev/samurai-ai-company-2026/samurai/backend@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa' \
  '--update-env-vars=QUEUE_ENABLED=true' \
  '--update-secrets=REDIS_URL=samurai-redis-url:7' \
  '--network=samurai-network' \
  '--subnet=samurai-redis-subnet' \
  '--vpc-egress=private-ranges-only' \
  '--cpu=1' '--memory=2Gi' '--no-cpu-throttling' \
  '--min=1' '--max=1' '--min-instances=1' '--max-instances=1' '--concurrency=8' '--deploy-health-check'; do
  grep -Fxq -- "$argument" "$test_dir/gcloud-args"
done
grep -q 'configuration readback passed' "$test_dir/success-output"
if grep -q 'redis://' "$test_dir/success-output"; then exit 1; fi
printf 'PASS: exact queue configuration is applied and read back without a secret value\n'

# Given update returns nonzero after changing mock state, when execute runs, then the prior revision warning is emitted.
rm -f "$test_dir/updated" "$test_dir/gcloud-args"
if SCENARIO=update-fails bash "$script_dir/prepare-cloud-run-queue.sh" --execute > "$test_dir/update-failure-output" 2>&1; then
  exit 1
fi
grep -q 'may have changed state' "$test_dir/update-failure-output"
grep -q 'prior revision samurai-backend-old' "$test_dir/update-failure-output"
printf 'PASS: nonzero update warns that cloud state may have changed\n'

# Given update exceeds the bounded command time after changing mock state, when execute runs, then it is stopped with the prior revision warning.
rm -f "$test_dir/updated" "$test_dir/gcloud-args"
if SCENARIO=update-hangs GCLOUD_COMMAND_TIMEOUT_SECONDS=1 bash "$script_dir/prepare-cloud-run-queue.sh" --execute > "$test_dir/update-timeout-output" 2>&1; then
  exit 1
fi
grep -q 'may have changed state' "$test_dir/update-timeout-output"
grep -q 'prior revision samurai-backend-old' "$test_dir/update-timeout-output"
printf 'PASS: timed-out update warns that cloud state may have changed\n'

# Given post-update describe fails, when execute runs, then the prior revision warning is emitted.
rm -f "$test_dir/updated" "$test_dir/gcloud-args"
if SCENARIO=post-describe-fails bash "$script_dir/prepare-cloud-run-queue.sh" --execute > "$test_dir/describe-failure-output" 2>&1; then
  exit 1
fi
grep -q 'may have changed state' "$test_dir/describe-failure-output"
grep -q 'prior revision samurai-backend-old' "$test_dir/describe-failure-output"
printf 'PASS: failed post-update readback warns that cloud state may have changed\n'

# Given the update command succeeds but scale readback differs, when preparation runs, then it refuses success.
rm -f "$test_dir/updated" "$test_dir/gcloud-args"
if SCENARIO=bad-readback bash "$script_dir/prepare-cloud-run-queue.sh" --execute > "$test_dir/readback-output" 2>&1; then
  exit 1
fi
grep -q 'may have changed state' "$test_dir/readback-output"
grep -q 'prior revision samurai-backend-old' "$test_dir/readback-output"
printf 'PASS: mismatched readback fails closed\n'
