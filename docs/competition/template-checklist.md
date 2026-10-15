# Submission-template inspection — 16 October 2026

The [recorded Google Slides template](https://docs.google.com/presentation/d/13rg7vW43mEH6DkpuusAE6fdoEylSFz8waNpE4RLzoUg/edit)
opened read-only in the internal browser with the title “Submission Template |
AI Builder Cup”. Its initial slide navigator exposed 12 slides. A subsequent public PowerPoint
export contains 16 slide parts: 14 with text and two without text.
This confirms the contents of that recorded link, not its selection in the
authenticated submission portal.

| Slide | Required content visible in the template | Samurai preparation / remaining work |
| --- | --- | --- |
| 1 | Team name, leader, and problem | Samurai and the founder-coordination problem are drafted; confirm actual team and leader metadata in the portal. |
| 2 | Instructions for downloading and editing a local PowerPoint copy | The public export downloaded successfully after browser export failed; layout adaptation is pending. No edit request was sent. |
| 3 | Idea summary | Adapt the [solution description](solution-description.md). |
| 4 | Differentiation, problem-solving approach, and distinctive value | Explain retained company context, evidence gates, and founder-approved progression without claiming validated business outcomes. |
| 5 | Product features | Separate locally accepted features from historical deployment and proposed capabilities using [local acceptance](../local-acceptance.md). |
| 6 | Process or use-case diagram | Show intake, research, verification, approval, and downstream work, including rework on insufficient evidence. |
| 7 | Optional wireframes | Prefer sanitized captures of the implemented interface; label mockups if used. |
| 8 | Architecture diagram | Use the [architecture guide](../architecture.md); distinguish local queue/storage from deferred cloud rollout. |
| 9 | Technology choices | Use locked repository dependencies; distinguish implemented Google integrations from future Cloud Storage. |
| 10 | Optional cost estimate | Use [cost preparation](../readiness-costs.md), with estimates separated from measured spend. |
| 11 | Prototype screenshots | Capture the final accepted candidate and label local synthetic fixtures; do not reuse private or historical screenshots as current proof. |
| 12 | Prototype performance or benchmark results | Test counts establish correctness coverage, not latency, throughput, or business impact. Supply measured benchmarks or explicitly state that those metrics have not been measured. |
| 13 | Optional additional details and future development | Separate deferred cloud rollout and future integrations from accepted local functionality. |
| 14 | Public repository, three-minute demo, and final product links | Final published links and evaluator access remain pending; do not fill these with inaccessible or historical substitutes. |
| 15–16 | Spare branded slide and closing artwork | PDF inspection confirms slide 15 has a branded header and slide 16 is the closing graphic; both are retained. |

A new [16-slide working draft](template-deck/README.md) now uses the downloaded
layout and has passed local rendering and package checks. The older seven-slide
[draft deck](draft-deck/README.md) is historical preparation. Final acceptance
still needs verified team details, the authorized portal requirements, current
cloud evidence, video, and public/evaluator links.

## Download verification

The public export returned HTTP 200 and a valid PowerPoint ZIP of 705,743 bytes.
SHA-256: `fac56448966ecac0bea3975b7c9c61bf578679ccf4bd252a5f281ed4db90ce77`.
The unmodified source is retained in ignored local evidence; it is not a final
Samurai deck. Its 16 slide XML parts passed ZIP integrity verification.

## Access and evidence limits

The generic web reader could not open the template. The internal browser exposed
the title, read-only mode, and the first 12 slide headings. A Google Workspace PowerPoint
export failed; the next observed state reported sign-out/connection trouble and
disabled downloads. An unauthenticated download from the public export endpoint
then succeeded without browser cookies or credentials. No cloud copy, permission change, edit request, or upload was
performed. The task-created browser tab was closed after inspection.

The [official FAQ](https://aibuildercup.com/Faqs.html), checked the same day,
continues to require a deployed prototype, public repository, solution deck, and
a video shorter than three minutes. This checklist does not verify portal fields,
submission state, final access, or an exact deadline cutoff.
