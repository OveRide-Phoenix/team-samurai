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
