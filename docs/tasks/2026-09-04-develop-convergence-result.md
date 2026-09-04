# `develop` 收敛实施结果

日期：2026-09-04
状态：`IN_PROGRESS`
实施 baseline：`18a62382685b6deb92010968d4a5a920952fa206`
任务分支：`chore/develop-convergence`
设计：`docs/tasks/2026-09-04-develop-convergence-design.md`
计划：`docs/tasks/2026-09-04-develop-convergence-implementation-plan.md`

## Owner 分发决定

`NEWOW_SCREENSHOT_POLICY=RETAIN`
`DISTRIBUTION_STATUS=DISTRIBUTION_APPROVED_BY_OWNER`

该状态只覆盖 `docs/research/newow-v3.2.82/screenshots/**`，不覆盖原始页面响应、逐 Bar 股票数据或 RQData/Canonical 原文。

## Baseline inventory

- Git status：clean
- Baseline SHA：`18a62382685b6deb92010968d4a5a920952fa206`
- Branch topology：见本任务 PR 的 Task A evidence
- Open PR / Issue：见本任务 PR 的 Task A evidence
- Worktree：见本任务 PR 的 Task A evidence

## 初始 blocker

- 尚待 Task B–G 验证。

## 变更记录

- 删除 tracked `.playwright-cli/**`；Git 历史未重写。
- `.gitignore` 已加入 `.playwright-cli/`。
- Newow screenshot 保留，状态为 `DISTRIBUTION_APPROVED_BY_OWNER`。
- 未恢复或分发原始页面响应、逐 Bar 输入或 RQData/Canonical 原文。
- 删除三个 `docs/superpowers/*` 非 canonical 文件；replacement 与无 active inbound reference 已核验。
- Issue `#286`、`#259` 已关闭为 `NOT_PLANNED`，仅表示 superseded，不冒充旧计划完成。
- Issue `#307` 已更新为 `subing_ths_15m_v3` 当前合同并保持 open。
- PR `#333` metadata 已对齐 current head `2eb33e6d9f8195847b908e399539c5e12f5ff7b6`，旧 SHA Review 标记为 `RELEASE_REVIEW_STALE`。
- `STATUS.md` 仅同步 PR current-head/stale Review 事实；`TESTING.md` 仅增加 repository-hygiene 命令与非授权边界。

## 验证

- Task C guard RED：删除前定向 guard 以 `1 failed` 指出三个 tracked `docs/superpowers/**` 文件。
- Task C guard GREEN：删除后 `tests/engineering/test_repository_hygiene.py` 为 `3 passed`。
- Task C authority scan：未发现同一主题两份并列 active authority；旧 Newow V1 文档保留独立版本身份，UI 冲突优先级由 current Market Detail design 明确。
- 全量完成矩阵仍待后续 Task。

## Branch 清理

- 尚未执行。

## Review 与集成

- 尚未执行。
