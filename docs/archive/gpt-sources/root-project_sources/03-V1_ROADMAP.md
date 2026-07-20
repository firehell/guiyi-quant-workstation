# V1 Roadmap

更新时间：2026-07-14

事实来源：`PROJECT_SOURCE.md`、`STATUS.md`、`CODEX_TASKS.md`、`docs/CODEX_HANDOFF.md`

## 当前阶段

当前阶段是 V1 / V1-B 的可信研究闭环收口：

```text
数据更新 -> 数据质量检查 -> 标准化存储 -> K 线查看
-> 策略 / 信号 -> 回测 -> 报告 -> 单笔复盘
-> 人工观察 -> 前向验证
```

V1-B 仍是研究闭环，不是 V1.5 / V2 实盘阶段。企业微信只做 observation-only 提醒，不做自动下单。

## 已具备能力

- RQData ingest、standard parquet、manifest、checksum、quality report 和 PostgreSQL metadata 登记。
- DuckDB active 读取、Market K 线展示、指标叠加和 Web 基础页面。
- vn.py 回测、报告、trade/order、equity/drawdown、K 线 marker 和 `report_id=14` trust audit。
- `signal_events`、Stage 9 Gate、企业微信 preview、受控发送记录和 Stage 9-B2 historical replay single-send smoke。
- Runtime health API、launchd/frp/nginx 模板和工作站任务控制面。

## 当前 Gate

```text
DATA_LAYER_PARTIAL
DATA_LAYER_READY_FOR_MARKET_BACKTEST_SIGNAL  # 未达成
```

当前不能宣称全品种周线从上市以来完整，不能宣称 `T3_REAL_PASSED`、`JM_RUNTIME_READY`、`LONG_RUNNING_READY`，也不能把 `report_id=14` 写成策略盈利、稳定或实盘准入。

## 下一步顺序

| 优先级 | 任务 | 默认模式 | Gate |
|---|---|---|---|
| P0 | manifest / DB 对齐专项 | Plan 模式 | 解释或修复 `metadata_gap=1853` |
| P0 | pre-2020 周线 34 品种缺口专项 | Plan 模式 | 判定补数据或 N/A |
| P0 | JM T3-real 单次 live 写入 Gate | Plan + 用户确认 | 真实可交易时段和写入授权 |
| P0 | 真实公网安全 smoke | Plan + 人工环境 | TLS、Basic Auth、端口封闭、重启恢复 |
| P1 | actual contract 缺口专项 | Plan 模式 | 判定补 bars、N/A 或 mapping 修复 |
| P1 | OOS / walk-forward 验证 | Plan 模式 | frozen config，不调参改善收益 |
| P1 | Web trust audit 展示 | Plan 模式 | 展示可信审计，不改变回测口径 |

## 明确排除

- 自动交易、无人值守实盘、订单生成、多用户 SaaS。
- 用 `quality_warning` 冒充 `passed`。
- 把 historical replay smoke 写成 live-confirmed 或长期发送验收。
- 为改善收益而静默修改策略版本或回测口径。
