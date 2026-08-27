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
python3 -I scripts/dependency_qualification.py
python3 -I scripts/typescript_dependency_qualification.py
python3 scripts/check-public-surface.py
git diff --check
```

For SDK-facing changes, also run:

```bash
./scripts/install-deepagents-runtime.sh
.deepagents-runtime/bin/python scripts/deepagents_sdk_smoke.py
.deepagents-runtime/bin/python scripts/deepagents_e2e_smoke.py \
  --python .deepagents-runtime/bin/python
./scripts/run-local.sh preflight --require-deepagents --deepagents-python .deepagents-runtime/bin/python
./scripts/run-network-isolated-sdk-smoke.sh
```

For TypeScript SDK-facing changes, also run:

```bash
./scripts/install-deepagents-typescript-runtime.sh
node --test .deepagents-typescript-runtime/dist/deepagents_worker.test.js
node .deepagents-typescript-runtime/dist/deepagents_sdk_smoke.js
python3 scripts/deepagents_e2e_smoke.py --language typescript --node node
./scripts/run-local.sh preflight --require-deepagents \
  --deepagents-language typescript --deepagents-node node
./scripts/run-network-isolated-typescript-sdk-smoke.sh
```

## Always

- Keep the repository customer-neutral and use only synthetic fixtures and disposable local services.
- Keep Deep Agents and model adapters external and install them only from the qualified transitive hash locks. Preserve the recorded LangGraph, LangChain, and LangSmith versions, provenance, and license evidence.
- Use the Python or TypeScript SDK-native worker as the integration surface and keep both tool surfaces to `ls`, `read_file`, `write_file`, `edit_file`, `glob`, and `grep`.
- Let `scripts/runner.py` own attempts, deadlines, policy, acceptance, artifact linkage, delivery eligibility, and cleanup.
- Treat every model or fixture success claim as untrusted until deterministic verification accepts the exact candidate.
- Keep continuation handoffs, phase plans, raw research workpads, reviewer notes,
  and orchestration control records outside the repository. Public documentation
  must serve users, contributors, security reviewers, or release verification.
- Use `apply_patch` for manual edits and run the unit, public-surface, formatting, and relevant Docker checks before handoff.

## Ask first

- Ask before adding shell, deletion, network tools, delegation, persistent memory, MCP, hooks, plugins, hosted tracing, live connectors, or a new execution backend.
- Ask before changing the controller/verifier trust boundary, image digests, vulnerability baseline, delivery mode, or external publication state.

## Never

- Never add real credentials, customer identifiers, internal endpoints, retained model sessions, billing data, or absolute user paths.
- Never vendor Deep Agents, LangGraph, LangChain, LangSmith, provider adapters, plugins, assets, or dependency trees.
- Never make `dcode`, LangSmith, Agent Server, remote sandboxes, or shared memory part of the default authoritative path.
- Never expose merge, approval, deployment, production-write, or incident-mutation operations; delivery stays file-based and draft-only.
