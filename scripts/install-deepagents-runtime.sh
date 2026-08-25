#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repository_root="$(cd "${script_dir}/.." && pwd)"
runtime_dir="${DEEPAGENTS_RUNTIME_DIR:-${repository_root}/.deepagents-runtime}"
python_bin="${PYTHON_BIN:-python3}"

if [[ "${runtime_dir}" != "${repository_root}/.deepagents-runtime" ]]; then
  printf '%s\n' 'DEEPAGENTS_RUNTIME_DIR must point to the repository .deepagents-runtime directory.' >&2
  exit 1
fi

if [[ -L "${runtime_dir}" ]]; then
  printf '%s\n' 'Refusing to rebuild a symlinked .deepagents-runtime directory.' >&2
  exit 1
fi
if [[ -e "${runtime_dir}" && ! -d "${runtime_dir}" ]]; then
  printf '%s\n' 'Refusing to rebuild a non-directory .deepagents-runtime path.' >&2
  exit 1
fi

# Rebuild instead of reusing an environment that may contain stale profile
# entry points or interpreter startup hooks from an earlier experiment. The
# exact repository-local target was checked above before the destructive clear.
"${python_bin}" -m venv --clear "${runtime_dir}"

"${runtime_dir}/bin/python" -m pip install --disable-pip-version-check \
  "${repository_root}[deepagents]"

"${runtime_dir}/bin/python" - <<'PY'
from importlib.metadata import version

expected = {
    "deepagents": "0.7.8",
    "langchain-anthropic": "1.6.1",
    "langchain-google-genai": "4.3.5",
    "langchain-ollama": "1.1.0",
    "langchain-openai": "1.6.0",
}
actual = {package: version(package) for package in expected}
if actual != expected:
    raise SystemExit(f"Deep Agents runtime mismatch: expected {expected}, found {actual}")
from importlib.metadata import entry_points
plugins = [
    f"{group}:{entry.name}"
    for group in ("deepagents.provider_profiles", "deepagents.harness_profiles")
    for entry in entry_points(group=group)
]
if plugins:
    raise SystemExit(f"Forbidden Deep Agents profile entry points: {plugins}")
print("Validated Deep Agents runtime: " + ", ".join(f"{key}=={value}" for key, value in actual.items()))
PY

printf 'Deep Agents runtime is installed in %s\n' "${runtime_dir}"
