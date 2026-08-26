---
name: quant-backend
description: Use when 任务涉及归一量化 FastAPI、Pydantic、PostgreSQL 应用域、Redis、Alert、Runtime、后端接口或 guiyi CLI。
---

# 归一量化后端

## Current surface

- 主 API：Market、Alert、Runtime health。
- CLI：`guiyi data`、`guiyi research`、`guiyi runtime` 的 active 子命令。
- Alert：Rule/Scope/Event、HTDY/SuBing evaluator、one-shot PushPlus transport。

已退役的 Signal/Review/Strategy、RQAlpha、Execution Review、旧 backtest worker/queue、data_center
HTTP 与 RQ notification worker 不得恢复。

## 实现边界

- 路由只做输入校验与依赖注入，业务放在对应 domain/service；Historical 读统一经过
  `MarketDataService`。
- Catalog、coverage、mapping、Session 与物理完整性异常 fail-closed。
- Alert 保持两表、Event-first、one-shot；无 retry/replay/backfill/queue/outbox 或订单。
- Redis Live 是当日 observation，不提升为 Canonical；`auto_order=false`。
- 错误和日志不得暴露密钥、内部路径、SQL、stack 或 provider token。

数据/Catalog/市场 migration 任务使用 `futures-data`；前端或浏览器故障使用 `quant-frontend`。

## 验证

先运行覆盖改动的定向 pytest，再按风险扩展 Ruff、Mypy 和完整非 isolated PostgreSQL 测试。
真实 DB/Redis、Runtime switch、Scope、通知或 release 都不是普通测试；执行前需
当次范围明确的单次执行意图。命令以 `TESTING.md` 为准。
