# CURRENT_STATE.md

生成时间：2026-07-03  
用途：上传到新的 ChatGPT 项目，作为当前项目状态速览。  
事实优先级：当前代码最高，其次是本文件和 `PROJECT_SNAPSHOT.md`，再次是 `docs/ROADMAP.md`；旧聊天只作为历史参考。

## 1. 当前分支

- 当前分支：`codex/data-001-rqdata-slimdown`。
- 相对 `main` 领先 1 个提交（`32eda93c 删除数据`），工作区干净。
- `DATA-001-rqdata-source-slimdown` 五步已全部完成，建议合并到 `main` 后再开下一阶段任务。

## 2. 当前仓库状态

- `git status --short`：空，无未提交修改。
- 后端测试：`uv run --project services/quant-api pytest -q` → **183 passed**。
- 数据主链路已收敛为 RQData / Local Standard Parquet primary；TqSdk / 交易练习者 active 入口和数据已移除。
- 当前 active 数据体积：`data/raw/rqdata` 约 1.1G；`data/parquet/canonical/bars/provider=rqdata` 约 8.4M。
- RQData manifest 保留 9 份（catalog / contract / dominant / baseline / trading params 等）。

## 3. RQData Licence 状态（2026-07-03 实测）

- 认证方式：`license_key`（`.env` 中 `RQDATA_LICENSE_KEY`，未打印具体值）。
- `rqdatac.user.get_quota()` 结果：
  - **剩余天数：361 天**
  - **许可类型：FULL**
  - 流量配额：已用 0 / 上限约 1 GB
- API 冒烟：`trading_dates(2025-12-01 ~ 2025-12-05)` 返回 5 个交易日，接口可用。

## 4. 本轮任务状态

当前已完成任务是：

```text
DATA-001：数据源瘦身（移除旧天勤 / 交易练习者，收敛 RQData 主链路）
```

验收项全部勾选。下一步建议按 `docs/NEXT_STEPS.md` 进入 **阶段 1：RQData 权限与接口能力 PoC**（本轮实测已确认 licence 可用，PoC 可聚焦接口/字段能力清单）。

## 5. 当前项目主链路

当前 V1 主链路仍为：

```text
RQData / Local Standard Parquet
-> DuckDB
-> vn.py CTA BacktestingEngine
-> ResultConverter
-> PostgreSQL
-> FastAPI
-> Vue Web
-> K线复盘 / 信号提醒 / 人工观察 / 交易复盘
```

TqSdk、CTP、TuShare、AKShare 不作为当前 V1 主链路。旧天勤数据、交易练习者数据和 TqSdk 临时下载文件已从当前 active 数据体系移除；TqSdk 后续仅可作为 future backup 单独重引入。

## 6. 当前后端状态

- FastAPI 入口：`services/quant-api/app/main.py`。
- 已注册 data center、market、backtests、signals、reviews、WebSocket 路由。
- 回测 API 已支持通用任务、JM 15m/5m 固定任务、日线 EMA21/MACD/量能任务、日线 score2of4 任务。
- vn.py 集成位于 `services/quant-api/app/vnpy_integration/`。
- 报告、交易、订单、资金曲线、回撤曲线查询 API 已存在。
- 信号扫描支持通用扫描和 `POST /api/signals/v1b/jm/scan`。
- 复盘 API 支持从 backtest trade 创建 review note。
- 本轮未运行服务、未连接数据库、未执行 Alembic current。

## 7. 当前前端状态

- 前端位于 `apps/quant-web/`。
- 路由包括 `/dashboard`、`/data`、`/market`、`/strategy`、`/backtest`、`/backtest/batch`、`/signal`、`/review`、`/settings`。
- K线图使用 Lightweight Charts，交易 marker 工具位于 `src/utils/tradeMarker.ts`。
- 回测、K线、信号、复盘页面具备当前研究闭环所需基础能力。
- Dashboard 仍可能是 mock；Strategy / Settings 与后端接口一致性需要后续验收。
- 本轮是文档任务，未做浏览器验收。

## 8. 当前数据状态

- V1 主数据源：RQData / Local Standard Parquet。
- JM 已有 2023-01-03 至 2025-12-31 的 1d / 15m / 5m / 1m 数据资产。
- 正式回测应读取 `source=rqdata/local_parquet`、`data_role=primary`、`quality_status!=failed` 的数据；严格研究优先使用 `quality_status=passed`。
- DuckDB 用于本地 Parquet 查询，PostgreSQL 存业务事实。
- 实时 RQData 1m 入库、最新交易日更新、manifest / checksum 收敛仍是后续任务，不是本轮已完成内容。

## 9. 当前策略状态

- 已有 JM V1-B / V1-Final 固定策略 `jm_v1b_daily_direction_fast_entry / v1b.0`。
- 已有苏冰短持有策略 `su_bing_jm_v1b_short_hold / v0.1.1-spec`。
- 已有日线冻结基线 `su_bing_jm_daily_ema21_macd_volume / v0.2.0-daily`。
- 已有日线研究版本 `su_bing_jm_daily_ema21_macd_volume / v0.3.0-daily-score2of4`。
- 当前最重要结论：`v0.3` raw 为正，但 trusted excluding cross-contract 为负，不建议进入实盘、模拟盘或参数优化。

## 10. 当前回测报告状态

- V1-Final 15m / 5m 报告：`report_id=5` / `report_id=6`，历史验收通过，但策略收益和回撤仍需审查。
- `v0.2.0-daily` baseline 有 report 10 trusted review，上下文用于对比。
- `v0.3.0-daily-score2of4` 报告：`report_id=11`。
- `v0.3` 核心可信指标：
  - raw trades：47
  - trusted trades：39
  - excluded cross-contract trades：8
  - raw net pnl：52798.083
  - trusted net pnl：-34914.555
  - trusted win rate：0.2051282051
  - trusted max drawdown：0.3728810309
  - trusted max consecutive losses：8
- 可信结论必须只使用 trusted excluding cross-contract metrics。

## 11. 当前信号扫描和复盘状态

- 通用信号扫描和 JM V1-B 专用扫描 API 已存在。
- 当前 V1 信号扫描只提醒，不自动下单。
- 日线 `v0.3 score2of4` 是否接入信号扫描，后续必须作为单独任务设计，不能顺手扩展。
- 可以从 backtest trade 创建 review note。
- `immediate_failure_later`、MFE、MAE 等交易后信息不得参与同一时点入场/出场判断。

## 12. 下一步最应该做什么

1. 将 `codex/data-001-rqdata-slimdown` 合并到 `main`（checkpoint）。
2. 进入 **阶段 1：RQData 权限与接口能力 PoC** — licence 已确认可用（剩余 361 天），PoC 可聚焦接口/字段能力清单和限制。
3. 后续按 `docs/NEXT_STEPS.md` 推进 JM 数据更新、manifest 收敛、可信回测主线。
