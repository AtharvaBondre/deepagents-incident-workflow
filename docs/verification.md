# Verification

## Qualification target

The workflow targets Python 3.11/3.12 with `deepagents==0.7.11` and Node
22.23.2 with `deepagents@1.13.2`. Candidate execution remains in the same
digest-pinned Python 3.12 Alpine verifier regardless of SDK language. The
default validation path uses no paid model and no live system.

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

python3 -I scripts/dependency_qualification.py
./scripts/install-deepagents-runtime.sh
.deepagents-runtime/bin/python scripts/deepagents_sdk_smoke.py
.deepagents-runtime/bin/python scripts/deepagents_e2e_smoke.py \
  --python .deepagents-runtime/bin/python
./scripts/run-network-isolated-sdk-smoke.sh

python3 -I scripts/typescript_dependency_qualification.py
./scripts/install-deepagents-typescript-runtime.sh
node --test .deepagents-typescript-runtime/dist/deepagents_worker.test.js
node .deepagents-typescript-runtime/dist/deepagents_sdk_smoke.js
python3 scripts/deepagents_e2e_smoke.py --language typescript --node node
./scripts/run-network-isolated-typescript-sdk-smoke.sh

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
- Python and TypeScript Deep Agents request, environment, process, tool,
  runtime-digest, memory, and cleanup boundaries;
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
- exact Python and npm transitive lock parsing, artifact provenance, license derivation,
  package/source-tag linkage, strict qualification types, UTC cutoffs, official
  host and redirect controls, and atomic snapshot replacement.

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

Each language installs an in-process network guard before loading its SDK,
proves a write outside the controller path allowlist is denied, denies traversal
reads and writes, then performs a real `read_file` followed by `edit_file` and
confirms the edit in a temporary root. The TypeScript guard rejects fetch,
socket-connect, callback DNS, promise DNS, and resolver-instance attempts. The
smoke exercises the OpenAI harness-profile path and verifies delete, execute,
task, and todo tools are absent. This instrumentation is not an OS-level network
boundary.

The two `run-network-isolated-*-sdk-smoke.sh` commands rebuild from the Python
3.12 hash lock or npm integrity lock and repeat the smoke in digest-pinned containers with
Docker network mode `none`. The container has a read-only root, an unprivileged
UID, no capabilities, `no-new-privileges`, bounded CPU/memory/PIDs, controlled
tmpfs mounts, and a 120-second container-execution deadline. Per-run nonce
labels bind cleanup to the exact container and image; missing ownership or
cleanup failure makes the command fail. CI applies a separate 20-minute bound to
the complete image-build-and-run job. The smoke writes only its result into a
fresh controller-owned output mount outside the agent workspace. After the
container stops, the controller validates the exact schema, SDK version, tool
set, network counters, and every boundary outcome. Exit zero or log text without
that trusted record fails closed.

The end-to-end smoke uses the selected pinned SDK with a controller-approved
scripted edit and no provider transport. It must cross the real isolated Python
or Node worker subprocess, Deep Agents graph/tool loop, shadow-Git diff,
candidate contract, pinned Docker tests, trusted verifier receipts, clean
reapply, draft delivery, independent `verify_run`, and ownership-checked
cleanup. A component-level smoke cannot substitute for this composed proof.

## Qualification snapshot: 2026-08-31

- `./scripts/run-local.sh test`: 152 controller and adversarial tests passed;
  the two optional Python SDK-import tests skipped under the base interpreter as
  designed.
- Offline and live qualification passed for both 62-package locks, PyPI
  artifacts and licenses, exact tags, scoped source heads, and the recorded
  57-page Deep Agents documentation inventory. Deep Agents Code 0.1.65 remains
  review-only and is not part of the executable workflow.
- Direct SDK smokes: passed with exactly six tools, rejected forged
  `execute`, `delete`, `task`, and `write_todos` dispatches, denied out-of-scope
  and traversal probes, and observed zero network attempts.
- Controller-to-worker SDK smoke: `SUCCEEDED` in one attempt with `scripted-no-transport`, trusted verification, exact artifact linkage, and complete cleanup.
- Network-none SDK smoke: passed with a strictly validated host-output record and
  no ownership-labeled container or image left behind.
- TypeScript lock/source/documentation qualification, strict compilation, nine
  worker tests, direct SDK smoke, controller-to-worker smoke, and network-none
  Docker smoke passed with exactly six tools and no observed network attempt.
- Deterministic retry workflow: `SUCCEEDED` on attempt two and `verify --latest` reported no issues.
- Disposable PostgreSQL/Kafka/OpenSearch workflow: `SUCCEEDED` on attempt one, independently verified, and left no matching container, network, or volume.
- Trivy 0.70.0: OpenSearch still matches its hash-bound finding set. Kafka,
  PostgreSQL, Python Alpine, and the Node build-base findings have drifted, so
  release eligibility remains blocked until each delta is reviewed explicitly.
  npm, Corepack, Yarn, source, and compiler tooling are still removed from the
  final TypeScript smoke image; that does not authorize refreshing the base
  image exception without review.
- Deep Agents Code compatibility review: exact 0.1.65 source and the current 17-page
  official Code documentation set were reviewed; the lane remains disabled
  because the stock CLI cannot satisfy the full ambient-state and network
  isolation contract.
- The upstream record and executable runtime both bind to the fully tested
  `deepagents==0.7.11` boundary.
- Public-surface scan: zero issues.
- Ruff 0.12.12 lint and format checks: passed.
- `git diff --check`: passed.

## Maintenance validation: 2026-09-03

- `./scripts/run-local.sh test`: 153 controller and adversarial tests passed;
  the two optional Python SDK-import tests skipped under the base interpreter as
  designed.
- Offline Python and TypeScript qualification, both network-isolated SDK
  smokes, TypeScript type checking and worker tests, deterministic retry and
  independent verification, the public-surface scan, and `git diff --check`
  passed.
- Current Python upstream evidence was refreshed without changing any direct
  pin or transitive lock. TypeScript upstream drift remains review-only because
  the latest LangSmith release is outside the peer range accepted by the pinned
  Deep Agents SDK.
- The current Trivy comparison remains fail-closed because several pinned base
  images exceed their hash-bound vulnerability baselines. No baseline or image
  digest was changed.

## Interpretation

Passing these checks demonstrates the synthetic reference boundary on the tested host. It does not certify a model provider, Docker/kernel implementation, third-party sandbox, customer repository, live connector, or deployment system. Each such integration requires its own documented threat model and qualification evidence.
