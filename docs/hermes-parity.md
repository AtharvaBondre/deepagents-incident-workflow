# Hermes reference parity

## Purpose

This project uses the public [Hermes Incident Workflow](https://github.com/AtharvaBondre/hermes-incident-workflow) as its reference product pattern. The comparison baseline is Hermes commit [`48cbf19bfc82305be8467607647ec14d4fc4192e`](https://github.com/AtharvaBondre/hermes-incident-workflow/commit/48cbf19bfc82305be8467607647ec14d4fc4192e).

Hermes is a design reference, not a runtime dependency. This repository does not copy or vendor Hermes, its profile, bundled skills, plugins, assets, sessions, or dependency tree. Parity means preserving the same safety and product guarantees through native Deep Agents mechanisms.

## Shared product contract

Both projects must preserve these invariants:

1. The agent proposes; controller-owned code decides.
2. Incident text, evidence, repository content, model output, and tool output are untrusted.
3. Repository identity, allowed paths, test commands, limits, and delivery authority come only from reviewed policy.
4. Every attempt starts with isolated state and a disposable candidate workspace.
5. The controller derives the candidate patch rather than trusting an agent-authored success declaration.
6. Candidate execution and verification are pinned, network-disabled, resource-bounded, and time-bounded.
7. Acceptance applies to one exact patch and candidate digest, including a clean reapplication.
8. Failure, exhaustion, rejection, crash, signal, timeout, malformed evidence, or incomplete cleanup cannot reach delivery.
9. Delivery remains local and draft-only.
10. The public repository contains only synthetic, customer-neutral material.

## Product and control parity

| Capability | Hermes reference | Deep Agents implementation | Parity status |
| --- | --- | --- | --- |
| Controller-owned policy | `config/workflow.json` plus compiled ceilings | Same policy/ceiling pattern | Matched |
| Intake validation | Repository, service, environment, and evidence-window checks | Equivalent validation | Matched |
| Prompt-injection rejection | Rejected before evidence and patching | Equivalent regression | Matched |
| Bounded evidence | Fixture broker, row/log caps, redaction | Equivalent fixture broker, caps, and redaction | Matched |
| Candidate lifecycle | Fresh Hermes session per attempt | Fresh Deep Agents process per attempt | Matched semantically |
| Agent tool boundary | Locked Hermes profile and Docker terminal | Exact six-tool SDK filesystem surface; no shell | Stronger SDK-specific reduction |
| Persistence | No retained Hermes session | No checkpointer, store, memory, or retained session | Matched |
| Patch authority | Host-derived Git patch | Controller-derived Git patch | Matched |
| Patch policy | Path, binary, mode, size, link, and content checks | Same checks plus hidden rename/copy rejection and post-apply path reconciliation | Matched and strengthened |
| Candidate tests | Pinned, network-none, read-only Docker sandbox | Equivalent Docker sandbox | Matched |
| Semantic verifier | Controller-owned verifier | AST-only controller verifier that never imports candidate modules | Strengthened |
| Completion integrity | Test/verifier results and digest linkage | Nonce-bound receipts plus exact terminal-state and completion-marker checks | Strengthened |
| Adversarial exits | Timeout and failure coverage | Early zero exit, forged marker, nonzero exit, signal, crash, inner timeout, and outer timeout coverage | Strengthened |
| Clean reapplication | Required on a fresh baseline | Required with exact patch and tree digest | Matched |
| Optional services | PostgreSQL, Kafka, and OpenSearch | Equivalent synthetic stack and assertions | Matched |
| Delivery | File-based draft GitHub and notification mocks | Equivalent mocks with post-eligibility revocation | Matched and strengthened |
| Cleanup | Controller-owned container and Compose cleanup | Pre-launch intents, exact ownership checks, restart recovery, pre-delivery and closeout cleanup | Strengthened |
| Public safety | Public-surface scanner and ignored artifacts | Expanded scanner, credential shapes, irregular-file checks, and git-aware ignored-path checks | Matched and strengthened |
| CI | Deterministic tests and SDK smoke | Python 3.11/3.12 deterministic and SDK matrices, pinned Ruff, direct graph smoke, and controller-to-worker end-to-end smoke | Matched and strengthened |
| Customer adaptation | Public templates; private packs remain external | Equivalent customer-neutral templates and boundaries | Matched |
| Costing | Evidence-backed model-cost guidance | Equivalent formulas and provider-rate structure | Matched |

## Intentional runtime differences

### Candidate execution surface

Hermes is integrated through its external CLI and an isolated profile. Its terminal work runs in a network-disabled Docker sandbox. Deep Agents is integrated directly through the Python SDK and receives no shell or execution tool. The SDK worker uses a disposable virtual-root filesystem, while candidate tests run later in the controller-owned Docker boundary.

This is intentional. Adding a shell merely to resemble Hermes would enlarge the Deep Agents attack surface without improving the workflow.

### Network boundary

Both real-model host processes may contact one explicitly selected inference provider. In the Deep Agents implementation, Python socket interception in the scripted smoke is a regression detector, not an OS sandbox. High-assurance unattended real-model use therefore remains gated on an outer egress-controlled worker boundary and durable supervision.

### Profiles and skills

Hermes needs a repository-owned profile to constrain CLI behavior. Deep Agents builds the exact middleware, backend, permission, profile, and tool configuration in code. Shipping a shadow profile or agent skill would add ambient prompt state and undermine the smaller SDK-native boundary.

### Memory and LangGraph

Deep Agents exposes native LangGraph checkpoint and store integration. They are disabled in Phase 1. Their availability does not justify enabling them until resume, replay, namespace, poisoning, retention, and concurrency tests meet the gates in the implementation plan.

## Parity verification matrix

Every release candidate must retain evidence for these shared gates:

| Gate | Required Deep Agents proof |
| --- | --- |
| Policy inspection | `./scripts/run-local.sh dump-policy` emits only the compiled, customer-neutral boundary |
| Unit/adversarial suite | `./scripts/run-local.sh test` passes |
| Retry behavior | `retry-success` fails first, succeeds second, and verifies independently |
| Failure behavior | exhaustion, rejection, timeout, forged-success, crash, and cleanup regressions deny delivery |
| Real SDK wiring | pinned direct smoke observes exactly six tools; full no-cost smoke crosses the controller, worker subprocess, graph, patch, Docker verifier, delivery, and cleanup with no transport |
| Path containment | out-of-scope and traversal read/write probes are denied |
| Exact-candidate integrity | patch, candidate, verifier, receipt, clean-reapply, and delivery digests remain linked |
| Service behavior | optional event-indexing fixture passes and leaves no project resources |
| Publication safety | public-surface, formatting, Git diff, and CI checks pass |

Test counts are evidence, not the parity target. A platform-specific invariant may require multiple Deep Agents regressions or no direct Hermes analogue. Coverage should be evaluated by threat and product guarantee, not identical file or test structure.

## Maintenance rule

When either public project changes a controller, verifier, cleanup path, delivery gate, credential boundary, or sandbox assumption:

1. review the corresponding public change in the other project;
2. decide whether the underlying invariant applies across runtimes;
3. port the invariant through native mechanisms, not copied runtime configuration;
4. add a platform-specific regression before claiming parity;
5. update this matrix and the relevant threat model;
6. run the complete local and CI qualification gates.

Do not make CI fetch or execute the Hermes repository. Cross-project review is a maintainer process; each repository remains independently reproducible and independently secure.

## Current conclusion

Against the pinned public Hermes baseline, the Deep Agents project has feature parity for the safe synthetic incident-remediation workflow and broader fail-closed verifier, patch-integrity, cleanup-recovery, and public-surface regression coverage. Its remaining gaps are future capability gates shared by both projects or explicit Deep Agents-specific residuals, not missing Phase 1 parity.

The composed no-cost SDK qualification also proves that this conclusion is not based only on unit-level equivalence: an actual Deep Agents graph and worker subprocess can produce a candidate that survives the complete controller-owned acceptance chain without receiving delivery authority.
