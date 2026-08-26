# Deep Agents integration

This project uses LangChain's open-source Deep Agents Python SDK as an
untrusted candidate author. Deep Agents, LangChain, LangGraph, LangSmith, model
providers, and their dependencies remain external packages and are not
vendored.

## Why the SDK is the integration point

The SDK lets the controller construct the exact agent used for an attempt. The
worker creates `deepagents==0.7.8` with:

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

## Upstream architecture used

The integration follows the public upstream layering:

1. LangGraph runs the state graph.
2. LangChain supplies the model-and-tool loop and middleware interface.
3. Deep Agents composes filesystem middleware and the agent harness.

`create_deep_agent` returns a compiled LangGraph graph, but this project does
not attach a checkpointer or store. Resume, replay, cross-thread memory, and
long-term memory are therefore absent from the authoritative path. They would
require separate retention, concurrency, poisoning, and replay controls before
being enabled.

LangSmith is also optional upstream functionality. It is not required here and
tracing is disabled because traces may contain incident evidence, prompts, tool
arguments, tool output, and model responses.

## Upstream version boundary

The qualified runtime uses:

- `deepagents==0.7.8`;
- `langgraph==1.2.11`;
- `langchain==1.3.17`;
- `langsmith==0.11.1`; and
- exact provider-adapter versions recorded in the dependency qualification
  evidence.

Python 3.11 and 3.12 lock files contain the complete transitive package set and
artifact hashes. See [Dependency qualification](dependency-qualification.md)
for reproduction, upgrade, and rollback instructions.

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
- [Deep Agents backends](https://docs.langchain.com/oss/python/deepagents/backends)
- [Deep Agents harness](https://docs.langchain.com/oss/python/deepagents/harness)
- [Deep Agents long-term memory](https://docs.langchain.com/oss/python/deepagents/long-term-memory)
- [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence)
- [LangGraph interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)
- [LangGraph fault tolerance](https://docs.langchain.com/oss/python/langgraph/fault-tolerance)
- [LangSmith tracing for Deep Agents](https://docs.langchain.com/langsmith/trace-deep-agents)

The exact documentation and source revisions used for qualification are
machine-readable in `security/dependency-qualification.json`.
