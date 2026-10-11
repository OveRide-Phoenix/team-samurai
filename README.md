# Team Samurai — AI Idea → Company

An AI company-building workspace, developed as a general-purpose product and for Google AI Builder Cup 2026. Founders describe a business idea and work with one connected system to validate demand, shape an offer, find customers, coordinate delivery, and improve through business feedback.

Software generation is a supporting capability when the company needs it. The product's goal is business progress, not simply generating an app.

## Current status

Product direction, UI principles, and competition requirements are documented in [AGENTS.md](AGENTS.md). Samurai brand assets are available in [assets/samurai-logo](assets/samurai-logo).

The repository has an Agno AgentOS backend bootstrap, a Next.js application with a health endpoint, local PostgreSQL configuration for Podman, environment templates, and locked dependencies. Configuring a Google API key registers a starter Gemini researcher; the company workflow, grounded research, designed UI, end-user authentication, and cloud deployment are still to be built.

The selected stack and phased implementation plan are in [docs/architecture.md](docs/architecture.md). This setup is not yet a functional company-building prototype.

## The idea: “Build my business.”

The founder starts with one question:

> **What do you want to build?**
>
> “An AI receptionist for Indian dental clinics.”

They interact with one company workspace, not seven separate agent chats. Behind that experience, connected specialist roles carry the idea through research, strategy, product definition, execution, customer acquisition, and improvement.

| Role | Produces or discovers |
|---|---|
| **Researcher** | Competitors, pricing, target markets, reviews, and pain points, with sources and uncertainties. |
| **Strategist** | Ideal customer profile (ICP), positioning, pricing, offer, and business model grounded in the research. |
| **Product Manager** | MVP scope, user stories, delivery requirements, architecture when software is needed, and a roadmap. |
| **Builder** | Database schemas, APIs, UI, and deployment configuration for the software the business needs. |
| **Marketer** | Landing pages, Google Ads drafts, social posts, and email campaigns aligned with the offer. |
| **Sales Agent** | Qualified prospect lists, outreach drafts, sales scripts, and objection handling. |
| **Analyst** | Evaluation of measured performance and recommendations that feed back into strategy and execution. |

For example, given connected analytics, the Analyst might report: “Your landing page gets traffic but conversion is only 0.8%. Here are the three changes I'd make.” This is an illustrative scenario, not an observed result or implemented capability.

The journey is **validate demand → shape an offer → build what is needed → find customers → support sales and delivery → measure → improve**. Outputs from each stage inform the next. Documents, generated software, and campaigns support business progress; customers and revenue are not guaranteed.

## Logical architecture

This is the target responsibility map, implemented incrementally with Next.js and Agno AgentOS workflows. It does not require a separate deployed service for each agent.

```mermaid
flowchart TD
    Founder["Founder: Build my business"] --> Workspace["Next.js: conversation, panels, evidence, approvals"]
    Workspace --> Boundary["AgentOS API: identity and action authorization"]
    Boundary --> Orchestrator["Agno Workflow: explicit stages and shared company context"]
    Orchestrator --> Research["Research: Researcher"]
    Orchestrator --> Plan["Plan: Strategist and Product Manager"]
    Orchestrator --> Execute["Execute: Builder, Marketer, and Sales Agent"]
    Research <--> Gemini["Gemini: grounded reasoning and tool use"]
    Plan <--> Gemini
    Execute <--> Gemini
    Research --> Verifier["Verifier: sources, contradictions, artifact checks"]
    Plan --> Verifier
    Execute --> Verifier
    Verifier -->|"Conflicting or insufficient evidence"| Orchestrator
    Verifier -->|"Checked results and explicit limitations"| State["PostgreSQL: company records; Cloud Storage: artifacts"]
    State --> Workspace
    State --> Orchestrator
    Orchestrator --> Approval["Explicit approval for consequential external actions"]
    Approval --> Tools["Authorized integrations and execution"]
    Tools --> Measurements["Real business feedback and measurements"]
    Measurements --> Analyst["Analyst: evaluate and recommend"]
    Analyst <--> Gemini
    Analyst --> Verifier
```

Gemini supports research, planning, execution, and analysis within a coordinated workflow. Deterministic code should handle permissions, validation, arithmetic, persistence, and rendering where appropriate.

The **Verifier** checks whether sources and tool results support claims, identifies contradictory information, and applies suitable checks to generated artifacts. A second model agreeing with the first is not sufficient verification. When evidence conflicts, the system should say, “I found conflicting information. I need to verify this,” and return to the relevant work with the uncertainty visible.

Generated outreach and advertising remain drafts until approved for external execution. Publishing, sending messages, spending money, and deploying require authorization for the specific action. Continuous analysis depends on connected measurements and an implemented execution mechanism.

## Repository layout

```text
team-samurai/
├── AGENTS.md             # Shared contributor instructions and product constraints
├── README.md             # Product overview and logical architecture
├── backend/
│   ├── src/samurai/      # AgentOS application factory
│   ├── pyproject.toml    # Python dependencies and checks; uv.lock pins resolution
│   └── README.md         # Backend setup and boundaries
├── frontend/
│   ├── src/app/          # Next.js App Router; health endpoint first
│   ├── package.json      # Frontend scripts; package-lock.json pins resolution
│   └── README.md         # Frontend setup and ownership
├── compose.yaml          # Local PostgreSQL through Podman
├── docs/architecture.md  # Selected architecture and phased build plan
└── assets/
    └── samurai-logo/     # Existing shared brand assets
```

The backend owns orchestration, execution, verification, integrations, and authorization. The frontend owns the founder experience and will render structured company state. The current frontend serves `/api/health`; product screens are not implemented yet.

## UI direction

A Hark Pro-inspired conversational workspace with an atmospheric background, frosted surfaces, floating controls, and a soft top blur. A persistent left pane shows work in progress, founder decisions, and contextual business panels. Generative UI presents interactive prospects, pricing, offers, campaigns, and performance views as they become useful.

## Intended stack

- Python 3.14, Agno AgentOS 3.1.2, and explicit workflows for backend execution.
- Next.js 16.4.0, React 19.3.0, TypeScript 7.0.2, and Tailwind CSS 4.3.3; shadcn/ui components will follow the design system.
- PostgreSQL locally in Podman, with Cloud SQL as the production target.
- Cloud Run for application hosting and Cloud Storage for generated artifacts.
- Gemini for reasoning and planned Google Search grounding; the configured default is `gemini-3.8-flash`.
- End-user identity and company authorization remain a separate implementation step.

Framework versions were resolved on 11 October 2026. Check the manifests and lockfiles for exact versions. Cloud services remain planned; see AGENTS.md for the agent responsibilities, verification requirements, and submission checklist.

## Local setup

Requirements: Python 3.14, uv, Node.js 24 or 26, npm, and a running Podman machine. Local `.env` files were created in this checkout; new contributors should follow the copy/configuration instructions in the directory guides.

1. Configure the root `.env` from [.env.example](.env.example), then run `uv tool run --from podman-compose podman-compose up -d` from the repository root.
2. Follow [backend/README.md](backend/README.md) to configure the database URL and bearer key, then run `uv sync --locked` and `uv run uvicorn samurai.app:create_app --factory --app-dir src --host 127.0.0.1 --port 8000` inside `backend/`.
3. Run `npm ci` and `npm run dev` inside `frontend/`. Check [frontend health](http://127.0.0.1:3000/api/health) and [backend health](http://127.0.0.1:8000/health).

Health endpoints show process liveness, not proof of Gemini access or a completed business workflow. Keep the shared backend key server-side; this local bootstrap must not be exposed as a multi-user service.

Current Mac limitation: the PostgreSQL container is healthy, but Podman host-port connections timed out during verification. See the [backend setup notes](backend/README.md#current-mac-verification-limit). [Setup verification](docs/setup-verification.md) distinguishes passing checks from unverified integrations.

## Contributing

Start with [AGENTS.md](AGENTS.md), then the [backend guide](backend/README.md) or [frontend guide](frontend/README.md). Use the applicable **OMo and Ponytail skills for planning, coding, and execution**: inspect existing behavior, make the smallest complete change, and verify it through its real surface.

Before implementation, define the intended outcome and affected contracts. Coordinate changes across both directories, preserve existing product and UI decisions, and document architecture decisions where contributors can find them. Include verification evidence and clearly identify anything still planned or unverified.

Backend checks: `uv run ruff check src tests`, `uv run basedpyright`, and `uv run pytest`. Frontend checks: `npm run check` and `npm run build`. Dependency update pull requests are configured in [.github/dependabot.yml](.github/dependabot.yml); they require GitHub activation and review.

[GitHub Actions checks](.github/workflows/checks.yml) run these gates on pushes and pull requests once published. They do not deploy or require cloud credentials.

For the competition, demonstrate a focused end-to-end journey with meaningful Gemini use, visible verification, and clear user value; the full agent vision is not a claim that every role is already implemented.
