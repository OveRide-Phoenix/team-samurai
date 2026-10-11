# Backend contributor guide

Read [../AGENTS.md](../AGENTS.md) and [README.md](README.md). Use `agno:agno`, `omo:programming`, and Ponytail; use `omo:debugging` for runtime issues. Consult current Agno documentation through Context7 and verify the installed API before copying examples.

- Python 3.14, uv, Agno AgentOS, Gemini, and PostgreSQL are the selected stack. Use explicit Agno Workflows for the company journey.
- Keep typed configuration at the boundary, secrets server-side, and structured agent outputs validated with Pydantic.
- Keep the bootstrap small. Add workflow, evidence, and artifact modules when those stages are implemented; do not pre-create an unused service per role.
- Run Ruff, basedpyright, pytest, and a real HTTP smoke check. Database and Gemini proof must be reported separately.
- Shared bearer access is for local development. Add identity, company isolation, and action authorization before public access.
- Keep `.env` ignored; document configuration in `.env.example`. Never include key values or database URLs with passwords in logs or handoffs.
