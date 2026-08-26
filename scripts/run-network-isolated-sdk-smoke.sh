#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repository_root="$(cd "${script_dir}/.." && pwd)"
dockerfile="${repository_root}/docker/deepagents-smoke/Dockerfile"
base_image="$(sed -En 's/^FROM[[:space:]]+([^[:space:]]+@sha256:[0-9a-f]{64})([[:space:]].*)?$/\1/p' "${dockerfile}")"
if [[ -z "${base_image}" || "${base_image}" == *$'\n'* ]]; then
  printf '%s\n' 'SDK smoke Dockerfile must contain exactly one digest-pinned FROM image.' >&2
  exit 1
fi
owner_label="io.github.atharvabondre.deepagents-incident-workflow.sdk-smoke"
run_nonce="$(python3 -I -c 'import secrets; print(secrets.token_hex(8))')"
owner_value="${run_nonce}"
image_tag="daiw-sdk-smoke:${run_nonce}"
container_name="daiw-sdk-smoke-${run_nonce}"
temporary_dir="$(mktemp -d "${TMPDIR:-/tmp}/daiw-sdk-image.XXXXXX")"
iid_file="${temporary_dir}/image-id"
output_dir="${temporary_dir}/output"
smoke_record="${output_dir}/deepagents-sdk-smoke.json"
image_created=false
container_id=""

mkdir -p "${output_dir}"
# The mktemp parent remains mode 0700. This nested directory is writable by the
# container's unprivileged UID but cannot be traversed by other host users.
chmod 0777 "${output_dir}"

cleanup() {
  original_status=$?
  cleanup_failed=0
  trap - EXIT
  set +e
  cleanup_container_id="${container_id}"
  if [[ -z "${cleanup_container_id}" ]]; then
    if ! cleanup_container_id="$(
      docker container ls \
        --all \
        --quiet \
        --filter "name=^/${container_name}$"
    )"; then
      printf 'Failed to determine whether SDK smoke container exists.\n' >&2
      cleanup_failed=1
    fi
  fi
  if [[ -n "${cleanup_container_id}" ]]; then
    if ! actual_container_owner="$(
      docker container inspect \
        --format "{{ index .Config.Labels \"${owner_label}\" }}" \
        "${cleanup_container_id}" 2>/dev/null
    )"; then
      printf 'Failed to inspect owned SDK smoke container: %s\n' \
        "${cleanup_container_id}" >&2
      cleanup_failed=1
      actual_container_owner=""
    fi
    if [[ "${actual_container_owner}" != "${owner_value}" ]]; then
      printf 'Refusing to remove container with mismatched ownership: %s\n' \
        "${cleanup_container_id}" >&2
      cleanup_failed=1
    elif ! docker rm -f "${cleanup_container_id}" >/dev/null; then
      printf 'Failed to remove owned SDK smoke container: %s\n' \
        "${cleanup_container_id}" >&2
      cleanup_failed=1
    fi
  fi
  if [[ "${image_created}" == "true" ]]; then
    image_id="$(<"${iid_file}")"
    if ! actual_image_owner="$(
      docker image inspect \
        --format "{{ index .Config.Labels \"${owner_label}\" }}" \
        "${image_id}" 2>/dev/null
    )"; then
      printf 'Failed to inspect owned SDK smoke image: %s\n' "${image_id}" >&2
      cleanup_failed=1
      actual_image_owner=""
    fi
    if [[ "${actual_image_owner}" != "${owner_value}" ]]; then
      printf 'Refusing to remove image with mismatched ownership: %s\n' "${image_id}" >&2
      cleanup_failed=1
    elif ! docker image rm -f "${image_id}" >/dev/null; then
      printf 'Failed to remove owned SDK smoke image: %s\n' "${image_id}" >&2
      cleanup_failed=1
    fi
  fi
  case "$(basename "${temporary_dir}")" in
    daiw-sdk-image.*)
      if ! rm -rf -- "${temporary_dir}"; then
        printf 'Failed to remove SDK smoke temporary directory: %s\n' \
          "${temporary_dir}" >&2
        cleanup_failed=1
      fi
      ;;
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

python3 -I "${repository_root}/scripts/dependency_qualification.py"
docker image inspect "${base_image}" >/dev/null
docker build \
  --build-arg "LOCK_FILE=requirements/deepagents-py312-universal.lock" \
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
  /workspace/scripts/deepagents_sdk_smoke.py \
  --assert-os-network-disabled \
  --output /controller-output/deepagents-sdk-smoke.json)"

completed=false
for _ in $(seq 1 120); do
  container_status="$(docker container inspect --format '{{.State.Status}}' "${container_id}")"
  case "${container_status}" in
    exited)
      completed=true
      break
      ;;
    dead)
      printf '%s\n' 'SDK smoke container entered the abnormal dead state.' >&2
      exit 1
      ;;
  esac
  sleep 1
done
if [[ "${completed}" != "true" ]]; then
  printf 'SDK smoke exceeded the 120-second controller deadline.\n' >&2
  exit 1
fi

docker logs "${container_id}"
container_exit_code="$(
  docker container inspect --format '{{.State.ExitCode}}' "${container_id}"
)"
if [[ "${container_exit_code}" != "0" ]]; then
  printf 'SDK smoke container exited with status %s.\n' "${container_exit_code}" >&2
  exit 1
fi

python3 -I "${repository_root}/scripts/validate_sdk_smoke_record.py" "${smoke_record}"
