#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd "$(dirname "$0")" && pwd)
test_dir=$(mktemp -d)
trap 'rm -rf "$test_dir"' EXIT
export TEST_STATE="$test_dir"
export PROJECT_ID=test-project REGION=test-region REGISTRY=registry.test/project/repository
export BACKEND_IMAGE="$REGISTRY/backend@sha256:$(printf '%064d' 1)"
export FRONTEND_IMAGE="$REGISTRY/frontend@sha256:$(printf '%064d' 2)"
export GITHUB_SHA=test-sha GITHUB_STEP_SUMMARY="$test_dir/summary"
mkdir "$test_dir/bin"
export PATH="$test_dir/bin:$PATH"

cat > "$test_dir/bin/gcloud" <<'MOCK'
#!/usr/bin/env bash
set -euo pipefail
shift 3
resource=$1 action=$2 service=$3
if [[ "$action" == update ]]; then
  [[ "$*" == "services update $service --region=test-region --image="*" --deploy-health-check" ]]
  [[ "$#" == 6 ]]
  printf '%s\n' "$service" >> "$TEST_STATE/updates"
  if [[ "${SCENARIO:-}" == backend-fails && "$service" == samurai-backend ]]; then exit 1; fi
  touch "$TEST_STATE/$service"
  exit
fi
if [[ "$resource" == revisions ]]; then
  if [[ "$service" == *-new ]]; then
    if [[ "$service" == samurai-backend-new ]]; then printf '%s\n' "$BACKEND_IMAGE"; else printf '%s\n' "$FRONTEND_IMAGE"; fi
  else
    printf 'registry.test/old@sha256:%064d\n' 0
  fi
  exit
fi
revision="$service-old"
if [[ -f "$TEST_STATE/$service" ]]; then revision="$service-new"; fi
iap=true
mode=iap
if [[ "${SCENARIO:-}" == guest* ]]; then iap=false; mode=guest; fi
if [[ "${SCENARIO:-}" == guest-iap ]]; then iap=true; fi
if [[ "${SCENARIO:-}" == unprotected ]]; then iap=false; fi
jq -n --arg revision "$revision" --arg service "$service" --arg iap "$iap" --arg mode "$mode" '{
  metadata: {annotations: {"run.googleapis.com/iap-enabled": $iap}},
  spec: {template: {spec: {containers: [{env: [{name: "FRONTEND_AUTH_MODE", value: $mode}], startupProbe: {httpGet: {path: "/healthz"}}}]}}},
  status: {latestReadyRevisionName: $revision, latestCreatedRevisionName: $revision,
    url: ("https://" + $service + ".test"),
    conditions: [{type: "Ready", status: "True"}],
    traffic: [{revisionName: $revision, percent: 100}]}
}'
MOCK
cat > "$test_dir/bin/curl" <<'MOCK'
#!/usr/bin/env bash
set -euo pipefail
if [[ "$*" == *samurai-frontend* ]]; then
  if [[ "${SCENARIO:-}" == public-response || "${SCENARIO:-}" == guest ]]; then printf 200; else printf 302; fi
fi
MOCK
chmod +x "$test_dir/bin/gcloud" "$test_dir/bin/curl"

for scenario in success unprotected backend-fails public-response invalid-digest guest guest-iap guest-denied; do
  rm -f "$test_dir/updates" "$test_dir/samurai-backend" "$test_dir/samurai-frontend" "$test_dir/summary"
  export SCENARIO="$scenario"
  image="$BACKEND_IMAGE"
  if [[ "$scenario" == invalid-digest ]]; then image="$REGISTRY/backend:main"; fi
  if BACKEND_IMAGE="$image" bash "$script_dir/deploy-cloud-run.sh" > "$test_dir/output" 2>&1; then
    [[ "$scenario" == success || "$scenario" == guest ]]
    [[ "$(cat "$test_dir/updates")" == $'samurai-backend\nsamurai-frontend' ]]
    grep -q 'rollback image:' "$test_dir/summary"
    grep -q 'startup/readiness and configured frontend access checks passed' "$test_dir/summary"
  else
    [[ "$scenario" != success && "$scenario" != guest ]]
    case "$scenario" in
      unprotected|invalid-digest|guest-iap) [[ ! -f "$test_dir/updates" ]] ;;
      backend-fails) [[ "$(cat "$test_dir/updates")" == samurai-backend ]] ;;
      public-response) grep -q 'unexpected anonymous HTTP 200' "$test_dir/output" ;;
    esac
  fi
  printf 'PASS: deployment contract %s\n' "$scenario"
done
