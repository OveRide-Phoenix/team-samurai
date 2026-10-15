# Competition source support

`source-support.json` records a manual semantic assessment for each factual
competition claim. Its key is `<artifact_id>/<claim_id>`; the matching value
repeats both IDs, preserves the verbatim claim, source URL, UTC fetch time,
relevant excerpt, verdict, and rationale. Validate records against
`source-support.schema.json`.

Only an assessor who has read the actual page may mark a claim `supported`.
`unsupported` covers missing or inaccessible support. `conflicting` records
contradictory sources. These assessments do not change application claim
statuses. The current research workflow leaves claims `unverified`; neither its
mapping check nor final journey verification promotes them to `supported`.
Missing or conflicting support remains `needs_rework` for the competition demo.
The empty template is deliberate; no competitor evidence is claimed until the
later live-source adjudication.

Application source excerpts currently retain the provider's generated grounding
segments, not independently fetched page content. Matching a claim to those
segments proves citation lineage only. Read the actual source before completing
this assessment; model agreement, a URL, or a framework reference is insufficient.

An offer gate that requires supported application claims needs a separate
adjudication path before it can accept ordinary research results. A test seeded
with supported claims proves the gate's behavior, not that end-to-end path. The
readiness plan excludes a new claim-review subsystem, so implementing that path
requires an explicit plan-scope decision.
