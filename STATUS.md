# 当前状态

更新时间：2026-09-08

本文件只记录当前 release、production Runtime、Scope、自然 evidence 与尚未完成的 Gate。稳定产品面见 `PROJECT_SOURCE.md`，长期决策见 `DECISIONS.md`，active 依赖见 `docs/ARCHITECTURE.md`；已完成版本的实现和验证过程从 Git tag、GitHub Release、PR 与 Git history 追溯。

## Release、Runtime 与 Scope

| 项目 | 当前事实 |
|---|---|
| 正式 Release | `v1.10.3@dd9f3fa0fa332d433e4409dd657d35174b2b371c` 是最新正式 release；PR #357 于 `2026-09-08T09:31:21Z` 合入 main。发布 tree 为 `e8d81d08be57abe30034b9db9982ac6ce26263b0`，annotated tag object 为 `411502b0c9543192e0844c0034b75788fea29d11`，GitHub Release 为 non-draft、non-prerelease，已于 `2026-09-08T09:32:17Z` 发布。v1.10.2 候选已完整吸收，未单独发布。 |
| `main` | `main@dd9f3fa0fa332d433e4409dd657d35174b2b371c` 与 `v1.10.3` peeled commit、GitHub Release target 一致；tree 与已双审候选 `9f22847cfa39d7318d039fc645697ba9da9f3fc0` 一致。发布合并结果已回流 develop；之后仅在 develop 更新本文发布/清理事实，不改已发布 tag。 |
| 发布与部署边界 | 用户明确授权继续一次本机五服务部署、失败即停且不自动回滚后，`v1.10.3@dd9f3fa0fa332d433e4409dd657d35174b2b371c` 已完成一次实际服务切换。API/Web/Live/After-market/Alert 均加载同一 clean detached 新根；发布与加载身份一致。完整健康验收为 `PARTIAL / EXTERNAL_GATE_PENDING`：部署前已有 SuBing `evaluation_failed` 仍保留，尚不能声明 `RUNTIME_READY`。未自动重试或回滚。 |
| Runtime | `2026-09-08 17:50 CST` 只读核对五项服务均加载 `/Volumes/扩展盘/guiyi-quant-runtime-v1.10.3-r1@dd9f3fa0fa332d433e4409dd657d35174b2b371c`。三个安装器步骤均成功：API/Web/既有日志轮转 `services=3`、Live/After-market `services=2`、Alert `services=1`；Market preflight 为 `snapshot_ready / operational_count=60 / snapshot_count=60`，Market/Alert activation marker 均为 enabled、0600。After-market 为已加载、等待自然 18:05 调度，未手工触发；API/Web/Live/Alert 为 running。 |
| Runtime root 核对 | 当前保留主 develop、clean detached v1.10.3 现役根、clean detached `v1.10.0@f8f7d91765122c33cf5e82ed425b6c44f41ad0b1` 切换前恢复根，以及 clean detached `v1.9.15@36fef03923a168145e6fd2eab023dc1d2b411ad6` 旧恢复根。此前两个 RC 工作树与分支已清理；本轮未删除恢复目录。五服务 root/loaded commit 均只引用 v1.10.3。 |
| Database 与 Canonical | 最近 production 只读 readback 为 Alembic `20260903_0045`；RQData session anchor repair 已发布并保留 D1/W1 原始事实。此前全库 Canonical 快照为 8,801 个 Dataset、42,575 个分区、44,629,532 行；该快照不是当前全库总量；PF2611 与本轮 60 合约历史 15m 的最新验收分别见下行及后文。 |
| PF2611 physical warm-up | 2026-09-05 从 clean detached `v1.9.15@36fef03923a168145e6fd2eab023dc1d2b411ad6`，以 `symbol=pf`、`contract=PF2611`、`through=2026-09-04`、plan SHA-256 `7a51886988ff0508f6b3295d40665cef11ff54bc7b0b63ab79aee4fec5544f19` 完成唯一一次真实 RQData/Canonical apply：76 个目标全部 applied，blocked/failed 均为 0。只读 audit finding 为 0；MarketDataService exact physical 15m 读回 4,491 根，交易日窗口为 `2025-11-17..2026-09-04`，七周期最终共 77 个分区、89,280 行（含原已完整且未改写的 1w 分区 1 行）。Rule/Scope/Event、非目标 Catalog、pf 其他合约与 continuous 文件、MainContractMap 及五项 Runtime 的前后基线一致；状态为 `PF2611_WARMUP_APPLIED_AND_VERIFIED`。 |
| Market Runtime Scope | `operational_products.txt` 的 60 个品种。 |
| Alert Scope | `2026-09-07T06:49:43Z` 只读审计：HTDY 仅 `jm × 5m/15m`，其余59品种Scope为空；SuBing为全部60品种 × 15m，两Rule均enabled。HTDY“焦煤继续15m和5m，其他所有品种统一60m”共61对仅为目标，尚未应用。 |
| 当前 Runtime health | `2026-09-08 19:26:57 CST` 只读核对：DB/Redis/Live/After-market 均 ok；60 品种 CLOSED，Live 当日订阅已清理，新进程 last_bar_at=null。Alert 仍 degraded，SuBing 保留 `evaluation_failed@2026-09-08T07:00:29.336273Z`；通用 processing success 已自然推进至 `11:05:52.775687Z`，这不是 RS 新 completed Bar 的苏冰评估证据。未清除故障、确认通知或补发，尚不能声明 `RUNTIME_READY`。 |
| 最近自然 After-market | `v1.10.3` 于 2026-09-08 自然运行：18:05:05 开始、19:05:52 完成，passed、attempts=1、60 品种顺序有效，last_failure/current_run 均 null。19:26 CST 通过现役 API health 与状态文件读回确认；Canonical 发布和当日 Live 清理已完成。本轮没有手工触发盘后任务。 |

Alert transport 为 PushPlus；provider accepted 不等于微信送达。

2026-09-08 12:18 CST 的部署验证在 exact v1.10.0 上运行 Market/Alert launchd 与 promotion 定向回归，结果 `90 passed in 53.82s`；render-only 通过，远端 main、annotated tag peeled commit 与 GitHub non-draft/non-prerelease Release 身份一致。未修改发布 tag、Scope、生产配置或 Live recovery 开关，未手工下载/修复数据、清除故障、确认通知、补发或发送测试通知；新版本自然业务证据仍待采集。

`v1.10.1` 全量发布矩阵在对齐 main 前的 RC `30debdf3787686c09b312ab4472579479a1cb459` 上完成：backend `2394 passed, 5 skipped, 15 deselected`、Mypy 134 个源文件、Ruff、engineering `74 passed`、OpenSpec `9/9`、secret scan `0`、Web `467 passed, 1 skipped`、build/topology 与 Playwright `140 passed`。对齐 `origin/main@f8f7d917...` 后的 merge commit `0e140552605da9079d5525e5977821b7de9b2496` 仅吸收已发布 v1.10.0 的 README、ARCHITECTURE 与两份任务事实文档，未改功能代码；该 tree 的 focused 验证为 backend `181 passed`、engineering `74 passed`、OpenSpec `9/9`、secret scan `0`、Web `467 passed, 1 skipped` 与 build/topology 通过。此后至 reviewed RC `e5771d6a674700ee3a561c3787e0871b475c56d5` 仅更新 `STATUS.md` 的验证/Review 事实；独立 Standards 与 Spec Review 均为 PASS、0 findings。reviewed RC、PR #356 合入结果、main、annotated tag peeled commit 与 GitHub Release target 已读回为同一发布 tree。本轮未执行 Runtime promotion、生产数据/DB/Redis 写入、Scope 变更或真实通知；现役五服务仍为 v1.10.0。

已吸收但未单独发布的 `v1.10.2` 候选，其全量发布矩阵在已对齐 main、已统一版本身份的 RC `8e79bfcfc03793c2b090e1c67b31ffdfef4fbcc9` 上完成：backend `2398 passed, 5 skipped, 15 deselected`、Mypy 134 个源文件、Ruff、engineering `74 passed`、OpenSpec `9/9`、secret scan `0`、Web `468 passed, 1 skipped`、Alert Rule ownership、build/topology 与 Playwright `141 passed`。Market Home P0 的独立实现双轴 Review 已 PASS、0 findings；最终 RC Review 绑定 `4276207f48f958c07f22d249737709763e34841d`、tree `2b0aab6b05e8dad91dd3ca97fce4744f60446f82`，独立 Standards 与 Spec Review 均 PASS、0 findings。本轮没有连接或写入生产 Canonical/Catalog/PostgreSQL/Redis，没有修改 MainContractMap、Scope、通知或 Runtime，也未合入 main、创建 tag 或发布 GitHub Release。

`v1.10.3` 发布矩阵绑定 `83e9e291f68981cf4ae02752d333d83749b28345`：backend `2415 passed, 5 skipped, 15 deselected`、engineering `74 passed`、Web `478 passed, 1 skipped`、Playwright `141 passed`、Mypy 135 个源文件、Ruff、Alert Rule ownership、build/topology、OpenSpec `9/9`、secret scan `0` 与 diff check 均通过。独立 Standards / Spec Review 覆盖 `v1.10.1@8e3df5c0...` 到该候选的 62 个文件，均 PASS、0 findings。最初 pnpm 自动安装受网络沙箱限制、浏览器监听受沙箱限制以及临时端口 5193 不匹配 fixture 白名单的尝试未通过；最终复用既有依赖、关闭 pnpm 自动安装，在默认 5182 隔离运行的完整矩阵通过，没有修改测试白名单或截图基线。此后仅补充本文验证事实。2026-09-08 17:22 CST 只读核对五项 launchd 均引用现役 `v1.10.0@f8f7d917...`；该发布轮次明确不部署、不切换 Runtime、不连接 RQData、不写生产数据、DB、Scope 或通知；后续部署事实见上表。

`v1.10.3` 首次部署准备的 exact-tag 定向回归为 `90 passed in 65.45s`（Market/Alert launchd 与 promotion），新根独立 Web typecheck/build/topology 与 render-only 通过；只读 promotion preflight 为 `snapshot_ready / operational_count=60 / snapshot_count=60`。盘后状态复制在 mutation 前因错误的 `config/universe/operational_products.txt` 路径退出；随后只读核验已改用唯一 `load_operational_products()`，确认源 public schema v2、60 品种顺序、无 current run、passed 与源 SHA-256 `e98f09a39ded99fe4b566b9e6616455929155a9e6619dd99c284d3578431e610` 均有效，目标仍不存在。用户随后给出新的明确授权，本轮已按修正校验 create-only 带入该状态并完成一次五服务切换；各安装器成功，无自动重试或回滚。部署前 API/Web 为 200、DB/Redis/Live/After-market 为 ok，60 品种处于 CLOSED；Alert 已 degraded，SuBing `evaluation_failed` 的最新失败时间为 `2026-09-08T07:00:29.336273+00:00`。该故障是切换前基线；未清除故障、改 Scope、补数或补发通知。

## v1.10.4 候选与盘后复核

用户已确认新候选版本为 `v1.10.4`；API/Web、Python 项目/lock 与 health 测试版本同步准备，
候选包含 `4b55a4189` 的 captured-source 恢复及盘后互斥修复。正式发布和本机五服务切换仍未执行，
现役保持 `v1.10.3`。候选完整验证已通过：backend `2563 passed, 16 skipped, 15 deselected`、
engineering `74 passed`、Web `478 passed, 1 skipped`、Playwright `141 passed`、Mypy `138` 源文件、
Ruff、Alert Rule ownership、build/topology、OpenSpec `9/9`、secret scan `0` 与 diff check。
工程检查首次发现固定版本断言尚为 1.10.3，同步至 1.10.4 后完整重跑通过。独立 Review 尚待结束。

2026-09-08 19:26:46..19:26:57 CST 从现役 exact v1.10.3，只读 PostgreSQL 事务及统一
MarketDataService/Redis/API 复核：RS2609 当日 Canonical 的 1m/5m/15m/30m/60m 分别为
225/45/15/8/5 根，均与权威 Session 期望精确一致；旧五根目标 09:01/09:05/09:15/09:30/10:00
全部存在。60 个当日 rank1 合约从上市日至当日收盘的 physical 15m 前缀均 `coverage_exact=true`，
RS2609 为 3,570/3,570 根；本次 JD 的当前主力为 JD2611，不能沿用旧 JD2610 身份。
自然盘后已清理当日 Live bars 和订阅，RS recovery watermark/circuit 均 null，下午 provider
attempt count 仍为 3；没有清零预算或补写水位。旧日内 event reader 因订阅已清理返回
`MARKET_READ_CONTRACT_UNAVAILABLE`，属于已结束的 Live 生命周期，不能重新解释为 Canonical 缺口。

结论：原五根缺口已由自然盘后维护解决，本轮不再生成或执行这五根 Live 恢复计划；旧计划失效，
不能为完成步骤而重建过期 Live 数据。剩余为新版本发布/部署以及后续自然 completed Bar 的苏冰
评估与健康验收。通用盘后 processing success、完整历史数据或旧 Rule 最新评估时间均不能替代
RS 的自然评估成功证据；不手工清除 `evaluation_failed`。

## 苏冰 60 品种输入恢复候选

2026-09-08 新增 captured-source 受控恢复入口，状态为 `CODE_COMPLETE_EXTERNAL_GATE_PENDING`。
默认只读计划，显式 apply 绑定源/计划哈希、当日同合约与精确五根增量；零 provider 调用，保留已耗尽预算，
在共享提交边界检查预算/circuit/序列/TTL 后原子写五根和恢复水位。新增实际共享锁心跳证据及与盘后维护
互斥的全局 OS 锁。独立 Standards/Spec 初审发现的盘后检查竞态和源数值别名冲突均已修正，复审均 PASS、0 findings。
最终后端回归 `2563 passed, 16 skipped, 15 deselected`；恢复/CLI/Runtime/盘后/Alert/SuBing 定向回归
`327 passed`（包含真实隔离 Redis 验证）；工程 `74 passed`，Mypy `138` 源文件、Ruff、OpenSpec `9/9`、
secret scan `0` 与 diff check 通过。既有 225 行 RS2609 源快照经新严格解析器离线通过。
本轮只实现并验证代码，没有生产读取/恢复、RQData 请求、配置变更、通知、release 或 Runtime 切换；
现役仍为上表 v1.10.3，五根生产 Bar 与旧 `evaluation_failed` 未由本轮处理。
采用新入口须另行完成发布/部署授权与 exact-version 核对，再生成当前仍有效的恢复计划并取得单次执行授权；
旧 2026-09-08 候选跨日即失效。不得由代码验收声明 `RUNTIME_READY`。


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

- PR #352 已将 P6 Review 修复与 facts-only truth closure 集成到 `develop@c64b42f10b48ec8eace2390abd3254e0dd573d22` / tree `60e606cc92b33160e1fee67a35a2c60917844c89`。同 tree 的最终候选 `efcd12f1794c80ae7f6cad638d98b0acc1693380` 在全部 Review finding 关闭后完成唯一一次最终 Task 22 矩阵：backend `2274 passed, 4 skipped, 15 deselected`、engineering `74 passed`、Web `431 passed, 1 skipped`、Playwright `109 passed`，Ruff、Mypy、Alert Rule ownership、build/topology、OpenSpec `9/9`、secret 与 diff/status checks 均通过，失败与重试均为 0。初始完整 Review 按轴记录为 Standards 3 个 P2、Spec 1 个独立 P2，共 4 个唯一 finding：generation invalidation、auxiliary FIFO/LRU、tracked docs truth、Reference DOM/PNG；`74e58587b` 关闭三个 code/visual finding，`84868658e` 与 `efcd12f17` 关闭 docs truth，相应两轴 scoped re-review 均为 PASS、无新 P1/P2/P3，累计 Review ledger clean。该P6代码已随`v1.10.0@f8f7d917...`发布；产品证据状态仍为 `P6_COMPLETE / PARTIAL_PRODUCT_EVIDENCE_REQUIRED`，不是完整page parity或Runtime验收。
- 旧任务文档迁移不升级验收：杯柄D1 clean-room并非原页面精确公式；既有18个D1/60m OOS结果与9个W1执行事实不足仍属于研究证据，产品测试不能升级为新的`OOS_PASSED`。
- 页面诊断 token、六组合评分/排序、AI copy、目标/吸筹的权威昨收与期货 owner parity、比较器 browser-final/tie golden 等 P3 原件缺口继续为 `EVIDENCE_REQUIRED`。本机已找到manifest登记的完整逻辑根，133项manifest完整性、27项页面响应、AI矩阵、综合决策witness与离线比较器均可重放；但当前Core replay因原包依赖已退役接口而阻塞，且来源包自身仍明确缺少上述原件，route fixture不能替代。
- [P6真实工作站只读证据](docs/research/newow-v3.2.82/P6_TRUSTED_CLOSURE.md)在已加载v1.10.0 API上完成首30品种两轮和rb 45项矩阵；两轮分别`30/30`、代表矩阵`45/45`均为HTTP 500，诊断根因为`MAIN_CONTRACT_MAP_MISSING`被v1.10.0 API错误包装为`NEWOW_INTERNAL_ERROR`。因此`REAL_WORKSTATION_MDS_REQUEST_PATH = MEASURED`，但`REAL_WORKSTATION_MDS_SUCCESS_PERFORMANCE = BLOCKED / INPUT_IDENTITY_UNAVAILABLE`，不生成SLA pass/fail。`v1.10.1` 已以RED→GREEN回归测试将MDS失败统一映射为typed Web可识别的`NEWOW_DATA_UNAVAILABLE / HTTP 409`；该修复不改MDS或主力映射，且尚未进入当前Runtime。


- 2026-09-08 `12:47:43..12:53:53 Asia/Shanghai`，按 Owner 本轮对三个新有界计划的批准，从 clean `develop@edfab6fd469919fe25a1f7ba9e27579b3e99d25e` 完成 rb 同合约 `1m + 60m` 补齐：RB2701（through=2026-09-07）9/9、RB2605（through=2026-04-07）16/16、RB2610（through=2026-09-01）14/14，共39/39分区，实际RQData请求15次；failed/partial/blocked/unstarted=0，无重试或回滚。执行前三个fresh hash均匹配，锁内复核；逐合约新只读事务经Catalog/Canonical物理读取和MarketDataService完整端点验证，60m分别为1,084/1,509/1,502根（合计4,095），原有Bar全字段一致，剩余有界目标均为0。净补齐85,995根1m和2,803根60m；执行结果和逐月目标在本机 `rb60m-apply` 诊断附件中。该批准已消费，不授权重跑或其它周期/合约。
- 上述补齐后，现役v1.10.0 API的 `rb / trend / 60m / auxiliary / zhaoyao_mirror` 固定历史快照 `as_of=2026-09-07T07:00:01Z` 两次真实HTTP均200，约3,096/2,902ms、406,663B。独立同release只读进程确认结果cache首次miss、第二次hit，但每次仍执行2,432条DB语句；独立进程首次结果缓存未命中的请求（未清除OS/磁盘缓存）窗口解析约535ms、读取/覆盖校验约1,462ms、照妖镜公式约10ms。该单样本支持后续优先研究读取成本，不构成全产品SLA或浏览器渲染验收。`2026-09-08T04:56:17Z` 当前日期请求仍500/NEWOW_INTERNAL_ERROR，同日rb rank1映射只读行数为0；历史补齐不关闭当日owner边界Gate，也未切换Runtime或修改映射。


- 2026-09-08 照妖镜与历史入口候选 `3f14974e392dbdcf0642f2bb8c64725a50c89bbe` 已完成独立 worktree 实现、测试和 Standards/Spec Review，状态为 `CODE_COMPLETE_EXTERNAL_GATE_PENDING`。照妖镜改用冻结原件的分类彩柱、上下独立缩放与提示装饰；空数据清空后不会污染其他副图。历史入口显式验证最多20个完成交易日，保留最后Session结束后1微秒的精确截止及30秒协作式检查预算；当前数据不自动回退。历史模式隐藏当前报价/合约，跨合约重叠时间戳的Action/Hint按已选Frame归属投影；reference缺数只影响自身，真正身份/世代冲突仍联动撤销。
- 同一固定历史 rb 60m 请求，优化前后各五组新进程首次/同进程缓存命中测试均为HTTP200，4,095根输入、406,663B及完整稳定业务字段不变。含诊断事务开销的DB语句2,433→89（减少96.34%），冷/热HTTP中位数2,210/2,167ms→536/488ms（降低75.77%/77.46%）；未清除OS/磁盘缓存、未改公式或裁剪输入。冻结原件与新绘图对确定性及真实60根数组、三个视窗、DPR1/2共12组对照，像素差异均0；这是有界绘图证据，不是在线全页面或60品种SLA。
- 最终回归：后端 `2415 passed, 5 skipped, 15 deselected`，engineering `74 passed`，Web `478 passed, 1 skipped`，Playwright `141 passed`；Mypy135源文件、Ruff、build/topology、OpenSpec9/9、secret scan0与diff检查通过。后端矩阵位于`a24320bf6`，此后`3f14974e3`仅修复前端缺数分类并通过新定向/完整Web验证；两轴scoped re-review均PASS。真实浏览器DPR1/2主动等待reference409后，历史主图/照妖镜仍ready，MACD切换、平移缩放及返回当前均通过，无pageerror；首次照妖镜点击到绘制1,344/1,368ms，缓存切回31.9/32.9ms且无新增HTTP。
- `2026-09-08T08:41:20Z`最终只读核对：当天rb rank1映射仍0行、有效RQData Session4行，最新映射日09-07。历史入口真实返回 `2026-09-07T07:00:00.000001Z` 并验证chart+zhaoyao_mirror，当前请求在候选API中仍明确409；reference自身仍409/NEWOW_DATA_UNAVAILABLE。当日权威输入、其他独立面板及正式Runtime Gate未关闭。本任务未下载、补写映射/Canonical/DB、重跑旧补数、发布main/tag或切换Runtime。

## 自然 evidence

- `2026-09-07T06:55:25Z` 对全部 60 品种逐一 GET events，查询区间为 2026-09-03 至该次审计时刻，SuBing 合计 `total=0`。该历史快照只证明当时自然 Event/provider/人工收件尚未完成；后续发生的自然闭环见下文，不得回写或删除这个早期事实。
- 2026-09-03 的自然 after-market 为 `failed`，`attempts=1`、`error_code=LIVE_DOMINANT_MISMATCH`；这是 strict rank1/Live subscription snapshot reconciliation 未通过的真实失败，不能改写为 passed，也不能以手工、synthetic、replay 或 fallback 替代。
- 2026-09-07 夜盘后，exact `v1.9.15@36fef03923a168145e6fd2eab023dc1d2b411ad6` Runtime 自然持久化 SuBing 15m Event：`AG2610` Event `id=31`、`bar_end=2026-09-07T13:15:00Z`、`result=buy`、`detected_at=2026-09-07T13:15:15.222713Z`；`AL2610` 还分别在 `13:30Z` 和 `14:00Z` 形成 `sell` / `buy` Event。Event 的 `notification_attempted_at` 与各自 `detected_at` 一致，Runtime 通知状态为 `provider_accepted`。没有 synthetic、replay、backfill、手工发送或同 Event retry 代替自然闭环。
- 2026-09-08 Owner 明确确认微信已收到与上述事件匹配的沪银 `AG2610` 与沪铝 `AL2610` 15m 通知。因此 G11 provider acceptance 与 G12 Owner 实际收件均已完成，状态为 `SUBING_WECHAT_DELIVERY_CONFIRMED / SUBING_NATURAL_CLOSURE_COMPLETE`。该确认不证明 Topic 内其他成员的逐人送达。
- 历史物理 15m 完成后，现役 exact `v1.9.15` Runtime 又自然推进 SuBing 评估至 `2026-09-08T02:30:00 Asia/Shanghai`，health 记录最新 Event 为 `02:15:04.503024` 且当前 `error_type=null`。该时点状态已不是 `evaluation_failed`；这是早先的历史恢复事实，当前 12:19 CST 读回的后续 SuBing failure 见上表。旧 `last_failure` 时间戳作为历史诊断事实保留，不执行清除写入，也不据此重发 Event。
- v1.9.15 最终发布核对：reviewed RC tree、release tree 与 `main` tree 均为 `d33efc91071995f2f04860b8916ea56f660eb903`；PR #333 的最终证据记录双轴 Review P1/P2=0，GitHub 未配置 checks，精确分类为 `NO_CHECKS_REPORTED`，不是 `CHECKS_PASSED`。Issue #307 所列 exact RC/Review、release、PF2611 plan/apply、Runtime promotion、自然 Event、provider acceptance 与 Owner 收件八项 Gate 全部完成。

## Pending Gate

- 苏冰截至 `2026-09-04` 的历史物理 15m 已 `60/60 VERIFIED`，本轮 50 个合约全部成功，无 partial、failed、blocked 或未开始项；该历史目标已完成。BU/BZ 旧七周期 warm-up 的 D1/W1 问题仍未关闭，尤其 BZ `2026-03-20` 非零成交零 O/H/L 不得用 close、settlement 或 1m 代替；它不再阻塞限定 `1m → 15m` 的苏冰历史输入验收。当前五服务已统一为 exact v1.10.0，但 Alert degraded、SuBing evaluation_failed 尚未关闭，且本轮没有取得一份有效的60品种当前readiness汇总，因此不声称当前Live输入逐品种60/60 ready。下一项为只读定位 SuBing 这项既有评估失败；完整健康、切换后自然 completed Bar 与业务 evidence 尚待验收。生产 Live recovery enable 仍是独立 Gate；同一 exact root/version 不等于恢复协议已启用。盘后`missed`已由2026-09-07自然passed关闭。
- `PF2611` exact plan、一次性真实 apply、只读验证、exact `v1.9.15` 五项 Runtime promotion 与自然收件验收已完成；`NATURAL_EVIDENCE_PENDING` 已由 `RUNTIME_READY / SUBING_NATURAL_CLOSURE_COMPLETE` 替代。这是 v1.9.15 发布闭环状态，不替代上一条的当前 Live 输入健康核验与后续恢复发布 Gate。
- HTDY目标61对Scope未应用；任何Scope调整、真实数据修复、通知、main/tag/release或Runtime版本切换仍需目标/环境/范围明确的单次执行意图。本轮仅按明确部署请求完成五服务 v1.10.0 身份统一；既有通知故障 acknowledgment、真实通知、Scope 和数据修复均未执行。
