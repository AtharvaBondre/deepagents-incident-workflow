# Deep Agents research dossier

Snapshot date: 2026-08-25

This dossier records a public-source review of LangChain Deep Agents, Deep Agents Code, LangGraph persistence and memory, and relevant LangSmith boundaries. It is the design basis for this repository. It does not use customer material, private systems, retained sessions, credentials, or paid-provider results.

## Executive conclusion

Deep Agents is a strong fit for the candidate-authoring part of an incident workflow. It is an opinionated harness over LangChain `create_agent`, which itself runs on LangGraph. Its filesystem, context management, subagents, skills, memory, streaming, HITL, and sandbox abstractions help an agent work on long-running tasks.

It is not a verifier or containment boundary. Upstream explicitly follows a “trust the LLM within the powers granted to its tools” model. Filesystem containment is not process isolation, permissions default to allow when no rule matches, memory and skills are prompt content, model rubrics are model judgments, and graph completion does not prove a code change is correct.

The safe architecture is therefore:

1. Use the open-source `deepagents` SDK only for untrusted reasoning and edits in a disposable workspace.
2. Remove shell, deletion, delegation, external tools, shared memory, and persistence from the default agent surface.
3. Let a separate deterministic controller derive the patch, enforce policy, execute pinned network-disabled tests, validate trusted verifier completion, recompute digests, and decide draft eligibility.
4. Keep Deep Agents Code, LangSmith, Agent Server, MCP, hooks, plugins, remote sandboxes, and real-model evaluations optional and outside the authoritative path.

## Snapshot and provenance

| Surface | Snapshot reviewed | License/status |
|---|---|---|
| Deep Agents repository | [`dfde21e379201c833da4162444ef4a13b46980fd`](https://github.com/langchain-ai/deepagents/tree/dfde21e379201c833da4162444ef4a13b46980fd) | MIT |
| `deepagents` release | 0.7.8; tag commit [`1e261ba201bb1af4dbc5cbc8b6424e709b850ea8`](https://github.com/langchain-ai/deepagents/tree/1e261ba201bb1af4dbc5cbc8b6424e709b850ea8) | Beta, Python 3.11–3.14, MIT |
| `deepagents-code` release | 0.1.61; tag commit [`23a80f4d8ef4eef97f1a95440f34cc0f8ec4dffe`](https://github.com/langchain-ai/deepagents/tree/23a80f4d8ef4eef97f1a95440f34cc0f8ec4dffe) | Beta, Python 3.12–3.14, MIT |
| Documentation source | [`e2db436571b15bc9c3634c48db28b4c0611edec6`](https://github.com/langchain-ai/docs/tree/e2db436571b15bc9c3634c48db28b4c0611edec6) | Public docs |
| LangGraph repository | [`38031739e551638e373fb553453256c23feeb41f`](https://github.com/langchain-ai/langgraph/tree/38031739e551638e373fb553453256c23feeb41f) | MIT core |
| Deep Agents JavaScript | [`241cf2cf2404dd5ec3fd21289170e4aaca17493e`](https://github.com/langchain-ai/deepagentsjs/tree/241cf2cf2404dd5ec3fd21289170e4aaca17493e) | Separate MIT implementation |

The validated environment resolved `deepagents==0.7.8`, `deepagents-code==0.1.61`, `langgraph==1.2.11`, `langchain==1.3.17`, and `langsmith==0.11.1`. Versions evolve quickly; this report describes the pinned snapshot, not an evergreen promise.

## Complete Deep Agents Python documentation inventory

The official `llms.txt` index contains 40 pages. The public sitemap omits six indexed pages (`a2a`, both changelog aliases, `code-link`, `mcp`, and `openwiki`), so sitemap-only crawling is incomplete.

| # | Page | What it establishes | Workflow relevance |
|---:|---|---|---|
| 1 | [A2A](https://docs.langchain.com/oss/python/deepagents/a2a) | Agent Server A2A endpoint and distributed tracing | Hosted/distributed option; excluded from core |
| 2 | [ACP](https://docs.langchain.com/oss/python/deepagents/acp) | Editor/IDE Agent Client Protocol adapter | Optional UX; no verifier authority |
| 3 | [Async subagents](https://docs.langchain.com/oss/python/deepagents/async-subagents) | Persistent background-agent threads | Preview, persistence-heavy; excluded initially |
| 4 | [Backends](https://docs.langchain.com/oss/python/deepagents/backends) | State, filesystem, store, composite, sandbox, and custom storage | Central to workspace containment |
| 5 | [JavaScript changelog](https://docs.langchain.com/oss/python/deepagents/changelog-js) | Redirect to JavaScript releases | Tracks separate implementation |
| 6 | [Python changelog](https://docs.langchain.com/oss/python/deepagents/changelog-py) | Redirect to Python releases | Required for pin review |
| 7 | [Deep Agents Code link](https://docs.langchain.com/oss/python/deepagents/code-link) | Coding-agent entry point | Leads to CLI surface reviewed below |
| 8 | [Comparison](https://docs.langchain.com/oss/python/deepagents/comparison) | Comparison with Claude Agent SDK | Product positioning, not security proof |
| 9 | [Content builder](https://docs.langchain.com/oss/python/deepagents/content-builder) | Memory, skills, subagents, research, image example | Demonstrates composition and extra trust surfaces |
| 10 | [Context engineering](https://docs.langchain.com/oss/python/deepagents/context-engineering) | Prompt construction, offloading, compression, isolation | Explains long-context behavior and drift risks |
| 11 | [Customization](https://docs.langchain.com/oss/python/deepagents/customization) | Prompts, tools, middleware, models, subagents | Enables the bounded worker profile |
| 12 | [Data analysis](https://docs.langchain.com/oss/python/deepagents/data-analysis) | Sandboxed files, code, plots | Useful pattern; execution remains untrusted |
| 13 | [Deep research](https://docs.langchain.com/oss/python/deepagents/deep-research) | Multi-step research and delegation | Confirms orchestration strengths |
| 14 | [Dynamic subagents](https://docs.langchain.com/oss/python/deepagents/dynamic-subagents) | QuickJS-driven fan-out and orchestration | Excluded; parallel calls can bypass ordinary HITL |
| 15 | [Event streaming](https://docs.langchain.com/oss/python/deepagents/event-streaming) | Typed v3 events for messages/tools/state/output | Observability only; never acceptance evidence |
| 16 | [Fault tolerance](https://docs.langchain.com/oss/python/deepagents/fault-tolerance) | Retries, fallbacks, error conversion, call limits | Helpful reliability controls, not verifier trust |
| 17 | [Frontend overview](https://docs.langchain.com/oss/python/deepagents/frontend/overview) | UI integration patterns | Future review UI surface |
| 18 | [Sandbox frontend](https://docs.langchain.com/oss/python/deepagents/frontend/sandbox) | IDE-style files and sandbox UI | Optional frontend |
| 19 | [Subagent streaming UI](https://docs.langchain.com/oss/python/deepagents/frontend/subagent-streaming) | Progress cards for delegated work | Optional frontend |
| 20 | [Task-list UI](https://docs.langchain.com/oss/python/deepagents/frontend/todo-list) | State-synchronized task list | Optional frontend; planning is not policy |
| 21 | [Going to production](https://docs.langchain.com/oss/python/deepagents/going-to-production) | Persistence, resilience, auth, deployment, sandbox guidance | Useful future-service checklist |
| 22 | [Human in the loop](https://docs.langchain.com/oss/python/deepagents/human-in-the-loop) | Approve, edit, reject, respond, and interrupts | HITL comes after trusted verification in this project |
| 23 | [Interpreters](https://docs.langchain.com/oss/python/deepagents/interpreters) | In-process QuickJS `eval` orchestration | Not OS isolation; excluded initially |
| 24 | [MCP](https://docs.langchain.com/oss/python/deepagents/mcp) | Model Context Protocol tools | External capability surface; excluded initially |
| 25 | [Memory](https://docs.langchain.com/oss/python/deepagents/memory) | Thread and cross-thread memory patterns | Disabled by default to prevent cross-incident leakage |
| 26 | [Models](https://docs.langchain.com/oss/python/deepagents/models) | Model selection, initialization, evaluation | Explicit model required; provider call is opt-in |
| 27 | [Multimodal](https://docs.langchain.com/oss/python/deepagents/multimodal) | Image, audio, video, PDF, and presentation inputs | Not needed for the initial text fixture |
| 28 | [OpenWiki](https://docs.langchain.com/oss/python/deepagents/openwiki) | Separate repository-wiki product | Related but outside project scope |
| 29 | [Overview](https://docs.langchain.com/oss/python/deepagents/overview) | Core architecture and default features | Primary product map |
| 30 | [Permissions](https://docs.langchain.com/oss/python/deepagents/permissions) | First-match filesystem allow/deny/interrupt rules | Used with a final explicit deny |
| 31 | [Profiles](https://docs.langchain.com/oss/python/deepagents/profiles) | Provider and harness profiles | Used to remove delete/execute/task |
| 32 | [Quickstart](https://docs.langchain.com/oss/python/deepagents/quickstart) | Minimal agent creation | Establishes baseline API |
| 33 | [RAG](https://docs.langchain.com/oss/python/deepagents/rag) | Retrieval-augmented example | Optional evidence-broker pattern |
| 34 | [Retrieval](https://docs.langchain.com/oss/python/deepagents/retrieval) | Retrieval concepts and implementations | Retrieval output remains untrusted evidence |
| 35 | [Rubric](https://docs.langchain.com/oss/python/deepagents/rubric) | Iterative LLM-as-judge grading | Advisory only; cannot authorize delivery |
| 36 | [Sandboxes](https://docs.langchain.com/oss/python/deepagents/sandboxes) | Provider adapters and lifecycle | Isolation claims remain provider-specific |
| 37 | [Skills](https://docs.langchain.com/oss/python/deepagents/skills) | Agent Skills layout and progressive disclosure | Prompt content, not executable policy |
| 38 | [Streaming](https://docs.langchain.com/oss/python/deepagents/streaming) | LangGraph v2 stream modes and subgraphs | Observational only |
| 39 | [Subagents](https://docs.langchain.com/oss/python/deepagents/subagents) | Synchronous isolated-context delegation | Disabled in the initial worker |
| 40 | [Tools](https://docs.langchain.com/oss/python/deepagents/tools) | Built-ins and custom tool registration | Tool power defines the practical trust boundary |

## Complete Deep Agents Code documentation inventory

All 16 pages in the coding-agent subtree were reviewed and returned successfully.

| # | Page | Main surface |
|---:|---|---|
| 1 | [Overview](https://docs.langchain.com/oss/deepagents/code/overview) | Product capabilities and TUI |
| 2 | [Quickstart](https://docs.langchain.com/oss/deepagents/code/quickstart) | Installation and first coding session |
| 3 | [CLI reference](https://docs.langchain.com/oss/deepagents/code/cli-reference) | Interactive, headless, ACP, model, sandbox, shell, and limit flags |
| 4 | [Configuration](https://docs.langchain.com/oss/deepagents/code/configuration) | Environment and configuration precedence |
| 5 | [Config file](https://docs.langchain.com/oss/deepagents/code/config-file) | User/project agent configuration |
| 6 | [Credentials](https://docs.langchain.com/oss/deepagents/code/credentials) | Provider authentication resolution and storage |
| 7 | [Providers](https://docs.langchain.com/oss/deepagents/code/providers) | Built-in and custom model providers |
| 8 | [Approval modes](https://docs.langchain.com/oss/deepagents/code/approval-modes) | Manual, classifier-backed Auto, and YOLO |
| 9 | [Memory and skills](https://docs.langchain.com/oss/deepagents/code/memory-and-skills) | Persistent markdown memory and skill discovery |
| 10 | [Subagents](https://docs.langchain.com/oss/deepagents/code/subagents) | File-defined and dynamic delegation |
| 11 | [MCP tools](https://docs.langchain.com/oss/deepagents/code/mcp-tools) | User/project MCP discovery and trust |
| 12 | [Remote sandboxes](https://docs.langchain.com/oss/deepagents/code/remote-sandboxes) | LangSmith, AgentCore, Daytona, Modal, Runloop, Vercel |
| 13 | [Hooks](https://docs.langchain.com/oss/deepagents/code/hooks) | Lifecycle and tool-use command hooks |
| 14 | [Plugins](https://docs.langchain.com/oss/deepagents/code/plugins) | Skills, hooks, MCP, marketplaces, updates |
| 15 | [Goals and rubrics](https://docs.langchain.com/oss/deepagents/code/goals-and-rubrics) | Model-drafted goals and model-graded iteration |
| 16 | [Changelog](https://docs.langchain.com/oss/deepagents/code/changelog) | Version changes and migration signals |

### CLI runtime behavior

`deepagents-code==0.1.61` installs both `dcode` and `deepagents-code`. Major modes are:

- `dcode`: interactive Textual TUI.
- `dcode -n "task"`: a fresh headless thread.
- `dcode --stdin`: explicit piped-input mode.
- `dcode -r [thread]`: resume a checkpointed thread.
- `dcode --acp`: Agent Client Protocol server over stdio.
- `dcode --sandbox <provider>`: remote execution backend.

Automation controls include `--max-turns`, `--timeout`, `--allow-fs-tools`, `--no-mcp`, `--quiet`, `--no-stream`, and `-S/--shell-allow-list`. Exit 124 represents a turn or wall-clock limit.

The TUI client starts a local LangGraph development server, connects over HTTP/SSE, and uses an ephemeral loopback port with `LANGGRAPH_AUTH_TYPE=noop`. Sessions are retained in unencrypted SQLite under the user Deep Agents state directory. A local process that discovers the port is within the upstream threat model.

Headless mode automatically approves non-shell tools because there is no interactive HITL handler. Shell is off unless `-S` is supplied, but its allowlist checks executable names rather than semantic effects. Allowing `python`, `bash`, `env`, `xargs`, `uv`, or a similar wrapper effectively permits arbitrary execution.

### CLI ambient state

The coding agent can combine package prompts, user `AGENTS.md`, project `.deepagents/AGENTS.md`, root `AGENTS.md`, automatic memories, skills, subagents, MCP configuration, hooks, plugins, provider configuration, project `.env`, and update state. An ephemeral `HOME` is a stronger isolation control than only setting an auto-save flag.

Relevant defensive environment controls include:

```text
DEEPAGENTS_CODE_NO_UPDATE_CHECK=1
DEEPAGENTS_CODE_AUTO_UPDATE=0
DEEPAGENTS_CODE_PLUGIN_AUTO_UPDATE=0
DEEPAGENTS_CODE_PRICES_AUTO_UPDATE=0
DEEPAGENTS_CODE_MEMORY_AUTO_SAVE=0
DEEPAGENTS_CODE_READ_PROJECT_DOTENV=0
DEEPAGENTS_CODE_OLLAMA_DISCOVERY=0
DEEPAGENTS_CODE_OFFLINE=1
LANGSMITH_TRACING=false
```

These suppress known application paths; they do not provide OS-level network isolation.

### Why `dcode` is not the core adapter

The CLI always adds a `fetch_url` capability, its documented filesystem allowlist does not remove every non-filesystem surface, and its local client/server, persistent state, discovery rules, and update mechanisms broaden the trusted computing base. A black-box CLI adapter can still be valuable for compatibility testing, but only inside an outer controller-owned OS sandbox. The SDK lets this project construct a smaller exact tool surface and avoid the CLI server entirely.

## Source-tree map

The reviewed Deep Agents monorepo contains these relevant packages and folders:

| Path | Role |
|---|---|
| `libs/deepagents/deepagents/graph.py` | `create_deep_agent` graph and middleware assembly |
| `libs/deepagents/deepagents/backends/` | State, filesystem, store, composite, shell, and sandbox backends |
| `libs/deepagents/deepagents/middleware/` | Filesystem, skills, memory, summarization, subagents, permissions, tool patching |
| `libs/deepagents/deepagents/profiles/` | Provider/model and harness profiles |
| `libs/deepagents/tests/` | Core unit, integration, and benchmark coverage |
| `libs/deepagents/THREAT_MODEL.md` | Generated SDK threat analysis |
| `libs/code/deepagents_code/` | Coding-agent client, server, TUI, configuration, tools, memory, hooks, plugins |
| `libs/code/tests/` | CLI and agent tests |
| `libs/code/THREAT_MODEL.md` | Generated coding-agent threat analysis |
| `libs/acp/` | ACP adapter |
| `libs/evals/` | Behavioral evaluation suite and scorecards |
| `libs/partners/` | Optional sandbox/provider adapters |
| `examples/` | Deployment and application examples |

At the snapshot, the Code package contains roughly 504 files: about 250 package-source files and 228 tests. Core Deep Agents testing contains 65 test files: 57 unit, six integration, and two benchmark files. The separate evaluation catalog contains 135 behavioral evaluations across filesystem, retrieval, tool use, memory, conversation, summarization, unit-test generation, and middleware categories.

## Deep Agents architecture in detail

### Layering

1. LangGraph supplies graph execution, state, checkpoints, interrupts, retry primitives, and streaming.
2. LangChain `create_agent` supplies the model/tool loop and middleware interface.
3. Deep Agents assembles an opinionated harness with filesystem tools, summarization, delegation, skills, memory, profiles, prompt caching, and optional HITL.

`create_deep_agent` returns a LangGraph `CompiledStateGraph`. `DeepAgentState` extends LangChain agent state and uses delta snapshots for message history to avoid quadratic checkpoint growth.

### Default and optional tools

The filesystem layer exposes `ls`, `read_file`, `write_file`, `edit_file`, `delete`, `glob`, and `grep`. `execute` appears only when a backend implements the sandbox protocol. `task` appears when synchronous subagents are present. Task planning is opt-in in 0.7.

This project replaces the default filesystem middleware with an explicit six-tool allowlist and disables the general-purpose subagent. It also excludes `delete` and `execute` through a harness profile. The duplicate controls are intentional defense in depth; the controller still validates the resulting patch independently.

### Middleware composition

The effective stack can include skills, filesystem, synchronous subagents, summarization, dangling-tool-call repair, asynchronous subagents, caller middleware, profile middleware, prompt caching, memory, HITL, and final tool exclusion. Declarative subagents get their own stack and do not recursively inherit every parent feature.

Middleware ordering matters. Error conversion, retries, limits, and fallback middleware can change apparent outcomes. None may convert missing controller evidence into acceptance.

### Backends

- `StateBackend`: virtual files in graph state; persists only when graph state is checkpointed.
- `FilesystemBackend`: host files with virtual path mapping. Current 0.7.8 defaults `virtual_mode=True`; this restricts paths but is not process isolation.
- `LocalShellBackend`: unrestricted host shell via `subprocess.run(..., shell=True)`; unsuitable here.
- `StoreBackend`: cross-thread files over a LangGraph store; namespace design is a tenant boundary.
- `CompositeBackend`: longest-prefix routing across backends.
- sandbox backends: filesystem plus process execution under provider-specific isolation.

The worker uses `FilesystemBackend(root_dir=<disposable copy>, virtual_mode=True)`. The model never receives an execution tool. Repository code runs only later in the controller-owned Docker verifier.

### Permissions

Filesystem rules are first-match-wins and default-allow. The worker therefore generates:

1. allow writes under controller-approved prefixes;
2. deny all other writes;
3. allow reads inside the already-contained virtual root;
4. deny unmatched reads.

Permissions cover built-in filesystem tools only. They do not cover custom tools, MCP, direct backend calls, or sandbox shell commands, which is why none of those capabilities is present.

## LangGraph state, persistence, and memory

### Short-term state

A checkpointer stores thread snapshots keyed by `thread_id`. Checkpoints enable resume, HITL, time travel, replay, and fault recovery. Full checkpoints occur at super-step boundaries; pending writes can prevent successful siblings from rerunning when another task fails.

Durability modes have different crash windows:

- `exit`: intermediate state can be lost on a process crash.
- `async`: persistence can lag execution briefly.
- `sync`: writes complete before the next step and is the safest choice for future controller-state transitions.

Interrupt resumption restarts the interrupted node from its beginning. Code before `interrupt()` can run again, so external side effects must be idempotent or placed after a separate committed boundary. Replay re-executes nodes after the selected checkpoint, including model and API calls. Replay and state-update APIs must never authorize delivery.

The initial SDK worker supplies no checkpointer and starts a new process for every attempt. This prevents cross-attempt graph state from becoming an authority or leakage channel.

### Long-term memory

LangGraph stores share JSON-like items across threads under tuple namespaces. Deep Agents adds filesystem-shaped memory, commonly `AGENTS.md`, over state or store backends. Shared writable memory is explicitly a prompt-injection risk, concurrent writes are last-write-wins, and search limits/order are not an authoritative inventory mechanism.

Phase 1 has no cross-thread memory. If memory is introduced later, it must be opt-in, read-only by default, controller-namespaced, retention-bounded, content-filtered, and permanently excluded from verifier policy and delivery authority. Semantic search must not silently introduce a remote embeddings provider.

### Local persistence option

For a future resumable single-user controller, `langgraph-checkpoint-sqlite==3.1.1` is the preferred local option. Store the database outside every agent-visible mount, use controller-issued opaque thread identifiers, use synchronous durability for eligibility transitions, and enforce a per-incident lock. A future multi-user service should move to PostgreSQL and explicit leases rather than assuming the direct graph runtime serializes competing runs.

## LangSmith and deployment boundary

The `langsmith` Python SDK is MIT, but LangSmith Cloud, managed deployment, BYOC, and self-hosted platform offerings are separate hosted or commercial surfaces. The LangGraph SDK is MIT; the current standalone Agent Server packages include Elastic-2.0 components and require license/usage-reporting behavior unless an appropriate enterprise air-gap arrangement exists.

Core verification does not require LangSmith, Studio, `langgraph dev`, `langgraph up`, Agent Server, or any hosted evaluator. Tracing is off by default because traces can contain prompts, evidence, tool inputs, tool output, and model responses. Optional local evaluation with upload disabled may be useful diagnostically, but deterministic unit and verifier checks remain authoritative.

## Security findings and controls

| Risk | Upstream behavior | Project control |
|---|---|---|
| Prompt injection | Tool, memory, skill, web, and subagent output re-enters context | Treat all such content as data; give model no authority |
| Host filesystem access | `FilesystemBackend` maps host files | Disposable copied root plus virtual mode and explicit rules |
| Shell escape | `LocalShellBackend` executes with `shell=True`; CLI shell allowlist is semantically weak | No shell backend or `execute` tool |
| Network exfiltration | Models, web/fetch, MCP, updates, tracing, and remote sandboxes can call out | Only explicit model transport; no network tools; verifier network disabled |
| Persistent poisoning | Memory, skills, goals, rubrics, hooks, plugins, sessions | Fresh process and ephemeral home; all disabled in core |
| False success | Model text, exit zero, rubric, or graph completion may claim success | Controller-derived patch and trusted verifier receipt |
| Early exit/crash/timeout | Partial state or workspace may remain | AST-only fixture semantics, outer process/container timeout, cleanup, and missing-receipt rejection |
| Receipt forgery | Candidate can write arbitrary workspace files | Receipts outside candidate mount with nonce and digest checks |
| Stale/replayed evidence | Checkpoints and old artifacts can be replayed | Attempt/run binding plus exact candidate/policy/verifier digests |
| Tool-surface drift | Beta releases change defaults | Exact SDK pin, worker digest, six-tool smoke, versioned policy |

## Documentation and source drift found

The review found several places where examples or prose lag current 0.7.8 behavior:

1. The sitemap omits six pages present in the official Markdown index.
2. Context-engineering prose describes base/tool prompt content largely removed in 0.7.
3. Architecture prose can imply task planning is default, while 0.7 made it opt-in.
4. Backend prose says `FilesystemBackend.virtual_mode` defaults false; current source defaults true.
5. Some backend and memory examples use factory/constructor forms removed in 0.7.
6. Store prose describes namespace enforcement as future behavior although 0.7.8 requires it.
7. Skills documentation links to removed `libs/cli` locations; current code is under `libs/code`.
8. Some sandbox model tabs wrap non-Anthropic identifiers with `ChatAnthropic`.
9. A production synchronization example refers to an undefined runtime value and an older store form.
10. The content-builder page contains unfinished example text and an obsolete pre-0.4 dependency range.
11. `graph.py` prose says unsupported execution returns an error, while current middleware hides unsupported execution/deletion tools.
12. The generated threat model reflects an older commit and older defaults.
13. Legacy v2 streaming remains documented while typed v3 event streaming is recommended for new applications.
14. CLI docs say interpreter PTC defaults to pure REPL; 0.1.61 source exposes the safe read-only set.
15. CLI memory docs emphasize `.deepagents/AGENTS.md`; source also loads project-root `AGENTS.md`.
16. Generated CLI threat wording around auto-approval can be confused with current Manual, Auto, and YOLO modes.

The implementation pins and tests executable behavior rather than relying on prose alone.

## Fit compared with the Hermes reference workflow

| Concern | Hermes integration | Deep Agents integration |
|---|---|---|
| Candidate runtime | External CLI/profile | Direct SDK worker process |
| Workspace tools | Docker terminal profile | Virtual-root filesystem tools only |
| Shell | Network-disabled container shell | Absent from agent surface |
| Agent persistence | Disabled profile memory/session reuse | No memory, checkpointer, or store |
| Candidate patch | Host-derived from isolated workspace | Controller-derived from disposable workspace |
| Verification | Controller-owned pinned Docker verifier | Same hardened controller/verifier design |
| Delivery | Local draft artifacts | Local draft artifacts |
| Real-model dependency | Optional | Optional |
| Default CI | Synthetic fixtures | Synthetic fixtures plus optional real SDK smoke |

Deep Agents offers a cleaner library-level composition point than a CLI-only adapter. The tradeoff is that model provider credentials normally arrive through environment variables; this project forwards only provider-specific allowlisted names to the worker and never forwards them to candidate-code tests.

## Final implementation decisions

- Public repository name: `AtharvaBondre/deepagents-incident-workflow`. Using `langchain/...` would incorrectly imply organization ownership.
- Core package: `deepagents==0.7.8`, external and exact-pinned.
- Core controller: standard-library Python; Deep Agents is an optional extra.
- Candidate process: fresh process, ephemeral home, no persistence, hard process-group deadline.
- Candidate tools: exact six-tool filesystem allowlist; no delete, shell, network, MCP, subagent, hook, plugin, interpreter, memory, or delivery tool.
- Verification: controller-owned, digest-pinned, network-disabled Docker process with explicit trusted completion.
- Delivery: file-based draft mocks only.
- LangSmith and `dcode`: documented optional surfaces, not required dependencies or acceptance inputs.

## Official source set

- [Deep Agents overview](https://docs.langchain.com/oss/python/deepagents/overview)
- [Deep Agents Code overview](https://docs.langchain.com/oss/deepagents/code/overview)
- [Deep Agents repository](https://github.com/langchain-ai/deepagents)
- [Deep Agents JavaScript repository](https://github.com/langchain-ai/deepagentsjs)
- [LangGraph overview](https://docs.langchain.com/oss/python/langgraph/overview)
- [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence)
- [LangGraph memory](https://docs.langchain.com/oss/python/langgraph/add-memory)
- [LangGraph interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)
- [LangGraph fault tolerance](https://docs.langchain.com/oss/python/langgraph/fault-tolerance)
- [LangGraph streaming](https://docs.langchain.com/oss/python/langgraph/streaming)
- [LangSmith tracing for Deep Agents](https://docs.langchain.com/langsmith/trace-deep-agents)
- [LangSmith data storage and privacy](https://docs.langchain.com/langsmith/data-storage-and-privacy)
- [LangSmith local evaluation](https://docs.langchain.com/langsmith/local)
- [LangSmith Agent Server](https://docs.langchain.com/langsmith/agent-server)
- [Standalone Agent Server](https://docs.langchain.com/langsmith/deploy-standalone-server)
