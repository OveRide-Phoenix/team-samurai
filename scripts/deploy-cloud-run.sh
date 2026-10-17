#!/usr/bin/env bash
set -euo pipefail

: "${PROJECT_ID:?}" "${REGION:?}" "${REGISTRY:?}" "${BACKEND_IMAGE:?}" "${FRONTEND_IMAGE:?}"
: "${GITHUB_STEP_SUMMARY:?}" "${GITHUB_SHA:?}"

[[ "$BACKEND_IMAGE" =~ ^${REGISTRY}/backend@sha256:[a-f0-9]{64}$ ]]
[[ "$FRONTEND_IMAGE" =~ ^${REGISTRY}/frontend@sha256:[a-f0-9]{64}$ ]]
cloud=(gcloud --project="$PROJECT_ID" --quiet run)
check_frontend_auth() {
  jq -e '
    ([.spec.template.spec.containers[0].env[]? | select(.name == "FRONTEND_AUTH_MODE") | .value][0] // "iap") as $mode |
    if $mode == "guest" then .metadata.annotations["run.googleapis.com/iap-enabled"] != "true"
    elif $mode == "iap" then .metadata.annotations["run.googleapis.com/iap-enabled"] == "true"
    else false end
  ' <<< "$1" >/dev/null
}
printf '## Production deployment `%s`\n\n' "$GITHUB_SHA" >> "$GITHUB_STEP_SUMMARY"

# Both services must already exist; capture rollback targets before either update.
for component in backend frontend; do
  service="samurai-$component"
  state=$("${cloud[@]}" services describe "$service" --region="$REGION" --format=json)
  if [[ "$component" == frontend ]]; then
    check_frontend_auth "$state"
    jq -e '.spec.template.spec.containers[0].startupProbe.httpGet.path == "/healthz"' <<< "$state" >/dev/null
  fi
  revision=$(jq -er '.status.latestReadyRevisionName' <<< "$state")
  jq -e --arg revision "$revision" '
    [.status.traffic[] | select(.percent > 0)] |
    length == 1 and .[0].revisionName == $revision and .[0].percent == 100
  ' <<< "$state" >/dev/null
  previous=$("${cloud[@]}" revisions describe "$revision" --region="$REGION" --format='value(status.imageDigest)')
  [[ "$previous" == *@sha256:* ]]
  printf '%s previous revision: `%s`; rollback image: `%s`\n\n' "$service" "$revision" "$previous" >> "$GITHUB_STEP_SUMMARY"
done

for component in backend frontend; do
  service="samurai-$component"
  image="$BACKEND_IMAGE"
  if [[ "$component" == frontend ]]; then image="$FRONTEND_IMAGE"; fi
  # Image-only updates preserve bootstrap secrets, identities, SQL, IAP, and probes.
  "${cloud[@]}" services update "$service" --region="$REGION" --image="$image" --deploy-health-check
  state=$("${cloud[@]}" services describe "$service" --region="$REGION" --format=json)
  revision=$(jq -er '.status.latestReadyRevisionName' <<< "$state")
  jq -e --arg revision "$revision" '
    .status.latestCreatedRevisionName == $revision and
    any(.status.conditions[]; .type == "Ready" and .status == "True") and
    ([.status.traffic[] | select(.percent > 0)] |
     length == 1 and .[0].revisionName == $revision and .[0].percent == 100)
  ' <<< "$state" >/dev/null
  deployed=$("${cloud[@]}" revisions describe "$revision" --region="$REGION" --format='value(status.imageDigest)')
  [[ "$deployed" == "$image" ]]
  url=$(jq -er '.status.url' <<< "$state")
  if [[ "$component" == backend ]]; then
    curl --fail --silent --show-error --retry 5 --retry-all-errors --max-time 30 "$url/agentos/health" >/dev/null
  else
    check_frontend_auth "$state"
    code=$(curl --silent --show-error --max-time 30 --output /dev/null --write-out '%{http_code}' "$url/")
    mode=$(jq -r '[.spec.template.spec.containers[0].env[]? | select(.name == "FRONTEND_AUTH_MODE") | .value][0] // "iap"' <<< "$state")
    if [[ "$mode" == guest ]]; then
      [[ "$code" == 200 ]] || { printf 'Guest frontend returned unexpected anonymous HTTP %s\n' "$code" >&2; exit 1; }
    else
      case "$code" in
        302|401|403) ;;
        *) printf 'Protected frontend returned unexpected anonymous HTTP %s\n' "$code" >&2; exit 1 ;;
      esac
    fi
  fi
  printf '%s deployed revision: `%s`; image: `%s`; URL: %s\n\n' "$service" "$revision" "$image" "$url" >> "$GITHUB_STEP_SUMMARY"
done
printf 'Cloud Run startup/readiness and configured frontend access checks passed. Guest or authenticated founder journeys and Agno Live acceptance require separate verification.\n' >> "$GITHUB_STEP_SUMMARY"
