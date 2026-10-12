# Frontend / AgentOS integration

The local founder UI adapts the installed Agno native SSE API using `src/agentos.ts`. New companies use the live transport; existing/demo companies remain explicitly Preview. The local Vite server injects a signed user JWT from ignored `.env.local`; provider and service keys never reach the browser.

## Existing seam

`Transport` in `src/model.ts` accepts user text and an `AbortSignal`, then yields validated `WorkEvent` objects. `src/App.tsx` consumes the events to update the left-pane activity and assistant-ui conversation. `demoTransport` is restricted to preview companies. Live requests use `createAgentosTransport(company.id)`.

```ts
type Transport = (input: string, signal: AbortSignal) => AsyncIterable<WorkEvent>;
```

The adapter consumes native AgentOS SSE and checks session/run/company scope before accepting results. Live cancellation posts to the scoped native cancel endpoint and waits for acknowledgement. A rejected cancellation retains the running identity so the founder can retry.

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

- Chat, pins, shortlisted IDs, and reviewed drafts currently live in browser localStorage. They are UI preferences, not durable backend approvals, researched prospects, or sent outreach.
- Preview fixtures use a dental scenario. New companies submit their validated brief to the real backend.
- Backend artifacts retain validated evidence, citations, assumptions and lineage. Token-by-token prose, server-confirmed approvals and connected measurements are not implemented.
- The verifier in the demo validates structure only. Never interpret it as verification of market facts.
- Provider credentials belong on the backend. The frontend must not contain a Gemini API key or Firebase Admin credential.

## Multi-company state

`Portfolio` version 2 stores a company list, the active company ID, and a global light/dark mode. Each company contains an independent `Workspace`; the old single-workspace preview migrates without losing its conversation or panels. New companies start empty. Company IDs must be included in live requests, events, persistence, authorisation, and cancellation so concurrent runs cannot update another company. The old `Workspace.theme` field is retained solely for legacy compatibility; current visual mode is portfolio-level.

Gemini outputs are mapped into the validated panel catalog through native AgentOS SSE. assistant-ui renders known panel components; model-generated code is never executed.

## Generative UI catalog

The existing assistant-ui `business_panel` tool renders validated panel objects in chat. The same objects render in Home and the full Company dashboard. No additional generative UI service or library is needed for this catalog. Gemini/AgentOS can choose a `kind` and populate its fields on the backend; runtime schemas in `src/model.ts` are the current frontend contract.

- `evidence`: `claims` with `id`, `claim`, `status` (`hypothesis`, `needs-check`, `supported`), `detail`, and `sources` (`title`, HTTP(S) `url`). Supported claims require a source. The UI says “Source attached”; attaching a link does not establish independent verification.
- `launch-plan`: `tasks` with unique `id`, `title`, `owner`, `timing`, and `detail`. Checkmarks and progress are local founder controls, not execution by an agent. Completion is stored per company in `completedTasks` using serialized `[panelId, taskId]` pairs.
- Reuse a panel ID for a revised result. The dashboard deduplicates it and pinned content updates to the latest payload. Keep task IDs stable when preserving completed steps; use a new ID when replacing a task.

Existing saved workspaces migrate with an empty `completedTasks` list. The evidence and launch samples are deterministic previews, not outputs from a connected model. Live runs use the native server API; template streams remain limited to Preview companies.

## Server-owned prerequisite intake

`GET /api/agentos/intake` forwards to the public metadata-only `/api/company/intake`. It returns three pages covering six supported question IDs exactly once: idea, customer, location, budget, founderSkills and goal. The UI validates both metadata and required answers, then persists the brief per company. Founder skills are included in the first structured prompt so the backend can proceed beyond Intake. No private founder data is exposed by the metadata endpoint. Leaving/reloading unfinished onboarding discards that draft.

## Native workflow progress

Backend CustomEvents serialize their payload as `content: {kind: "workflow_progress", detail: "Research started"}`. Agno drops arbitrary fields outside its declared event schema, so the adapter reads the preserved content object and also accepts historical string events. Real StepStarted/StepCompleted events drive activity; early evidence stops derive explicit waiting states from the validated workflow outcome. Clicking a Team role expands its history. History survives local reload and is reconstructed from scoped saved-run events without rerunning the workflow. Cancellation/failure settles only unfinished roles; completed roles retain their history. No completion percentage or model reasoning is invented.

## Native local wire

`POST /api/agentos/agents/samurai/runs` sends multipart `message`, `session_id`, `stream=true`, `background=false`. The proxy forwards to `http://127.0.0.1:8000/agentos`, requires `X-Samurai-Client: 1`, and injects the server JWT. Read and cancel routes require the same session ID. Stored run/company bindings are checked on reload; completed results are read without rerunning. This is completed-run recovery, not a durable job queue.

The model is locked to `gemini-3.5-flash-lite`; configuration rejects other models. The original 2.5 Flash-Lite request returned 404 for this new account. On 12 October the user authorized 3.5 Flash-Lite; no automatic fallback or paid billing was enabled.

The Vite proxy is development-only. The static Sites build does not contain this proxy; production needs an authenticated backend-for-frontend before live deployment.

Google Search grounding is disabled in this free-tier 3.5 Flash-Lite runtime. Research without citations remains insufficient evidence; no paid search or billing was enabled.

### Model configuration restored — 12 October 2026
The user explicitly restored Kalyan's main setup, superseding the earlier free-only Lite restriction: default `gemini-3.8-flash`, configurable through `GEMINI_MODEL`, with native Google Search only for Researcher. Evidence gates, JWT auth, limits, per-run model construction and UI integration remain. The user prohibits API calls during this restoration because they may incur cost; leave the local backend stopped and do not run provider smoke tests or browser workflows until explicitly authorized. Restoring configuration does not change account billing or verify provider access.

### Paid-account Flash-Lite testing — 12 October 2026
The user funded the API account and now requests `gemini-3.5-flash-lite` with native Google Search. This supersedes the preceding 3.8 restoration and temporary no-call instruction. Keep all roles on Flash-Lite and enable Search only for Researcher. Initial live verification is one bounded research call; do not launch bulk/full-journey tests without discussing measured cost. Billing allowance and tax are estimates until confirmed in the account. Keep the local backend stopped outside explicitly requested testing to avoid accidental charges.

Founder-paced journey: native `run_company_journey` defaults to `stage="brief"`. Explicit research, strategy, and plan stages stop at their respective boundaries; incomplete context and source gates remain enforced. The UI offers one next-stage action and suppresses repeated artifacts by retained ID/revision. Tests use deterministic models; no additional paid provider run was made for this refinement.
