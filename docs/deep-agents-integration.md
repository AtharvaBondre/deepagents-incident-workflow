# Deep Agents integration

This project supports LangChain's open-source Deep Agents Python and TypeScript
SDKs as interchangeable, untrusted candidate authors. Deep Agents, LangChain,
LangGraph, LangSmith, model providers, and their dependencies remain external
packages and are not vendored.

## Why the SDK is the integration point

The SDKs let the controller construct the exact agent used for an attempt. The
Python worker uses `deepagents==0.7.8`; the TypeScript worker uses
`deepagents@1.13.1`. Both create:

- a disposable `FilesystemBackend` in virtual-root mode;
- only `ls`, `read_file`, `write_file`, `edit_file`, `glob`, and `grep`;
- explicit write allow-rules followed by default-deny rules;
- no shell, delete tool, subagent, skill, memory, checkpointer, store, MCP,
  hook, plugin, interpreter, or LangSmith tracing; and
- a fresh process and ephemeral home for every attempt.

The SDK filesystem boundary is capability reduction, not an operating-system
sandbox. Candidate code never runs in that process. Tests and trusted
verification run later in separate digest-pinned Docker containers with
networking disabled.

The TypeScript SDK differs in important details. Its filesystem backend must
set `virtualMode: true` explicitly. Permissions are first-match-wins and
default-allow, so the worker installs narrow allow rules followed by explicit
deny-all rules. A registered harness profile disables the general-purpose
subagent and excludes delete, execute, todo, and task tools. A controller-owned
middleware observes the unmodified tool set offered to every model call and
fails closed unless it is exactly the six-tool contract. It also rejects every
tool call outside that contract.

## Upstream architecture used

The integration follows the public upstream layering:

1. LangGraph runs the state graph.
2. LangChain supplies the model-and-tool loop and middleware interface.
3. Deep Agents composes filesystem middleware and the agent harness.

Python `create_deep_agent` and TypeScript `createDeepAgent` return compiled
LangGraph graphs, but this project does not attach a checkpointer or store.
Resume, replay, cross-thread memory, and long-term memory are therefore absent
from the authoritative path. They would require separate retention,
concurrency, poisoning, and replay controls before being enabled.

LangSmith is also optional upstream functionality. It is not required here and
tracing is disabled because traces may contain incident evidence, prompts, tool
arguments, tool output, and model responses.

## Upstream version boundary

The qualified Python runtime uses:

- `deepagents==0.7.8`;
- `langgraph==1.2.11`;
- `langchain==1.3.17`;
- `langsmith==0.11.1`; and
- exact provider-adapter versions recorded in the dependency qualification
  evidence.

Python 3.11 and 3.12 lock files contain the complete transitive package set and
artifact hashes. See [Dependency qualification](dependency-qualification.md)
for reproduction, upgrade, and rollback instructions.

The qualified TypeScript runtime uses Node 22.23.2 and npm 10.9.8 with:

- `deepagents@1.13.1`;
- `langchain@1.5.10`;
- `@langchain/core@1.2.9`;
- `@langchain/langgraph@1.4.13`;
- `langsmith@0.9.0`; and
- exact OpenAI, Anthropic, Google GenAI, and Ollama adapters recorded in the
  TypeScript qualification evidence.

Its lockfile v3 records every transitive registry URL and integrity digest. The
installer disables lifecycle scripts, compiles with `typescript@7.0.2`, and
requires the generated worker digest to match controller policy.

## What remains authoritative

Deep Agents may reason about the bounded request and edit the disposable copy.
It cannot approve its own result. The controller independently:

1. derives the Git patch;
2. applies path, content, file-type, mode, and size policy;
3. runs repository tests and the controller-owned verifier;
4. requires nonce-bound completion evidence;
5. reapplies the exact patch to a clean baseline;
6. compares the resulting candidate digest; and
7. permits only local draft artifacts after successful cleanup.

Model text, tool output, LangGraph state, process exit zero, and candidate files
are never acceptance evidence by themselves.

## Official references

- [Deep Agents overview](https://docs.langchain.com/oss/python/deepagents/overview)
- [Deep Agents JavaScript overview](https://docs.langchain.com/oss/javascript/deepagents/overview)
- [Deep Agents backends](https://docs.langchain.com/oss/python/deepagents/backends)
- [Deep Agents harness](https://docs.langchain.com/oss/python/deepagents/harness)
- [Deep Agents long-term memory](https://docs.langchain.com/oss/python/deepagents/long-term-memory)
- [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence)
- [LangGraph interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)
- [LangGraph fault tolerance](https://docs.langchain.com/oss/python/langgraph/fault-tolerance)
- [LangSmith tracing for Deep Agents](https://docs.langchain.com/langsmith/trace-deep-agents)

The exact documentation and source revisions used for qualification are
machine-readable in `security/dependency-qualification.json` and
`security/typescript-dependency-qualification.json`.
