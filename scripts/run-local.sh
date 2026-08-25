#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
package_root="$(cd "${script_dir}/.." && pwd)"
cd "${package_root}"

runner_environment=(
  "PATH=${PATH}"
  "HOME=${HOME}"
  "USER=${USER:-user}"
  "SHELL=${SHELL:-/bin/sh}"
  "TMPDIR=${TMPDIR:-/tmp}"
  "LANG=${LANG:-C.UTF-8}"
)

# The controller receives only known model-transport variables. It narrows this
# list again to the selected provider before starting the untrusted worker.
# Candidate-code containers never receive these values.
provider_environment_names=(
  ANTHROPIC_API_KEY
  GOOGLE_API_KEY
  OPENAI_API_KEY
  OPENAI_ORG_ID
  OPENAI_PROJECT_ID
)
for name in "${provider_environment_names[@]}"; do
  value="${!name-}"
  if [[ -n "${value}" ]]; then
    runner_environment+=("${name}=${value}")
  fi
done

exec env -i "${runner_environment[@]}" \
  python3 "${script_dir}/runner.py" "$@"
