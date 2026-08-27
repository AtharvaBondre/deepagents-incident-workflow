# Model provider setup

The default fixture workflow needs no model account, API key, or paid request.
Use a real model only as an explicit manual option after the deterministic
workflow passes.

## 1. Choose and install a qualified SDK runtime

Python is the default and supports Python 3.11 or 3.12:

```bash
./scripts/install-deepagents-runtime.sh
```

TypeScript is equally supported and requires exactly Node.js 22.23.2 and npm
10.9.8:

```bash
node --version  # v22.23.2
npm --version   # 10.9.8
./scripts/install-deepagents-typescript-runtime.sh
```

The installers create ignored `.deepagents-runtime/` or
`.deepagents-typescript-runtime/` environments from the qualified dependency
locks. The TypeScript installer rejects lifecycle scripts, verifies the source,
lock, and compiled-worker digests, and refuses a different Node or npm version.
Installation contacts only the official package registry. Candidate-code tests
and verification later run with network access disabled.

## 2. Configure one provider

Set credentials in the invoking process through your shell, CI secret store, or
another secret manager. Never write a real value into this repository, an
incident fixture, a command argument, or an artifact.

| `--deepagents-provider` | Required environment | Optional environment |
| --- | --- | --- |
| `openai` | `OPENAI_API_KEY` | `OPENAI_ORG_ID`, `OPENAI_PROJECT_ID` |
| `anthropic` | `ANTHROPIC_API_KEY` | None |
| `google_genai` | `GOOGLE_API_KEY` | None |
| `ollama` | None | None |

For example, after loading a key from your preferred secret manager:

```bash
export OPENAI_API_KEY="<your-key>"
```

The controller forwards only the selected provider's approved variable names
to the worker. It deliberately removes base-URL overrides, unrelated provider
keys, cloud credentials, source-control tokens, and other ambient variables.
Custom OpenAI-compatible endpoints and a custom `OLLAMA_HOST` are therefore not
supported by the secure adapter.

For Ollama, start the local service and pull the requested model before running
the workflow. Standard model tags such as `model-name:tag` are accepted.

## 3. Check the setup without making a model request

Python:

```bash
./scripts/run-local.sh preflight \
  --with-docker \
  --require-deepagents \
  --deepagents-python .deepagents-runtime/bin/python \
  --deepagents-provider openai
```

TypeScript:

```bash
./scripts/run-local.sh preflight \
  --with-docker \
  --require-deepagents \
  --deepagents-language typescript \
  --deepagents-node node \
  --deepagents-provider openai
```

The preflight checks the pinned SDK runtime, Docker, and presence of the
required credential name. It never prints the credential value and does not
contact the model provider. For `ollama`, it reports that no key is required;
the first real run is responsible for proving that the local service and model
are available.

## 4. Run and independently verify

Replace `replace-with-model-id` with a model available to the configured
account. Python is the default:

```bash
./scripts/run-local.sh run \
  --scenario retry-success \
  --candidate-provider deepagents \
  --deepagents-provider openai \
  --deepagents-model "replace-with-model-id" \
  --deepagents-python .deepagents-runtime/bin/python \
  --budget-seconds 600 \
  --max-attempts 2

./scripts/run-local.sh verify --latest
```

TypeScript uses the same command with an explicit language selection:

```bash
./scripts/run-local.sh run \
  --scenario retry-success \
  --candidate-provider deepagents \
  --deepagents-language typescript \
  --deepagents-provider openai \
  --deepagents-model "replace-with-model-id" \
  --deepagents-node node \
  --budget-seconds 600 \
  --max-attempts 2

./scripts/run-local.sh verify --latest
```

The SDK language selects the agent implementation, not the candidate
repository language. Both workers produce a controller-derived patch and use
the identical policy, verifier, clean-reapply, delivery, and cleanup gates.

Provider values are `openai`, `anthropic`, `google_genai`, and `ollama`. Model
identifiers are passed to the corresponding pinned LangChain adapter. The model
request is the only intended network operation in this mode; candidate tests
and trusted verification remain network-disabled.

## Troubleshooting

- **Python runtime rejected:** rebuild it with
  `./scripts/install-deepagents-runtime.sh`.
- **TypeScript runtime rejected:** use Node 22.23.2 with npm 10.9.8, then rerun
  `./scripts/install-deepagents-typescript-runtime.sh`. Do not bypass the
  source, lock, or compiled-worker digest check.
- **Missing credential:** load the required variable and rerun the provider
  preflight. Do not commit an `.env` file.
- **Model not found:** use an identifier supported by the selected provider and
  account. The project does not choose or provision models.
- **Ollama connection failed:** confirm the local Ollama service is running and
  the named model is already present at the default local endpoint.
- **Docker unavailable:** start Docker and rerun the preflight with
  `--with-docker`.

Review the provider's processing, retention, regional, and billing terms before
using non-synthetic input. A successful provider call does not bypass any
controller verification gate.
