---
kind: Task
schema_version: "2.0"
task_id: TASK-2026-07-16-001-control-plane-fix
title: 工作站控制平面修复 — DEMO-WB-V3-001 阻断问题修复
status: REQUIREMENT_READY
risk_level: R3
work_level: L2
approval_scope:
  - plan
  - code
allowed_paths:
  - scripts/ai/dispatch_task.sh
  - scripts/ai/run_tests.sh
  - scripts/ai/_approve_lib.sh
  - scripts/ai/lib/task_meta.py
forbidden_paths:
  - apps/**
  - services/**
  - packages/**
  - strategies/**
  - experiments/**
  - data/**
  - database/**
  - migrations/**
  - .github/**
  - .env*
resource_locks: []
required_tests:
  - git diff --check
  - bash -n scripts/ai/dispatch_task.sh
  - bash -n scripts/ai/run_tests.sh
  - python3 -m pytest -q tests/workstation/test_github_task_resolver.py tests/workstation/test_task_router.py
  - python3 -m pytest -q tests/workstation/test_workbuddy_unified_v3.py
base_branch: main
owner: WorkBuddy
created_at: "2026-07-16"
updated_at: "2026-07-16"
---

# TASK-2026-07-16-001：工作站控制平面修复

## 0. 元信息

| 字段 | 值 |
|---|---|
| Task ID | `TASK-2026-07-16-001-control-plane-fix` |
| Status | `REQUIREMENT_READY` |
| Risk Level | `R3` |
| Work Level | `L2` |
| GitHub Issue | `待创建` |
| Branch | `TBD by bootstrap` |
| Draft PR | `TBD` |
| Depends On | 无 |

## 1. 背景

DEMO-WB-V3-001（Issue #27）PLAN 阶段发现 5 个阻断问题，导致全链路无法通过。其中 2 个是控制平面代码缺陷，需独立修复后合入 `main`，再重跑 Demo。

## 2. 当前阶段

修复 `scripts/ai/` 下的两个代码缺陷：

1. **状态机盲推进**（P0 阻断）
2. **测试命令提取路径单一**（P1 阻断）

本任务不涉及业务代码、数据、DB、API、前端。

## 3. 修复项 1：状态机盲推进

### 问题

`scripts/ai/dispatch_task.sh` 的 `advance_status_after_success()` 在 plan 成功后仅根据 exit_code 推进到 `PLAN_READY`，不检查 `plan_result.md` 中 Codex 的实际结论。

当 Codex 输出 `REPLAN_REQUIRED` 时，状态仍被推进到 `PLAN_READY`，导致后续 `APPROVE → DEV` 可以绕过阻断。

### 修复

在 `advance_status_after_success` 的 plan case 中，增加对 `plan_result.md` 结论的解析：

```bash
plan)
    local plan_result="$out_dir/plan_result.md"
    if [[ -f "$plan_result" ]]; then
        if grep -q "REPLAN_REQUIRED" "$plan_result" 2>/dev/null; then
            echo "[GATE] Plan result says REPLAN_REQUIRED — NOT advancing to PLAN_READY" >&2
            return 0
        fi
    fi
    transition_task_status_cli "$task_file" "PLAN_READY" ...
```

**不变**：exit_code≠0 时不进 `advance_status_after_success`。REPLAN_REQUIRED 的文件格式不做约定，只做简单 grep。

## 4. 修复项 2：测试命令提取路径单一

### 问题

`scripts/ai/run_tests.sh` 的 awk 只识别 `### 18.0 自动化测试命令` 节，不检查 V2 YAML frontmatter 中的 `required_tests`。

V2 任务（如 DEMO-WB-V3-001）在 frontmatter 中已声明 `required_tests`，但 `run_tests.sh` 找不到 `### 18.0` 节时只执行 fallback（`git diff --check` + `bash -n`），不运行真正的 required tests。

### 修复

在 `run_tests.sh` 中，当 markdown 解析找不到命令时，增加从 route.json 读取 `required_tests` 的 fallback：

```bash
# After markdown awk section, if $CMDS is empty:
if ! grep -q '[^[:space:]#]' "$CMDS"; then
    # Fallback 1: try reading required_tests from route.json
    local route_file="$OUT_DIR/route.json"
    if [[ -f "$route_file" ]]; then
        python3 -c "
import json, sys
with open('$route_file') as f:
    data = json.load(f)
tests = data.get('required_tests', [])
for t in tests:
    print(t)
" > "$CMDS" 2>/dev/null
    fi
fi

# Fallback 2: if still empty, use safe default
if ! grep -q '[^[:space:]#]' "$CMDS"; then
    printf '%s\n' 'git diff --check' 'bash -n scripts/ai/*.sh' > "$CMDS"
    echo "TASK §18.0 and required_tests missing; used fallback: git diff --check + bash -n scripts/ai/*.sh" > "$SKIPPED_FILE"
fi
```

**不变**：已有的安全白名单 `is_safe_command()` 对所有命令（包括从 route.json 读取的）仍然生效。

## 5. 允许修改

```text
scripts/ai/dispatch_task.sh
scripts/ai/run_tests.sh
```

## 6. 禁止修改

```text
apps/**
services/**
packages/**
strategies/**
experiments/**
data/**
database/**
migrations/**
.github/**
.env*
```

## 7. 不做事项

- 不修改业务代码。
- 不修改 DB、Parquet、manifest、checksum 或 quality status。
- 不调用 RQData 下载。
- 不自动 push / merge / deploy / close Issue。
- 不改变 workbuddy_task.sh facade 或路由逻辑。
- 不修改 approve_task.sh 的审批逻辑。
- 不开启自动交易、live scheduler 或企业微信通知。

## 8. 验收标准

1. `dispatch_task.sh` plan 成功后，若 `plan_result.md` 含 `REPLAN_REQUIRED`，不推进到 `PLAN_READY`
2. `run_tests.sh` 能从 `route.json` 的 `required_tests` 字段读取测试命令
3. 从 route.json 读取的命令仍受 `is_safe_command()` 白名单保护
4. 全量 `tests/workstation` 测试通过
5. `git diff --check` 通过
6. `bash -n` 对修改的脚本通过

## 9. 测试清单

### 9.0 自动化测试命令

```bash
git diff --check
bash -n scripts/ai/dispatch_task.sh
bash -n scripts/ai/run_tests.sh
python3 -m pytest -q tests/workstation/test_github_task_resolver.py tests/workstation/test_task_router.py
python3 -m pytest -q tests/workstation/test_workbuddy_unified_v3.py
```
