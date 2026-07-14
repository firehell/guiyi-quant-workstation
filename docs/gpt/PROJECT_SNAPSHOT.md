# 项目快照

更新时间：2026-07-14

## 项目定位

归一量化是本地、单用户的国内期货研究工作站，服务于数据更新、质量检查、K 线、策略、回测、报告、复盘、信号提醒和人工观察。V1 不自动交易，不接实盘账户，不做 SaaS。

## 架构快照

```text
RQData / Local Standard Parquet
-> DuckDB
-> PostgreSQL metadata / facts
-> FastAPI / vn.py / Vue Web
-> Market / Backtest / Signal / Review / Runtime
```

active 入口：

```text
provider in ("rqdata", "local_parquet")
data_role = "primary"
quality_status != "failed"
```

严格研究、回测和 Stage 9 前置 Gate 默认要求 `quality_status=passed`。

## 当前数据状态

当前最终状态：

```text
DATA_LAYER_PARTIAL
DATA_LAYER_READY_FOR_MARKET_BACKTEST_SIGNAL  # 未达成
```

Phase 3 口径：

- `covered_passed=15350`
- `covered_warning=105`
- `metadata_gap=1853`
- `not_applicable=1943`
- `direct_1w_present=90/90`
- `pre_2020_weekly_covered=29/63`
- `pre_2020_weekly_missing=34`

`DATA-PART-TARGET-CLOSURE DELIVERY_READY` 是历史数据部分目标收口，不等于当前数据层最终 ready。

## 当前功能面

- Web：Dashboard、Data、Market、Strategy、Backtest、Signal、Runtime、Review、Settings。
- 数据：RQData ingest、standard parquet、manifest、quality report、PostgreSQL metadata、DuckDB active 读取。
- 指标：EMA validated；MACD/ATR draft；火天大有 observation-only。
- 策略：苏冰 EMA21、JM V1-B 等 vn.py strategy drafts / candidates；策略结论仍需样本外验证。
- 回测：vn.py runner、报告、trade/order、equity/drawdown、trust audit。
- 信号：`strategy_signals`、`signal_events`、Stage 9 Gate、企业微信 preview/send-once/retry 框架。
- Runtime：live tables、scheduler 代码和模板、runtime health；真实 T3 和长稳 Gate pending。
- 工作站：TASK、dispatch、writer lock、result bundle、redaction、WorkBuddy/CodeBuddy/Codex 协作规则。

## 可信回测状态

`report_id=14`：155 trades、239 orders 全 mapped，trust audit passed，total return 约 -19.29%。这只证明数据、执行、成本、lineage 和指标可追溯，不证明盈利、稳定或可实盘。

## 运行与安全

- PostgreSQL/Redis 仅 localhost；凭据走环境变量。
- 腾讯云 Nginx + FRP 是当前公网只读拓扑模板；真实域名/TLS/Basic Auth/端口封闭/重启恢复仍需 smoke。
- launchd 本机磁盘副本已作为运行方向；`T3_REAL_PASSED`、`JM_RUNTIME_READY`、`LONG_RUNNING_READY` 未达成。
- 企业微信 webhook 只允许通过环境变量读取，不进入仓库、日志或文档。

## 推荐读取

浏览器 GPT 优先读取 `docs/gpt/project_sources/00-INDEX.md`，再按需读取本文件链接的 canonical 文档。
