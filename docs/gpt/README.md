# GPT handoff package

生成时间：2026-07-06

本目录用于把阶段 1-D 后需要提交给浏览器 GPT 的项目事实集中放在一起。这里的文件是从原项目路径真正移动过来的交接包，不是副本。

## 推荐阅读顺序

1. `CURRENT_STATE.md`
2. `PROJECT_SNAPSHOT.md`
3. `RQDATA_POC_REPORT.md`
4. `rqdata_poc_result.md`
5. `NEXT_STEPS.md`
6. `ROADMAP.md`
7. `tasks_current.md`

## 当前结论

- 阶段 1 RQData 权限与接口能力 PoC 已完成，判定为 `PARTIAL`。
- 核心历史数据权限可支撑阶段 2：JM 合约、1d / 1m 小样本、5m / 15m / 30m / 60m 直取、主力映射、合约乘数、保证金和手续费字段可用。
- 阶段 2 可以进入 Plan：JM 历史数据更新到最新交易日。

## 仍需注意

- JM 正式研究数据仍停在 `2025-12-31`，尚未更新。
- `trading_sessions`、`continuous_contracts`、`ex_factor` 在 1-C 中返回 0 行，后续需要单独确认。
- `realtime_snapshot_or_bar` 未验证，不能写成实时 1m 入库完成。
- 阶段 2 不应直接运行写入脚本，必须先明确输出路径、manifest、checksum、quality_status、质量检查和回滚策略。

## 路径变更提醒

以下文件已从原路径移动到本目录：

- `CURRENT_STATE.md`
- `PROJECT_SNAPSHOT.md`
- `docs/RQDATA_POC_REPORT.md`
- `docs/NEXT_STEPS.md`
- `docs/ROADMAP.md`
- `tasks/current.md`

其中 `tasks/current.md` 已移动为 `docs/gpt/tasks_current.md`。后续 Codex 新会话如果按项目规则读取 `tasks/current.md`，会发现原路径缺失；应先参考本交接包恢复或新建下一阶段任务文件。
