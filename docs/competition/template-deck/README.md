# Samurai template-based working draft

[Editable PowerPoint](output/samurai-template-working-draft.pptx) and
[PDF preview](output/samurai-template-working-draft.pdf) adapt the downloaded
16-slide competition template. These are working drafts, not submission assets.

The original dimensions, branding, instruction slide, spare branded slide 15,
and closing artwork are retained. Native text remains editable, including the
process and architecture diagrams. Slide 11 contains a sanitized Task 20 local
fixture screenshot; it is labelled and is not evidence of cloud deployment or
customer activity. The older seven-slide deck remains historical preparation.

The draft distinguishes local correctness checks from unmeasured performance and
business outcomes. Team-leader confirmation, current cloud acceptance, final
public links, video, and evaluator access remain pending. See the
[template checklist](../template-checklist.md) and
[local acceptance record](../../local-acceptance.md).

## Rebuild a candidate

Use the bundled Node runtime and packages returned by
`load_workspace_dependencies`. Download the public template linked in the
checklist and verify its recorded SHA-256 before reuse. Supply an authorized,
sanitized local screenshot; do not copy private user or account screens.

```sh
export RUNTIME_NODE=/path/from/load_workspace_dependencies/node
export RUNTIME_NODE_MODULES=/path/from/load_workspace_dependencies/node_modules
export PRESENTATION_FONT_DIR=/System/Library/Fonts/Supplemental

NODE_PATH="$RUNTIME_NODE_MODULES:$PWD/docs/competition/draft-deck/.compat/modules" \
  "$RUNTIME_NODE" docs/competition/template-deck/build-deck.mjs \
  /path/to/verified-template.pptx /path/to/sanitized-screenshot.png \
  .omo/evidence/competition-template/rebuild
```

This writes candidate PPTX/PDF, individual PNG previews, and an object inventory
under ignored local evidence. It does not overwrite the reviewed files here.
Run the presentation skill finalizer and inspect all rendered slides before
replacing these outputs. The accepted working-draft export passed package,
16-slide count, dimensions, font-reference, bullet/heading geometry, and
Artifact Tool re-import checks. Each slide was inspected; the two repaired
slides were re-rendered. This does not establish portal template selection or
PowerPoint-native application acceptance.
