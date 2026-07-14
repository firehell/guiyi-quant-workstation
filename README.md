# 归一量化工作站

更新时间：2026-07-14

本仓库是本地运行、单用户使用的国内期货量化研究工作站。当前重点是 V1 / V1-B：数据更新、质量检查、K 线查看、策略回测、报告、复盘、信号提醒和人工观察。

项目不是 SaaS，不做无人值守自动实盘，不接实盘账户自动下单，不把信号或回测结果当成交易指令。

## 快速导航

| 用途 | 文件 |
|---|---|
| 长期事实源 | `PROJECT_SOURCE.md` |
| 当前状态 | `STATUS.md` |
| 架构决策 | `DECISIONS.md` |
| 当前任务池 | `CODEX_TASKS.md` |
| 测试与 Gate | `TESTING.md` |
| 当前任务 | `tasks/current.md` |
| 数据中心 | `docs/DATA_CENTER.md` |
| 系统架构 | `docs/ARCHITECTURE.md` |
| 回测口径 | `docs/BACKTEST_ENGINE.md` |
| 信号事件 | `docs/SIGNAL_EVENTS.md` |
| Codex 交接 | `docs/CODEX_HANDOFF.md` |
| GPT Project Sources | `docs/gpt/project_sources/00-INDEX.md` |
| GPT Sources manifest | `docs/gpt/PROJECT_SOURCE_MANIFEST.md` |

## 当前状态

当前数据层最终状态：

```text
DATA_LAYER_PARTIAL
DATA_LAYER_READY_FOR_MARKET_BACKTEST_SIGNAL  # 未达成
```

`DATA-PART-TARGET-CLOSURE DELIVERY_READY` 是先前数据部分目标收口结论，不等于数据层最终封板完成。

当前 Phase 3 数据口径保留：

- `covered_passed=15350`
- `covered_warning=105`
- `metadata_gap=1853`
- `not_applicable=1943`
- `pre_2020_weekly_covered=29/63`
- `pre_2020_weekly_missing=34`

105 条 `quality_warning` 保持 warning，不升级为 passed。

## 主链路

```text
RQData / Local Standard Parquet
-> DuckDB
-> PostgreSQL metadata / facts
-> FastAPI / vn.py / Vue Web
-> Market / Backtest / Signal / Review / Runtime
```

active 入口硬约束：

```text
provider in ("rqdata", "local_parquet")
data_role = "primary"
quality_status != "failed"
```

严格研究、回测和 Stage 9 前置 Gate 默认使用 `quality_status=passed`。

## 已具备能力

- RQData ingest、standard parquet、manifest、checksum、quality report 和 PostgreSQL metadata 登记。
- DuckDB active 读取与 K 线工作台。
- vn.py 回测、报告、trade/order、equity/drawdown、K 线 marker。
- `report_id=14` trust audit passed；该结论只代表可追溯和内部一致，不代表策略盈利或可实盘。
- `signal_events`、Stage 9 Gate、企业微信 preview、受控发送记录和 Stage 9-B2 historical replay single-send smoke。
- Runtime health API、launchd/frp/nginx 模板和工作站任务控制面。

## 未完成 Gate

- manifest / DB 对齐专项：`metadata_gap=1853`。
- pre-2020 周线 34 品种缺口专项。
- actual contract 缺口专项。
- JM T3-real 单次 live 写入 Gate。
- 5 个真实交易日长稳与 kill/recovery。
- 真实公网 TLS、Basic Auth、端口封闭、FRP/Nginx 重启恢复 smoke。
- OOS / walk-forward 验证。

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
./scripts/post-reboot-verify.sh
```

## 安全边界

- 密钥、密码、license、webhook、cookie 只允许存在于本机环境或受控系统配置。
- 不接实盘账户，不生成自动委托，不自动 push/merge/deploy。
- 企业微信只做观察提醒，不表达买卖指令。
- 单次 smoke 不等于长期运行 ready。
