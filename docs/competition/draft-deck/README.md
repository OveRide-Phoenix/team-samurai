# Samurai competition draft deck

This directory contains an editable, local-only competition draft. It is not a
submission package and does not claim a current cloud candidate, public links,
portal approval, team status, template compliance, or video completion.

## Build

Use the bundled workspace dependencies discovered with `load_workspace_dependencies`.
Set the runtime and presentation-skill locations for the active machine, then build:

```sh
export RUNTIME_NODE=/path/from/load_workspace_dependencies/node
export RUNTIME_NODE_MODULES=/path/from/load_workspace_dependencies/node_modules
export RUNTIME_PYTHON=/path/from/load_workspace_dependencies/python
export PRESENTATION_SKILL_DIR=/path/to/presentations/skill
export PRESENTATION_FONT_DIR=/System/Library/Fonts/Supplemental # macOS default; override when needed

NODE_PATH="$RUNTIME_NODE_MODULES:$PWD/docs/competition/draft-deck/.compat/modules" \
  "$RUNTIME_NODE" docs/competition/draft-deck/build-deck.mjs
```

The build writes the editable PowerPoint file and rendered PDF to `output/`.
It also writes individual rendered slide PNGs and a montage to `.build/` for
visual review. Speaker notes contain slide-level evidence and claim limits.

The bundled runtime currently omits an internal `#standard-fonts` module needed
for PDF export. The tracked `.compat/modules/#standard-fonts/` adapter maps
that request to the existing `@pdf-lib/standard-fonts` package exposed through
`RUNTIME_NODE_MODULES`. It adds no dependency and is required by the documented
local rebuild command.

## Evidence boundary

The deck is bound to the local evidence named in each slide's notes and to the
competition narrative sources listed in `docs/competition/demo-script.md`.
It uses the original Samurai logo only. It deliberately omits product
screenshots because this task did not re-open an application or validate a new
sanitized capture.

The official deck-template URL was not accessible through the permitted
read-only check on 2026-10-13. Apply an authorized template only after the
portal confirms it; do not treat this local layout as template compliant.
