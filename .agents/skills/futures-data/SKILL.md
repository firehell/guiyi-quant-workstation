---
name: futures-data
description: Use when 任务涉及归一量化 RQData、期货合约行情、Canonical Parquet、八表 Market Catalog、MainContractMap、数据质量、历史维护或 guiyi data CLI。
---

# 期货数据任务

只处理 Market Fact Domain。应用域 PostgreSQL/Alembic、普通 API 或 Web 任务不因使用数据库而自动路由到本 skill。

先用 `STATUS.md` 判断现场状态，以 `docs/DATA_CENTER.md` 和对应 OpenSpec 决定合同：

- Catalog：`openspec/specs/data-foundation-metadata/spec.md`
- Canonical：`openspec/specs/canonical-market-storage/spec.md`
- 维护：`openspec/specs/historical-data-maintenance/spec.md`
- 查询：`openspec/specs/market-series-query/spec.md`

## 先判定任务类型

| 类型 | 允许的默认动作 | 必须保持的边界 |
|---|---|---|
| 源码/隔离测试 | 修改 Market Data 代码、fixture 和专用可销毁隔离库 | 通过不授权真实 RQData、Canonical 或生产 DB |
| 只读诊断 | 读取已授权范围的 Catalog/MDS/报告并给出精确缺口 | 不下载、不修复、不把未知写成零缺口 |
| daily update | 只处理既有基线的最新增量和映射到的新主力 | 真实 provider/发布需要精确单次意图；daily 成功不证明全历史完整 |
| full maintenance | 绑定 symbol、physical contract、周期、窗口、plan hash 和当前 readback | 不扩范围、不跨频替代；部分成功/结果不明时停止，不盲目重试 |
| weekly audit | operational 全历史只读审计 | 不下载、不自动修复、不通知；`skipped_busy` 不算 passed |

实现入口为 `services/quant-api/app/market_data/`、`app/models/market_tables.py` 和
`app/guiyi_cli/data_commands.py`。复用现有 resolver 与维护入口；缺少 Calendar、Session、rank1、coverage
或物理可读性时 fail-closed，不造数、缩窗、插值或跨合约/周期替代。

验证以 `TESTING.md` 为准。生产 mutation 前重读精确计划和现场身份；provider、commit 或网络结果不明时
只做独立只读核对，再由 owner 决定后续动作。
