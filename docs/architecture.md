# Selected architecture

The owner's Agno proposal selects a workflow-first implementation of AI Idea → Company. The founder supplies a business idea, geography, budget, skills, and goals; the intended result is evidence-backed research, an offer, an MVP roadmap, and a launch kit that can be inspected and revised.

## Boundaries

| Layer | Choice | Status |
|---|---|---|
| Founder workspace | React/Vite, TypeScript, Tailwind, assistant-ui, Radix | Authenticated local intake, SSE progress, cancellation, and saved-result recovery implemented; production IAP sign-in, live brief and reload were verified against recorded deployed revisions, not the current local source |
| Agent runtime | Python, Agno AgentOS, FastAPI | With a configured Gemini model, current source registers one ordinary `Samurai` parent Agent with four bounded tools; local API and Chrome acceptance passed |
| Orchestration | Explicit Agno Workflow stages, with bounded branching/parallelism | The local parent journey, conditional metrics analysis, restart/recall, and cancellation paths passed; launch drafts remain draft-only and were not generated live |
| Intelligence | Gemini API initially; Vertex AI is a future deployment choice | Model configuration present; live access requires credentials |
| Research | Native Gemini Search with bounded retained source evidence | The local API primary retained three unique sources and nine propagated references; the Chrome primary retained five unique sources. Claims remained unverified and verification returned `needs_rework` |
| Records | PostgreSQL locally through Podman; Cloud SQL in production | The backend's app-owned workspace/company rows hold canonical state and revisioned artifact history; actor-scoped AgentOS sessions bind members to those companies. Root Taskfile commands manage only the local Samurai PostgreSQL service; Cloud SQL-backed readback and Agno Live reload were verified in the recorded backend deployment |
| Artifacts | Local immutable workspace-file store with metadata/revision references in PostgreSQL; Cloud Storage is a future adapter | Provider-free workspace-file lifecycle accepted locally; no Cloud Storage adapter or deployment is established |
| Hosting | Cloud Run for the Python backend and Node frontend serving Vite assets | Historical backend/frontend deployment and automatic/manual main rollout acceptance are recorded; they do not show that the current local source is deployed |
| Identity | JWT authentication plus company-scoped backend authorization | RS256 JWT/scope enforcement and owner isolation implemented; Agno Live key retained, additive frontend public key supports verified IAP subjects; the user skipped the live two-account browser exercise |

Agno agents are reasoning roles, not independent services. Samurai is the one founder-facing ordinary Agent; Intake, Researcher, Strategist, Product Manager, Builder, Marketer, Sales, Analyst, and Verifier are internal roles. Explicit workflows own their order and validation. Deterministic code owns identity/session bindings, revision checks, artifact acceptance, limits, calculations, and execution controls. Preserve the root README's product story and architecture map.

## Production request and delivery path

The selected team-only path is browser → Google IAP → Node frontend → AgentOS backend → Cloud SQL/Gemini. The frontend serves the React/Vite build and validates Google's signed IAP assertion, including the exact Cloud Run audience, before deriving `iap:<sub>`. It creates a short-lived RS256 application JWT for each proxied call. Backend trust adds the frontend public key while preserving Agno Live's existing public key. The private frontend signer stays in Secret Manager and is accessible only to the frontend runtime identity. Browser-supplied identity is never authoritative.

IAP restricts team membership; the backend enforces each user's session/run ownership. Existing Agno Live sessions and IAP sessions have distinct identities. Production browser persistence uses a SHA-256 namespace derived from the verified Google identity before React mounts, with no migration from the legacy shared cache. Already-open tabs retain loaded state until reloaded: refresh after switching Google accounts. Browser-local panels and drafts are not a cloud-synchronized company database. The backend retains public transport so Agno Live can supply its application JWT; IAP belongs on the frontend service.

GitHub Actions checks the same source commit before building and deploying immutable image digests, backend first and frontend second. Main pushes and manual main dispatch use restricted OIDC federation. The two-service rollout is not atomic; record both previous revisions and preserve their runtime configuration. Run POSTs are not automatically retried. See [the deployment guide](gcp-deployment.md) for access, rollout, rollback, and acceptance limits.

## Parent, state, and workflow boundaries

The parent has exactly four bounded business tools: run or continue the company journey, create launch drafts, analyze metrics, and read canonical company state. The backend owns canonical state in an app-owned workspace/company row. Authenticated parent sessions and runs remain actor-scoped and bind a member to that company, while company-wide revision fencing serializes accepted state. This prevents model-supplied identity, company, session, or revision values from selecting another company's state.

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

Persistent AgentOS sessions are not, by themselves, proof that a job resumes after a process restart. The native queue runtime at `201f0f7` (formatted at `aa07b46`) and the independently reviewed Task 8 scenario verify, locally, that an active PostgreSQL 18/Redis queue can be restored and completed by a replacement worker with ordered unique terminal events. Task 7's terminal-cancellation/exhaustion UI evidence (`1a4c6a9`) and Task 10's provider-free readiness runner (`76c9884`) are locally accepted. The separate Founder Platform Task 9 acceptance at `5eea8dea4c4469c39e6682879d637d5ca3dcf0f8` records 39 focused PostgreSQL file tests without skips, a full backend result of 266 passed with 105 environment-gated skips, a frontend result of 130 passed, and a provider-free Vite-BFF/IAB owner download-and-deletion flow. It does not claim an authorized GitHub Actions run. These bounded results do not establish a deployed queue: `a84c718` prepares guarded Cloud SQL recovery and `571a378` prepares a Cloud Run queue rollout, but neither performs it. Readiness Task 11 paid-resource authorization remains required before a current cloud-resumability claim. Do not add Celery or a second queue without a demonstrated need.

Financial projections and market estimates must remain labeled assumptions or estimates. Search grounding cannot prove willingness to pay. External actions need explicit approval of the concrete action, and the backend must enforce it.

The configured request boundary limits founder message input to 20,000 characters. The model token and timeout settings and the native parent tool-call limit are configured from the backend environment. Local JWT/API and Chrome acceptance verified port 8000 liveness, authorization and isolation, source-backed primary journeys, recall/reload, and cancellation. These results do not establish deployment or external action capability.

## Local developer architecture

The root Taskfile is the local entry point. It creates missing private configuration without overwriting it, installs locked dependencies, starts only Samurai PostgreSQL through the pinned Podman Compose provider, and runs backend or frontend servers in the foreground. `task health` checks PostgreSQL and AgentOS liveness without a model call.

The saved **Samurai Local** AgentOS connection is a backend technical-console test path: it renders raw structured responses and verifies the parent agent, state persistence, and JWT boundary. The founder workspace is the React/Vite UI preview in `frontend/`. The user requested consolidating the existing UI here, replacing the Next.js health-only scaffold without a framework rewrite. The request/result contract and authenticated local integration are implemented.

## Sources and update policy

Reviewed on 11 October 2026:

- [Agno documentation](https://docs.agno.com/) and [AgentOS security](https://docs.agno.com/agent-os/security/overview).
- Frontend runtime and build commands are recorded in [frontend/README.md](../frontend/README.md) and its committed package manifests.
- [Gemini model catalogue](https://ai.google.dev/gemini-api/docs/models), the runtime is locked to user-approved `gemini-3.5-flash-lite`. Text access was verified locally; Researcher uses native Google Search. Source retention does not establish that a claim is verified.
- [Dependabot ecosystem support](https://docs.github.com/en/code-security/reference/supply-chain-security/supported-ecosystems-and-repositories).

Recheck official docs and release notes when changing a dependency. Commit exact direct versions and generated lockfiles, use locked installs, and run the relevant checks before accepting an upgrade. Preview model/framework releases need an explicit reason and evaluation. Never auto-upgrade the runtime during startup or silently auto-merge updates.
