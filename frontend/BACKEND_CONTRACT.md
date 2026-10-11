# Frontend / AgentOS integration

The local founder UI adapts the installed Agno native SSE API using `src/agentos.ts`. New companies use the live transport; existing/demo companies remain explicitly Preview. The local Vite server injects a signed user JWT from ignored `.env.local`; provider and service keys never reach the browser.

## Existing seam

`Transport` in `src/model.ts` accepts user text and an `AbortSignal`, then yields validated `WorkEvent` objects. `src/App.tsx` consumes the events to update the left-pane activity and assistant-ui conversation. `demoTransport` is restricted to preview companies. Live requests use `createAgentosTransport(company.id)`.

```ts
type Transport = (input: string, signal: AbortSignal) => AsyncIterable<WorkEvent>;
```

The first backend flow can adapt SSE, NDJSON, or a durable-job subscription into this interface without changing the visual components. Add company/session/run identity and authentication to the adapter when the server contract is agreed. Live cancellation posts to the scoped native cancel endpoint and waits for acknowledgement. A rejected cancellation retains the running identity so the founder can retry.

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
- The UI fixtures use one dental receptionist scenario. New-company creation and arbitrary-idea generation belong to a later connected flow.
- Backend evidence, source citations, streamed text chunks, error/retry events, and server-confirmed approvals need explicit agreed fields before live use.
- The verifier in the demo validates structure only. Never interpret it as verification of market facts.
- Provider credentials belong on the backend. The frontend must not contain a Gemini API key or Firebase Admin credential.

## Multi-company state

`Portfolio` version 2 stores a company list, the active company ID, and a global light/dark mode. Each company contains an independent `Workspace`; the old single-workspace preview migrates without losing its conversation or panels. New companies start empty. Company IDs must be included in live requests, events, persistence, authorisation, and cancellation so concurrent runs cannot update another company. The old `Workspace.theme` field is retained solely for legacy compatibility; current visual mode is portfolio-level.

Gemini can populate the existing validated panel catalog. assistant-ui already renders known tool results. An AG-UI transport is a candidate if Kalyan's AgentOS API exposes it; this has not been connected or verified. No Gemini credentials are configured in this UI task.

## Generative UI catalog

The existing assistant-ui `business_panel` tool renders validated panel objects in chat. The same objects render in Home and the full Company dashboard. No additional generative UI service or library is needed for this catalog. Gemini/AgentOS can choose a `kind` and populate its fields on the backend; runtime schemas in `src/model.ts` are the current frontend contract.

- `evidence`: `claims` with `id`, `claim`, `status` (`hypothesis`, `needs-check`, `supported`), `detail`, and `sources` (`title`, HTTP(S) `url`). Supported claims require a source. The UI says “Source attached”; attaching a link does not establish independent verification.
- `launch-plan`: `tasks` with unique `id`, `title`, `owner`, `timing`, and `detail`. Checkmarks and progress are local founder controls, not execution by an agent. Completion is stored per company in `completedTasks` using serialized `[panelId, taskId]` pairs.
- Reuse a panel ID for a revised result. The dashboard deduplicates it and pinned content updates to the latest payload. Keep task IDs stable when preserving completed steps; use a new ID when replacing a task.

Existing saved workspaces migrate with an empty `completedTasks` list. The evidence and launch samples are deterministic previews, not outputs from a connected model. The stream continues to use activity and message events; no server API was introduced or connected.

## Prerequisite intake proposal

`src/Onboarding.tsx` contains placeholder `intakePages`; these are not fetched from a server. Required answers are validated by `companyBriefSchema` and stored in `workspace.brief` per company. Creating a company is deferred until all pages pass. The initial run uses `onboardingPreview`, an abortable template workflow over that brief, not Gemini or market research. Coordinate server-owned question IDs/types/validation and a real first-run endpoint before replacing these placeholders. Reloading a company with existing messages does not replay the initial preview.

## Native local wire

`POST /api/agentos/agents/samurai/runs` sends multipart `message`, `session_id`, `stream=true`, `background=false`. The proxy forwards to `http://127.0.0.1:8000/agentos`, requires `X-Samurai-Client: 1`, and injects the server JWT. Read and cancel routes require the same session ID. Stored run/company bindings are checked on reload; completed results are read without rerunning. This is completed-run recovery, not a durable job queue.

The model is locked to `gemini-3.5-flash-lite`; configuration rejects other models. The original 2.5 Flash-Lite request returned 404 for this new account. On 12 October the user authorized 3.5 Flash-Lite; no automatic fallback or paid billing was enabled.

The Vite proxy is development-only. The static Sites build does not contain this proxy; production needs an authenticated backend-for-frontend before live deployment.

Google Search grounding is disabled in this free-tier 3.5 Flash-Lite runtime. Research without citations remains insufficient evidence; no paid search or billing was enabled.
