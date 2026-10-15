# Frontend / AgentOS integration

The local founder UI adapts the installed Agno native SSE API using `src/agentos.ts`. New companies use the live transport; existing/demo companies remain explicitly Preview. The local Vite server injects a signed user JWT from ignored `.env.local`; provider and service keys never reach the browser.

## Existing seam

`Transport` in `src/model.ts` accepts user text and an `AbortSignal`, then yields validated `WorkEvent` objects. `src/App.tsx` consumes the events to update the left-pane activity and assistant-ui conversation. `demoTransport` is restricted to preview companies. Live requests use `createAgentosTransport(company.id)`.

```ts
type Transport = (input: string, signal: AbortSignal) => AsyncIterable<WorkEvent>;
```

The adapter consumes native AgentOS SSE and checks session/run/company scope before accepting results. Before a run POST, the browser synchronously saves a logical submission UUID in the owner-scoped portfolio. The production BFF validates that UUID and forwards it as the native `Idempotency-Key`. If storage fails, the POST is not sent. Live cancellation posts to the scoped native cancel endpoint and waits for acknowledgement. A rejected cancellation retains the running identity so the founder can retry.

## Activity event

```json
{
  "type": "activity",
  "agent": "Researcher",
  "state": "working",
  "detail": "Checking competitor pricing against published sources"
}
```

Supported initial roles: Researcher, Strategist, Verifier, Sales. States: working, done, waiting, stopped. Add roles and failure states to the shared schema when the corresponding backend behavior exists. Do not expose hidden chain-of-thought; use concise work descriptions and evidence summaries.

## Assistant message with a business panel

```json
{
  "type": "message",
  "text": "Here are the prospects to review before outreach.",
  "panel": {
    "id": "prospects-v1",
    "kind": "prospects",
    "title": "Find your first customers",
    "note": "Fictional example; replace with backend evidence provenance",
    "rows": [
      {
        "id": "clinic-1",
        "name": "Maple Dental",
        "area": "Indiranagar",
        "reason": "Owner-managed clinic with limited front-desk coverage",
        "fit": "High"
      }
    ]
  }
}
```

Supported panel kinds are `offer`, `pricing`, `prospects`, `evidence`, and `launch-plan`; their exact schemas are in `panelSchema`. Zod validates panel and event payloads. React renders only the known component types; model-generated JavaScript or arbitrary HTML is not executed.

## State ownership and current limits

- Chat, pins, shortlisted IDs, reviewed drafts, and the durable run receipt currently live in owner-scoped browser localStorage. They are UI preferences and a reconnect pointer, not durable backend approvals, researched prospects, or sent outreach.
- Preview fixtures use a dental scenario. New companies submit their validated brief to the real backend.
- Backend artifacts retain validated evidence, citations, assumptions and lineage. Explicit journey-stage approval is server-confirmed; token-by-token prose and connected measurements are not implemented.
- The verifier in the demo validates structure only. Never interpret it as verification of market facts.
- Provider credentials belong on the backend. The frontend must not contain a Gemini API key or Firebase Admin credential.

## Multi-company state

`Portfolio` version 2 stores a company list, the active company ID, and a global light/dark mode. Each company contains an independent `CompanyView`; the old single-company preview migrates without losing its conversation or panels. New companies start empty. Company IDs must be included in live requests, events, persistence, authorisation, and cancellation so concurrent runs cannot update another company. The old persisted `workspace.theme` field is retained solely for legacy compatibility; current visual mode is portfolio-level.

Gemini outputs are mapped into the validated panel catalog through native AgentOS SSE. assistant-ui renders known panel components; model-generated code is never executed.

## Shared workspace directory

Portfolio Home loads the authenticated directory through `/api/agentos/samurai`. The BFF permits only the fixed workspace, membership, company-list, company-reservation, and company-open paths; it rejects browser identity fields and forwards the verified JWT subject only. Workspace and company directory responses are parsed with strict Zod schemas.

Creating a company reserves its server company and actor session before the brief starts. `POST /workspaces/{workspace_id}/companies` accepts exactly `{}` and requires a canonical UUID `X-Samurai-Submission-Id`; both BFFs validate it and forward it as the only upstream `Idempotency-Key`. After a failed company request, the Home flow retries with that same key and workspace; a completed or explicit new reservation creates a new key. The browser uses the returned `parent_session_id` as its local CompanyView ID. `POST /workspaces/{workspace_id}/companies/{company_id}/open` accepts only `{}` and returns the current actor binding plus a strict snapshot envelope: `summary` and canonical `artifacts`, with no native session or context data. The client reuses the existing summary and artifact renderer to hydrate that envelope and never reads another actor's session. Viewer access shows the hydrated company but disables sending, runs, panel mutations, and task completion; backend authorization remains the enforcement boundary.

## Generative UI catalog

The existing assistant-ui `business_panel` tool renders validated panel objects in chat. The same objects render in Home and the full Company dashboard. No additional generative UI service or library is needed for this catalog. Gemini/AgentOS can choose a `kind` and populate its fields on the backend; runtime schemas in `src/model.ts` are the current frontend contract.

- `evidence`: `claims` with `id`, `claim`, `status` (`hypothesis`, `needs-check`, `supported`), `detail`, and a strict source union. `external` carries a title and HTTP(S) URL; it is rendered with `noopener noreferrer`. `workspace_file` carries file ID, chunk ID, indexed revision, SHA-256 and the fixed `uploaded_file`/`untrusted_context` trust labels; the UI resolves its title and downloads only through the authenticated same-origin file BFF. `accepted_artifact` carries immutable artifact/chunk/revision/hash provenance and is never a download. Supported claims require at least one external source; uploaded context never independently verifies a claim. Legacy `{title,url}` external entries parse as the external variant for existing saved panels.

Knowledge references on an Intake, Strategy, Research, or Verifier artifact map to `knowledge_sources` on the existing stable panel ID. Their trust/hash/revision/chunk details remain progressively disclosed. The renderer uses `GET /api/agentos/samurai/workspaces/{workspace_id}/files/{file_id}` only to resolve authorized metadata, and `GET .../{file_id}/download` only after a user action. Both calls use same-origin credentials and `X-Samurai-Client`; browser URLs never contain an access token or a storage locator. A deleted or revoked file stays represented as provenance and reports only `Download unavailable.`

Development fixture: `/?preview=knowledge&workspaceId=<authorized-workspace-uuid>` renders an illustrative external source, uploaded-file provenance, and accepted-artifact provenance through the real mapper. The fixture has no embedded token or mock authorization response. Browser acceptance must point it at a task-owned synthetic authenticated BFF/backend harness; fixture rendering by itself is not file-download acceptance.
- Founder intake and strategy artifacts may map their validated `founder_truth` or `offer_diagnostic` into optional `founder_context` on existing evidence, offer, and pricing panels. It carries a next decision, visible evidence gaps, and a reviewed framework attribution (`id`, semantic version, attribution, repository, immutable revision, and the matching GitHub tree URL). Attribution is rendered separately from claims and never changes a claim's evidence status. Existing saved panels omit this optional field and continue to parse.
- `launch-plan`: `tasks` with unique `id`, `title`, `owner`, `timing`, and `detail`. Checkmarks and progress are local founder controls, not execution by an agent. Completion is stored per company in `completedTasks` using serialized `[panelId, taskId]` pairs.
- Reuse a panel ID for a revised result. The dashboard deduplicates it and pinned content updates to the latest payload. Keep task IDs stable when preserving completed steps; use a new ID when replacing a task.

Existing saved workspaces migrate with an empty `completedTasks` list. The evidence and launch samples are deterministic previews, not outputs from a connected model. Live runs use the native server API; template streams remain limited to Preview companies.

## Server-owned prerequisite intake

`GET /api/agentos/intake` forwards to the public metadata-only `/api/company/intake`. It returns three pages covering six supported question IDs exactly once: idea, customer, location, budget, founderSkills and goal. The UI validates both metadata and required answers, then persists the brief per company. Founder skills are included in the first structured prompt so the backend can proceed beyond Intake. No private founder data is exposed by the metadata endpoint. Leaving/reloading unfinished onboarding discards that draft.

## Native workflow progress

Backend CustomEvents serialize their payload as `content: {kind: "workflow_progress", detail: "Research started"}`. Agno drops arbitrary fields outside its declared event schema, so the adapter reads the preserved content object and also accepts historical string events. Real StepStarted/StepCompleted events drive activity; early evidence stops derive explicit waiting states from the validated workflow outcome. Clicking a Team role expands its history. History survives local reload and is reconstructed from scoped saved-run events without rerunning the workflow. Cancellation/failure settles only unfinished roles; completed roles retain their history. No completion percentage or model reasoning is invented.

## Native local wire

`POST /api/agentos/agents/samurai/runs` sends exactly multipart `message`, `session_id`, `stream=true`, `background=true` plus `X-Samurai-Submission-Id`. The production BFF accepts only a canonical UUID for that header, forwards it as `Idempotency-Key`, derives the owner from IAP and injects the short-lived server JWT. It never accepts a browser-supplied owner or user ID.

Initial intake omits approval headers and is limited to journey `brief` at revision 0. After an accepted artifact and completed owner receipt are present, the UI offers one explicit next-stage approval. That submit includes all of `X-Samurai-Operation`, `X-Samurai-Stage`, `X-Samurai-Expected-Revision`, and `X-Samurai-Company-Id`. The BFF validates the operation/stage pair, canonical nonnegative revision, and company UUID before forwarding them. The backend then verifies the company against the JWT owner, parent session, and canonical revision before provider work. Missing, partial, forged, or stale approval binding fails closed; ordinary model text never creates a stage approval.

The initial response remains native AgentOS SSE. The adapter saves the native `run_id` and zero-based `event_index` as events arrive. A stream disconnect resumes the same run with `POST /api/agentos/agents/samurai/runs/{run_id}/resume`, multipart `session_id` and optional `last_event_index`; replayed indices are ignored. If the initial response is lost before `RunStarted`, `GET /api/agentos/work-receipts/{submission_id}?session_id=...` recovers the owner-scoped run ID and queue state. Neither path replays the original run POST.

Receipt states map visibly to queued, running, recovering, paused, completed, cancelled or failed. Reload uses the saved receipt/run/cursor and the native resume stream, then reconciles panels by stable artifact ID and revision. Read, receipt, resume and cancel routes remain session scoped. Missing or cross-owner receipts are 404 at the backend. Operator queue routes and Samurai `/continue` are not exposed by the BFF; paused work needs a separately approved recovery contract.

The model is locked to `gemini-3.5-flash-lite`; configuration rejects other models. The original 2.5 Flash-Lite request returned 404 for this new account. On 12 October the user authorized 3.5 Flash-Lite; no automatic fallback or paid billing was enabled.

The Vite proxy is development-only. The static Sites build does not contain this proxy. Cloud Run serves the authenticated production BFF in `server/production.mjs` behind IAP.

Google Search grounding is disabled in this free-tier 3.5 Flash-Lite runtime. Research without citations remains insufficient evidence; no paid search or billing was enabled.

### Model configuration restored — 12 October 2026
The user explicitly restored Kalyan's main setup, superseding the earlier free-only Lite restriction: default `gemini-3.8-flash`, configurable through `GEMINI_MODEL`, with native Google Search only for Researcher. Evidence gates, JWT auth, limits, per-run model construction and UI integration remain. The user prohibits API calls during this restoration because they may incur cost; leave the local backend stopped and do not run provider smoke tests or browser workflows until explicitly authorized. Restoring configuration does not change account billing or verify provider access.

### Paid-account Flash-Lite testing — 12 October 2026
The user funded the API account and now requests `gemini-3.5-flash-lite` with native Google Search. This supersedes the preceding 3.8 restoration and temporary no-call instruction. Keep all roles on Flash-Lite and enable Search only for Researcher. Initial live verification is one bounded research call; do not launch bulk/full-journey tests without discussing measured cost. Billing allowance and tax are estimates until confirmed in the account. Keep the local backend stopped outside explicitly requested testing to avoid accidental charges.

Founder-paced journey: native `run_company_journey` defaults to `stage="brief"`. Explicit research, strategy, and plan stages stop at their respective boundaries; incomplete context and source gates remain enforced. The UI offers one next-stage action and suppresses repeated artifacts by retained ID/revision. Tests use deterministic models; no additional paid provider run was made for this refinement.

Cancellation POST acknowledges intent. Both active-stream and saved-run Stop paths keep the run active until a scoped run read confirms CANCELLED, COMPLETED or ERROR. Read-only confirmation is bounded to 60 seconds; an unconfirmed stop retains the running identity and blocks a new request. If completion wins the cancellation race, retained results are recovered rather than labelled cancelled.

## CopilotKit AG-UI — 13 October 2026
The live frontend now runs through `/api/copilotkit` using a single-route CopilotKit v2 envelope. The server admits only `info` and `agent/run` for `samurai`; it keeps identity and JWTs server-side. Runs forward one user text turn to `/agentos/agents/samurai/agui` with empty tools/context/state/forwardedProps. The backend enforces the unchanged per-agent run scope, owner isolation, bounded text and no client tool continuation.

Native progress/completion records travel as `CUSTOM` events named `samurai` alongside Agno's standard AG-UI events. Existing validators, artifacts, evidence lineage, cancellation and saved-run recovery remain. Presentation tools return `SAMURAI_PANEL=` plus a validated declarative/custom panel; their owner/session-scoped IDs remain stable for updates. They carry no company artifact provenance and never modify canonical evidence. The known A2UI catalog is CompanyBrief, ResearchEvidence, Offer, Pricing, DeliveryPlan and ProspectList. `npm run test:server` and the frontend/backend checks cover these new boundaries.

## Founder operations

The Company dashboard exposes explicit learning, schedules, and deterministic scenarios through authenticated `/api/agentos/samurai/workspaces/...` BFF routes. The BFF allowlists each route, query, and JSON shape, derives identity from the server session, and maps `X-Samurai-Submission-Id` to upstream `Idempotency-Key` only for scenario create/run. It does not expose a generic backend proxy.

Learning create/list/supersede remains revision-pinned and labelled `untrusted_preference_context`. Schedule create accepts only `workspace_review` with `{}` or `scenario_recompute` with `{scenario_id}`; list, disable, and bounded run-receipt reads are recoverable after reload. Scenario definitions are company-scoped and pinned to the directory response's `current_revision` and `state_sha256`. Persisted results map to the single allowlisted `scenario` panel with low/base/high trajectories, assumptions, formulas, constraints, hashes, and the always-visible `synthetic_scenario_not_validation` provenance. This analysis does not advance canonical company revision or establish observed demand.
