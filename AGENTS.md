# Repository instructions

- Keep this repository customer-neutral and safe to publish.
- Use only synthetic fixtures and disposable local services.
- Never add real credentials, customer identifiers, internal endpoints, retained model sessions, or absolute user paths.
- Keep Deep Agents and the direct model adapters external and exactly pinned for qualified runs; record observed LangGraph/LangChain/LangSmith versions and add a complete transitive lock before claiming fully reproducible dependency resolution. Never vendor their source, plugins, assets, or dependency trees.
- Use the SDK-native worker as the integration surface. Treat `dcode`, LangSmith, Agent Server, MCP, hooks, plugins, remote sandboxes, and shared memory as optional and outside the default path.
- Keep the agent tool surface to `ls`, `read_file`, `write_file`, `edit_file`, `glob`, and `grep`; do not add shell, deletion, network, delegation, or persistent memory without explicit security review.
- Let `scripts/runner.py` own attempts, deadlines, policy, acceptance, artifact linkage, delivery eligibility, and cleanup.
- Treat every model or fixture success claim as untrusted until deterministic verification accepts the exact candidate.
- Keep delivery file-based and draft-only. Do not expose merge, approval, deployment, production-write, or incident-mutation operations.
- Use `apply_patch` for manual edits and run the unit, public-surface, and relevant Docker checks before handoff.

## Required validation

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
