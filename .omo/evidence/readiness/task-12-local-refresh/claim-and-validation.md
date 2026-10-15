# Task 12 local documentation refresh

## Scope

The committed documentation changes are `README.md`, `docs/architecture.md`,
`docs/local-development.md`, `.omo/plans/README.md`, `AGENTS.md`,
`frontend/README.md`, and `frontend/AGENTS.md`; this evidence receipt is
included with them. This is a local documentation snapshot; it does not deploy,
publish, call a provider, change an account, or claim a current cloud release.

## Claim sources

| Documentation claim | Direct source checked | Verified boundary |
| --- | --- | --- |
| The local frontend integration exists | `frontend/vite.config.mjs`, `frontend/src/agentosProxy.test.ts`, `frontend/BACKEND_CONTRACT.md` | The Vite proxy is local-only. Recorded production IAP/Node-proxy acceptance is historical and does not deploy the current source. |
| Workspace/company rows are canonical | `.omo/plans/samurai-founder-platform.md` Tasks 5–6 and `backend/src/samurai/company_store.py` | AgentOS sessions/runs remain actor-scoped; the backend owns accepted company state. |
| Workspace files are local by default | `.omo/plans/samurai-founder-platform.md` Task 8 and `docs/local-development.md` | A Cloud Storage adapter/deployment is not established. |
| Production-history guidance remains bounded | `AGENTS.md`, `frontend/README.md`, and `frontend/AGENTS.md` | Cloud Run/IAP statements describe recorded revisions or intended behavior, not current-source deployment; Task 9 cites its accepted SHA and final counts. |
| Founder Platform status | `.omo/plans/samurai-founder-platform.md` checkboxes: Tasks 1–9 checked, Task 10 unchecked | The separate Founder Platform Task 10 is in progress. |
| Founder Platform Task 9 result | `/Users/bkakumar/Documents/ChatGPT/Samurai/samurai-founder-file-api/.omo/evidence/founder-platform/task-9/DoneClaim.md`, `/Users/bkakumar/Documents/ChatGPT/Samurai/samurai-founder-file-api/.omo/evidence/founder-platform/task-9/final-acceptance-receipt.txt`, and `/Users/bkakumar/Documents/ChatGPT/Samurai/samurai-founder-file-api/.omo/evidence/founder-platform/task-9/task-check-final-pass.txt` | Exact accepted SHA `5eea8dea4c4469c39e6682879d637d5ca3dcf0f8`; focused 39/0, full backend 266 passed/105 environment-gated skips, frontend 130 passed, and provider-free Vite-BFF/IAB owner download/deletion. |
| Historical deployment and external gates | `/Users/bkakumar/Documents/ChatGPT/Samurai/samurai-readiness-runtime/.omo/evidence/readiness/task-12/docs-audit.md` and `/Users/bkakumar/Documents/ChatGPT/Samurai/samurai-readiness-runtime/.omo/evidence/readiness/task-13/final-blocked-state.txt` | Historical cloud/IAP evidence does not prove the current checkout is deployed. Readiness Task 11 is deferred; external access/publication remains blocked. |

## Success-criterion evidence

| Criterion | Scenario and invocation | Binary observable | Captured artifact |
| --- | --- | --- |
| Stale local-frontend, cloud, and Task 9 wording is removed | `rg -n 'frontend integration is not implemented|Planned frontend-to-AgentOS|Production auth/proxy, source-supported|1f841e7|233 backend|26 PostgreSQL|production Node server supplies|Cloud Run container serves|Production verifies Google IAP' README.md docs/architecture.md docs/local-development.md .omo/plans/README.md AGENTS.md frontend/README.md frontend/AGENTS.md` | Exit 1 with no matches | `claim-and-validation.md` (validation receipt below) |
| Status and boundary claims match their sources | `rg -n '^- \\[x\\] [1-9]\\.|^- \\[ \\] 10\\.' .omo/plans/samurai-founder-platform.md` plus `git show -s --format='%H%n%s' 5eea8dea4c4469c39e6682879d637d5ca3dcf0f8` | Nine accepted task rows, one in-progress Task 10 row, and the exact Task 9 SHA/subject | `claim-and-validation.md` (validation receipt below) |
| Documentation diff is structurally valid | `git diff --check -- README.md docs/architecture.md docs/local-development.md .omo/plans/README.md AGENTS.md frontend/README.md frontend/AGENTS.md` | Exit 0 with no diagnostics | `claim-and-validation.md` (validation receipt below) |
| Relative Markdown targets resolve | The Python read-only checker in the validation receipt below | `RELATIVE_LINKS_OK files=7 targets=37` | `claim-and-validation.md` (validation receipt below) |

## Validation receipt

```text
git diff --check -- README.md docs/architecture.md docs/local-development.md \
  .omo/plans/README.md AGENTS.md frontend/README.md frontend/AGENTS.md \
  .omo/evidence/readiness/task-12-local-refresh/claim-and-validation.md
DIFF_CHECK_EXIT=0

RELATIVE_LINKS_OK files=7 targets=37

RG_NO_STALE_CLAIM_MATCHES_EXIT=1
STALE_CLAIM_ASSERTION_EXIT=0

TASK9_ANCESTOR_OF_CURRENT_HEAD=YES
5eea8dea4c4469c39e6682879d637d5ca3dcf0f8
style(tests): apply upstream formatter
```
