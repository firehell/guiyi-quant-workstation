# 当前状态

更新时间：2026-08-29

本文件只记录当前 release、production Runtime、Scope、自然 evidence 与尚未完成的 Gate。稳定产品面见 `PROJECT_SOURCE.md`，长期决策见 `DECISIONS.md`，active 依赖见 `docs/ARCHITECTURE.md`。

## Release、Runtime 与 Scope

| 项目 | 当前事实 |
|---|---|
| Release | `v1.8.8@10b92488e8a174202a90e7317110828564b5d3be`；Release PR `#242`、annotated tag peeled commit 与 GitHub Release target 一致。Release 已通过 PR `#243` 回流 `develop`。本机当前 Runtime 已离开该 tag，不等于新的 `RELEASED`。 |
| Runtime | 2026-08-29 00:08 起本机已绑定 clean/detached `/Volumes/扩展盘/guiyi-quant-runtime-develop-17a7a6598@17a7a6598b29f561f857c309b090cd0e0a64bfcd`（`develop` HEAD，含 SuBing 效果增量快照与 v2→v3 adopt 修正）。API `/api/health` 仍报告 `version=1.8.8 / readonly=true`，因 `pyproject` 未升版；身份以 `GUIYI_RUNTIME_COMMIT=17a7a6598…` 为准。旧 `/Volumes/扩展盘/guiyi-quant-runtime-v1.8.8` 保留未改。Market Runtime 保持 enabled。Alert Runtime 已 enabled：`com.guiyi.quant-alert` loaded/running，marker 为 owner-only `enabled`。只读 `/api/runtime/health` 为 `status=degraded`：DB/Redis/Live/after-market `ok`；Alert `configured_enabled=true`、HTDY `processing_state=ok`；`strategy_state=degraded`（active60 restore 后 `0 ready / 60 unavailable`）。根因已定位：restore 以 Daily Watch 下一交易日 `2026-08-31` 查 rank1 occupancy，而 MainContractMap 只覆盖到 `2026-08-28`，60/60 均为 `MAIN_CONTRACT_MAP_MISSING`。occupancy-capped restore 已进入仓库，待随 v1.9.0 部署后重启 Alert 验收。health 探针的 `would_send_notifications=false` 只表示该只读检查不发送。 |
| Database | production Alembic 为 `20260826_0042 (head)`。Rule 已原子收敛为 `htdy_original_15m` 与 `subing_strategy_v1`；旧 SuBing Rule/Event 不保留。四张空的退役 `trade_*` 表已删除。 |
| Market Runtime Scope | `operational_products.txt` 的 60 个品种。Promotion 后即时 Live 读回为 `subscribed_count=11 / phase_counts.TRADING=11 / CLOSED=49`（周六凌晨夜盘品种）。 |
| Alert Scope | HTDY 唯一 production Scope 为 `jm × 15m`（`1 symbol / 1 pair`）；SuBing 唯一 production Scope 为 `jm`。两种授权边界不合并。DB 中 2 个 Rule 均 enabled；Alert Runtime marker 已 enabled；heartbeat `enabled_rule_count=2 / scope_product_count=1`；audience count 2。通知配置结构 health 为 `ready`（parent `0700` / file `0600` / 当前用户所有），不含成员清单。 |
| v1.8.8 Runtime 能力 | N Structure 与专用于 SuBing↔N 的 Multi-Candidate Robustness 已从 active Web/API/CLI/research/candidate/code surface 删除；SuBing Strategy Stage 2、HTDY、Market、Alert 与 canonical lineage 保持。该 release 未新增 migration、未修改 Scope；当时未启用 Alert Runtime。 |
| N Structure / Multi-Candidate retirement | release 与当时的 v1.8.8 Runtime promotion 均已完成；旧 `GET /api/v1/market/research/n-structure/bands` 在 production 返回 `404`，不保留 410、feature-disabled 或兼容 reader。Git/Alembic history 只保留 lineage。 |

Alert transport 为 PushPlus；provider accepted 不等于微信送达。2026-08-26 21:33，operator 已按当次明确请求对 `last_notification_failure_at=2026-08-25T11:40:05.182316+00:00` 执行一次精确 CAS acknowledgment；读回 `notification_state=acknowledged`、`notification_acknowledged_at=2026-08-26T13:33:29.088633+00:00`。原 failure、`notification_transport_failed` 与连续失败计数保留，`event_replayed=false / notification_sent=false`；该操作不证明 provider accepted 或微信送达。

## 自然 evidence

- 2026-08-26 自然 after-market 于 18:05:01 开始、19:48:41 以 `passed` 完成，`attempts=1 / error_code=null`，覆盖 active60，未发生 retry。盘后只读验收确认六个当日周期 60/60 推进到 `2026-08-26T07:00:00Z`、最近完整周 60/60 为 `2026-08-21T07:00:00Z`，420 个最新 Continuous 分区物理回读与 60 个 actual-dominant 1m 正式读取均零错误；未手工启动、补跑或回填。
- Daily Watch V2 已进入 release/Runtime；production `current` API 已读回 V2 identity，但当前自然 V2 artifact 尚未生成并返回 `SUBING_DAILY_WATCH_NOT_GENERATED`。2026-08-26 已有 V1 segment-local artifact 保持 immutable，不转换或冒充 V2 evidence。
- SuBing Strategy V1 Stage 1 在只读 `2024-01-01..2026-08-25` 自然窗口对 AG/JM/RB/EG 得到 `89/58/48/58` 个完整 Episode，共 `253` 个；自然语料覆盖 long/short、四种 entry source、四类 exit、gap、terminal close 与 prefix/pan invariance。该证据只支持 Historical Strategy Projection，不授权 Stage 2。
- HTDY 在既有 420-pair Scope 下形成的 6 条 D1 Event 保持 immutable；一次 W1 transport failure 后 processing 已自然恢复，但这不证明微信送达，也不替代 D1/W1 各自的自然身份核验。
- 2026-08-27 v1.8.8 Runtime promotion 前，只读校验 v1.8.7 的 schema-v2 `after-market-status.json` 为 owner-only `0600`，随后按相同 SHA-256 `7a4b25554fc63e377bb53ed6d3d38f6774d6da9b2905174c33d964dfb8592023` 迁入新 Runtime 根。13:32:10 首次读回 `status=ok / subscribed_count=60 / phase_counts.TRADING=60 / last_bar_at=2026-08-27T05:32:00Z`，支持当时 Market Runtime promotion acceptance；它不构成 Alert、Strategy Action 或通知 evidence。
- 2026-08-29 develop Runtime promotion 前，只读校验当时 v1.8.8 根的 schema-v2 `after-market-status.json`（2026-08-28 自然盘后 `passed`）为 owner-only `0600`，随后按相同 SHA-256 `d5e9db417b09ae8c38f5ad63cdabeb20d89281fb42c972fac1fb83b9012e65fc` 迁入 `guiyi-quant-runtime-develop-17a7a6598`。`after_market.subing_strategy_performance` 在 health 中仍为 `null`，要等下一次自然盘后 derived 阶段写入 schema v3。该迁入不构成 derived 刷新、Alert 通知或微信送达 evidence。
- 2026-08-29 只读诊断：`restore_machine(jm)` 在 `now=Saturday` 下因 `MAIN_CONTRACT_MAP_MISSING`（目标 `2026-08-31`，occupancy 止于 `2026-08-28`）失败；`au/ag/a` 同样缺失下一交易日 occupancy。该证据支持 occupancy-capped restore，不构成 Runtime 已修复。

## 仓库验收 evidence

- Stage 2 recorded production-format shadow 使用 sealed Null Event/notification/cache/status 依赖与 committed deterministic fake readers，故意注入 1 个 source unavailable 后验证 active60 为 `59 ready / 1 bounded unavailable`、相同输入前缀的 Historical/Live Action 一致、Action 精确绑定下一实际 15m 区间第一根 1m open、跨 contract/segment identity 拒绝，以及无 Action 前缀不制造 Action。真实 read-only shadow 未获本轮授权，保持 skipped；该证据不构成 Runtime、自然 Event 或通知证据。
- SuBing active60 全历史效果代码已合入 `develop`：固定复用 `actual_dominant + 15m` Historical Projection，新增 reference-change 统计 API、产品详情底部效果与 Episode 记录、Git 外 cache warm CLI，以及 after-market schema v3 派生阶段；它晚于 v1.8.8 tag；2026-08-29 已随 `develop@17a7a6598` 进入本机 production Runtime。2026-08-28 第三次单次授权生产 warm 以 `status=passed` 完成：`planned_count=60 / completed_count=60 / failed_products=[] / cache_published_count=60 / authoritative_writes=false`；物理回读 `through=2026-08-27` 为 active60 各 1 份 schema-v2 效果文件、无 `.tmp`。
- SuBing 增量快照已合入 `develop` 并完成真实 schema-v2→v3 adopt（`through=2026-08-27`、active60 `60/60 UNCHANGED`）。2026-08-29 已将该 `develop` HEAD promote 到本机 Runtime 并启用 Alert；不声明 `RELEASED`。
- SuBing Stage 2 occupancy-capped restore 已达到 `CODE_COMPLETE` / `TEST_COMPLETE`：expected Daily Watch / 下一交易日无 rank1 occupancy 时，回退到上一共同已映射日并只读 Canonical 到该日（含当日），且只在 Live `trading_day` 与该日一致时合并 completed Live。仓库定向 `test_subing_strategy_current_service` 17 passed，相关 runtime/alert 测试 passed，ruff All checks passed，current_service mypy Success。该证据不构成 Runtime 已修复、自然 Action 或通知。

## Pending Gate

- HTDY 的真实 PushPlus/微信送达，以及 D1/W1 `canonical_updated` 的自然 Event identity/evidence，仍须分别核验；不以测试、synthetic event、replay 或手工发送补证。
- SuBing 自然 Live seam evidence pending；Daily Watch V2 自然盘后 artifact pending，不以既有 V1 artifact、手工触发或回填替代。
- SuBing Strategy V1 Stage 2 的 production migration `20260826_0042` 与 Alert enable 已完成；occupancy-capped restore 待 v1.9.0 Runtime 部署后重启 Alert 验收 ready 计数。一次 owner PushPlus canary 仍是独立 Gate。
- SuBing Candidate 的 prospective OOS 按其 protocol 独立累积，retrospective 不回填 OOS。
- SuBing 全历史效果的真实 schema-v2→v3 current-manifest 采纳（`through=2026-08-27`、active60）与含该派生阶段的本机 Runtime promotion 已完成；第一次自然盘后 derived 增量刷新（把效果 `through` 从 `2026-08-27` 推到最新完整交易日）仍须单独发生。不声明 `RELEASED`。
- HTDY `jm × 15m` 在 Alert 关闭期间不会发通知。2026-08-29 00:08 启用后 evaluator 已在跑，但当时为周六凌晨，焦煤夜盘已结束；下一次自然 15m completed Live bar 与 one-shot transport evidence 仍 pending，不以 canary、replay 或手工发送替代。
