# Verification

## Qualification target

Version 0.1.0 targets Python 3.11+ for the deterministic controller, `deepagents==0.7.8` for the optional SDK worker, and digest-pinned Python 3.12 Alpine for candidate execution. The default validation path uses no paid model and no live system.

## Required checks

```bash
./scripts/bootstrap-pinned-images.sh sandbox
./scripts/run-local.sh preflight
./scripts/run-local.sh dump-policy
./scripts/run-local.sh test

./scripts/run-local.sh run \
  --scenario retry-success \
  --budget-seconds 120 \
  --max-attempts 2
./scripts/run-local.sh verify --latest

./scripts/install-deepagents-runtime.sh
.deepagents-runtime/bin/python scripts/deepagents_sdk_smoke.py
.deepagents-runtime/bin/python scripts/deepagents_e2e_smoke.py \
  --python .deepagents-runtime/bin/python

python3 scripts/check-public-surface.py
git diff --check
```

The optional service scenario is:

```bash
./scripts/bootstrap-pinned-images.sh all
./scripts/run-local.sh preflight --with-docker
./scripts/run-local.sh run \
  --scenario event-indexing-collision \
  --budget-seconds 900 \
  --max-attempts 2 \
  --with-docker
./scripts/run-local.sh verify --latest
```

## Regression coverage

The unit suite covers:

- input validation, evidence caps, and redaction;
- controller-owned policy and bounded retry feedback;
- fixture candidate contracts and exact patch digests;
- Deep Agents request, environment, process, tool, memory, and cleanup boundaries;
- strict request/result field contracts and public-schema/runtime drift checks;
- forged or malformed worker completion output;
- no-patch success claims;
- SDK process-group timeout termination;
- patch path, symlink, binary, mode, size, and content policy;
- rejection of hidden rename/copy metadata and post-apply path reconciliation;
- AST-only semantic verification that rejects import-time exit, forged output,
  executable annotations/defaults/decorators, extra helpers, dictionary unpacking,
  and unsupported expressions;
- candidate-test Docker flags, durable pre-launch intents, and ownership-scoped restart cleanup;
- directory-bound 128-bit Compose identity, durable pre-launch intent, and refusal of artifact-supplied cleanup targets;
- trusted verifier nonce and completion-marker integrity;
- adversarial early exit, forged success, crash, nonzero exit, and outer timeout;
- exact candidate/receipt/verification/delivery repository, base, head, and digest linkage;
- retry success, exhaustion, rejection, timeout, and cleanup;
- public-surface and CLI contract behavior.

## Trusted verifier rule

Delivery eligibility requires all of the following:

1. The controller starts the pinned verifier with its own nonce and exact candidate/fixture inputs.
2. The verifier parent reaches every required assertion.
3. Exactly one controller-recognized completion marker is observed.
4. The process exits normally with code zero and is neither signaled nor timed out.
5. The receipt binds the candidate, fixture, policy, verifier, command, and attempt identities.
6. A clean workspace accepts the exact patch and produces the exact expected tree digest.
7. The independent verification rerun also passes.
8. Cleanup completes.

An assistant message, worker result, stream event, rubric result, checkpoint value, or exit code without the complete receipt is never sufficient.

## SDK smoke rule

The no-cost smoke constructs the real Deep Agents graph with a scripted local model. It must observe exactly these tools:

```text
edit_file
glob
grep
ls
read_file
write_file
```

It first proves a write outside the controller path allowlist is denied, then performs a real `read_file` followed by `edit_file`, confirms the edit in a temporary root, exercises the OpenAI/Codex harness-profile path, and verifies `delete`, `execute`, `task`, and `write_todos` are absent. It fails on observed Python socket or DNS calls; this is instrumentation, not an OS-level network boundary.

The end-to-end smoke uses the same pinned SDK with a controller-approved scripted edit and no provider transport. It must cross the real `python -I` worker subprocess, Deep Agents graph/tool loop, shadow-Git diff, candidate contract, pinned Docker tests, trusted verifier receipts, clean reapply, draft delivery, independent `verify_run`, and ownership-checked cleanup. A component-level smoke cannot substitute for this composed proof.

## Qualification snapshot: 2026-08-25

- `./scripts/run-local.sh test`: 100 tests completed successfully; the two optional SDK-import tests skipped under the base interpreter as designed.
- `.deepagents-runtime/bin/python -m unittest discover -s tests -v`: 100 tests passed with no skips under `deepagents==0.7.8`.
- Direct SDK smoke: passed with exactly six tools, denied out-of-scope and traversal probes, and zero observed network attempts.
- Controller-to-worker SDK smoke: `SUCCEEDED` in one attempt with `scripted-no-transport`, trusted verification, exact artifact linkage, and complete cleanup.
- Deterministic retry workflow: `SUCCEEDED` on attempt two and `verify --latest` reported no issues.
- Disposable PostgreSQL/Kafka/OpenSearch workflow: `SUCCEEDED` on attempt one, independently verified, and left no matching container, network, or volume.
- Trivy 0.70.0: all four pinned image finding sets matched the unexpired hash-bound baseline.
- Public-surface scan: 93 files, zero issues.
- Ruff 0.12.12 lint and format checks: passed.
- `git diff --check`: passed.

## Interpretation

Passing these checks demonstrates the synthetic reference boundary on the tested host. It does not certify a model provider, Docker/kernel implementation, third-party sandbox, customer repository, live connector, or deployment system. Those require separate qualification under the phase gates in [Implementation plan](implementation-plan.md).
