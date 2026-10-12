# Samurai UI

The React/Vite founder workspace for AI Idea → Company. New companies use the configured local AgentOS backend; existing and demo companies retain labelled Preview mode. Live Gemini runs may incur provider charges. The workspace does not send, publish or deploy; the production Node proxy uses team-only Google IAP, with Google sign-in, live brief creation and reload verified.

## Run locally

From the repository root, use `task frontend:setup` and `task frontend:dev`. Alternatively, use Node 24 from `frontend/`, then:

```sh
npm ci
npm run dev
```

Open http://127.0.0.1:4173. The former Next.js `/api/health` scaffold has been replaced. The server binds to loopback only.

## Included

- Hark-inspired atmospheric workspace, frosted Home panels, floating navigation, and top blur.
- assistant-ui conversation runtime, message primitives, composer, cancellation, and custom tool rendering.
- Interactive prospect filtering and shortlisting, offer review, pricing views, and pinning to Home.
- Company view, local search (Cmd/Ctrl+K), light/dark modes, and accessible Radix dialogs.
- Fresh landing and empty-company states, with an always-present preview team.
- Multiple companies with isolated conversations, pinned panels, shortlists, and draft reviews.
- Browser-local persistence; local preview retains the original dental-preview migration. Production caches use a SHA-256 namespace for the verified Google user before React mounts, without importing the legacy shared cache. Refresh after switching Google accounts; already-open tabs retain their loaded state until reload.
- Inline search focused by Cmd/Ctrl+K, and subtle reduced-motion-aware transitions.
- Be UI is used selectively for the sliding tab indicator; the core controls keep Samurai styling.
- `liquid-glass-react` adds actual backdrop refraction to the navigation, search and composer without filtering their content. Safari and Firefox support is partial; local verification used Chromium.
- Responsive mobile layout and reduced-motion support.

## Backend handoff

The backend is in `backend/`. New companies use the authenticated native AgentOS transport; legacy/sample companies use the labelled preview transport. See [BACKEND_CONTRACT.md](BACKEND_CONTRACT.md). Validated UI schemas live in `src/model.ts`, the live adapter in `src/agentos.ts`, and preview fixtures in `src/demo.ts`.

Preview companies need no Gemini credentials. Live companies require the ignored server-side configuration described below. Provider secrets never enter the browser.

## Checks

```sh
npm run check
npm run build
npm run test:sites
npm run test:server
```

The build emits `dist/client/` plus Sites packaging. The Cloud Run container serves these assets through the production Node server and proxies the allowed AgentOS API routes. Static hosting alone cannot provide the authenticated live transport. See [Google Cloud deployment and CI/CD](../docs/gcp-deployment.md) for bootstrap, team access, and acceptance status.

## Open-source dependencies

React, Vite, TypeScript, Tailwind CSS, assistant-ui, Radix UI, Lucide, Zod, and Vitest use permissive open-source licenses. Inter is distributed under the SIL Open Font License. No assistant-cloud account or paid UI service is required. Package versions are recorded in `package-lock.json`.

Panels expand inside Home. Use Company or the expand control at the top of the left pane to open the full-width dashboard; Chat with Samurai returns to the retained conversation draft and scroll position. Search opens panels inline, with the full dashboard used on mobile. Settings use a themed dropdown; panel creation choices use a dialog.

Generative UI catalog: offer, prospects, pricing, evidence review, and launch plan. Use Add a panel → Evidence review or Launch plan, or ask “Show sample validation evidence” / “Show sample launch plan”. Preview streams demonstrate template components; live streams render validated backend artifacts. Launch task checkmarks persist per company.

The atmospheric mesh background uses `@paper-design/shaders-react` (Apache-2.0), the shader engine used by Be UI. It freezes under reduced motion and retains the existing CSS atmosphere when WebGL2 is unavailable.

Company panels use masonry columns. Choose Edit card order in the settings dropdown, then drag a handle or use the earlier/later buttons; Done hides these controls. The order is saved per company in this browser. Switch companies from Home; the current company name appears once as a prominent heading. The expanded dashboard has no sidebar rail; its larger team card describes idle roles and shows activity during preview runs.

The landing send button opens three required intake pages fetched from the backend. Idea, customers, location, budget, founder skills/resources and first milestone become the saved brief. Completing intake starts a cancellable live run once on first entry. Back preserves answers; leaving or reloading unfinished onboarding discards that draft. All page/view reveals use an 850 ms blur-and-grain fade, disabled for reduced motion.

### Local UI integration — 11 October 2026

New companies use native AgentOS SSE through the Vite server proxy. Configure `AGENTOS_USER_TOKEN` in ignored `frontend/.env.local` and the matching `JWT_VERIFICATION_KEY` in ignored `backend/.env`; restart the backend after changing its configuration. `GEMINI_MODEL` is locked to `gemini-3.5-flash-lite`, with no fallback. The original 2.5 Flash-Lite request returned HTTP 404 for this new account. The user then authorized 3.5 Flash-Lite on 12 October; verify its access separately. Existing and dental-demo companies retain Preview mode. Never call fixture tests proof of successful Gemini research. Local tokens are development-only. Production verifies Google IAP assertions and mints short-lived per-user JWTs server-side; neither signing keys nor bearer tokens belong in `VITE_` variables.

Team roles expand to show actual workflow start/completion history, retained per company and recovered from scoped backend runs. Missing evidence shows Researcher/Verifier blocked and Strategist waiting. A completed workflow is not proof of customer demand. Research remains insufficient without source evidence; Researcher has native Gemini Search enabled; provider access, quota, and supported source evidence must be checked separately.
