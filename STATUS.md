# 当前状态

更新时间：2026-09-07

本文件只记录当前 release、production Runtime、Scope、自然 evidence 与尚未完成的 Gate。稳定产品面见 `PROJECT_SOURCE.md`，长期决策见 `DECISIONS.md`，active 依赖见 `docs/ARCHITECTURE.md`；已完成版本的实现和验证过程从 Git tag、GitHub Release、PR 与 Git history 追溯。

## Release、Runtime 与 Scope

| 项目 | 当前事实 |
|---|---|
| 正式 Release | `v1.9.15@36fef03923a168145e6fd2eab023dc1d2b411ad6` 是最新正式 release；发布 tree 为 `d33efc91071995f2f04860b8916ea56f660eb903`，annotated tag object 为 `e90ad8ac67ceb5b02576f02998697cd0d288eeba`，GitHub Release 已于 2026-09-05 发布。 |
| `main` | `main@36fef03923a168145e6fd2eab023dc1d2b411ad6` 与 `v1.9.15` peeled commit 一致，对应 tree `d33efc91071995f2f04860b8916ea56f660eb903`。 |
| Runtime | 五项 launchd 已于 `2026-09-05T09:14:07Z` promotion 到 clean、detached `/Volumes/扩展盘/guiyi-quant-runtime-v1.9.15-r1@36fef03923a168145e6fd2eab023dc1d2b411ad6`，installed 与 loaded root/commit 均一致。显式及安装器内置 preflight 均以 `non_trading_interval` 通过；fresh 只读 readback 中 API/Web/Live/Alert 为 `running`，After-market 已加载、按每日 18:05 调度且 `not running`，API/Web HTTP 为 200，Runtime health 为 `ok / readonly=true`，本地隧道 health 通过。状态为 `RUNTIME_PROMOTED_V1_9_15 / NATURAL_EVIDENCE_PENDING`；该点时进程健康不构成 `RUNTIME_READY`，也不改写 2026-09-03 的自然盘后失败。 |
| Runtime root 核对 | 2026-09-07 只读核对：Git worktree 与文件系统均已不存在旧 `guiyi-quant-runtime-v1.9.14-r1`，不能再把它列为可直接切换的保留副本；当前正式运行副本仍为上述 `v1.9.15-r1`。本轮未删除或切换 Runtime。 |
| Database 与 Canonical | 最近 production 只读 readback 为 Alembic `20260903_0045`；RQData session anchor repair 已发布并保留 D1/W1 原始事实。此前全库 Canonical 快照为 8,801 个 Dataset、42,575 个分区、44,629,532 行；本次 PF2611 warm-up 的最新事实见下行。 |
| PF2611 physical warm-up | 2026-09-05 从 clean detached `v1.9.15@36fef03923a168145e6fd2eab023dc1d2b411ad6`，以 `symbol=pf`、`contract=PF2611`、`through=2026-09-04`、plan SHA-256 `7a51886988ff0508f6b3295d40665cef11ff54bc7b0b63ab79aee4fec5544f19` 完成唯一一次真实 RQData/Canonical apply：76 个目标全部 applied，blocked/failed 均为 0。只读 audit finding 为 0；MarketDataService exact physical 15m 读回 4,491 根，交易日窗口为 `2025-11-17..2026-09-04`，七周期最终共 77 个分区、89,280 行（含原已完整且未改写的 1w 分区 1 行）。Rule/Scope/Event、非目标 Catalog、pf 其他合约与 continuous 文件、MainContractMap 及五项 Runtime 的前后基线一致；状态为 `PF2611_WARMUP_APPLIED_AND_VERIFIED`。 |
| Market Runtime Scope | `operational_products.txt` 的 60 个品种。 |
| Alert Scope | `2026-09-07T06:49:43Z` 只读审计：HTDY 仅 `jm × 5m/15m`，其余59品种Scope为空；SuBing为全部60品种 × 15m，两Rule均enabled。HTDY“焦煤继续15m和5m，其他所有品种统一60m”共61对仅为目标，尚未应用。 |
| 当前 Alert health | 同轮只读审计中aggregate显示`ok`，但SuBing `error_type=evaluation_failed`，`last_failure=2026-09-07T06:45:40.440418Z`、`last_eval=2026-09-07T03:30:00Z`、`last_event=null`。聚合ok不能证明Rule健康或提醒链路修好。 |
| 当前 After-market | 2026-09-07 的自然 18:05 任务于 `19:30:30 Asia/Shanghai` 完成，`status=passed`、`attempts=1`、`last_successful_trading_day=2026-09-07`、`last_failure=null`；任务已退出。该成功关闭此前盘后 `missed`，但不替代苏冰历史 warm-up 或自然 Alert evidence。 |

Alert transport 为 PushPlus；provider accepted 不等于微信送达。

## 苏冰 60 品种输入恢复候选

- 当前开发候选为 `CODE_COMPLETE_EXTERNAL_GATE_PENDING`：新增只读 `runtime subing-readiness`、默认关闭的当日 Live 缺口恢复、原子数据与恢复水位提交、跨进程 Alert/recovery 互斥及日志丢失后安全重开。恢复窗口和旧触发不创建 Event 或补发；恢复后的新 completed Bar 才允许按既有 Rule 评估与 one-shot transport。苏冰公式、版本、60 × 15m Scope 与 HTDY Scope 均未改变。
- 2026-09-07 以 `as_of=2026-09-07T07:00:00Z` 对全部 60 品种做只读输入检查：Scope 全部启用，`ready_count=0`。a/ag/al/ao/ap/au/b/pf 的历史物理 15m 前缀完整；其余 52 个中，51 个有历史缺口，RS 历史输入不可读。全部 60 品种缺少当日 13:31 的 1m 和 13:45 的 15m；FG、RS、SH 另有当日缺失分钟。代码检查不能把这些生产输入变为完整。
- 针对上述 52 个阻塞合约的只读执行清单固定为 `through=2026-09-04`，初始批次 SHA-256 为 `f19338ea0d4540e69fc9f90e5c00b5141701228b0c82ad9d08cdaac1fefb1b00`，共 1,454 个 direct 和 1,948 个 derived 目标。用户于 2026-09-07 明确授权逐合约串行 production apply，并要求任一失败、partial、blocked 或 quota 立即停止且不重试。
- 该 apply 从 clean detached `v1.9.15@36fef03923a168145e6fd2eab023dc1d2b411ad6` 开始，在第 1 个 `BU2610` 返回非零/partial 后按约定停止；其余 51 个合约未开始，也未重试。失败后的只读计划证明 BU 的 1m 与 `5m/15m/30m/60m` 已全部发布，只剩 11 个 1d 与 11 个 1w direct 月目标，新的 BU plan SHA-256 为 `4db0746534645779c5c64cb3ce6fb9bbf515e92ec21607f6441a2265b167ecb6`。MarketDataService 从 Catalog/Canonical 严格读回 BU2610 physical 15m 共 4,997 根，交易日覆盖 `2025-10-16..2026-09-04`；因此苏冰历史 15m 已完整品种由 8 个增至 9 个，仍有 51 个待修复。批次整体状态保持 `PARTIAL`。
- 恢复代码的验证为后端完整测试 `2333 passed, 5 skipped, 15 deselected`，工程检查 `74 passed`，隔离 Redis `27 passed`；Mypy 133 个源文件、Ruff、前端类型/build/topology、OpenSpec `9/9`、secret 与 diff 检查通过。独立 Standards 与 Spec 复审均 PASS，旧 finding 已关闭。隔离 Redis 验证数据/水位原子性、拒绝不改旧值及幂等；不连接生产 Redis。本次 production apply 事实只以上一条的 partial 结果与只读读回为准；真实推送、release、Runtime promotion 和恢复开关启用均未执行。

## Newow 开发候选

- PR #352 已将 P6 Review 修复与 facts-only truth closure 集成到 `develop@c64b42f10b48ec8eace2390abd3254e0dd573d22` / tree `60e606cc92b33160e1fee67a35a2c60917844c89`。同 tree 的最终候选 `efcd12f1794c80ae7f6cad638d98b0acc1693380` 在全部 Review finding 关闭后完成唯一一次最终 Task 22 矩阵：backend `2274 passed, 4 skipped, 15 deselected`、engineering `74 passed`、Web `431 passed, 1 skipped`、Playwright `109 passed`，Ruff、Mypy、Alert Rule ownership、build/topology、OpenSpec `9/9`、secret 与 diff/status checks 均通过，失败与重试均为 0。初始完整 Review 按轴记录为 Standards 3 个 P2、Spec 1 个独立 P2，共 4 个唯一 finding：generation invalidation、auxiliary FIFO/LRU、tracked docs truth、Reference DOM/PNG；`74e58587b` 关闭三个 code/visual finding，`84868658e` 与 `efcd12f17` 关闭 docs truth，相应两轴 scoped re-review 均为 PASS、无新 P1/P2/P3，累计 Review ledger clean。P6 状态为 `P6_COMPLETE / PARTIAL_PRODUCT_EVIDENCE_REQUIRED`，不是完整 page parity、release 或 Runtime 能力。
- 旧任务文档迁移不升级验收：杯柄D1 clean-room并非原页面精确公式；既有18个D1/60m OOS结果与9个W1执行事实不足仍属于研究证据，产品测试不能升级为新的`OOS_PASSED`。
- 页面诊断 token、六组合评分/排序、AI copy、目标/吸筹的权威昨收与期货 owner parity、比较器 browser-final/tie golden 等 P3 原件缺口继续为 `EVIDENCE_REQUIRED`。route fixture 不能替代这些原件；`REAL_WORKSTATION_MDS_PERFORMANCE = NOT_RUN / PENDING`。
- `74e58587b` 的 Review 修复已随 PR #352 集成 develop，但尚未发布、未进入 Runtime；它不改变本文件中的 `v1.9.15` Release、现役 Runtime、SuBing Event=0、`NATURAL_EVIDENCE_PENDING` 或 G12 人工收件 Gate，也未授权 main/tag/release、Runtime promotion 或任何生产写入。

## 自然 evidence

- `2026-09-07T06:55:25Z` 对全部60品种逐一GET events，查询区间为2026-09-03至该次审计时刻，SuBing合计`total=0`。该结果与当前evaluation_failed共同说明自然Event/provider/人工收件仍未完成，不能宣称提醒链路已修好。
- 2026-09-03 的自然 after-market 为 `failed`，`attempts=1`、`error_code=LIVE_DOMINANT_MISMATCH`；这是 strict rank1/Live subscription snapshot reconciliation 未通过的真实失败，不能改写为 passed，也不能以手工、synthetic、replay 或 fallback 替代。

## Pending Gate

- 苏冰候选停在等待版本发布；历史 warm-up 当前为 `PARTIAL`，51 个合约未开始。按照 stop-on-first-failure 合同，继续 51 个合约、重试 BU 的 D1/W1、main/tag/release、exact-tag Runtime promotion、生产 Live recovery enable 均分别需要新的明确执行意图。启用恢复前必须核对 Live/Alert 为同一 exact root/version 且恢复协议同时启用；60 品种输入完整性、后续自然 Event、provider acceptance 与人工收件仍须分别验收。盘后 `missed` 已由 2026-09-07 自然 passed 关闭。
- `PF2611` exact plan、一次性真实 apply、只读验证及 exact `v1.9.15` 五项 Runtime promotion 已完成；当前仍为 `NATURAL_EVIDENCE_PENDING`，`RUNTIME_READY` 尚未证实。
- HTDY目标61对Scope未应用；任何Scope调整、真实数据修复、通知、main/tag/release或Runtime版本切换仍需目标/环境/范围明确的单次执行意图。本轮仓库修复不改变现役`v1.9.15@36fef039`。
- 仍须等待自然 completed SuBing 15m Event、immutable `AlertEvent` 与 one-shot PushPlus provider acceptance；不得用 synthetic、replay、backfill 或手工发送替代。
- 最终 G12 仍须由用户人工确认微信实际收到同一自然 Event；provider accepted 不能替代实际送达确认。
