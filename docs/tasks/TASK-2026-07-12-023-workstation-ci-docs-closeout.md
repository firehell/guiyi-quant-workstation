# TASK-2026-07-12-023: CI, V1.5 Acceptance, Docs Closeout

## 0. 元信息

| 字段 | 值 |
|------|-----|
| Task ID | TASK-2026-07-12-023-workstation-ci-docs-closeout |
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

新增 GitHub Actions `workstation-test` workflow、V1.5 验收文档；同步 `tasks/current.md`、`CODEX_HANDOFF`、`gpt/*`、`ARCHITECTURE`、`AGENTS.md`；完成 021–023 交付关闭。

## 6. 不做事项

- 不自动 merge `main`（人工 Gate）。
- 不触发真实 Codex plan smoke（可选、非阻塞）。

## 7. 涉及模块

**允许修改**：

- `.github/workflows/workstation-test.yml`
- `docs/tasks/examples/V1.5-ACCEPTANCE.md`
- `tasks/current.md`
- `docs/CODEX_HANDOFF.md`
- `docs/gpt/CURRENT_STATE.md`
- `docs/gpt/NEXT_STEPS.md`
- `docs/workstation/ARCHITECTURE.md`
- `docs/workflows/dispatcher_fault_handling.md`
- `AGENTS.md`
- `docs/tasks/TASK-2026-07-12-021*.md`
- `docs/tasks/TASK-2026-07-12-022*.md`
- `docs/tasks/TASK-2026-07-12-023*.md`

**禁止修改**：

- `.env`
- 交易/回测业务代码

## 18. 测试清单

### 18.0 自动化测试命令

```bash
make workstation-test
bash scripts/ai/dispatch_task.sh TASK-2026-07-12-021-workstation-v1.5-pause-cancel route --dry-run
bash scripts/ai/dispatch_task.sh TASK-2026-07-12-021-workstation-v1.5-pause-cancel plan --dry-run
bash scripts/ai/dispatch_task.sh TASK-2026-07-12-021-workstation-v1.5-pause-cancel status
```

## 19. 验收标准

- CI workflow 存在且本地 `make workstation-test` 通过。
- V1.5-ACCEPTANCE 映射全部 AC 到测试或人工签字项。
- 文档与实现一致；021–023 均为 `DELIVERY_READY`。

## 20. 风险点

- 合并 main 前需全量 diff 审查，仅限 workstation 控制平面。

## 21. 交付记录

- CI：`.github/workflows/workstation-test.yml`
- 验收：`docs/tasks/examples/V1.5-ACCEPTANCE.md`
- 文档：`tasks/current.md`、`CODEX_HANDOFF`、`ARCHITECTURE`、`AGENTS.md`、fault_handling 已同步
- 合并 `main`：**待用户人工 Gate**（feature 分支 `make workstation-test` 已通过）
