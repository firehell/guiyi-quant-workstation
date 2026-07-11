#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"; OUT_ROOT="$REPO_ROOT/.ai/results"
source "$SCRIPT_DIR/_approve_lib.sh"
source "$SCRIPT_DIR/_work_level_lib.sh"
TASK_ID=""; FORMAT="json"
while [[ $# -gt 0 ]]; do case "$1" in --task) TASK_ID="${2:-}"; shift 2;; --format) FORMAT="${2:-}"; shift 2;; -h|--help) echo "Usage: scripts/ai/collect_result.sh --task <TASK_ID> [--format json|md]"; exit 0;; *) echo "Unknown argument: $1" >&2; exit 2;; esac; done
[[ -n "$TASK_ID" ]] || { echo "--task is required" >&2; exit 2; }; [[ "$FORMAT" =~ ^(json|md)$ ]] || exit 2; cd "$REPO_ROOT"
TASK_FILE="$(resolve_task_file "$TASK_ID" || true)"
[[ -n "$TASK_FILE" ]] || { echo "TASK not found: $TASK_ID" >&2; exit 4; }
WORK_LEVEL="$(extract_work_level "$TASK_FILE")"
WORKTREE_PATH="$(extract_worktree_path "$TASK_FILE" 2>/dev/null || true)"
OUT_DIR="$OUT_ROOT/$TASK_ID"; mkdir -p "$OUT_DIR"
APPROVAL_FILE=".ai/approvals/${TASK_ID}.json"; PLAN_FILE="$OUT_DIR/plan_result.md"
STATUS_FILE="$(mktemp)"; STAT_FILE="$(mktemp)"; trap 'rm -f "$STATUS_FILE" "$STAT_FILE"' EXIT
git status --short --branch > "$STATUS_FILE"; git diff --stat HEAD > "$STAT_FILE"
approval_valid=false; if verify_approval "$APPROVAL_FILE" "$TASK_ID" "$TASK_FILE" "$PLAN_FILE" >/dev/null 2>&1; then approval_valid=true; fi
plan_changed=true; if detect_plan_change "$APPROVAL_FILE" "$PLAN_FILE" >/dev/null 2>&1; then plan_changed=false; fi
APPROVAL_VALID="$approval_valid" PLAN_CHANGED="$plan_changed" TASK_ID_ENV="$TASK_ID" TASK_FILE_ENV="$TASK_FILE" OUT_DIR_ENV="$OUT_DIR" APPROVAL_FILE_ENV="$APPROVAL_FILE" PLAN_FILE_ENV="$PLAN_FILE" STATUS_FILE_ENV="$STATUS_FILE" STAT_FILE_ENV="$STAT_FILE" WORK_LEVEL_ENV="$WORK_LEVEL" WORKTREE_PATH_ENV="$WORKTREE_PATH" python3 - <<'PY'
import hashlib, json, os, re, subprocess
def read(path):
    try:
        with open(path,encoding="utf-8") as f: return f.read()
    except FileNotFoundError: return ""
def redact(value):
    pattern=re.compile(r"(?i)(token|webhook|password|secret|api[_-]?key|access[_-]?key|QYWX_WEBHOOK)(\s*[:=]\s*)([^\s,;}]+)")
    if isinstance(value,str): return pattern.sub(lambda m:m.group(1)+m.group(2)+"[REDACTED]",value)
    if isinstance(value,list): return [redact(x) for x in value]
    if isinstance(value,dict): return {k:redact(v) for k,v in value.items()}
    return value
task=os.environ["TASK_FILE_ENV"]; text=read(task); out=os.environ["OUT_DIR_ENV"]; approval_path=os.environ["APPROVAL_FILE_ENV"]
try: approval=json.loads(read(approval_path))
except Exception: approval={}
status=subprocess.run(["git","status","--porcelain"],text=True,capture_output=True,check=True).stdout.splitlines()
changed=sorted({line[3:] for line in status if len(line)>3})
pre=approval.get("pre_existing_changes",[]) or []; pre_hashes=approval.get("pre_existing_sha256",{}) or {}
def file_hash(path):
    try:
        with open(path,"rb") as f: return hashlib.sha256(f.read()).hexdigest()
    except (FileNotFoundError, IsADirectoryError, PermissionError): return ""
unchanged_pre={p for p in pre if not pre_hashes or pre_hashes.get(p,"")==file_hash(p)}
task_changes=sorted(set(changed)-unchanged_pre)
section=text.split("## 7.",1)[1].split("## 8.",1)[0] if "## 7." in text else ""
parts=section.split("**禁止修改**",1); allowed=re.findall(r"`([^`]+)`",parts[0]); forbidden=re.findall(r"`([^`]+)`",parts[1] if len(parts)>1 else "")
def match(path, item): return path==item or (item.endswith("/") and path.startswith(item)) or ("（" in item and path==item.split("（",1)[0])
unexpected=[p for p in task_changes if not any(match(p,a) for a in allowed)]
forbidden_hits=[p for p in task_changes if any(match(p,f) for f in forbidden)]
sensitive_re=re.compile(r"(?i)(QYWX_WEBHOOK|token|webhook|password|secret|api[_-]?key|access[_-]?key)\s*[:=]\s*['\"]?(?!\$|\[REDACTED\])[^\s'\"]{8,}")
sensitive_hits=[]
for path in task_changes:
    try:
        if sensitive_re.search(read(path)): sensitive_hits.append(path)
    except (UnicodeDecodeError, OSError): pass
commands=[line.split("\t",1)[-1] for line in read(out+"/commands_executed.tsv").splitlines() if line]
results=[]; failed=[]
for line in read(out+"/test_results.tsv").splitlines():
    cols=line.split("\t",3)
    if len(cols)==4:
        item={"index":int(cols[0]),"exit_code":int(cols[1]),"status":cols[2],"command":cols[3]}; results.append(item)
        if item["exit_code"]: failed.append(item["command"])
issue=re.search(r"^\| GitHub Issue \| (.*) \|$",text,re.M); branch=re.search(r"^\| Branch \| (.+) \|$",text,re.M)
work_level=re.search(r"^\| Work Level \| (.*) \|$",text,re.M); worktree=re.search(r"^\| Worktree \| (.*) \|$",text,re.M)
task_status=re.search(r"^\| Status \| (.+) \|$",text,re.M)
level=(work_level.group(1).strip().upper() if work_level else os.environ.get("WORK_LEVEL_ENV","L2"))
issue_val=(issue.group(1).strip() if issue else "")
if re.match(r"^#[0-9]+$", issue_val): issue_gate="passed"
elif level=="L1": issue_gate="skipped_l1"
else: issue_gate="failed"
wt=os.environ.get("WORKTREE_PATH_ENV") or (worktree.group(1).strip() if worktree else "")
head_now=subprocess.run(["git","rev-parse","HEAD"],text=True,capture_output=True,check=True).stdout.strip()
plan_sha=""
if os.path.isfile(os.environ["PLAN_FILE_ENV"]):
    plan_sha=subprocess.run(["shasum","-a","256",os.environ["PLAN_FILE_ENV"]],text=True,capture_output=True,check=True).stdout.split()[0]
payload={"task_id":os.environ["TASK_ID_ENV"],"task_file":task,"work_level":level,"worktree_path":wt,
"github_issue":issue_val if re.match(r"^#[0-9]+$", issue_val) else "",
"task_status":task_status.group(1) if task_status else "","branch":subprocess.run(["git","branch","--show-current"],text=True,capture_output=True).stdout.strip(),
"expected_branch":branch.group(1) if branch else "","head_commit_before":approval.get("head_commit",head_now),"head_commit_after":head_now,
"generated_at":subprocess.run(["date","-u","+%Y-%m-%dT%H:%M:%SZ"],text=True,capture_output=True).stdout.strip(),
"git_status":read(os.environ["STATUS_FILE_ENV"]),"pre_existing_changes":pre,"task_changes":task_changes,"unexpected_changes":unexpected,
"changed_files":changed,"git_diff_stat":read(os.environ["STAT_FILE_ENV"]),"commands_executed":commands,"test_results":results,
"failed_commands":failed,"skipped_tests":read(out+"/skipped_tests.txt").splitlines(),"scope_check":"passed" if not unexpected else "failed",
"forbidden_path_check":"passed" if not forbidden_hits else "failed: "+", ".join(forbidden_hits),
"sensitive_data_check":"passed" if not sensitive_hits else "failed: "+", ".join(sensitive_hits),"approval_valid":os.environ["APPROVAL_VALID"]=="true",
"approved_plan_sha256":approval.get("plan_sha256",""),"current_plan_sha256":plan_sha,"plan_changed":os.environ["PLAN_CHANGED"]=="true",
"issue_gate":issue_gate,"risks":unexpected,"incomplete_items":failed,
"manual_review_required":True,"next_action":"manual review; do not merge until all gates pass"}
payload=redact(payload)
with open(out+"/result_bundle.json","w",encoding="utf-8") as f: json.dump(payload,f,ensure_ascii=False,indent=2); f.write("\n")
PY
if [[ "$FORMAT" == md ]]; then
  python3 - "$OUT_DIR/result_bundle.json" > "$OUT_DIR/result_bundle.md" <<'PY'
import json,sys
d=json.load(open(sys.argv[1],encoding="utf-8")); print(f"# Result Bundle — {d['task_id']}\n")
for k,v in d.items(): print(f"## {k}\n\n```json\n{json.dumps(v,ensure_ascii=False,indent=2)}\n```\n")
PY
fi
echo "[OK] Result Bundle: $OUT_DIR/result_bundle.$FORMAT"
