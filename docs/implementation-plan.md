# Implementation plan

This plan separates the publishable, deterministic core from optional capabilities that need new threat analysis or operator authority. Each phase has an explicit completion gate; a later phase cannot weaken an earlier gate.

## Invariants across every phase

- Deep Agents proposes; controller-owned code decides.
- Candidate work occurs only in a disposable copy.
- The candidate never receives verifier receipts, delivery credentials, or controller state.
- Candidate-code execution is pinned, network-disabled, read-only except for controlled temporary storage, and hard-timed-out.
- Verification binds a controller nonce, exact patch/candidate digest, fixture/policy identity, verifier identity, terminal process status, and completion marker.
- Missing, malformed, stale, forged, crashed, signaled, or timed-out evidence fails closed.
- Delivery remains draft-only until a separately authorized project changes that boundary.
- The public repository contains only synthetic, customer-neutral content.
- Deep Agents, LangGraph, LangChain, LangSmith, and their dependencies remain external.

## Phase 0 — research and boundary selection

Status: complete in the 2026-08-25 snapshot.

Deliverables:

- Complete 40-page Deep Agents Python documentation inventory.
- Complete 16-page Deep Agents Code documentation inventory.
- Source-tree review of the SDK, Code CLI, backends, middleware, profiles, tests, threat models, and evaluations.
- LangGraph checkpoint, store, interrupt, replay, fault-tolerance, and streaming analysis.
- LangSmith open-source/commercial and privacy boundary analysis.
- Version and license snapshot with observed documentation drift.
- Architecture decision: direct SDK core; `dcode` compatibility only as a later isolated adapter.

Gate: public evidence supports a precise architecture and all external/version assumptions are written down.

## Phase 1 — deterministic SDK-native reference

Status: implemented in version 0.1.0.

Deliverables:

- Standard-library controller with synthetic fixture provider as the default.
- Exact `deepagents==0.7.8` and direct provider-adapter versions in the optional runtime; transitive lock qualification remains Phase 2.
- Fresh SDK subprocess per semantic attempt.
- Ephemeral home and provider-specific credential-name allowlist.
- Virtual-root filesystem backend and explicit first-match permission rules ending in deny.
- Exact agent tool set: `ls`, `read_file`, `write_file`, `edit_file`, `glob`, `grep`.
- No shell, deletion, subagent, MCP, hook, plugin, interpreter, memory, checkpointer, store, or LangSmith tracing.
- Controller-derived patch and digest.
- AST-only semantic verification for the synthetic pure-function fixtures, plus hardened outer verifier supervision against early exit, forged success, crash, and timeout.
- Clean-workspace reapply and digest check.
- File-only draft delivery artifacts, exact target linkage, and fail-closed revocation.
- Durable pre-launch cleanup intents for candidate/verifier containers and Compose projects.
- No-cost real-SDK smoke with a scripted model.
- Optional synthetic PostgreSQL/Kafka/OpenSearch scenario.
- Public-surface, unit, workflow, verifier, and formatting checks.

Gate:

```bash
./scripts/bootstrap-pinned-images.sh sandbox
./scripts/run-local.sh preflight
./scripts/run-local.sh dump-policy
./scripts/run-local.sh test
./scripts/run-local.sh run --scenario retry-success --budget-seconds 120 --max-attempts 2
./scripts/run-local.sh verify --latest
./scripts/install-deepagents-runtime.sh
.deepagents-runtime/bin/python scripts/deepagents_sdk_smoke.py
python3 scripts/check-public-surface.py
git diff --check
```

## Phase 2 — reproducible dependency qualification

Entry condition: Phase 1 remains green.

Scope:

- Add a lock generated for supported Python versions and platforms.
- Add dependency provenance and license policy checks.
- Add automated review of new Deep Agents/LangGraph release notes and source defaults.
- Qualify an exact source tag/commit in addition to the package version.
- Add a scheduled SDK construction smoke inside an OS network-disabled runner.
- Document a controlled upgrade procedure with rollback criteria.

Gate: a clean machine can reproduce the runtime from pinned metadata; dependency drift fails CI; no transitive package is vendored.

## Phase 3 — optional `dcode` compatibility lane

Entry condition: a dedicated threat review confirms an OS isolation design.

Scope:

- Run exact-pinned `deepagents-code` in an outer controller-owned container or VM.
- Use an ephemeral home and clean configuration directories.
- Disable updates, price refreshes, plugin updates, memory auto-save, project dotenv loading, Ollama discovery, tracing, and MCP.
- Do not pass `-S`; shell remains disabled.
- Prevent `fetch_url` and all unintended egress at the OS boundary.
- Disable or remove project hooks, plugins, ambient skills, root instructions, and resumable sessions.
- Treat stdout and CLI exit status as untrusted; derive the patch and verify it through the Phase 1 controller.

Gate: adversarial tests prove no network, no ambient-state ingestion, no shell, bounded timeout/cleanup, and no delivery without the trusted verifier receipt. This lane remains optional and cannot become the default merely by being present.

## Phase 4 — controller-owned LangGraph orchestration

Entry condition: persistence is needed for a concrete local workflow, not merely for feature parity.

Scope:

- Model deterministic controller stages as explicit LangGraph nodes.
- Use `langgraph-checkpoint-sqlite==3.1.1` for a single-user local CLI.
- Store the database outside all agent-visible mounts.
- Use controller-issued opaque incident/thread identifiers and a per-incident lock.
- Use synchronous durability for freeze, verifier receipt, eligibility, and review transitions.
- Make every pre-interrupt side effect idempotent or isolate it in an earlier committed node.
- Recompute receipt validity after every resume or replay.
- Place HITL after trusted verification and before draft rendering.

Gate: crash-at-every-super-step, duplicate resume, replay, stale receipt, concurrent same-thread invocation, and stream-forgery tests all fail closed; a valid run resumes correctly after process restart.

## Phase 5 — optional bounded knowledge and memory

Entry condition: a documented use case justifies cross-run state and includes retention/deletion policy.

Scope:

- Keep per-incident short-term state separate from long-term knowledge.
- Make shared memory read-only by default.
- Namespace by repository and synthetic incident domain.
- Require controller authorization for every memory write.
- Apply size, provenance, age, and content filters.
- Keep verifier commands, policy, receipts, eligibility, and delivery state permanently outside memory.
- Use local retrieval by default; remote embeddings require separate opt-in and disclosure review.

Gate: poisoning, namespace collision, last-write-wins conflict, truncation, stale-memory, and deletion tests pass; disabling memory produces identical verification decisions.

## Phase 6 — customer adaptation boundary

Entry condition: a private deployment project supplies an explicit target and authorization. No private material is added here.

Scope:

- Load customer packs only from ignored/private locations through a reviewed schema.
- Broker observability and database evidence through bounded read-only adapters.
- Strip credentials and customer identifiers from public artifacts and logs.
- Require explicit environment, account, repository, and service allowlists.
- Keep source-control and notification outputs in draft mode.

Gate: public-surface checks remain clean; the public fixture suite stays fully runnable without a customer pack; private adapters cannot change compiled controller limits.

## Phase 7 — connector and service hardening

Entry condition: separately approved product work identifies each external system and write authority.

Scope:

- Add brokered read-only connectors one at a time.
- Add authentication, RBAC, rate limits, tenant isolation, audit retention, and kill switches.
- Move multi-user state to PostgreSQL with leases and idempotency keys.
- Add signed or externally anchored attestation storage if immutable audit evidence is required.
- Add a review UI that displays the exact patch, verifier receipt, and digest.
- Keep merge, deployment, and incident mutation disabled unless a later explicit authorization model is designed and independently reviewed.

Gate: threat model, data-flow map, abuse cases, integration tests, operational rollback, and human authorization are complete for each connector. No broad “enable all connectors” step is allowed.

## Explicitly deferred surfaces

The following are not missing Phase 1 work; they are deliberately outside the safe initial boundary:

- automatic merge, deployment, or incident mutation;
- live production credentials or endpoints;
- hosted LangSmith tracing, evaluation, or deployment;
- Agent Server and Studio as runtime requirements;
- writable cross-incident memory;
- MCP, plugins, hooks, dynamic or asynchronous subagents;
- shell access or remote paid sandboxes;
- real-model calls in default CI;
- image-baseline changes unrelated to the existing verifier images;
- release publication.
