# Architecture

## Authority split

The system has four trust classes:

1. **Controller-owned policy:** repository identity, service/environment allowlists, path prefixes, evidence caps, required test argv, SDK pin, tool surface, attempt ceiling, and deadline.
2. **Untrusted input:** incidents, evidence, prior diagnoses, model output, tool output, and candidate workspace files.
3. **Untrusted candidate author:** either deterministic fixture patches or one fresh Deep Agents SDK worker.
4. **Trusted decision path:** controller patch derivation, policy validation, pinned verifier supervision, exact digest recreation, eligibility, draft rendering, and cleanup.

The agent cannot modify policy, receipts, control state, artifacts, or delivery configuration through its filesystem tools.

## State machine

```text
NEW
  -> VALIDATING
  -> COLLECTING_EVIDENCE
  -> PATCHING
  -> TESTING
  -> RETRYING | VERIFYING | EXHAUSTED | REJECTED | TIMED_OUT
  -> DELIVERING_DRAFTS (only after independent verification)
  -> CLOSED | CLEANUP_FAILED
```

All failure paths end without a mock GitHub draft. A mock notification may record the terminal outcome.

## Candidate boundary

The fixture provider applies reviewed patches through the same candidate contract used by the real adapter. The real adapter:

1. copies the fixture repository into an attempt directory;
2. copies that attempt into a second disposable SDK workspace;
3. initializes a shadow Git repository outside the candidate-visible tree;
4. gives a fresh worker an ephemeral home;
5. starts `deepagents==0.7.8` with no checkpointer, store, memory, skills, or subagents;
6. exposes only `ls`, `read_file`, `write_file`, `edit_file`, `glob`, and `grep` through `FilesystemBackend(virtual_mode=True)`;
7. applies explicit write-prefix permissions followed by default-deny rules;
8. starts the worker in an isolated process group and terminates that group on timeout;
9. ignores model success claims and derives the patch from the shadow Git baseline;
10. deletes the worker directory before writing final execution evidence.

The host process may contact only the explicitly selected model provider. Only provider-specific credential names are forwarded; ambient base-URL and local-host overrides are stripped. Third-party Deep Agents profile entry points are rejected before profile bootstrap. The candidate cannot execute repository code or make tool-driven network calls.

## Verification boundary

Candidate code runs only in the pinned Python Alpine image with:

- network mode `none`;
- read-only root filesystem;
- dropped Linux capabilities;
- `no-new-privileges`;
- bounded memory, CPU, PIDs, and timeout;
- deterministic environment variables;
- read-only workspace and verifier mounts;
- controller-scoped container name, label, and ID file.

The trusted verifier parent owns assertions and the terminal completion marker. Its semantic probe never imports or executes candidate modules: it parses an allowlisted one-function/one-return AST subset and evaluates only bounded data and string operations. Imports, decorators, defaults, executable annotations, helper functions, process control, output calls, and every unsupported expression fail closed. The outer pinned container remains hard-timed-out. A missing marker, process failure, timeout, malformed receipt, or digest mismatch fails.

After tests pass, the controller recreates a clean workspace, reapplies the exact patch, reruns verification, and compares the resulting tree digest with the accepted candidate digest.

The optional PostgreSQL/Kafka/OpenSearch scenario is an additional veto-only exercise, not the acceptance authority. Its unprivileged verifier parses the same narrow candidate AST without importing candidate modules, then uses the resulting values while exercising synthetic services on an internal network. The controller-owned network-disabled verifier must pass first. This service lane must not be reused for customer code, live data, or real credentials without a separate isolation design and review.

## Evidence and artifacts

Each run records:

- controller state and events;
- redacted bounded evidence;
- candidate request and contract;
- exact patch and SHA-256;
- candidate-workspace digest;
- SDK worker version, source digest, capability flags, invocation identifier, and cleanup result when used;
- repository-test and trusted-verifier results;
- clean-reapply verification;
- local draft delivery payloads;
- closeout and cleanup status.

Artifacts are ignored local evidence, not immutable attestations. The verifier receipt and control state are never mounted into the candidate workspace.

## LangGraph and memory

Deep Agents runs on LangGraph internally, but Phase 1 intentionally uses no checkpointer or store. Every attempt receives a fresh graph and process.

A future resumable controller may use a controller-owned SQLite checkpointer outside the agent mount. Eligibility transitions must use synchronous durability, opaque controller-issued thread IDs, a per-incident lock, and receipt revalidation after resume or replay. Long-term memory remains a separate opt-in feature and can never store policy or verifier authority.

## Delivery

Delivery writes local JSON mocks only. The system has no source-control token, merge API, deployment credential, notification webhook, or incident mutation capability. Draft rendering revalidates the exact candidate/verifier linkage before writing output.

## Cleanup

Cleanup runs on success, rejection, failure, and timeout. Before every candidate-test/verifier container or Compose project starts, the controller atomically records a cleanup intent bound to the run, attempt, phase, image or Compose-file digest, and a controller-derived name/label. Restart cleanup validates those records, inspects exact ownership, removes only matching resources, and performs a fresh final check. This closes the host-process crash window before ordinary result artifacts exist. Attempt workspaces and the SDK worker directory are also removed. Artifact-supplied names cannot select a target, and a run cannot close successfully when scoped cleanup is incomplete.
