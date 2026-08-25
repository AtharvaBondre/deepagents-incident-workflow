# Changelog

## 0.1.0 - 2026-08-25

- Added a policy-controlled local remediation controller.
- Added deterministic success, retry, exhaustion, timeout, and injection-rejection scenarios.
- Added an exact-pinned Deep Agents SDK worker with a six-tool, no-shell,
  no-memory integration surface and a no-cost scripted SDK smoke.
- Added optional PostgreSQL, Kafka, and OpenSearch verification for a synthetic event-indexing incident.
- Added exact-patch, clean-reapply, artifact-linkage, environment-scrubbing, and cleanup checks.
- Added public documentation, CI, schemas, and disclosure checks.
- Added customer-pack guidance, connector contracts, and a reusable private-pack
  template for organization-specific adoption.
- Isolated every candidate test and verifier from the host in a locked-down Docker sandbox.
- Hash-locked verifier dependencies and upgraded kafka-python to 2.3.2.
- Refreshed disposable service pins and added an expiring, hash-bound image vulnerability baseline.
- Added an AST-only semantic verifier for the synthetic pure-function fixtures
  plus fail-closed outer verifier supervision for early exit, forged success,
  crash, nonzero exit, signal, and timeout cases.
- Added pre-launch recovery journals for candidate/verifier containers and
  Compose projects, strict ownership revalidation, and crash-window regressions.
- Bound draft delivery to the validated repository/base/head and revoke it on
  every non-successful closeout.
- Rejected hidden Git rename/copy metadata, reconciled post-apply paths, and
  covered adversarial dictionary-unpack execution in the AST verifier.
- Added a pinned Hermes reference-parity contract and a complete continuation
  handoff so future work preserves shared guarantees without coupling runtimes.
- Added strict public Deep Agents request/result schemas and fail-closed
  top-level field validation at both ends of the worker boundary.
- Added a no-cost full controller-to-worker Deep Agents smoke, including patch
  derivation, Docker verification, clean reapply, draft delivery, and cleanup.
- Fixed retained-patch identity checks to compare canonical paths, including
  macOS `/var` and `/private/var` aliases, without weakening collision checks.
- Expanded CI to run pinned Ruff and both SDK smokes on Python 3.11 and 3.12.
