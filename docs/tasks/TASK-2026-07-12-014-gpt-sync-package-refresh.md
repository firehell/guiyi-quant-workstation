# TASK-2026-07-12-014：GPT 同步包刷新

| 字段 | 内容 |
|---|---|
| Task ID | TASK-2026-07-12-014-gpt-sync-package-refresh |
| 日期 | 2026-07-12 |
| 分支 | `main` |
| Base | DATA-PART-TARGET-CLOSURE |
| 状态 | `DELIVERY_READY_DOC_SYNC` |
| 类型 | docs-only |

## 目标

刷新数据收口后的 GPT / Cursor / Codex 共享事实源，明确当前已进入数据部分之后的 Gate 阶段。

## 当前事实

- 数据部分状态：`DATA-PART-TARGET-CLOSURE DELIVERY_READY`。
- Target coverage final：

```text
covered_passed=17203
covered_warning=105
metadata_gap=0
not_applicable=273
issue_register_rows=105
quality_warning=105
```

- 105 条 `quality_warning` 不升级为 `passed`。
- Stage 9、企业微信、live runtime、scheduler、自动交易均未授权。
- 下一阶段以基础监督服务 Gate、JM 单次真实 live Gate Plan、样本外验证设计、macOS 长期运行方案为主。

## 修改范围

允许更新：

- `tasks/current.md`
- `docs/gpt/NEXT_STEPS.md`
- `docs/CODEX_HANDOFF.md`
- 本任务文档及后续任务文档

禁止修改：

- 代码
- DB / Parquet / manifest / quality report
- 策略版本和回测结果
- live / 企业微信真实开关

## Cursor 执行 Prompt

BEGIN CURSOR PROMPT

你现在在 `/Volumes/扩展盘/guiyi-quant-workstation` 仓库中工作。

任务：刷新浏览器 GPT 同步包，只更新文档，不改业务代码。

先阅读：

- `AGENTS.md`
- `tasks/current.md`
- `docs/tasks/DATA-PART-TARGET-CLOSURE-ACCEPTANCE.md`
- `docs/DATA_CENTER.md`
- `docs/gpt/CURRENT_STATE.md`
- `docs/gpt/NEXT_STEPS.md`
- `docs/CODEX_HANDOFF.md`
- `data/reports/target_coverage_audit_after_reference_metadata_apply_full_20260712/coverage_summary.md`
- `data/reports/stage8_6_pending_reconcile_20260712/STAGE8_6_PENDING_RECONCILE.md`

目标：

1. 确保 GPT 同步包明确写入：数据部分已 `DATA-PART-TARGET-CLOSURE DELIVERY_READY`。
2. 保留 105 条 `quality_warning` 不升级 passed 的边界。
3. 保留 Stage 9 / 企业微信 / live / 自动交易未授权。
4. 列出下一阶段 P0/P1。
5. 删除或修正任何 “metadata gap 仍未收口” 的过期说法。

允许修改：

- `docs/gpt/CURRENT_STATE.md`
- `docs/gpt/NEXT_STEPS.md`
- `docs/CODEX_HANDOFF.md`
- 必要时 `tasks/current.md`

禁止修改：

- 代码
- 数据文件
- Parquet
- manifest
- DB
- quality report
- 策略版本
- 回测结果

完成后运行过期 blocker 检查。为避免文档中的检查命令自匹配，建议用变量拼接：

```bash
STALE_PATTERN="metadata_gap=54""6|missing_continuous_contract_map=54""6|PARTIAL_""DELIVERY|CONTINUOUS_""BLOCKED"
rg -n "$STALE_PATTERN" tasks/current.md docs/DATA_CENTER.md docs/gpt/CURRENT_STATE.md docs/tasks
```

并运行：

```bash
git diff --check
```

完成后输出：

1. 修改文件；
2. 修改摘要；
3. 检查命令和结果；
4. 是否建议开新 Codex 会话；
5. 是否建议下一步使用 Plan 模式；
6. 建议给浏览器 GPT 的文件清单。

END CURSOR PROMPT

## 验收

- GPT 同步文件不再把 reference metadata gap 写成未收口 blocker。
- 下一阶段 P0/P1 指向 runtime/live/oos/macOS，而不是继续扩大数据修复。
- `git diff --check` 通过。
