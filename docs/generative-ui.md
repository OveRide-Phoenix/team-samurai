# CopilotKit / Agno UI contract

## Decided panels

| Founder stage | Declarative catalog component | Retained behavior |
| --- | --- | --- |
| Entry form / brief | CompanyBrief | Idea, customers, market, budget, resources, milestone; pin and expand |
| Approved research | ResearchEvidence | Evidence, uncertainty, sources, conflicts and verification findings |
| Approved strategy | Offer, Pricing | Draft offer review and pricing hypotheses |
| Approved planning | DeliveryPlan | Delivery steps and company-scoped founder checkmarks |
| Customer exploration | ProspectList | Filtering and company-scoped shortlist |

Completing the entry form starts only the brief stage. The existing one-next-stage action governs further work. The frontend deterministically projects validated business artifacts into A2UI v0.9 surfaces; known renderers reuse the established BusinessPanel components. Additional agent-authored compositions have only text, metric, list and table primitives. Customer-requested custom components can use inline HTML/CSS/JavaScript in an opaque sandbox.

## Transport and identity

Browser → `/api/copilotkit` → the existing Node identity proxy / CopilotRuntime → `/agentos/agents/samurai/agui` → a fresh Agno Samurai parent. Production verifies IAP before minting the same per-user AgentOS JWT; local development uses the existing ignored local JWT. The AG-UI route requires the unchanged `agents:samurai:run` scope and rejects foreign sessions before streaming. Client tools, context/state/identity overrides and tool resumptions are not accepted. The runtime exposes only info and the fixed Samurai run method; it does not keep global thread history. Agno remains the durable history store.

The public CopilotKit headless context preserves the existing assistant-ui chat and composer. A small adapter passes native completion/progress events carried over AG-UI into the established workspace validator. Native owner-scoped read and cancel routes remain authoritative; an abort acknowledgement alone is not completion. Before forwarding native RunStarted, the interface persists an owned running record so a slow first model response is readable and cancellable. This is a startup checkpoint, not a durable execution queue or automatic restart recovery.

## Design and custom-frame boundary

All catalog views inherit Samurai's existing CSS tokens. Known panels include overview/input toggles, evidence filters, source disclosures, offer review, selectable pricing hypotheses, delivery checklists and searchable prospect shortlists; their existing saved callbacks remain authoritative. Composed controls use the same card, surface, border, primary and typography tokens. Custom frames embed the existing Inter font as data and receive the light/dark palette and styled controls; a protected first important CSS layer owns native controls and typography, CSP rejects inline style attributes, and model instructions allow layout CSS only. Transparent frames fit their content through the bounded size signal. Responsive layouts and reduced motion remain required. No generic developer UI, duplicate outer headings, green palette, heavy shadows or fake progress.

Custom frames use `srcdoc` and `sandbox="allow-scripts"`, without same-origin, forms, popups or navigation permissions. An inline CSP blocks external resources, connections, nested frames, workers and form submissions. The parent policy blocks external frame navigation; it is supplied by the servers and the built HTML, including static previews. No host function bridge is exposed. A trusted size-only signal is accepted exclusively from the matching opaque iframe, with strict shape checks and a 120–720px clamp. Generated definitions are bounded and persisted in Agno run output and company browser state. Custom frame values are temporary and reset on reload/theme regeneration; they are not company measurements or external actions.

## Dependencies and verification

Direct versions are exact in the manifests/lockfiles: CopilotKit 1.79.0, AG-UI client 1.0.2, and Agno 3.1.2 with the AG-UI extra. A Zod 3 alias matches CopilotKit's catalog API while the application keeps Zod 4. Backend evidence/state contracts remain unchanged.

Run the existing `npm run check`, `npm run build`, `npm run test:server`, `npm run test:sites`, and backend Ruff, formatting, basedpyright and pytest commands. No environment or provider-key changes are required for the source integration. Restart both application processes after installing locked dependencies. Development skills OMo and Agno were unavailable in this Codex session; Ponytail was read and used, with current official documentation and installed APIs checked directly.

Initial transport checks on 13 October 2026 passed: 169 backend tests, 84 frontend tests, 39 production-server tests, 4 Sites packaging tests, Ruff/formatting, basedpyright, TypeScript and the production build.

Acceptance: real browser form → CopilotKit runtime → authenticated Agno → CompanyBrief, composed-table filtering, a sandboxed calculator, pinning, reload recovery, dark/light styling and mobile layouts. Browser tests use a loopback-only deterministic AgentOS/SQLite fixture with generated test keys and a fixture identity; real IAP verification is covered separately by production-server tests. This does not verify live Gemini output, real PostgreSQL, a cloud deployment or customer demand. The configured backend remains stopped outside requested testing.

References: [CopilotKit / Agno](https://docs.copilotkit.ai/agno), [Agno AG-UI](https://docs.agno.com/agent-os/interfaces/ag-ui/introduction), [A2UI](https://docs.copilotkit.ai/generative-ui/a2ui), [generative UI spectrum](https://www.copilotkit.ai/generative-ui-spectrum).

## Local interactive review

Start the frontend with `npm run dev`, then open `http://127.0.0.1:4173/?preview=panels` to inspect all six actual catalog renderers and an interactive custom revenue scenario. Open `http://127.0.0.1:4173/?preview=intake` for the actual three-page form and brief-first sequence; later sample work starts only on a founder action. These development-only views use isolated browser preview storage and labelled fictional data, with no AgentOS or Gemini calls. They demonstrate UI behavior, not business verification or live generated output. The normal local route retains the real CopilotKit/Agno connection.

Interactive UI follow-up: 87 frontend tests, 39 production-server tests, 4 packaging tests, TypeScript and the production build passed. Browser checks covered the six catalog views, discussion drafts without submission, saved review/checklist/shortlist state, filtering, pricing selection, custom calculations, brief-first intake, desktop/mobile and both themes. A styling stress case attempted conflicting fonts, colors and squared controls; computed styles retained Inter, Samurai colors, rounded controls and a transparent shell. No provider call or deployment was made. The local frontend was left running for the requested review.


## Focused team workspace

Company filters panels through a centered multi-select workflow bar, without an Overview button. Nothing selected reveals all current panels; multiple selections reveal their union. The brief belongs to general company context; research evidence to Researcher; offer, pricing and delivery to Strategist; reviews to Verifier; prospects and sales drafts to Sales. Current native outputs replace earlier visible results of the same artifact/component type, while the underlying artifact history remains. Authored views inherit their conversation's area. Each area starts as a full-width dashboard with the retained floating chat bar. Opening it reveals the focused conversation alongside panels on desktop, or in the content area on mobile; closing restores the dashboard without losing drafts or scroll. Main Chat keeps the overall company conversation. Drafts and selected areas migrate through optional/defaulted workspace fields without discarding saved actions.

The browser forwards only {team_area: overview|research|strategy|verification|sales}. Node and Python both validate this property and continue rejecting all identity, tools, state and dependency overrides. The authenticated company thread is shared; this does not create independent companies or services per role. The parent has scoped guidance plus deterministic business tool/stage guards and a bounded suggest_team_area presentation tool. Switching is explicit, and the original question is prepared as a draft without submission. Natural-language topic discipline still depends on the model following scope guidance; live Gemini behavior has not been verified for this change.

A dedicated verify stage checks existing artifacts without upstream execution and returns needs_input when the full journey is unavailable. Accepted history and native cancellation remain authoritative. There were no paid provider calls or deployment for this work.

Workflow filter refinement: opening the floating chat bar uses a gentle panel-position spring and an opacity-only chat reveal. One selected workflow retains its typed execution scope; no selection or multiple filters use the shared general conversation. Filter selections persist with legacy single-choice migration. This is presentation filtering, not independent backend runs or an array-valued transport scope.
