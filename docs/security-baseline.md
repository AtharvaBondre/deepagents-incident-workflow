# Container security baseline

All upstream base and service image inputs are pinned by multi-architecture OCI
index digest. The candidate-test and verifier image had no HIGH or CRITICAL
findings when scanned with Trivy 0.70.0 on 2026-08-18. The Deep Agents host
runtimes remain external. The Python smoke uses the qualified Python 3.12
Alpine base; the TypeScript smoke uses the exact Node 22.23.2 Alpine image.
Both build per-run, nonce-labeled images from qualified locks.

The disposable PostgreSQL, Kafka, and OpenSearch images retain upstream
findings even at the current stable versions used for qualification. They are
accepted only for this synthetic local POC because they expose no host ports,
run on an internal disposable network, receive no credentials or customer data,
and are destroyed after the run. This is not a production exception.

The exact finding sets are hash-bound in
`security/image-vulnerability-baseline.json`. Exceptions expire on 2026-09-18.
The check fails when a pin changes, a finding is added or altered, the scanner
version changes, or the exception expires:

```bash
python3 scripts/check-image-vulnerabilities.py
```

Refresh an image and requalify the full workflow before changing the baseline.
Do not extend an exception solely to make CI pass.

Python 3.11/3.12 and TypeScript runtime dependencies are fully version- and
integrity-locked.
`security/dependency-qualification.json` binds the lockfiles to official PyPI
artifacts, normalized license evidence, source tags, scoped source commits, and
the official documentation inventory. Validate it offline before installation:

```bash
python3 -I scripts/dependency_qualification.py
python3 -I scripts/typescript_dependency_qualification.py
```

Each SDK smoke image is built from its qualified lock using ordinary build
network access. The resulting smoke container then runs with Docker network
mode `none`, a read-only root, an unprivileged UID, resource limits, a
controller execution deadline, strict controller-side result validation, and
verified per-run cleanup. Dependency-update pull requests remain manual and
disabled by default; CI and the scheduled read-only drift job cannot silently
widen runtime versions. See `docs/dependency-qualification.md` for upgrade and
rollback rules.

The pinned Node base currently carries reviewed upstream findings, including a
critical finding in npm's bundled build tooling. Development dependencies are
pruned and npm, Corepack, Yarn, source files, and compiler inputs are removed
from the final TypeScript smoke image before execution. That container is
synthetic-only, network-disabled, read-only, and unprivileged; the expiring
exception is not approval for a production runtime image.
