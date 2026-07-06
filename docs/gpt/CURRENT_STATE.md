# CURRENT_STATE.md

生成时间：2026-07-06
用途：上传到新的 ChatGPT 项目，作为当前项目状态速览。
事实优先级：当前仓库代码最高，其次是本文件和 `PROJECT_SNAPSHOT.md`，再次是 `docs/ROADMAP.md`；旧聊天只作为历史参考。

## 1. 当前阶段

```text
阶段 2-A：JM 历史数据更新方案 + 数据源收敛 Gate
```

阶段 1 RQData 权限与接口能力 PoC 已完成，结论为 `PARTIAL`。

阶段 1-C 真实只读 PoC 已确认：

- `rqdatac_import` 通过，版本为 `3.2.5`。
- `rqdata_auth_init` 通过。
- JM 合约目录、DCE JM 合约列表、1d / 1m 小样本可用。
- 1m / 5m / 15m / 30m / 60m 返回字段包含 OHLCV 和 `open_interest`。
- 主力映射、合约乘数、保证金和手续费字段可用。

阶段 1-C 缺口：

- `trading_sessions` 返回 0 行。
- `continuous_contracts` 返回 0 行。
- `ex_factor` 返回 0 行。
- `realtime_snapshot_or_bar` 没有安全 wrapper，仍未验证。
- `invalid_symbol_error` 返回 `ValueError`，属于负向探针结果，不阻塞阶段 2。

阶段 2-A 结论：已完成 JM 历史数据执行前方案设计，下一步建议进入 `JM-UPDATE-2B-PLAN-VERIFY`，只读确认实际最新交易日、合约段、30m/60m 处理方式和目标版本。阶段 2-B 之前不得直接运行写入脚本。

## 2. 当前分支和工作区

- 当前分支：`main`。
- 本轮只更新文档和任务状态。
- 本轮没有运行真实 RQData。
- 本轮没有写 `data/`、数据库、parquet、manifest、checksum 或 quality report。
- 本轮没有修改业务代码。

## 3. 当前项目定位

归一量化是本地运行的国内期货量化研究、实时行情观察规划、策略信号提醒规划和 Web 复盘工作站。

V1 第一版目标：

```text
RQData / Local Standard Parquet
-> DuckDB
-> PostgreSQL / vn.py CTA BacktestingEngine
-> FastAPI
-> Vue Web
-> K线展示 / 策略信号 / 回测报告 / 单笔复盘 / 人工观察
```

V1 不做自动下单，不做模拟盘自动接单，不做无人值守交易。

## 4. 现有 MVP 可复用资产

后续应优先复用：

- FastAPI 后端。
- Vue Web 工作台。
- RQData ingest、Parquet、DuckDB、PostgreSQL 数据链路。
- vn.py CTA 回测适配、ResultConverter、报告入库。
- Market K线查询、K线 marker、信号扫描、复盘 note。
- 本地 `/healthz` 和 Cloudflare Access 文档准备项。

这些能力不代表实时 1m 入库、`signal_events`、企业微信提醒、Web Market 策略展示已经完成。

## 5. 数据链路状态

V1 active 数据入口只允许：

```text
source = rqdata / local_parquet
data_role = primary
quality_status != failed
```

旧 TqSdk / 天勤数据最多作为历史 validation source；交易练习者数据最多作为 legacy_reference。它们不得恢复为 V1 active 数据源。

当前 JM 数据资产仍停在 2025-12-31，需要后续阶段更新到最新交易日：

| 周期 | 范围 | 行数 | data_version |
|---|---|---:|---|
| 1d | 2023-01-03 至 2025-12-31 | 727 | `rqdata_jm_standard_1d_20230103_20251231_v1` |
| 15m | 2023-01-03 至 2025-12-31 | 16569 | `rqdata_jm_standard_15m_20230103_20251231_v1` |
| 5m | 2023-01-03 至 2025-12-31 | 49707 | `rqdata_jm_standard_5m_20230103_20251231_v1` |
| 1m | 2023-01-03 至 2025-12-31 | 248535 | `rqdata_jm_standard_1m_20230103_20251231_v1` |
| 30m | unknown | unknown | `unknown` |
| 60m | unknown | unknown | `unknown` |

Stage 2-A 方案文件：`docs/JM_HISTORY_UPDATE_PLAN.md`。

## 6. 当前未完成项

以下均为后续任务，不能描述为已完成能力：

- JM 历史数据更新到最新交易日。
- manifest / checksum / quality_status 收敛。
- `trading_sessions`、`continuous_contracts`、`ex_factor` 空样本原因确认。
- RQData 实时 1m 入库。
- 1m 聚合 5m / 15m / 30m / 1h / 1d / 1w。
- `signal_events` 信号事件化。
- 企业微信只读提醒。
- Web Market 策略展示。
- 本地长期运行 / worker / scheduler / health check。
- Cloudflare Access 本地 Web 访问部署验收。
- 可信回测主线复核。

## 7. 当前禁止事项

后续未获明确授权前，不做：

- 不修改业务代码。
- 不修改前端代码。
- 不修改策略或回测代码。
- 不新增 migration。
- 不运行 RQData 写入、下载、sync、asset 或 ingest 任务。
- 不写数据库。
- 不写 `data/`。
- 不写 parquet 或 manifest。
- 不启动服务。
- 不写敏感信息。
- 不把 RQData PoC 结论写成 JM 数据已更新或实时 1m 入库已完成。

## 8. 下一步

下一步应进入：

```text
JM-UPDATE-2B-PLAN-VERIFY
```

Stage 2-B 建议新 Codex 会话 + Plan 模式。先只读确认实际更新范围、最新交易日、目标合约段、6 个周期目标版本和输出路径，再决定是否进入写 parquet / manifest / DB 的任务。
