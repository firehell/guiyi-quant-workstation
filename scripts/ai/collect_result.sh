#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
OUT_ROOT="$REPO_ROOT/.ai/results"

source "$SCRIPT_DIR/_approve_lib.sh"
source "$SCRIPT_DIR/_work_level_lib.sh"

TASK_ID=""
FORMAT="json"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --task) TASK_ID="${2:-}"; shift 2 ;;
    --format) FORMAT="${2:-}"; shift 2 ;;
    -h|--help)
      echo "Usage: scripts/ai/collect_result.sh --task <TASK_ID> [--format json|md]"
      exit 0
      ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

[[ -n "$TASK_ID" ]] || { echo "--task is required" >&2; exit 2; }
[[ "$FORMAT" =~ ^(json|md)$ ]] || exit 2

cd "$REPO_ROOT"

TASK_FILE="$(resolve_task_file "$TASK_ID" || true)"
[[ -n "$TASK_FILE" ]] || { echo "TASK not found: $TASK_ID" >&2; exit 4; }

WORK_LEVEL="$(extract_work_level "$TASK_FILE")"
WORKTREE_PATH="$(extract_worktree_path "$TASK_FILE" 2>/dev/null || true)"
OUT_DIR="$OUT_ROOT/$TASK_ID"
mkdir -p "$OUT_DIR"

APPROVAL_FILE=".ai/approvals/${TASK_ID}.json"
PLAN_FILE="$OUT_DIR/plan_result.md"
STATUS_FILE="$(mktemp)"
STAT_FILE="$(mktemp)"
trap 'rm -f "$STATUS_FILE" "$STAT_FILE"' EXIT

git status --short --branch > "$STATUS_FILE"
git diff --stat HEAD > "$STAT_FILE"

approval_valid=false
if verify_approval "$APPROVAL_FILE" "$TASK_ID" "$TASK_FILE" "$PLAN_FILE" >/dev/null 2>&1; then
  approval_valid=true
fi

plan_changed=true
if detect_plan_change "$APPROVAL_FILE" "$PLAN_FILE" >/dev/null 2>&1; then
  plan_changed=false
fi

export PYTHONPATH="$SCRIPT_DIR/lib${PYTHONPATH:+:$PYTHONPATH}"

APPROVAL_VALID="$approval_valid" \
PLAN_CHANGED="$plan_changed" \
TASK_ID_ENV="$TASK_ID" \
TASK_FILE_ENV="$TASK_FILE" \
OUT_DIR_ENV="$OUT_DIR" \
APPROVAL_FILE_ENV="$APPROVAL_FILE" \
PLAN_FILE_ENV="$PLAN_FILE" \
STATUS_FILE_ENV="$STATUS_FILE" \
STAT_FILE_ENV="$STAT_FILE" \
WORK_LEVEL_ENV="$WORK_LEVEL" \
WORKTREE_PATH_ENV="$WORKTREE_PATH" \
python3 - <<'PY'
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from task_meta import parse_task_file


def read(path: str | Path) -> str:
    try:
        return Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def run(args: list[str]) -> str:
    return subprocess.run(args, text=True, capture_output=True, check=True).stdout.strip()


def redact(value):
    pattern = re.compile(
        r"(?i)(token|webhook|password|secret|api[_-]?key|access[_-]?key|QYWX_WEBHOOK|DATABASE_URL)"
        r"(\s*[:=]\s*)([^\s,;}]+)"
    )
    if isinstance(value, str):
        return pattern.sub(lambda m: f"{m.group(1)}{m.group(2)}[REDACTED]", value)
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, dict):
        return {key: redact(item) for key, item in value.items()}
    return value


def task_field(text: str, field: str) -> str:
    match = re.search(rf"^\|\s*{re.escape(field)}\s*\|\s*(.*?)\s*\|$", text, re.M)
    return match.group(1).strip() if match else ""


def clean_path_item(item: str) -> str:
    return item.split("（", 1)[0].strip()


def match_path(path: str, item: str) -> bool:
    item = clean_path_item(item)
    return path == item or (item.endswith("/") and path.startswith(item))


def file_hash(path: str) -> str:
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except (FileNotFoundError, IsADirectoryError, PermissionError):
        return ""


def parse_changed_files() -> list[str]:
    status = subprocess.run(["git", "status", "--porcelain"], text=True, capture_output=True, check=True).stdout
    files: set[str] = set()
    for line in status.splitlines():
        if len(line) < 4:
            continue
        raw = line[3:]
        if " -> " in raw:
            raw = raw.split(" -> ", 1)[1]
        files.add(raw)
    return sorted(files)


def parse_tests(out: Path) -> tuple[list[str], list[dict[str, object]], list[str], list[str]]:
    commands = [line.split("\t", 1)[-1] for line in read(out / "commands_executed.tsv").splitlines() if line]
    results: list[dict[str, object]] = []
    failed: list[str] = []
    for line in read(out / "test_results.tsv").splitlines():
        cols = line.split("\t", 3)
        if len(cols) != 4:
            continue
        item = {"index": int(cols[0]), "exit_code": int(cols[1]), "status": cols[2], "command": cols[3]}
        results.append(item)
        if item["exit_code"]:
            failed.append(item["command"])
    skipped = [line for line in read(out / "skipped_tests.txt").splitlines() if line]
    return commands, results, failed, skipped


def review_status(out: Path) -> str:
    review = read(out / "review.md")
    if not review:
        return "missing"
    if re.search(r"(?i)(critical|high priority|high-priority|高优先级|严重|阻断|P0|P1)", review):
        return "high_priority_findings"
    return "completed"


def is_external_review_required(text: str, review_state: str) -> bool:
    explicit = task_field(text, "External Review Required").lower()
    critical = task_field(text, "Critical").lower()
    if explicit in {"true", "yes", "required", "是", "需要"}:
        return True
    if critical in {"true", "yes", "是", "critical"}:
        return True
    if re.search(r"(?i)\bcritical\b|外部审查|required external review|external_review_required", text):
        return True
    return review_state == "high_priority_findings"


task_id = os.environ["TASK_ID_ENV"]
task_file = Path(os.environ["TASK_FILE_ENV"])
out = Path(os.environ["OUT_DIR_ENV"])
approval_path = Path(os.environ["APPROVAL_FILE_ENV"])
plan_file = Path(os.environ["PLAN_FILE_ENV"])
meta = parse_task_file(task_file)
text = read(task_file)

try:
    approval = json.loads(read(approval_path))
except Exception:
    approval = {}

changed_files = parse_changed_files()
pre_existing = approval.get("pre_existing_changes", []) or []
pre_hashes = approval.get("pre_existing_sha256", {}) or {}
unchanged_pre = {path for path in pre_existing if not pre_hashes or pre_hashes.get(path, "") == file_hash(path)}
task_changes = sorted(set(changed_files) - unchanged_pre)

allowed = list(meta.allowed_paths)
forbidden = list(meta.forbidden_paths)
unexpected = [path for path in task_changes if not any(match_path(path, item) for item in allowed)]
forbidden_hits = [path for path in task_changes if any(match_path(path, item) for item in forbidden)]

sensitive_re = re.compile(
    r"(?i)(QYWX_WEBHOOK|token|webhook|password|secret|api[_-]?key|access[_-]?key|DATABASE_URL)"
    r"\s*[:=]\s*['\"]?(?!\$|\[REDACTED\])[^\s'\"]{8,}"
)
sensitive_hits: list[str] = []
for path in task_changes:
    try:
        if sensitive_re.search(read(path)):
            sensitive_hits.append(path)
    except (UnicodeDecodeError, OSError):
        pass

commands, test_results, failed_commands, skipped_tests = parse_tests(out)
review_state = review_status(out)

level = (task_field(text, "Work Level") or os.environ.get("WORK_LEVEL_ENV", "L2")).upper().replace(" ", "")
issue_value = task_field(text, "GitHub Issue")
if re.match(r"^#[0-9]+$", issue_value):
    issue_gate = "passed"
elif level == "L1":
    issue_gate = "skipped_l1"
else:
    issue_gate = "failed"

head_now = run(["git", "rev-parse", "HEAD"])
plan_sha = run(["shasum", "-a", "256", str(plan_file)]).split()[0] if plan_file.is_file() else ""
generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
route_file = out / "route.json"
try:
    route = json.loads(read(route_file))
except Exception:
    route = {}

scope_check = "passed" if not unexpected else "failed"
forbidden_path_check = "passed" if not forbidden_hits else "failed: " + ", ".join(forbidden_hits)
sensitive_data_check = "passed" if not sensitive_hits else "failed: " + ", ".join(sensitive_hits)
test_status = "passed" if test_results and not failed_commands else "failed" if failed_commands else "not_recorded"

warnings: list[str] = []
if unexpected:
    warnings.append("changed files outside allowed_paths")
if forbidden_hits:
    warnings.append("forbidden_paths modified")
if sensitive_hits:
    warnings.append("sensitive data pattern detected")
if failed_commands:
    warnings.append("tests failed")
if test_status == "not_recorded":
    warnings.append("tests not recorded")
if review_state == "high_priority_findings":
    warnings.append("review contains high priority findings")
if os.environ["APPROVAL_VALID"] != "true":
    warnings.append("approval missing or invalid")
if os.environ["PLAN_CHANGED"] == "true":
    warnings.append("approved plan changed")
if issue_gate == "failed":
    warnings.append("issue gate failed")

external_review_required = is_external_review_required(text, review_state)
if external_review_required:
    warnings.append("external review required")

all_gates_passed = (
    scope_check == "passed"
    and forbidden_path_check == "passed"
    and sensitive_data_check == "passed"
    and not failed_commands
    and test_status == "passed"
    and os.environ["APPROVAL_VALID"] == "true"
    and os.environ["PLAN_CHANGED"] != "true"
    and issue_gate != "failed"
    and review_state != "high_priority_findings"
)

execution_status = "ready_for_manual_review" if all_gates_passed else "blocked"
next_action = (
    "manual review; do not merge until all gates pass"
    if execution_status == "blocked"
    else "manual review; user may decide whether to mark DELIVERY_READY"
)
if external_review_required:
    next_action = "external review required; do not close based only on Codex review"

(out / "changed_files.txt").write_text("\n".join(changed_files) + ("\n" if changed_files else ""), encoding="utf-8")
(out / "diff_stat.txt").write_text(read(os.environ["STAT_FILE_ENV"]), encoding="utf-8")

execution = {
    "schema_version": 1,
    "task_id": task_id,
    "stage": "result",
    "status": execution_status,
    "resolved_profile": route.get("resolved_profile", "no-model"),
    "reasoning_effort": route.get("reasoning_effort", ""),
    "sandbox_mode": route.get("sandbox", "none"),
    "started_at": route.get("dispatcher", {}).get("started_at", ""),
    "finished_at": generated_at,
    "duration": "",
    "exit_code": route.get("dispatcher", {}).get("exit_code", 0),
    "branch": run(["git", "branch", "--show-current"]),
    "base_branch": task_field(text, "Base Branch") or task_field(text, "Base") or "",
    "commit_before": approval.get("head_commit", head_now),
    "commit_after": head_now,
    "changed_files": changed_files,
    "tests": {
        "status": test_status,
        "commands": commands,
        "results": test_results,
        "failed_commands": failed_commands,
        "skipped_tests": skipped_tests,
    },
    "review_status": review_state,
    "warnings": sorted(set(warnings)),
    "external_review_required": external_review_required,
    "approval_reference": str(approval_path) if approval_path.is_file() else "",
}

payload = {
    "task_id": task_id,
    "task_file": str(task_file),
    "work_level": level,
    "worktree_path": os.environ.get("WORKTREE_PATH_ENV") or task_field(text, "Worktree"),
    "github_issue": issue_value if re.match(r"^#[0-9]+$", issue_value) else "",
    "task_status": task_field(text, "Status"),
    "branch": execution["branch"],
    "expected_branch": task_field(text, "Branch"),
    "head_commit_before": execution["commit_before"],
    "head_commit_after": execution["commit_after"],
    "generated_at": generated_at,
    "git_status": read(os.environ["STATUS_FILE_ENV"]),
    "pre_existing_changes": pre_existing,
    "task_changes": task_changes,
    "unexpected_changes": unexpected,
    "changed_files": changed_files,
    "git_diff_stat": read(os.environ["STAT_FILE_ENV"]),
    "allowed_paths": allowed,
    "forbidden_paths": forbidden,
    "commands_executed": commands,
    "test_results": test_results,
    "failed_commands": failed_commands,
    "skipped_tests": skipped_tests,
    "scope_check": scope_check,
    "forbidden_path_check": forbidden_path_check,
    "sensitive_data_check": sensitive_data_check,
    "approval_valid": os.environ["APPROVAL_VALID"] == "true",
    "approved_plan_sha256": approval.get("plan_sha256", ""),
    "current_plan_sha256": plan_sha,
    "plan_changed": os.environ["PLAN_CHANGED"] == "true",
    "issue_gate": issue_gate,
    "review_status": review_state,
    "external_review_required": external_review_required,
    "execution_status": execution_status,
    "warnings": execution["warnings"],
    "risks": sorted(set(unexpected + forbidden_hits + sensitive_hits + failed_commands)),
    "incomplete_items": failed_commands,
    "manual_review_required": True,
    "next_action": next_action,
}

payload = redact(payload)
execution = redact(execution)

(out / "result_bundle.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
(out / "execution.json").write_text(json.dumps(execution, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

summary = [
    f"# Execution Summary - {task_id}",
    "",
    "- Stage: result",
    f"- Status: {execution['status']}",
    f"- Branch: {execution['branch']}",
    f"- Tests: {test_status}",
    f"- Review: {review_state}",
    f"- Scope: {scope_check}",
    f"- Forbidden paths: {forbidden_path_check}",
    f"- Sensitive data: {sensitive_data_check}",
    f"- External review required: {str(external_review_required).lower()}",
    "",
    "## Changed Files",
]
summary.extend([f"- `{path}`" for path in changed_files] or ["- None"])
summary.extend(["", "## Warnings"])
summary.extend([f"- {warning}" for warning in execution["warnings"]] or ["- None"])
summary.extend(["", "## Next Action", f"- {next_action}"])
(out / "execution_summary.md").write_text("\n".join(summary) + "\n", encoding="utf-8")
PY

if [[ "$FORMAT" == md ]]; then
  python3 - "$OUT_DIR/result_bundle.json" > "$OUT_DIR/result_bundle.md" <<'PY'
import json
import sys

d = json.load(open(sys.argv[1], encoding="utf-8"))
print(f"# Result Bundle — {d['task_id']}\n")
for key, value in d.items():
    print(f"## {key}\n\n```json\n{json.dumps(value, ensure_ascii=False, indent=2)}\n```\n")
PY
fi

echo "[OK] Result Bundle: $OUT_DIR/result_bundle.$FORMAT"
echo "[OK] Execution JSON: $OUT_DIR/execution.json"
