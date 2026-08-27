# Threat model

## Protected assets

- Controller policy, deadlines, attempt state, and delivery eligibility.
- Verifier code, nonce/completion protocol, receipts, and digests.
- Host credentials, private files, network access, and unrelated repositories.
- Integrity of the exact accepted patch and clean reapplication.
- Public neutrality of committed source and fixtures.

## Trust assumptions

- Incident text, evidence, model responses, tool output, candidate code, and candidate filesystem state are hostile.
- Deep Agents and model providers are dependencies, not policy authorities.
- A model can exploit every capability visible to it; prompt instructions are not containment.
- Docker, the host kernel, Git, Python, Node, and pinned third-party packages remain part of the trusted computing base.
- Local artifacts can be changed by a user with host access and are not cryptographic transparency records.

## Threats and mitigations

| Threat | Mitigation |
|---|---|
| Incident/evidence prompt injection | Mark content untrusted, reject known markers, use a controller-authored system prompt, and never expose policy-changing tools. |
| Model reads unrelated host files | Disposable copied root, `FilesystemBackend(virtual_mode=True)`, and explicit read rules ending in deny. |
| Model writes policy, tests, or receipts | Write allowlist comes from trusted policy; unmatched writes deny; controller independently validates patch paths. |
| Model deletes data | `delete` is absent from the tool surface. |
| Model executes code or shell | No sandbox/shell backend, `execute`, interpreter, custom execution tool, or subagent tool is supplied. |
| Model exfiltrates through tools | No fetch, web, MCP, browser, connector, or network-capable tool; candidate tests use Docker network `none`. |
| Ambient memory or instruction poisoning | Fresh process, ephemeral home, no skills, no memory, no checkpointer/store, and no Code CLI discovery. |
| LangSmith trace disclosure | `LANGSMITH_TRACING=false`; tracing is not required and is recorded disabled. |
| Cross-provider credential leakage | Minimal worker environment forwards only names approved for the selected provider; candidate containers receive none. |
| Agent claims tests passed | Agent cannot run tests; claims are ignored. Controller runs the fixed argv later. |
| Candidate prints a forged success marker or exits during import | The trusted semantic verifier never imports candidate modules; its allowlisted AST evaluator rejects top-level execution, executable annotations/defaults/decorators, extra helpers, output calls, and process-control constructs. |
| Verifier exits early with code zero | Missing exactly one trusted completion marker makes the controller check fail. |
| Verifier crashes or is signaled | Terminal container/process status and required assertions fail closed. |
| Verifier times out | Controller kills the owned process/container and denies eligibility. |
| Candidate edits verifier code | Verifier files are mounted from controller-owned paths, read-only, outside candidate workspace. |
| Stale or replayed receipt | Run/attempt nonce plus candidate, fixture, policy, and verifier digests bind the receipt. |
| Patch changes after testing | Patch SHA, workspace digest, clean reapply, and rerun must all match. |
| Symlink/path escape | Workspace walk rejects links/irregular files; patch path normalization and prefix policy reject escapes. |
| Binary/mode/oversized change | Patch validator rejects binary diffs, unsafe modes, excessive bytes, and excessive paths. |
| Timeout leaves processes or containers | A handled SDK timeout terminates the worker process group. Candidate-test/verifier containers and Compose projects receive controller-derived identities and durable pre-launch cleanup intents; restart cleanup revalidates ownership and fails closed. |
| Controller crash leaves containers | Candidate-test/verifier containers and Compose projects have pre-launch cleanup intents that a later controller run validates before cleanup. |
| Cleanup removes unrelated resources | Run IDs contain a controller-issued 128-bit nonce and are bound to the run-directory name; container and Compose targets are derived from run ID, attempt, and phase; image/config/working-directory/resource labels are checked before removal; artifact-supplied names cannot select a target. |
| Delivery bypass | Delivery implementation writes local mocks only and rechecks verification linkage. |
| Dependency behavior drifts | Exact Python/npm locks, SDK/runtime versions, source and compiled-worker digests, scheduled official-source drift checks, digest-pinned smoke/verifier images, and no-cost tool-surface smokes. |

## Deep Agents-specific residual risks

- `FilesystemBackend` containment is not OS process isolation. The model can only reach it through bounded file tools, but a vulnerability in Python, Node, or a dependency remains in the trusted computing base.
- The real-model worker must reach a selected inference provider. Provider processing, retention, compromise, and response behavior are outside this repository.
- A hard controller crash can orphan the opt-in provider-connected SDK worker because process-group termination only runs on handled timeouts. Operators must inspect and stop an orphan before retrying; a durable worker supervisor or independent watchdog is required before unattended real-model operation.
- Deep Agents is Beta and changes rapidly. Exact pins reduce drift but require deliberate upgrades.
- Provider SDK initialization runs third-party dependency code in the selected worker process. The ephemeral home and minimal environment reduce exposure; a future high-assurance mode should place the whole worker in an outbound allowlisted container or VM.
- The pure-expression semantic verifier intentionally supports only the narrow synthetic fixture contract. Adapting it to general application code requires a new controller-owned verifier, not a broader `eval` or candidate import.
- The default fixture path does not exercise a paid model. The no-cost smoke verifies SDK graph/tool wiring, not model quality.
- The optional service verifier evaluates only the narrow candidate AST subset without importing candidate modules, then accesses an internal synthetic service network. It can veto but never authorize: the network-disabled controller verifier must pass first. Do not reuse this lane for customer code, live data, or real credentials without stronger isolation.
- Artifact files are mutable by the host user. External signing or transparency storage is required for tamper-evident audit use.

## Explicitly excluded high-risk surfaces

The current workflow does not enable `LocalShellBackend`, Deep Agents Code, Agent Server, writable memory, MCP, hooks, plugins, remote sandboxes, dynamic/async subagents, QuickJS, web search, `fetch_url`, LangSmith tracing, model-graded delivery gates, live connectors, automatic merge, deployment, or incident mutation.
