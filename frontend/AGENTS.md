# Frontend contributor guide

Read [../AGENTS.md](../AGENTS.md) and [README.md](README.md). Use Ponytail and `omo:programming`; use `omo:frontend` for React/UI work and `omo:visual-qa` afterward. Consult current Next.js, Tailwind, and shadcn/ui documentation through Context7.

- Next.js App Router with TypeScript and Tailwind CSS is the selected stack. Use npm and the committed `package-lock.json`.
- The current surface is an HTTP health endpoint. Before building product screens, create `DESIGN.md` from the root's Hark-inspired direction and follow the frontend skill's design, component, and dev-tooling gates.
- Use `task frontend:setup` and `task frontend:dev` from the repository root. A healthy port-3000 endpoint does not establish backend integration or the founder experience.
- Use shadcn/ui components when the design system is ready; avoid adding unused component libraries or stock dashboards.
- Keep credentials in server-only configuration. Never expose a service bearer key through `NEXT_PUBLIC_` or the browser bundle.
- Establish identity and company access before proxying authenticated backend operations to browser users. The planned route, form fields, SSE lifecycle, cancellation, and run-read contract is in [../docs/local-development.md](../docs/local-development.md#planned-frontend-to-agentos-contract); the installed `/agentos/docs` is authoritative when implementing it.
- Run `npm run check`, `npm run build`, and real surface checks; UI work also requires browser QA and cleanup of task-opened sessions.
