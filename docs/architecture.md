# Selected architecture

The owner's Agno proposal selects a workflow-first implementation of AI Idea → Company. The founder supplies a business idea, geography, budget, skills, and goals; the intended result is evidence-backed research, an offer, an MVP roadmap, and a launch kit that can be inspected and revised.

## Boundaries

| Layer | Choice | Status |
|---|---|---|
| Founder workspace | Next.js App Router, TypeScript, Tailwind; shadcn/ui after the design system | Runtime and health endpoint configured; no product screens |
| Agent runtime | Python, Agno AgentOS, FastAPI | With a configured Gemini model, current source registers one ordinary `Samurai` parent Agent with four bounded tools; local API and Chrome acceptance passed |
| Orchestration | Explicit Agno Workflow stages, with bounded branching/parallelism | The local parent journey, conditional metrics analysis, restart/recall, and cancellation paths passed; launch drafts remain draft-only and were not generated live |
| Intelligence | Gemini API initially; Vertex AI is a future deployment choice | Model configuration present; live access requires credentials |
| Research | Native Gemini Search with bounded retained source evidence | The local API primary retained three unique sources and nine propagated references; the Chrome primary retained five unique sources. Claims remained unverified and verification returned `needs_rework` |
| Records | PostgreSQL locally through Podman; Cloud SQL in production | Parent/child AgentOS session model and revisioned `CompanyState` passed local persistence, recall, reload, and cancellation checks; Cloud SQL remains planned |
| Artifacts | Cloud Storage with metadata/revision references in PostgreSQL | Planned |
| Hosting | Cloud Run for the Python service and server-capable Next.js | Planned |
| Identity | JWT authentication plus company-scoped backend authorization | Optional RS256 JWT/scope enforcement and user isolation configured and tested; real control-plane key installed and authenticated discovery verified; company authorization remains pending |

Agno agents are reasoning roles, not independent services. Samurai is the one founder-facing ordinary Agent; Intake, Researcher, Strategist, Product Manager, Builder, Marketer, Sales, Analyst, and Verifier are internal roles. Explicit workflows own their order and validation. Deterministic code owns identity/session bindings, revision checks, artifact acceptance, limits, calculations, and execution controls. Preserve the root README's product story and architecture map.

## Parent, state, and workflow boundaries

The parent has exactly four bounded business tools: run or continue the company journey, create launch drafts, analyze metrics, and read canonical company state. The authenticated parent session owns only its deterministic child-workflow session ID, company ID, and current revision. The child workflow session owns the canonical company state. This keeps one backend-generated company per parent session without allowing model-supplied identity, company, session, or revision values to select another company's state.

Intake, Strategist, Product Manager, and Verifier preload validated local skill text and have no runtime function tools. Researcher has native Gemini Search only. Builder, Marketer, Sales, and Analyst have only local read-only skill functions; the parent narrows its local skill inspection to instructions and references. Child workflows have a deadline of seven configured model timeouts (420 seconds by default), cancellation drains child runs, model calls are capped at the tool-call budget plus one, and child failures are converted to sanitized typed errors. These are source-level execution controls, not evidence of a completed provider run.

Canonical state is an accepted, contiguous artifact history. Each artifact has a company ID, revision and input revision, producer, status, payload, founder statements, assumptions, sources, claims, optional measurements, and verification findings. Source URLs and grounding segments establish retained lineage, not truth: claims remain unverified unless a later verifier can support them. Conflicts or missing lineage stop the core journey before strategy and product outputs continue.

The core workflow requires founder context for target customer, geography, budget, founder skills, and goal before research. Builder, Marketer, and Sales workflows require verified strategy and product-plan inputs and produce drafts only. Analyst returns `requires_metrics` for missing or ineligible metric input; when it accepts founder-supplied values, its result remains `based_on_founder_supplied_metrics`. No workflow has a tool for external side effects.

## Build sequence

1. **Foundation:** dependency locks, environment templates, secured AgentOS bootstrap, PostgreSQL, and frontend runtime. Verify startup and authentication without paid model calls.
2. **Research and strategy:** define typed idea-intake, evidence, and business-plan contracts; connect Gemini grounding; retain source URLs, timestamps, supported claims, and assumptions. Add researcher and strategist outputs that subsequent stages consume.
3. **Workflow and verification:** sequence research → strategy → product plan → marketing/sales launch kit → verification. Preserve per-stage state and artifact revisions. Verification checks source support, contradictory claims, numerical assumptions, and applicable artifact checks; unresolved issues return to their owning stage or request human review.
4. **Workspace:** implement the agreed Hark-inspired design system, idea intake, progress, citations, deliverable inspection/editing, and regeneration of one deliverable without restarting the whole workflow.
5. **Demo and deployment:** add user/company isolation, Google Cloud resources, controlled artifact access, and one measured end-to-end demo. Verify deployed behavior separately from local checks.

The first launch kit contains landing-page copy, outreach drafts, ad concepts, and a 30-day action plan. Autonomous code generation, deployment engines, billing, and broad integrations are outside the initial journey. The longer-term seven-role vision remains intact.

## Execution and evidence requirements

Persistent AgentOS sessions are not, by themselves, proof that a job resumes after a process restart. The current parent-agent source has no durable queue and makes no resumable in-progress-work claim. Before promising durable background execution, select the supported Agno durable queue/store, validate compatibility with the locked release, and test restart recovery and side-effect idempotency. Do not add Celery or a second queue without a demonstrated need.

Financial projections and market estimates must remain labeled assumptions or estimates. Search grounding cannot prove willingness to pay. External actions need explicit approval of the concrete action, and the backend must enforce it.

The configured request boundary limits founder message input to 20,000 characters. The model token and timeout settings and the native parent tool-call limit are configured from the backend environment. Local JWT/API and Chrome acceptance verified port 8000 liveness, authorization and isolation, source-backed primary journeys, recall/reload, and cancellation. These results do not establish deployment or external action capability.

## Sources and update policy

Reviewed on 11 October 2026:

- [Agno documentation](https://docs.agno.com/) and [AgentOS security](https://docs.agno.com/agent-os/security/overview).
- [Next.js installation](https://nextjs.org/docs/app/getting-started/installation).
- [Gemini model catalogue](https://ai.google.dev/gemini-api/docs/models), which lists `gemini-3.8-flash` as stable. Availability for the team's account is unverified.
- [shadcn/ui Next.js installation](https://ui.shadcn.com/docs/installation/next).
- [Dependabot ecosystem support](https://docs.github.com/en/code-security/reference/supply-chain-security/supported-ecosystems-and-repositories).

Recheck official docs and release notes when changing a dependency. Commit exact direct versions and generated lockfiles, use locked installs, and run the relevant checks before accepting an upgrade. Preview model/framework releases need an explicit reason and evaluation. Never auto-upgrade the runtime during startup or silently auto-merge updates.
