# 当前状态

更新时间：2026-08-31

本文件只记录当前 release、production Runtime、Scope、自然 evidence 与尚未完成的 Gate。稳定产品面见 `PROJECT_SOURCE.md`，长期决策见 `DECISIONS.md`，active 依赖见 `docs/ARCHITECTURE.md`。

## Release、Runtime 与 Scope

| 项目 | 当前事实 |
|---|---|
| Release | `v1.9.5@e2376dc7f76e2ad85acc2d5512d3cd0c0c13af69` 已发布；main、annotated tag 与 GitHub Release 均指向该 commit。前一 tag `v1.9.4@1ee01c4d717e164eda03ec5404390fbf63573b16` 保留。 |
| Runtime | 本机已绑定 detached `/Volumes/扩展盘/guiyi-quant-runtime-v1.9.5@e2376dc7`；API、Web、Live 与 Alert 均从该 root 运行。2026-08-31 收盘后 promotion 的 Live health 为 operational `60` / subscribed `0`、phase `CLOSED:60`，这是闭市状态而非订阅失败。Alert 在 16:18 启动，restore/final catch-up 于 16:34 完成；同合约收盘后 causal continuation 使 `57` 个产品 ready，`ag`、`au`、`sc` 为 unavailable，故 Runtime 仍为 degraded。未回滚、未回填 Event、未发送通知。 |
| Database | production Alembic 为 `20260826_0042 (head)`。当前 Rule 为 `htdy_original_15m` 与 `subing_strategy_v1`。 |
| Market Runtime Scope | `operational_products.txt` 的 60 个品种。 |
| Alert Scope | HTDY Scope 为 `jm × 15m`；SuBing `scope_products` 为 operational 60。两种 authority 不合并。两条 Rule 均 enabled，Alert Runtime marker 已 enabled，audience count 2；未发生 Scope、Rule 或 audience 变更。 |
| v1.9.5 | 在 v1.9.4 的 typed continuation seam 上修复收盘后 final catch-up：只有该路径可使用 existing operational、same-day、internally single-contract 的 `post_close` completed 1m/5m/15m snapshot；冻结 decision 贯穿逐 Bar 处理。普通 Live 不获得该 authority；snapshot 不一致仍 fail-closed，不同 frozen contract 仍只进入 `LIVE_CONTRACT_AUTHORITY_PENDING`。无 migration、Scope、transport 或策略公式变化。 |

Alert transport 为 PushPlus；provider accepted 不等于微信送达。

## 自然 evidence

- 2026-08-26 自然 after-market 于 18:05:01 开始、19:48:41 以 `passed` 完成，`attempts=1 / error_code=null`，覆盖 active60，未发生 retry。盘后只读验收确认六个当日周期 60/60 推进到 `2026-08-26T07:00:00Z`、最近完整周 60/60 为 `2026-08-21T07:00:00Z`，420 个最新 Continuous 分区物理回读与 60 个 actual-dominant 1m 正式读取均零错误；未手工启动、补跑或回填。
- 2026-08-31 只读 `subing-daily-watch/current` 读回 V2 target `2026-08-31`：60 个产品、23 long、3 short、34 excluded、0 unavailable；该日事实只支持当前 direction context，不替代 `v1.9.5` 的自然 Live seam evidence。
- SuBing Strategy V1 Stage 1 在只读 `2024-01-01..2026-08-25` 自然窗口对 AG/JM/RB/EG 得到 `89/58/48/58` 个完整 Episode，共 `253` 个；自然语料覆盖 long/short、四种 entry source、四类 exit、gap、terminal close 与 prefix/pan invariance。该证据只支持 Historical Strategy Projection，不构成自然 Live Action。
- HTDY 在既有 420-pair Scope 下形成的 6 条 D1 Event 保持 immutable；一次 W1 transport failure 后 processing 已自然恢复，但这不证明微信送达，也不替代 D1/W1 各自的自然身份核验。

## Pending Gate

- HTDY 的真实 PushPlus/微信送达，以及 D1/W1 `canonical_updated` 的自然 Event identity/evidence，仍须分别核验；不以测试、synthetic event、replay 或手工发送补证。
- SuBing `v1.9.5` 自然 Live continuation seam evidence pending；收盘后启动恢复只证明 `57 ready / 3 unavailable`，不替代下一交易时段的 Live `60/60`、Alert `60 ready` 与跨交易日 cutoff 自然推进。不得以重启、回滚、回填或手工通知掩盖。
- 一次 owner PushPlus canary 仍是独立 Gate。
- SuBing Candidate 的 prospective OOS 按其 protocol 独立累积，retrospective 不回填 OOS。
- 第一次自然盘后 derived 增量刷新仍须单独发生；2026-08-29 operator 已把效果快照 `through` 推到 `2026-08-28`，但不替代自然盘后 schema v3 status 写入。
- HTDY `jm × 15m` 下一次自然 15m completed Live bar 与 one-shot transport evidence 仍 pending（下次交易时段），不以 canary、replay 或手工发送替代。
