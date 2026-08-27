#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repository_root="$(cd "${script_dir}/.." && pwd)"
dockerfile="${repository_root}/docker/deepagents-typescript-smoke/Dockerfile"
base_image="$(sed -En 's/^FROM[[:space:]]+([^[:space:]]+@sha256:[0-9a-f]{64})([[:space:]].*)?$/\1/p' "${dockerfile}")"
if [[ -z "${base_image}" || "${base_image}" == *$'\n'* ]]; then
  printf '%s\n' 'TypeScript smoke Dockerfile must contain exactly one digest-pinned FROM image.' >&2
  exit 1
fi

owner_label="io.github.scoutflo.deepagents-incident-workflow.typescript-sdk-smoke"
run_nonce="$(python3 -I -c 'import secrets; print(secrets.token_hex(8))')"
owner_value="${run_nonce}"
image_tag="daiw-typescript-sdk-smoke:${run_nonce}"
container_name="daiw-typescript-sdk-smoke-${run_nonce}"
temporary_dir="$(mktemp -d "${TMPDIR:-/tmp}/daiw-typescript-sdk-image.XXXXXX")"
iid_file="${temporary_dir}/image-id"
output_dir="${temporary_dir}/output"
smoke_record="${output_dir}/deepagents-typescript-sdk-smoke.json"
image_created=false
container_id=""

mkdir -p "${output_dir}"
chmod 0777 "${output_dir}"

cleanup() {
  original_status=$?
  cleanup_failed=0
  trap - EXIT
  set +e
  cleanup_container_id="${container_id}"
  if [[ -z "${cleanup_container_id}" ]]; then
    cleanup_container_id="$(
      docker container ls --all --quiet --filter "name=^/${container_name}$" 2>/dev/null
    )" || cleanup_failed=1
  fi
  if [[ -n "${cleanup_container_id}" ]]; then
    actual_owner="$(
      docker container inspect \
        --format "{{ index .Config.Labels \"${owner_label}\" }}" \
        "${cleanup_container_id}" 2>/dev/null
    )" || cleanup_failed=1
    if [[ "${actual_owner}" != "${owner_value}" ]]; then
      printf 'Refusing to remove container with mismatched ownership: %s\n' \
        "${cleanup_container_id}" >&2
      cleanup_failed=1
    else
      docker rm -f "${cleanup_container_id}" >/dev/null || cleanup_failed=1
    fi
  fi
  if [[ "${image_created}" == "true" ]]; then
    image_id="$(<"${iid_file}")"
    actual_owner="$(
      docker image inspect \
        --format "{{ index .Config.Labels \"${owner_label}\" }}" \
        "${image_id}" 2>/dev/null
    )" || cleanup_failed=1
    if [[ "${actual_owner}" != "${owner_value}" ]]; then
      printf 'Refusing to remove image with mismatched ownership: %s\n' "${image_id}" >&2
      cleanup_failed=1
    else
      docker image rm -f "${image_id}" >/dev/null || cleanup_failed=1
    fi
  fi
  case "$(basename "${temporary_dir}")" in
    daiw-typescript-sdk-image.*) rm -rf -- "${temporary_dir}" || cleanup_failed=1 ;;
    *)
      printf 'Refusing to remove unexpected temporary path: %s\n' "${temporary_dir}" >&2
      cleanup_failed=1
      ;;
  esac
  if [[ "${original_status}" -ne 0 ]]; then
    exit "${original_status}"
  fi
  exit "${cleanup_failed}"
}
trap cleanup EXIT

python3 -I "${repository_root}/scripts/typescript_dependency_qualification.py"
docker image inspect "${base_image}" >/dev/null
docker build \
  --label "${owner_label}=${owner_value}" \
  --iidfile "${iid_file}" \
  --tag "${image_tag}" \
  --file "${dockerfile}" \
  "${repository_root}"
image_created=true

container_id="$(docker run --detach \
  --name "${container_name}" \
  --label "${owner_label}=${owner_value}" \
  --network none \
  --read-only \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  --pids-limit 128 \
  --memory 768m \
  --cpus 1 \
  --user 65532:65532 \
  --mount "type=bind,src=${output_dir},dst=/controller-output" \
  --tmpfs /tmp:rw,noexec,nosuid,size=128m,uid=65532,gid=65532,mode=1770 \
  --tmpfs /home/worker:rw,noexec,nosuid,size=16m,uid=65532,gid=65532,mode=0700 \
  "${image_tag}" \
  /workspace/typescript-runtime/dist/deepagents_sdk_smoke.js \
  --assert-os-network-disabled \
  --output /controller-output/deepagents-typescript-sdk-smoke.json)"

completed=false
for _ in $(seq 1 120); do
  container_status="$(docker container inspect --format '{{.State.Status}}' "${container_id}")"
  case "${container_status}" in
    exited) completed=true; break ;;
    dead)
      printf '%s\n' 'TypeScript SDK smoke container entered the abnormal dead state.' >&2
      exit 1
      ;;
  esac
  sleep 1
done
if [[ "${completed}" != "true" ]]; then
  printf '%s\n' 'TypeScript SDK smoke exceeded the 120-second controller deadline.' >&2
  exit 1
fi

docker logs "${container_id}"
container_exit_code="$(docker container inspect --format '{{.State.ExitCode}}' "${container_id}")"
if [[ "${container_exit_code}" != "0" ]]; then
  printf 'TypeScript SDK smoke container exited with status %s.\n' \
    "${container_exit_code}" >&2
  exit 1
fi
python3 -I "${repository_root}/scripts/validate_typescript_sdk_smoke_record.py" \
  "${smoke_record}"
