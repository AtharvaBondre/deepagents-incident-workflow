#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repository_root="$(cd "${script_dir}/.." && pwd)"
uv_bin="${UV_BIN:-uv}"
policy_path="${repository_root}/security/dependency-policy.json"

policy_values="$(python3 -I - "${policy_path}" <<'PY'
import json
import sys
from datetime import datetime

with open(sys.argv[1], encoding="utf-8") as handle:
    policy = json.load(handle)
resolver = policy.get("resolver", {})
expected_fields = {
    "hashes_required": bool,
    "index": str,
    "name": str,
    "resolution_cutoff": str,
    "universal": bool,
    "version": str,
}
if (
    type(policy.get("schema_version")) is not int
    or policy.get("schema_version") != 1
    or set(policy) != {"schema_version", "resolver"}
    or set(resolver) != set(expected_fields)
    or any(type(resolver[key]) is not value_type for key, value_type in expected_fields.items())
    or resolver["name"] != "uv"
    or not resolver["version"]
    or resolver["index"] != "https://pypi.org/simple"
    or not resolver["resolution_cutoff"].endswith("Z")
    or resolver["hashes_required"] is not True
    or resolver["universal"] is not True
):
    raise SystemExit("invalid dependency resolver policy")
try:
    cutoff = datetime.fromisoformat(resolver["resolution_cutoff"].replace("Z", "+00:00"))
except ValueError as exc:
    raise SystemExit("invalid dependency resolution cutoff") from exc
if cutoff.utcoffset() is None or cutoff.utcoffset().total_seconds() != 0:
    raise SystemExit("dependency resolution cutoff must be UTC")
print(resolver["version"], resolver["resolution_cutoff"], resolver["index"], sep="\t")
PY
)"
IFS=$'\t' read -r expected_uv_version resolution_cutoff package_index <<< "${policy_values}"

actual_uv_version="$("${uv_bin}" --version 2>/dev/null || true)"
case "${actual_uv_version}" in
  "uv ${expected_uv_version}"|"uv ${expected_uv_version} "*) ;;
  *)
    printf 'uv %s is required; found %s\n' "${expected_uv_version}" "${actual_uv_version:-unavailable}" >&2
    exit 1
    ;;
esac

temporary_dir="$(mktemp -d "${TMPDIR:-/tmp}/daiw-dependency-locks.XXXXXX")"
cleanup() {
  case "$(basename "${temporary_dir}")" in
    daiw-dependency-locks.*) rm -rf -- "${temporary_dir}" ;;
    *) printf 'Refusing to remove unexpected temporary path: %s\n' "${temporary_dir}" >&2 ;;
  esac
}
trap cleanup EXIT

mkdir -p "${repository_root}/requirements"
mkdir -p "${temporary_dir}/home" "${temporary_dir}/uv-cache"
chmod 700 "${temporary_dir}/home" "${temporary_dir}/uv-cache"
for python_version in 3.11 3.12; do
  suffix="${python_version/./}"
  output="${temporary_dir}/deepagents-py${suffix}-universal.lock"
  env -i \
    "HOME=${temporary_dir}/home" \
    "LANG=${LANG:-C.UTF-8}" \
    "PATH=${PATH}" \
    "TMPDIR=${TMPDIR:-/tmp}" \
    "UV_CACHE_DIR=${temporary_dir}/uv-cache" \
    "${uv_bin}" --no-config pip compile "${repository_root}/pyproject.toml" \
      --extra deepagents \
      --universal \
      --python-version "${python_version}" \
      --generate-hashes \
      --no-build \
      --no-sources \
      --default-index "${package_index}" \
      --index-strategy first-index \
      --resolution highest \
      --prerelease if-necessary-or-explicit \
      --fork-strategy requires-python \
      --exclude-newer "${resolution_cutoff}" \
      --quiet \
      --custom-compile-command './scripts/refresh-dependency-locks.sh' \
      --output-file "${output}"
done

for python_version in 3.11 3.12; do
  suffix="${python_version/./}"
  mv \
    "${temporary_dir}/deepagents-py${suffix}-universal.lock" \
    "${repository_root}/requirements/deepagents-py${suffix}-universal.lock"
done

printf '%s\n' 'Refreshed universal hash-locked Deep Agents runtime dependencies.'
printf '%s\n' 'Review the lock diff, then refresh dependency qualification explicitly.'
