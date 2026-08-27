#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repository_root="$(cd "${script_dir}/.." && pwd)"
runtime_dir="${repository_root}/.deepagents-typescript-runtime"
runtime_prefix="${repository_root}/.deepagents-typescript-runtime.build."
node_bin="${NODE_BIN:-node}"
npm_bin="${NPM_BIN:-npm}"

if ! command -v "${node_bin}" >/dev/null 2>&1; then
  printf '%s\n' 'Node 22.23.2 is required.' >&2
  exit 1
fi
if ! command -v "${npm_bin}" >/dev/null 2>&1; then
  printf '%s\n' 'npm 10.9.8 is required.' >&2
  exit 1
fi
node_bin="$(command -v "${node_bin}")"
npm_bin="$(command -v "${npm_bin}")"
node_version="$("${node_bin}" --version | sed 's/^v//')"
npm_version="$("${npm_bin}" --version)"
if [[ "${node_version}" != "22.23.2" ]]; then
  printf 'Node 22.23.2 is required; found %s.\n' "${node_version}" >&2
  exit 1
fi
if [[ "${npm_version}" != "10.9.8" ]]; then
  printf 'npm 10.9.8 is required; found %s.\n' "${npm_version}" >&2
  exit 1
fi

if [[ -L "${runtime_dir}" ]]; then
  printf '%s\n' 'Refusing to replace a symlinked TypeScript runtime.' >&2
  exit 1
fi
if [[ -e "${runtime_dir}" && ! -d "${runtime_dir}" ]]; then
  printf '%s\n' 'Refusing to replace a non-directory TypeScript runtime.' >&2
  exit 1
fi

python3 -I "${repository_root}/scripts/typescript_dependency_qualification.py"

build_dir="$(mktemp -d "${runtime_prefix}XXXXXX")"
cleanup() {
  status=$?
  trap - EXIT
  case "${build_dir}" in
    "${runtime_prefix}"*) rm -rf -- "${build_dir}" ;;
    *) printf 'Refusing to remove unexpected build path: %s\n' "${build_dir}" >&2 ;;
  esac
  exit "${status}"
}
trap cleanup EXIT

cp "${repository_root}/typescript-runtime/package.json" "${build_dir}/package.json"
cp "${repository_root}/typescript-runtime/package-lock.json" "${build_dir}/package-lock.json"
cp "${repository_root}/typescript-runtime/tsconfig.json" "${build_dir}/tsconfig.json"
mkdir -p "${build_dir}/src" "${build_dir}/.installer-home"
cp "${repository_root}/typescript-runtime/src/"*.ts "${build_dir}/src/"
chmod 700 "${build_dir}/.installer-home"

node_dir="$(dirname "${node_bin}")"
env -i \
  "PATH=${node_dir}:/usr/local/bin:/usr/bin:/bin" \
  "HOME=${build_dir}/.installer-home" \
  "npm_config_userconfig=/dev/null" \
  "npm_config_cache=${build_dir}/.installer-home/cache" \
  "npm_config_registry=https://registry.npmjs.org/" \
  "npm_config_engine_strict=true" \
  "npm_config_ignore_scripts=true" \
  "npm_config_audit=false" \
  "npm_config_fund=false" \
  "npm_config_update_notifier=false" \
  "${npm_bin}" ci --ignore-scripts --engine-strict --no-audit --no-fund \
  --prefix "${build_dir}"

env -i \
  "PATH=${node_dir}:/usr/local/bin:/usr/bin:/bin" \
  "HOME=${build_dir}/.installer-home" \
  "${npm_bin}" run typecheck --prefix "${build_dir}"
env -i \
  "PATH=${node_dir}:/usr/local/bin:/usr/bin:/bin" \
  "HOME=${build_dir}/.installer-home" \
  "${npm_bin}" run build --prefix "${build_dir}"
env -i \
  "PATH=${node_dir}:/usr/local/bin:/usr/bin:/bin" \
  "HOME=${build_dir}/.installer-home" \
  "npm_config_userconfig=/dev/null" \
  "npm_config_cache=${build_dir}/.installer-home/cache" \
  "npm_config_registry=https://registry.npmjs.org/" \
  "npm_config_ignore_scripts=true" \
  "npm_config_audit=false" \
  "npm_config_fund=false" \
  "npm_config_update_notifier=false" \
  "${npm_bin}" prune --omit=dev --ignore-scripts --no-audit --no-fund \
  --prefix "${build_dir}"
env -i \
  "PATH=${node_dir}:/usr/local/bin:/usr/bin:/bin" \
  "HOME=${build_dir}/.installer-home" \
  "npm_config_userconfig=/dev/null" \
  "npm_config_update_notifier=false" \
  "${npm_bin}" ls --omit=dev --all --json --prefix "${build_dir}" >/dev/null

source_sha256="$(shasum -a 256 "${repository_root}/typescript-runtime/src/deepagents_worker.ts" | awk '{print $1}')"
lock_sha256="$(shasum -a 256 "${repository_root}/typescript-runtime/package-lock.json" | awk '{print $1}')"
worker_sha256="$(shasum -a 256 "${build_dir}/dist/deepagents_worker.js" | awk '{print $1}')"
expected_worker_sha256="$(
  python3 -I -c \
    'import json,sys; print(json.load(open(sys.argv[1]))["deepagents"]["runtimes"]["typescript"]["worker_build_sha256"])' \
    "${repository_root}/config/workflow.json"
)"
if [[ "${worker_sha256}" != "${expected_worker_sha256}" ]]; then
  printf 'TypeScript worker build digest mismatch: expected %s, found %s.\n' \
    "${expected_worker_sha256}" "${worker_sha256}" >&2
  exit 1
fi

SOURCE_SHA256="${source_sha256}" \
LOCK_SHA256="${lock_sha256}" \
WORKER_SHA256="${worker_sha256}" \
RUNTIME_DIR="${build_dir}" \
python3 -I - <<'PY'
import json
import os
from pathlib import Path

manifest = {
    "schema_version": 1,
    "sdk_language": "typescript",
    "node_version": "22.23.2",
    "runtime_version": "1.13.1",
    "worker_source_sha256": os.environ["SOURCE_SHA256"],
    "package_lock_sha256": os.environ["LOCK_SHA256"],
    "worker_sha256": os.environ["WORKER_SHA256"],
}
Path(os.environ["RUNTIME_DIR"], "runtime-manifest.json").write_text(
    json.dumps(manifest, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
PY

rm -rf -- "${build_dir}/.installer-home"
if [[ -d "${runtime_dir}" ]]; then
  rm -rf -- "${runtime_dir}"
fi
mv "${build_dir}" "${runtime_dir}"
build_dir="${runtime_prefix}consumed"
trap - EXIT

"${node_bin}" "${runtime_dir}/dist/deepagents_worker.js" --runtime-info
printf 'Deep Agents TypeScript runtime is installed in %s\n' "${runtime_dir}"
