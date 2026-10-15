# Local acceptance snapshot — 16 October 2026

This snapshot records the founder-platform implementation, not a deployed release
or a competition-ready submission. The original production/competition readiness
plan remains open.

## Version and checks

Production and test candidate: `7b731d6942e113e671d5ce0110d694deea19193e`.
Acceptance documentation: `da69bbfa6fef32abb01d789efde21eed4f550782`.
The latter changes only the two founder-plan documents; backend, frontend,
tests, dependency locks, and deployment files are identical.

| Check | Recorded result |
| --- | --- |
| `task check` | 554 backend tests, 150 frontend tests, static checks and build passed |
| `npm --prefix frontend run test:server` | 60 passed |
| `npm --prefix frontend run test:sites` | 4 passed |
| Platform evaluator against disposable PostgreSQL | 40 passed, zero skips, zero provider calls |

These are local results at the named version, not GitHub Actions or cloud
acceptance. Follow [local development](local-development.md) for setup and the
disposable evaluator command; private environments and ignored QA harnesses are
not required repository dependencies.

## Observed behavior

Founder-platform Tasks 1–20 are locally accepted. Their scope includes durable
approved-stage recovery, cancellation and stale-write fencing; workspace/company
membership; quotas and local files; governed founder references; source
adjudication; typed founder, offer, and knowledge views; explicit learning; and
persisted, allowlisted schedules and deterministic scenarios.

Task 20 browser/API acceptance created a scenario and schedule, executed one due
run, observed no duplicate receipt on replay, and retained company and result
hashes through an actual backend restart and browser reload. The completed
browser check recorded zero console errors or warnings. A revoked scheduled
actor was skipped without a result or canonical company mutation.

The isolated restore reconciled 18 table counts and populated company, file,
deletion, learning, schedule, and scenario records. Knowledge, session, and
work-intent tables were empty in that fixture; their populated-data recovery is
not established by this restore. Task-owned runtime resources were cleaned up.

Synthetic principals and illustrative scenario inputs were used. Scenarios remain
labelled `synthetic_scenario_not_validation`; learning and retrieved knowledge
remain untrusted context, not source-backed claims or action authority.

## Remaining gates

At `da69bbfa6fef32abb01d789efde21eed4f550782`, plan-compliance, code-quality,
security, runtime, scope/context, and final local manual QA reviews returned PASS.
Root reconciled the corrected PostgreSQL stale-write evidence: HTTP 401 probes
prove only authentication denial; the separate persistence test proves a stale
Agno upsert cannot overwrite the accepted canonical revision or actor mirror.
Local `main` was fast-forwarded to this exact reviewed commit with a clean tree.
No push occurred. Caller final acceptance of the founder plan remains pending;
these local reviews do not complete the original readiness plan.

- The paid cloud queue upgrade is deferred. Current-candidate deployment,
  cross-replica cloud recovery, and the isolated Cloud SQL restore drill remain
  unverified.
- No new live Gemini business journey is claimed. Source-supported strategy and
  business acceptance still require the approved bounded live evidence.
- The live second-Google-account test was explicitly skipped. Synthetic-actor
  isolation does not establish that exercise.
- Final public-repository review, publication permission, evaluator identities
  and access, official-template confirmation, final video, and submission
  verification remain open. Existing deck/PDF and narrative files are drafts.

See the [plan index](../.omo/plans/README.md),
[deployment evidence](gcp-deployment.md), and
[publication readiness](publication-readiness.md) for the separate boundaries.
Do not infer a deployed digest, public access, or submission receipt from a local
commit or passing test.

## Evidence locations

The local acceptance record is retained in ignored evidence, not published as
part of this guide: `task20-exact-check-7b731d6/result.json`,
`task20-premerge-acceptance.json`, `task20-independent-qa/`,
`task20-independent-qa-revoked/`, and the exact-SHA final `review-ledger.jsonl`.
The tracked plans describe acceptance and limitations for fresh checkouts;
absence of the private local receipts must not be presented as a new test run.
