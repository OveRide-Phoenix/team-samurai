# Samurai UI

Samurai is a chat-first mentor and validator for software ideas. Mentor keeps
pinned panels on the left and the conversation on the right. Idea map puts the
six-aspect graph on the left with the same conversation on the right.
Map selection highlights a node; invoke an aspect mentor explicitly from chat.

Submitting an idea opens a mentor greeting and a first-pass analysis through the
existing intake workflow. Useful aspect drafts are labelled provided/inferred;
unknowns, founder edits and readiness assessments remain distinct from evidence.
The mentor challenges assumptions and suggests improvements before recommending
implementation. Answers can be concise text, useful OpenUI panels, or both.

## Run locally

From the repository root, use `task frontend:setup`, `task backend:dev` and
`task frontend:dev`, following [local development](../docs/local-development.md).
Open [Samurai](http://127.0.0.1:4173/). Localhost runs the actual app and configured
AgentOS backend. Developer preview routes and simulated chat transports have been
removed. Old query links open the ordinary app. Legacy sample caches are archived
within the same scoped browser cache, freeing the active idea limit; real ideas reopen through the
owned workspace directory. No browser data is silently deleted.

Node 24 and npm are the toolchain. The dev server binds to loopback. Keep local
`AGENTOS_USER_TOKEN` in ignored `frontend/.env.local` and JWT trust in the backend;
no provider key, service key or bearer token belongs in `VITE_` variables. Live
Gemini calls may incur charges. Static hosting alone cannot serve the authenticated
transport. See [GCP deployment](../docs/gcp-deployment.md) for the production boundary.

## Experience and boundaries

- One software idea, six independently discussable aspects, eighteen OpenUI question forms.
  Submit the form for a structured mentor review and the next question. Mentor drafts
  remain suggestions until reviewed; they do not complete the walkthrough.
- Free chat stays independent: sending a message does not answer or advance a form.
  Unsent form and chat drafts persist separately in the current browser account.
- Desktop Mentor/Idea map views, pinned panels, themed menus and accessible controls.
- One continuous transcript with explicit mentor invocation and retained drafts.
- OpenUI renders guided controls and typed business views. Generated panels can be
  pinned; custom interactive views stay in the existing isolated sandbox.
- CopilotKit carries scoped AG-UI requests to Agno. Native run recovery, cancellation,
  ownership, revisions, evidence gates and explicit execution approvals are retained.
- Intake drafts, founder readiness and synthetic scenarios are not validated demand.
  Research can remain insufficient; the app must not infer a go from a filled map.
- Browser caches retain notes, panel state and drafts. Production caches use the
  verified user's namespace. Checkpoint collaboration is not server-synchronized.
- Marketing, sales and build outputs remain drafts. Nothing sends, spends, publishes
  or deploys through the mentor conversation.

## Production guest access

The BFF defaults to `FRONTEND_AUTH_MODE=iap`. Production uses `guest` during the
approved seven-day judge window beginning 17 October 2026. Guest mode
creates signed browser identities while retaining scoped server-to-server JWTs.
See [public guest access](../docs/public-guest-access.md) for limits, cookie lifetime,
verification scope, expiry and rollback instructions.

## Verify

```sh
npm run check
npm run build
npm run test:sites
npm run test:server
```

Deterministic fixtures are imported by tests only; there is no sample-data app mode.
For browser acceptance, use an isolated real idea and the configured local backend.
See the [handoff](../docs/idea-validation-handoff.md) for live results and limitations,
[DESIGN.md](DESIGN.md) for visual rules and [BACKEND_CONTRACT.md](BACKEND_CONTRACT.md)
for transport and persistence.

React, Vite, TypeScript, Tailwind CSS, assistant-ui, Radix UI, Lucide, Zod and Vitest
use permissive licenses; Inter uses SIL Open Font License. Versions are locked in
`package-lock.json`. OpenUI renders the typed catalog; direct model-native OpenUI
streaming is not implemented. The atmospheric shader respects reduced motion and
retains the CSS fallback when WebGL2 is unavailable.

Guided reviews match the question using the bounded `panel_key` returned by `compose_panel`. Legacy panels still render, but cannot advance the guide. For backward-compatible backend-first rollout, only guide-prefixed compositions carry correlation metadata; ordinary panels retain their previous shape.

Submitted answers stay pending until their matching review completes. Cancellation, failed requests and incomplete output keep that question resumable after reload; its full answer remains in chat and in the form draft.

A guided answer is bound to its existing frontend submission ID before dispatch. Recovering a completed saved run accepts only that submission’s matching structured review and resumes the next open question; free-chat or stale results cannot finish another pending answer.
