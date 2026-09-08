# 当前状态

更新时间：2026-09-08

本文件只记录当前 release、production Runtime、Scope、自然 evidence 与尚未完成的 Gate。稳定产品面见 `PROJECT_SOURCE.md`，长期决策见 `DECISIONS.md`，active 依赖见 `docs/ARCHITECTURE.md`；已完成版本的实现和验证过程从 Git tag、GitHub Release、PR 与 Git history 追溯。

## Release、Runtime 与 Scope

| 项目 | 当前事实 |
|---|---|
| 正式 Release | `v1.9.15@36fef03923a168145e6fd2eab023dc1d2b411ad6` 是最新正式 release；发布 tree 为 `d33efc91071995f2f04860b8916ea56f660eb903`，annotated tag object 为 `e90ad8ac67ceb5b02576f02998697cd0d288eeba`，GitHub Release 已于 2026-09-05 发布。 |
| `main` | `main@36fef03923a168145e6fd2eab023dc1d2b411ad6` 与 `v1.9.15` peeled commit 一致，对应 tree `d33efc91071995f2f04860b8916ea56f660eb903`。 |
| Runtime | 五项 launchd 已于 `2026-09-05T09:14:07Z` promotion 到 clean、detached `/Volumes/扩展盘/guiyi-quant-runtime-v1.9.15-r1@36fef03923a168145e6fd2eab023dc1d2b411ad6`，installed 与 loaded root/commit 均一致。显式及安装器内置 preflight 均以 `non_trading_interval` 通过。2026-09-08 最终只读核对中五项服务仍指向该 exact root/commit，API/Web 为 200，Runtime health 为 `ok / readonly=true`，本地隧道通过；同一 exact Runtime 已完成自然 SuBing 15m Event、one-shot PushPlus provider acceptance 及 Owner 微信收件确认，因此 v1.9.15 发布验收状态为 `RUNTIME_READY / SUBING_NATURAL_CLOSURE_COMPLETE`。该状态不改写 2026-09-03 的自然盘后失败，也不代表 60 品种当前输入全部完整。 |
| Runtime root 核对 | 2026-09-07 只读核对：Git worktree 与文件系统均已不存在旧 `guiyi-quant-runtime-v1.9.14-r1`，不能再把它列为可直接切换的保留副本；当前正式运行副本仍为上述 `v1.9.15-r1`。本轮未删除或切换 Runtime。 |
| Database 与 Canonical | 最近 production 只读 readback 为 Alembic `20260903_0045`；RQData session anchor repair 已发布并保留 D1/W1 原始事实。此前全库 Canonical 快照为 8,801 个 Dataset、42,575 个分区、44,629,532 行；该快照不是当前全库总量；PF2611 与本轮 60 合约历史 15m 的最新验收分别见下行及后文。 |
| PF2611 physical warm-up | 2026-09-05 从 clean detached `v1.9.15@36fef03923a168145e6fd2eab023dc1d2b411ad6`，以 `symbol=pf`、`contract=PF2611`、`through=2026-09-04`、plan SHA-256 `7a51886988ff0508f6b3295d40665cef11ff54bc7b0b63ab79aee4fec5544f19` 完成唯一一次真实 RQData/Canonical apply：76 个目标全部 applied，blocked/failed 均为 0。只读 audit finding 为 0；MarketDataService exact physical 15m 读回 4,491 根，交易日窗口为 `2025-11-17..2026-09-04`，七周期最终共 77 个分区、89,280 行（含原已完整且未改写的 1w 分区 1 行）。Rule/Scope/Event、非目标 Catalog、pf 其他合约与 continuous 文件、MainContractMap 及五项 Runtime 的前后基线一致；状态为 `PF2611_WARMUP_APPLIED_AND_VERIFIED`。 |
| Market Runtime Scope | `operational_products.txt` 的 60 个品种。 |
| Alert Scope | `2026-09-07T06:49:43Z` 只读审计：HTDY 仅 `jm × 5m/15m`，其余59品种Scope为空；SuBing为全部60品种 × 15m，两Rule均enabled。HTDY“焦煤继续15m和5m，其他所有品种统一60m”共61对仅为目标，尚未应用。 |
| 当前 Alert health | `2026-09-08T08:05:00 Asia/Shanghai` 从现役 exact `v1.9.15` `/api/runtime/health` 只读核对：Alert aggregate 与 processing 均为 `ok`，notification 为 `provider_accepted`；SuBing `last_eval=2026-09-08T02:30:00 Asia/Shanghai`、`last_event=2026-09-08T02:15:04.503024 Asia/Shanghai`，当前 `error_type=null`。`last_failure=2026-09-08T01:30:04.607822 Asia/Shanghai` 仍按历史 health 保留，不是当前错误；此前 `00:00` 的 `evaluation_failed` 快照同样不回写。该恢复是自然后续评估结果，本轮未重启 Runtime、未写 acknowledgment、未改 Scope、未补发通知。当前 Rule 已恢复不等于逐品种 readiness 已证明 60/60 ready。 |
| 当前 After-market | 2026-09-07 的自然 18:05 任务于 `19:30:30 Asia/Shanghai` 完成，`status=passed`、`attempts=1`、`last_successful_trading_day=2026-09-07`、`last_failure=null`；任务已退出。该成功关闭此前盘后 `missed`，但不替代苏冰历史 warm-up 或自然 Alert evidence。 |

Alert transport 为 PushPlus；provider accepted 不等于微信送达。

## 苏冰 60 品种输入恢复候选

- 当前开发候选为 `CODE_COMPLETE_EXTERNAL_GATE_PENDING`：新增只读 `runtime subing-readiness`、默认关闭的当日 Live 缺口恢复、原子数据与恢复水位提交、跨进程 Alert/recovery 互斥及日志丢失后安全重开。恢复窗口和旧触发不创建 Event 或补发；恢复后的新 completed Bar 才允许按既有 Rule 评估与 one-shot transport。苏冰公式、版本、60 × 15m Scope 与 HTDY Scope 均未改变。
- 2026-09-07 以 `as_of=2026-09-07T07:00:00Z` 对全部 60 品种做只读输入检查：Scope 全部启用，`ready_count=0`。a/ag/al/ao/ap/au/b/pf 的历史物理 15m 前缀完整；其余 52 个中，51 个有历史缺口，RS 历史输入不可读。全部 60 品种缺少当日 13:31 的 1m 和 13:45 的 15m；FG、RS、SH 另有当日缺失分钟。代码检查不能把这些生产输入变为完整。
- 针对上述 52 个阻塞合约的只读执行清单固定为 `through=2026-09-04`，初始批次 SHA-256 为 `f19338ea0d4540e69fc9f90e5c00b5141701228b0c82ad9d08cdaac1fefb1b00`，共 1,454 个 direct 和 1,948 个 derived 目标。用户于 2026-09-07 明确授权逐合约串行 production apply，并要求任一失败、partial、blocked 或 quota 立即停止且不重试。
- 该 apply 从 clean detached `v1.9.15@36fef03923a168145e6fd2eab023dc1d2b411ad6` 开始，在第 1 个 `BU2610` 返回非零/partial 后按约定停止；其余 51 个合约未开始，也未重试。失败后的只读计划证明 BU 的 1m 与 `5m/15m/30m/60m` 已全部发布，只剩 11 个 1d 与 11 个 1w direct 月目标，新的 BU plan SHA-256 为 `4db0746534645779c5c64cb3ce6fb9bbf515e92ec21607f6441a2265b167ecb6`。MarketDataService 从 Catalog/Canonical 严格读回 BU2610 physical 15m 共 4,997 根，交易日覆盖 `2025-10-16..2026-09-04`；因此苏冰历史 15m 已完整品种由 8 个增至 9 个，仍有 51 个待修复。批次整体状态保持 `PARTIAL`。
- 停止后为剩余 51 个合约重新生成了零 provider 请求、零写入的只读计划：1,421 个 direct、1,904 个 derived 目标，预计 3,983,204 根 Bar，批次 SHA-256 为 `93b913e561f6a7b3bfc8c09ba15ad90948b54f45aea81b3cce436fca988aee88`。后续在 `develop@7ba649ad1b79e3fda765f49e30a1b8d7e208810a` 以同一 `through` 重新读取 Catalog，51 个唯一计划保持 1,421 个 direct、1,904 个 derived 和 3,983,204 根 Bar；HC2701、RB2701 的 2026-09 期望窗口由 4 个交易日扩为 5 个交易日，缺口数量与范围未扩大，故使用新 hash。
- 该批次第 1 个 `BZ2610` 以 hash `4f87127f5e85058d7ea6e236754a921a0d64402813e12ff56340fab4fd443c60` 返回 `partial`，因此按合同停止，未启动余下 50 个合约，也未重试。其结果为 55 个目标 applied、8 个 blocked、1 个 failed；失败为 `contract:bz:BZ2610:1w:2025-10` 的 `MARKET_DATA_CONTRACT_INVALID`。只读 MarketDataService/Catalog 验证确认 BZ2610 physical 15m 已完整：4,790 根，交易日 `2025-10-29..2026-09-04`，`coverage_exact=true`。苏冰历史物理 15m 完整度因此从 9/60 提升到 10/60，仍有 50/60 待修复；日内 Live 缺口保持未解决。
- 用户随后授权对 BZ 失败做只读诊断、最小代码修复并在修复后自动继续。RQData 诊断显示 2025-10 首周三个零成交日为 O/H/L=`0`、正 close 的占位；`develop@a2a57d23a4b97aabcaa1344653155b5d3517f545` 将其与原有全空占位一并规范为同一行 close，同时拒绝部分零价和任何非零成交的全零 O/H/L。数据基础回归 `687 passed, 1 skipped`、Mypy 133 源文件、Ruff 与独立 Standards re-review 均通过；完整后端回归为 `2339 passed, 19 skipped, 1 error`，唯一 error 是环境未设 `GUIYI_ISOLATED_MIGRATION_DATABASE_URL` 的隔离 Alembic fixture。
- 修复后的 BZ hash `6472e57ae7ee6dd60b2a9637f78fac9d1ff69f6f2e0d85404132ea84ebbe1208` 只剩 22 个 D1/W1 direct 目标；其唯一一次 apply 再次返回 `partial`（10 applied、3 blocked、1 failed），失败为 `contract:bz:BZ2610:1w:2026-04` 的 `RQDATA_ZERO_OHL_INVALID`。完整周源窗口的只读 RQData 复现确认 `2026-03-20` 返回 `volume=2`、O/H/L 全为 `0`、`close=7811`；这是非零成交但价格字段无效的交易所日行情，不能用 close、settlement 或 1m 代替。该轮因此停止，当时历史 15m 完整度为 10/60；此后的限定频率批次已独立完成，最新结果见下节。BZ 的异常 D1/W1 未被改写。
- 恢复代码的验证为后端完整测试 `2333 passed, 5 skipped, 15 deselected`，工程检查 `74 passed`，隔离 Redis `27 passed`；Mypy 133 个源文件、Ruff、前端类型/build/topology、OpenSpec `9/9`、secret 与 diff 检查通过。独立 Standards 与 Spec 复审均 PASS，旧 finding 已关闭。隔离 Redis 验证数据/水位原子性、拒绝不改旧值及幂等；不连接生产 Redis。上述旧轮次 production apply 为 partial；后续限定频率批次的最新事实见下节。上述恢复任务未执行真实推送、release、Runtime promotion 或恢复开关启用。

## 苏冰历史物理 15m 完整度（2026-09-08 最终验收）

- 状态：`COMPLETED / 60_OF_60_HISTORICAL_PHYSICAL_15M_VERIFIED`。固定 `through=2026-09-04`；原有 10 个合约仅复核，本轮授权的 50 个合约全部串行 apply 成功，`partial=0 / failed=0 / blocked=0 / unstarted=0`，未重试。
- 执行代码为已 Review、已集成并推送的 `ac9843f115806a08c3f7f4c914dc0500224c69c0`：HistoricalDataManager/Catalog 权威入口新增显式 `--frequency 15m`，仅维护同物理合约 `1m` 基础与 `15m` 派生；省略参数仍为原七周期合同。保留 fresh hash、maintenance lock、原子发布及失败停止；没有新增 consumer resolver，也未修改 BU/BZ 异常日线。
- 50 个 fresh 逐合约计划共 `465 direct 1m + 465 derived 15m`，全部 `930 applied`；计划 expected bars 合计 `3,130,016`，是计划目标行数，不是最终 15m 根数或净新增行数。批次 SHA-256 为 `c181453a449c95ec711ac80cfee365ae6cec0cb3e6f89fa89572b6458a2e31c1`；每次 apply 前重新只读生成该合约计划并核对 hash，apply 内持锁再核对，未复用旧七周期计划。
- 最终独立全量读回为 `2026-09-08 02:27:44..02:28:20 Asia/Shanghai`，执行 `develop@caebf92a6df04f85680b5c38a13f5c6724e4979b`；并发集成只改 Newow 等无关入口，warm-up 调用链相对上述已审代码未变。生产数据根为 `/Volumes/扩展盘/guiyi-quant-workstation/data/parquet/canonical`。60 个合约合计 `259,183` 根 physical 15m、`640` 个相关月分区；每项 `coverage_exact=true`、实际根数等于预期。
- 只读事务通过 MarketDataService 查询上市日至固定 through 的物理 15m；逐项核对 request identity、Catalog DatasetKey，以及 Canonical URI、schema、row_count、coverage 和 `(bar_end, trading_day)` 完整前缀。下表统一截止交易日为 `2026-09-04`，所有 effective through 均未缩短。临时逐合约计划/apply/readback 在 `/private/tmp/subing-physical15m-20260907/`；最终 `verify-last-run.json` SHA-256 为 `2d4afc3f714538a94758cc7af9e65e5618c282f35e6f8bfafecdbde9de1089d3`，这些文件是本次 evidence，不能代替未来 fresh plan 或重新验收。
- 代码验证：数据基础模块 `699 passed, 1 skipped`；相关模块 `253 passed`；Mypy `51` 源文件、Ruff、OpenSpec `9/9`、工程 hygiene/canonical `18 passed`、secret 与 diff 检查通过。独立 Standards、Spec 与串行执行安全复审 clean。本轮未重跑完整后端或隔离 Alembic fixture。历史验收不修改 Alert Rule、Scope、Event、Redis Live、PushPlus 或 Runtime；没有 main merge、tag、release、Runtime promotion 或真实发送，也不以该验收改写既有自然收件闭环。

| Catalog DatasetKey | 本轮 apply | 15m 实际 / 预期 | 首交易日 | 月分区 | Catalog / Canonical 只读结果 |
|---|---|---:|---|---:|---|
| `contract:a:A2611:15m` | 原已完整，仅复核 | 4,491 / 4,491 | 2025-11-17 | 11 | VERIFIED / exact |
| `contract:ag:AG2610:15m` | 原已完整，仅复核 | 7,993 / 7,993 | 2025-10-16 | 12 | VERIFIED / exact |
| `contract:al:AL2610:15m` | 原已完整，仅复核 | 6,709 / 6,709 | 2025-10-16 | 12 | VERIFIED / exact |
| `contract:ao:AO2610:15m` | 原已完整，仅复核 | 6,709 / 6,709 | 2025-10-16 | 12 | VERIFIED / exact |
| `contract:ap:AP2701:15m` | 原已完整，仅复核 | 2,310 / 2,310 | 2026-01-19 | 9 | VERIFIED / exact |
| `contract:au:AU2610:15m` | 原已完整，仅复核 | 8,563 / 8,563 | 2025-09-16 | 13 | VERIFIED / exact |
| `contract:b:B2611:15m` | 原已完整，仅复核 | 4,491 / 4,491 | 2025-11-17 | 11 | VERIFIED / exact |
| `contract:bu:BU2610:15m` | 原已完整，仅复核 | 4,997 / 4,997 | 2025-10-16 | 12 | VERIFIED / exact |
| `contract:bz:BZ2610:15m` | 原已完整，仅复核 | 4,790 / 4,790 | 2025-10-29 | 12 | VERIFIED / exact |
| `contract:pf:PF2611:15m` | 原已完整，仅复核 | 4,491 / 4,491 | 2025-11-17 | 11 | VERIFIED / exact |
| `contract:c:C2611:15m` | 成功 | 4,491 / 4,491 | 2025-11-17 | 11 | VERIFIED / exact |
| `contract:cf:CF2701:15m` | 成功 | 3,510 / 3,510 | 2026-01-19 | 9 | VERIFIED / exact |
| `contract:cj:CJ2701:15m` | 成功 | 2,310 / 2,310 | 2026-01-19 | 9 | VERIFIED / exact |
| `contract:cu:CU2610:15m` | 成功 | 6,709 / 6,709 | 2025-10-16 | 12 | VERIFIED / exact |
| `contract:eb:EB2610:15m` | 成功 | 4,790 / 4,790 | 2025-10-29 | 12 | VERIFIED / exact |
| `contract:ec:EC2610:15m` | 成功 | 3,165 / 3,165 | 2025-10-28 | 12 | VERIFIED / exact |
| `contract:eg:EG2610:15m` | 成功 | 4,790 / 4,790 | 2025-10-29 | 12 | VERIFIED / exact |
| `contract:fg:FG2701:15m` | 成功 | 3,510 / 3,510 | 2026-01-19 | 9 | VERIFIED / exact |
| `contract:fu:FU2611:15m` | 成功 | 4,721 / 4,721 | 2025-11-03 | 11 | VERIFIED / exact |
| `contract:hc:HC2701:15m` | 成功 | 3,533 / 3,533 | 2026-01-16 | 9 | VERIFIED / exact |
| `contract:i:I2701:15m` | 成功 | 3,510 / 3,510 | 2026-01-19 | 9 | VERIFIED / exact |
| `contract:j:J2701:15m` | 成功 | 3,510 / 3,510 | 2026-01-19 | 9 | VERIFIED / exact |
| `contract:jd:JD2610:15m` | 成功 | 3,150 / 3,150 | 2025-10-29 | 12 | VERIFIED / exact |
| `contract:jm:JM2701:15m` | 成功 | 3,510 / 3,510 | 2026-01-19 | 9 | VERIFIED / exact |
| `contract:l:L2701:15m` | 成功 | 3,510 / 3,510 | 2026-01-19 | 9 | VERIFIED / exact |
| `contract:lc:LC2701:15m` | 成功 | 2,310 / 2,310 | 2026-01-19 | 9 | VERIFIED / exact |
| `contract:lh:LH2611:15m` | 成功 | 2,850 / 2,850 | 2025-11-26 | 11 | VERIFIED / exact |
| `contract:m:M2701:15m` | 成功 | 3,510 / 3,510 | 2026-01-19 | 9 | VERIFIED / exact |
| `contract:ma:MA2610:15m` | 成功 | 4,882 / 4,882 | 2025-10-23 | 12 | VERIFIED / exact |
| `contract:ni:NI2610:15m` | 成功 | 6,709 / 6,709 | 2025-10-16 | 12 | VERIFIED / exact |
| `contract:oi:OI2611:15m` | 成功 | 4,491 / 4,491 | 2025-11-17 | 11 | VERIFIED / exact |
| `contract:p:P2701:15m` | 成功 | 3,510 / 3,510 | 2026-01-19 | 9 | VERIFIED / exact |
| `contract:pb:PB2610:15m` | 成功 | 6,709 / 6,709 | 2025-10-16 | 12 | VERIFIED / exact |
| `contract:pd:PD2610:15m` | 成功 | 2,835 / 2,835 | 2025-11-27 | 11 | VERIFIED / exact |
| `contract:pg:PG2610:15m` | 成功 | 4,790 / 4,790 | 2025-10-29 | 12 | VERIFIED / exact |
| `contract:pk:PK2611:15m` | 成功 | 2,955 / 2,955 | 2025-11-17 | 11 | VERIFIED / exact |
| `contract:pl:PL2611:15m` | 成功 | 4,491 / 4,491 | 2025-11-17 | 11 | VERIFIED / exact |
| `contract:pp:PP2701:15m` | 成功 | 3,510 / 3,510 | 2026-01-19 | 9 | VERIFIED / exact |
| `contract:pr:PR2611:15m` | 成功 | 4,491 / 4,491 | 2025-11-17 | 11 | VERIFIED / exact |
| `contract:ps:PS2611:15m` | 成功 | 2,955 / 2,955 | 2025-11-17 | 11 | VERIFIED / exact |
| `contract:pt:PT2610:15m` | 成功 | 2,835 / 2,835 | 2025-11-27 | 11 | VERIFIED / exact |
| `contract:px:PX2611:15m` | 成功 | 4,491 / 4,491 | 2025-11-17 | 11 | VERIFIED / exact |
| `contract:rb:RB2701:15m` | 成功 | 3,533 / 3,533 | 2026-01-16 | 9 | VERIFIED / exact |
| `contract:rm:RM2611:15m` | 成功 | 4,491 / 4,491 | 2025-11-17 | 11 | VERIFIED / exact |
| `contract:rs:RS2609:15m` | 成功 | 3,540 / 3,540 | 2025-09-15 | 13 | VERIFIED / exact |
| `contract:ru:RU2701:15m` | 成功 | 3,533 / 3,533 | 2026-01-16 | 9 | VERIFIED / exact |
| `contract:sa:SA2701:15m` | 成功 | 3,510 / 3,510 | 2026-01-19 | 9 | VERIFIED / exact |
| `contract:sc:SC2610:15m` | 成功 | 8,156 / 8,156 | 2025-10-09 | 12 | VERIFIED / exact |
| `contract:sf:SF2611:15m` | 成功 | 2,955 / 2,955 | 2025-11-17 | 11 | VERIFIED / exact |
| `contract:sh:SH2611:15m` | 成功 | 4,491 / 4,491 | 2025-11-17 | 11 | VERIFIED / exact |
| `contract:si:SI2611:15m` | 成功 | 2,955 / 2,955 | 2025-11-17 | 11 | VERIFIED / exact |
| `contract:sm:SM2611:15m` | 成功 | 2,955 / 2,955 | 2025-11-17 | 11 | VERIFIED / exact |
| `contract:sn:SN2610:15m` | 成功 | 6,709 / 6,709 | 2025-10-16 | 12 | VERIFIED / exact |
| `contract:sr:SR2701:15m` | 成功 | 3,510 / 3,510 | 2026-01-19 | 9 | VERIFIED / exact |
| `contract:ss:SS2610:15m` | 成功 | 6,709 / 6,709 | 2025-10-16 | 12 | VERIFIED / exact |
| `contract:ta:TA2701:15m` | 成功 | 3,510 / 3,510 | 2026-01-19 | 9 | VERIFIED / exact |
| `contract:ur:UR2701:15m` | 成功 | 2,310 / 2,310 | 2026-01-19 | 9 | VERIFIED / exact |
| `contract:v:V2701:15m` | 成功 | 3,510 / 3,510 | 2026-01-19 | 9 | VERIFIED / exact |
| `contract:y:Y2701:15m` | 成功 | 3,510 / 3,510 | 2026-01-19 | 9 | VERIFIED / exact |
| `contract:zn:ZN2610:15m` | 成功 | 6,709 / 6,709 | 2025-10-16 | 12 | VERIFIED / exact |

## Newow 开发候选

- PR #352 已将 P6 Review 修复与 facts-only truth closure 集成到 `develop@c64b42f10b48ec8eace2390abd3254e0dd573d22` / tree `60e606cc92b33160e1fee67a35a2c60917844c89`。同 tree 的最终候选 `efcd12f1794c80ae7f6cad638d98b0acc1693380` 在全部 Review finding 关闭后完成唯一一次最终 Task 22 矩阵：backend `2274 passed, 4 skipped, 15 deselected`、engineering `74 passed`、Web `431 passed, 1 skipped`、Playwright `109 passed`，Ruff、Mypy、Alert Rule ownership、build/topology、OpenSpec `9/9`、secret 与 diff/status checks 均通过，失败与重试均为 0。初始完整 Review 按轴记录为 Standards 3 个 P2、Spec 1 个独立 P2，共 4 个唯一 finding：generation invalidation、auxiliary FIFO/LRU、tracked docs truth、Reference DOM/PNG；`74e58587b` 关闭三个 code/visual finding，`84868658e` 与 `efcd12f17` 关闭 docs truth，相应两轴 scoped re-review 均为 PASS、无新 P1/P2/P3，累计 Review ledger clean。P6 状态为 `P6_COMPLETE / PARTIAL_PRODUCT_EVIDENCE_REQUIRED`，不是完整 page parity、release 或 Runtime 能力。
- 旧任务文档迁移不升级验收：杯柄D1 clean-room并非原页面精确公式；既有18个D1/60m OOS结果与9个W1执行事实不足仍属于研究证据，产品测试不能升级为新的`OOS_PASSED`。
- 页面诊断 token、六组合评分/排序、AI copy、目标/吸筹的权威昨收与期货 owner parity、比较器 browser-final/tie golden 等 P3 原件缺口继续为 `EVIDENCE_REQUIRED`。route fixture 不能替代这些原件；`REAL_WORKSTATION_MDS_PERFORMANCE = NOT_RUN / PENDING`。
- `74e58587b` 的 Review 修复已随 PR #352 集成 develop，但尚未发布、未进入 Runtime；它不改变本文件中的 `v1.9.15` Release、现役 Runtime 或已完成的 SuBing 自然收件闭环，也不替代独立的历史输入完整度验收。它未授权 main/tag/release、Runtime promotion 或任何生产写入。

## 自然 evidence

- `2026-09-07T06:55:25Z` 对全部 60 品种逐一 GET events，查询区间为 2026-09-03 至该次审计时刻，SuBing 合计 `total=0`。该历史快照只证明当时自然 Event/provider/人工收件尚未完成；后续发生的自然闭环见下文，不得回写或删除这个早期事实。
- 2026-09-03 的自然 after-market 为 `failed`，`attempts=1`、`error_code=LIVE_DOMINANT_MISMATCH`；这是 strict rank1/Live subscription snapshot reconciliation 未通过的真实失败，不能改写为 passed，也不能以手工、synthetic、replay 或 fallback 替代。
- 2026-09-07 夜盘后，exact `v1.9.15@36fef03923a168145e6fd2eab023dc1d2b411ad6` Runtime 自然持久化 SuBing 15m Event：`AG2610` Event `id=31`、`bar_end=2026-09-07T13:15:00Z`、`result=buy`、`detected_at=2026-09-07T13:15:15.222713Z`；`AL2610` 还分别在 `13:30Z` 和 `14:00Z` 形成 `sell` / `buy` Event。Event 的 `notification_attempted_at` 与各自 `detected_at` 一致，Runtime 通知状态为 `provider_accepted`。没有 synthetic、replay、backfill、手工发送或同 Event retry 代替自然闭环。
- 2026-09-08 Owner 明确确认微信已收到与上述事件匹配的沪银 `AG2610` 与沪铝 `AL2610` 15m 通知。因此 G11 provider acceptance 与 G12 Owner 实际收件均已完成，状态为 `SUBING_WECHAT_DELIVERY_CONFIRMED / SUBING_NATURAL_CLOSURE_COMPLETE`。该确认不证明 Topic 内其他成员的逐人送达。
- 历史物理 15m 完成后，现役 exact `v1.9.15` Runtime 又自然推进 SuBing 评估至 `2026-09-08T02:30:00 Asia/Shanghai`，health 记录最新 Event 为 `02:15:04.503024` 且当前 `error_type=null`。因此最新状态已不是 `evaluation_failed`；旧 `last_failure` 时间戳作为历史诊断事实保留，不执行清除写入，也不据此重发 Event。
- v1.9.15 最终发布核对：reviewed RC tree、release tree 与 `main` tree 均为 `d33efc91071995f2f04860b8916ea56f660eb903`；PR #333 的最终证据记录双轴 Review P1/P2=0，GitHub 未配置 checks，精确分类为 `NO_CHECKS_REPORTED`，不是 `CHECKS_PASSED`。Issue #307 所列 exact RC/Review、release、PF2611 plan/apply、Runtime promotion、自然 Event、provider acceptance 与 Owner 收件八项 Gate 全部完成。

## Pending Gate

- 苏冰截至 `2026-09-04` 的历史物理 15m 已 `60/60 VERIFIED`，本轮 50 个合约全部成功，无 partial、failed、blocked 或未开始项；该历史目标已完成。BU/BZ 旧七周期 warm-up 的 D1/W1 问题仍未关闭，尤其 BZ `2026-03-20` 非零成交零 O/H/L 不得用 close、settlement 或 1m 代替；它不再阻塞限定 `1m → 15m` 的苏冰历史输入验收。最新现役 Rule health 已自然恢复为 `error_type=null`，但本轮没有取得一份有效的 60 品种当前 readiness 汇总，因此不声称当前 Live 输入逐品种 60/60 ready。输入恢复候选仍等待 main/tag/release、exact-tag Runtime promotion 与生产 Live recovery enable 的各自 Gate；启用前必须核对 Live/Alert 为同一 exact root/version 且恢复协议同时启用。盘后 `missed` 已由 2026-09-07 自然 passed 关闭。
- `PF2611` exact plan、一次性真实 apply、只读验证、exact `v1.9.15` 五项 Runtime promotion 与自然收件验收已完成；`NATURAL_EVIDENCE_PENDING` 已由 `RUNTIME_READY / SUBING_NATURAL_CLOSURE_COMPLETE` 替代。这是 v1.9.15 发布闭环状态，不替代上一条的当前 Live 输入健康核验与后续恢复发布 Gate。
- HTDY目标61对Scope未应用；任何Scope调整、真实数据修复、通知、main/tag/release或Runtime版本切换仍需目标/环境/范围明确的单次执行意图。本轮仓库修复不改变现役`v1.9.15@36fef039`。
