#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
source "$SCRIPT_DIR/_work_level_lib.sh"

TASK_ID=""
BASE_REF="origin/main"
BRANCH=""
BOOTSTRAP=false
PRINT_PATH=false

usage() {
  cat <<'EOF'
Usage: scripts/ai/init_task_worktree.sh --task <TASK_ID> [options]

Options:
  --base <ref>       Base ref for new branch (default: origin/main)
  --branch <name>    Branch name (default: from TASK meta or feature/<slug>)
  --bootstrap        Create L1 TASK skeleton if missing
  --print-path       Print worktree path and exit (after create/update)
  -h, --help         Show help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --task) TASK_ID="${2:-}"; shift 2 ;;
    --base) BASE_REF="${2:-}"; shift 2 ;;
    --branch) BRANCH="${2:-}"; shift 2 ;;
    --bootstrap) BOOTSTRAP=true; shift ;;
    --print-path) PRINT_PATH=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

[[ -n "$TASK_ID" ]] || { usage >&2; exit 2; }
cd "$REPO_ROOT"

TASK_FILE=""
if ! TASK_FILE="$(resolve_task_file "$TASK_ID")"; then
  if [[ "$BOOTSTRAP" == true ]]; then
    TASK_FILE="docs/tasks/${TASK_ID}.md"
    mkdir -p docs/tasks
    slug="$(task_slug_from_id "$TASK_ID")"
    cat > "$TASK_FILE" <<EOF
# ${TASK_ID}

## 0. 元信息

| 字段 | 值 |
|------|-----|
| Task ID | ${TASK_ID} |
| Work Level | L1 |
| GitHub Issue | 待创建 |
| Branch | feature/${slug} |
| Worktree | 待 init_task_worktree.sh 回填 |
| Status | REQUIREMENT_READY |
| Created At | $(date +%Y-%m-%d) |
| Owner | local-user |

## 5. 目标

（待填写）

## 6. 不做事项

- 不自动 push / merge / deploy
- 不修改 .env 或数据目录

## 7. 涉及模块

**允许修改**：

- \`scripts/ai/\`

**禁止修改**：

- \`.env\`
- \`data/\`

## 18. 测试清单

### 18.0 自动化测试命令

\`\`\`bash
bash -n scripts/ai/*.sh
git diff --check
\`\`\`

## 19. 验收标准

- Gate 脚本通过

## 20. 风险点

- 无
EOF
    echo "[OK] Bootstrapped L1 TASK: $TASK_FILE"
  else
    echo "TASK not found: $TASK_ID (use --bootstrap to create skeleton)" >&2
    exit 4
  fi
fi

slug="$(task_slug_from_id "$TASK_ID")"
WT_ROOT="$(resolve_worktree_root "$REPO_ROOT")"
WT_PATH="${WT_ROOT}/${slug}"
mkdir -p "$WT_ROOT"

if [[ -z "$BRANCH" ]]; then
  BRANCH="$(default_branch_for_task "$TASK_FILE")"
fi

if [[ -d "$WT_PATH/.git" || -f "$WT_PATH/.git" ]]; then
  echo "[OK] Worktree already exists: $WT_PATH"
else
  echo "[INIT] fetch $BASE_REF"
  git fetch origin >/dev/null 2>&1 || git fetch --all >/dev/null 2>&1 || true
  if git show-ref --verify --quiet "refs/heads/${BRANCH}"; then
    git worktree add "$WT_PATH" "$BRANCH"
  elif git show-ref --verify --quiet "refs/remotes/${BASE_REF}"; then
    git worktree add -b "$BRANCH" "$WT_PATH" "$BASE_REF"
  else
    git worktree add -b "$BRANCH" "$WT_PATH" HEAD
  fi
  echo "[OK] Created worktree: $WT_PATH (branch=$BRANCH)"
fi

set_task_meta_field "$TASK_FILE" "Worktree" "$WT_PATH"
set_task_meta_field "$TASK_FILE" "Branch" "$BRANCH"

if [[ "$PRINT_PATH" == true ]]; then
  printf '%s\n' "$WT_PATH"
  exit 0
fi

cat <<EOF

[OK] TASK worktree ready
  Task:     $TASK_ID
  File:     $TASK_FILE
  Worktree: $WT_PATH
  Branch:   $BRANCH

Next:
  cd "$WT_PATH"
  scripts/ai/codex_plan.sh --task "$TASK_ID"
EOF
