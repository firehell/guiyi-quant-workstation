#!/usr/bin/env bash
set -euo pipefail

OUTPUT_JSON=0
[[ "${1:-}" == "--json" ]] && OUTPUT_JSON=1

units=(guiyi-quant-api guiyi-quant-worker-signals nginx)

unit_state() {
  systemctl is-active "$1" 2>/dev/null || printf 'unknown'
}

if [[ "$OUTPUT_JSON" -eq 1 ]]; then
  printf '{"readonly":true,"services":{'
  comma=""
  for unit in "${units[@]}"; do
    printf '%s"%s":"%s"' "$comma" "$unit" "$(unit_state "$unit")"
    comma=,
  done
  printf '},"would_restart":false}\n'
  exit 0
fi

printf '[server-status] readonly=true\n'
for unit in "${units[@]}"; do
  printf '  %-34s %s\n' "$unit" "$(unit_state "$unit")"
done
