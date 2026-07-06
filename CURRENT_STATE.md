# CURRENT_STATE.md

生成时间：2026-07-06
用途：上传到新的 ChatGPT 项目，作为当前项目状态速览。
事实优先级：当前仓库代码最高，其次是本文件和 `PROJECT_SNAPSHOT.md`，再次是 `docs/ROADMAP.md`；旧聊天只作为历史参考。

## 1. 当前分支和工作区

- 当前分支：`codex/workstation-cloudflare-healthz`。
- 当前 HEAD：`fcaba363 数据提交`。
- 本次同步前工作区干净。
- 最近已完成两类事项：
  - `DATA-001-rqdata-source-slimdown`：数据源瘦身，active 主链路收敛为 RQData / Local Standard Parquet。
  - `workstation-cloudflare-healthz`：本地工作站远程浏览器访问准备，补充 `/healthz`、同源 API/WS 解析和 Cloudflare Tunnel + Access 文档。

## 2. 当前项目定位

归一量化是本地运行的国内期货量化研究、回测、复盘、信号扫描和人工观察工作站。当前仍处于 V1 Web 研究闭环，不是 SaaS，不做自动下单，不做无人值守实盘。

当前主链路：

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

## 3. 数据链路状态

- V1 active 数据入口只允许 `rqdata` / `local_parquet`。
- active 数据只允许 `data_role=primary`。
- `quality_status=failed` 不得进入正式读取；严格研究优先使用 `quality_status=passed`。
- TqSdk / 天勤旧数据、交易练习者数据和 TqSdk 临时下载文件已从当前 active 数据体系移除。
- `find data -path '*tqsdk*' -o -path '*trader*' -o -path '*Future*'` 当前无输出。
- TqSdk / CTP 后续仅可作为 V2 或 future backup 单独评估，不是 V1 主链路。

当前 JM 数据资产：

| 周期 | 范围 | 行数 | data_version |
|---|---|---:|---|
| 1d | 2023-01-03 至 2025-12-31 | 727 | `rqdata_jm_standard_1d_20230103_20251231_v1` |
| 15m | 2023-01-03 至 2025-12-31 | 16569 | `rqdata_jm_standard_15m_20230103_20251231_v1` |
| 5m | 2023-01-03 至 2025-12-31 | 49707 | `rqdata_jm_standard_5m_20230103_20251231_v1` |
| 1m | 2023-01-03 至 2025-12-31 | 248535 | `rqdata_jm_standard_1m_20230103_20251231_v1` |

RQData licence 状态来自 2026-07-03 只读实测：认证方式为本地环境变量中的 `license_key`，许可类型 `FULL`，剩余约 361 天；未打印或写入真实 key。后续 PoC 应继续只读确认接口和字段能力。

## 4. 后端状态

- FastAPI 入口：`services/quant-api/app/main.py`。
- 已注册 data center、market、backtests、signals、reviews、WebSocket 路由。
- 健康检查：
  - `GET /health`
  - `GET /api/health`
  - `GET /healthz` 返回 `{"status":"ok","service":"local-workstation"}`。
- 回测 API 支持通用任务、JM 15m/5m 固定任务、日线 EMA21/MACD/量能任务、日线 score2of4 任务。
- vn.py 集成位于 `services/quant-api/app/vnpy_integration/`。
- 信号扫描支持通用扫描和 `POST /api/signals/v1b/jm/scan`。
- 复盘 API 支持从 backtest trade 创建 review note。

## 5. 前端和远程访问状态

- 前端位于 `apps/quant-web/`。
- 主要路由：`/dashboard`、`/data`、`/market`、`/strategy`、`/backtest`、`/backtest/batch`、`/signal`、`/review`、`/settings`。
- `apps/quant-web/src/utils/network.ts` 负责同源 API base 和 WebSocket URL 解析，支持 Cloudflare Access 后的 `https` / `wss` 场景。
- Vite 已代理 `/api`、`/ws`、`/healthz` 到本地后端。
- Cloudflare 访问口径见 `docs/CLOUDFLARE_WORKSTATION_ACCESS.md`：
  - 本地前端：`http://127.0.0.1:5173`
  - 本地 API：`http://127.0.0.1:8000`
  - 远程浏览器入口：`https://workstation.yanyi.com`
  - 只暴露 Web/API，不暴露 SSH、terminal、code-server 或 shell。

## 6. 策略和回测状态

主要策略版本：

| strategy_code | strategy_version | 状态 |
|---|---|---|
| `jm_v1b_daily_direction_fast_entry` | `v1b.0` | JM 15m / 5m 固定任务主线，历史 V1-Final 报告已生成 |
| `su_bing_jm_v1b_short_hold` | `v0.1.1-spec` | 日线方向 + 15m/5m 短持有研究 spec |
| `su_bing_jm_daily_ema21_macd_volume` | `v0.2.0-daily` | 日线 EMA21 / MACD / 量能冻结基线 |
| `su_bing_jm_daily_ema21_macd_volume` | `v0.3.0-daily-score2of4` | 日线 2/4 条件研究版本，trusted 结果为负 |

关键结论：

- V1-Final 15m / 5m 报告：`report_id=5` / `report_id=6`，历史验收通过，但不能直接代表实盘收益。
- `v0.3.0-daily-score2of4` 报告：`report_id=11`。
- `v0.3` raw 为正，但 trusted excluding cross-contract 为负：
  - raw trades：47
  - trusted trades：39
  - excluded cross-contract trades：8
  - raw net pnl：52798.083
  - trusted net pnl：-34914.555
  - trusted win rate：0.2051282051
  - trusted max drawdown：0.3728810309
  - trusted max consecutive losses：8
- 可信结论只能使用 trusted metrics，不能把跨合约收益混入策略判断。

## 7. RQAlpha 实验目录状态

当前存在两个独立 RQAlpha Plus PoC：

- `experiments/rqalpha_su_bing_jm_daily/`：移植 `v0.2.0-daily` 日线规则，用于 RQAlpha 引擎冒烟和规则体感验证。
- `experiments/rqalpha_tdx_xma_bands/`：通达信 XMA 通道策略 PoC，明确存在未来函数 / 重绘风险。

这两个实验目录不属于 V1 正式回测报告链路，不入 PostgreSQL，不替代 vn.py 主链路；实验结论不能直接写成可信回测结论。

## 8. 当前测试基线

最近任务记录中的测试基线：

- `uv run --project services/quant-api pytest -q`：183 passed。
- `uv run --project services/quant-api ruff check .`：passed。
- `cd apps/quant-web && pnpm build`：passed，保留既有 chunk size warning。
- Cloudflare healthz 相关后端测试：`services/quant-api/tests/test_health.py`。
- 前端网络解析测试：`apps/quant-web/tests/network.test.ts`。

本次文档同步任务不运行 RQData 下载、不写数据库、不执行回测。

## 9. 当前风险和未完成项

- JM 数据仍停在 2025-12-31，后续目标是更新到最新可用交易日。
- manifest / checksum / quality_status 还需要进一步收敛，确保数据可追溯、可复算。
- RQData 权限 PoC 已有 licence 初步确认，但接口能力、字段覆盖、限制和错误类型仍需单独整理。
- RQData 实时 1m 入库、1m 聚合、signal_events、企业微信只读提醒、worker/scheduler/health check 都还没进入实现阶段。
- Dashboard 仍可能是 mock；Strategy / Settings 与后端接口一致性需要后续验收。
- 浏览器级 Data / Market / Signal / Review smoke 仍需单独执行。
- `v0.3.0-daily-score2of4` 当前 trusted 指标不合格，不能进入模拟盘、实盘或参数优化包装。

## 10. 下一步建议

下一步最小任务应是：

```text
阶段 1：RQData 权限与接口能力 PoC
```

目标是只读确认本地 RQData 能力：期货分钟数据、合约基础信息、主力映射、复权因子、交易参数、手续费、保证金、合约乘数字段、接口限制和错误类型。该任务建议新 Codex 会话 + Plan 模式，不写 `data/`、不写数据库、不打印 licence。
