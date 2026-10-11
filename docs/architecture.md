# Selected architecture

The owner's Agno proposal selects a workflow-first implementation of AI Idea → Company. The founder supplies a business idea, geography, budget, skills, and goals; the intended result is evidence-backed research, an offer, an MVP roadmap, and a launch kit that can be inspected and revised.

## Boundaries

| Layer | Choice | Status |
|---|---|---|
| Founder workspace | Next.js App Router, TypeScript, Tailwind; shadcn/ui after the design system | Runtime and health endpoint configured; no product screens |
| Agent runtime | Python, Agno AgentOS, FastAPI | Local secured bootstrap; optional Gemini researcher registration |
| Orchestration | Explicit Agno Workflow stages, with bounded branching/parallelism | Planned |
| Intelligence | Gemini API initially; Vertex AI is a future deployment choice | Model configuration present; live access requires credentials |
| Research | Google Search grounding with retained source evidence | Planned |
| Records | PostgreSQL locally through Podman; Cloud SQL in production | Local database configuration and Agno database adapter |
| Artifacts | Cloud Storage with metadata/revision references in PostgreSQL | Planned |
| Hosting | Cloud Run for the Python service and server-capable Next.js | Planned |
| Identity | End-user authentication plus company-scoped backend authorization | Planned; a local shared bearer key is only service access control |

Agno agents are reasoning roles, not independent services. Workflow state connects their inputs and outputs. Deterministic code must own validation, authorization, calculations, and execution controls. Preserve the root README's product story and architecture map.

## Build sequence

1. **Foundation:** dependency locks, environment templates, secured AgentOS bootstrap, PostgreSQL, and frontend runtime. Verify startup and authentication without paid model calls.
2. **Research and strategy:** define typed idea-intake, evidence, and business-plan contracts; connect Gemini grounding; retain source URLs, timestamps, supported claims, and assumptions. Add researcher and strategist outputs that subsequent stages consume.
3. **Workflow and verification:** sequence research → strategy → product plan → marketing/sales launch kit → verification. Preserve per-stage state and artifact revisions. Verification checks source support, contradictory claims, numerical assumptions, and applicable artifact checks; unresolved issues return to their owning stage or request human review.
4. **Workspace:** implement the agreed Hark-inspired design system, idea intake, progress, citations, deliverable inspection/editing, and regeneration of one deliverable without restarting the whole workflow.
5. **Demo and deployment:** add user/company isolation, Google Cloud resources, controlled artifact access, and one measured end-to-end demo. Verify deployed behavior separately from local checks.

The first launch kit contains landing-page copy, outreach drafts, ad concepts, and a 30-day action plan. Autonomous code generation, deployment engines, billing, and broad integrations are outside the initial journey. The longer-term seven-role vision remains intact.

## Execution and evidence requirements

Persistent AgentOS sessions are not, by themselves, proof that a job resumes after a process restart. Before promising durable background execution, select the supported Agno durable queue/store, validate compatibility with the locked release, and test restart recovery and side-effect idempotency. Do not add Celery or a second queue without a demonstrated need.

Financial projections and market estimates must remain labeled assumptions or estimates. Search grounding cannot prove willingness to pay. External actions need explicit approval of the concrete action, and the backend must enforce it.

## Sources and update policy

Reviewed on 11 October 2026:

- [Agno documentation](https://docs.agno.com/) and [AgentOS security](https://docs.agno.com/agent-os/security/overview).
- [Next.js installation](https://nextjs.org/docs/app/getting-started/installation).
- [Gemini model catalogue](https://ai.google.dev/gemini-api/docs/models), which lists `gemini-3.8-flash` as stable. Availability for the team's account is unverified.
- [shadcn/ui Next.js installation](https://ui.shadcn.com/docs/installation/next).
- [Dependabot ecosystem support](https://docs.github.com/en/code-security/reference/supply-chain-security/supported-ecosystems-and-repositories).

Recheck official docs and release notes when changing a dependency. Commit exact direct versions and generated lockfiles, use locked installs, and run the relevant checks before accepting an upgrade. Preview model/framework releases need an explicit reason and evaluation. Never auto-upgrade the runtime during startup or silently auto-merge updates.
