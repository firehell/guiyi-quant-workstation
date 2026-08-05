#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
AGENT_DIR="${HOME}/Library/LaunchAgents"
API_PLIST="${AGENT_DIR}/com.guiyi.quant-api.plist"

labels=(com.guiyi.quant-api com.guiyi.quant-worker-backtests com.guiyi.quant-worker-signals com.guiyi.quant-web com.guiyi.quant-log-rotate)
[[ "${GUIYI_LIVE_RUNTIME_ENABLED:-0}" =~ ^(1|true|yes|on)$ ]] && labels+=(com.guiyi.quant-runtime-scheduler)
[[ "${GUIYI_AFTER_MARKET_AUTOMATION_ENABLED:-0}" =~ ^(1|true|yes|on)$ ]] && labels+=(com.guiyi.quant-after-market-scheduler)
[[ "${GUIYI_WECHAT_AUTOSEND_ENABLED:-0}" =~ ^(1|true|yes|on)$ ]] && labels+=(com.guiyi.quant-worker-notifications)

runtime_root_from_plist() {
  if [[ ! -f "$API_PLIST" ]]; then
    printf 'missing_plist'
    return 0
  fi
  plutil -extract EnvironmentVariables.GUIYI_PROJECT_ROOT raw -o - "$API_PLIST" 2>/dev/null || printf 'unknown'
}

runtime_root="$(runtime_root_from_plist)"
printf '[local-services-status] inspector_repo=%s\n' "$PROJECT_ROOT"
printf '[local-services-status] supervised_runtime_root=%s\n' "$runtime_root"
if [[ "$runtime_root" != "$PROJECT_ROOT" ]]; then
  printf '[local-services-status] note=launchd 当前未绑定本仓库；长期运行副本见 docs/tasks/JM-LIVE-GATE-EVIDENCE.md\n'
fi

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
