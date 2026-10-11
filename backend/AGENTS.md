# Backend contributor guide

Read [../AGENTS.md](../AGENTS.md) and [README.md](README.md). Use `agno:agno`, `omo:programming`, and Ponytail; use `omo:debugging` for runtime issues. Consult current Agno documentation through Context7 and verify the installed API before copying examples.

- Python 3.14, uv, Agno AgentOS, Gemini, and PostgreSQL are the selected stack. Register only the ordinary `Samurai` parent Agent for founders; use explicit internal Agno Workflows for the company journey, drafts, and metrics analysis.
- Keep typed configuration at the boundary, secrets server-side, and structured agent outputs validated with Pydantic.
- Keep the parent session limited to the child-session/company/revision binding. The child workflow session owns canonical state and artifact lineage; do not pre-create a service per role or widen the four bounded parent tools.
- Keep Intake, Strategist, Product Manager, and Verifier on preloaded validated skill text with no runtime function tools; keep Researcher on native Gemini Search only. Builder, Marketer, Sales, Analyst, and the parent may use bounded local read-only skill inspection, never external action tools.
- Preserve the child deadline at seven configured model timeouts, cancellation-and-drain behavior, model cap at tool-call budget plus one, and sanitized typed workflow errors. Do not claim queue-backed resumability from persisted sessions.
- Maintain the accepted local boundaries: parent/core journeys preserve unverified claims and `needs_rework`, founder metrics remain conditional, cancellation must stop and drain both runs without late artifacts, and launch drafts remain untested live and draft-only.
- Run Ruff, basedpyright, pytest, and a real HTTP smoke check. Database and Gemini proof must be reported separately.
- Shared bearer access is for local development. Add identity, company isolation, and action authorization before public access.
- Keep `.env` ignored; document configuration in `.env.example`. Never include key values or database URLs with passwords in logs or handoffs.
