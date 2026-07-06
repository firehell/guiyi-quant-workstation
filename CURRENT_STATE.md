# CURRENT_STATE.md

生成时间：2026-07-06
用途：上传到新的 ChatGPT 项目，作为当前项目状态速览。
事实优先级：当前仓库代码最高，其次是本文件和 `PROJECT_SNAPSHOT.md`，再次是 `docs/ROADMAP.md`；旧聊天只作为历史参考。

## 1. 当前阶段

```text
阶段 0：V1 重构基线冻结
```

本轮任务性质：docs-only。

本轮目标是把“现有 MVP 上收敛重构”的 V1 新基线冻结到项目文档中，清理旧路线、待定数据源和历史讨论对后续任务的影响。

## 2. 当前分支和工作区

- 当前分支：`codex/workstation-cloudflare-healthz`。
- 本轮开始前工作区干净。
- 当前不在 `main`，因此不需要新建 `codex/stage0-rebase-freeze`。

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

## 6. 当前未完成项

以下均为后续任务，不能描述为已完成能力：

- 阶段 1：RQData 权限与接口能力 PoC。
- JM 历史数据更新到最新交易日。
- manifest / checksum / quality_status 收敛。
- RQData 实时 1m 入库。
- 1m 聚合 5m / 15m / 30m / 1h / 1d / 1w。
- `signal_events` 信号事件化。
- 企业微信只读提醒。
- Web Market 策略展示。
- 本地长期运行 / worker / scheduler / health check。
- Cloudflare Access 本地 Web 访问部署验收。
- 可信回测主线复核。

## 7. 本轮禁止事项

本轮不做：

- 不修改业务代码。
- 不修改前端代码。
- 不修改策略或回测代码。
- 不新增 migration。
- 不运行 RQData。
- 不写数据库。
- 不写 `data/`。
- 不启动服务。
- 不做浏览器验收。
- 不写敏感信息。

## 8. 下一步

下一步应进入：

```text
阶段 1：RQData 权限与接口能力 PoC
```

阶段 1 默认只读，禁止写 `data/`，禁止写数据库，禁止运行真实数据写入任务，禁止打印 licence。建议新 Codex 会话 + Plan 模式。
