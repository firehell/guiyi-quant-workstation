# TASK-2026-07-12-022: Issue Dry-Run, F02 Doctor, Production Approve

## 0. 元信息

| 字段 | 值 |
|------|-----|
| Task ID | TASK-2026-07-12-022-workstation-issue-fault-approve |
| Work Level | L1 |
| GitHub Issue | 待创建（L1 可选） |
| Branch | feature/unified-task-dispatcher |
| Worktree | /Volumes/扩展盘/guiyi-parallel/workstation-router |
| Status | DELIVERY_READY |
| Required Env | - |
| Required Mounts | - |
| Base Branch | feature/unified-task-dispatcher |
| Created At | 2026-07-12 |
| Owner | local-user |

## 5. 目标

为 Issue 外部操作脚本增加默认 dry-run Gate；在 `workstation_doctor.sh` 实现 F02 状态/产物一致性检测；`approve_task.sh` 支持 `--confirm-production-write`；测试 helper 去重。

## 6. 不做事项

- 默认不调用真实 `gh issue` 写操作。
- 不 push、merge、deploy。

## 7. 涉及模块

**允许修改**：

- `scripts/ai/update_issue_status.sh`
- `scripts/ai/comment_issue_result.sh`
- `scripts/ai/approve_task.sh`
- `scripts/ai/_approve_lib.sh`
- `scripts/ai/workstation_doctor.sh`
- `docs/workstation/REMOTE_DEVELOPMENT.md`
- `docs/workflows/dispatcher_fault_handling.md`
- `tests/workstation/`

**禁止修改**：

- `.env`
- 未列出的业务模块

## 18. 测试清单

### 18.0 自动化测试命令

```bash
bash -n scripts/ai/*.sh
python -m pytest -q tests/workstation/test_issue_dry_run.py
make workstation-test
```

## 19. 验收标准

- 无 `--confirm-issue-ops` 时 Issue 脚本打印将执行的操作并 exit 6。
- `--dry-run` 仅预览、不写 Issue。
- doctor 报告 F02 不一致项；`approve_task.sh --confirm-production-write` 写入 `production_write_approved: true`。
- `test_task_router.py` 复用 `testkit.py` helper。

## 20. 风险点

- Issue 脚本误调用 gh 会造成远程状态污染；必须默认 fail-closed。

## 21. 交付记录

- `update_issue_status.sh` / `comment_issue_result.sh`：`--dry-run` + `--confirm-issue-ops`（默认 exit 6）
- `approve_task.sh --confirm-production-write` → `production_write_approved: true`
- doctor `f02_status_artifact`；`test_issue_dry_run.py` 5 passed
