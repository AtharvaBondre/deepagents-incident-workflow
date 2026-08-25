# Release checklist

- [ ] Confirm the repository owner has the right to publish and license every original file.
- [ ] Confirm the project name and Deep Agents references comply with applicable trademark guidance.
- [ ] Confirm no customer agreement, confidential architecture, or proprietary code is represented.
- [ ] Run `python3 scripts/check-public-surface.py`.
- [ ] Run `./scripts/run-local.sh dump-policy` and confirm the effective policy
      exposes only generic placeholders and draft-only delivery.
- [ ] Refresh `docs/model-costing.md` against provider pricing pages before any
      customer-facing quote.
- [ ] Run `./scripts/run-local.sh test` twice from a clean clone.
- [ ] Run the event-indexing Docker scenario and `verify --latest`.
- [ ] Confirm pre-launch cleanup intents exist and no run container, network, or volume remains, including after a simulated controller crash.
- [ ] Validate the exact Deep Agents SDK version, strict request/result schemas, six-tool contract, write-prefix enforcement, direct graph smoke, and full controller-to-worker no-transport smoke on Python 3.11 and 3.12.
- [ ] Run pinned Ruff lint and formatting checks.
- [ ] Review pinned image indexes for supported architectures.
- [ ] Review dependencies and update `THIRD_PARTY_NOTICES.md`.
- [ ] Run the pinned-image vulnerability check and review every unexpired exception.
- [ ] Review GitHub Actions permissions and pinned action commits.
- [ ] Confirm generated artifacts, sessions, credentials, and local paths are ignored and absent from Git.
- [ ] Confirm README limitations match the tested release.
- [ ] Confirm `customer-pack-template/` contains only placeholders and synthetic
      examples.
- [ ] Tag only after CI passes on the published commit.
