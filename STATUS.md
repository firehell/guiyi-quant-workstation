# 当前状态

更新时间：2026-09-07

本文件只记录当前 release、production Runtime、Scope、自然 evidence 与尚未完成的 Gate。稳定产品面见 `PROJECT_SOURCE.md`，长期决策见 `DECISIONS.md`，active 依赖见 `docs/ARCHITECTURE.md`；已完成版本的实现和验证过程从 Git tag、GitHub Release、PR 与 Git history 追溯。

## Release、Runtime 与 Scope

| 项目 | 当前事实 |
|---|---|
| 正式 Release | `v1.9.15@36fef03923a168145e6fd2eab023dc1d2b411ad6` 是最新正式 release；发布 tree 为 `d33efc91071995f2f04860b8916ea56f660eb903`，annotated tag object 为 `e90ad8ac67ceb5b02576f02998697cd0d288eeba`，GitHub Release 已于 2026-09-05 发布。 |
| `main` | `main@36fef03923a168145e6fd2eab023dc1d2b411ad6` 与 `v1.9.15` peeled commit 一致，对应 tree `d33efc91071995f2f04860b8916ea56f660eb903`。 |
| Runtime | 五项 launchd 已于 `2026-09-05T09:14:07Z` promotion 到 clean、detached `/Volumes/扩展盘/guiyi-quant-runtime-v1.9.15-r1@36fef03923a168145e6fd2eab023dc1d2b411ad6`，installed 与 loaded root/commit 均一致。显式及安装器内置 preflight 均以 `non_trading_interval` 通过；fresh 只读 readback 中 API/Web/Live/Alert 为 `running`，After-market 已加载、按每日 18:05 调度且 `not running`，API/Web HTTP 为 200，Runtime health 为 `ok / readonly=true`，本地隧道 health 通过。状态为 `RUNTIME_PROMOTED_V1_9_15 / NATURAL_EVIDENCE_PENDING`；该点时进程健康不构成 `RUNTIME_READY`，也不改写 2026-09-03 的自然盘后失败。 |
| 保留 Runtime root | `/Volumes/扩展盘/guiyi-quant-runtime-v1.9.14-r1@ca15456eaff988db4fe61c37657ca37302a7f977` 保持 clean、detached；其 activation marker 与 after-market 状态文件未改写。它仅为保留的 rollback 候选，本次未授权或执行 rollback。 |
| Database 与 Canonical | 最近 production 只读 readback 为 Alembic `20260903_0045`；RQData session anchor repair 已发布并保留 D1/W1 原始事实。此前全库 Canonical 快照为 8,801 个 Dataset、42,575 个分区、44,629,532 行；本次 PF2611 warm-up 的最新事实见下行。 |
| PF2611 physical warm-up | 2026-09-05 从 clean detached `v1.9.15@36fef03923a168145e6fd2eab023dc1d2b411ad6`，以 `symbol=pf`、`contract=PF2611`、`through=2026-09-04`、plan SHA-256 `7a51886988ff0508f6b3295d40665cef11ff54bc7b0b63ab79aee4fec5544f19` 完成唯一一次真实 RQData/Canonical apply：76 个目标全部 applied，blocked/failed 均为 0。只读 audit finding 为 0；MarketDataService exact physical 15m 读回 4,491 根，交易日窗口为 `2025-11-17..2026-09-04`，七周期最终共 77 个分区、89,280 行（含原已完整且未改写的 1w 分区 1 行）。Rule/Scope/Event、非目标 Catalog、pf 其他合约与 continuous 文件、MainContractMap 及五项 Runtime 的前后基线一致；状态为 `PF2611_WARMUP_APPLIED_AND_VERIFIED`。 |
| Market Runtime Scope | `operational_products.txt` 的 60 个品种。 |
| Alert Scope | `2026-09-07T06:49:43Z` 只读审计：HTDY 仅 `jm × 5m/15m`，其余59品种Scope为空；SuBing为全部60品种 × 15m，两Rule均enabled。HTDY“焦煤继续15m和5m，其他所有品种统一60m”共61对仅为目标，尚未应用。 |
| 当前 Alert health | 同轮只读审计中aggregate显示`ok`，但SuBing `error_type=evaluation_failed`，`last_failure=2026-09-07T06:45:40.440418Z`、`last_eval=2026-09-07T03:30:00Z`、`last_event=null`。聚合ok不能证明Rule健康或提醒链路修好。 |
| 当前 After-market | 只读状态为`missed`，expected为`2026-09-04`；最近运行`2026-09-06 18:05 Asia/Shanghai`以`NON_TRADING_DAY`跳过，`last_success=null`。非交易日skip不是成功盘后业务证据。 |

Alert transport 为 PushPlus；provider accepted 不等于微信送达。

## Newow 开发候选

- PR #352 已将 P6 Review 修复与 facts-only truth closure 集成到 `develop@c64b42f10b48ec8eace2390abd3254e0dd573d22` / tree `60e606cc92b33160e1fee67a35a2c60917844c89`。同 tree 的最终候选 `efcd12f1794c80ae7f6cad638d98b0acc1693380` 在全部 Review finding 关闭后完成唯一一次最终 Task 22 矩阵：backend `2274 passed, 4 skipped, 15 deselected`、engineering `74 passed`、Web `431 passed, 1 skipped`、Playwright `109 passed`，Ruff、Mypy、Alert Rule ownership、build/topology、OpenSpec `9/9`、secret 与 diff/status checks 均通过，失败与重试均为 0。初始完整 Review 按轴记录为 Standards 3 个 P2、Spec 1 个独立 P2，共 4 个唯一 finding：generation invalidation、auxiliary FIFO/LRU、tracked docs truth、Reference DOM/PNG；`74e58587b` 关闭三个 code/visual finding，`84868658e` 与 `efcd12f17` 关闭 docs truth，相应两轴 scoped re-review 均为 PASS、无新 P1/P2/P3，累计 Review ledger clean。P6 状态为 `P6_COMPLETE / PARTIAL_PRODUCT_EVIDENCE_REQUIRED`，不是完整 page parity、release 或 Runtime 能力。
- 旧任务文档迁移不升级验收：杯柄D1 clean-room并非原页面精确公式；既有18个D1/60m OOS结果与9个W1执行事实不足仍属于研究证据，产品测试不能升级为新的`OOS_PASSED`。
- 页面诊断 token、六组合评分/排序、AI copy、目标/吸筹的权威昨收与期货 owner parity、比较器 browser-final/tie golden 等 P3 原件缺口继续为 `EVIDENCE_REQUIRED`。route fixture 不能替代这些原件；`REAL_WORKSTATION_MDS_PERFORMANCE = NOT_RUN / PENDING`。
- `74e58587b` 的 Review 修复已随 PR #352 集成 develop，但尚未发布、未进入 Runtime；它不改变本文件中的 `v1.9.15` Release、现役 Runtime、SuBing Event=0、`NATURAL_EVIDENCE_PENDING` 或 G12 人工收件 Gate，也未授权 main/tag/release、Runtime promotion 或任何生产写入。

## 自然 evidence

- `2026-09-07T06:55:25Z` 对全部60品种逐一GET events，查询区间为2026-09-03至该次审计时刻，SuBing合计`total=0`。该结果与当前evaluation_failed共同说明自然Event/provider/人工收件仍未完成，不能宣称提醒链路已修好。
- 2026-09-03 的自然 after-market 为 `failed`，`attempts=1`、`error_code=LIVE_DOMINANT_MISMATCH`；这是 strict rank1/Live subscription snapshot reconciliation 未通过的真实失败，不能改写为 passed，也不能以手工、synthetic、replay 或 fallback 替代。

## Pending Gate

- `PF2611` exact plan、一次性真实 apply、只读验证及 exact `v1.9.15` 五项 Runtime promotion 已完成；当前仍为 `NATURAL_EVIDENCE_PENDING`，`RUNTIME_READY` 尚未证实。
- HTDY目标61对Scope未应用；任何Scope调整、真实数据修复、通知、main/tag/release或Runtime版本切换仍需目标/环境/范围明确的单次执行意图。本轮仓库修复不改变现役`v1.9.15@36fef039`。
- 仍须等待自然 completed SuBing 15m Event、immutable `AlertEvent` 与 one-shot PushPlus provider acceptance；不得用 synthetic、replay、backfill 或手工发送替代。
- 最终 G12 仍须由用户人工确认微信实际收到同一自然 Event；provider accepted 不能替代实际送达确认。
