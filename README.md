# 归一量化工作站

本仓库是本地运行的国内期货量化研究工作站，当前重点是 V1 / V1-B：数据更新、质量检查、K 线、策略回测、报告、复盘、信号提醒和人工观察。

项目不是 SaaS，不做无人值守自动实盘，不把信号或回测结果当成交易指令。

## 快速导航

| 用途 | 文件 |
|---|---|
| 当前任务 | `tasks/current.md` |
| GPT 当前状态 | `docs/gpt/CURRENT_STATE.md` |
| GPT 长期快照 | `docs/gpt/PROJECT_SNAPSHOT.md` |
| 下一步 | `docs/gpt/NEXT_STEPS.md` |
| 架构 | `docs/ARCHITECTURE.md` |
| 数据中心 | `docs/DATA_CENTER.md` |
| 回测口径 | `docs/BACKTEST_ENGINE.md` |
| Stage 13 审计 | `docs/STAGE13_BACKTEST_TRUST_AUDIT.md` |
| 实时闭环验收 | `docs/tasks/V1-LIVE-RUNTIME-CLOSURE-ACCEPTANCE.md` |
| Codex 交接 | `docs/CODEX_HANDOFF.md` |
| AI 工作站 | `workstation/STATION_CONFIG.md` |

## 当前阶段

当前执行 `V1-LIVE-RUNTIME-CLOSURE`：

- Stage 13-G 已完成，`report_id=14` trust audit 为 `passed`。
- JM 最新主连六周期已收敛到 `20230103_20260710_v2`；5m/15m/30m/60m/1d 全部从通过质量 Gate 的 1m standard parquet 本地聚合。
- Stage 8.6 全品种 `1d` Gate 当前为 82 products `active_passed`、8 products `active_partial`；176 assets passed、8 assets pending。
- JM 最新主连六周期专用 Gate 为 6/6 `active_passed`。
- PostgreSQL / Redis 仅绑定 `127.0.0.1`；Redis 使用环境变量密码。
- JM-only live runtime 的 scheduler、交易时钟、日/周 confirmed 聚合、正式 event、盘后归档和 notification worker 已完成代码测试；真实开关默认关闭，尚未做写入/发送/长稳 smoke。
- 公网主线是腾讯云 Nginx + FRP。真实域名、证书、401/200/WS、端口和重启恢复尚未远程 smoke。

## 主链路

```text
RQData 1m / Local Standard Parquet
-> 1m quality Gate
-> local aggregation 5m / 15m / 30m / 60m / 1d
-> manifest / checksum / PostgreSQL metadata
-> DuckDB
-> vn.py / FastAPI
-> Vue Web
-> K线 / 回测 / 复盘 / 信号提醒 / 人工观察
```

active 入口硬约束：

```text
provider in ("rqdata", "local_parquet")
data_role = "primary"
quality_status != "failed"
```

严格研究使用 `quality_status=passed`。validation、legacy_reference、candidate、旧 TqSdk / 天勤和交易练习者数据不得进入默认 Market、Backtest 或 Signal 输入。

## JM 最新数据

| timeframe | rows | max datetime | data_version | derivation | quality |
|---|---:|---|---|---|---|
| 1m | 290490 | 2026-07-09 23:00 | `rqdata_jm_standard_1m_20230103_20260710_v2` | RQData direct | passed |
| 5m | 58098 | 2026-07-09 23:00 | `rqdata_jm_standard_5m_20230103_20260710_v2` | aggregated from 1m | passed |
| 15m | 19366 | 2026-07-09 23:00 | `rqdata_jm_standard_15m_20230103_20260710_v2` | aggregated from 1m | passed |
| 30m | 10108 | 2026-07-09 23:00 | `rqdata_jm_standard_30m_20230103_20260710_v2` | aggregated from 1m | passed |
| 60m | 5904 | 2026-07-09 23:00 | `rqdata_jm_standard_60m_20230103_20260710_v2` | aggregated from 1m | passed |
| 1d | 851 | 2026-07-10 00:00 | `rqdata_jm_standard_1d_20230103_20260710_v2` | aggregated by trading_day from 1m | passed |

证据：

- `data/processed/v1b/jm/jm_v2_parquet_20230103_20260710.json`
- `data/manifests/rqdata_jm_v2_history_20230103_20260710.csv`
- `data/reports/jm_main_six_period_latest/stage8_6_active_gate_summary.md`

## 已具备能力

- RQData ingest、Parquet、manifest、checksum、quality report 和 DB 元数据登记。
- DuckDB active 读取与 K 线工作台。
- vn.py 回测任务、报告、曲线、trade/order、K 线 marker。
- Stage 13 只读 trust audit，复算 trade/order/equity/drawdown/cost/multiplier/lineage。
- JM V1-B 信号扫描、append-only `signal_events`、真实合约 Gate。
- 企业微信 preview、受控单条发送、通知记录、独立 notification queue/worker 和 live-only dispatcher；autosend 默认关闭。
- 从回测成交创建 review note、标签和统计。
- runtime health API 与只读 Web 页面；按 queue 检查 worker，并展示 scheduler/live/archive/retry 状态。
- JM actual-contract live 1m→5m/15m/30m/60m/1d/1w、受控盘后归档和 formal live event writer。

## 仍未完成

- 全品种 8 个 `active_partial` 的质量或登记修复。
- JM 单次真实 live write/restart、盘后归档和 live event 企业微信 smoke。
- 5 个交易日长期运行、故障注入与 launchd 重启恢复；代码/模板通过不等于长期 ready。
- 样本外 / walk-forward 验证；不得通过调参改善当前报告收益。
- 真实公网服务器的 TLS、未认证 401、端口封闭和重启恢复 smoke。
- 实施前只读状态为 API/Web loaded、backtest/signal worker missing、runtime degraded；外接卷权限或本机运行副本仍需人工处理。

## 本地开发启动

```bash
cp .env.example .env
# 替换所有 replace-with-*；.env 严禁提交
./scripts/dev-up.sh
```

```text
Web: http://127.0.0.1:5173
API: http://127.0.0.1:8000
API docs: http://127.0.0.1:8000/docs
```

```bash
./scripts/dev-status.sh --json
./scripts/dev-healthcheck.sh --json --no-start
```

生产模板和安全 Gate 见 `deploy/nginx/README.md`；公网验收必须使用 HTTPS，且 5432/6379/8000/5173 不得对公网开放。

## 安全边界

- 密钥、密码、license、webhook、cookie 只允许存在于本机环境或受控系统配置。
- 不接实盘账户，不生成自动委托，不自动 push/merge/deploy。
- 回测通过可信审计只证明结果可追溯和内部一致，不证明策略可盈利或可实盘。
