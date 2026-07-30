# 当前状态

更新时间：2026-07-30

本文件是项目当前状态的仪表盘：只列当前工作、未关闭 Gate、必要事实锚点与防过度宣称的红线。历史过程由 Git 提交和 final receipt 追溯。

## 当前在做什么

当前阶段为 V1-B 的 JM Stage 6 与指标/策略可信验证主线。S6-10 schema-v7 的完整日/收盘观察与长期 daily-child 消费链已代码闭环，但仍为 `CODE_COMPLETE_EXTERNAL_GATE_PENDING`：必须以干净 source checkpoint 生成 fresh 完整交易日 C2、取得 Approval D，并完成真实 mapping、部署和运行证据。已失败的 `8119dbba` C2 仅是 fail-closed 证据，不得重试、补发或复用。

## 未关闭 Gate

| 项 | 状态 | 说明 |
|---|---|---|
| HTDY XMA 语义 | blocked | 保持 `HTDY_FORMULA_OR_XMA_SEMANTICS_UNRESOLVED`，不重开公式审计 |
| Audit V2 residual triage | pending | 解释 calendar/session/physical/quality residual 后再决定受控任务 |
| 全历史 residual triage | pending | 不得将消费者 Ready 扩写为所有历史资产零 residual |
| S6-10 长稳 | external Gate pending | fresh C2、Approval D、真实运行与完整日/长期证据均未完成 |
| 真实公网安全 smoke | pending | TLS、Basic Auth、端口不可达与 FRP/Nginx 重启恢复 |
| V1 最终验收 | pending | 仅在各独立 receipt 与长期 Gate 完成后进行 |

## 必要事实锚点

| 事实 | 当前值 | 证据 |
|---|---|---|
| PostgreSQL revision | `20260721_0025` | `docs/tasks/S6-07-DATABASE-REVISION-DRIFT-RECOVERY.md` |
| HTDY S6-08 | 已完成限定自然事件与幂等验证；autosend=false | `docs/tasks/JM-LIVE-SIGNAL-EVENT-S6-08.md` 与 final receipt |
| S6-09 单条企业微信 | event 4 only；notification 2；attempt=1 | `data/reports/jm_live_wecom_single_s6_09/` final receipt |
| S6-10 | schema-v7 code complete，真实 Gate 未执行 | `docs/tasks/JM-LIVE-STABILITY-S6-10.md` |

## 不可宣称

- 不可把数据、消费者或 archive Gate 写成所有历史资产零 residual、Runtime Ready、长稳 Ready、通知 Ready 或自动交易 Ready。
- 不可把 `report_id=14` trust audit、任何 backtest 或单次 smoke 写成策略盈利或实盘准入。
- 不可把 HTDY realtime exception 写成历史回测、OOS、收益或交易资格；`REJECTED_RESEARCH_CANDIDATE` 不得被翻转。
- 不可宣称 `HTDY_XMA_SEMANTICS_AUDITED`；原始 XMA 仅保留精确 observation-only policy。

相关业务定义见 `docs/ARCHITECTURE.md`、`docs/DATA_CENTER.md`、`docs/BACKTEST_ENGINE.md`、`docs/SIGNAL_EVENTS.md` 与 `docs/INDICATOR_KERNEL.md`。
