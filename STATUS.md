# 当前状态

更新时间：2026-08-31

本文件只记录当前 release、production Runtime、Scope、自然 evidence 与尚未完成的 Gate。稳定产品面见 `PROJECT_SOURCE.md`，长期决策见 `DECISIONS.md`，active 依赖见 `docs/ARCHITECTURE.md`。

## Release、Runtime 与 Scope

| 项目 | 当前事实 |
|---|---|
| Release | `v1.9.4` release candidate：SuBing completed-Live trading-day continuation。前一 tag `v1.9.3@0ff83f2704e554f44b8505a744f9060288ca3440` 保留；main/tag/GitHub Release 完成前不标为 `RELEASED`。 |
| Runtime | 本机仍绑定 `/Volumes/扩展盘/guiyi-quant-runtime-v1.9.3@0ff83f27…`；`v1.9.4` 尚未 promotion。2026-08-31 只读 health 读回 Live 60/60、Alert `strategy_state=ready / 60 ready / 0 unavailable / processing_state=ok`，最近 completed Live bar 为 `2026-08-31T06:15:00Z`。 |
| Database | production Alembic 为 `20260826_0042 (head)`。当前 Rule 为 `htdy_original_15m` 与 `subing_strategy_v1`。 |
| Market Runtime Scope | `operational_products.txt` 的 60 个品种。 |
| Alert Scope | HTDY Scope 为 `jm × 15m`；SuBing `scope_products` 为 operational 60。两种 authority 不合并。两条 Rule 均 enabled，Alert Runtime marker 已 enabled，audience count 2；未发生 Scope、Rule 或 audience 变更。 |
| v1.9.4 release candidate | 以 typed identity seam 继续同一 Live physical contract 的跨交易日 completed 1m/5m/15m；不同 Live contract 仅对该产品进入 `LIVE_CONTRACT_AUTHORITY_PENDING`，由 `canonical_updated` 的 formal rollover reconciliation 处理。restart/final catch-up 复用同一 authority 且不回填 Event/通知。无 migration、Scope、transport 或策略公式变化。 |

Alert transport 为 PushPlus；provider accepted 不等于微信送达。

## 自然 evidence

- 2026-08-26 自然 after-market 于 18:05:01 开始、19:48:41 以 `passed` 完成，`attempts=1 / error_code=null`，覆盖 active60，未发生 retry。盘后只读验收确认六个当日周期 60/60 推进到 `2026-08-26T07:00:00Z`、最近完整周 60/60 为 `2026-08-21T07:00:00Z`，420 个最新 Continuous 分区物理回读与 60 个 actual-dominant 1m 正式读取均零错误；未手工启动、补跑或回填。
- 2026-08-31 只读 `subing-daily-watch/current` 读回 V2 target `2026-08-31`：60 个产品、23 long、3 short、34 excluded、0 unavailable；该日事实只支持当前 direction context，不替代 `v1.9.4` 的自然 Live seam evidence。
- SuBing Strategy V1 Stage 1 在只读 `2024-01-01..2026-08-25` 自然窗口对 AG/JM/RB/EG 得到 `89/58/48/58` 个完整 Episode，共 `253` 个；自然语料覆盖 long/short、四种 entry source、四类 exit、gap、terminal close 与 prefix/pan invariance。该证据只支持 Historical Strategy Projection，不构成自然 Live Action。
- HTDY 在既有 420-pair Scope 下形成的 6 条 D1 Event 保持 immutable；一次 W1 transport failure 后 processing 已自然恢复，但这不证明微信送达，也不替代 D1/W1 各自的自然身份核验。

## Pending Gate

- HTDY 的真实 PushPlus/微信送达，以及 D1/W1 `canonical_updated` 的自然 Event identity/evidence，仍须分别核验；不以测试、synthetic event、replay 或手工发送补证。
- SuBing `v1.9.4` 自然 Live continuation seam evidence pending；不以测试、startup replay、手工触发或回填替代。
- 一次 owner PushPlus canary 仍是独立 Gate。
- SuBing Candidate 的 prospective OOS 按其 protocol 独立累积，retrospective 不回填 OOS。
- 第一次自然盘后 derived 增量刷新仍须单独发生；2026-08-29 operator 已把效果快照 `through` 推到 `2026-08-28`，但不替代自然盘后 schema v3 status 写入。
- HTDY `jm × 15m` 下一次自然 15m completed Live bar 与 one-shot transport evidence 仍 pending（下次交易时段），不以 canary、replay 或手工发送替代。
