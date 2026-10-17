# Software idea mentor handoff

Updated 17 October 2026.

Samurai now helps people validate and implement **software ideas**: apps, websites,
and software enhancements. The UX is organized around six aspects of one idea,
rather than company-building roles. The existing backend journey is retained.
This document supersedes the role/filter UX guidance in
[the historical backend handoff](backend-ux-handoff.md); that document's dated
backend acceptance records remain historical evidence.

## Product and aspect model

| Aspect | Frontend identity | Existing backend scope | Three checkpoints |
| --- | --- | --- | --- |
| Problem & demand | `research` | `research` | Customer & problem; Evidence of demand; Riskiest assumption |
| Market & alternatives | `market` | `research` | Existing products; Market & timing; A reason to switch |
| Sales & distribution | `sales` | `sales` | First buyers; Channels & message; Willingness to pay |
| Product & technology | `strategy` | `strategy` | Minimum useful product; Technical requirements; Data & quality |
| Budget & resources | `resources` | `strategy` | Build budget; Skills & capacity; Running costs |
| Validation & delivery | `verification` | `verification` | Experiment & decision; Implementation plan; Test, release & learn |

The catalog lives in
[`ideaAspectCatalog.ts`](../frontend/src/ideaAspectCatalog.ts). Relationships are
suggestions for sharing context, never prerequisites for opening an aspect or
discussing a topic. Budget and Sales remain accessible when technology is blocked.

Readiness is the user's assessment: green requires all three checkpoints to be
marked ready; one blocked checkpoint makes its aspect red; other states are amber.
This is not an AI success score or independent validation. Assessments and notes
save in the existing account-scoped browser cache. Notes are limited to 4,000
characters each. There is no new backend checkpoint storage.

## UX journey

Validation and improvement across all six aspects come first. Cofounder provides
the split map/chat layout; Samurai should challenge assumptions, propose tests and
iterate toward an evidence-based go/revise/stop decision. A filled map or manual
readiness light does not authorize building. Implementation follows a reviewed
validation decision and the founder's explicit choice through existing approvals.
This is mentor guidance; no new deterministic six-aspect approval gate is claimed.

Gemini must materially change the assessment: analyse the idea, interpret evidence,
challenge assumptions and revise recommendations. The six-aspect scaffold and UI
do not replace that reasoning. Marketing and sales content, including Instagram
concepts based on the validated audience and offer, is a follow-on capability.
It does not authorize publication, outreach or spending.

1. Home still owns idea creation and switching. Enter a name and software idea,
   then meet the mentor immediately. Customer, geography, budget, skills and milestone
   are optional at entry; unknowns remain null in the existing brief request.
   The same intake call returns an additive, optional `idea_analysis` containing
   a short assessment and up to eighteen bounded, unique draft starting points.
   No separate analysis service, model call or database migration is introduced.
2. Keep two views of the same workspace and conversation. Mentor shows pinned panels
   on the left; Idea map shows the graph on the left, with chat always on the right
   on desktop. Generated OpenUI panels still appear in chat and can be pinned.
   The recommended path is Problem → Market
   → Sales → Product → Budget → Validation, with three ordered questions per aspect.
   One registered OpenUI question appears at a time; the user answers in the existing
   composer. Guided questions, readiness choices, answer disclosures and completion
   actions use OpenUI. Ordinary mentor replies can be concise plain text, a useful
   structured panel, or both; do not force every answer into a UI component.
3. Intake drafts fill empty aspect notes, labelled as provided context or mentor
   inference. Founder edits and assessments win over autofill; no draft turns a
   node green. The guide skips filled starting points and asks the next real gap.
   Sending a guided answer saves its tagged question/answer locally and asks the
   existing live mentor for critical feedback without execution approval. On success
   it advances; failures/cancellation retain the answer and question for retry.
   Preview uses explicit provider-free fixtures. Readiness remains the user's assessment.
4. Every aspect remains accessible without prerequisites. Map clicks only highlight
   the selected card: chat history, active question, composer draft and scroll stay
   unchanged. Use the chat header's aspect mentor picker to explicitly change the
   next message's context, preserving the transcript and current composer text.
   Choosing a mentor does not send a message or approve work. **Ask freely**
   leaves the guide; the completed guide can prepare bounded answer excerpts for
   review with Samurai, which the user explicitly sends through the existing transport.

   Read-only mentor requests carry the chosen frontend aspect name as context,
   so Market and Budget remain distinct even when they share an existing backend
   scope with another aspect. General requests and explicitly approved operation
   text remain unchanged; no new wire scope or execution permission is introduced.
5. Saved workflow actions continue to prepare existing approved operations.
   Execution still follows `brief → research → strategy → plan → verify`, with
   existing evidence and approval guards. Sales, Builder and Marketer outputs
   remain reviewable drafts. Discussion can precede evidence; execution cannot
   bypass the existing guards.

The graph is live React buttons and SVG, not a screenshot or force-layout service.
Its compact layout responds to available component width, including beside the
mentor conversation. Full names remain in accessible labels when short labels are
shown. Keyboard focus, reduced motion and forced colors are supported.
Readiness lights stay inside the aspect boxes without visible status words; real
filled-question counts sit at the top right. Status remains in accessible labels,
hover titles and the legend. The separate numbered question
buttons above graph nodes were removed at the user's request; questions stay in chat.

## Compatibility boundaries

- Keep the existing five wire scopes: `overview`, `research`, `strategy`,
  `verification`, `sales`. `market` and `resources` are frontend identities only;
  translate them at the transport/approval boundary with `scopeForAspect()`.
- Keep six frontend draft/history identities distinct. Optional `message.aspect`
  and local `backendRun.aspect` retain the originating aspect through recovery;
  `area` retains the backend scope. Legacy messages remain available, including
  in the general conversation. Reopening through Shared ideas refreshes canonical
  panels while retaining each matching saved reply's identity and aspect.
  Do not rename or discard old saved data.
- Saved action IDs map to frontend owners through `actionAreas`: delivery plans,
  build drafts and measurement reviews open Validation; distribution drafts open
  Sales. Prepared approvals are bound to that frontend aspect, company and revision,
  while `approval.teamArea` retains the action's original backend scope (for example,
  delivery planning still executes in `strategy`).
- Internal company IDs, routes, API payloads, storage keys, artifact formats,
  specialist roles, ownership, revisions, hashes, cancellation and approval rules
  remain compatible. No database migration, service split or dependency was added.
- Problem and Market share research evidence panels. Pricing and deterministic
  scenarios appear in Budget. Offers appear in Product. Product plans, build
  drafts and analysis appear in Validation; sales/marketing drafts in Sales.
  Custom views retain their originating aspect. Existing panel controls and source
  lineage are reused. The chooser opens Pricing in Budget and Launch plan in
  Validation.
- Backend changes include the additive optional intake analysis contract, its
  persistence in the existing artifact, mentor/intake/action guidance and tests.
  Parent guidance permits independent discussion with labelled assumptions;
  deterministic stage eligibility and authorization remain unchanged. Do not
  replace these guards with the graph's user-assessed readiness.

## Implementation entry points

| Location | Responsibility |
| --- | --- |
| [`TeamNavigation.tsx`](../frontend/src/TeamNavigation.tsx), [`idea-aspects.css`](../frontend/src/idea-aspects.css) | Graph, icon cards, internal readiness lights, top-right counts and independent map selection |
| [`aspectState.ts`](../frontend/src/aspectState.ts), [`ideaAnalysis.ts`](../frontend/src/ideaAnalysis.ts) | Assessment validation, labelled draft autofill, preservation of founder edits |
| [`teamAreas.ts`](../frontend/src/teamAreas.ts), [`model.ts`](../frontend/src/model.ts) | Aspect/scope mapping, panel ownership, readiness, persistence and run-origin identity |
| [`App.tsx`](../frontend/src/App.tsx) | Navigation, separate drafts/history, existing composer and approved actions |
| [`aspectJourney.ts`](../frontend/src/aspectJourney.ts), [`OpenUIAspectGuide.tsx`](../frontend/src/OpenUIAspectGuide.tsx) | Ordered questions, local answer persistence and registered OpenUI conversation controls |
| [`OpenUIIdeaAnalysis.tsx`](../frontend/src/OpenUIIdeaAnalysis.tsx), [`Onboarding.tsx`](../frontend/src/Onboarding.tsx) | Direct entry to the mentor, welcome and six-aspect first pass |
| [`ThemedSelect.tsx`](../frontend/src/ThemedSelect.tsx) | Shared themed menus retaining form values, reset and disabled behavior |
| [`companyHydration.ts`](../frontend/src/companyHydration.ts) | Refresh shared-idea snapshots without losing saved conversation identity |
| [`team_areas.py`](../backend/src/samurai/team_areas.py), [`main.md`](../backend/src/samurai/prompts/main.md) | Independent software-idea discussion while retaining execution guards |
| [`company_actions.py`](../backend/src/samurai/company_actions.py), [`intake.py`](../backend/src/samurai/intake.py) | Existing action eligibility and intake with idea-facing wording |

Use [`DESIGN.md`](../frontend/DESIGN.md) for the current visual contract.
[`BACKEND_CONTRACT.md`](../frontend/BACKEND_CONTRACT.md) and
[`company_workflow.py`](../backend/src/samurai/company_workflow.py) remain the
backend contract and stage implementation references.

## Local verification — 17 October 2026

Localhost now opens the actual app at `http://127.0.0.1:4173/`. All developer
preview routes, their loader and simulated app transports have been removed.
Old query links fall through to the actual app. Test fixtures stay test-only;
legacy browser caches are retained but sample workspaces are not opened.

The acceptance scope is desktop only. TypeScript and 221 frontend tests in 23
files passed after preview removal. Six obsolete simulated-transport tests were
removed along with that implementation; real adapter, cancellation, recovery,
permissions and hydration regressions remain. The earlier production build and
66 proxy/Sites tests passed before removal; the MR review reruns current checks.
Backend Ruff, formatting, basedpyright and the focused parent/panel/agent tests
passed. Existing contract/workflow regressions also cover optional analysis
compatibility, unchanged legacy serialization and preserved evidence boundaries.

The earlier desktop visual review covered fifteen settled map, mentor-picker and
guided-question captures in both themes. The actual-app follow-up uses an isolated
real idea, the normal route, current Gemini replies and a pinned generated panel.
All six map nodes plus the center preserve the chat text, composer draft and scroll
in the real app. Actual conversation and filled aspect drafts survived reload.

### Bounded live Gemini test

Used a new isolated local workspace and the fictional software idea LessonLoop
(tutor scheduling and payment follow-up). The budget, skills and time constraints
were explicit test assumptions. PostgreSQL, Redis, authenticated local proxy,
native durable queue and `gemini-3.5-flash-lite` were used. Ten existing ideas kept
exactly their original canonical revisions and state hashes.

| Aspect | Live outcome |
| --- | --- |
| Problem & demand | Challenged switching demand and proposed a behavior-based interview and manual concierge test. The initial answer invented an unmeasured admin-time threshold; it was explicitly challenged. |
| Market & alternatives | One approved native Search research pass retained five source references but returned `insufficient_evidence`, with zero supported findings. Two completed comparison panels retained draft/assumption labels; follow-up removed speculative vendor prices and an invented switching threshold. |
| Sales & distribution | Discussed a low-cost recruitment channel and willingness-to-pay test. A second exchange corrected the initial fictional normal-price/discount suggestion. No outreach or payment occurred. |
| Product & technology | Recommended a zero-code concierge pilot; deferred auth, custom UI, database and integrations until value is tested. |
| Budget & resources | Assessed the test budget and capacity, then revised advice to keep the pilot manual and the cash cap unspent. Founder-time estimates remain assumptions. |
| Validation & delivery | Recommended **revise**, deferred software building and proposed provisional experiment criteria. A completed first pass did not produce a go signal. |

Intake completed with eighteen starting points, three per aspect. The final
canonical revision was 2: intake plus insufficient research. Ordinary mentoring,
comparison panels and follow-ups did not append business artifacts or execute
later stages. Fresh normal-route reload retained the transcript and aspect notes.

### Live failures fixed

- Gemini rejected the intake schema's redundant `maxItems: 18`. Eighteen known
  checkpoint IDs plus uniqueness already enforce the same bound. Removing only
  that provider constraint restored intake; boundary tests still reject a
  nineteenth duplicate.
- Agno's Gemini converter dropped the discriminated block catalog and object
  extra-field constraints. The panel declaration now uses supported `anyOf`/enum
  and passes the exact schema through Google's native `parameters_json_schema`.
  Parent function calling uses `validated`, which still allows ordinary text.
  Strict Pydantic validation remains unchanged; invalid/mixed block fields are
  rejected. The real table update completed after this correction.
- Mentor guidance now permits concise text, useful OpenUI, or both, and explicitly
  rejects fictional normal prices and silently converting a manual pilot to a build.

The complete diagnostic run included failed attempts and bounded retests: fifteen
parent turns, one approved Search pass and three tiny schema probes. Recorded
parent metrics total 131,714 input and 3,133 output tokens; child workflow token
metrics and exact billed cost were unavailable, so those totals are **not** the
complete provider bill. No bulk journey, strategy/build execution, deployment,
publication, outreach or paid acquisition was run.

## Review walkthrough

1. Open the actual local app and create an isolated software idea. Submit a clear
   idea; verify the immediate mentor welcome, first-pass drafts and unknowns.
2. Use the recommended Problem → Market → Sales → Product → Budget → Validation
   guide, or invoke an aspect from the chat header. Answer only through chat.
3. Switch Mentor/Idea map. Verify the same conversation and draft; selecting map
   nodes must only highlight them. Readiness lights remain inside cards with
   counts at the top right and no visible status words inside nodes.
4. Ask for ordinary text, a useful comparison panel and a correction. Pin a panel
   in Mentor and verify it remains after reload. Inspect both desktop themes.
5. Keep the existing execution approvals and evidence gates. An unsupported idea
   should produce critical next tests or revision, rather than a build go signal.

## Remaining limits

This is local live integration evidence, not deployment or validated customer
demand. Research retained source lineage but lacked supported factual claims.
Generated advice still needs scrutiny: comparative claims and numeric thresholds
can be overconfident despite draft labels. The human-reviewed six-aspect rubric
and real customer experiments remain essential. Filled notes/manual readiness
never replace evidence.

Checkpoint notes and assessments use browser persistence; server-synchronized
checkpoint collaboration is not implemented. Mobile work is deferred. Merge,
deployment, external outreach and publishing remain separate actions.
