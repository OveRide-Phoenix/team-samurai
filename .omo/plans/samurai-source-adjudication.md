# Samurai Research Source Adjudication Before Strategy

## TL;DR
> Summary:      Extend the existing company journey with one internal source-adjudication step between retained Research and Strategy. It fetches the cited public page under a pinned-address SSRF policy, asks the existing no-tool Verifier for one typed semantic assessment batch, validates exact quote/source/revision bindings in code, and appends a second immutable Research revision that can satisfy the unchanged Task 12 offer gate.
> Deliverables:
> - A bounded backend-only HTTP(S) fetcher for retained Research URLs, isolated in one fixed killable helper process per adjudication attempt, with redirect, DNS/address, deadline, media-type, byte, pipe, and cleanup limits.
> - Immutable adjudication records binding the original Research artifact/revision, verbatim claim, source identity/URL, final fetched URL, page-content hash, exact page quote, fetch time, semantic verdict, and rationale.
> - Provider-free parent/workflow/store/queue acceptance from ordinary unverified research to the Task 12 draft offer, plus a separately authorized live Gemini/public-page gate that remains `NOT_RUN` in this scope.
> Effort:       Large
> Risk:         High - the feature performs outbound requests to untrusted URLs and uses a model for semantic support, so both network confinement and fail-closed evidence binding are release-critical.

## Scope
### Must have
- Start only after the current Task 12 offer work is committed and present on the implementation branch. Serialize all edits to `backend/src/samurai/company_workflow.py`, `backend/src/samurai/contracts.py`, and their tests after Task 12; identify the moving gate by `_supported_research_claim`, `_has_critical_contradiction`, `OfferDiagnostic`, and `StrategyArtifact`, not by a guessed line number.
- Keep adjudication inside the existing authenticated Agno company workflow and canonical `CompanyState`. The Research-approved stage authorizes only bounded public-page reads for URLs already retained by Research; it creates no route, tool, public API, database table, frontend control, or independently queryable claim system.
- Preserve the original Research artifact byte-for-byte. Append one new Research artifact revision whose payload points to the exact original Research artifact ID/revision and whose adjudication records retain the exact claim/source/page lineage.
- Fetch each unique cited URL at most once per adjudication attempt, at most five URLs total. Permit only `http` on port 80 and `https` on port 443; reject credentials, fragments, non-public address results, unsafe redirects, and all other schemes/ports.
- Prevent DNS rebinding: resolve A and AAAA records once for each hop, reject the hop if any resolved address is non-global/loopback/private/link-local/reserved/multicast/unspecified (including IPv4-mapped IPv6), connect the socket to one validated address without a second DNS lookup, and preserve the original hostname for `Host`, TLS SNI, and certificate verification. Re-resolve and revalidate every redirect target.
- Bound acquisition to three redirects, a three-second DNS/connect/TLS/write cap, a five-second cap for each header/body read, a twenty-second total acquisition deadline across process start and all URLs, 256 KiB raw bytes per page, 64 KiB normalized visible text per page, and the repository's existing maximum of five sources. Before DNS, connect, TLS handshake, request write, response headers, every body read, and every redirect, compute remaining total time and apply `min(operation_cap, remaining)`; stop when remaining time is non-positive. Accept only `text/html`, `application/xhtml+xml`, and `text/plain`; request identity encoding and reject other content encodings. Send no cookies, authorization, referrer, founder content, or workspace identity.
- Run all blocking resolution/socket work in one short-lived repository-owned helper process for the complete adjudication attempt. The parent starts only the fixed current Python executable plus fixed `source_fetch_helper.py` path, with no shell, empty environment, standard close-fds behavior, `pass_fds=()`, only the three explicit stdio pipes, an isolated temporary working directory, and bounded JSON. Stdin contains only protocol version, at most five retained URLs, and remaining deadline milliseconds; it never contains claims, founder/workspace/session/auth data, prompts, credentials, or model-generated commands. The helper implementation imports and invokes no process-launch API; this is code-surface minimization, not an OS sandbox claim.
- Make the parent deadline authoritative even if child DNS never returns. On success, timeout, parse failure, output overflow, or external cancellation, a shielded cleanup path sends terminate, waits a 250 ms grace, sends kill if still running, waits/reaps the exact child, closes all pipes, and removes the temporary directory within a separate two-second cleanup budget. Cancellation is re-raised only after reap; no artifact is accepted on cleanup failure. Parent stdin is capped at 16 KiB, stdout at 2 MiB, and stderr at 4 KiB; pipe contents and source bodies are never logged.
- Treat page bytes and text as untrusted data. Strip scripts, styles, and non-visible markup; create bounded candidate context without executing page content or giving the Verifier tools/search. Build complete-sentence blocks of at most 1,000 characters without cutting a sentence; rank claim-overlapping anchors deterministically, and retain each selected anchor with its immediately preceding and following blocks in document order so adjacent negation, quotation, qualification, and refutation remain visible. Assess at most two non-overlapping windows, 4 KiB per claim/source pair and 32 KiB for the complete batch. If there is no overlap, more than two relevant windows, an overlong/incomplete sentence, a context window that cannot retain both neighbors, or a pair displaced by the batch limit, record `insufficient` without a model call for that pair. Keep the full bounded normalized text only in memory for exact-quote validation. Prompt injection in a page must remain quoted content and cannot alter IDs, permissions, workflow steps, or external actions.
- Reuse the existing `Role.VERIFIER` agent for one non-streaming semantic assessment call per Research artifact, using Agno's per-run `output_schema` override. The result must cover the exact candidate claim/source pairs once each and use `supported`, `contradicted`, or `insufficient`; inaccessible fetches are generated deterministically without a model call.
- Validate every model decision in code before persistence: IDs must be complete and exact, the claim text and original source URL must match the original Research revision, and every supported/contradicted evidence quote must be a non-truncated contiguous span of at most 500 characters that occurs verbatim in the normalized fetched page text associated with that source/content hash. Concatenate unique validated quotes per source in stable claim order within the existing 2,000-character `SourceReference.excerpt` limit; a decision whose complete quote would exceed either bound is invalid and promotes nothing. Missing, duplicate, extra, malformed, or misbound decisions promote nothing.
- Make semantic relation decisive. Exact quote containment is necessary grounding, not sufficient support: negated, quoted-as-false, refuted, wrong-entity, wrong-date/window, wrong-unit/quantity, speculative, and context-limited statements must be `contradicted` or `insufficient` as applicable.
- Define `supported` narrowly as "this independently fetched source content semantically supports this claim." It is not a claim that the source is authoritative or that the statement is universally true. Corroboration, source quality, observed customer behavior, and factual truth remain separate.
- Leave Task 12's supported-claim and contradiction gates intact. A supported pain claim may unlock a `draft_only` `OfferDiagnostic`; pricing and purchasing power remain `Assumption` values unless separately evidenced, and no willingness-to-pay, demand, or future behavior is inferred from a listed price or a model opinion.
- Preserve existing work-intent ownership, active owner/editor membership, authorization epoch, expected revision, stage approval, idempotency, retry, cancellation, queue attempt, model-call-budget, and atomic acceptance fences. One additional Verifier call keeps the child journey within `CHILD_WORKFLOW_MODEL_CALL_BUDGET = 7`.
- Prove provider-free behavior through the real parent/workflow/store path using unverified ordinary Research plus independently supplied fake fetched page bytes and a typed fake Verifier result. The test must never pre-seed `SourcedClaim.verification_status="supported"` for the end-to-end path.
- Preserve the strict frontend wire boundary by adding only the matching optional/defaulted Research adjudication schema and parser tests in `frontend/src/agentos.ts` and `frontend/src/agentos.test.ts`. Do not add or redesign a visual component; existing evidence panels continue to render validated claims and sources.
- For every changed behavior, run the current focused baseline first, add a failing test that demonstrates the missing behavior, capture that failure, then implement until the focused test and broader provider-free checks pass.
- Update the existing live company-journey smoke to report raw and adjudicated Research revisions, final URL/content hash/exact quote bindings, supported/contradicted outcomes, and Task 12 offer status without logging page bodies, credentials, private addresses, or prompts. Document but do not execute this paid/live gate without separate authorization.

### Must NOT have (guardrails, anti-slop, scope boundaries)
- Do not modify `/Users/bkakumar/Documents/ChatGPT/Samurai/samurai-founder-offer`; use it only to settle and land Task 12 before starting this plan.
- Do not add a general claim-review service, standalone adjudication API, new ArtifactType, migration/table, browser/crawler service, queue, visual UI/redesign, third-party fetch dependency, proxy dependency, vector store, or manual assessor workflow.
- Do not change or weaken `_supported_research_claim`, `_has_critical_contradiction`, `OfferDiagnostic`, Strategy's `draft_only` status, or Task 12's price/purchasing-power assumption rules. Source-adjudication edits around these symbols must be serialized after Task 12.
- Do not mark a claim supported from provider grounding text, citation mapping, URL presence, exact substring alone, founder assertion, framework metadata, another model merely agreeing, or an evidence quote that code cannot bind to the fetched page revision.
- Do not fetch founder-supplied arbitrary URLs, authenticated/private pages, local files, IP metadata endpoints, custom ports, PDFs/media/binaries, or pages requiring cookies/JavaScript/login. Such sources remain inaccessible/insufficient.
- Do not persist full page bodies. Retain only the bounded exact evidence quote/context, final URL, content hash, media type, timestamps, verdict, and rationale needed for provenance and audit.
- Do not auto-retry source fetches inside the step, raise existing queue/model limits, bypass cancellation, overwrite prior Research history, or append a duplicate adjudication revision after an accepted retry/replay.
- Do not launch any subprocess except the single fixed internal source-fetch helper described above. Never use a shell, user/model-provided executable, module, path, argument list, inherited secret environment, or helper child process. This narrow exception supersedes the prior blanket subprocess exclusion only for source acquisition.
- Do not run a paid Gemini/provider call, live public-page smoke, browser session, deployment, push, publication, IAM/access change, or external action under this plan's current authorization.

## Verification strategy
> Zero human intervention - all verification is agent-executed.
- Test decision: baseline + TDD/failing-first with pytest and Vitest, followed by Ruff, basedpyright, existing PostgreSQL/Redis recovery checks, frontend type/lint/build checks, and the repository `task check`; semantic unit tests use a typed fake Verifier, never a live model.
- QA policy: every task has agent-executed scenarios
- Red/green evidence policy: each implementation task's evidence file records the passing pre-change focused baseline, the new test failing for the intended missing behavior, and that same test passing after the implementation.
- Evidence: `<attemptDir>/task-<N>-<slug>.<ext>` — under ulw-loop, `<attemptDir>` is the `currentAttemptDir` from `omo ulw-loop status --json` (`.omo/evidence/ulw/<session>/<goalId>/a<attempt>`); outside ulw-loop use `.omo/evidence/`

## Execution strategy
### Parallel execution waves
> Target 5-8 tasks per wave. <3 per wave (except final) = under-splitting.
> Extract shared dependencies as Wave-1 tasks to maximize parallelism.

Wave 1 (baseline gate; no implementation starts before it passes):
- Task 1: settle and verify the Task 12 baseline and locked Agno override API

Wave 2 (after Wave 1; no source-file overlap):
- Task 2: add immutable adjudication contracts and transition validation
- Task 3: implement the pinned-address bounded source fetcher

Wave 3 (after Wave 2):
- Task 4: build the typed semantic assessment and Research-revision transformer; depends [2, 3]

Wave 4 (after Wave 3):
- Task 5: insert adjudication into the staged company journey; depends [4]

Wave 5 (after Wave 4):
- Task 6: prove the real provider-free parent/store/queue journey and prepare the opt-in live gate; depends [5]

Critical path: Task 1 -> Task 2/Task 3 -> Task 4 -> Task 5 -> Task 6

### Dependency matrix
| Task | Depends on | Blocks | Can parallelize with |
|------|------------|--------|----------------------|
| 1    | none       | 2, 3   | none                 |
| 2    | 1          | 4      | 3                    |
| 3    | 1          | 4      | 2                    |
| 4    | 2, 3       | 5      | none                 |
| 5    | 4          | 6      | none                 |
| 6    | 5          | F1-F4  | none                 |

## Todos
> Implementation + Test = ONE task. Never separate.
> Every task MUST have: References + Acceptance Criteria + QA Scenarios + Commit.

- [x] 1. Settle Task 12 and pin the downstream gate/API baseline

  What to do: Wait for the Task 12 owner to provide its verified local commit, then start source-adjudication implementation only from an integration branch containing that commit. Derive and record the exact Task 12 SHA from the commit that introduces `_supported_research_claim`, rather than relying on a commit subject, and confirm the post-Task12 symbols `_supported_research_claim`, `_has_critical_contradiction`, `OfferDiagnostic`, `StrategyArtifact.offer_diagnostic`, and the `draft_only` Strategy behavior. Re-run and capture the already observed locked `agno==3.1.2` preflight: `Agent.arun` accepts `output_schema` and forwards it into per-run dispatch. Task 4 must prove behavioral nonmutation with a fake model because signature/source inspection alone does not establish it. Do not implement a fallback second agent unless this exact locked API check fails; if it fails, stop this plan as blocked because the selected one-call Verifier design would need replanning.
  Must NOT do: Do not edit, discard, commit, rebase, or merge another worker's dirty Task 12 checkout as part of this task. Do not start `company_workflow.py` or `contracts.py` adjudication edits against pre-Task12 integration.

  Parallelization: Can parallel: NO | Wave 1 | Blocks: [2, 3] | Blocked by: []

  References (executor has NO interview context - be exhaustive):
  - Pattern:  `../samurai-founder-offer/backend/src/samurai/company_workflow.py:_supported_research_claim` - moving Task 12 supported-claim gate; reference by symbol after Task 12 lands.
  - Pattern:  `../samurai-founder-offer/backend/src/samurai/company_workflow.py:_has_critical_contradiction` - Task 12 contradiction gate, including retained Research conflicts.
  - API/Type: `../samurai-founder-offer/backend/src/samurai/contracts.py:OfferDiagnostic` - protected offer diagnostic contract.
  - API/Type: `../samurai-founder-offer/backend/src/samurai/contracts.py:StrategyArtifact` - protected additive Strategy payload.
  - Test:     `../samurai-founder-offer/backend/tests/test_company_workflow.py:test_mixed_supported_and_contradicted_research_requires_rework` - fail-closed Task 12 conflict behavior.
  - Test:     `../samurai-founder-offer/backend/tests/test_parent.py:296` - current supported fixture that must remain only as focused gate proof, not the new ordinary end-to-end fixture.
  - External: `https://docs.agno.com/reference/agents/agent` - official per-run `output_schema` parameter contract; verify it against locked 3.1.2 before use.

  Acceptance criteria (agent-executable only):
  - [ ] `git log --all --format='%H' -S 'def _supported_research_claim' -- backend/src/samurai/company_workflow.py` identifies the Task 12 commit supplied by its owner, `git merge-base --is-ancestor <task12-sha> HEAD` exits 0 on the implementation branch, and the SHA is captured in `<attemptDir>/task-1-task12-baseline.txt`.
  - [ ] `rg -n 'def _supported_research_claim|def _has_critical_contradiction|class OfferDiagnostic|offer_diagnostic: OfferDiagnostic' backend/src/samurai/company_workflow.py backend/src/samurai/contracts.py` finds every protected symbol on the implementation branch.
  - [ ] `uv run --directory backend python -c 'import inspect; from agno.agent import Agent; assert "output_schema" in inspect.signature(Agent.arun).parameters'` exits 0 and the inspected locked source confirms the override is passed per run without assigning `self.output_schema`; Task 4 owns the focused fake-model behavior test that proves the configured schema remains `VerificationArtifact` afterward.
  - [ ] `git -C ../samurai-founder-offer status --short` is unchanged from the recorded pre-task inventory.

  QA scenarios (MANDATORY - task incomplete without these):
  > Name the exact tool AND its exact invocation - not "verify it works". Browser use: in Codex, use `browser:control-in-app-browser` first when available and no authenticated/persistent user browser profile is required; otherwise use Chrome to drive the page, or agent-browser (https://github.com/vercel-labs/agent-browser) when Chrome is unavailable. Computer use: OS-level GUI automation for a non-browser desktop app.
  ```
  Scenario: Task 12 baseline and locked API are present
    Tool:     bash
    Steps:    Run the four acceptance commands above from the new implementation branch and save command output plus `git rev-parse HEAD` to `<attemptDir>/task-1-task12-baseline.txt`.
    Expected: Task 12 is an ancestor; protected symbols exist; locked Agno exposes per-run `output_schema`; the Task 12 checkout inventory is unchanged.
    Evidence: <attemptDir>/task-1-task12-baseline.txt   (attemptDir = currentAttemptDir from `omo ulw-loop status --json`, .omo/evidence/ulw/<session>/<goalId>/a<attempt>)

  Scenario: pre-Task12 or unsupported Agno baseline
    Tool:     bash
    Steps:    Run the same checks against a disposable branch at integration commit `c73d260ca93942a55aaba499b5ad1637c8453894`, or monkeypatch the signature assertion to inspect a callable without `output_schema`.
    Expected: The gate fails before any adjudication source file is edited and records the missing Task 12/API prerequisite.
    Evidence: <attemptDir>/task-1-task12-baseline-error.txt
  ```

  Commit: NO | Message: `N/A` | Files: []

- [x] 2. Add immutable source-adjudication contracts and wire validation

  What to do: After Task 1 passes, run the current backend contract and frontend wire-parser baselines, then add failing tests for the new Research shape before implementation. In the post-Task12 `contracts.py`, add one `SourceAdjudication` contract and backward-compatible optional/defaulted Research payload fields `adjudicated_from_artifact_id`, `adjudicated_from_revision`, and `adjudications`. Each record must bind the original Research artifact ID/revision, claim ID/verbatim text, source ID/original URL, attempted/fetched time, final URL, raw-byte SHA-256, media type, bounded exact evidence quote (empty for `insufficient`/`inaccessible`, at most 500 characters otherwise), verdict (`supported|contradicted|insufficient|inaccessible`), and rationale. Require fetched provenance for every non-inaccessible verdict and forbid it for inaccessible records. Extend `accept_artifact` transition validation so an adjudicated Research revision can only append immediately from the referenced latest raw Research revision; summary/conflicts, claim IDs/text/source IDs, and source IDs/original URLs must match; decision pairs must be complete and unique; supported/contradicted quotes must exist in the new retained source excerpt; and a prior accepted adjudication for the same raw artifact cannot be replayed. Keep raw/legacy Research payloads valid with empty defaults. Mirror this exact optional/defaulted contract in the `artifact_type: 'research'` branch of the frontend's strict payload discriminated union and add parser coverage for both raw and adjudicated payloads.
  Must NOT do: Do not add a new ArtifactType, table, route, top-level store, full page body, confidence probability, source-authority score, mutable status update, or frontend presentation behavior. Do not edit Task 12's OfferDiagnostic or Strategy validators.

  Parallelization: Can parallel: YES | Wave 2 | Blocks: [4] | Blocked by: [1]

  References (executor has NO interview context - be exhaustive):
  - API/Type: `backend/src/samurai/contracts.py:86` - existing `SourceReference` URL/excerpt boundary.
  - API/Type: `backend/src/samurai/contracts.py:95` - existing `SourcedClaim` mapping and verification statuses.
  - API/Type: `backend/src/samurai/contracts.py:255` - existing minimal `ResearchArtifact`; extend compatibly after Task 12.
  - Pattern:  `backend/src/samurai/contracts.py:335` - `ArtifactEnvelope` validates claim/source containment.
  - Pattern:  `backend/src/samurai/contracts.py:402` - `CompanyState` enforces contiguous immutable accepted history.
  - Pattern:  `backend/src/samurai/contracts.py:548` - `accept_artifact` is the shared stale/history transition boundary.
  - Test:     `backend/tests/test_contracts.py:113` - accepted revision and stale-revision test style.
  - Test:     `backend/tests/test_contracts.py:260` - retained-source/forged-provenance rejection style.
  - API/Type: `frontend/src/agentos.ts:31` - strict payload discriminated union; the `artifact_type: 'research'` branch rejects additive keys until its schema is updated.
  - Test:     `frontend/src/agentos.test.ts:8` - canonical Research wire fixture and strict transport/snapshot parsing pattern.

  Acceptance criteria (agent-executable only):
  - [ ] `uv run --directory backend pytest tests/test_contracts.py -k 'adjudication or source or revision'` passes tests for a valid raw->adjudicated append and exact JSON round-trip of every required binding.
  - [ ] Focused tests reject stale raw revision, non-latest raw artifact, altered claim text/source URL, duplicate/missing/extra claim-source decisions, unknown IDs, forged quote/hash/final URL, invalid fetched/inaccessible field combinations, a second accepted adjudication for the same raw artifact, and any attempted rewrite of the raw Research artifact.
  - [ ] An existing pre-adjudication serialized `ResearchArtifact` still validates with empty/default adjudication fields.
  - [ ] The accepted `CompanyState` contains both the unchanged raw Research JSON and the new adjudicated Research revision with contiguous revisions.
  - [ ] `npm --prefix frontend exec -- vitest run src/agentos.test.ts` accepts raw and adjudicated Research results/snapshots, rejects malformed adjudication bindings, and produces the existing evidence panel without a new UI branch.

  QA scenarios (MANDATORY - task incomplete without these):
  > Name the exact tool AND its exact invocation - not "verify it works". Browser use: in Codex, use `browser:control-in-app-browser` first when available and no authenticated/persistent user browser profile is required; otherwise use Chrome to drive the page, or agent-browser (https://github.com/vercel-labs/agent-browser) when Chrome is unavailable. Computer use: OS-level GUI automation for a non-browser desktop app.
  ```
  Scenario: immutable raw-to-adjudicated lineage
    Tool:     bash
    Steps:    Run `uv run --directory backend pytest tests/test_contracts.py -k 'valid_source_adjudication or preserves_raw_research' -vv`, then `npm --prefix frontend exec -- vitest run src/agentos.test.ts`.
    Expected: State revisions are contiguous; the original Research bytes remain exact; the adjudication binds its artifact/revision, verbatim claim, source URL, final URL, hash, quote, verdict, and rationale; strict frontend parsing accepts the same wire contract and renders the existing evidence panel.
    Evidence: <attemptDir>/task-2-adjudication-contracts.txt   (attemptDir = currentAttemptDir from `omo ulw-loop status --json`, .omo/evidence/ulw/<session>/<goalId>/a<attempt>)

  Scenario: stale, forged, or duplicate adjudication
    Tool:     bash
    Steps:    Run `uv run --directory backend pytest tests/test_contracts.py -k 'rejects_adjudication' -vv` with parametrized stale revision, changed claim, foreign source, quote mismatch, duplicate pair, and replay cases.
    Expected: Every case raises the stable validation/transition error and leaves the canonical state JSON/hash unchanged.
    Evidence: <attemptDir>/task-2-adjudication-contracts-error.txt
  ```

  Commit: YES | Message: `feat(research): bind immutable source adjudication` | Files: [backend/src/samurai/contracts.py, backend/tests/test_contracts.py, frontend/src/agentos.ts, frontend/src/agentos.test.ts]

- [x] 3. Implement bounded public-source retrieval in a killable helper process

  What to do: After Task 1 passes, run the current network-boundary baseline and add failing policy, process-lifecycle, and transport tests before implementation. Add `backend/src/samurai/source_fetch.py` as the internal async parent supervisor and `backend/src/samurai/source_fetch_helper.py` as a Python 3.14 standard-library-only child. The parent computes `deadline = anyio.current_time() + 20` before process creation and starts exactly one helper for the complete attempt with `anyio.open_process([sys.executable, "-I", "-S", fixed_absolute_helper_path], stdin=PIPE, stdout=PIPE, stderr=PIPE, cwd=empty_temporary_directory, env={}, pass_fds=(), start_new_session=True)`. `-I -S` disables Python environment/user-site/site initialization; locked AnyIO/Python must retain the standard `close_fds=True` subprocess behavior, so only stdin/stdout/stderr pipes reach the child. Prove descriptor closure with a parent sentinel descriptor. Validate and serialize one JSON request of at most 16 KiB containing only protocol version, at most five deduplicated retained URLs, and `remaining_budget_ms`; write it, close stdin, concurrently drain stdout/stderr under 2-MiB/4-KiB caps, and validate one exact response schema. Wrap process start, request write, response reads, and normal `wait()` in the parent deadline. In a `finally` block shielded from cancellation for at most two additional seconds: send `terminate()`, allow 250 ms for `wait()`, call `kill()` if the child remains, await `wait()` to reap it, close process streams/`aclose()`, and remove the temporary directory. Preserve and re-raise external cancellation only after cleanup; timeout/crash/malformed/oversize output returns sanitized inaccessible results only after reap; cleanup failure is a hard internal failure and cannot accept an artifact.

  In the fixed helper, validate the exact request keys/types and set one monotonic deadline from `min(remaining_budget_ms, 20_000)`. Fetch the URLs sequentially. Before resolution, direct connect, TLS handshake, request write, header read, every body read, and every redirect, compute `remaining = deadline - monotonic()` and use `min(stage_cap, remaining)`; DNS/connect/TLS/write caps are three seconds and each header/body read cap is five seconds. Use a child-main-thread `setitimer` around `getaddrinfo` for the DNS stage, with the parent total deadline/kill as the authoritative backstop if the resolver ignores interruption. Resolve all A/AAAA answers once per hop, normalize IPv4-mapped IPv6, reject the whole hop if any answer is not globally routable, and connect the socket to one validated sockaddr without another lookup. Preserve the original IDNA hostname for `Host`, TLS SNI, and certificate verification; re-resolve/revalidate redirects. Create production TLS contexts only with `ssl.create_default_context()` under the empty environment; before implementation, prove the locked runtime's compiled default CA file/path is present and the empty-environment child loads a non-empty trust store. If that preflight fails, stop Task 3 rather than inheriting `SSL_CERT_FILE`/`SSL_CERT_DIR` or weakening verification. Enforce the existing scheme/port/redirect/media/encoding/raw-byte/visible-text limits, return only typed bounded results, and emit no URL/body/error detail to stderr.

  The production command/path/limits are fixed and not exposed through workflow/API input. Tests may inject a private supervisor command factory only to run a temporary launcher that imports the fixed helper and replaces its internal resolver/dialer: one launcher maps a synthetic public address to an ephemeral loopback TLS server; another writes its PID to `tmp_path` and blocks forever inside the resolver seam. These launchers prove the real parent process lifecycle without a production allow-private/test-mode switch. Test certificate/key material is written only under `tmp_path`, and every server, helper, pipe, process, and temporary file is cleaned in fixture finalizers.
  Must NOT do: Do not use bare `urlopen`, automatic redirects, `httpx` destination resolution, browser automation, `shell=True`, a shell command, an arbitrary/user/model-provided executable/module/path/argument, inherited environment or non-stdio file descriptor, more than one production helper per attempt, process-launch code in the helper, another subprocess use, an unpinned DNS connection, an inherited/custom CA environment override, retries, cookies, authentication, JavaScript, compression, or a new dependency/config/public surface.

  Parallelization: Can parallel: YES | Wave 2 | Blocks: [4] | Blocked by: [1]

  References (executor has NO interview context - be exhaustive):
  - Pattern:  `backend/src/samurai/research.py:27` - existing five-source/ten-source and segment retention bounds to preserve.
  - API/Type: `backend/src/samurai/contracts.py:86` - only retained Research `HttpUrl` values are eligible inputs.
  - API/Type: `backend/uv.lock:98` - locked AnyIO 4.15.1 already supplies `open_process`, bounded byte streams, cancellation scopes, and process terminate/kill/wait/close primitives; add no dependency.
  - Test:     `backend/tests/test_research.py:183` - existing caps and injection test style.
  - Test:     `backend/tests/test_boundaries.py:271` - fixed-interpreter/module subprocess setup and loopback fixture pattern.
  - Test:     `backend/tests/test_boundaries.py:304` - terminate, wait, kill, and reap cleanup pattern.
  - Test:     `backend/tests/test_queue_process.py:73` - bounded repository-owned process launch pattern.
  - Evidence: `.omo/evidence/founder-platform/source-adjudication-cancellation-probe.json` - proves caller cancellation does not terminate a blocked worker thread and is the reason process isolation is mandatory.
  - External: `https://anyio.readthedocs.io/en/stable/subprocesses.html` - official `open_process` and process-stream lifecycle contract; verify locked signatures during the Task 3 baseline.
  - External: `https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html` - validate schemes/domains/IPs, disable or revalidate redirects, and address DNS rebinding.
  - External: `https://docs.python.org/3/library/ipaddress.html` - classify every resolved IPv4/IPv6 address.
  - External: `https://docs.python.org/3/library/socket.html#socket.getaddrinfo` - resolve and retain the exact sockaddr used for connection.
  - External: `https://docs.python.org/3/library/http.client.html` - bounded HTTP response parsing over the pinned connection.
  - External: `https://docs.python.org/3/library/ssl.html#ssl.create_default_context` - production TLS trust and hostname verification must come from the locked runtime's default verified context under the empty environment.
  - External: `https://docs.python.org/3/library/ssl.html#ssl.SSLContext.wrap_socket` - preserve TLS SNI and certificate verification for the original hostname.
  - External: `https://www.rfc-editor.org/rfc/rfc9110.html#section-8.6` - do not trust Content-Length as the byte limit; enforce the streaming cap.

  Acceptance criteria (agent-executable only):
  - [ ] `uv run --directory backend pytest tests/test_source_fetch.py` passes without opening a public network connection; local integration cases use only ephemeral loopback fixtures behind the test-only launcher seam.
  - [ ] Process-spawn tests assert exactly `[sys.executable, "-I", "-S", fixed_absolute_helper_path]`, one child per attempt, empty environment, `pass_fds=()`, standard close-fds behavior with only explicit stdio pipes, isolated temporary `cwd`, no shell, 16-KiB stdin/2-MiB stdout/4-KiB stderr caps, exact JSON keys, and absence of claim/founder/workspace/session/auth/prompt/credential data; a deliberately open parent sentinel descriptor is inaccessible in the child.
  - [ ] An empty-environment child preflight records `ssl.get_default_verify_paths()`, confirms the compiled CA file/path exists, and asserts `ssl.create_default_context().get_ca_certs()` is non-empty; no CA environment variable, disabled hostname check, or unverified context is introduced.
  - [ ] Deadline tests use an injected subsecond `_ProcessLimits` only inside tests and prove the parent budget starts before spawn; the child receives only remaining milliseconds; DNS, connect, TLS, write, header, every body read, and redirect use `min(stage_cap, remaining)` from the single helper deadline; no URL or redirect resets it.
  - [ ] Unit tests prove rejection of localhost, RFC1918, link-local, metadata, reserved, multicast, unspecified, mixed public/private DNS answers, IPv4-mapped private IPv6, userinfo, fragments, custom ports, non-HTTP schemes, redirect loops, a safe-to-unsafe redirect, DNS answer changes, invalid TLS hostname/certificate, unsupported status/media/content encoding, slow reads, declared and streamed oversize bodies, and total-deadline exhaustion.
  - [ ] Unit tests prove the socket connects to the exact validated sockaddr while `Host`/TLS SNI use the original hostname, and every redirect performs a fresh full validation before connection.
  - [ ] A valid fake HTTPS response returns final URL, media type, fetch timestamp, SHA-256 of the exact accepted raw bytes, at most 64 KiB normalized visible text, and no script/style/instruction execution.
  - [ ] The real local TLS fixture, driven through the helper subprocess, proves success with the expected hostname/SNI, rejection with a wrong-host certificate, incremental streaming rejection above 256 KiB regardless of `Content-Length`, total-budget exhaustion across redirects/reads, and complete server/process/socket/pipe/temp cleanup; production loopback policy remains rejecting.
  - [ ] The temporary blocked-resolver launcher writes its real child PID, then never returns from the resolver seam. Separate timeout and external-cancellation tests wait for that PID, invoke the supervisor, and before returning assert termination escalation occurred, `wait()` reaped the child (`os.waitpid(pid, WNOHANG)` raises `ChildProcessError`), `os.kill(pid, 0)` raises `ProcessLookupError`, cancellation propagated, no artifact/result was accepted, and no temp/stdout/stderr/log residue remains.
  - [ ] `git diff -- backend/pyproject.toml backend/uv.lock` is empty.

  QA scenarios (MANDATORY - task incomplete without these):
  > Name the exact tool AND its exact invocation - not "verify it works". Browser use: in Codex, use `browser:control-in-app-browser` first when available and no authenticated/persistent user browser profile is required; otherwise use Chrome to drive the page, or agent-browser (https://github.com/vercel-labs/agent-browser) when Chrome is unavailable. Computer use: OS-level GUI automation for a non-browser desktop app.
  ```
  Scenario: pinned helper fetches a local TLS page within one total budget
    Tool:     bash
    Steps:    Run `uv run --directory backend pytest tests/test_source_fetch.py -k 'helper_protocol or local_tls or redirect_revalidation or content_limits or remaining_budget' -vv`; the local-TLS launcher maps only the injected synthetic public address to the fixture and invokes the same fixed helper entrypoint.
    Expected: Exactly one child handles all URLs; one validated sockaddr is used per hop; SNI/Host remain the public hostname; TLS, streaming, hash, redirect, pipe, and total-budget assertions pass; the child is reaped and no public connection or residual server/socket/pipe/temp file remains.
    Evidence: <attemptDir>/task-3-source-fetch.txt   (attemptDir = currentAttemptDir from `omo ulw-loop status --json`, .omo/evidence/ulw/<session>/<goalId>/a<attempt>)

  Scenario: blocked DNS, cancellation, SSRF, and resource-abuse fail closed
    Tool:     bash
    Steps:    Run `uv run --directory backend pytest tests/test_source_fetch.py -k 'blocked_resolver or cancelled_helper or rejects or timeout or oversized' -vv`; for blocked-resolver cases capture the real PID before triggering timeout and external cancellation, then assert process absence and reap as specified above.
    Expected: Timeout/cancellation completes only after terminate/kill/wait cleanup; no child, pipe, socket, temp file, or log survives; unsafe cases return a stable sanitized failure before private connection/body persistence; no retry or second unvalidated resolution occurs.
    Evidence: <attemptDir>/task-3-source-fetch-error.txt
  ```

  Commit: YES | Message: `feat(research): isolate bounded source retrieval` | Files: [backend/src/samurai/source_fetch.py, backend/src/samurai/source_fetch_helper.py, backend/tests/test_source_fetch.py]

- [x] 4. Semantically adjudicate fetched source content and build the next Research revision

  What to do: Run the focused adjudication baseline and add failing semantic/binding/context tests before implementation. Add `backend/src/samurai/source_adjudication.py`. Fetch unique URLs once. Build complete-sentence blocks of at most 1,000 characters without cutting sentences. Rank claim-overlapping anchors deterministically; for each of at most two non-overlapping windows, retain the anchor plus its immediately preceding and following blocks in document order. If there is no overlap, more than two relevant windows, an overlong/incomplete sentence, missing adjacent context, a pair window would exceed 4 KiB, or the stable claim/source pair would exceed the 32-KiB batch limit, create deterministic `insufficient` for that pair. Submit the remaining fetched claim/source candidates in one non-streaming call to the existing no-tool/search-disabled Verifier with a per-run `SourceAssessmentBatch` schema. The assessment prompt must require exact same-entity/date/window/unit/quantity/modality support, distinguish direct support from contradiction and insufficiency, and explicitly treat page instructions as data. Code must require one decision per submitted candidate, reject unknown/duplicate/missing bindings, and verify every quoted evidence span against the correct full bounded fetched text/hash retained only in memory. Aggregate per claim fail-closed: any valid contradiction wins; otherwise at least one valid support may produce `supported`; otherwise retain `unverified`. Replace supported/contradicted `support_segments` with the validated exact page quote and construct bounded `SourceReference.excerpt` values that contain those quotes. Create deterministic inaccessible and context-incomplete records without a Verifier call. Append one `_ArtifactCandidate`-ready Research payload/envelope input with original summary/conflicts/IDs preserved and findings that state source support is not factual truth.
  Must NOT do: Do not use exact text matching as the verdict, let the model create IDs/URLs/hashes, accept a quote from another source, call the Verifier once per claim/source, give it tools/Search, mutate its configured `VerificationArtifact` output schema, or promote willingness-to-pay/future behavior merely because a source lists a price or makes a marketing assertion.

  Parallelization: Can parallel: NO | Wave 3 | Blocks: [5] | Blocked by: [2, 3]

  References (executor has NO interview context - be exhaustive):
  - Pattern:  `backend/src/samurai/agents.py:124` - existing Verifier role and configured `VerificationArtifact` schema.
  - Pattern:  `backend/src/samurai/agents.py:188` - Verifier has validated instructions but no runtime tools and Search is enabled only for Researcher.
  - Pattern:  `backend/src/samurai/prompts/roles/verifier.md:1` - lineage, support, contradiction, and second-model limitation.
  - Pattern:  `backend/src/samurai/prompts/shared/evidence.md:1` - retrieved content is untrusted and evidence classes remain distinct.
  - Pattern:  `backend/src/samurai/research.py:253` - original claims/IDs arise from retained provider grounding and remain unverified.
  - API/Type: `backend/src/samurai/company_workflow.py:_agent_payload` - existing non-streaming typed-content validation pattern; do not use it unchanged if it cannot pass the per-run schema override.
  - Test:     `backend/tests/test_research.py:236` - injected source content remains content only.
  - External: `https://docs.agno.com/reference/agents/agent` - `Agent.arun(..., output_schema=...)` per-run override, pinned by Task 1 against Agno 3.1.2.

  Acceptance criteria (agent-executable only):
  - [ ] `uv run --directory backend pytest tests/test_source_adjudication.py` passes with a typed fake Verifier and fake fetched pages; no provider or network call occurs.
  - [ ] A direct same-entity/date/unit statement with an exact bound quote becomes `supported`; a direct negation becomes `contradicted`; a quoted/refuted claim, wrong entity, stale date/window, wrong unit/quantity, hedged speculation, truncated context, and unsupported paraphrase remain `insufficient`/`unverified`.
  - [ ] Candidate-context tests assert complete-sentence 1,000-character blocks, at most two anchor windows with preceding/following context, 4-KiB pair and 32-KiB batch ceilings, deterministic overlap/tie/pair ordering, at-most-500-character complete quotes, stable per-source excerpt assembly within 2,000 characters, and exact-quote validation against the full in-memory normalized page rather than only the model excerpt.
  - [ ] A claim repeated in a later negation/refutation window, a quote introduced as false in the adjacent block, more than two relevant windows, an overlong/truncated sentence, a missing neighbor, and a pair displaced by the batch ceiling all retain the contradicting context or fail closed as `insufficient`; none can become supported from an isolated matching sentence.
  - [ ] Source prompt injection cannot alter the complete decision set, IDs, role tools, approval, or output schema; any extra/missing/duplicate/misbound decision or non-verbatim quote promotes no claim.
  - [ ] One Research artifact causes at most one Verifier call, the agent still has `VerificationArtifact` as its configured schema afterward, and inaccessible-only research causes zero Verifier calls.
  - [ ] Multiple decisions aggregate fail-closed: contradiction beats support, support beats only-insufficient, and no evidence leaves the claim unverified; page support never changes Strategy pricing/purchasing-power assumptions.
  - [ ] The returned adjudicated Research candidate preserves the raw artifact's summary/conflicts/claim and source identities, carries complete fetch/assessment provenance, and can pass Task 2's transition validator.

  QA scenarios (MANDATORY - task incomplete without these):
  > Name the exact tool AND its exact invocation - not "verify it works". Browser use: in Codex, use `browser:control-in-app-browser` first when available and no authenticated/persistent user browser profile is required; otherwise use Chrome to drive the page, or agent-browser (https://github.com/vercel-labs/agent-browser) when Chrome is unavailable. Computer use: OS-level GUI automation for a non-browser desktop app.
  ```
  Scenario: independently fetched page semantically supports the claim
    Tool:     bash
    Steps:    Run `uv run --directory backend pytest tests/test_source_adjudication.py -k 'supports_bound_claim or batches_once' -vv` with raw unverified Research, fake fetched HTML, and a typed Verifier decision quoting the page.
    Expected: One Verifier call; exact IDs/hash/quote are code-validated; the next Research revision contains one mapped/supported claim and a finding that support is source-relative, not truth.
    Evidence: <attemptDir>/task-4-semantic-adjudication.txt   (attemptDir = currentAttemptDir from `omo ulw-loop status --json`, .omo/evidence/ulw/<session>/<goalId>/a<attempt>)

  Scenario: negation, context mismatch, and injection fail closed
    Tool:     bash
    Steps:    Run `uv run --directory backend pytest tests/test_source_adjudication.py -k 'negation or wrong_entity or wrong_date or wrong_unit or injection or invalid_binding' -vv`.
    Expected: Contradiction is retained or the claim stays unverified; no invalid quote/decision is promoted; verifier authority/tools/schema remain unchanged.
    Evidence: <attemptDir>/task-4-semantic-adjudication-error.txt
  ```

  Commit: YES | Message: `feat(research): adjudicate claims against fetched sources` | Files: [backend/src/samurai/source_adjudication.py, backend/tests/test_source_adjudication.py]

- [x] 5. Insert adjudication before Strategy without weakening Task 12 or staged execution

  What to do: Run the focused workflow baseline and add failing order/stage/retry/cancellation tests before implementation. After Task 12 is settled, extend `_Journey` with an `adjudicate_sources` executor between `evidence_check` and `strategy`. It consumes the accepted raw Research artifact, calls Task 4, wraps the result as a second `Role.VERIFIER`-produced Research artifact, and saves it through existing `_envelope`/`_save`/`accept_artifact`. If the latest Research artifact is already adjudicated, return it without fetch/model/save; retries and later approved stages must reuse it. Update stage slices so `brief` still stops after two steps, `research` includes evidence check plus adjudication before the founder pause, and `strategy` includes Strategy only after adjudication. Preserve Task 12 `_supported_research_claim` and `_has_critical_contradiction` unchanged: valid support reaches Strategy, retained/assessed contradiction returns `needs_rework`, and absent support returns `needs_input` before the Strategist model runs. Update ordered-lineage, staged resume, final verification, smoke expectations, cancellation, and model-call-count tests for two Research revisions. The workflow cancellation test must use Task 3's real blocked-resolver child launcher through the injected private supervisor seam, capture its PID, cancel the journey, and wait for helper reap before asserting state.
  Must NOT do: Do not edit the settled Task 12 helper bodies, re-run Research after an accepted adjudication, start Strategy on raw/unverified research, save after cancellation, increase `max_retries`, or change approval/queue/model-call limits.

  Parallelization: Can parallel: NO | Wave 4 | Blocks: [6] | Blocked by: [4]

  References (executor has NO interview context - be exhaustive):
  - Pattern:  `backend/src/samurai/company_workflow.py:542` - ordinary Research and raw evidence-check insertion seam.
  - Pattern:  `backend/src/samurai/company_workflow.py:_supported_research_claim` - settled Task 12 gate to preserve exactly.
  - Pattern:  `backend/src/samurai/company_workflow.py:_has_critical_contradiction` - settled Task 12 contradiction behavior to preserve exactly.
  - Pattern:  `backend/src/samurai/company_workflow.py:create_company_workflow` - ordered steps and staged slice ownership; edit only after Task 12.
  - Pattern:  `backend/src/samurai/company_workflow.py:_save` - canonical append through existing transition and store.
  - Pattern:  `backend/src/samurai/workflow_state.py:114` - trusted identity/company/revision loading.
  - Pattern:  `backend/src/samurai/workflow_state.py:154` - history-preserving/atomic save path.
  - Test:     `backend/tests/test_company_workflow.py:684` - current ordered journey and model-call assertions.
  - Test:     `backend/tests/test_company_workflow.py:970` - stale continuation before model work.
  - Test:     `backend/tests/test_company_workflow.py:1004` - staged stop/resume behavior.

  Acceptance criteria (agent-executable only):
  - [ ] `uv run --directory backend pytest tests/test_company_workflow.py -k 'adjudicat or complete_company_journey or stage or stale or cancellation or offer'` passes with no live network/model.
  - [ ] Canonical state contains `intake, research(raw), research(adjudicated), strategy, product_plan, verification` at contiguous revisions `1..6`; `WorkflowResult` exposes only the latest Research snapshot with revisions `[1,3,4,5,6]`, while fresh state readback retains raw revision 2 exactly.
  - [ ] Stage `research` executes `Intake -> Verify brief -> Research -> Verify evidence -> Adjudicate sources -> Await founder decision`; stage `strategy` adds Strategy and stops; resumed `plan` does not repeat Research/fetch/assessment.
  - [ ] Supported evidence invokes the Strategist and creates the existing `draft_only` OfferDiagnostic; no support invokes the Strategist zero times and returns `needs_input`; conflict/contradiction invokes it zero times and returns `needs_rework`.
  - [ ] A retry after accepted adjudication performs zero additional fetches, Verifier assessments, or revision appends; a stale concurrent acceptance loses through the existing revision fence.
  - [ ] Cancellation while the helper is blocked in resolution reaches the supervisor, which performs terminate/kill/wait/close cleanup before propagating cancellation; the captured PID no longer exists and is already reaped, and no late adjudicated artifact or downstream model output is accepted.
  - [ ] Total child model calls are at most six for the full journey and remain below `CHILD_WORKFLOW_MODEL_CALL_BUDGET` without changing the constant.

  QA scenarios (MANDATORY - task incomplete without these):
  > Name the exact tool AND its exact invocation - not "verify it works". Browser use: in Codex, use `browser:control-in-app-browser` first when available and no authenticated/persistent user browser profile is required; otherwise use Chrome to drive the page, or agent-browser (https://github.com/vercel-labs/agent-browser) when Chrome is unavailable. Computer use: OS-level GUI automation for a non-browser desktop app.
  ```
  Scenario: raw research becomes eligible before Strategy
    Tool:     bash
    Steps:    Run `uv run --directory backend pytest tests/test_company_workflow.py -k 'ordinary_research_adjudicates_before_offer or approved_stages_resume' -vv` with unverified Research, fake fetched page content, and typed fake Verifier output.
    Expected: Raw revision 2 is preserved; adjudicated revision 3 is appended; Strategy sees only the validated supported revision and emits the existing draft-only offer; no step repeats on resume.
    Evidence: <attemptDir>/task-5-workflow-adjudication.txt   (attemptDir = currentAttemptDir from `omo ulw-loop status --json`, .omo/evidence/ulw/<session>/<goalId>/a<attempt>)

  Scenario: missing/conflicting evidence, stale retry, and cancellation
    Tool:     bash
    Steps:    Run `uv run --directory backend pytest tests/test_company_workflow.py -k 'inaccessible or contradiction or stale or retry or cancellation' -vv`.
    Expected: Strategy is not called; no unsupported offer is accepted; stale/replay/cancel paths append no duplicate or late artifact and preserve the last accepted hash; the blocked helper PID is killed/reaped and leaves no pipe/temp/log residue before cancellation returns.
    Evidence: <attemptDir>/task-5-workflow-adjudication-error.txt
  ```

  Commit: YES | Message: `feat(founder): adjudicate research before strategy` | Files: [backend/src/samurai/company_workflow.py, backend/tests/test_company_workflow.py]

- [ ] 6. Prove provider-free parent/store/queue acceptance and prepare the separate live gate

  What to do: Run the current parent/store/queue acceptance baseline and add a failing ordinary-research-to-offer test before changing fixtures or smoke expectations. Replace the ordinary parent acceptance path's seeded supported claim with raw mapped/unverified Research, fake acquired page bytes, and a typed fake Verifier assessment; retain a separate focused Task 12 gate unit fixture if needed. Add durable acceptance coverage using the existing workspace/company fixtures: owner/editor authorization epoch recheck, foreign workspace/actor isolation, stale concurrent acceptance, duplicate idempotency, retry reuse, cancellation without a late artifact, fresh PostgreSQL readback of both Research revisions, and queue/provider-call guards. Update `smoke_company_journey.py` to require/report the six-revision state, adjudication provenance, source-relative verdicts, and Task 12 draft offer without emitting full bodies or sensitive prompts. Update `backend/README.md` with the provider-free proof command and a clearly separate opt-in live command/gate. Run all provider-free checks. Record the live Gemini/public-page/browser gate as `NOT_RUN: explicit paid/live authorization required`; do not execute it in this task.
  Must NOT do: Do not count a supported fixture, mocked citation excerpt, local HTML string, or passing provider-free test as live source/provider proof. Do not run the live smoke, browser, provider, deployment, or cloud queue.

  Parallelization: Can parallel: NO | Wave 5 | Blocks: [F1, F2, F3, F4] | Blocked by: [5]

  References (executor has NO interview context - be exhaustive):
  - Pattern:  `backend/src/samurai/parent.py:112` - current child model-call budget of seven.
  - Pattern:  `backend/src/samurai/parent.py:54` - parent creates the existing company workflow; no new public route is needed.
  - Pattern:  `backend/src/samurai/execution_state.py:76` - approved stage ceilings to preserve.
  - Pattern:  `backend/src/samurai/execution_state.py:762` - work-intent binding, authorization epoch, and changed-approval fences.
  - Pattern:  `backend/src/samurai/company_store.py:193` - atomic canonical/mirror acceptance with workspace/revision checks.
  - Test:     `backend/tests/test_parent.py:296` - current seeded supported fixture; do not use it as ordinary end-to-end proof.
  - Test:     `backend/tests/test_company_store_acceptance.py:62` - authorization epoch recheck.
  - Test:     `backend/tests/test_company_store_acceptance.py:142` - concurrent revision race.
  - Test:     `backend/tests/test_queue_process.py:742` - owner-scoped idempotency and no-provider guard.
  - Test:     `backend/tests/test_boundaries.py:921` - cancellation and late-artifact prevention pattern.
  - Pattern:  `backend/scripts/smoke_company_journey.py:65` - sanitized live artifact record and current five-revision terminal condition.
  - Pattern:  `backend/README.md:117` - provider/live evidence and cost authorization boundary.
  - Pattern:  `Taskfile.yml:115` - full provider-free repository check.

  Acceptance criteria (agent-executable only):
  - [ ] `uv run --directory backend pytest tests/test_parent.py -k 'ordinary_research_adjudication_offer' -vv` drives the real parent and company workflow from mapped/unverified Research through fake independent page content and typed fake semantic assessment to the existing draft-only OfferDiagnostic; no `supported` claim is seeded.
  - [ ] `SAMURAI_TEST_DATABASE_URL=<isolated-postgres> SAMURAI_TEST_REDIS_URL=<isolated-redis> uv run --directory backend pytest tests/test_source_adjudication_acceptance.py tests/test_company_store_acceptance.py tests/test_queue_runtime.py tests/test_queue_process.py` passes fresh-readback, foreign actor/workspace, authorization-epoch, stale race, idempotency, retry, cancellation, zero-live-provider/public-network assertions, and captured-helper PID kill/reap/no-residue assertions.
  - [ ] Fresh owner readback contains raw Research revision 2 and adjudicated revision 3 with exact binding/hash/quote; a foreign actor/workspace receives no state/receipt; viewer or changed authorization cannot accept; retry/replay produces no second adjudication/offer.
  - [ ] `task check` passes; `git diff --check` passes; `git diff --exit-code <task12-sha> -- backend/pyproject.toml backend/uv.lock backend/src/samurai/app.py frontend ':(exclude)frontend/src/agentos.ts' ':(exclude)frontend/src/agentos.test.ts'` confirms no dependency, route, or unplanned frontend change.
  - [ ] `backend/scripts/smoke_company_journey.py` fails unless the live result contains both Research revisions, at least one code-bound supported claim, Task 12's draft-only offer, and sanitized provenance; README labels this command paid/live and separately authorized.
  - [ ] `<attemptDir>/task-6-live-gate-not-run.json` contains `{"status":"NOT_RUN","reason":"explicit paid/live authorization required"}` and no provider/browser evidence is claimed.

  QA scenarios (MANDATORY - task incomplete without these):
  > Name the exact tool AND its exact invocation - not "verify it works". Browser use: in Codex, use `browser:control-in-app-browser` first when available and no authenticated/persistent user browser profile is required; otherwise use Chrome to drive the page, or agent-browser (https://github.com/vercel-labs/agent-browser) when Chrome is unavailable. Computer use: OS-level GUI automation for a non-browser desktop app.
  ```
  Scenario: ordinary app research reaches offer provider-free
    Tool:     bash
    Steps:    Run `uv run --directory backend pytest tests/test_parent.py tests/test_source_adjudication_acceptance.py -k 'ordinary_research_adjudication_offer or fresh_readback' -vv` with all public-network/provider entry points patched to fail if called, then run `task check`; the only extra process/socket activity allowed by the full check is Task 3's fixed helper and self-contained loopback TLS fixture.
    Expected: Unverified ordinary Research is retained, fake independently acquired page content is semantically assessed through the typed fake Verifier, canonical readback preserves both Research revisions, and the unchanged Task 12 gate emits one draft-only offer with pricing/purchasing power still assumptions; no public network/provider call occurs.
    Evidence: <attemptDir>/task-6-provider-free-e2e.txt   (attemptDir = currentAttemptDir from `omo ulw-loop status --json`, .omo/evidence/ulw/<session>/<goalId>/a<attempt>)

  Scenario: authorization, stale/replay, inaccessible/conflicting content, and cancellation
    Tool:     bash
    Steps:    Run `SAMURAI_TEST_DATABASE_URL=<isolated-postgres> SAMURAI_TEST_REDIS_URL=<isolated-redis> uv run --directory backend pytest tests/test_source_adjudication_acceptance.py tests/test_company_store_acceptance.py tests/test_queue_runtime.py tests/test_queue_process.py -k 'foreign or authorization or stale or duplicate or retry or cancel or inaccessible or contradiction' -vv`.
    Expected: Every case fails closed; no foreign read/write, unsupported offer, duplicate revision, extra fetch/Verifier call after accepted retry, late post-cancel artifact, live helper PID, unreaped child, open helper pipe, or helper temp/log residue exists.
    Evidence: <attemptDir>/task-6-provider-free-e2e-error.txt

  Scenario: separate live gate remains authorization-gated
    Tool:     bash
    Steps:    Do not start a server or invoke Gemini. Validate the smoke/README contract with `uv run --directory backend pytest tests/test_company_workflow.py -k 'smoke_requires_adjudicated_source' -vv`, then write the exact NOT_RUN JSON specified above.
    Expected: The live command is ready and fail-closed, but no paid/provider/public-page/browser call is made or claimed.
    Evidence: <attemptDir>/task-6-live-gate-not-run.json
  ```

  Commit: YES | Message: `test(founder): prove source-gated offer journey` | Files: [backend/tests/test_parent.py, backend/tests/test_source_adjudication_acceptance.py, backend/tests/queue_process_app.py, backend/tests/test_queue_process.py, backend/scripts/smoke_company_journey.py, backend/README.md]

## Final verification wave (MANDATORY - after all implementation tasks)
> Runs in PARALLEL. ALL must APPROVE. Once all local/provider-free evidence is recorded, report completion without requesting another approval; paid/live, deployment, publication, and access changes remain separately authorized gates.
- [ ] F1. Plan compliance audit - every task done, every acceptance criterion met; confirm Task 12 landed first, raw Research remained immutable, no seeded supported claim was used for end-to-end proof, and the live gate is truthfully `NOT_RUN`. Evidence: `<attemptDir>/final-plan-compliance.md`.
- [ ] F2. Code quality review - diagnostics clean, idioms match, no dead code; inspect the fixed helper command/data boundary, close-fds/empty-environment/default-CA proof, pinned-address transport, single-deadline propagation, terminate/kill/reap cancellation path, per-run Verifier schema override, complete-set/quote validation, and absence of a new dependency/API/table. Evidence: `<attemptDir>/final-code-quality.md`.
- [ ] F3. Real manual QA - execute every provider-free QA scenario against the actual local parent/workflow plus disposable PostgreSQL/Redis, retain command/JSON evidence, and confirm no public network/provider call occurred; Task 3's self-contained loopback TLS fixture and fixed helper child are the only process/network exceptions. Include real blocked-resolver timeout and cancellation evidence with captured PID absence, reap, and no-residue checks. The separate live gate remains unexecuted until explicitly authorized. Evidence: `<attemptDir>/final-manual-qa.md`.
- [ ] F4. Scope fidelity - nothing extra shipped beyond Must-Have, nothing Must-NOT-Have introduced; verify no Task 12 gate relaxation, frontend change beyond the strict Research wire schema/tests, public route/migration/dependency/deploy/access change, full page body, factual-truth overclaim, or willingness-to-pay promotion. Evidence: `<attemptDir>/final-scope-fidelity.md`.

## Commit strategy
- One logical change per commit. Conventional Commits (`<type>(<scope>): <subject>` body + footer).
- Atomic: every commit builds and passes tests on its own.
- No "WIP" / "fix typo squash later" commits on the final branch - clean up before merge.
- Reference the plan file path in the final commit footer: `Plan: .omo/plans/samurai-source-adjudication.md`.
- Apply commits in this order after the Task 12 commit: Task 2 backend contracts + frontend wire schema -> Task 3 safe fetch -> Task 4 semantic adjudication -> Task 5 workflow -> Task 6 acceptance/docs. Tasks 2 and 3 may be developed in parallel, but neither starts until Task 1 passes, and each must be rebased/tested on the Task 12 baseline before its final commit.

## Success criteria
- All Must-Have shipped; all provider-free QA scenarios pass with captured evidence; F1-F4 approved; commit history clean.
- Ordinary application Research starts mapped/unverified, independently acquires bounded actual page content, receives one typed semantic assessment from the existing Verifier, persists exact immutable source/claim/page/revision provenance, and reaches the unchanged Task 12 draft offer only when support is valid.
- Negation, quotation/refutation, wrong entity/date/unit/window, contradiction, inaccessible content, injection, stale revision, duplicate replay, revoked/foreign authority, retry, and cancellation all fail closed without an offer or history rewrite.
- `supported` is described and stored as source-relative factual support, never universal truth; pricing and purchasing power remain assumptions unless separately evidenced.
- No new public API/table/visual-UI/dependency/deployment/access surface exists; the frontend change is limited to strict Research wire-schema compatibility and tests, and no paid/live call is claimed. Live Gemini/public-page/browser acceptance remains an explicit later gate requiring separate authorization.
