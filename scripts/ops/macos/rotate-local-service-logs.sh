#!/usr/bin/env bash
set -euo pipefail

LOG_DIR="${GUIYI_LOG_DIR:-$HOME/Library/Logs/GuiyiQuant}"
MAX_BYTES="${GUIYI_LOG_MAX_BYTES:-10485760}"
KEEP="${GUIYI_LOG_KEEP:-5}"

[[ "$MAX_BYTES" =~ ^[1-9][0-9]*$ ]] || { printf '[rotate-logs] invalid GUIYI_LOG_MAX_BYTES\n' >&2; exit 2; }
[[ "$KEEP" =~ ^[1-9][0-9]*$ ]] || { printf '[rotate-logs] invalid GUIYI_LOG_KEEP\n' >&2; exit 2; }
[[ -d "$LOG_DIR" ]] || exit 0

for log_file in "$LOG_DIR"/*.log; do
  [[ -f "$log_file" ]] || continue
  size="$(stat -f '%z' "$log_file")"
  (( size >= MAX_BYTES )) || continue
  rm -f "$log_file.$KEEP"
  for ((index=KEEP-1; index>=1; index--)); do
    [[ -f "$log_file.$index" ]] && mv "$log_file.$index" "$log_file.$((index + 1))"
  done
  cp "$log_file" "$log_file.1"
  : >"$log_file"
done
