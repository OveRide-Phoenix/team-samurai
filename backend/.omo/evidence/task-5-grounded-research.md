# Task 5 grounded research evidence

## Delivered boundary

`run_research(agent: ResearchAgent, brief: CompanyBrief, *, max_sources: int = 5) -> ResearchResult`
performs one non-streaming Researcher call, parses the provider response at a code-owned boundary,
and retains bounded native Gemini grounding. Provider linkage is never promoted to factual
verification. The Researcher alone enables `Gemini.search`; its provider response is unstructured
because Agno/Gemini structured output was observed to conflict with the code-owned artifact shape.

## Acceptance observations

| Scenario | Invocation | Binary observable | Artifact |
| --- | --- | --- | --- |
| Baseline before Task 5 | `.venv/bin/python -m pytest -q` | exit 0; 44 passed | Recorded in this task session before implementation |
| Focused behavior and regressions | `.venv/bin/python -m pytest tests/test_research.py tests/test_agents.py -q` | exit 0; 20 passed | This ledger; command output recorded in the task transcript |
| Formatting and lint | `.venv/bin/ruff format --check ...` and `.venv/bin/ruff check ...` over Task 5 files | exit 0 | This ledger; command output recorded in the task transcript |
| Static typing | `.venv/bin/basedpyright ...` over Task 5 files | exit 0; 0 errors | This ledger; command output recorded in the task transcript |
| OMo no-excuse rules | `check-no-excuse-rules.py` over Task 5 Python files | exit 0; no violations | This ledger; command output recorded in the task transcript |
| Native Gemini Search smoke | `.venv/bin/python scripts/smoke_research.py --idea 'AI receptionist for Indian dental clinics' --max-sources 3` | exit 0; provider metadata present; 3 search queries; 14 provider citations; 3 retained sources; all claims unverified | `.omo/evidence/task-5-grounded-research.json` |
| Live stderr | Same smoke invocation | 0 bytes | `.omo/evidence/task-5-grounded-research-live-stderr.txt` |
| Prompt-injection containment | `.venv/bin/python -m pytest tests/test_research.py -q -k untrusted_source_injection` | exit 0; injected text retained only as unverified content; one agent call | `.omo/evidence/task-5-grounded-research-error.txt` |
| Credential cleanup | `test ! -e .env` after the smoke | exit 0 | This ledger; `ENV_REMOVED` recorded in the task transcript |

The live JSON contains only sanitized request/model shape, timestamps, source URLs/titles, opaque
source IDs, source-ID linkage, support status, and verification status. It contains no model prose,
claim text, excerpts, prompts, or credentials. Provider citation count can exceed retained source
count because the code deduplicates and applies `max_sources` after provider grounding.

## Adversarial and failure scenarios

- Duplicate URLs, invalid URLs, source caps, segment caps, and claim caps are deterministic and
  covered by `tests/test_research.py`.
- Mapped and unmapped support are explicit. Every retained claim remains `unverified`; URL presence
  is treated as provenance only. No-citation output returns `insufficient_evidence` with no claims.
- Explicit source conflicts are retained in `ResearchArtifact.conflicts`.
- Retrieved prompt injection cannot trigger another tool call or action; the fake agent call count
  remains one and the text is retained only as unverified source content.
- Provider output with an invented artifact discriminator is parsed into a code-owned
  `ResearchArtifact`; fenced JSON is accepted, while malformed content raises `ValidationError`.
- Earlier bounded provider observations included one invented discriminator, one fenced JSON
  response, and calls with zero citations. They were treated only as observations and did not prove
  provider incompatibility. The final acceptance call independently observed grounding metadata.
- The smoke exits nonzero when it cannot retain source lineage, preventing a misleading success.
- The provider call was bounded by the configured request timeout. No retry loop was added.
- Concurrent Task 6 files and edits were preserved and excluded from this Task 5 commit.
- The live `.env` copy was mode 600 and removed immediately. No browser, server, database, or
  background automation process was opened.
