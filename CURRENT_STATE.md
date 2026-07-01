# CURRENT_STATE.md

生成时间：2026-07-01  
用途：上传到新的 ChatGPT 项目，作为当前项目状态速览。  
事实优先级：当前代码最高，其次是本文件和 `PROJECT_SNAPSHOT.md`，再次是 `docs/ROADMAP.md`；旧聊天只作为历史参考。

## 1. 当前分支

- 本轮开始检查时分支：`main`。
- 为避免直接在 `main` 修改文档，已创建并切换到：`codex/stage0-project-context`。
- 本轮只修改允许范围内的文档和 `tasks/current.md`，不修改业务代码。

## 2. 当前仓库状态

- 本轮开始 `git status --short` 为空，无未提交修改。
- 本轮新增 `docs/PROJECT_INSTRUCTIONS_COMPACT.md`。
- 本轮更新 `PROJECT_SNAPSHOT.md`、`CURRENT_STATE.md`、`docs/CODEX_HANDOFF_FOR_CHATGPT.md`、`docs/NEXT_STEPS.md`、`docs/AI_DEVELOPMENT_WORKFLOW.md`、`docs/ROADMAP.md`、`tasks/current.md`。
- `docs/STRATEGY_CURRENT_STATE.md` 保持当前策略结论，不在本轮重写。

## 3. 本轮任务状态

当前任务是：

```text
阶段 0：项目上下文和协作规则收敛
```

本轮任务性质：

- 文档与任务上下文更新。
- 不修改后端、前端、策略、回测或数据库代码。
- 不运行 RQData。
- 不写数据库。
- 不写 `data/`。
- 不启动后端或前端服务。
- 不做浏览器验收。

## 4. 当前项目主链路

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

TqSdk、CTP、TuShare、AKShare 不作为当前 V1 主链路。旧天勤数据只可作为 validation source；交易练习者数据只可作为 legacy_reference。

## 5. 当前后端状态

- FastAPI 入口：`services/quant-api/app/main.py`。
- 已注册 data center、market、backtests、signals、reviews、WebSocket 路由。
- 回测 API 已支持通用任务、JM 15m/5m 固定任务、日线 EMA21/MACD/量能任务、日线 score2of4 任务。
- vn.py 集成位于 `services/quant-api/app/vnpy_integration/`。
- 报告、交易、订单、资金曲线、回撤曲线查询 API 已存在。
- 信号扫描支持通用扫描和 `POST /api/signals/v1b/jm/scan`。
- 复盘 API 支持从 backtest trade 创建 review note。
- 本轮未运行服务、未连接数据库、未执行 Alembic current。

## 6. 当前前端状态

- 前端位于 `apps/quant-web/`。
- 路由包括 `/dashboard`、`/data`、`/market`、`/strategy`、`/backtest`、`/backtest/batch`、`/signal`、`/review`、`/settings`。
- K线图使用 Lightweight Charts，交易 marker 工具位于 `src/utils/tradeMarker.ts`。
- 回测、K线、信号、复盘页面具备当前研究闭环所需基础能力。
- Dashboard 仍可能是 mock；Strategy / Settings 与后端接口一致性需要后续验收。
- 本轮是文档任务，未做浏览器验收。

## 7. 当前数据状态

- V1 主数据源：RQData / Local Standard Parquet。
- JM 已有 2023-01-03 至 2025-12-31 的 1d / 15m / 5m / 1m 数据资产。
- 正式回测应读取 primary / passed 数据，不应混入 validation / legacy_reference。
- DuckDB 用于本地 Parquet 查询，PostgreSQL 存业务事实。
- 实时 RQData 1m 入库、最新交易日更新、manifest / checksum 收敛仍是后续任务，不是本轮已完成内容。

## 8. 当前策略状态

- 已有 JM V1-B / V1-Final 固定策略 `jm_v1b_daily_direction_fast_entry / v1b.0`。
- 已有苏冰短持有策略 `su_bing_jm_v1b_short_hold / v0.1.1-spec`。
- 已有日线冻结基线 `su_bing_jm_daily_ema21_macd_volume / v0.2.0-daily`。
- 已有日线研究版本 `su_bing_jm_daily_ema21_macd_volume / v0.3.0-daily-score2of4`。
- 当前最重要结论：`v0.3` raw 为正，但 trusted excluding cross-contract 为负，不建议进入实盘、模拟盘或参数优化。

## 9. 当前回测报告状态

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

## 10. 当前信号扫描和复盘状态

- 通用信号扫描和 JM V1-B 专用扫描 API 已存在。
- 当前 V1 信号扫描只提醒，不自动下单。
- 日线 `v0.3 score2of4` 是否接入信号扫描，后续必须作为单独任务设计，不能顺手扩展。
- 可以从 backtest trade 创建 review note。
- `immediate_failure_later`、MFE、MAE 等交易后信息不得参与同一时点入场/出场判断。

## 11. 下一步最应该做什么

下一步建议进入：

```text
阶段 1：RQData 权限与接口能力 PoC
```

建议新 Codex 会话和 checkpoint。下一轮默认只做只读 PoC：确认 RQData 本地环境、权限、可用接口、合约/分钟数据/交易参数字段能力，并输出数据链路任务设计。除非下一轮 Prompt 明确允许，否则禁止写 `data/` 和数据库。
