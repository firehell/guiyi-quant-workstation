#!/usr/bin/env bash
set -euo pipefail

labels=(com.guiyi.quant-api com.guiyi.quant-worker-backtests com.guiyi.quant-worker-signals com.guiyi.quant-web)
failed=0
for label in "${labels[@]}"; do
  if launchctl print "gui/$UID/$label" >/dev/null 2>&1; then
    printf '%-42s loaded\n' "$label"
  else
    printf '%-42s missing\n' "$label"
    failed=$((failed + 1))
  fi
done
exit "$failed"
