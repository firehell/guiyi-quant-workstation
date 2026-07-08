# 当前项目状态

生成时间：2026-07-07

用途：上传到浏览器 GPT，作为当前项目状态速览。事实优先级为当前仓库代码和数据证据，其次是本文件、`PROJECT_SNAPSHOT.md`、`tasks/current.md`。

## 1. 当前阶段

当前已进入：

```text
Stage 8.5：数据主链路扩展 Gate
```

已完成：

```text
8.5-0 Stage 8 输出审查
8.5-1 数据新口径冻结与文档更新
8.5-2 schema / model 变更 Plan
8.5-3 schema / model 最小实现
8.5-4 RQData 元数据与目标品种池只读 Plan
8.5-5 主连 + 当前真实主力合约 historical bars 设计冻结
8.5-6 写入试点代码 + dry-run + fixture 测试闭环
8.5-6B JM-only 当前真实主力合约 historical bars 真实写入试点
8.5-7 Web Data / Web Market actual-contract 数据消费扩展
8.5-8 live 监听目标合约池 + evaluator 数据源收敛
8.5-9 盘后归档设计与 Stage 9 前 final Gate
```

下一步建议：

```text
Stage 9：企业微信只读提醒 guarded adapter 设计 / 实现
```

Stage 9 可进入 guarded adapter 设计 / 实现，但真实发送仍需后续单独授权。`signal_events` / `strategy_signals` 已显式支持 product、continuous contract、actual contract、dominant mapping date、confirmed bar boundary、trigger price、provider/source、data_role 和 quality_status。8.5-9 已新增只读 `evaluate_stage9_signal_event_gate()`，只有通过 Gate 的 `signal_created` / `signal_changed` entry signal 事件才可作为企业微信只读提醒候选；当前 historical scanner 仍以 `jm.MAIN` 为扫描合约的事件会被阻断。

当前补充事实：

- Web Market 已新增「品种研究」只读面板，读取本地 PostgreSQL 中的 RQData 结构化数据，不改变 K 线读取入口。
- 全品种下载已出现一批 manifest / processed summary，但仍处于“进行中 / 待审计”，不能直接写成全部可进入 active。
- Web 托管当前主线改为阿里云方案；Cloudflare Access 保留为历史备选，不再作为当前默认路线。

## 2. 数据链路约束

V1 active 数据入口只允许：

```text
source/provider in ("rqdata", "local_parquet")
data_role = "primary"
quality_status != "failed"
```

严格研究优先 `quality_status=passed`。

旧 TqSdk / 天勤、交易练习者、validation、legacy_reference、candidate、failed 数据不得进入正式回测、默认 Market API 或信号输入。

Stage 8.5 新增口径：

- `continuous_contract` 用于研究、回测背景、连续图和日线方向。
- `actual_contract` 用于 live 触发、trigger price、企业微信 payload 和复盘入口。
- live DB 只做盘中观察和 preview，不登记 `market_data_files`，不自动进入 active historical。
- 盘后归档必须单独通过质量 Gate 后才能进入 historical active。
- V1-B 默认目标品种池先锁定为 `jm`，不在 8.5-4 扩成全品种。
- metadata 源复用 `FuturesContractUniverse`、`MainContractMap`、`FuturesContinuousContractMap`、`FuturesTradingParameter` 和 `FeeMarginRule`。
- `jm.MAIN` historical bars 只作为研究主连资产；真实 `actual_contract` historical bars 必须作为独立 canonical bars 资产。
- `trigger_price` 后续只能来自 `actual_contract` 的 confirmed historical / live bar close。
- 8.5-6 dry-run 默认不构造 RQData client、不打开 DB、不写 parquet / manifest / DB、不登记 primary。
- 8.5-6B 已写入 `actual_contract=JM2609` 的 independent canonical bars，不能把该合约硬编码为长期主力。
- 8.5-7 Web 只读消费扩展只读取已登记的 `market_data_files` / `data_quality_reports`，不新增 RQData 写入、不改 parquet / manifest、不改变策略或回测口径。
- 8.5-8 live/evaluator 收敛只读解析 live target 和 preview DTO，不写正式 signal/event/notification，不接企业微信。
- 8.5-9 盘后归档只冻结设计边界：RQData after-market direct data 是主输入，live DB 仅作为 verification / discrepancy evidence；真实归档写入、worker、scheduler 仍需另开任务授权。

## 3. JM v2 数据状态

分钟 bar 最大自然时间为夜盘 `2026-07-06 23:00:00`，对应最大 `trading_day=2026-07-07`。日线最大自然时间为 `2026-07-06 00:00:00`。

| timeframe | rows | min datetime | max datetime | max trading_day | data_version |
|---|---:|---|---|---|---|
| 1m | 289455 | 2023-01-03 09:01 | 2026-07-06 23:00 | 2026-07-07 | `rqdata_jm_standard_1m_20230103_20260707_v2` |
| 5m | 57891 | 2023-01-03 09:05 | 2026-07-06 23:00 | 2026-07-07 | `rqdata_jm_standard_5m_20230103_20260707_v2` |
| 15m | 19297 | 2023-01-03 09:15 | 2026-07-06 23:00 | 2026-07-07 | `rqdata_jm_standard_15m_20230103_20260707_v2` |
| 30m | 10072 | 2023-01-03 09:30 | 2026-07-06 23:00 | 2026-07-07 | `rqdata_jm_standard_30m_20230103_20260707_v2` |
| 60m | 5883 | 2023-01-03 10:00 | 2026-07-06 23:00 | 2026-07-07 | `rqdata_jm_standard_60m_20230103_20260707_v2` |
| 1d | 847 | 2023-01-03 00:00 | 2026-07-06 00:00 | 2026-07-06 | `rqdata_jm_standard_1d_20230103_20260707_v2` |

关键证据：

- `data/processed/v1b/jm/jm_v2_parquet_20230103_20260707.json`
- `data/manifests/rqdata_jm_v2_history_20230103_20260707.csv`
- `data/processed/v1b/jm/jm_v2_coverage_audit_20230103_20260707.json`

## 4. 已具备功能

- RQData ingest、JM v2 parquet、manifest、quality report、DB 登记。
- DuckDB 读取 standard parquet。
- FastAPI 数据中心、Market、Backtest、Signal、Review API。
- RQData live 1m 最小入库骨架。
- live 1m 聚合 5m / 15m / 30m / 60m。
- Web Market 显式 historical / live 查看。
- JM V1-B live evaluator preview-only 接口。
- vn.py CTA 回测任务、JM V1-B 固定任务、报告、曲线、交易明细。
- Vue Web 的 Data、Market、Backtest、Signal、Review 页面。
- K 线图、指标、回测买卖点 marker。
- JM V1-B 信号扫描，只提醒不下单。
- `signal_events` append-only 信号事件账本。
- `strategy_signals` / `signal_events` contract context 显式字段与 API 过滤。
- Web Data / Web Market 显式展示 `jm.MAIN` 主连研究视图与 `JM2609` 真实合约视图、data_version、file_path、latest bar boundary。
- `GET /api/v1/market/live/targets` 可只读查看 live target readiness、actual-contract coverage、live coverage 和 blocked reasons。
- JM V1-B live evaluator preview 可省略 `contract` 自动解析 actual-contract，并显式返回 `continuous_contract`、`actual_contract`、`dominant_mapping_date`、`bar_end` 和 entry-signal-only `trigger_price`。
- `evaluate_stage9_signal_event_gate()` 可只读判断 Stage 9 提醒候选事件，返回 `allowed`、`blocked_reasons` 和脱敏 `payload_basis`。
- 从回测成交创建复盘 note。
- WebSocket 进度与信号通道。
- `/health`、`/api/health`、`/healthz` 健康检查。
- Web Market 品种研究面板：主力映射、复权因子、交易参数、仓单、展期收益、合约池、连续合约和会员排名只读展示。
- 全品种下载分层脚本：metadata、主连 historical、actual-contract roll、research enhancers、audit。

## 5. Stage 8.5 审查结论

当前 `signal_events` 已完成：

- `signal_created`
- `signal_changed`
- `signal_status_changed`
- `GET /api/signals/events`
- `GET /api/signals/{signal_id}/events`

Stage 8.5-3 已补齐 Stage 9 前置所需显式字段：

- `product`
- `continuous_contract`
- `actual_contract`
- `dominant_mapping_date`
- `bar_start` / `bar_end`
- `trigger_price`
- `provider` / `source`

当前 JM V1-B historical scan 仍以 `jm.MAIN` 为扫描合约，`actual_contract` 缺少真实映射证据时保持 `NULL`，`trigger_price` 仍来自主连 bar close，不足以作为真实主力合约提醒价格。

Stage 8.5-4 已完成 docs-level 元数据只读方案：

- `continuous_contract=jm.MAIN` 仍只作为研究主连 / 连续视图。
- `actual_contract` 只能来自 `MainContractMap.rank=1` 的真实主力映射。
- trading params 必须覆盖 `price_tick`、`contract_multiplier`、margin、commission；缺任一关键字段时不能进入 Stage 9。
- 真实 `rqdata_realtime_poc.py --run-readonly` 仍需单独授权。

Stage 8.5-5 已完成 docs-level historical bars 方案：

- `continuous_contract=jm.MAIN` 继续用于研究主连、连续图、日线方向和 historical scan 背景。
- 当前真实主力合约 historical bars 后续必须使用真实合约代码作为 `contract`，独立于 `jm.MAIN` 文件和语义。
- 首批 periods 与 JM v2 对齐：`1m / 5m / 15m / 30m / 60m / 1d`。
- 8.5-6 写入试点建议优先下载真实主力 `1m` 标准 bars，再聚合生成更高周期；如改用 RQData 直接多周期下载，必须在代码计划中说明取舍并补测试。
- 只有明确授权写入且质量报告通过后，才允许登记 `market_data_files` 和 `data_role=primary`。

Stage 8.5-6 已完成 code-level dry-run / fixture 闭环：

- 新增 `actual_contract_bars_pilot.py` 和 `rqdata_actual_contract_bars_pilot.py`。
- fake client / SQLite 测试覆盖缺主力映射、`.MAIN` 误用、缺交易参数、quality failed 不登记 primary、quality passed 登记真实 `actual_contract`。

Stage 8.5-6B 已完成 real write：

- `actual_contract=JM2609`
- `dominant_mapping_date=2026-07-07`
- window：`2026-07-06..2026-07-07`
- manifest：`data/manifests/rqdata_actual_contract_bars_jm_JM2609_20260706_20260707.csv`
- row_count：`1m=690`、`5m=138`、`15m=46`、`30m=24`、`60m=14`、`1d=3`
- 六周期 canonical `market_data_files` 均为 `provider=rqdata`、`contract_code=JM2609`、`data_role=primary`、`quality_status=passed`
- 质量口径：自然午休、夜盘、节假日和周末间隔记录为 `gap_samples`，不计入 `missing_bars`；重复、OHLC 异常、负 volume/open_interest 仍阻断 primary。

Stage 8.5-7 已完成 Web 只读消费扩展：

- `GET /api/v1/market/workbench/coverage` / `GET /api/v1/market/bars` 的 coverage 返回 `view_role`、`continuous_contract`、`actual_contract`、`latest_bar_time`、`data_version`、`data_role`、`file_path`。
- Web Data 数据文件表新增“视图”和“最新边界”显示。
- Web Market 普通行情模式使用真实合约，回测深链才允许主连；页面展示当前主力、主连研究合约、真实合约、数据版本、文件路径和最新边界。

Stage 8.5-8 已完成 live/evaluator 只读收敛：

- 新增 live target resolver 和 `GET /api/v1/market/live/targets`。
- target 默认仅限 `jm`，actual-contract 来自 `MainContractMap.rank=1/provider=rqdata`。
- target gate 检查交易参数和 actual-contract historical `1m/5m/15m` primary passed coverage。
- `LiveSignalEvaluator` 不再信任任意请求合约；省略 contract 时解析当前 actual-contract，`.MAIN` 或错配合约返回 422。
- evaluator preview 显式区分 live observation、continuous historical daily view 和 actual-contract historical coverage。

Stage 8.5-9 已完成 final Gate：

- 新增只读 `evaluate_stage9_signal_event_gate()`，不读取 webhook、不发送通知、不写 `SignalNotification`。
- Gate 要求 `signal_created` / `signal_changed`、`entry_signal`、真实 `actual_contract`、`dominant_mapping_date`、`bar_end`、正数 `trigger_price`、`provider in (rqdata, local_parquet)`、`data_role=primary`、`quality_status.status=passed`。
- payload basis 固定表达 `observation_only` 和 `not_trading_instruction`，并过滤敏感字段。
- 盘后归档边界已冻结，真实归档写入仍不属于 8.5-9。

## 6. 未完成能力

- 企业微信只读提醒。
- 全品种下载结果审计、DB 登记核对和 active Gate 分层确认。
- Web Market 策略 marker、策略详情侧栏、historical / live / signal 联动。
- 盘后归档真实写入、worker、scheduler 和 runtime dashboard。
- 阿里云 Web 托管设计与远程 health smoke。
- Dashboard 真实数据接入。
- 策略管理页面实用化。
- Settings 持久化。
- 可信回测主线复核。

## 7. 当前禁止事项

- 不运行新的 RQData 写入、下载、sync、asset 或 ingest 任务，除非另开任务明确授权。
- 不运行真实 RQData `--run-readonly`，除非另开任务明确授权。
- 不运行新的真实 historical bars 写入试点，除非另开任务明确授权。
- 不覆盖 JM v1 或 JM v2 历史数据文件。
- 不把当前真实主力合约 bars 写入 `jm.MAIN` 文件或复用 `jm.MAIN` 的 `contract` 语义。
- 不把 live DB 或 live 聚合 DB 直接登记为 trusted historical active。
- 不接企业微信，不读取或打印 `QYWX_WEBHOOK_URL`。
- 不接实盘，不自动下单，不生成订单草稿。
- Stage 9 真实发送必须另开任务授权；默认只能设计 / 实现 guarded adapter，不自动发送。
