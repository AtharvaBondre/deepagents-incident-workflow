# Repository instructions

## Commands

Run commands from the repository root:

```bash
./scripts/bootstrap-pinned-images.sh sandbox
./scripts/run-local.sh preflight
./scripts/run-local.sh dump-policy
./scripts/run-local.sh test
./scripts/run-local.sh run --scenario retry-success --budget-seconds 120 --max-attempts 2
./scripts/run-local.sh verify --latest
python3 scripts/check-public-surface.py
git diff --check
```

For SDK-facing changes, also run:

```bash
./scripts/install-deepagents-runtime.sh
.deepagents-runtime/bin/python scripts/deepagents_sdk_smoke.py
./scripts/run-local.sh preflight --require-deepagents --deepagents-python .deepagents-runtime/bin/python
```

## Always

- Keep the repository customer-neutral and use only synthetic fixtures and disposable local services.
- Keep Deep Agents and direct model adapters external and exactly pinned for qualified runs. Record observed LangGraph, LangChain, and LangSmith versions; add a complete transitive lock before claiming fully reproducible dependency resolution.
- Use the SDK-native worker as the integration surface and keep its tool surface to `ls`, `read_file`, `write_file`, `edit_file`, `glob`, and `grep`.
- Let `scripts/runner.py` own attempts, deadlines, policy, acceptance, artifact linkage, delivery eligibility, and cleanup.
- Treat every model or fixture success claim as untrusted until deterministic verification accepts the exact candidate.
- Use `apply_patch` for manual edits and run the unit, public-surface, formatting, and relevant Docker checks before handoff.

## Ask first

- Ask before adding shell, deletion, network tools, delegation, persistent memory, MCP, hooks, plugins, hosted tracing, live connectors, or a new execution backend.
- Ask before changing the controller/verifier trust boundary, image digests, vulnerability baseline, delivery mode, or external publication state.

## Never

- Never add real credentials, customer identifiers, internal endpoints, retained model sessions, billing data, or absolute user paths.
- Never vendor Deep Agents, LangGraph, LangChain, LangSmith, provider adapters, plugins, assets, or dependency trees.
- Never make `dcode`, LangSmith, Agent Server, remote sandboxes, or shared memory part of the default authoritative path.
- Never expose merge, approval, deployment, production-write, or incident-mutation operations; delivery stays file-based and draft-only.
