#!/usr/bin/env bash

set -euo pipefail

SERVICE_NAME="${SERVICE_NAME:-englishbot}"
SOURCE_DIR="${SOURCE_DIR:-/srv/services/${SERVICE_NAME}/backups}"
SYNC_DIR="${SYNC_DIR:-/srv/drive-sync/services/${SERVICE_NAME}/backups}"
KEEP_COUNT="${KEEP_COUNT:-30}"

if ! [[ "${KEEP_COUNT}" =~ ^[0-9]+$ ]] || [ "${KEEP_COUNT}" -lt 1 ]; then
  echo "KEEP_COUNT must be a positive integer, got: ${KEEP_COUNT}" >&2
  exit 1
fi

mkdir -p "${SOURCE_DIR}" "${SYNC_DIR}"

copy_backups() {
  local source_dir="$1"
  local sync_dir="$2"

  find "${source_dir}" -maxdepth 1 -type f -print0 | while IFS= read -r -d '' file_path; do
    cp -p "${file_path}" "${sync_dir}/"
  done
}

prune_backups() {
  local target_dir="$1"
  local keep_count="$2"

  mapfile -d '' files < <(
    find "${target_dir}" -maxdepth 1 -type f -printf '%T@ %p\0' | sort -z -rn
  )

  if [ "${#files[@]}" -le "${keep_count}" ]; then
    return 0
  fi

  local index
  for ((index = keep_count; index < ${#files[@]}; index += 1)); do
    rm -f "${files[$index]#* }"
  done
}

copy_backups "${SOURCE_DIR}" "${SYNC_DIR}"
prune_backups "${SOURCE_DIR}" "${KEEP_COUNT}"
prune_backups "${SYNC_DIR}" "${KEEP_COUNT}"
