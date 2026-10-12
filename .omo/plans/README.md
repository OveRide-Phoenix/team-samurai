# Tracked plan index

This directory contains portable, reviewable plan summaries. New runtime boulders, attempt ledgers, screenshots, credentials, and local evidence remain ignored; already tracked historical records are retained.

| Plan | Status | What it records |
|---|---|---|
| [Samurai parent-agent completion](samurai-parent-agents.md) | Complete locally | The accepted ordinary Samurai parent, internal workflows, evidence limits, and local API/UI acceptance summary. |
| [Local developer onboarding completion](local-developer-setup.md) | Complete locally | Repeatable local setup, safe PostgreSQL lifecycle, command validation, and documentation boundaries. |
| [Frontend deployment and CI/CD](frontend-deployment-cicd.md) | Complete; automatic/manual rollout verified | Team-only IAP, per-user JWT bridge, additive backend trust, main/manual deployment and rollback. |
| [GCP deployment](gcp-deployment.md) | Deployed; Agno Live accepted | Mumbai Cloud Run, Cloud SQL, Gemini, JWT key rotation, authenticated console chat, and reload persistence passed. |
| [Samurai Founder Platform](samurai-founder-platform.md) | Reviewed plan; Task 1 accepted | The follow-on platform plan is reviewed; only its durable backend baseline acceptance is complete, with later tasks unstarted. |

Current product and onboarding status:

- The parent-agent workflow is locally accepted with source lineage, conditional founder metrics, cancellation, persistence, and technical-console checks.
- Local onboarding commands completed repeatable setup, health, cleanup, and `task check` validation. Git remote state determines whether publication occurred.
- The backend is deployed in Mumbai with JWT, Gemini, and Cloud SQL-backed run-readback checks passed. Agno Live is connected using its public verification key; authenticated chat and reload persistence passed. Public HTTP transport retains application JWT authorization.
- The custom founder UI and local authenticated frontend/backend intake, workflow progress and saved-result recovery are implemented. Gemini 3.5 Flash-Lite intake/research were exercised locally; research stopped honestly at the missing-source gate. The native queue runtime (`201f0f7`, formatted at `aa07b46`), Task 8's independent local PostgreSQL/Redis restore scenario, Task 7's terminal UI proof (`1a4c6a9`), and Task 10's provider-free readiness runner (`76c9884`) establish bounded local recovery. Task 9's combined check passed at `1f841e7` with 26 PostgreSQL tests intentionally skipped and separately covered; its independent terminal review remains pending. Task 11 paid-resource authorization remains open. None of this is a Cloud Run queue deployment. Live strategy beyond the source gate, launch drafts, connected metrics, external actions, and submission remain unverified/pending.
