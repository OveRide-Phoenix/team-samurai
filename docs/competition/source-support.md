# Competition source support

`source-support.json` records a manual semantic assessment for each factual
competition claim. Its key is `<artifact_id>/<claim_id>`; the matching value
repeats both IDs, preserves the verbatim claim, source URL, UTC fetch time,
relevant excerpt, verdict, and rationale. Validate records against
`source-support.schema.json`.

Only an assessor who has read the actual page may mark a claim `supported`.
`unsupported` covers missing or inaccessible support. `conflicting` records
contradictory sources. These assessments do not change application claim
statuses: claims remain `unverified` until the existing workflow resolves them,
and missing or conflicting support remains `needs_rework` for the competition
demo. The empty template is deliberate; no competitor evidence is claimed until
the later live-source adjudication.
