# 当前状态

更新时间：2026-09-05

本文件只记录当前 release、production Runtime、Scope、自然 evidence 与尚未完成的 Gate。稳定产品面见 `PROJECT_SOURCE.md`，长期决策见 `DECISIONS.md`，active 依赖见 `docs/ARCHITECTURE.md`；已完成版本的实现和验证过程从 Git tag、GitHub Release、PR 与 Git history 追溯。

## Release、Runtime 与 Scope

| 项目 | 当前事实 |
|---|---|
| 正式 Release | `v1.9.15@36fef03923a168145e6fd2eab023dc1d2b411ad6` 是最新正式 release；发布 tree 为 `d33efc91071995f2f04860b8916ea56f660eb903`，annotated tag object 为 `e90ad8ac67ceb5b02576f02998697cd0d288eeba`，GitHub Release 已于 2026-09-05 发布。 |
| `main` | `main@36fef03923a168145e6fd2eab023dc1d2b411ad6` 与 `v1.9.15` peeled commit 一致，对应 tree `d33efc91071995f2f04860b8916ea56f660eb903`。 |
| Runtime | 五项 launchd 仍指向 clean、detached `/Volumes/扩展盘/guiyi-quant-runtime-v1.9.14-r1@ca15456eaff988db4fe61c37657ca37302a7f977`，尚未 promotion 到 `v1.9.15`。2026-09-05 的 fresh 只读 readback 中 API/Web/Live/Alert 为 `running`，After-market 已加载且 `not running`，当前进程 health 为 `ok`；该点时进程健康不等于自然业务验收，不构成 `RUNTIME_READY`，也不改写 2026-09-03 的自然盘后失败。 |
| Database 与 Canonical | 最近 production 只读 readback 为 Alembic `20260903_0045`；RQData session anchor repair 已发布并保留 D1/W1 原始事实。此前全库 Canonical 快照为 8,801 个 Dataset、42,575 个分区、44,629,532 行；本次 PF2611 warm-up 的最新事实见下行。 |
| PF2611 physical warm-up | 2026-09-05 从 clean detached `v1.9.15@36fef03923a168145e6fd2eab023dc1d2b411ad6`，以 `symbol=pf`、`contract=PF2611`、`through=2026-09-04`、plan SHA-256 `7a51886988ff0508f6b3295d40665cef11ff54bc7b0b63ab79aee4fec5544f19` 完成唯一一次真实 RQData/Canonical apply：76 个目标全部 applied，blocked/failed 均为 0。只读 audit finding 为 0；MarketDataService exact physical 15m 读回 4,491 根，交易日窗口为 `2025-11-17..2026-09-04`，七周期最终共 77 个分区、89,280 行（含原已完整且未改写的 1w 分区 1 行）。Rule/Scope/Event、非目标 Catalog、pf 其他合约与 continuous 文件、MainContractMap 及五项 Runtime 的前后基线一致；状态为 `PF2611_WARMUP_APPLIED_AND_VERIFIED`。 |
| Market Runtime Scope | `operational_products.txt` 的 60 个品种。 |
| Alert Scope | HTDY 为 `jm × 15m`；SuBing 为 execution-time operational 60 个品种 × 15m，Scope hash `ce1daca77aeb1abe134806b67aebd96b2c35db3ba82aa10af58f6e5a2e4f5fa2`。两条 Rule 均为 enabled；SuBing Event 为 0。 |

Alert transport 为 PushPlus；provider accepted 不等于微信送达。

## 自然 evidence

- 2026-09-03 的自然 after-market 为 `failed`，`attempts=1`、`error_code=LIVE_DOMINANT_MISMATCH`；这是 strict rank1/Live subscription snapshot reconciliation 未通过的真实失败，不能改写为 passed，也不能以手工、synthetic、replay 或 fallback 替代。

## Pending Gate

- `PF2611` exact plan、一次性真实 apply 与只读验证已完成；将五项服务 promotion 到 exact `v1.9.15` Runtime 仍待独立明确授权，尚未执行。
- 仍须等待自然 completed SuBing 15m Event、immutable `AlertEvent` 与 one-shot PushPlus provider acceptance；不得用 synthetic、replay、backfill 或手工发送替代。
- 最终 G12 仍须由用户人工确认微信实际收到同一自然 Event；provider accepted 不能替代实际送达确认。
