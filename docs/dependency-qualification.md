# Dependency qualification

The optional Deep Agents runtimes are reproducible for Python 3.11/3.12 and
TypeScript on Node 22.23.2 without vendoring third-party code. The repository
records resolver policy, exact dependency locks and integrity, package
provenance, license conclusions, source tags/commits, and reviewed official
documentation snapshots.

## Trusted records

- `security/dependency-policy.json` is the single source of truth for the exact
  `uv` version, official package index, resolution cutoff, universal resolution,
  and hash requirement.
- `requirements/deepagents-py311-universal.lock` and
  `requirements/deepagents-py312-universal.lock` contain exact transitive
  versions and PyPI artifact hashes.
- `security/dependency-qualification.json` binds both lock digests to the
  corresponding official PyPI release artifacts, license evidence, locked
  package versions, release uploads, Git tags, source-path commits, and all 40
  Deep Agents Python plus 16 Deep Agents Code documentation pages.
- `typescript-runtime/package-lock.json` is a lockfile v3 containing exact
  versions, official npm registry URLs, and SHA-512 integrity for all 82
  TypeScript runtime/build packages. Lifecycle scripts are forbidden.
- `security/typescript-dependency-qualification.json` binds that lock to Node
  22.23.2, npm 10.9.8, `deepagents@1.13.1`, its official npm tarball,
  `langchain-ai/deepagentsjs` tag and commit, license totals, audit result, and
  the official JavaScript and Code overview pages.

The installer separately compares every applicable installed distribution and
version with the selected lock before declaring the runtime valid.

The lock parser rejects unpinned requirements, malformed or duplicate hashes,
indexes, VCS references, local paths, and editable sources. Qualification also
rejects an artifact hash not present in official PyPI metadata, an upload newer
than the resolution cutoff, an unreviewed license, a license conclusion that
does not follow from its evidence, or a source tag that does not match the
locked Deep Agents or LangGraph version.

## Routine checks

The offline check is authoritative for installation and CI:

```bash
python3 -I scripts/dependency_qualification.py
./scripts/install-deepagents-runtime.sh
python3 -I scripts/typescript_dependency_qualification.py
./scripts/install-deepagents-typescript-runtime.sh
```

The online check compares the trusted record with the current official PyPI,
GitHub, and LangChain documentation surfaces:

```bash
python3 -I scripts/dependency_qualification.py --online
python3 -I scripts/typescript_dependency_qualification.py --online
```

Only HTTPS requests to the explicit PyPI, LangChain documentation, and tracked
LangChain GitHub repository paths are permitted. Redirect targets are checked
before they are followed. Online drift is a review signal, never permission to
change a pin automatically.

The scheduled `Upstream drift` workflow runs that comparison and rebuilds the
Python and TypeScript SDK smoke images. It has read-only repository permissions
and cannot create a branch, pull request, release, or deployment. The
TypeScript online check also reruns the production-only npm advisory query with
the qualified Node and npm versions; a new advisory fails the drift job even
when package versions and documentation are unchanged.

## Controlled upgrade

1. Start from a clean branch and run the current deterministic, SDK, public
   surface, and Docker smoke gates.
2. Install exactly the `uv` version named in `security/dependency-policy.json`
   into a disposable environment.
3. Change direct pins only when the new versions and upstream behavior have
   been deliberately selected. Change the resolution cutoff only to a reviewed
   UTC timestamp.
4. Run `UV_BIN=/path/to/exact/uv ./scripts/refresh-dependency-locks.sh`. The
   script launches `uv` under an environment allowlist with `--no-config`, an
   explicit official index, resolver strategy, prerelease policy, fork policy,
   cutoff, universal mode, binary metadata resolution, and hashes.
5. Review both lock diffs. Confirm that each new package is necessary, its
   license is acceptable, and supported targets still have binary wheels.
6. Run `python3 -I scripts/dependency_qualification.py --capture`. This writes
   only the ignored `security/dependency-qualification.candidate.json`; it does
   not alter the last-known-good record.
7. Diff the candidate against `security/dependency-qualification.json`. Review
   every package, artifact, license, tag, source-path, and documentation change.
8. Run `python3 -I scripts/dependency_qualification.py --promote`. Promotion
   rechecks current official evidence and atomically replaces the trusted record
   only after all checks pass.
9. Rebuild the Python 3.11 and 3.12 runtimes in clean environments, run
   `./scripts/run-network-isolated-sdk-smoke.sh`, and complete every command in
   `docs/verification.md`.

No dependency-update automation is authorized. A maintainer must own every
review and promotion.

For TypeScript upgrades, update exact versions in `package.json`, regenerate
the npm lock using the selected npm version, and review every resolved URL,
integrity, license, lifecycle-script flag, source tag, and provider adapter.
Then update the qualification record, compile the worker, record its new digest
in both workflow policies, rebuild the isolated runtime, and run the direct,
end-to-end, and network-none TypeScript smokes. Never use a floating semver
range or accept a local, Git, workspace, or alternate-registry dependency.

This qualification is not a signed supply-chain attestation. Python evidence
does not claim a vulnerability scan; TypeScript records the reviewed production
`npm audit` result but does not treat it as a substitute for lock integrity or
runtime isolation. Add stronger signature or vulnerability policy only as a
separately designed gate.

## Rollback criteria

Keep the previous direct pins, both lockfiles, resolver policy, and qualification
record as one atomic review unit. Revert that unit if any of these occur:

- lock resolution, hash verification, provenance, or license validation fails;
- Python 3.11, Python 3.12, Node 22.23.2, npm 10.9.8, or locked package
  installation fails;
- the six-tool worker surface, path isolation, or no-transport behavior changes;
- deterministic tests, trusted verification, clean reapply, or draft delivery
  linkage changes;
- the OS network-disabled smoke, cleanup checks, or public-surface scan fails;
- upstream source/default changes cannot be explained and accepted explicitly.

Do not fix an upgrade by weakening hashes, widening hosts, allowing source
builds, accepting an unknown license, changing the verifier boundary, or
enabling a new tool. Those are separate design decisions with separate review.
