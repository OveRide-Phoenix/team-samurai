# Frontend contributor guide

Samurai's first slice uses React, TypeScript, Vite, Tailwind, assistant-ui, Radix, Lucide, and Zod. Follow root AGENTS.md and ponytail. Keep structured panel validation and the explicit sample-data/activity labels. Agent provider secrets belong on the backend. The authenticated AgentOS integration is implemented; BACKEND_CONTRACT.md records the interface.

Run the local server yourself and open the preview in the browser available to this environment. Do not give the user server-start instructions when you can run it.

Before making substantial visual changes, use the Product Design plugin's `get-context` skill when the visual source is unclear or no longer matches the current goal. When the user gives durable prototype-specific design feedback, preferences, or decisions, record them in `AGENTS.md`.

When implementing from a selected generated mock, treat that image as the source of truth for layout, component anatomy, density, spacing, color, typography, visible content, and hierarchy.

Build app UI in `src/`. Keep `.openai/hosting.json`, `worker/index.js`, `scripts/prepare-sites-build.mjs`, and `tests/sites-worker.test.mjs` intact so the same local prototype can be handed to Sites. Before a Sites handoff, run `npm run build` and `npm run test:sites`; the build must leave `dist/client/index.html`, `dist/server/index.js`, and `dist/.openai/hosting.json`.

## Identity refinement — 11 October 2026

The user wants Samurai to feel its own while keeping the airy atmosphere and top blur. Their latest preference supersedes the initial dark-direction choice: do not force the logo colors or turn the workspace dark. Reduce decorative labels, repetitive helper copy, and idle-agent descriptions. Keep essential data provenance and preview labels readable, and preserve chat, panel actions, and visible progress during work.

## Company workspace and final visual direction

Hark is a reference for visual materials and components, not a required UX flow or layout. The user explicitly permits exploring different layouts and company-building journeys. Keep atmospheric backgrounds, blurred top and full-width bottom edges, contextual panels, and a restrained liquid-glass feel. Apply glass selectively to navigation, composer, and panel shells while preserving readable content. Stitch exploration should include this distinction and current screenshots.

Keep the airy atmosphere, but use Samurai's own warm porcelain/peach/graphite light palette and charcoal/champagne dark palette. Green was explicitly rejected. Provide light and dark modes across all UI and dialogs. Use self-hosted Inter as the chosen free typeface; do not declare GT Standard as a fallback. Keep the earlier clean buttons, forms, and frosted surfaces. Be UI is only for specific useful custom components, currently the sliding navigation indicator, not a wholesale visual replacement. Motion should remain subtle and honour reduced-motion preferences.

Show a true landing screen, a fresh company with zero messages and panels, and an optional dental demo. Support multiple companies with separate persisted workspace state. The team must stay present, including on mobile. Cmd/Ctrl+K focuses the inline top search field; results appear beneath it without a search dialog. The footer uses a masked blur across the entire viewport, with the composer kept crisp above it.

The user rejects fake 3D glass: no bevelled or embossed controls, heavy glass shadows, or a glossy gradient used as a substitute for refraction. Use actual backdrop refraction for selective floating chrome, keep content sharp, and preserve quiet panels. Before presenting a UI change, verify icon centring, shared header alignment, control spacing and overflow in rendered desktop and mobile views; code inspection alone is insufficient.

The user rejected the Stitch mockup; do not adopt it. Panels expand in place in Home instead of opening review dialogs. The Company view extends Home across the workspace as a dashboard of the same business panels, keeping the team and company context present. A bottom chat button returns to the existing conversation; preserve its draft, scroll position and panel actions. On mobile, reveal panels in the full dashboard because the compact Home strip only contains the team. Settings and the panel chooser may still use dialogs.

Header geometry is an explicit acceptance check: tab indicators must match their selected trigger bounds, with equal top/bottom insets in the group. Glass backdrop bounds must match the control they cover. Check both tabs, themes and desktop/mobile sizes, including after reload and resize; visually aligned text alone does not establish correct geometry.

## Generative UI catalog

Use the installed assistant-ui tool renderer with validated Zod panel payloads. The catalog includes offer, prospects, pricing, evidence review and launch plans. Keep the same panel components in chat, Home and the dashboard; reuse stable panel IDs for updates. Source attachment must not be presented as independent verification. Launch checkmarks are local founder progress, not agent execution. Keep task completion isolated per company and migrate old saved workspaces without discarding their data. No live Gemini integration is implied by these UI components.

Floating glass controls must have a visible theme tint: warm porcelain in light mode and smoky champagne in dark mode. The tab-group shell and entire composer need a strongly tinted, near-opaque frosted background, not clear outlines through which scrolling text remains legible. Tint only the decorative backdrop; preserve refraction, crisp foreground content and existing control geometry.

Keep the dashboard expand/collapse control at the top of the left pane. Expanding Home uses a slower 850 ms ease-in-out blur-and-fade reveal; returning to chat uses the same 850 ms instead of abruptly resizing the pane; retain mounted chat/panel state and skip the effect for reduced motion.

Use a calm animated mesh shader for the atmosphere, inspired by Be UI’s shader background. Keep Samurai’s warm light/dark palettes, freeze animation for reduced motion, retain the CSS atmosphere when WebGL is unavailable, and cap rendering resolution for this decorative layer.

Light-mode atmosphere should have a richer visible gradient: creamy highlights, peach warmth and soft lavender, rather than washed-out beige/grey. Keep dark-mode colors unchanged.

The header Chat/Company switch must slide smoothly between conversation and dashboard positions, matching the 850 ms expansion timing; reduced motion disables the slide.

Company switching and creation happen only on the portfolio Home screen; do not show a company dropdown or New company link inside a company. Display the company name once per view as a large bold Inter heading, using primary foreground text. Keep subtle shadows on business/team/action cards. The Company dashboard uses masonry columns; cards can be dragged or moved with accessible earlier/later buttons. Persist their order per company, preserving old saved workspaces.

Workspace settings open as a themed anchored dropdown, including Edit card order. Reorder handles and move buttons are hidden until edit mode is enabled; Done or returning to chat exits edit mode. Keep settings accessible on mobile.

Expanded Company view is a full-width dashboard, without the sidebar action stack or Add a panel row. Place the single bold company name at the far left above the content. The team becomes a larger dashboard card: idle agents explain their role; activity details take precedence while work runs. Keep the header plus action, edit-mode Done and collapse control available. Company switching stays exclusive to portfolio Home.

Landing has no AI → COMPANY kicker. Center the floating company-name intake. Start company opens three required prerequisite pages (business idea; customer/location; budget/first milestone), currently placeholder definitions for backend handoff. Save the validated brief with its company and create only after completion. Start an explicitly labelled, cancellable preview run on first entry; do not imply live research. All page/view reveals use the same 850 ms ease-in-out blur and transient grain, including returning to Chat, with reduced motion disabled.

## Repository consolidation

The user requested moving the working UI from `ui/` to `frontend/`. Preserve its React/Vite runtime and all existing behavior; the Next.js health-only scaffold is superseded. Use npm with exact direct versions and the generated lockfile. `task frontend:setup` installs the UI independently of backend setup; `task frontend:dev` runs on port 4173. Run `npm run check` and `npm run build`. Follow applicable OMo and Ponytail skills. Local JWT-authenticated native AgentOS SSE plumbing is implemented; verify model access separately. New companies use the live transport, legacy/demo companies remain Preview. The production Node proxy validates Google IAP and supplies per-user JWTs; Google sign-in, live brief creation and reload are verified. Never expose provider keys, service keys, JWT configuration or bearer tokens in VITE_ variables.

### Local UI integration — 11 October 2026

New companies use native AgentOS SSE through the Vite server proxy. Configure `AGENTOS_USER_TOKEN` in ignored `frontend/.env.local` and the matching `JWT_VERIFICATION_KEY` in ignored `backend/.env`; restart the backend after changing its configuration. `GEMINI_MODEL` is locked to `gemini-3.5-flash-lite`, with no fallback. The original 2.5 Flash-Lite request returned HTTP 404 for this new account. The user then authorized 3.5 Flash-Lite on 12 October; verify its access separately. Existing and dental-demo companies retain Preview mode. Never call fixture tests proof of successful Gemini research. The production Node server supplies the IAP-authenticated proxy; static hosting alone cannot support live authenticated runs.

Latest landing refinement: remove Team and dental-demo shortcut from portfolio Home; keep Team inside companies. Replace separate Start company CTA with a circular upward-arrow send inside the company-name pill. Pointer focus must not show an outline; retain visible focus through surface/shadow and keyboard focus on submit. Dark chat/card/action surfaces should be lighter and distinct from the unchanged shader background. Dark reveal grain must remain barely visible, with lower opacity and soft-light blending; preserve the light-mode fade.

Latest output preference: make founder chat streamlined. Hide technical JSON and `intake: complete`/similar status lines. No repeated Needs checking or Founder supplied context labels; a brief is a compact overview, with source/review caveats once per evidence panel. Additional findings belong in Details. Produce work in founder-approved stages rather than generating a whole company at once.

Production persistence must resolve the verified Google user namespace before React mounts, using SHA-256 without migrating the legacy shared cache. Already-open tabs retain loaded state until reload; refresh after an account switch. Browser persistence does not replace backend owner authorization.

## CopilotKit generative UI — 13 October 2026

The founder workspace uses the public CopilotKit headless context and a self-hosted runtime at `/api/copilotkit`, connected to the authenticated request-scoped Agno parent at `/agentos/agents/samurai/agui`. Keep assistant-ui for the existing conversation/composer and native AgentOS endpoints for cancellation and saved-run recovery. Preserve the exact `agents:samurai:run` scope; do not widen JWT scopes. Agno owns history and identity; do not add a process-global CopilotKit thread cache.

The decided A2UI catalog is CompanyBrief, ResearchEvidence, Offer, Pricing, DeliveryPlan and ProspectList. The entry form creates the Company brief first. Subsequent panels follow founder-approved research, strategy and planning stages. Reuse existing BusinessPanel controls and persistent company state through the declarative renderer. Do not auto-generate every stage at intake. Additional declarative compositions use validated text, metric, list and table blocks. Custom components are created when the founder asks for one; never execute generated code in the host page.

The user explicitly requires every generated view to match Samurai's visual direction, with Inter Variable, warm porcelain/peach/graphite light colors, charcoal/champagne dark colors, quiet surfaces, rounded controls and restrained spacing. Generic browser widgets or developer-dashboard styling are unacceptable. Custom frames get embedded Inter and the same theme tokens; keep customer CSS on those tokens, avoid duplicate headings, and verify actual desktop/mobile rendering in both themes. Custom HTML/CSS/JS lives only in an `allow-scripts` iframe without same-origin access, host function bridges, network, navigation or form submission. The trusted shell may send only a height measurement; the host validates the exact iframe source, opaque origin, message shape and bounded integer height. Keep the frame CSP and parent navigation policy intact. Custom input state is local to the frame; the panel definition, not its ephemeral form values, is recovered on reload.

Standard panels must be useful interactive views: brief Overview/Inputs and a refine draft; evidence filters and source disclosures; offer inclusion/review controls; selectable pricing hypotheses; a persistent delivery checklist; searchable/filterable prospects and a persistent shortlist. Do not replace these with paragraphs or raw artifact fields. Custom views inherit the same shared controls through the first important CSS layer, reject inline style attributes via CSP, use a transparent shell and size to their content. User interaction never implies external execution.

Development-only previews are `?preview=panels` and `?preview=intake`. They use labelled illustrative data, isolated preview storage and no AgentOS/provider calls. The production entry excludes this loader. Keep intake preview brief-first, and keep the normal live route unchanged.

The user prefers less default text. Keep idle role descriptions, pricing explanations, prospect reasons, owners and full notes behind existing disclosures. Keep essential values, evidence status and a short draft/sample/assumption indicator visible. Shorten labels and action text without removing callbacks or underlying content.
