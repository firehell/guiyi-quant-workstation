#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
TASK_ID=""; BUNDLE=""
while [[ $# -gt 0 ]]; do case "$1" in --task) TASK_ID="${2:-}"; shift 2;; --bundle) BUNDLE="${2:-}"; shift 2;; -h|--help) echo "Usage: scripts/ai/make_delivery_summary.sh --task <TASK_ID> [--bundle <json>]"; exit 0;; *) echo "Unknown argument: $1" >&2; exit 2;; esac; done
[[ -n "$TASK_ID" ]] || { echo "--task is required" >&2; exit 2; }; cd "$REPO_ROOT"
OUT_DIR=".ai/results/$TASK_ID"; [[ -n "$BUNDLE" ]] || BUNDLE="$OUT_DIR/result_bundle.json"; [[ -f "$BUNDLE" ]] || { echo "Bundle not found: $BUNDLE" >&2; exit 4; }
python3 - "$BUNDLE" "$OUT_DIR/delivery_summary.md" <<'PY'
import json,sys
d=json.load(open(sys.argv[1],encoding="utf-8")); passed=not d["failed_commands"] and d["scope_check"]=="passed" and d["forbidden_path_check"]=="passed" and d["approval_valid"] and not d["plan_changed"]
lines=[f"# 交付摘要 — {d['task_id']}","","## 摘要",f"- 当前状态：{d['task_status'] or '未记录'}",f"- Issue Gate：{d['issue_gate']}","","## 完成"]
lines += [f"- `{x}`" for x in d["task_changes"]] or ["- 无已识别的本次变更"]
lines += ["","## 未完成"] + ([f"- {x}" for x in d["incomplete_items"]] or ["- 无"])
lines += ["","## 测试"] + ([f"- {x['status']} (rc={x['exit_code']}): `{x['command']}`" for x in d["test_results"]] or ["- 未记录测试"])
lines += ["","## 风险"] + ([f"- {x}" for x in d["risks"]] or ["- 未发现越界变更；仍需人工 review"])
lines += ["","## 是否合并",f"- {'可进入人工合并审查' if passed else '不建议合并，Gate 尚未全部通过'}","","## 下一步",f"- {d['next_action']}"]
open(sys.argv[2],"w",encoding="utf-8").write("\n".join(lines)+"\n")
PY
echo "[OK] Delivery summary: $OUT_DIR/delivery_summary.md"
