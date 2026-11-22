#!/usr/bin/env bash
# Run the existing comparison engine from any working directory.
set -eu
root="$(cd "$(dirname "$0")/../.." && pwd)"
py="$root/services/quant-api/.venv/bin/python"
if [[ ! -x "$py" ]]; then
  echo "缺少 quant-api Python 环境，请在仓库执行 uv sync --frozen --project services/quant-api" >&2
  exit 2
fi
# Resolve explicit file dependencies before the engine imports the research stack.
args=("$@")
for ((i=1; i<${#args[@]}; i++)); do
  case "${args[i]}" in
    --hours)
      if [[ ! -f "${args[i+1]:-}" ]]; then
        echo "缺少已核对的小时输入：${args[i+1]:-}，先使用 legacy-hours 准备。" >&2
        exit 2
      fi ;;
    --source)
      if [[ ! -d "${args[i+1]:-}" ]]; then
        echo "找不到研究来源目录：${args[i+1]:-}" >&2
        exit 2
      fi ;;
  esac
done
export PYTHONPATH="$root:$root/services/quant-api:$root/packages/quant-core"
exec "$py" -B -m scripts.research.subing_exit_comparison "$@"
