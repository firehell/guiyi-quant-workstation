# TASK-2026-07-12-021: Workstation V1.5 Pause / Resume / Cancel / Status

## 0. 元信息

| 字段 | 值 |
|------|-----|
| Task ID | TASK-2026-07-12-021-workstation-v1.5-pause-cancel |
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

在 V1.5 调度器上实现 `pause|resume|cancel|status` 控制阶段，写入 `pause_record.json` / `cancel_record.json`，并与 writer lock、静态 Gate 联动；补齐集成测试与状态机文档。

## 6. 不做事项

- 不恢复 V1.4 `.run/dispatch/` 全局锁模型。
- 不 push、merge、deploy。
- 不触碰 `.env`、凭据、数据目录或交易逻辑。

## 7. 涉及模块

**允许修改**：

- `scripts/ai/dispatch_task.sh`
- `scripts/ai/lib/dispatch_control.py`
- `scripts/ai/lib/route_task.py`
- `docs/workflows/status_machine.md`
- `docs/workflows/ai_delivery_workflow.md`
- `docs/workflows/dispatcher_fault_handling.md`
- `tests/workstation/`

**禁止修改**：

- `.env`
- `data/raw/`
- 未列出的业务模块

## 18. 测试清单

### 18.0 自动化测试命令

```bash
bash -n scripts/ai/*.sh
python -m pytest -q tests/workstation/integration/test_pause_resume_cancel.py
make workstation-test
git diff --check
```

## 19. 验收标准

- `dispatch_task.sh <TASK> pause|resume|cancel|status` 可用；pause 释放本 TASK writer lock；resume 恢复 `previous_status`。
- `CANCELLED` 阻断 `dev|fix|test|result`；`PAUSED` 阻断 `dev|fix`；重复 pause/cancel 返回 exit 5。
- 集成测试覆盖 V1.4 T20–T22、T07、幂等表。

## 20. 风险点

- pause 与跨 TASK writer lock 冲突需只释放本 TASK 持有锁。
- resume 需校验审批仍有效（APPROVED_DEV/CODING 等路径）。

## 21. 交付记录

- 测试：`make workstation-test` 50 passed；`test_pause_resume_cancel.py` 5 passed
- smoke：`route --dry-run` / `plan --dry-run` / `status` exit 0
- 实现：`dispatch_control.py`、`dispatch_task.sh` Gate、`release_task_writer_lock_if_held` 按 task_id 释放
