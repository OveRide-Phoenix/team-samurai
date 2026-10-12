# Repository publication and evaluator-access readiness

**Status: BLOCKED — preparation audit only.** No repository visibility, IAM,
application, release, artifact, upload, message, deployment, or history change
was made by this audit. The application remains team-only behind IAP.

## Audited snapshot and coverage

The audit used a disposable mirror fetched from the configured remote on 12
October 2026. The candidate commit was
`c84b8a58eb682bc845663b8adb68a2bb580cdb44` (`main` and
`Kalyan/frontend-cicd`). The mirror contained seven reachable refs, including
one pull-request ref and no tag refs. `git fsck --full --no-reflogs` passed.

Gitleaks `8.30.1` (local binary SHA-256
`f414bc2fb952be6c9072b75cb411e3368614ef4b16d48dbd9ad238034afd2302`) ran
with its bundled default rules, `--log-opts="--all"`, and `--redact`. Its
synthetic-fixture check detected a generated disposable private key and exited
nonzero, proving the scanner was active. The all-history scan covered 72
commits and the exported `main` candidate directory scan covered the intended
tracked source tree. The resulting reports were reduced to finding type, path,
line, and commit metadata before they were retained as evidence.

The history scan returned one `generic-api-key` alert at
`frontend/src/model.ts:55` in commit `dcebe447`; the candidate-tree scan
located the same expression at line 58. Manual review verified it is the
`portfolioKey` local-storage key constant, not a credential. This is an exact
proposed allowlist candidate only: rule `generic-api-key` for that constant,
pending a separately reviewed scanner configuration change. Do not suppress
broader matches for that rule.

Manual review covered the tracked public-facing documentation, deployment
workflow/configuration, environment examples, and committed visual assets. The
asset review found Samurai branding only; it found no person or customer data.
The documentation/configuration review found no known-key-pattern file, but it
did find deployment and account identifiers in the deployment material. Those
identifiers are not credentials, but a public repository should replace them
with scoped placeholders or move operational detail to a restricted runbook
before any visibility change. This document deliberately does not repeat them.

## Coverage still blocked

| Surface | Result | Consequence |
| --- | --- | --- |
| Git LFS inventory | A temporary official Git LFS v3.8.0 macOS arm64 binary, verified against the release SHA-256, ran `git lfs ls-files --all` on a fresh seven-ref mirror. It exited 0 with zero LFS objects. | Complete for the audited refs; no LFS object existed to fetch or secret-scan. Rerun after any new ref is introduced. |
| Releases, release assets, and Actions artifacts | The configured GitHub CLI credential is invalid. The GitHub API is reachable outside the sandbox, but anonymous repository, release, and Actions-artifact requests returned 404; no private artifact was downloaded. | Provide a read-only GitHub credential with repository and Actions metadata access, inventory release assets/artifact names and retention, then scan only authorized downloads. |
| Actual repository visibility | Not queried successfully, and no change is authorized. | After explicit authorization only, use `gh repo view OveRide-Phoenix/team-samurai --json visibility` and record the result. |
| Evaluator access | Evaluator Google identities/group, access period, removal owner, and explicit IAM authorization are absent. The excluded second-account live test was not performed. | Obtain organizer/user supplied identities, a least-privilege expiry/removal schedule, and explicit access approval. |
| Signed-out public links | No public repository, deck, or video link is authorized or available to test. | After approval, test each published link signed out; a restricted application redirect is the expected result. |

Because those surfaces are incomplete, this audit is not evidence that the
repository may be published or that an evaluator can access the application.

## Proposed external changes, pending explicit approval

1. Complete the blocked inventories above and review every release asset and
   retained Actions artifact before exposing repository content.
2. Produce a curated public documentation set. Remove or replace cloud project,
   service, account, identity-provider, and deployment-specific identifiers
   from public-facing operational documentation. Keep actual secrets out of
   source and do not rewrite history unless a verified exposed credential and a
   separate destructive authorization require it.
3. Choose and approve the repository visibility, exact public materials, and
   release owner. Do not infer that a source-code repository must be public for
   the competition.
4. Keep the application IAP-protected. Grant only organizer/user-supplied
   evaluator identities or an approved Google group access to the frontend IAP
   resource, set a documented end date, then remove that grant on schedule.
   Do not grant broad public application access. The backend's existing
   application-JWT boundary remains unchanged.
5. After authorization, verify repository visibility and every public link
   signed out. Separately verify the restricted application redirects signed
   out and provide evaluator sign-in instructions. This does not require or
   claim a second-account live isolation test.

## Required evaluator inputs

- Evaluator email addresses or an organizer-managed Google group.
- Approved access start/end time, removal owner, and confirmation method.
- Explicit authorization for any GitHub visibility change, IAP IAM grant, link
  publication, upload, or submission.
- A read-only GitHub credential or authorized operator for release and Actions
  metadata inventory.
- The list of repository, deck, video, and prototype URLs intended for public
  evaluation.

## Reproducible evidence

| Scenario | Invocation | Binary observable | Captured artifact |
| --- | --- | --- | --- |
| Scanner self-test | `gitleaks dir --redact --report-format json` over a disposable generated private-key fixture | Exit `1`; exactly one `private-key` finding with a redacted report | `.omo/evidence/readiness/task-13/scanner-self-test.json` |
| Reachable-history scan | `gitleaks git --log-opts="--all" --redact --report-format json` over the disposable remote mirror | Exit `1`; one reviewed `generic-api-key` false positive at the path above | `.omo/evidence/readiness/task-13/remote-history-gitleaks.json` |
| Intended public tree scan | `gitleaks dir --redact --report-format json` over an archive of remote `main` | Exit `1`; same reviewed false positive in the candidate tree | `.omo/evidence/readiness/task-13/public-candidate-gitleaks.json` |
| Remote-ref and object audit | Mirror clone/fetch, `git for-each-ref`, `git fsck --full --no-reflogs`, and `git count-objects -vH` | Seven refs recorded; fsck exit `0` | `.omo/evidence/readiness/task-13/remote-refs.txt`, `git-fsck.txt`, `remote-object-inventory.txt` |
| Git LFS inventory | Verified temporary Git LFS v3.8.0 running `git lfs ls-files --all` on a fresh remote mirror | Exit `0`; zero LFS objects across seven refs, so no object download/scan was needed | `.omo/evidence/readiness/task-13/lfs-audit.md`, `lfs-inventory-v3.8.0.txt`, `lfs-fresh-remote-refs.txt` |
| Release/Actions inventory | `gh release list` and unauthenticated GitHub REST requests | CLI/API authorization unavailable; coverage blocked | `.omo/evidence/readiness/task-13/gh-release-list.txt`, `github-api-inventory.txt` |
| Manual artifact/configuration review | Tracked-file inventories, known-key-pattern scan, identifier review, image dimensions, and visual inspection | No known-key-pattern file; deployment identifiers require curation; reviewed image is branding only | `.omo/evidence/readiness/task-13/intended-public-inventory.txt`, `config-and-automation-inventory.txt`, `manual-known-secret-pattern-files.txt`, `manual-identifier-hits.txt` |

The evidence reports contain redacted scanner output and finding type/path only;
they do not contain credentials or private artifact downloads.
