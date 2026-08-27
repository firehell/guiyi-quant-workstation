# 当前状态

更新时间：2026-08-27

本文件只记录当前 release、production Runtime、Scope、自然 evidence 与尚未完成的 Gate。稳定产品面见 `PROJECT_SOURCE.md`，长期决策见 `DECISIONS.md`，active 依赖见 `docs/ARCHITECTURE.md`。

## Release、Runtime 与 Scope

| 项目 | 当前事实 |
|---|---|
| Release | `v1.8.7@f07f04e496687c3e14ff2895a2da89810ba6e989`；Release PR `#238`、annotated tag peeled commit 与 GitHub Release target 一致。 |
| Runtime | 本机已绑定 clean/detached `/Volumes/扩展盘/guiyi-quant-runtime-v1.8.7@f07f04e496687c3e14ff2895a2da89810ba6e989`；API health 为 `version=1.8.7 / readonly=true`。2026-08-27 13:11 的只读读回为 `overall=passed`，DB、Redis、Live 与 after-market 均为 `ok`；Market Runtime enabled，60 个品种均处于 `BREAK`，heartbeat 正常、`subscribed_count=0 / last_bar_at=null`；Alert Runtime disabled，未运行 evaluator、未发送通知。 |
| Database | production Alembic 为 `20260826_0042 (head)`。Rule 已原子收敛为 `htdy_original_15m` 与 `subing_strategy_v1`；旧 SuBing Rule/Event 不保留。四张空的退役 `trade_*` 表已删除。 |
| Market Runtime Scope | `operational_products.txt` 的 60 个品种；2026-08-26 自然盘后成功后，当日 Live subscription 与 300 个 Live bar key 已清理。 |
| Alert Scope | HTDY 唯一 production Scope 为 `jm × 15m`（`1 symbol / 1 pair`）；SuBing 唯一 production Scope 为 `jm`。两种授权边界不合并。DB 中 2 个 Rule 均 enabled，但 Alert Runtime marker 仍 disabled；audience count 2。 |
| v1.8.8 release candidate | N Structure 与专用于 SuBing↔N 的 Multi-Candidate Robustness 已从 active Web/API/CLI/research/candidate/code surface 删除；SuBing Strategy Stage 2、HTDY、Market、Alert 与 canonical lineage 保持。该 release 不新增 migration、不修改 Scope、不启用 Alert Runtime。 |
| N Structure / Multi-Candidate retirement | repository code 已实施，正随 `v1.8.8` candidate 进入 release；当前 production Runtime 仍是 `v1.8.7` exact tag，因此在 v1.8.8 Runtime promotion 前仍可能暴露旧 N Historical layer。 |

Alert transport 为 PushPlus；provider accepted 不等于微信送达。2026-08-26 21:33，operator 已按当次明确请求对 `last_notification_failure_at=2026-08-25T11:40:05.182316+00:00` 执行一次精确 CAS acknowledgment；读回 `notification_state=acknowledged`、`notification_acknowledged_at=2026-08-26T13:33:29.088633+00:00`。原 failure、`notification_transport_failed` 与连续失败计数保留，`event_replayed=false / notification_sent=false`；该操作不证明 provider accepted 或微信送达。

## 自然 evidence

- 2026-08-26 自然 after-market 于 18:05:01 开始、19:48:41 以 `passed` 完成，`attempts=1 / error_code=null`，覆盖 active60，未发生 retry。盘后只读验收确认六个当日周期 60/60 推进到 `2026-08-26T07:00:00Z`、最近完整周 60/60 为 `2026-08-21T07:00:00Z`，420 个最新 Continuous 分区物理回读与 60 个 actual-dominant 1m 正式读取均零错误；未手工启动、补跑或回填。
- Daily Watch V2 已进入 release/Runtime；production `current` API 已读回 V2 identity，但当前自然 V2 artifact 尚未生成并返回 `SUBING_DAILY_WATCH_NOT_GENERATED`。2026-08-26 已有 V1 segment-local artifact 保持 immutable，不转换或冒充 V2 evidence。
- SuBing Strategy V1 Stage 1 在只读 `2024-01-01..2026-08-25` 自然窗口对 AG/JM/RB/EG 得到 `89/58/48/58` 个完整 Episode，共 `253` 个；自然语料覆盖 long/short、四种 entry source、四类 exit、gap、terminal close 与 prefix/pan invariance。该证据只支持 Historical Strategy Projection，不授权 Stage 2。
- HTDY 在既有 420-pair Scope 下形成的 6 条 D1 Event 保持 immutable；一次 W1 transport failure 后 processing 已自然恢复，但这不证明微信送达，也不替代 D1/W1 各自的自然身份核验。
- 已部署的 `v1.8.7` 仍可能保留历史 N Historical layer；这不是本次 repository retirement 的 release、Runtime promotion 或 production 退役证据。

## 仓库验收 evidence

- Stage 2 recorded production-format shadow 使用 sealed Null Event/notification/cache/status 依赖与 committed deterministic fake readers，故意注入 1 个 source unavailable 后验证 active60 为 `59 ready / 1 bounded unavailable`、相同输入前缀的 Historical/Live Action 一致、Action 精确绑定下一实际 15m 区间第一根 1m open、跨 contract/segment identity 拒绝，以及无 Action 前缀不制造 Action。真实 read-only shadow 未获本轮授权，保持 skipped；该证据不构成 Runtime、自然 Event 或通知证据。
- SuBing active60 全历史效果代码已在 feature branch 完成：固定复用 `actual_dominant + 15m` Historical Projection，新增 reference-change 统计 API、产品详情底部效果与 Episode 记录、Git 外 cache warm CLI，以及 after-market schema v3 派生阶段。真实 active60 cache warm 与 Runtime promotion 均未执行，不构成 production 数据或运行证据。

## Pending Gate

- HTDY 的真实 PushPlus/微信送达，以及 D1/W1 `canonical_updated` 的自然 Event identity/evidence，仍须分别核验；不以测试、synthetic event、replay 或手工发送补证。
- SuBing 自然 Live seam evidence pending；Daily Watch V2 自然盘后 artifact pending，不以既有 V1 artifact、手工触发或回填替代。
- SuBing Strategy V1 Stage 2 的 release、production migration `20260826_0042` 与 v1.8.7 Runtime promotion 已完成；Alert Runtime 当前 disabled，因此没有自然 Strategy Action/通知 evidence。一次 owner PushPlus canary 仍是独立 Gate，本次 v1.8.8 发布不执行。
- v1.8.8 的 release/main/tag 与 Runtime promotion 尚待本次 release candidate 验证；两者完成前不得把 production 描述为已退役 N Historical layer。
- SuBing Candidate 的 prospective OOS 按其 protocol 独立累积，retrospective 不回填 OOS。
- SuBing 全历史效果首次 active60 Git 外 cache warm，以及含该派生阶段的 Runtime promotion，仍须分别取得单次明确授权；代码测试不自动授予任一 Gate。
