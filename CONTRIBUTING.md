# Contributing

Contributions that improve deterministic policy, isolation, verification, portability, documentation, or synthetic examples are welcome.

## Development workflow

1. Create a focused branch.
2. Keep all examples synthetic and free of customer or provider credentials.
3. Run `./scripts/run-local.sh preflight --with-docker` when Docker is available.
4. Run `./scripts/run-local.sh test`.
5. For TypeScript runtime changes, run
   `python3 -I scripts/typescript_dependency_qualification.py`,
   `./scripts/install-deepagents-typescript-runtime.sh`,
   `node --test .deepagents-typescript-runtime/dist/deepagents_worker.test.js`,
   both TypeScript smokes, and the
   TypeScript preflight documented in `AGENTS.md`.
6. Run `python3 scripts/check-public-surface.py`.
7. For changes to the service example, run the event-indexing scenario and verify the resulting run.
8. Explain security-boundary changes explicitly in the pull request.

Do not add automatic merge, approval, deployment, production-write, or incident-mutation operations. Proposals for live connectors must begin with a threat model and a brokered least-privilege interface.

## Public repository hygiene

Commit only material intended for users, contributors, security review, or
release verification. Keep continuation handoffs, phase plans, raw research
workpads, reviewer notes, orchestration state, generated artifacts, sessions,
credentials, and private adaptations outside the repository. The public-surface
check rejects known internal coordination paths and common disclosure patterns.

By submitting a contribution, you agree that it is licensed under Apache-2.0 and that you have the right to contribute it.
