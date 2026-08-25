# Continuation handoff: 2026-08-25

Read this document first after `AGENTS.md` when continuing work on the public repository.

## Repository

- Remote: `https://github.com/AtharvaBondre/deepagents-incident-workflow.git`
- Default branch: `main`
- Implementation baseline before this handoff: `cd17af0d8de8bd0f6e93b6151a15bff8d6b4c11f`
- License: Apache-2.0
- Status: public, customer-neutral, local-first experimental reference implementation.
- Product reference: public Hermes Incident Workflow commit `48cbf19bfc82305be8467607647ec14d4fc4192e`.

Do not add private customer material, credentials, internal endpoints, retained model sessions, billing data, private repository code, or absolute local machine paths. Deep Agents, LangGraph, LangChain, LangSmith, and their dependencies stay external.

## Product objective

The workflow demonstrates a bounded remediation loop:

1. A controller validates a synthetic incident and collects bounded evidence.
2. A fixture provider or fresh Deep Agents worker proposes a candidate in a disposable workspace.
3. The controller derives the exact patch and rejects policy violations.
4. Pinned, network-disabled tests and controller-owned verifiers assess the candidate.
5. Trusted receipts bind the run, attempt, patch, candidate, fixture, policy, verifier, command, image, nonce, and terminal process result.
6. The accepted patch is reapplied to a clean baseline and the exact tree digest is reverified.
7. Only local draft delivery artifacts are written, followed by ownership-checked cleanup.

Preserve this rule:

```text
Deep Agents proposes; the controller decides.
```

## Current implementation surface

- `scripts/runner.py`: deterministic state machine, policy, retries, deadlines, patch validation, verifier receipts, delivery linkage, and cleanup.
- `scripts/deepagents_worker.py`: fresh SDK-native candidate worker with the exact six-tool filesystem surface.
- `scripts/deepagents_sdk_smoke.py`: no-cost scripted graph/tool smoke with denied path escape and observed-network checks.
- `scripts/deepagents_e2e_smoke.py`: no-cost full controller-to-worker graph, patch, verifier, delivery, and cleanup smoke.
- `scripts/install-deepagents-runtime.sh`: clean repository-local runtime installation and exact direct-version validation.
- `scripts/run-local.sh`: operator entry point for preflight, tests, runs, verification, cleanup, and policy inspection.
- `scripts/check-public-surface.py`: disclosure, irregular-file, tracked-ignore, JSON, placeholder, and credential-pattern checks.
- `verifiers/`: controller-owned AST-only semantic verification code.
- `compose.event-indexing.yaml`: optional disposable PostgreSQL, Kafka, and OpenSearch scenario.
- `customer-pack-template/`: synthetic placeholders for downstream private adaptation.
- `docs/deepagents-research-2026-08-25.md`: complete Deep Agents, Code CLI, LangGraph, and LangSmith research dossier.
- `docs/hermes-parity.md`: pinned cross-project invariant and parity matrix.
- `docs/implementation-plan.md`: completed Phase 0/1 work and gated Phases 2–7.
- `schemas/deepagents-request.schema.json` and `schemas/deepagents-worker-result.schema.json`: strict public worker-boundary contracts.

## Proven behavior

- 100 controller, provider, verifier, SDK-boundary, cleanup, contract-schema, and public-surface tests pass in the pinned SDK runtime with no skips.
- Early exit, forged success, top-level execution, dictionary unpacking, nonzero exit, signal, crash, verifier timeout, and outer timeout fail closed.
- Exact patch/digest reapplication and delivery linkage pass.
- Retry-success passes on the second attempt and independently verifies.
- The SDK smoke constructs the real `deepagents==0.7.8` graph with no model transport, observes exactly six tools, denies out-of-scope and traversal reads/writes, and observes no socket or DNS call.
- The end-to-end SDK smoke crosses the real controller, `python -I` worker subprocess, Deep Agents graph/tool loop, shadow-Git patch derivation, Docker tests, trusted verifier, clean reapply, draft delivery, independent verification, and cleanup without a provider call.
- The optional event-indexing scenario passes with PostgreSQL, Kafka, and OpenSearch and leaves no project container, network, or volume.
- Public-surface, formatting, image-vulnerability baseline, and Git checks pass.
- GitHub CI covers Python 3.11 and 3.12 for deterministic tests, pinned Ruff, direct SDK smoke, and full controller-to-worker smoke.
- An independent read-only review found no release-blocking correctness or security issue.

## Required validation

From a clean clone:

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

python3 scripts/check-public-surface.py
git diff --check
```

For SDK-facing changes:

```bash
./scripts/install-deepagents-runtime.sh
.deepagents-runtime/bin/python scripts/deepagents_sdk_smoke.py
.deepagents-runtime/bin/python scripts/deepagents_e2e_smoke.py \
  --python .deepagents-runtime/bin/python
./scripts/run-local.sh preflight \
  --require-deepagents \
  --deepagents-python .deepagents-runtime/bin/python
```

For service-facing changes:

```bash
./scripts/bootstrap-pinned-images.sh all
./scripts/run-local.sh preflight --with-docker
./scripts/run-local.sh run \
  --scenario event-indexing-collision \
  --budget-seconds 900 \
  --max-attempts 2 \
  --with-docker
./scripts/run-local.sh verify --latest
python3 scripts/check-image-vulnerabilities.py
```

## Safety boundaries

- No shell, deletion, network tool, MCP, subagent, skill discovery, hook, plugin, interpreter, memory, checkpointer, store, or tracing in the core worker.
- The optional real-model worker is a host process and may contact only the selected provider. Its virtual filesystem is not an OS sandbox.
- Candidate code runs only in the pinned Docker verifier boundary with network disabled.
- A hard controller crash can orphan an opt-in provider-connected worker. Do not use unattended real-model mode until a durable supervisor or independent watchdog is added.
- Local artifacts are mutable audit evidence, not signed attestations.
- Delivery is file-based and draft-only. There is no merge, approval, deployment, production write, or incident mutation.
- Hosted services, live connectors, private packs, and real-model calls require separate authorization and qualification.

## Next safe improvements

Start with Phase 2 in `docs/implementation-plan.md`:

1. Add complete cross-platform transitive dependency locks.
2. Add package provenance and license policy checks.
3. Qualify exact upstream source tags or commits as well as package versions.
4. Run the SDK construction smoke in an OS network-disabled CI boundary.
5. Add controlled upstream release/default-drift review and rollback criteria.
6. Reintroduce dependency-update automation only when a maintainer explicitly authorizes the PR workflow.

Do not start with `dcode`, memory, live connectors, customer packs, releases, or deployment. Those have later phase gates and must not weaken Phase 1.

## Continuation procedure

1. Confirm `origin/main` and read `AGENTS.md`, this handoff, `docs/hermes-parity.md`, and `docs/implementation-plan.md`.
2. Run public-surface, preflight, policy dump, and tests before changing trust-boundary code.
3. Compare relevant controller/verifier changes with the pinned public Hermes reference by invariant, not by line-for-line copying.
4. Keep Deep Agents-specific controls native to its SDK and add regression evidence for every changed invariant.
5. Ask before expanding authority, adding external effects, changing image/baseline policy, publishing, or creating PRs.
