# Stage 8.5 Data Universe And Archive

生成时间：2026-07-07

## 1. 当前判断

Stage 8 `signal_events` 已完成代码 / 文档级闭环，但还不能直接进入 Stage 9 企业微信只读提醒。

原因：

- 当前 `signal_events` 已通过 Stage 8.5-3 显式支持 `product`、`continuous_contract`、`actual_contract`、`dominant_mapping_date`、`bar_start`、`bar_end`、`trigger_price`、`provider`、`source`。
- JM V1-B historical scan 当前仍以 `jm.MAIN` 作为扫描合约，`actual_contract` 在没有真实主力映射证据时保持 `NULL`，`trigger_price` 仍来自主连 bar close，不能稳定表达真实主力合约触发价。
- `live_signal_evaluator` 当前是 preview-only，只返回临时 DTO，不写 `StrategySignal`、`SignalNotification` 或 `SignalEvent`。

因此阶段顺序冻结为：

```text
Stage 8 signal_events 完成
-> Stage 8.5 数据主链路扩展
-> Stage 9 企业微信只读提醒
```

Stage 9 之前必须继续完成 Stage 8.5 后续 Gate，避免企业微信 payload 只显示主连研究合约，无法审计真实触发合约和触发价。

## 2. Stage 8 输出审查

### 已支持

- append-only `signal_events` 事件账本。
- `signal_created`、`signal_changed`、`signal_status_changed` 三类事件。
- `source_mode` 区分 `historical_scan`、`jm_v1b_scan`、`manual_api`。
- `payload` 会过滤 `webhook`、`token`、`password`、`secret`、`cookie` 等敏感键。
- 只读 API：`GET /api/signals/events`、`GET /api/signals/{signal_id}/events`。
- `live_signal_evaluator` 不写正式事件，保持 preview-only。

### 仍不足以承接 Stage 9 的点

- `actual_contract` 只有在已有明确真实合约证据时才写入；`jm.MAIN` 不会被伪装成真实交易合约。
- `trigger_price` 已列化，但 JM V1-B historical scan 当前仍来自主连 bar close，不足以作为真实主力合约提醒价格。
- `dominant_mapping_date` 已列化但当前可空，后续仍需 8.5-4 / 8.5-5 确认映射来源。

### 结论

Stage 8.5-3 已完成 schema / model 最小实现；Stage 9 前仍需补真实主力映射、真实合约 historical bars 和 trigger price 来源。

## 3. 数据口径冻结

### 合约角色

- `continuous_contract`：研究、回测背景、连续图和日线方向使用。例如 `jm.MAIN`。
- `actual_contract`：当前真实主力合约，盘中 live 触发、trigger price、企业微信 payload、复盘入口使用。例如 `JM2609`。
- `previous_actual_contract`：换月安全窗口内的前主力合约，用于覆盖检查和回放。
- `next_actual_contract`：下一个主力候选合约，用于换月前预检和数据补齐。

### 数据层边界

```text
RQData historical
-> raw parquet
-> standard parquet
-> manifest / checksum / quality report
-> market_data_files / data_quality_reports
-> active historical
```

```text
RQData live / near-realtime
-> live_minute_bars
-> live_aggregated_bars
-> explicit live view / live evaluator preview
```

live DB 只做盘中观察和 preview，不直接登记为 `market_data_files`，不自动进入 active historical。

### active Gate

正式默认读取仍只允许：

```text
source/provider in ("rqdata", "local_parquet")
data_role = "primary"
quality_status != "failed"
```

严格研究和 Stage 9 前置 Gate 优先要求：

```text
quality_status = "passed"
bar_status = "confirmed"  # live 层适用
```

禁止把 `validation`、`legacy_reference`、`candidate`、`failed`、旧 TqSdk / 天勤数据或交易练习者数据作为默认 active 输入。

## 4. 现有模型复用

Stage 8.5 不从零新建一套数据宇宙，优先复用现有模型：

- `MainContractMap`：真实主力映射，适合记录 product/date/rank/contract。
- `FuturesContinuousContractMap`：连续合约到真实合约的映射。
- `FuturesContractUniverse`：目标品种在某交易日的合约池。
- `FuturesTradingParameter`：保证金、手续费、最小变动、合约乘数。
- `MarketDataFile` / `DataQualityReport`：historical active 数据资产登记和质量报告。
- `LiveMinuteBar` / `LiveAggregatedBar`：盘中显式 live 层。

当前更可能需要增强的是信号侧字段，而不是新增大表。

## 5. Schema Plan

### 推荐最小方向

在正式进入 Stage 9 前，新增或等价实现以下显式可查询字段：

- `product`
- `continuous_contract`
- `actual_contract`
- `dominant_mapping_date`
- `bar_start`
- `bar_end`
- `trigger_price`
- `provider`
- `source`
- `data_role`
- `quality_status`

推荐优先落在 `strategy_signals` 和 `signal_events`，保证最新信号快照和 append-only 事件账本口径一致。

### 不推荐方向

- 不建议只把关键字段放进 `payload.features`。
- 不建议让企业微信阶段自行解析不同来源 payload。
- 不建议在 Stage 9 里临时补合约映射逻辑。
- 不建议把 live evaluator preview 直接持久化为正式事件，除非另开阶段定义 confirmed bar 和质量 Gate。

### 迁移风险

- 旧 `signal_events` 没有这些字段，需要 nullable 迁移或回填策略。
- `event_key` 去重口径可能需要纳入 `actual_contract` 和 `bar_end`，否则主连与真实合约绑定变化时不易区分。
- `StrategySignal.contract` 现有语义含混，迁移后应明确是 `continuous_contract`、`actual_contract` 还是兼容旧字段。

### 建议实施顺序

1. `DATA-CHAIN-8_5B-SCHEMA-PLAN`：只做 schema Plan，不改代码。
2. `DATA-CHAIN-8_5C-SCHEMA-MINIMAL-IMPLEMENTATION`：确认后新增 migration、ORM、schema、事件 payload 和测试。
3. `DATA-UNIVERSE-8_5D-METADATA-READONLY-PLAN`：只读确认目标品种池、主力映射、交易参数。
4. `DATA-UNIVERSE-8_5E-HISTORICAL-BARS-PLAN`：设计主连和真实主力 historical 扩展，不写数据。
5. `DATA-UNIVERSE-8_5F-HISTORICAL-BARS-PILOT-WRITE`：明确授权后做 JM-only 或极小试点写入。

### 8.5-3 实现结论

已新增 Alembic migration、ORM、Pydantic schema、API 输出与过滤、事件投影和测试。`strategy_signals` 与 `signal_events` 已具备显式 contract context 字段。

兼容策略：

- 保留旧 `contract` 字段作为兼容展示字段。
- `.MAIN` 主连写入 `continuous_contract`，不写入 `actual_contract`。
- 缺少真实映射证据时，`actual_contract` 保持 `NULL`。
- `bar_start` 暂按 `period` 和 `bar_end` 保守推导；后续真实 bar metadata 接入后应优先使用源 bar 边界。

## 6. Stage 8.5-4 RQData 元数据只读 Plan

8.5-4 已冻结为 docs-level 只读方案阶段，不运行真实 RQData 写入，不写 parquet / manifest / checksum，不登记 DB 行情资产。

目标是确认 Stage 9 前置所需元数据来源，而不是确认行情 bar 本身：

- 目标品种池：V1-B 默认只覆盖 `jm`，不在本阶段扩展为全品种池。
- 合约池来源：复用 `FuturesContractUniverse`，由 RQData `futures.get_contracts` / `RqDataClient.listed_contracts` 提供只读来源。
- 主力映射来源：复用 `MainContractMap`，由 RQData `futures.get_dominant(..., rank=1/2)` / `RqDataClient.dominant_contracts` 提供只读来源。
- 连续合约来源：复用 `FuturesContinuousContractMap`，由 RQData `futures.get_continuous_contracts` / `RqDataClient.continuous_contract_by_type` 提供 `front_month` / `next_month` 只读来源。
- 交易参数来源：复用 `FuturesTradingParameter` 和 `FeeMarginRule`，由 RQData `futures.get_trading_parameters`、`get_tick_size`、`get_contract_multiplier` 提供只读来源。

Stage 9 前置绑定规则：

- `continuous_contract=jm.MAIN` 只表示研究主连 / 连续视图，不得作为真实交易合约。
- `actual_contract` 只能来自 `MainContractMap.rank=1` 的真实主力映射；缺少映射证据时必须保持 `NULL`。
- `dominant_mapping_date` 对应 `MainContractMap.trade_date`，不能用信号生成日期替代。
- `trigger_price` 必须来自 `actual_contract` 的 confirmed bar；在 8.5-5 完成前，主连 close 不能宣称为真实合约提醒价格。
- trading params 必须覆盖 `price_tick`、`contract_multiplier`、margin、commission；缺任一关键字段时不能进入 Stage 9。

8.5-4 验证边界：

- 允许运行现有 metadata wrapper / ingest 单测和 `rqdata_realtime_poc.py --dry-run`。
- 真实 `rqdata_realtime_poc.py --run-readonly` 仍需单独授权，即使它设计为不写 DB / parquet / manifest。
- 本阶段不新增表、不新增 API、不修改信号或回测代码。

8.5-5 输入条件：

- 目标品种池已锁定为 `jm`。
- 真实主力映射字段来源已锁定为 `MainContractMap.rank=1`。
- 交易参数字段来源已锁定为 `FuturesTradingParameter`，必要时以 `FeeMarginRule` 作为审计 fallback。
- historical write 仍未授权；8.5-5 只设计主连 + 当前真实主力 historical bars 扩展方案。

## 7. Historical 数据扩展口径

首批不做全品种下载。

默认试点：

```text
product = jm
continuous_contract = jm.MAIN
actual_contract = 当前 RQData 主力真实合约
periods = 1m / 5m / 15m / 30m / 60m / 1d
```

每个 historical 数据资产必须经过：

```text
download
-> raw parquet
-> standard parquet
-> manifest
-> checksum
-> quality report
-> market_data_files
-> active Gate
```

质量检查至少包括：

- 缺口。
- 重复。
- 时间顺序。
- OHLC 异常。
- 空值。
- 非法 volume / open_interest。
- min/max datetime。
- row_count。
- data_version。
- checksum。

## 8. Web 与 live 口径

Web Data 后续应能看见：

- product。
- continuous coverage。
- actual contract coverage。
- period。
- latest trading day。
- data_version。
- quality_status。
- file_path。

Web Market 默认仍为 historical：

- 搜索 product 默认看 continuous historical view。
- 可切换当前真实主力合约。
- 可选择具体真实合约。
- live 模式必须显式切换，不自动拼接 historical。

live 监听后续只监听目标品种池的当前真实主力合约，不监听连续合约，不监听全市场所有合约。

## 9. 盘后归档 Gate

盘后归档只能作为单独阶段设计和实现。

目标流程：

```text
RQData after-market direct data / live DB verification
-> gap check
-> duplicate check
-> trading_day check
-> OHLC check
-> standard parquet
-> manifest
-> checksum
-> quality report
-> market_data_files
-> historical active
```

Stage 9 前 Gate：

- `signal_events` 能显式区分 product、continuous contract、actual contract。
- `trigger_price` 明确来自 actual contract。
- `bar_end` 已确认。
- `quality_status != failed`，严格场景优先 `passed`。
- 企业微信 payload 能显示真实合约，不表达实盘指令。
- webhook 只从环境变量读取，不进文档、DB、日志或 payload。
- V1 仍不自动下单。

## 10. Stage 8.5 任务顺序

```text
8.5-0 Stage 8 输出审查：done / docs-level
8.5-1 数据新口径冻结与文档更新：done / docs-level
8.5-2 schema / model 变更 Plan：done / docs-level
8.5-3 数据模型最小实现：done / code-level
8.5-4 RQData 元数据与目标品种池只读 Plan：done / docs-level
8.5-5 主连 + 当前主力真实合约 historical 数据方案：pending
8.5-6 historical 数据写入最小闭环：pending / requires explicit write authorization
8.5-7 Web Data / Web Market 数据消费扩展：pending
8.5-8 live 监听目标合约池 + evaluator 数据源收敛：pending
8.5-9 盘后归档设计与 Stage 9 前 Gate：pending
```

## 11. 本文档不授权

- 不授权 schema migration。
- 不授权真实 RQData 写入。
- 不授权写 parquet、manifest、checksum 或 DB rows。
- 不授权企业微信。
- 不授权自动下单或订单草稿。
- 不授权 live DB 直接进入 active historical。
- 不授权全品种数据下载。
