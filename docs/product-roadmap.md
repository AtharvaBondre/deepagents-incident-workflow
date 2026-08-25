# Product Roadmap

This project is a local-first reference implementation today. The product
direction is a configurable incident-remediation workflow that customers can run
against their own repositories, evidence sources, and delivery process while
preserving the core rule: Deep Agents proposes, the controller decides.

## Current product boundary

The current release supports:

- synthetic incidents and fixture repositories;
- deterministic retry, exhaustion, timeout, and injection-rejection paths;
- a real Deep Agents adapter for explicit manual qualification;
- capability-limited disposable candidate editing plus isolated candidate testing;
- optional disposable PostgreSQL, Kafka, and OpenSearch verification;
- draft-only file delivery;
- auditable artifacts and cleanup records.

It intentionally does not include live production connectors.

## Near-term work

- Generate complete cross-platform transitive dependency locks for the supported
  Python versions without vendoring packages.
- Add package provenance and license policy checks, then qualify an exact
  upstream source tag or commit alongside each package pin.
- Run the SDK construction smoke inside an OS network-disabled CI boundary.
- Define controlled upstream release/default-drift review and rollback criteria.
- Keep dependency-update PR automation disabled until a maintainer explicitly
  authorizes and owns that workflow.
- Add Linux AMD64 qualification from a clean public clone.

## Later gated work

- Add a packaged customer-pack loader only after the explicit private-pack
  selection and schema boundary is implemented.
- Add connector interfaces for log evidence, database evidence, source-control
  delivery, and notification delivery only after fixture-first threat tests.
- Add more synthetic scenarios for API regressions, background jobs, migrations,
  and test-failure repair.
- Add a repeated real-model qualification script that records pass rate, retry
  behavior, runtime, cleanup, and worker-output contract quality.
- Add signed or externally stored attestations only when immutable retention is
  an explicit requirement.

## Connector roadmap

Connectors should be brokered services, not raw credentials exposed to the
model. Each connector should accept a versioned request, enforce policy, return
bounded redacted output, and write an audit record.

Candidate connector families:

- log evidence broker;
- relational database evidence broker;
- source-control draft publisher;
- notification publisher;
- incident-trigger receiver;
- artifact retention sink.

## Product packaging roadmap

- Keep the public repository as the reusable core.
- Keep private customer packs outside the public repository.
- Publish versioned releases with compatibility notes for the Deep Agents SDK, Docker,
  Python, and container image pins.
- Provide an operator checklist for each release.
- Maintain a threat model for every connector family before adding live effects.

## Readiness levels

| Level | Meaning |
|---|---|
| Local fixture | Synthetic incident passes without model credentials. |
| Local real-model | Synthetic incident passes with a real Deep Agents model. |
| Customer-pack dry run | Private pack passes with sanitized customer-shaped data. |
| Non-production pilot | Brokered connectors run against approved non-production systems. |
| Production evidence pilot | Read-only production evidence is used with customer approval. |
| Production workflow | Repeatability, recovery, audit, cost, and ownership are proven. |

Do not skip readiness levels by adding a live connector directly to the public
fixture path.
