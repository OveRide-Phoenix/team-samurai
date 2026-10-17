# Repair the live company form and chat

Root cause: Kalyan's 4cb82ed/201f0f7 made canonical acceptance require a claimed native queue job. CopilotKit's older b6e65da AG-UI route calls Agent.arun inline. SQLite tests never exercised the PostgreSQL acceptance seam. Current remote main is 8d14d87, already included; no remote changes are missing.

Acceptance:
- Real browser intake -> Gemini -> exactly one accepted intake, readable through owned API and after browser reload; no automatic research.
- Chat retains CopilotKit/AG-UI and OpenUI, validated team scope, cancellation, drafts, owned receipt/run recovery.
- Queue admission validates company membership, immutable operation/stage/revision, deduplication and coordination availability. Never fabricate ownership or weaken save_company_state.
- Read-only chat cannot silently authorize new canonical work. Next-stage actions carry explicit typed approval.
- Provider-free real PostgreSQL/Redis integration regression for this exact path; scoped tests for denial, cancellation and stored results. Then one bounded live brief-first browser journey.
- Preserve dirty UI work, existing companies, quotas and auth; no push/deploy. Backend stopped after verification.

Implementation:
1. Share existing native work-admission validation with AG-UI. Typed optional work approval, default read-only.
2. Enqueue AG-UI via the existing AgentOS QueueWorker; translate its native events to current AG-UI stream. Preserve request run IDs and durable receipts.
3. Rebuild worker parent for validated team metadata; keep immutable intent guards and read-only constraints.
4. Carry form/next-stage approvals and stable submission ID through CopilotKit; repair narrow proxy recovery routes and frontend pre-run recovery state where necessary.
5. Tests, real browser desktop/mobile, persistence readback, documentation and cleanup.


Verified outcome (16 October 2026): real CycleNest form accepted one Gemini
intake at revision 1; receipt COMPLETED on worker attempt 1; owned company/run
reads and reload matched. No research started. Other nine company hashes and
revisions were preserved. Canonical reservation integration, duplicate/stale/
foreign denial, cancellation, replay and read-only constraints have provider-free
PostgreSQL/Redis regression coverage. Desktop/mobile checked with brief first.
No push or deployment. Local evidence remains ignored under `.omo/evidence`.

Final checks: 417 provider-free backend passes (149 environment-gated skips),
76 PostgreSQL/Redis regression passes without skips, 164 frontend, 61 server,
4 Sites packaging; build, Ruff, BasedPyright and diff whitespace checks pass.
Native next-stage draft opens/persists without submission; no later-stage
work intent exists. Local backend and task-started PostgreSQL/Redis stopped.
