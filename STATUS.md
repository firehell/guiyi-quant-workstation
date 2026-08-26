# 当前状态

更新时间：2026-08-26

本文件只记录当前 release、production Runtime、Scope、自然 evidence 与尚未完成的 Gate。稳定产品面见 `PROJECT_SOURCE.md`，长期决策见 `DECISIONS.md`，active 依赖见 `docs/ARCHITECTURE.md`。

## Release、Runtime 与 Scope

| 项目 | 当前事实 |
|---|---|
| Release | `v1.8.5@8af22bd65aa182313ee1108a23d975606d215495`；Release PR `#224`、annotated tag peeled commit 与 GitHub Release target 一致。 |
| Runtime | 本机五个 launchd label 绑定 clean/detached `/Volumes/扩展盘/guiyi-quant-runtime-v1.8.5@8af22bd65aa182313ee1108a23d975606d215495`；API health 为 `version=1.8.5 / readonly=true`。DB、Redis 与 Live 为 `ok`；after-market health 因新 Runtime 根未导入旧状态文件而为 `pending`。 |
| Database | production Alembic 为 `20260826_0041 (head)`；四张空的退役 `trade_*` 表已删除。 |
| Market Runtime Scope | `operational_products.txt` 的 60 个品种；Live 当前处于 `BREAK`。 |
| Alert Scope | HTDY 唯一 production Scope 为 `jm × 15m`（`1 symbol / 1 pair`）；SuBing 保持 1 个 product-level Scope。两种授权边界不合并。当前有 2 个 enabled Rule、audience count 2。 |
| Develop-only | SuBing Strategy V1 Stage 1 已由 PR `#225` 与修正 PR `#226` 合入 `develop`；仍未进入 release、Runtime、Alert Rule、Scope 或通知路径。其 Design Spec 仍为 design-only，written-spec review pending，且不构成任何实现或外部操作授权。 |

Alert transport 为 PushPlus；provider accepted 不等于微信送达。Runtime observation 保留一次精确失败 CAS acknowledgment 能力，当前 acknowledgment 为 `null`，未执行重放、补发或真实通知。当前 `degraded` 仅来自 after-market `pending` 与保留的 `notification_transport_failed`。

## 自然 evidence

- 2026-08-25 自然 after-market 于 18:05:02 开始、19:40:05 以 `passed` 完成，`attempts=1`，覆盖 active60；该证据不因 Runtime 封装变化重复采集，也不回填到新 Runtime 状态文件。
- Daily Watch V2 已进入 release/Runtime；production `current` API 已读回 V2 identity，但当前自然 V2 artifact 尚未生成并返回 `SUBING_DAILY_WATCH_NOT_GENERATED`。2026-08-26 已有 V1 segment-local artifact 保持 immutable，不转换或冒充 V2 evidence。
- SuBing Strategy V1 Stage 1 在只读 `2024-01-01..2026-08-25` 自然窗口对 AG/JM/RB/EG 得到 `89/58/48/58` 个完整 Episode，共 `253` 个；自然语料覆盖 long/short、四种 entry source、四类 exit、gap、terminal close 与 prefix/pan invariance。该证据只支持 Historical Strategy Projection，不授权 Stage 2。
- HTDY 在既有 420-pair Scope 下形成的 6 条 D1 Event 保持 immutable；一次 W1 transport failure 后 processing 已自然恢复，但这不证明微信送达，也不替代 D1/W1 各自的自然身份核验。
- N Structure 已在真实 AU `actual_dominant + 5m` Canonical 页面完成只读 API/Web 验收并随 v1.8.5 进入 Runtime；它仍是可选 Historical 图层，不是独立产品、第五个 Overlay、Alert 或 Runtime evaluator。

## Pending Gate

- HTDY 的真实 PushPlus/微信送达，以及 D1/W1 `canonical_updated` 的自然 Event identity/evidence，仍须分别核验；不以测试、synthetic event、replay 或手工发送补证。
- SuBing 自然 Live seam evidence pending；Daily Watch V2 自然盘后 artifact pending，不以既有 V1 artifact、手工触发或回填替代。
- SuBing Strategy V1 Design Spec 的 written-spec review pending；该文档不授权 implementation、migration、Rule、Scope、通知或 Runtime。
- SuBing、N 与 JDJ Candidate 的 prospective OOS 按各自 protocol 独立累积，retrospective 不回填 OOS。
- Production notification acknowledgment 尚未执行；只有新的范围明确执行意图才能对当前精确失败发起一次 CAS acknowledgment，且不重放、不补发、不证明 provider accepted 或微信送达。
