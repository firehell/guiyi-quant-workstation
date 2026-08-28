# 当前状态

更新时间：2026-08-29

本文件只记录当前 release、production Runtime、Scope、自然 evidence 与尚未完成的 Gate。稳定产品面见 `PROJECT_SOURCE.md`，长期决策见 `DECISIONS.md`，active 依赖见 `docs/ARCHITECTURE.md`。

## Release、Runtime 与 Scope

| 项目 | 当前事实 |
|---|---|
| Release | `v1.9.1` release candidate（occupancy-capped SuBing Stage 2 restore + 下一交易日 Live skip）。`v1.9.0` annotated tag 为 `a4d9a7b02bb4fd9b3bafefb719c579c0f0a184bc`。合入 `main` / tag / GitHub Release 完成前不把 `v1.9.1` 标为 `RELEASED`。 |
| Runtime | 本机当前仍绑定 `/Volumes/扩展盘/guiyi-quant-runtime-v1.9.0@a4d9a7b02…`。2026-08-29 01:37 验收 occupancy-capped restore 为 `57 ready / 3 unavailable`（`ag`/`au`/`sc`）；HTDY processing `ok`。这 3 个夜盘品种在 restore 成功后被 `2026-08-31` completed Live degrade（occupancy 止于 `2026-08-28`）。v1.9.1 Runtime promotion 完成后才验收 skip。 |
| Database | production Alembic 为 `20260826_0042 (head)`。Rule 已原子收敛为 `htdy_original_15m` 与 `subing_strategy_v1`；旧 SuBing Rule/Event 不保留。四张空的退役 `trade_*` 表已删除。 |
| Market Runtime Scope | `operational_products.txt` 的 60 个品种。 |
| Alert Scope | HTDY 唯一 production Scope 为 `jm × 15m`（`1 symbol / 1 pair`）；SuBing 唯一 production Scope 为 `jm`。两种授权边界不合并。DB 中 2 个 Rule 均 enabled；Alert Runtime marker 已 enabled；audience count 2。 |
| v1.9.1 release candidate | 含 SuBing 效果增量快照、v2→v3 adopt、occupancy-capped Stage 2 restore，以及 restore 后忽略尚未映射 occupancy 的下一交易日 Live。不新增 migration、不修改 Scope。Alert 保持 enabled。 |
| N Structure / Multi-Candidate retirement | release 与当时的 v1.8.8 Runtime promotion 均已完成；旧 `GET /api/v1/market/research/n-structure/bands` 在 production 返回 `404`，不保留 410、feature-disabled 或兼容 reader。Git/Alembic history 只保留 lineage。 |

Alert transport 为 PushPlus；provider accepted 不等于微信送达。2026-08-26 21:33，operator 已按当次明确请求对 `last_notification_failure_at=2026-08-25T11:40:05.182316+00:00` 执行一次精确 CAS acknowledgment；读回 `notification_state=acknowledged`、`notification_acknowledged_at=2026-08-26T13:33:29.088633+00:00`。原 failure、`notification_transport_failed` 与连续失败计数保留，`event_replayed=false / notification_sent=false`；该操作不证明 provider accepted 或微信送达。

## 自然 evidence

- 2026-08-26 自然 after-market 于 18:05:01 开始、19:48:41 以 `passed` 完成，`attempts=1 / error_code=null`，覆盖 active60，未发生 retry。盘后只读验收确认六个当日周期 60/60 推进到 `2026-08-26T07:00:00Z`、最近完整周 60/60 为 `2026-08-21T07:00:00Z`，420 个最新 Continuous 分区物理回读与 60 个 actual-dominant 1m 正式读取均零错误；未手工启动、补跑或回填。
- Daily Watch V2 已进入 release/Runtime；production `current` API 已读回 V2 identity，但当前自然 V2 artifact 尚未生成并返回 `SUBING_DAILY_WATCH_NOT_GENERATED`。2026-08-26 已有 V1 segment-local artifact 保持 immutable，不转换或冒充 V2 evidence。
- SuBing Strategy V1 Stage 1 在只读 `2024-01-01..2026-08-25` 自然窗口对 AG/JM/RB/EG 得到 `89/58/48/58` 个完整 Episode，共 `253` 个；自然语料覆盖 long/short、四种 entry source、四类 exit、gap、terminal close 与 prefix/pan invariance。该证据只支持 Historical Strategy Projection，不授权 Stage 2。
- HTDY 在既有 420-pair Scope 下形成的 6 条 D1 Event 保持 immutable；一次 W1 transport failure 后 processing 已自然恢复，但这不证明微信送达，也不替代 D1/W1 各自的自然身份核验。
- 2026-08-27 v1.8.8 Runtime promotion 前，只读校验 v1.8.7 的 schema-v2 `after-market-status.json` 为 owner-only `0600`，随后按相同 SHA-256 `7a4b25554fc63e377bb53ed6d3d38f6774d6da9b2905174c33d964dfb8592023` 迁入新 Runtime 根。13:32:10 首次读回 `status=ok / subscribed_count=60 / phase_counts.TRADING=60 / last_bar_at=2026-08-27T05:32:00Z`，支持当时 Market Runtime promotion acceptance；它不构成 Alert、Strategy Action 或通知 evidence。
- 2026-08-29 develop Runtime promotion 前，只读校验当时 v1.8.8 根的 schema-v2 `after-market-status.json`（2026-08-28 自然盘后 `passed`）为 owner-only `0600`，随后按相同 SHA-256 `d5e9db417b09ae8c38f5ad63cdabeb20d89281fb42c972fac1fb83b9012e65fc` 迁入后续 Runtime 根。`after_market.subing_strategy_performance` 在 health 中仍为 `null`，要等下一次自然盘后 derived 阶段写入 schema v3。该迁入不构成 derived 刷新、Alert 通知或微信送达 evidence。
- 2026-08-29 只读诊断：`restore_machine(jm)` 在 `now=Saturday` 下因 `MAIN_CONTRACT_MAP_MISSING`（目标 `2026-08-31`，occupancy 止于 `2026-08-28`）失败；occupancy-capped restore 合入 `v1.9.0` 后，`restore_machine(jm)` 与 `restore_machine(sc)` 成功。v1.9.0 Runtime 随后 `57/60 ready`，`ag`/`au`/`sc` 在夜盘 `TRADING` 下被下一交易日 completed Live degrade。该证据支持 v1.9.1 skip，不构成 v1.9.1 Runtime 已修复。

## 仓库验收 evidence

- Stage 2 recorded production-format shadow 使用 sealed Null Event/notification/cache/status 依赖与 committed deterministic fake readers，故意注入 1 个 source unavailable 后验证 active60 为 `59 ready / 1 bounded unavailable`、相同输入前缀的 Historical/Live Action 一致、Action 精确绑定下一实际 15m 区间第一根 1m open、跨 contract/segment identity 拒绝，以及无 Action 前缀不制造 Action。真实 read-only shadow 未获本轮授权，保持 skipped；该证据不构成 Runtime、自然 Event 或通知证据。
- SuBing active60 全历史效果代码已合入 `develop`：固定复用 `actual_dominant + 15m` Historical Projection，新增 reference-change 统计 API、产品详情底部效果与 Episode 记录、Git 外 cache warm CLI，以及 after-market schema v3 派生阶段；2026-08-28 第三次单次授权生产 warm 以 `status=passed` 完成：`planned_count=60 / completed_count=60 / failed_products=[] / cache_published_count=60 / authoritative_writes=false`；物理回读 `through=2026-08-27` 为 active60 各 1 份 schema-v2 效果文件、无 `.tmp`。
- SuBing 增量快照已合入并完成真实 schema-v2→v3 adopt（`through=2026-08-27`、active60 `60/60 UNCHANGED`）。
- SuBing Stage 2 occupancy-capped restore 已达到 `CODE_COMPLETE` / `TEST_COMPLETE`：expected Daily Watch / 下一交易日无 rank1 occupancy 时，回退到上一共同已映射日并只读 Canonical 到该日（含当日），且只在 Live `trading_day` 与该日一致时合并 completed Live。下一交易日 Live 的不同 `live_contract` 不使 restore 失败；`process_completed_bar` 忽略 watermark 日之后、尚无 occupancy 的 completed Live，不把产品标成 unavailable。仓库定向 `test_subing_strategy_current_service` 与 `test_subing_strategy_runtime` 在该修复后 passed。该证据不构成 v1.9.1 Runtime 已修复、自然 Action 或通知。

## Pending Gate

- HTDY 的真实 PushPlus/微信送达，以及 D1/W1 `canonical_updated` 的自然 Event identity/evidence，仍须分别核验；不以测试、synthetic event、replay 或手工发送补证。
- SuBing 自然 Live seam evidence pending；Daily Watch V2 自然盘后 artifact pending，不以既有 V1 artifact、手工触发或回填替代。
- 一次 owner PushPlus canary 仍是独立 Gate。
- v1.9.1 的 release/main/tag 与 Runtime promotion 完成前不声明 `v1.9.1 RELEASED`。
- SuBing Candidate 的 prospective OOS 按其 protocol 独立累积，retrospective 不回填 OOS。
- 第一次自然盘后 derived 增量刷新（把效果 `through` 从 `2026-08-27` 推到最新完整交易日）仍须单独发生。
- HTDY `jm × 15m` 在 Alert 关闭期间不会发通知。2026-08-29 00:08 启用后 evaluator 已在跑，但当时为周六凌晨，焦煤夜盘已结束；下一次自然 15m completed Live bar 与 one-shot transport evidence 仍 pending，不以 canary、replay 或手工发送替代。
