# Changelog

## Unreleased

- Added first-class TypeScript SDK support on Node 22.23.2 with
  `deepagents@1.13.2`, the same six-tool boundary and controller-owned
  verification path as Python, an integrity-locked npm graph, a digest-bound
  compiled worker, direct and end-to-end no-transport smokes, and an
  unprivileged network-none Docker smoke.
- Added controller-owned dispatch rejection for forged `execute`, `delete`,
  `task`, and `write_todos` calls in both SDK workers, with direct adversarial
  smoke coverage that also proves the workspace remains unchanged. The
  TypeScript boundary also rejects unnamed or malformed provider-side tools.
- Added exact provider-model construction for tagged Ollama identifiers,
  removed subagent middleware instead of merely hiding its tool, pruned
  TypeScript build dependencies from runtime images, installed no-transport
  interception before SDK imports with fetch, socket, and DNS coverage, and
  added a scheduled live production npm advisory check.
- Documented why the direct SDK is the supported integration and kept the
  optional `deepagents-code==0.1.65` lane disabled because the current CLI
  cannot satisfy the complete ambient-state and network-isolation contract.
- Added public model-provider setup and offline credential-presence preflight
  guidance without storing or printing secret values.
- Removed dated research, continuation, and internal planning documents from
  the public tree and added a public-surface regression guard for them.
- Refreshed the hash-locked dependency evidence to the 2026-08-31 cutoff and
  upgraded the qualified SDKs to `deepagents==0.7.11` and
  `deepagents@1.13.2` after direct, end-to-end, and network-none validation.
- Scoped optional GitHub authentication for upstream qualification to direct,
  proxy-free `api.github.com` requests and stripped it before every cross-host
  redirect.

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
- Added a pinned Hermes reference-parity contract so applicable safety
  guarantees can be maintained without coupling runtimes.
- Added strict public Deep Agents request/result schemas and fail-closed
  top-level field validation at both ends of the worker boundary.
- Added a no-cost full controller-to-worker Deep Agents smoke, including patch
  derivation, Docker verification, clean reapply, draft delivery, and cleanup.
- Fixed retained-patch identity checks to compare canonical paths, including
  macOS `/var` and `/private/var` aliases, without weakening collision checks.
- Expanded CI to run pinned Ruff and both SDK smokes on Python 3.11 and 3.12.
- Added reproducible Python 3.11/3.12 universal dependency locks with complete
  artifact hashes, exact resolver policy, PyPI provenance, and normalized
  license evidence.
- Added staged, atomic upstream qualification for package releases, source tags,
  scoped source commits, and the complete 40-page Python plus 16-page Code
  documentation inventory.
- Added an unprivileged, read-only, resource-bounded Docker SDK smoke with OS
  network isolation, controller-owned deadlines, strict retained-result
  validation, ownership-bound cleanup, and read-only scheduled drift detection.
