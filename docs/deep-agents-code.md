# Why this project does not use Deep Agents Code

Deep Agents Code is LangChain's interactive coding-agent CLI, exposed as
`dcode`. It is useful for a human-operated coding session, but this repository
has a narrower requirement: an unattended candidate author must not gain
authority over verification, delivery, persistent state, or unrelated host
capabilities.

## Current compatibility status

The reviewed `deepagents-code==0.1.65` CLI is not used by the workflow. Its
normal runtime includes a local client/server process, SQLite-backed sessions,
memory and instruction discovery, skills, a general-purpose subagent, goal
middleware, `fetch_url`, `get_current_thread_id`, hooks, plugins, and update
paths. Its managed configuration and headless flags can narrow several of those
surfaces—for example MCP, the JavaScript interpreter, model selection, shell
approval, automatic memory writes, and updates—but do not provide one supported
mode that disables all memory loading, skills, subagents, goals, hooks, plugins,
session persistence, and non-filesystem tools. The stock CLI therefore cannot
meet this project's exact six-tool contract.

Wrapping the whole CLI with Docker network mode `none` also blocks the ordinary
remote-model connection. Allowing broad egress would restore model access but
would weaken the required network boundary. A shell-command allowlist is not a
substitute for process isolation or an exact tool allowlist.

## Why the SDK is safer here

The Python and TypeScript SDKs allow each worker to construct the exact
middleware, backend, permission rules, and tool set in code. That makes the
effective surface testable: both SDK smokes fail unless they observe precisely
the six approved filesystem tools and no network attempt.

This is not a claim that the SDK is universally better than `dcode`. The CLI is
the richer interactive product; the SDK is the better fit for this specific
controller-owned, fail-closed workflow.

## Reconsidering a CLI lane

A future optional `dcode` adapter would require both:

1. a supported way to disable memory loading and writes, skills, subagents,
   goals, hooks, plugins, MCP, fetch/network tools, update activity, shell, and
   session reuse so the effective tools exactly match controller policy; and
2. a request-bounded model broker or qualified local model transport that works
   while every other network path remains denied.

It would also need an exact package lock, pinned outer image, process-group
timeouts, ownership-checked cleanup, adversarial failure fixtures, and the same
controller-owned patch and verifier path. Until all of those conditions hold,
the SDK remains the supported integration and the CLI lane remains disabled.

## Upstream references

- [Deep Agents Code overview](https://docs.langchain.com/oss/deepagents/code/overview)
- [`deepagents-code` 0.1.65 source](https://github.com/langchain-ai/deepagents/tree/a233ded7cffd4cc5c81e5767780bf93472dd8fe7/libs/code)
- [Upstream threat model](https://github.com/langchain-ai/deepagents/blob/a233ded7cffd4cc5c81e5767780bf93472dd8fe7/libs/code/THREAT_MODEL.md)
