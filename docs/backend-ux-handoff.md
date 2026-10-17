# Backend and UX flow handoff

Updated 14 October 2026.

The next priority is to decide the founder UX flow by working through the backend and Agno workflow contracts. Preserve the accepted visual direction and use the existing panels to show real company state. Start with the first company created from the intake form; custom customer-created panels can follow later.

## Accepted UI baseline

- Home shows the original company-name intake and saved company tiles. Preview Home navigation returns to this actual portfolio without discarding company data.
- Company has Researcher, Strategist, Verifier and Sales workflow filters, with no Overview button. No selection shows all panels and general chat; one selection focuses its conversation; multiple selections use general chat with the selected panel groups.
- The full dashboard is the default. The floating chat bar opens panels on the left and chat on the right with a gentle spring; closing restores the dashboard. Mobile shows the conversation in the content area.
- New workflow groups append in selection order. Masonry fills gaps, existing cards stay mounted, and incoming/outgoing cards use the shared 850 ms page fade. Preserve selections, disclosures, sandbox inputs, conversation drafts and cancellation.
- The core declarative panels are Company brief, Research evidence, Offer, Pricing, Delivery plan and Prospects. Verifier also has an evidence-review panel. Keep the interactive controls and Samurai styling.
- UI search and its keyboard shortcut are removed from Home, headers, prospect cards and composed tables. Keep the workflow and prospect filters. The plus beside Pinned and the composer/header controls provide panel creation; the duplicate sidebar footer button is removed.

## Current backend boundary

The four UI areas are scoped entry points to the existing owned Samurai parent and its internal workflows. They are not four newly independent deployed services. `team_area` is the sole accepted forwarded navigation property; identities, state, dependencies and expanded permissions remain rejected.

The current company journey supports `brief`, `research`, `strategy`, `plan` and `verify` stages. New companies default to brief. Area/stage guards reject another area's work or missing upstream prerequisites before execution. Verification reads existing artifacts without rerunning upstream stages. Sales is restricted to sales drafts with the existing evidence/verification prerequisites; nothing is sent or published.

Topic discipline uses parent instructions plus a bounded suggested handoff. The execution guards are deterministic, but live Gemini adherence to the conversational topic boundary has not been established by this change. A suggested switch opens a draft and does not submit it automatically.

## Decisions to make through backend work

1. Define the exact first-company flow: required intake answers, follow-up questions, the initial brief, and the first decision offered to the founder. Keep brief-first creation; do not generate every stage on entry.
2. Define each workflow's input, output, goal, completion, blocked and failure states. Decide whether separate callable Agno workflows are needed or whether scoped stages on the existing shared workflow are sufficient.
3. Decide where the founder reviews or approves work before the next stage. Distinguish a local review/checklist click from backend authorization or verified evidence.
4. Decide when weak evidence stops progression, what clarification or evidence is requested, and how the founder returns to Researcher. Keep sources, uncertainty, conflicting claims and revision lineage visible through the panel contract.
5. Specify handoffs for off-topic requests and missing prerequisites: destination, explanation, retained company context and draft request. Preserve the chosen general-chat behavior for zero or multiple workflow selections.
6. Specify the must-have panels for each state, when they first appear, how revised results replace current views, and what stays visible in chat, Company and Pinned. Do not use mere panel existence as proof that a backend stage is ready or approved.
7. Have the backend expose the canonical next action and its eligibility/reason once the flow is agreed. Replace frontend inference from artifact presence with this contract, retaining owner checks, single-run behavior, cancellation and reload recovery.

## Start here

- [`backend/src/samurai/team_areas.py`](../backend/src/samurai/team_areas.py): accepted scope, execution guards and suggested handoffs.
- [`backend/src/samurai/parent.py`](../backend/src/samurai/parent.py): owned company binding, parent tools and stage invocation.
- [`backend/src/samurai/company_workflow.py`](../backend/src/samurai/company_workflow.py): stages, canonical state, evidence gates and verification.
- [`frontend/src/agentos.ts`](../frontend/src/agentos.ts): backend events and artifact-to-panel mapping.
- [`frontend/src/App.tsx`](../frontend/src/App.tsx) and [`frontend/src/teamAreas.ts`](../frontend/src/teamAreas.ts): current navigation, conversations, panel groups and next-stage UI.
- [`generative-ui.md`](generative-ui.md): rendering and sandbox boundaries.

Work through one concrete company scenario before broadening the flow: intake → brief → requested research → evidence decision → reviewed offer/pricing → delivery planning → verification → eligible sales preparation. This is a scenario to agree and validate, not permission to silently run the entire journey. Exercise a missing-input case, unsupported evidence, an off-topic handoff, cancellation and reload as well as the successful path.

## Validation and limits

Local verification passed: frontend typecheck, 100 Vitest tests and the production build; 40 production-server tests and 4 Sites tests; 179 backend pytest tests, Ruff lint/format checks and basedpyright. Desktop/mobile rendering and the relevant panel/navigation controls were exercised in Chromium. Backend scope and workflow tests use deterministic local models.

No paid provider run or deployment is part of this UI/handoff pass. Do not treat sample panels or passing fixture tests as proof of grounded research, topic discipline with Gemini, customer demand or a finished business journey. Keep the backend stopped outside explicitly authorized live testing, preserve private configuration/data, and agree the UX decisions before implementing the next backend change.


## Canonical actions integration — 16 October 2026

The company summary now returns `next_action` and a bounded `actions` list. Each
entry names an operation, stage, team area, founder prompt, eligibility and a
blocked reason. `company_actions.py` derives these from canonical artifacts and
reuses the workflow's source-support/conflict checks and verified launch-input
guard. A draft-only offer can proceed to delivery planning; an incomplete brief
cannot offer Research. A later failed review revokes an older successful review's
launch eligibility. Execution admission, membership, immutable approvals and
worker ownership remain the authorization boundary.

The frontend refreshes the owned company snapshot after terminal runs and on
reopening, persists action metadata and the current revision/hash together, and
disables actions while refreshing or when stale. Explicit action controls prepare
a draft in the designated area; the founder sends it. Ordinary chat stays
read-only. Sales, Builder, Marketing and metrics actions carry their distinct
operation scope. Durable `verify` approval now reaches the verification-only
workflow. Launch result conversion uses the same validated model-dump boundary
as the other parent results.

Provider-free local evidence: a real Chromium flow used intake, brief, Researcher,
Strategist, delivery, standalone verification and Sales through the actual
OpenUI/React UI, CopilotKit, development proxy, AG-UI, claimed native worker,
PostgreSQL and Redis. Canonical readback showed eight contiguous artifacts;
Sales remained draft-only. Preference and revision-8 synthetic scenario writes
succeeded; saved results, actions and the scenario recovered after reload.
Desktop and mobile/dark layouts were inspected. The isolated test schema,
credentials, file storage, browser tab and temporary servers were removed.
The existing user companies and preview tab were preserved.

The process regression additionally exercises Builder, Marketing and supplied
metrics with canonical receipts and native event replay. Research/fetch outputs
and role responses in these tests are deterministic; every Gemini invocation
entry point is blocked. This is not live Gemini/Search, topic-adherence, demand,
production deployment or cloud-recovery evidence. Remaining full-goal gates
include editable clarification/metrics replies, weak-evidence recovery, the final
whole-app audit, and up to three provider-backed journeys after an aggregate
spend ceiling and effective controls are confirmed. No paid call was made here.


### Edited approvals and current inputs — 16 October 2026

Owned summaries now include optional `current_artifact_ids` (null when unknown).
Snapshots retain all artifact versions; current IDs identify the latest outputs
whose upstream inputs have not subsequently changed. The UI validates IDs
against the matching snapshot and marks earlier downstream panels as historical.
Eligibility, handoff prerequisites and launch validation use current inputs; an
amended brief requires downstream work again. Metrics retain their own supplied
provenance and do not become customer validation.

OpenUI reply drafts display their approved operation. Editing retains only that
operation for the same company, area and revision; clearing it restores read-only
chat. Approval is consumed on submission and remains independently checked by
the backend. Weak or conflicting research offers Research again; immutable
approval-revision lineage prevents resumed attempts from repeating saved Search
work, including a saved insufficient-evidence result.

Provider-free browser proof saved an edited INR 75000 budget, read it back at
revision 2 and recovered it on reload. Native process proof rebuilt the journey
after a brief amendment through revision 17 while retaining original history.
Neither test invoked Gemini, Search or public source fetches. The user's total
live-test allowance is INR 100-200; INR 100 is the conservative working limit,
with paid tests still gated on effective aggregate cost control.


Measurement entry now uses a registered OpenUI two-step form: the actual value
and unit, then the source label and time window. It rejects non-finite/missing
values and invalid or reversed dates, prepares a readable overview-area request
with metrics-only approval, and leaves final submission to the founder. Local
browser checks confirmed the invalid-date error and corrected review draft on
desktop and mobile in both themes. That form-to-draft check did not run a model;
the native process regression separately covers supplied-metric persistence.

The current full provider-free PostgreSQL/Redis run recorded 569 passes and three
failures in existing tight timing tests. Those same three passed unchanged on
an isolated rerun (2.34 seconds); the full run is not reported as clean. Ruff,
strict basedpyright, 176 frontend tests and production build passed. UI file
upload/download preserved exact bytes, and local schedule creation/disable
succeeded. No scheduled execution or paid provider test is established here.


The measurement form has now been submitted through the actual local OpenUI,
proxy, AG-UI and claimed worker path with deterministic parent/Analyst fixtures.
Canonical readback at revision 2 retained exactly 12 leads, the supplied source
label and UTC window, `founder_supplied` provenance and no trusted connector
receipt. The normal next action remained Research. This extends the earlier
form-to-draft check; it still does not establish real-model parsing.

Saved launch drafts and analysis keep their existing evidence-kind storage and
full validated provenance, but use the OpenUI WorkDraft renderer for short
reading steps. The new reader uses the same artifact schema as the transport;
it does not relax HTML, source, measurement or connected-receipt validation.
Kalyan's fixed platform evaluator also passed 40 checks, with zero skips and
provider calls. Fresh remote main still matches HEAD 8d14d87.


Scoped handoff browser acceptance found and repaired missing frontend run-origin
tracking and cross-run handoff deduplication. Every submitting/running/terminal
notification carries its originating area. Owned saved metadata restores older
misfiled assistant replies only for the matching run. Handoff replay is
deduplicated within that run, while another founder request gets its own reply.
The browser confirmed three visible native handoffs, exact request retention on
Open Strategist, no automatic execution, blocked missing Research prerequisites,
and unchanged revision/hash. Frontend 188 tests pass.

The intermittent canonical-parent binding failure was captured and repaired.
The actor, company and child identities matched, but recovery selected revision
8 over canonical revision 9 using whole-second update timestamps. Parent-cache
upserts now prefer the highest accepted revision, so ties and old-intent retries
cannot restore an earlier accepted binding. A real PostgreSQL regression failed
before the repair and passes afterward; ownership and revision guards remain.

The final full provider-free backend run passed 574 tests with zero skips
(211.00 s), including native queue, persistence and cancellation checks. Test
subprocesses explicitly default queue execution off instead of reading that flag
from a private local .env; native queue fixtures still enable their real worker.
Ruff, formatting and strict basedpyright pass. Frontend 188 tests, typing and the
production build pass; existing dependency-comment/chunk warnings remain.

Actual browser regression also confirmed that a late-arriving brief settles
before utility panels, and filter hide/reveal preserves its reading step.
Desktop and mobile card geometry has no overlaps or horizontal page overflow.
The layout screenshots and geometry remain local UI evidence. On 17 October the
user accepted sequential usage metering instead of a guaranteed hard cost cap.
Three real company tests then ran: all briefs persisted; RepairLoop and ShopLedger
saved research but remained evidence-gated; TiffinLoop Research errored. Its false
COMPLETED receipt was reproduced and repaired in shared streamed-worker dispatch:
when Agno omits the final RunOutput after failure, use the saved terminal output.
All 31 parent tests and the two real native-worker success/failure regressions pass.
The final full provider-free backend suite passed 576 tests with zero skips
(221.33 s); Ruff, formatting and strict basedpyright pass.

A real OpenUI measurement submission also completed through Gemini and Analyst,
retaining exactly 12 synthetic QA leads, dates/source and founder-supplied status
at RepairLoop revision 4. The user-authorized targeted TiffinLoop retry then completed on its first attempt
and saved Research at revision 3. All 16 provider responses were metered, with
eight Search queries and a conservative INR 16.71 estimate; actual invoice
settlement remains unverified. Paid services are stopped. Do not claim successful
provider progression through Sales or a diagnosed initial Research exception.
