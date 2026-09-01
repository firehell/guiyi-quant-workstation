# 当前状态

更新时间：2026-09-01

本文件只记录当前 release、production Runtime、Scope、自然 evidence 与尚未完成的 Gate。稳定产品面见 `PROJECT_SOURCE.md`，长期决策见 `DECISIONS.md`，active 依赖见 `docs/ARCHITECTURE.md`。

## Release、Runtime 与 Scope

| 项目 | 当前事实 |
|---|---|
| Release | `v1.9.11@64c689a3b73c27ea30397ca370acbbdc11522dda` 是当前最新 GitHub Release；`main`、annotated tag 的 peeled commit 与 GitHub Release target 精确一致，API 与 Web release identity 均为 `1.9.11`。它只包含 HTDY 当前 completed Bar Event/Push 修复与版本身份更新。 |
| Runtime | v1.9.11 已创建 clean、detached 的 `/Volumes/扩展盘/guiyi-quant-runtime-v1.9.11-r1@64c689a3`，并完成一次五项服务切换；读回出现 `live_unavailable / last_bar_at=null`、Alert `0/60 ready`，故已一次性 fail-closed 回滚。当前服务恢复绑定 clean、detached 的 `/Volumes/扩展盘/guiyi-quant-runtime-v1.9.10-r1@a56d13cd`：API/Web/Live running，Alert 为 `spawn_scheduled`，盘后服务按调度 `not_running`。当前 Runtime 为 degraded，不能标记 `RUNTIME_READY`。未执行盘后、未改 Scope/Rule、未手工发送通知。 |
| Database | production Alembic 为 `20260826_0042 (head)`。当前 Rule 为 `htdy_original_15m` 与 `subing_strategy_v1`。 |
| Market Runtime Scope | `operational_products.txt` 的 60 个品种。 |
| Alert Scope | HTDY Scope 为 `jm × 15m`；SuBing `scope_products` 为 operational 60。两种 authority 不合并。两条 Rule 均 enabled，Alert Runtime marker 已 enabled，audience count 2；未发生 Scope、Rule 或 audience 变更。 |
| v1.9.8 | Alert startup/final catch-up 的 Live snapshot 冻结在 causal `through` 上界，避免批量 restore 期间新到达 Bar 污染较早产品；Runtime status 写 schema v4，保留每个 unavailable 产品的固定公开 reason，并兼容读取 v1/v2/v3。无 migration、Scope、Rule、audience、transport 或策略公式变化。 |
| v1.9.9 | frozen final-catch-up watermark 队列 reconciliation：严格更旧 Bar 丢弃，相同 watermark 仍校验，更新 Bar 只推进且不补发；reconciliation 结束前保持 warming，只有 active60 全 ready 才写 `strategy_ready_at`。完整后端、Web、Ruff、Mypy、canonical、OpenSpec 与 secret scan 已通过，Standards/Spec 复审均 no findings；当前已 `RELEASED`，已完成 exact-tag Runtime 切换；首根自然 completed Live Gate 与 canary 均未完成。 |
| v1.9.10 | completed 1m Bar 仅在 atomic ready heartbeat 写入确认后才 PubSub；Redis 持久化、heartbeat、PubSub 或派生失败均 fail-closed，且同一 poll 不重试发布。完整非隔离后端、Mypy、Ruff、canonical、OpenSpec、secret scan 与 Web check/test/build 已通过，Standards/Spec 复审通过。当前为 `RELEASED`，并已完成 exact-tag Runtime 切换；startup restore 与下一交易时段的自然 completed Live Gate 尚未通过，不能标记 `RUNTIME_READY`。 |
| v1.9.11 | HTDY immutable Event 与 one-shot PushPlus 只接受触发窗口最新 completed Bar；repaint zone 中的旧 Bar 仅保留 Web retrospective 观察，不创建 Event/通知，既有 Event 不变，SuBing 不变。后端 `2234 passed, 3 skipped, 6 deselected`、Web `347 passed, 1 skipped`、Ruff、Mypy、OpenSpec、secret scan 与 release identity 检查均通过。当前为 `RELEASED`，但 exact-tag Runtime 切换因 `live_unavailable / last_bar_at=null` 已回滚，不能标记 `RUNTIME_READY`。 |

Alert transport 为 PushPlus；provider accepted 不等于微信送达。

## 自然 evidence

- 2026-08-31 只读 Runtime health 显示自然 after-market 本轮已以 `passed` 完成：开始 `18:05:07 +08:00`、结束 `20:10:21 +08:00`、`attempts=1 / error_code=null`、覆盖 operational 60；未手工启动、补跑或回填。
- 2026-09-01 `13:46:05 +08:00`，JM 的 HTDY 15m 自然 first-seen buy Event 已持久化并触发一次 PushPlus transport；provider accepted 仅表示服务端受理，不等于微信送达。SuBing 当前交易日没有 Strategy Action Event。

## Pending Gate

- v1.9.11 已 `RELEASED`，但唯一一次 exact-tag Runtime 切换已因 `live_unavailable / last_bar_at=null` fail-closed 回滚到 v1.9.10；不得重试，须在新的明确 Runtime 授权下重新 preflight 并重新取得首根自然 completed Live Gate。
- v1.9.10 已 `RELEASED` 并已完成一次 assets 预置后的 exact-tag Runtime 切换；当前 CLOSED startup restore 尚处 warming，必须等待 Alert heartbeat、下一交易时段的首根自然 completed Live Bar 和连续状态读回，才能标记 `RUNTIME_READY`。
- v1.9.9 已 `RELEASED` 并完成一次 exact-tag Runtime 切换，但首根自然 completed Live Gate 已失败：Alert 为 `19/60 ready`、`41/60 unavailable`，不得标记 `RUNTIME_READY`。修复后的 release 必须重新完成该 Gate。
- HTDY 的 2026-09-01 JM 15m natural Event 已取得 provider acceptance；微信实际送达，以及 D1/W1 `canonical_updated` 的自然 Event identity/evidence，仍须分别核验；不以测试、synthetic event、replay 或手工发送补证。
- v1.9.7-r3 当前仅作为 clean、detached rollback root 保留，已不再承载五项正式服务。
- 修复后的 SuBing 自然 Live continuation seam 与严格盘后完成制 evidence 必须重新取得；不以测试、startup replay、手工触发或回填替代。
- 一次 owner PushPlus canary 仍是独立 Gate。
- SuBing Candidate 的 prospective OOS 按其 protocol 独立累积，retrospective 不回填 OOS。
- 第一次自然盘后 derived 增量刷新仍须单独发生；2026-08-29 operator 已把效果快照 `through` 推到 `2026-08-28`，但不替代自然盘后 schema v3 status 写入。
- HTDY `jm × 15m` 下一次自然 15m completed Live bar 与 one-shot transport evidence 仍 pending（下次交易时段），不以 canary、replay 或手工发送替代。
