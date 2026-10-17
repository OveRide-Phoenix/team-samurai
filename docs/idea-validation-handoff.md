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

1. Home still owns idea creation and switching. Enter the idea name and complete
   the existing required intake: software problem, customer, geography, budget,
   skills/resources, and milestone. Preserve the brief-first save behavior.
2. The idea map shows the named idea at the center and six accessible aspect
   cards. Curved spokes show the main hierarchy; faint dashed links show related
   aspects. Light/dark themes and the existing Samurai atmosphere are retained.
3. Selecting a card opens its three checkpoints, notes, related aspects and saved
   result panels. The overview button returns to the graph. Selection does not
   submit a request or run a workflow.
4. **Explore with mentor** prepares a question and saved notes in the existing
   composer. The user reviews and sends it. Each aspect has its own frontend
   conversation and draft; canonical idea context is shared.
5. Saved workflow actions continue to prepare existing approved operations.
   Execution still follows `brief → research → strategy → plan → verify`, with
   existing evidence and approval guards. Sales, Builder and Marketer outputs
   remain reviewable drafts. Discussion can precede evidence; execution cannot
   bypass the existing guards.

The graph is live React buttons and SVG, not a screenshot or force-layout service.
Its compact layout responds to available component width, including beside the
mentor conversation. Full names remain in accessible labels when short labels are
shown. Keyboard focus, reduced motion and forced colors are supported.

## Compatibility boundaries

- Keep the existing five wire scopes: `overview`, `research`, `strategy`,
  `verification`, `sales`. `market` and `resources` are frontend identities only;
  translate them at the transport/approval boundary with `scopeForAspect()`.
- Keep six frontend draft/history identities distinct. Optional `message.aspect`
  and local `backendRun.aspect` retain the originating aspect through recovery;
  `area` retains the backend scope. Legacy messages remain available, including
  in the general conversation. Do not rename or discard old saved data.
- Internal company IDs, routes, API payloads, storage keys, artifact formats,
  specialist roles, ownership, revisions, hashes, cancellation and approval rules
  remain compatible. No database migration, service split or dependency was added.
- Problem and Market share research evidence panels. Pricing and deterministic
  scenarios appear in Budget. Offers appear in Product. Product plans, build
  drafts and analysis appear in Validation; sales/marketing drafts in Sales.
  Custom views retain their originating aspect. Existing panel controls and source
  lineage are reused. The chooser opens Pricing in Budget and Launch plan in
  Validation.
- Backend changes are mentor/intake/action copy and topic guidance plus tests.
  Parent guidance permits independent discussion with labelled assumptions;
  deterministic stage eligibility and authorization remain unchanged. Do not
  replace these guards with the graph's user-assessed readiness.

## Implementation entry points

| Location | Responsibility |
| --- | --- |
| [`TeamNavigation.tsx`](../frontend/src/TeamNavigation.tsx), [`idea-aspects.css`](../frontend/src/idea-aspects.css) | Graph, icon cards, checkpoint marks, connections and responsive presentation |
| [`AspectReview.tsx`](../frontend/src/AspectReview.tsx), [`aspectState.ts`](../frontend/src/aspectState.ts) | Checkpoint controls, assessment validation, browser-local notes |
| [`teamAreas.ts`](../frontend/src/teamAreas.ts), [`model.ts`](../frontend/src/model.ts) | Aspect/scope mapping, panel ownership, readiness, persistence and run-origin identity |
| [`App.tsx`](../frontend/src/App.tsx) | Navigation, separate drafts/history, existing composer and approved actions |
| [`team_areas.py`](../backend/src/samurai/team_areas.py), [`main.md`](../backend/src/samurai/prompts/main.md) | Independent software-idea discussion while retaining execution guards |
| [`company_actions.py`](../backend/src/samurai/company_actions.py), [`intake.py`](../backend/src/samurai/intake.py) | Existing action eligibility and intake with idea-facing wording |

Use [`DESIGN.md`](../frontend/DESIGN.md) for the current visual contract.
[`BACKEND_CONTRACT.md`](../frontend/BACKEND_CONTRACT.md) and
[`company_workflow.py`](../backend/src/samurai/company_workflow.py) remain the
backend contract and stage implementation references.

## Verification and review walkthrough

Local implementation checks passed:

| Check | Result |
| --- | --- |
| `cd frontend && npm run check` | TypeScript and 197 tests in 19 files passed |
| `cd frontend && npm run build` | Passed; existing dependency annotation and bundle-size warnings remain |
| `cd frontend && node --test tests/sites-worker.test.mjs tests/production-server.test.mjs` | 66 tests passed |
| `cd backend && uv run pytest tests/test_team_areas.py tests/test_app.py tests/test_agui.py tests/test_panels.py tests/test_company_workflow.py` | 81 targeted provider-free tests passed |
| Backend Ruff, formatting and basedpyright | Passed |
| `git diff --check` | Passed |

Independent visual reviews passed the original 79-view aspect/intake packet and
the final 14-view graph refinement packet. The final packet covers three widths,
both themes, the map beside the mentor, keyboard focus and mixed readiness.
Measured graph nodes had no intersections or outside-canvas placement, with no
settled horizontal overflow. Screenshots and runtime logs are local QA artifacts,
not committed source or proof of a deployment. PR checks report CI separately.

For a provider-free review, use the existing development server at
`http://127.0.0.1:4173/?preview=panels` (see
[local setup](local-development.md) when starting from a fresh checkout):

1. Open each of the six aspect cards and return to the overview. Confirm the
   heading and saved panels match the selected aspect.
2. Mark all Budget checkpoints ready and one Product checkpoint blocked. Confirm
   green Budget and red Product while Sales remains selectable. Restore the test
   assessments afterward.
3. Add a checkpoint note, reload, and verify it persists. Explore with mentor and
   verify the note is included in the draft without submitting automatically.
4. Keep different drafts in Problem/Market and Product/Budget; switch and reload
   to verify they stay separate even though each pair shares a backend scope.
5. Use the panel chooser: Pricing must open Budget, and Launch plan must open
   Validation. Keep existing pricing selections, reviews and checklist state.
6. Check 375px, 768px and 1280px layouts in both themes, and the map beside the
   mentor on tablet/desktop. Tab through nodes and press Enter to open one.
7. Use `?preview=intake` to check required inputs and the existing brief-first
   flow without a provider call. Preview data is explicitly illustrative.

## Remaining limits and next validation

This change has not run live Gemini/Search, been deployed, or established provider
adherence to the new mentoring/topic instructions. Current tests prove scope
mapping and deterministic guard behavior; they do not prove observed demand,
real-world feasibility or a successful provider-backed journey.

Checkpoint assessments, notes and frontend aspect grouping use the existing
browser cache. Server-synchronized checkpoint collaboration is not implemented.
Promoting readiness to an evidence-derived backend capability would require a
separately agreed contract; do not infer it from these local controls.

Before deployment, review this PR's CI result and run any newly authorized
provider-backed smoke check with a bounded spend allowance. Deployment, merging,
outreach and other external execution remain separate actions.
