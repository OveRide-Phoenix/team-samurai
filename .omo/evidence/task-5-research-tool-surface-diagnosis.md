# Research tool-surface diagnosis

## Recorded failure

The authorized Task 6 journey reached Gemini, then failed closed as
`insufficient_evidence`. Its retained stderr records a provider response containing a
non-text `function_call` part and no successful ordered lineage. The temporary SQLite
database was already removed and no retained artifact contains the function name, so
the name is unknown and must not be inferred.

## Bounded hypotheses

1. **Workflow model configuration drift** — refuted. A local no-provider factory probe
   observed both standalone and workflow Researcher agents as fresh `Gemini` instances
   using model `gemini-3.8-flash`, `search=True`, `tool_choice=None`, `output_schema=None`,
   identical role instructions, and the same two Skills packages.
2. **Native Search and Skills advertise incompatible tool surfaces** — confirmed as a
   structural defect, but not confirmed as the cause of this provider response. Installed
   Agno adds all three `get_skill_*` functions and a system instruction saying the model
   MUST use them. Installed Gemini request construction sends only built-in Google Search
   when `search=True` and disables external functions. The shared prompt also said skill
   access was the only tool surface while the Researcher prompt required Google Search.
3. **Provider/request variability returned no grounding** — still possible and unproven.
   Earlier bounded Task 5 calls included zero-citation observations before one grounded
   success. The complete journey uses a fuller brief, but no comparison call was made.

No causal root-cause claim is made because the failed function name was not retained and
the suspected configuration was not toggled against the provider failure.

## Minimal structural correction

- Researcher keeps its fresh `Gemini(search=True)` model and receives no Agno Skills
  object or unavailable skill-access functions.
- Researcher evidence and action constraints remain directly composed in its system
  instructions; shared wording now refers to the role's configured tool surface.
- Researcher capability metadata reports `google_search`. All other roles keep the two
  validated Skills packages and the three native `get_skill_*` functions.

## Verification

- Failing-first invocation: `.venv/bin/python -m pytest tests/test_agents.py tests/test_research.py -q`
  observed two expected failures because Researcher still had Skills.
- Green invocation: focused Ruff format/check, basedpyright, OMo no-excuse audit, and the
  same focused pytest command.
- Observable: all static checks exited 0 and 20 tests passed.
- Provider calls: none. The company-journey owner retains the single authorized live call.
