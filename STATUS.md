# 当前状态

更新时间：2026-09-03

本文件只记录当前 release、production Runtime、Scope、自然 evidence 与尚未完成的 Gate。稳定产品面见 `PROJECT_SOURCE.md`，长期决策见 `DECISIONS.md`，active 依赖见 `docs/ARCHITECTURE.md`。

## Release、Runtime 与 Scope

| 项目 | 当前事实 |
|---|---|
| Release | `v1.9.14@ca15456eaff988db4fe61c37657ca37302a7f977` 是当前最新正式 release；`main` 与 annotated tag peeled commit 精确一致。GitHub Release 已于 2026-09-03 正式发布。 |
| Runtime | 五项 launchd 均指向 clean、detached `/Volumes/扩展盘/guiyi-quant-runtime-v1.9.13-r1@9edbdfa7`；2026-09-03 只读 readback 为 API/Web/Live/Alert `running`，After-market 按调度 `not running`。该 exact tag 仍使用错误的一分钟 session 锚点，不能作为 G10 通过证据。 |
| Database | 2026-09-03 只读 readback：production Alembic 为 `20260902_0044`；Rule 恰为 enabled HTDY `jm × 15m` 与 disabled、empty-scope `subing_ths_alert_15m_v1`；SuBing Event 为 0。0045 尚未执行。 |
| Market Runtime Scope | `operational_products.txt` 的 60 个品种。 |
| Alert Scope | HTDY 为 `jm × 15m`；SuBing 严格保持 `disabled + empty scope`。G10 因 session 首分钟锚点错误判定未通过，G9 不得执行。 |
| Session anchor repair | `v1.9.14` 已包含 adapter 单点规范化、forward-only 0045、三阶段 `session-anchor-repair` 与 `subing_ths_15m_v3`。真实 RQData shadow prepare、Canonical/Catalog publish、production 0045、Redis cleanup、v1.9.14 Runtime 与重做 G10 均未执行。 |
| v1.9.8 | Alert startup/final catch-up 的 Live snapshot 冻结在 causal `through` 上界，避免批量 restore 期间新到达 Bar 污染较早产品；Runtime status 写 schema v4，保留每个 unavailable 产品的固定公开 reason，并兼容读取 v1/v2/v3。无 migration、Scope、Rule、audience、transport 或策略公式变化。 |
| v1.9.9 | frozen final-catch-up watermark 队列 reconciliation：严格更旧 Bar 丢弃，相同 watermark 仍校验，更新 Bar 只推进且不补发；reconciliation 结束前保持 warming，只有 active60 全 ready 才写 `strategy_ready_at`。完整后端、Web、Ruff、Mypy、canonical、OpenSpec 与 secret scan 已通过，Standards/Spec 复审均 no findings；当前已 `RELEASED`，已完成 exact-tag Runtime 切换；首根自然 completed Live Gate 与 canary 均未完成。 |
| v1.9.10 | completed 1m Bar 仅在 atomic ready heartbeat 写入确认后才 PubSub；Redis 持久化、heartbeat、PubSub 或派生失败均 fail-closed，且同一 poll 不重试发布。完整非隔离后端、Mypy、Ruff、canonical、OpenSpec、secret scan 与 Web check/test/build 已通过，Standards/Spec 复审通过。该版本仍为 `RELEASED`；其 Runtime checkout 已在 v1.9.11 五项服务读回后移除，不再是现役或本地 rollback root。 |
| v1.9.11 | HTDY immutable Event 与 one-shot PushPlus 只接受触发窗口最新 completed Bar；repaint zone 中的旧 Bar 仅保留 Web retrospective 观察，不创建 Event/通知，既有 Event 不变。后端 `2234 passed, 3 skipped, 6 deselected`、Web `347 passed, 1 skipped`、Ruff、Mypy、OpenSpec、secret scan 与 release identity 检查均通过。当前为 `RELEASED`，并实际承载五项服务；2026-09-02 开盘 Live 为 `60/60 TRADING`，Alert 有新 heartbeat 且 processing 为 `ok`，但 legacy SuBing 状态 `0/60 ready` 使 Runtime 仍为 degraded，不能标记 `RUNTIME_READY`。 |
| v1.9.12 | 已 `RELEASED`：后端 `880 passed, 3 skipped, 7 deselected`、engineering `10 passed`、0043 targeted `22 passed, 1 isolated PostgreSQL skipped`、Mypy、Ruff、OpenSpec、secret scan、Web unit/build 与 Playwright `25 passed` 均通过。已执行一次 Runtime 切换；API/Web/Live 已加载 exact tag，Alert 未能建立 heartbeat，production migration 仍未执行。 |
| v1.9.13 | 已 `RELEASED` 并完成 production 0043→0044 与五项 exact-tag Runtime promotion；SuBing 保持 disabled + empty scope。随后 G10 发现 RQData session 首根 1m 标签被当作排他 start，日内桶整体右移一分钟，因此 G10 未通过。 |
| v1.9.14 | 已 `RELEASED`：PR #326 的 RC `13688fcf…` 合入 `main@ca15456e…`，annotated tag 与 GitHub Release 均已创建。后端 `1374 passed, 3 skipped, 15 deselected`；isolated PostgreSQL `0043→0044→0045` 为 `9 passed`；Ruff、Mypy、Web、Playwright、OpenSpec、secret scan 与独立 Review 均通过。production 0045、Canonical repair、Runtime promotion 与 G10 均未执行。 |

Alert transport 为 PushPlus；provider accepted 不等于微信送达。

## 自然 evidence

- 2026-08-31 只读 Runtime health 显示自然 after-market 本轮已以 `passed` 完成：开始 `18:05:07 +08:00`、结束 `20:10:21 +08:00`、`attempts=1 / error_code=null`、覆盖 operational 60；未手工启动、补跑或回填。
- 2026-09-01 `13:46:05 +08:00`，JM 的 HTDY 15m 自然 first-seen buy Event 已持久化并触发一次 PushPlus transport；provider accepted 仅表示服务端受理，不等于微信送达。
- 2026-09-02 开盘只读 Runtime health 显示 Live `60/60`、全部 `TRADING`，且 Live 与 Alert heartbeat 均为新鲜；Alert processing 为 `ok`，但 legacy SuBing `0/60 ready` 使整体 health 仍为 degraded。

## Pending Gate

- exact-tag `session-anchor-repair --phase prepare --apply` 会调用真实 RQData 并写 shadow Canonical，需要一次新的真实数据授权。
- 停止五项 Runtime、publish shadow、reconcile Catalog、执行 production 0045 与清理最新交易日 Redis 是同一个维护 Gate，需要新的单次明确授权；0045 之后只能 forward recovery。
- exact-tag v1.9.14 Runtime promotion 是独立 Gate。完成 identity/health/data readback 前不得重做 G10。
- 新 G10 必须基于修正后的 exact-tag Runtime 对 RB/JM 及规定金叉/死叉样本逐条解释一致。G10 通过前 SuBing 必须保持 disabled + empty scope；G9 Scope activation 仍需另行授权。
- G9 之后仍须等待自然 completed 15m Event、one-shot PushPlus provider acceptance 与用户微信实际送达确认；不得用 synthetic、replay、backfill 或手工发送替代。
