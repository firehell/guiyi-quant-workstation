# 当前状态

更新时间：2026-08-27

本文件只记录当前 release、production Runtime、Scope、自然 evidence 与尚未完成的 Gate。稳定产品面见 `PROJECT_SOURCE.md`，长期决策见 `DECISIONS.md`，active 依赖见 `docs/ARCHITECTURE.md`。

## Release、Runtime 与 Scope

| 项目 | 当前事实 |
|---|---|
| Release | `v1.8.8@10b92488e8a174202a90e7317110828564b5d3be`；Release PR `#242`、annotated tag peeled commit 与 GitHub Release target 一致。Release 已通过 PR `#243` 回流 `develop`。 |
| Runtime | 本机已绑定 clean/detached `/Volumes/扩展盘/guiyi-quant-runtime-v1.8.8@10b92488e8a174202a90e7317110828564b5d3be`；API health 为 `version=1.8.8 / readonly=true`。2026-08-27 13:32:21 的只读读回为 `overall=passed`，DB、Redis、Live 与 after-market 均为 `ok`；Market Runtime enabled，60 个品种均处于 `TRADING` 且已订阅，重启后首根 completed Live bar 为 `2026-08-27T05:32:00Z`；Alert Runtime disabled，未运行 evaluator、未发送通知。 |
| Database | production Alembic 为 `20260826_0042 (head)`。Rule 已原子收敛为 `htdy_original_15m` 与 `subing_strategy_v1`；旧 SuBing Rule/Event 不保留。四张空的退役 `trade_*` 表已删除。 |
| Market Runtime Scope | `operational_products.txt` 的 60 个品种；2026-08-26 自然盘后成功后，当日 Live subscription 与 300 个 Live bar key 已清理。 |
| Alert Scope | HTDY 唯一 production Scope 为 `jm × 15m`（`1 symbol / 1 pair`）；SuBing 唯一 production Scope 为 `jm`。两种授权边界不合并。DB 中 2 个 Rule 均 enabled，但 Alert Runtime marker 仍 disabled；audience count 2。 |
| v1.8.8 Runtime 能力 | N Structure 与专用于 SuBing↔N 的 Multi-Candidate Robustness 已从 active Web/API/CLI/research/candidate/code surface 删除；SuBing Strategy Stage 2、HTDY、Market、Alert 与 canonical lineage 保持。该 release 未新增 migration、未修改 Scope、未启用 Alert Runtime。 |
| N Structure / Multi-Candidate retirement | release 与 Runtime promotion 均已完成；旧 `GET /api/v1/market/research/n-structure/bands` 在 production 返回 `404`，不保留 410、feature-disabled 或兼容 reader。Git/Alembic history 只保留 lineage。 |

Alert transport 为 PushPlus；provider accepted 不等于微信送达。2026-08-26 21:33，operator 已按当次明确请求对 `last_notification_failure_at=2026-08-25T11:40:05.182316+00:00` 执行一次精确 CAS acknowledgment；读回 `notification_state=acknowledged`、`notification_acknowledged_at=2026-08-26T13:33:29.088633+00:00`。原 failure、`notification_transport_failed` 与连续失败计数保留，`event_replayed=false / notification_sent=false`；该操作不证明 provider accepted 或微信送达。

## 自然 evidence

- 2026-08-26 自然 after-market 于 18:05:01 开始、19:48:41 以 `passed` 完成，`attempts=1 / error_code=null`，覆盖 active60，未发生 retry。盘后只读验收确认六个当日周期 60/60 推进到 `2026-08-26T07:00:00Z`、最近完整周 60/60 为 `2026-08-21T07:00:00Z`，420 个最新 Continuous 分区物理回读与 60 个 actual-dominant 1m 正式读取均零错误；未手工启动、补跑或回填。
- Daily Watch V2 已进入 release/Runtime；production `current` API 已读回 V2 identity，但当前自然 V2 artifact 尚未生成并返回 `SUBING_DAILY_WATCH_NOT_GENERATED`。2026-08-26 已有 V1 segment-local artifact 保持 immutable，不转换或冒充 V2 evidence。
- SuBing Strategy V1 Stage 1 在只读 `2024-01-01..2026-08-25` 自然窗口对 AG/JM/RB/EG 得到 `89/58/48/58` 个完整 Episode，共 `253` 个；自然语料覆盖 long/short、四种 entry source、四类 exit、gap、terminal close 与 prefix/pan invariance。该证据只支持 Historical Strategy Projection，不授权 Stage 2。
- HTDY 在既有 420-pair Scope 下形成的 6 条 D1 Event 保持 immutable；一次 W1 transport failure 后 processing 已自然恢复，但这不证明微信送达，也不替代 D1/W1 各自的自然身份核验。
- 2026-08-27 v1.8.8 Runtime promotion 前，只读校验 v1.8.7 的 schema-v2 `after-market-status.json` 为 owner-only `0600`，随后按相同 SHA-256 `7a4b25554fc63e377bb53ed6d3d38f6774d6da9b2905174c33d964dfb8592023` 迁入新 Runtime 根。13:32:10 首次读回 `status=ok / subscribed_count=60 / phase_counts.TRADING=60 / last_bar_at=2026-08-27T05:32:00Z`，支持本次 Market Runtime promotion acceptance；它不构成 Alert、Strategy Action 或通知 evidence。

## 仓库验收 evidence

- Stage 2 recorded production-format shadow 使用 sealed Null Event/notification/cache/status 依赖与 committed deterministic fake readers，故意注入 1 个 source unavailable 后验证 active60 为 `59 ready / 1 bounded unavailable`、相同输入前缀的 Historical/Live Action 一致、Action 精确绑定下一实际 15m 区间第一根 1m open、跨 contract/segment identity 拒绝，以及无 Action 前缀不制造 Action。真实 read-only shadow 未获本轮授权，保持 skipped；该证据不构成 Runtime、自然 Event 或通知证据。
- SuBing active60 全历史效果代码已合入 `develop`：固定复用 `actual_dominant + 15m` Historical Projection，新增 reference-change 统计 API、产品详情底部效果与 Episode 记录、Git 外 cache warm CLI，以及 after-market schema v3 派生阶段；它晚于 v1.8.8 tag，不属于当前 production Runtime。2026-08-27 首次生产 cache warm 因全历史首个 target 的上一交易日早于有效历史下界而得到 `60/60 SUBING_STRATEGY_CONTEXT_IDENTITY_INVALID`、`0 completed`；repository 随后修复该 causal lower-bound warm-up。修复后的第二次单次授权调用预检为 active60/operational 精确 `60/60`、production DB 可读、`20260826_0042 (head)`、目标根可写且初始 0 文件；正式调用耗时约 56 分钟并以 `degraded` 退出，仅报告 `a/ag completed`，其余 58 个品种均为 `SUBING_STRATEGY_SOURCE_UNAVAILABLE`。退出后物理回读仍为 cache 根不存在、0 文件、0 字节、无临时文件，因此 `cache_writes=true` 只作为 CLI 能力字段，不构成成功落盘 evidence；未重试，也未修改 authoritative data、Runtime、Scope 或通知状态。

## Pending Gate

- HTDY 的真实 PushPlus/微信送达，以及 D1/W1 `canonical_updated` 的自然 Event identity/evidence，仍须分别核验；不以测试、synthetic event、replay 或手工发送补证。
- SuBing 自然 Live seam evidence pending；Daily Watch V2 自然盘后 artifact pending，不以既有 V1 artifact、手工触发或回填替代。
- SuBing Strategy V1 Stage 2 的 release、production migration `20260826_0042` 与当前 v1.8.8 Runtime deployment 已完成；Alert Runtime 当前 disabled，因此没有自然 Strategy Action/通知 evidence。一次 owner PushPlus canary 仍是独立 Gate，本次 v1.8.8 发布未执行。
- SuBing Candidate 的 prospective OOS 按其 protocol 独立累积，retrospective 不回填 OOS。
- SuBing 全历史效果下一次 active60 Git 外 cache warm 重试，以及含该派生阶段的 Runtime promotion，仍须分别取得新的单次明确授权；代码修复与测试不自动授予任一 Gate。
