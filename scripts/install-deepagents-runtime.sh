#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repository_root="$(cd "${script_dir}/.." && pwd)"
runtime_dir="${DEEPAGENTS_RUNTIME_DIR:-${repository_root}/.deepagents-runtime}"

python_bin="${PYTHON_BIN:-}"
if [[ -z "${python_bin}" ]]; then
  for candidate in python3.12 python3.11 python3; do
    if command -v "${candidate}" >/dev/null 2>&1; then
      candidate_version="$("${candidate}" -I -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
      if [[ "${candidate_version}" == "3.11" || "${candidate_version}" == "3.12" ]]; then
        python_bin="${candidate}"
        break
      fi
    fi
  done
fi
if [[ -z "${python_bin}" ]] || ! command -v "${python_bin}" >/dev/null 2>&1; then
  printf '%s\n' 'Python 3.11 or 3.12 is required.' >&2
  exit 1
fi

python_version="$("${python_bin}" -I -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
case "${python_version}" in
  3.11) lock_file="${repository_root}/requirements/deepagents-py311-universal.lock" ;;
  3.12) lock_file="${repository_root}/requirements/deepagents-py312-universal.lock" ;;
  *)
    printf 'Python 3.11 or 3.12 is required; found %s via %s.\n' \
      "${python_version}" "${python_bin}" >&2
    exit 1
    ;;
esac

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

"${python_bin}" -I "${repository_root}/scripts/dependency_qualification.py"

# Rebuild instead of reusing an environment that may contain stale profile
# entry points or interpreter startup hooks from an earlier experiment. The
# exact repository-local target was checked above before the destructive clear.
"${python_bin}" -I -m venv --clear "${runtime_dir}"
installer_home="${runtime_dir}/.installer-home"
mkdir -p "${installer_home}/cache" "${installer_home}/config"
chmod 700 "${installer_home}" "${installer_home}/cache" "${installer_home}/config"

env \
  -u PIP_EXTRA_INDEX_URL \
  -u PIP_FIND_LINKS \
  -u PIP_INDEX_URL \
  -u PIP_NO_INDEX \
  -u PIP_TRUSTED_HOST \
  "HOME=${installer_home}" \
  "NETRC=/dev/null" \
  "XDG_CACHE_HOME=${installer_home}/cache" \
  "XDG_CONFIG_HOME=${installer_home}/config" \
  PIP_CONFIG_FILE=/dev/null \
  "${runtime_dir}/bin/python" -I -m pip --isolated install \
    --disable-pip-version-check \
    --index-url https://pypi.org/simple \
    --no-cache-dir \
    --only-binary=:all: \
    --require-hashes \
    --requirement "${lock_file}"

"${runtime_dir}/bin/python" -I -m pip --isolated check

LOCK_FILE="${lock_file}" "${runtime_dir}/bin/python" -I - <<'PY'
import os
import re
from importlib.metadata import version
from importlib.metadata import distributions
from sysconfig import get_paths

from packaging.markers import default_environment
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

lock_path = os.environ["LOCK_FILE"]
expected = {}
with open(lock_path, encoding="utf-8") as handle:
    for line in handle:
        if not line or line[0].isspace() or line.startswith("#"):
            continue
        requirement = Requirement(re.sub(r"\s*\\\s*$", "", line.strip()))
        if requirement.marker is None or requirement.marker.evaluate(default_environment()):
            expected[canonicalize_name(requirement.name)] = str(requirement.specifier).removeprefix("==")

site_packages = sorted({get_paths()["purelib"], get_paths()["platlib"]})
actual = {
    canonicalize_name(distribution.metadata["Name"]): distribution.version
    for distribution in distributions(path=site_packages)
    if canonicalize_name(distribution.metadata["Name"]) not in {"pip", "setuptools"}
}
if actual != expected:
    missing = sorted(set(expected) - set(actual))
    unexpected = sorted(set(actual) - set(expected))
    mismatched = sorted(
        name for name in set(actual) & set(expected) if actual[name] != expected[name]
    )
    raise SystemExit(
        "Hash-locked runtime mismatch: "
        f"missing={missing}, unexpected={unexpected}, mismatched={mismatched}"
    )

expected_direct = {
    "deepagents": "0.7.8",
    "langchain-anthropic": "1.6.1",
    "langchain-google-genai": "4.3.5",
    "langchain-ollama": "1.1.0",
    "langchain-openai": "1.6.0",
}
actual_direct = {package: version(package) for package in expected_direct}
if actual_direct != expected_direct:
    raise SystemExit(
        f"Deep Agents runtime mismatch: expected {expected_direct}, found {actual_direct}"
    )
from importlib.metadata import entry_points

plugins = [
    f"{group}:{entry.name}"
    for group in ("deepagents.provider_profiles", "deepagents.harness_profiles")
    for entry in entry_points(group=group)
]
if plugins:
    raise SystemExit(f"Forbidden Deep Agents profile entry points: {plugins}")
print(
    "Validated Deep Agents runtime: "
    + ", ".join(f"{key}=={value}" for key, value in actual_direct.items())
)
print(f"Validated {len(actual)} exact transitive distributions from {lock_path}")
PY

rm -rf -- "${installer_home}"

printf 'Deep Agents runtime is installed in %s\n' "${runtime_dir}"
