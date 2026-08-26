# Dependency qualification

The optional Deep Agents runtime is reproducible for the supported Python 3.11
and 3.12 targets without vendoring third-party code. The repository records the
resolver policy, universal hash locks, exact package provenance, normalized
license conclusions, source tags, relevant source-path commits, and the complete
official Deep Agents documentation inventory.

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
```

The online check compares the trusted record with the current official PyPI,
GitHub, and LangChain documentation surfaces:

```bash
python3 -I scripts/dependency_qualification.py --online
```

Only HTTPS requests to the explicit PyPI, LangChain documentation, and tracked
LangChain GitHub repository paths are permitted. Redirect targets are checked
before they are followed. Online drift is a review signal, never permission to
change a pin automatically.

The scheduled `Upstream drift` workflow runs that comparison and rebuilds the
SDK smoke image. It has read-only repository permissions and cannot create a
branch, pull request, release, or deployment.

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

This qualification is not a signed supply-chain attestation and does not scan
Python packages for known vulnerabilities. It verifies the selected hashes
against HTTPS-served official PyPI metadata, records license evidence, and
detects reviewed upstream drift. Add signature or Python-vulnerability policy
only as a separately designed gate; do not imply either from this record.

## Rollback criteria

Keep the previous direct pins, both lockfiles, resolver policy, and qualification
record as one atomic review unit. Revert that unit if any of these occur:

- lock resolution, hash verification, provenance, or license validation fails;
- Python 3.11, Python 3.12, or Linux wheel installation fails;
- the six-tool worker surface, path isolation, or no-transport behavior changes;
- deterministic tests, trusted verification, clean reapply, or draft delivery
  linkage changes;
- the OS network-disabled smoke, cleanup checks, or public-surface scan fails;
- upstream source/default changes cannot be explained and accepted explicitly.

Do not fix an upgrade by weakening hashes, widening hosts, allowing source
builds, accepting an unknown license, changing the verifier boundary, or
enabling a new tool. Those are separate design decisions with separate review.
