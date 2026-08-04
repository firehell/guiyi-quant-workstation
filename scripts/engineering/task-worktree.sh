#!/usr/bin/env bash
# Controlled Lane 1/2 task entrypoint. GitHub side effects require --apply.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  task-worktree.sh create --kind <kind> --task-id <ID> --slug <slug> --lane <1|2> --issue <N> [--apply] [--json]
  task-worktree.sh integrate --lane <1|2> --issue <N> --test-profile <profile> --commit-message <text> [--apply] [--json]
  task-worktree.sh cleanup --task-path <path> --lane <1|2> --issue <N> [--apply] [--json]
EOF
}

fail() { echo "[REJECTED] $1" >&2; exit 2; }

repo_root="$(git rev-parse --show-toplevel 2>/dev/null)" || fail "must run inside a Git repository"
cd "$repo_root"
[[ $# -gt 0 ]] || { usage >&2; exit 2; }
action="$1"
shift

lane=""; issue=""; kind=""; task_id=""; slug=""; test_profile=""; message=""; task_path=""
apply=false; json=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --lane) lane="${2:-}"; shift 2 ;;
    --issue) issue="${2:-}"; shift 2 ;;
    --kind) kind="${2:-}"; shift 2 ;;
    --task-id) task_id="${2:-}"; shift 2 ;;
    --slug) slug="${2:-}"; shift 2 ;;
    --test-profile) test_profile="${2:-}"; shift 2 ;;
    --commit-message) message="${2:-}"; shift 2 ;;
    --task-path) task_path="${2:-}"; shift 2 ;;
    --apply) apply=true; shift ;;
    --json) json=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) fail "unsupported argument: $1" ;;
  esac
done

[[ "$lane" =~ ^[12]$ ]] || fail "--lane must be 1 or 2"
[[ "$issue" =~ ^[1-9][0-9]*$ ]] || fail "--issue must be a positive GitHub Issue number"
mode="dry-run"
[[ "$apply" == true ]] && mode="apply"

case "$action" in
  create)
    [[ -n "$kind" && -n "$task_id" && -n "$slug" ]] || fail "create requires --kind, --task-id, and --slug"
    args=(python3 scripts/engineering/worktree_flow.py task-create --kind "$kind" --task-id "$task_id" --slug "$slug" --integration-branch develop --json)
    [[ "$apply" == true ]] && args+=(--apply)
    "${args[@]}"
    ;;
  cleanup)
    [[ -n "$task_path" ]] || fail "cleanup requires --task-path"
    args=(python3 scripts/engineering/worktree_flow.py task-cleanup --task-path "$task_path" --integration-branch develop --json)
    [[ "$apply" == true ]] && args+=(--apply)
    "${args[@]}"
    ;;
  integrate)
    [[ -n "$test_profile" && -n "$message" ]] || fail "integrate requires --test-profile and --commit-message"
    [[ "$test_profile" =~ ^(engineering|docs|backend-health|all-safe)$ ]] || fail "unsupported --test-profile"
    [[ "$message" != *$'\n'* && ${#message} -le 160 ]] || fail "commit message must be one line with at most 160 characters"
    branch="$(git branch --show-current)"
    [[ -n "$branch" ]] || fail "integrate requires a named task branch"
    [[ "$branch" != "main" && "$branch" != "master" && "$branch" != "develop" ]] || fail "integrate cannot run from a protected branch"
    [[ "$branch" =~ ^(feature|fix|docs|research|refactor)/ ]] || fail "integrate requires a managed task branch prefix"
    base_ref="origin/develop"
    git rev-parse --verify --quiet "${base_ref}^{commit}" >/dev/null 2>&1 || base_ref="develop"
    changed_paths=()
    while IFS= read -r changed_path; do
      [[ -n "$changed_path" ]] && changed_paths+=("$changed_path")
    done < <({ git diff --name-only "${base_ref}...HEAD"; git diff --cached --name-only; git diff --name-only; git ls-files --others --exclude-standard; } | sed '/^$/d' | sort -u)
    [[ ${#changed_paths[@]} -gt 0 ]] || fail "integrate requires at least one changed path"
    classification=""
    if ! classification="$(python3 scripts/engineering/task_workflow.py --lane "$lane" "${changed_paths[@]}")"; then
      echo "$classification" >&2
      exit 2
    fi
    planned_json="$(python3 -c 'import json,sys; branch,lane,issue,message=sys.argv[1:]; print(json.dumps([["bash","scripts/engineering/test.sh","<test-profile>"],["bash","scripts/engineering/check-secrets.sh"],["git","diff","--check"],["git","add","--all"],["git","commit","-m",message],["git","push","-u","origin",branch],["gh","pr","create","--base","develop","--head",branch]]))' "$branch" "$lane" "$issue" "$message")"
    if [[ "$apply" == true ]]; then
      bash scripts/engineering/test.sh "$test_profile"
      bash scripts/engineering/check-secrets.sh
      git diff --check
      git add --all
      git commit -m "$message"
      git push -u origin "$branch"
      gh pr create --draft --base develop --head "$branch" --title "[Lane ${lane}] #${issue}: ${message}" --body "Lane ${lane} task for Issue #${issue}. Automated checks passed locally. Draft PR does not authorize merge. After task acceptance, independent exact-head Review, required CI, PR head and reviewed head match, mergeability is explicit, and no manual Gate remains, Codex/GitHub Connector may perform an expected-head merge commit into develop. main/release/tag/Runtime and real side effects remain behind manual Gates."
    fi
    if [[ "$json" == true ]]; then
      python3 -c 'import json,sys; print(json.dumps({"schema_version":1,"tool":"scripts/engineering/task-worktree.sh","action":"integrate","mode":sys.argv[1],"status":"ok","bound_facts":{"branch":sys.argv[2],"lane":int(sys.argv[3]),"issue":int(sys.argv[4]),"base_ref":sys.argv[5]},"planned_commands":json.loads(sys.argv[6])},ensure_ascii=False))' "$mode" "$branch" "$lane" "$issue" "$base_ref" "$planned_json"
    else
      echo "[OK] action=integrate mode=${mode} branch=${branch} lane=${lane} issue=${issue}"
    fi
    ;;
  *) fail "action must be create, integrate, or cleanup" ;;
esac
