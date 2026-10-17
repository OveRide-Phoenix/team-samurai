# Full customer-flow integration and three bounded live tests

User objective: make the whole app's customer journey work, integrate Kalyan's
handoffs and changes, then run up to three live tests without exceeding cost.
This is not complete after a successful brief or a fixture-only dashboard.

Requirements and proof:
- Refresh remote main and inspect all handoffs; preserve dirty UI, company data,
  canonical membership, worker ownership, revision and evidence guards.
- One real founder journey: company/name + intake/clarification -> saved brief ->
  explicit research -> supported evidence decision -> offer/pricing -> delivery
  plan -> verification -> eligible sales preparation. Retain draft-only external
  actions. Builder/marketing drafts and supplied-metrics analysis remain usable.
- Server-owned action eligibility replaces panel-presence guesses. Missing input,
  insufficient/adjudicated evidence and stale/foreign access stop honestly.
- Scoped handoffs retain company, request and drafts, do not silently execute or
  repeat upstream stages. All explicit UI controls carry bounded approval.
- Company/Chat/OpenUI reading steps, edits, latest artifact replacement, pinning,
  filters, drafts, cancellation, receipts, replay and reload work together.
- Founder files/context, learning, scenarios and allowlisted schedules work with
  current canonical revision/hash; preserve existing contracts and provenance.
- Provider-free tests exercise the actual authenticated proxy + AG-UI + native
  worker + PostgreSQL/Redis path, not only SQLite agents. Cover success, missing
  input, weak/conflicting evidence, handoff, cancellation and restart/reload.
- After these gates pass, test up to three complete founder scenarios with real
  Gemini 3.5 Flash-Lite, Search only in Researcher, and no outreach/publication.
  Reserve and enforce a confirmed aggregate monetary ceiling before calls,
  include thinking, prompts/history, retries and grounding. No paid request yet:
  the user confirmed INR 100-200 total; use INR 100 conservatively. Three is a maximum.
- Keep sanitized receipts, screenshots and a requirement-by-requirement final
  audit. Do not infer deployment or public customer readiness from local tests.
  Stop task-started provider services outside testing; do not push/deploy.

Initial verified gaps:
- Durable ApprovedStage lacks verify even though company_workflow supports a
  verification-only stage. Its UI action currently has no runnable approval.
- UI next-stage inference relies on panel presence; canonical eligibility and
  blocked reasons requested in backend-ux-handoff are not yet exposed.
- Ordinary chat is intentionally read-only, so explicit work and handoff actions
  need complete bounded approvals, including sales/drafts and metrics.
- Founder-operation revision/hash props can lag a newly accepted chat artifact.
- Current model call/output/deadline caps are not an aggregate monetary ceiling.

Working method: use Ponytail, preserve Kalyan's guard implementations, inspect
installed Agno 3.1.2 APIs, make focused shared fixes and test actual boundaries.
Required OMo and Agno skills are not available in this session; do not claim use.


Progress, 16 October 2026:
- Fresh remote main matched local HEAD 8d14d87 (0 ahead/0 behind); no pull merge,
  push, deployment or existing company mutation.
- Repaired durable verify admission and the shared launch-result conversion
  which failed after saving a Sales draft. Added real-worker regressions.
- Canonical summary actions replace live panel-presence inference; current
  snapshot revision/hash now reaches operations. Missing briefs, unadjudicated or
  conflicting evidence, stale/running state and latest failed review remain gated.
- Actual provider-free browser journey completed to Sales at revision 8, then
  saved learning and a pinned synthetic scenario (800/1000/1200 from supplied
  assumptions), and recovered state on reload. No Gemini/Search/public fetch.
- PostgreSQL/Redis regression: 48 passed with zero skips, covering native jobs,
  cancellation/recovery/ownership, five journey stages, three draft workflows,
  supplied metrics, receipts and replay. Evidence in ignored
  .omo/evidence/full-customer-flow/{browser-journey,full-customer-journey}.json.
- Frontend 171 tests, typecheck, production build, 62 server tests and 4 Sites
  checks passed. Desktop/mobile dark rendering checked. Existing chunk warning.
- Follow-up audit fixed incomplete-brief Research eligibility and older verified
  review overriding a later failed review; focused workflow/draft tests passed.

Still unproven / do not mark the goal complete:
- Three real Gemini journeys, grounded Search behavior, source availability and
  actual model topic/handoff adherence. Zero paid calls in this goal so far.
- User authorized INR 100-200 maximum total for three live tests. Use INR 100
  conservatively. Zero paid calls so far. Installed SDK native Search has no
  per-request query-count cap; model/output caps do not bound Search spend.
  Official billing documentation also warns of around ten minutes of spend-cap
  and prepaid-balance latency. No paid calls until the cost boundary is resolved.
- Editable follow-up replies and supplied-metrics capture must keep explicit
  operation approval usable without granting ordinary chat write authority.
- Recovery from weak/conflicting evidence and revising downstream decisions needs
  a founder-facing repair path; do not silently bypass Kalyan's evidence guards.
- Builder/Marketing/Sales/analysis outputs still use generic evidence presentation;
  improve their readable draft sections without suggesting evidence support.
- Full remaining operations/upload/schedules and missing-input/handoff scenarios
  need current real-surface proof, followed by the complete requirement audit.

Final checks for this iteration: backend 419 passed / 150 environment-gated
skips, Ruff and full basedpyright clean. The separate real PostgreSQL/Redis run
had 48 passes with no skips. Frontend 171 passes, typecheck/build, 62 Node server
and 4 Sites checks passed. Native Search/Gemini is still untested in this goal.
Temporary browser fixture cleaned up; Samurai PostgreSQL/Redis stopped; the
user-owned port-4173 frontend and browser tab were retained. Goal remains active.


Follow-up progress, edited replies and current-input recovery:
- OpenUI composer visibly retains the exact approved operation while its draft is
  edited; Clear work approval returns to ordinary read-only chat. Company, area
  and revision changes discard the approval. No broader JWT/tool authority.
- Actual provider-free browser submission changed the brief budget to INR 75000.
  Canonical readback found exactly two intake versions at revision 2; latest
  budget survived reload. Desktop/light and mobile layouts inspected; no
  horizontal overflow. Screenshots are ignored local visualizations.
- Current artifact IDs distinguish historical outputs from outputs whose inputs
  are current. A brief/research/offer/plan revision invalidates downstream
  eligibility while preserving immutable history. Historical panels show an
  Earlier version note; launch and handoff guards use current prerequisites.
- Weak/conflicting research exposes Research again, without bypassing evidence
  gates. A fixed approval revision prevents a resumed worker from repeating an
  already saved research request, including insufficient-evidence results.
- Native workflow tests: 41 passed. Frontend: 173 passed, production build passed
  with existing chunk-size warnings. Expanded isolated PostgreSQL/Redis process
  regression passed through 17 revisions, including all three draft workflows,
  supplied metrics, brief amendment, downstream rebuild and wrong-area handoff.
- Full provider-free PostgreSQL/Redis suite and strict typing are running again.
  Remaining gates above still apply; this is not Gemini or deployment proof.

- Added a two-step OpenUI measurement entry using actual values, units, source and
  dates. It prepares a readable request with metrics-only approval and no raw
  JSON. Browser checked reversed-date rejection, corrected review draft and both
  mobile themes. No final analysis request was sent from that form. Frontend
  176 tests pass. Full backend run has failures to diagnose before acceptance.

Final verification for this iteration:
- Full provider-free backend with real isolated PostgreSQL/Redis: 569 passed,
  3 failed, zero skips (669.55 s). Failures were the existing job-lock race exit
  deadline, blocked-resolver cancellation at 0.25 s, and two-request TLS budget
  at 0.45 s. All three passed unchanged together in 2.34 s after overlapping
  browser/build fixture work stopped. Do not describe the full run as clean.
- Ruff and full strict basedpyright: clean. Frontend 176 passed and final
  production build passed; existing dependency-comment/chunk warnings remain.
- Actual UI uploaded a 117-byte generated test note, downloaded matching bytes,
  saved a once-only local workspace-review schedule and disabled it. These
  checks used only isolated local state; the schedule was never executed.
- Browser fixture stopped and its schema, keys and storage removed. User-owned
  frontend/tab retained. Paid calls remain zero; INR 100 is the conservative
  budget, but native Search's aggregate hard-cost bound is unresolved.
- Still required: provider-backed topic/handoff/evidence behavior and three live
  journeys, readable launch-draft/analysis presentation, measurement form through
  the real parent model, and final whole-app acceptance audit. Goal stays active.


Next continuation progress:
- Previous turn classified as progress: edited approvals, current-input lineage,
  measurement entry and authoritative local/browser regression evidence.
- WorkDraft OpenUI reader now presents build, marketing, sales and analysis as
  short Back/Next steps. Full payload/provenance stay in the existing schema and
  stored panels; malformed/HTML/forged connected measurements still fail closed.
  Default metrics preserve tiny finite values instead of rounding them to zero.
- Frontend 179 tests and typecheck pass. Desktop/mobile in both themes checked;
  actual filter toggling retained Sales step 4 of 5. Preview is illustrative.
- Kalyan's tracked platform evaluator passed 40 cases with zero skips, errors,
  failures and provider calls. Ignored evidence: platform-evals/summary.json.
- Fresh git fetch: HEAD and origin/main still match at 8d14d87; no merge/push.
- Actual measurement form -> proxy -> AG-UI -> claimed native worker -> canonical
  revision 2 -> new WorkDraft reader passed. Exactly 12 leads, source and dates
  retained as founder_supplied, with no connected receipt. Ignored evidence:
  browser-native-metrics.json. Parent/Analyst are deterministic fixtures.
- Paid calls remain zero. Native Search query cost has no enforceable per-call
  bound in installed SDK config; Google spend controls have settlement latency.
  The hard aggregate cost gate is still unresolved and is not presented as fixed.

- Actual scoped browser testing found two presentation defects: live run origin
  was omitted from run notifications, and identical handoffs were deduplicated
  across separate requests. Fixed the shared transport/state path. Verified
  saved native metadata can repair a misfiled reply, fresh repeated requests
  each receive a visible reply, replay stays idempotent, and Open Strategist
  retains the exact unsent request while prerequisites stay blocked. Canonical
  revision 2 and its state hash stayed unchanged after three handoff requests.
  Evidence: browser-handoff.json and task-owned screenshots. Frontend 188 pass.
- A subsequent complete worker regression hit one HTTP read timeout after a
  logged `parent session binding is not canonical` error at the final off-area
  request. Four further quiet reproductions passed (16.58-16.68 s each), so no
  failure-state snapshot was captured. This intermittent binding failure is
  unresolved; do not treat the passing repetitions as a root-cause repair.
  Existing binding/ownership guards remain unchanged. No paid calls made.

Final checks this continuation: frontend 188, server 62 and Sites 4 pass; final
production build passes with existing dependency/chunk warnings. Backend Ruff
and strict basedpyright pass; tracked platform evaluator 40/40, zero skips.
The complete 17-revision worker scenario passed four quiet repetitions after
one canonical-binding failure; intermittency remains unproven, not repaired.
Temporary browser harness/schema/keys/storage removed; test tabs closed,
viewport reset, Samurai Redis/PostgreSQL stopped, user frontend retained.
Paid Gemini/Search calls still zero; goal remains active.

Visual evidence qualification: samurai-native-metrics-dashboard.png was taken
immediately after a viewport/filter transition and contains overlapping card
positions. Do not deliver it as settled-layout acceptance. Retake the native
dashboard after the spring settles and inspect geometry before final approval.
The separate draft-preview desktop/mobile screenshots were inspected; reading
steps and canonical metric values were also verified through browser state.

Captured and repaired the intermittent parent-binding failure:
- Failure-only fixture trace established matching actor/session/run/company/child
  identities, but parent revision 8 against canonical revision 9. Sanitized proof
  is in binding-guard.json; no guard was bypassed.
- Recovery chose the newest whole-second updated_at, so tied stages or an older
  intent retry could win. Shared SamuraiPostgresDb.upsert_session now orders by
  accepted_revision first, with null legacy revisions last and timestamp second.
- Real PostgreSQL regression reproduced revision 1 overwriting revision 2 before
  the fix. Both tied timestamps and a later stale retry pass after it. Relevant
  persistence/fence/native-process suite: 35 passed, zero skips.
- Ruff and strict basedpyright passed. First full run: 571 passed, three subprocess
  startup failures caused by private QUEUE_ENABLED=true loading from backend cwd.
  The same three passed with QUEUE_ENABLED=false (8.15 s). Shared test isolation
  now sets that default; native queue tests retain explicit queue configuration.
  A complete rerun is in progress; do not report it as passed until terminal.
- No paid Gemini/Search calls have been made in this goal.

Final verification for the captured-binding repair:
- Full real PostgreSQL/Redis provider-free backend: 574 passed, zero failures and
  zero skips, 211.00 s. All earlier timing cases passed without relaxed limits.
- Ruff, formatting, strict basedpyright clean; frontend 188 tests, typing and
  production build pass. Existing dependency/chunk warnings are unchanged.
- Native browser company intake and measurement review completed again. Supplied
  12 leads stayed explicitly founder-supplied, not connected or verified evidence.
- Settled-layout QA discovered utilities retaining initial arrival order ahead of
  the generated brief. Shared reveal completion now restores requested order; a
  fresh UI company proved brief-first on desktop and mobile. Filtering Sales on
  and off retained brief step 2. Geometry assertions found no overlaps/overflow.
  Sanitized proof: settled-layout.json; brief-first screenshots are local only.
- Asked the user whether the strict paid ceiling should remain (tests pending) or
  may become sequential usage metering with INR 100 stopping target and disclosed
  inability to guarantee INR 200 with native Search. No answer/approval inferred.
  Paid Gemini/Search calls remain zero. Full objective remains incomplete.

Final local acceptance audit and cleanup:
- Founder entry/short intake, brief reading/editing, bounded stage actions, scoped
  handoffs and per-company drafts: native UI/process proofs plus 188 frontend
  regressions. Latest browser retest confirms business-first settled card order.
- Canonical actions, evidence/lineage/current-input gates, all three draft kinds,
  founder-supplied analysis, isolation, cancellation, receipts, replay and recovery:
  final 574-test provider-free backend suite passes with real PostgreSQL/Redis.
- Files, learning/scenarios and allowlisted schedule create/disable retain prior
  actual native browser proofs and current passing API/contract tests. Scheduled
  execution, external publication/outreach and cloud deployment are not claimed.
- Final production server 62/62 and Sites build-contract 4/4 passed.
- Temporary UI tab closed; harness exited 0 and removed its isolated schema, keys
  and storage. Samurai Redis/PostgreSQL stopped, preserving volumes. User-owned
  port-4173 frontend/tab remain untouched. No push, commit or cloud changes.
- The remaining real-provider gate has recurred across more than three goal
  continuations. All currently independent local checks are complete. The user
  must choose whether to retain the strict INR 200 ceiling or explicitly accept
  the disclosed sequential-metering risk; the pending question is not approval.
  Paid calls remain zero and the whole goal cannot be marked complete.

17 October live acceptance (user explicitly accepted sequential metering risk):
- Three real Gemini companies ran sequentially: RepairLoop, TiffinLoop, ShopLedger.
  All three briefs completed through authenticated AG-UI and claimed workers.
  Research used native Google Search only for Researcher. No provider substitutions.
- RepairLoop and ShopLedger saved raw and adjudicated Research (revision 3); their
  retained evidence did not qualify Strategy. No source/evidence guard was relaxed.
- TiffinLoop Research emitted RUN_ERROR and retained only its brief (revision 1).
  Its native receipt incorrectly said COMPLETED, exposing a streamed-error defect.
  Exact underlying Research exception was sanitized; do not claim its cause known.
- Actual OpenUI measurement form -> real parent -> Analyst -> canonical Analysis
  succeeded for RepairLoop at revision 4. Exact 12 leads, source and UTC window
  retained; explicitly synthetic QA input, founder-supplied and not market proof.
- Final ledger: 14 measured provider calls, 6 Search queries; conservative estimate
  INR 13.096053. No free Search assumed; bookkeeping INR 100/USD plus 18% reserve.
  Actual invoice/exchange/credit settlement unverified; no paid services running.
- Local VM/database time lagged Mac/current UTC by about 54 minutes. Automatic
  approval rejected a shared-VM clock change; user then approved, but clocks had
  already synchronized without manual action. No clock mutation was performed.
- Fixed the observed status defect in shared SamuraiParentAgent stream dispatch:
  Agno can omit final RunOutput after streamed validation errors; recover the
  retained terminal output for native-worker callers instead of inferring success.
  Direct regression failed before fix and passed after; all parent tests 31 pass.
  Real PostgreSQL/Redis HTTP regression plus full customer-worker case pass (2
  tests, 35.90 s), preserving native two-attempt ownership and cancellation guards.
  Full final provider-free suite is running; do not label all live journeys passed.
- Sanitized native results/usage/canonical snapshots: live-2026-10-17/summary.json.
  Three paid scenarios are exhausted for this iteration; no automatic paid retry.

Final 17 October handoff:
- User explicitly authorized one additional targeted TiffinLoop Research retry.
  Reused the same isolated company, real providers, repaired worker and cumulative
  meter. It completed on its first native attempt and saved Research at revision 3.
  The initial exception did not recur, so its exact cause remains undiagnosed.
- Final persisted states: RepairLoop revision 4 (brief, two Research versions and
  Analysis); TiffinLoop revision 3; ShopLedger revision 3. All three have real
  briefs and Search-backed Research. Evidence gates still require stronger support
  before Strategy; no offer, Plan or Sales output is claimed as live-verified.
- Final cumulative usage: 16 fully metered responses, 8 reported Search queries;
  INR 16.711998 conservative estimate. Actual invoice settlement not verified.
- After the streamed-error fix, full backend: 576 passed, zero failures/skips,
  221.33 s. Ruff, formatting and strict basedpyright pass. Existing frontend
  188 / server 62 / Sites 4 proofs remain applicable; no frontend source changed
  in this provider-test iteration. No paid calls after the approved targeted retry.
- Live host and frontend fixture exited 0; disposable credentials removed. Samurai
  Redis/PostgreSQL stopped with volumes retained; user port-4173 frontend/tab and
  Reporting services preserved. Isolated test data and sanitized evidence retained.
- Local integration and authorized bounded live-test work are complete. This is
  not three successful company journeys through Sales, a deployed release, or
  proof of customer demand. Future founder progression needs genuine evidence;
  no evidence, authorization or ownership guard was relaxed to manufacture it.
