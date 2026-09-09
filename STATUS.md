# 当前状态

文档核对：2026-09-09，develop 代码基线 `79c59ccb4`；统一详情页本轮修复已通过 owner 视觉接受并集成 develop。
本日 P1 验证使用临时数据与隔离 PostgreSQL；后续 WebSocket/详情页验证使用离线测试与浏览器 fixture。
上述工程验证没有连接生产 PostgreSQL/Redis/RQData 或重新验收 Runtime。
另有本日获准的 AU 来源查询与单键生产 Calendar 更正，具体事实及边界见 Newow 小节；没有切换 Runtime。
以下生产结论保留原采集时间，不能当作今天的实时健康状态。

本文件只保留 release、Runtime、Scope、关键验收事实与未完成 Gate。稳定产品面见 `PROJECT_SOURCE.md`，
长期决策见 `DECISIONS.md`，active 依赖见 `docs/ARCHITECTURE.md`。已完成的计划、逐次操作、旧候选矩阵及
逐合约结果从 Git history、tag、PR 和原 evidence 追溯；历史授权不授权重跑。

## v1.10.5 已发布并切换（苏冰历史输入故障与自然推送已闭环）

- 独立候选分支 `codex/subing-input-release-candidate` 基于 `0eca85209008e036626b37eb5563fc504dba12bc`；
  API/Web/Python/lock 版本身份与版本一致性断言为 `1.10.5`；已审候选为 `0d2273445637a6dd5cfef2a45c4f1242276952c5`。
- 本次新跑验证：直接相关 `357 passed`；backend + engineering `2967 passed, 16 skipped, 28 deselected`；
  隔离 PostgreSQL publication `6 passed`；Web `504 passed, 1 skipped`、typecheck/build 通过。
  浏览器首轮 89 passed / 60 failed / 3 skipped：60 项源于运行端口 5192 与 fixture 固定 5182 不一致；
  使用正确端口复跑这 60 项全部通过，candidate-preview 专用 3 项另跑全部通过。
  Ruff、Mypy（150 source files）、9 项 OpenSpec 与 secret scan 通过；代码基线独立 Standards/Spec Review 无阻塞。
  版本收尾后的 engineering + health `80 passed`、离线 `uv lock --check` 与 Web build 通过；版本增量独立复核无阻塞。
- 该候选包含已集成的 Canonical P1、captured Runtime 身份解析、WebSocket 资源边界、统一详情页、
  SuBing 历史参考与 Newow 只读相关改进，不是仅两合约数据修复的最小代码补丁。
- 本轮对两个精确 hash 的各一次真实 apply 已完成，执行版本为现役 v1.10.5；
  AO2701 先执行并严格读回通过后才执行 OI2701。两个 CLI 均 exit 0、passed、applied=18、blocked=failed=0，
  各 9 个 direct + 9 个 derived 目标，无重试。只发布各合约 2026 年 1～9 月的 `1m + 15m`，through=2026-09-08。
  AO2701 plan hash `602821c7195a11c35a2b44b6a18c4b6d806d8e7b9eb98b1be1cc15e0d9e5f504`；
  OI2701 plan hash `a7431d8eac813486181e2c773f43b1a99b01f30c9469bd25be66d1d6cd7a1a4f`。
  12:33:58 / 12:47:22 CST 的独立只读事务经 MDS 严格读回均 18/18 通过：AO 为 72,045 根 1m、4,803 根 15m；
  OI 为 53,340 根 1m、3,556 根 15m。逐月身份、URI/file SHA-256、行数、端点、完整 lifecycle/session 覆盖
  与公开 MDS 查询一致；44,210 个非目标分区的 Catalog 指纹未变。36 个目标本地独立证据复核通过。
  两合约随后只读重算均 exit 0、剩余目标为 0；13:00:24 CST 的 SuBing readiness exit 0、passed、60/60 ready，
  AO2701/OI2701 各自 historical_15m_gap、live_1m_gap、live_15m_gap 均为 0，error_codes 为空、scope_enabled=true。
  本次限定历史输入缺失已关闭；修复后的自然评估、Event 与 owner 微信收件已完成下述验收。
  整体 `RUNTIME_READY` 的现版本自然盘后验收仍独立保留，不补评、不补发。
  首次 readiness 临时命令遗漏 launcher 的 Redis 认证归一化，返回 60 个 INPUT_DIAGNOSIS_UNAVAILABLE；
  本地确认客户端缺少认证后，仅按既有 launcher 方式修正临时调用环境并通过只读检查，未修改生产配置或重跑 apply。
  已产生新 hash URI，不得回退只支持固定 URI 的 v1.10.4。
- 2026-09-09 午后自然验收及 owner 收件确认完成，状态为 `COMPLETED`，
  `SUBING_WECHAT_DELIVERY_CONFIRMED / SUBING_NATURAL_CLOSURE_COMPLETE`，归属 exact
  `v1.10.5@cdd72d7501227d8e7f905ea0b8a54c038b521a09`。14:03:17 CST 的只读核验中，
  严格 Runtime 身份与双心跳通过，60 品种 TRADING/subscribed，苏冰自然评估已到 14:00；
  `last_failure_at` 仍为 `2026-09-09T03:30:05.449850Z`，本轮观察未新增失败，旧记录未清除。
  14:03:46 CST 的 readiness exit 0、passed、60/60 ready；AO2701/OI2701 截至 14:00 的
  historical_15m_gap、live_1m_gap、live_15m_gap 均为 0，error_codes 为空、scope_enabled=true。
  补齐后已自然生成四条苏冰 Event：#143 EC2610 sell（13:45），#144 EG2610 sell、#145 L2701 sell、
  #146 PT2610 buy（后三条 bar_end 均为 14:00 CST）。#146 的 detected_at/notification_attempted_at
  为 `2026-09-09T06:00:16.478341Z`，与 Runtime `last_provider_accepted_at` 精确匹配；
  owner 在本任务针对该 PT2610 14:00 买入提醒明确回复“收到了，你可以闭环了，更新下文档”。
  该确认只证明 owner 收到这条通知，不声明另外三条或 Topic 其他成员实际送达。
  只读证据索引为 `/private/tmp/subing-fail-review-20260909-1403-{runtime,readiness,events}.json`；
  以上保存关键事实，临时文件再次使用前须检查存在与完整性。本次仅更新文档，未执行生产 failure acknowledgment、
  修改 Scope、重跑补齐或补发通知；苏冰本次故障闭环不替代 v1.10.5 自然盘后验收。

## Release、Runtime 与 Scope

| 项目 | 最近已记录事实 |
|---|---|
| 正式 Release | `v1.10.5@cdd72d7501227d8e7f905ea0b8a54c038b521a09`，PR #359 于 `2026-09-09T03:53:57Z` 合入 main；tree `11704da35b2eccf62bdddc330eb0e42ea5930247`，annotated tag object `71bad4102a9be883ba341c7dd27f0e98f59dab41`。GitHub Release 于 `2026-09-09T03:55:28Z` 发布，non-draft、non-prerelease；远端 main、peeled tag 与 Release target 一致。API/Web/Python/lock 为 1.10.5。 |
| 发布验收 | 已审候选 `0d2273445637a6dd5cfef2a45c4f1242276952c5` 与发布 tree 完全一致；验证矩阵见上节。本轮重新核验四处版本、远端 main、annotated tag 及 Release target；未重复运行已通过且输入未变的全套测试。 |
| Runtime | `2026-09-09 12:09:27 CST` 严格读回：五项 launchd 均加载 `/Volumes/扩展盘/guiyi-quant-runtime-v1.10.5-r1@cdd72d7501227d8e7f905ea0b8a54c038b521a09`；API/Web/Live/Alert running，After-market idle；Market/Alert marker enabled，Live/Alert 新鲜心跳同根同 commit 且 `recovery_guard_enabled=true`。切换完成、未使用回退；本日 14:03 的自然 completed Bar 核验通过，随后 owner 确认苏冰微信收件，详见上节；现版本自然盘后验收仍待完成，不声明整体 `RUNTIME_READY`。 |
| Runtime 工作树 | 现役 detached v1.10.5 根与原 v1.10.4 根均保留且干净。新根离线安装锁定 Python/Web 依赖并 build；render-only 与三个 installer 模式均一次通过，未重试。旧根目前无五项 launchd 引用；未清理，新格式数据发布后不可将其作为兼容回退根。 |
| 最近 health | `2026-09-09 14:03:17 CST`：API 1.10.5、Runtime health ok/readonly，严格 captured Runtime 身份 verifier 通过；Live/Alert 新鲜心跳同现役 exact root/commit，recovery guard 开启。60 品种 TRADING、subscribed_count=60，Live 与处理水位到 14:03，苏冰自然评估到 14:00。14:03:46 的 readiness 60/60 通过，AO/OI 三类输入缺口均为 0。最新 #146 自然 Event 与 provider acceptance 匹配，owner 已确认对应微信收件；苏冰旧 failure 时间戳保留，无新增失败记录。本次结论以这些带时间证据为准。 |
| Database | 最近已记录 production readback 为 Alembic `20260903_0045`；session anchor repair 已发布。旧全库 Dataset/分区/行数快照不作为当前总量。 |
| Market Scope | `operational_products.txt` 的 60 个品种。 |
| Alert Scope | `2026-09-07T06:49:43Z` 审计：HTDY 仅 `jm × 5m/15m`；SuBing 全部60品种 × 15m，两 Rule enabled。HTDY“焦煤15m和5m，其余59品种60m”共61对仍仅是未应用目标。 |
| 最近自然 After-market | v1.10.3 于 2026-09-08 自然运行，18:05:05 开始、19:05:52 完成，passed、attempts=1、60 品种，last_failure/current_run null。该状态经校验 create-only 先带入 v1.10.4，本轮以相同 bytes 带入 v1.10.5，hash `cece65929ba734c37cf91ee47af1b0d23b5dc3dd413c9d703888f669428347d5`；它不是 v1.10.5 自然盘后证据。 |

## Runtime 验收阻塞与开发差异

- WebSocket 阻塞读取修复 `fd6f566cc` 已合入 develop：同步读取进入最多四个并行 worker，
  每次独立创建与关闭 Session/Redis，取消不提前释放仍在执行的容量。backend 全量
  `2859 passed, 16 skipped, 21 deselected`、engineering `74 passed`，Ruff/Mypy 与独立 Review 通过。
- 统一详情页候选已删除旧页面及专用代码，保留旧链接的确定性迁移、Event 精确定位、
  失败态品种选择和盘后失败披露。Web `504 passed, 1 skipped`；完整浏览器 `149 passed, 3 skipped`
  （candidate-preview 专用场景）；build/typecheck、OpenSpec/secret/diff 与独立 Review 通过。
  工程状态为 `CODE_COMPLETE`、`TEST_COMPLETE`、`REVIEW_COMPLETE`；owner 已接受桌面/390px fixture 截图并明确允许合入 develop。
  本轮不发布、不切换 Runtime，fixture 不证明生产数据或自然业务闭环。

- Canonical P1 修复 `a6317cde262a14317e8db1f5fed962f94cd6e18d` 已完成不可变文件与 Catalog
  单分区原子指针发布；提交失败不再覆盖旧文件，结果不确定时明确停批。实际验证：backend
  `2855 passed, 16 skipped, 21 deselected`、隔离 PostgreSQL `6 passed`（含进程退出与事务可见性）、
  engineering `74 passed`，Ruff/Mypy/OpenSpec/secret/diff 通过，独立 Standards/Spec Review 无剩余阻塞。
  工程已随 v1.10.5 发布并切换消费者；本日 AO/OI 已获准发布生产 hash URI，详见上节。
  后续每批 Canonical 写入仍须独立单次意图及现役消费者/旧 writer 核对；不得回退旧读取代码。
  旧文件保留支持已有 reader，本次不执行文件回收或数据迁移。合同与命令分别见 `docs/DATA_CENTER.md`、`TESTING.md`。

- v1.10.4 的 captured-source 恢复入口误解析 launchd `event triggers` 中的 `=> {` 嵌套块，
  After-market 身份 Gate 失败。部署后的只读核对确认实际 root、commit、WorkingDirectory 与 idle 状态正确。
- `f08d86d88` 已在 develop 修复纯解析器并保留层级、重复字段、身份与括号校验；已记录验证为身份模块
  `76 passed`、调用链 `249 passed / 11 skipped`、engineering `18 passed`，两轴独立 Review clean。
  同份实机脱敏输出旧解析器失败、新解析器通过；未从开发根绕过 exact-tag Gate 运行恢复入口。
- 修复已发布并进入现役 v1.10.5；本轮真实 launchd、exact annotated tag 与新鲜双心跳的严格身份校验通过。
  两合约历史输入修复及修复后的自然苏冰评估、Event/provider acceptance、owner 微信收件
  均已按上节证据闭环；旧 failure 保留，整体现版本自然盘后验收仍独立待完成。
- 2026-09-08 19:26:46..19:26:57 CST 只读确认 RS2609 当日 Canonical 五周期
  `1m/5m/15m/30m/60m` 为 `225/45/15/8/5` 根，原五根日内目标均存在。
  当日 Live 已由自然盘后清理，恢复水位/circuit null，provider attempt count 仍为3。
  旧日内恢复计划已失效，不能为了完成步骤重建过期 Live 数据；以后恢复须另取当日精确计划和单次授权。

## 历史输入与自然闭环

- PF2611 于 2026-09-05 使用 exact v1.9.15 完成截至 `2026-09-04` 的 warm-up：76目标 applied，
  physical 15m 为4,491根，audit无finding；plan hash
  `7a51886988ff0508f6b3295d40665cef11ff54bc7b0b63ab79aee4fec5544f19`。该批准已消费。
- 苏冰截至 `2026-09-04` 的历史物理15m已完成 `60_OF_60_HISTORICAL_PHYSICAL_15M_VERIFIED`。
  2026-09-08 02:27:44..02:28:20 CST 经 MDS/Catalog/Canonical 全量读回259,183根、640个月分区，
  每项 actual=expected、`coverage_exact=true`。新增50合约为465 direct 1m + 465 derived 15m，930全部 applied，
  无partial/failed/blocked/unstarted或retry；批次hash `c181453a449c95ec711ac80cfee365ae6cec0cb3e6f89fa89572b6458a2e31c1`。
  原 `verify-last-run.json` hash `2d4afc3f714538a94758cc7af9e65e5618c282f35e6f8bfafecdbde9de1089d3`，
  evidence目录 `/private/tmp/subing-physical15m-20260907/`；保留索引不保证临时文件当前仍存在。
- 2026-09-08 盘后再次确认当日60个rank1合约上市日至收盘的physical15m前缀均exact；JD当时主力为JD2611。
  历史输入完整不能替代当前 Live readiness 或自然 Event 验收。
- BU/BZ旧七周期warm-up的D1/W1缺口仍未关闭。BZ `2026-03-20` 有 `volume=2`、O/H/L全0、close=7811，
  不能用close、settlement或1m填补；该问题不否定已完成的限定1m→15m历史验收。
- exact `v1.9.15@36fef03923a168145e6fd2eab023dc1d2b411ad6` 于2026-09-07夜盘自然生成
  AG2610 Event id=31，bar_end=`2026-09-07T13:15:00Z`，buy，detected_at=`2026-09-07T13:15:15.222713Z`；
  AL2610另在13:30Z/14:00Z形成sell/buy Event，均记录one-shot provider acceptance。
  Owner于2026-09-08确认收到对应沪银/沪铝微信通知，G11/G12完成，
  `SUBING_WECHAT_DELIVERY_CONFIRMED / SUBING_NATURAL_CLOSURE_COMPLETE`。Issue #307八项Gate已完成。
  这只归属v1.9.15历史闭环，不证明Topic其他成员送达或v1.10.4当前健康；provider accepted仍不等于送达。
- 早期自然Event为0、2026-09-03盘后`LIVE_DOMINANT_MISMATCH`失败等历史观察从Git history追溯；
  后续成功不改写这些历史失败，也不授权补评/补发。

## Newow 产品证据与开发候选

- 2026-09-09 新版牛哇盘点与参考卡片工程完成，代码候选 `c1d03c6d8`；公开观察、版本来源与缺口见
  [当前复核](docs/research/newow-current-review.md)。当前 FLAT 等待卡使用已接受的当前窗口身份，
  不创建参考交易或借用分页历史收益；日内时间增加时分并保留跨年信息。旧手册及派生 PDF 已同步纠正过时实现状态。
  Web `507 passed, 1 skipped`、定向 backend + engineering `275 passed, 1 skipped`、build 通过；
  等待卡浏览器 2 项、既有交互 4 项通过，1440/390px fixture 已视觉检查；9 项 OpenSpec、secret/diff 通过。
  独立 Standards/Spec 复审通过，复审分别实跑 59/69 项；工程为 `CODE_COMPLETE`、`TEST_COMPLETE`、`REVIEW_COMPLETE`。
  owner 解锁后于 14:16–14:32 CST 完成招商银行三策略 × 日/周/60分的单标的可见行为采样，
  并观察顺灏日周目标/吸筹、金钼周线清仓标记及14:30前后卡片变化；锁屏阻塞已解除，详见当前复核。
  新版五项解释拆分与现有四项 certainty 合同有明确展示差异，待独立版本设计和规则取证；未变更公式。
  未刷新页在14:30后仍留待确认文字，刷新后顺灏清仓变持仓，不能把盘中预览固化为正式交易。
  逐Bar parity、旧版个股bug因果修复、15:00收盘后及自动隐藏仍 `EXTERNAL_GATE_PENDING`。
  fixture 与旧版证据不证明新版 parity。本轮未发布、切换 Runtime 或修改策略公式、收益口径、生产数据与通知。

- 2026-09-09 黄金元数据接力已完成五合约 `AU2304/AU2306/AU2308/AU2310/AU2312` 的本批缺口修复。
  新来源审计于 `04:02:05..04:02:20Z` 独立完成 613 次 public metadata API（42 Calendar、571 Session），
  SDK RPC dispatch 575 次；无 retry、OHLCV、DB 或 Canonical 写入。source evidence hash
  `32c49db5713229aa290e1e4db734cc770390c6e8a96d62ac7634c3eb9b5a0a77`，目录
  `/private/tmp/newow-au-source-isolated-20260909-re136gmd/`。这不是旧失败批次的逐请求轨迹；旧批次已执行数仍未知。
  173 个候选中 168 个日期获得夜盘正证据；其余 `2022-04-06/05-05/06-06/09-13/10-10` 未更正。
  `04:14:31..04:14:32Z` 精确将 168 个 SHFE Calendar 的 `has_night_session` false→true，一次 commit、
  独立只读 readback verified，其他字段不变；不重复原 id46796 更正。plan hash
  `23c252c9d5d779ad3342b2bd768a6878c3edb33e7600a7420896b90a89406978`，结果
  `/private/tmp/newow-au-calendar-batch-20260909-9tu4f_4f/apply-result.json`。
- 更正后 fresh plan 与保存响应逐项核对，通过原生 snapshot 校验；`04:22:16..04:22:18Z` 再一次提交
  102 条 SHFE 非交易日 Calendar 与黄金 196 天的 779 条 Session，共 881 行，保留既有 200 天 Session。
  本次无 Calendar UPDATE、RQData 或 Canonical 写入、无 retry；独立只读回读一致，五合约本批范围的
  Calendar/Session 缺口均为 0。plan `aa8c8e3148181c54dfbb140083a60ff5757177ff14f45a590fb45e0c015e28b8`，
  snapshot `cd497e3249ba674b5a7a5d281f6e166bd94b59eff98e05758bb5961ff07e1af0`，结果
  `/private/tmp/newow-au-metadata-insert-20260909-one/apply-result.json`。
  上述两次 mutation 执行代码基线 `951d310df7bba7ac95597f1c77c658afac231be6`；168 更正包装器隔离测试
  9 passed，原生 bounded metadata 本轮 60 passed，独立 Review 通过。这些测试不证明页面恢复。
- 本轮只读核实五项 installed/loaded Runtime 同为 `v1.10.5@cdd72d750`，API/Web/Live/Alert running、
  After-market loaded、当前 not running，未发现旧 v1.10.4 根进程引用；本任务未重复切换。随后截至 `2026-09-08T07:00:00.000001Z`
  的 AU 真实矩阵审计返回 `PREFLIGHT_FAILED`，结果文件为空，仅保留通用错误码，不能声称矩阵已完成或定位真实原因。
  失败证据 `/private/tmp/newow-au-post-metadata-20260909-one/baseline.jsonl`；已停止外部操作、未重试。
  离线复现旧包装器不能序列化有效计划的 date 对象；预备入口增加类型序列化与安全 phase/error-type 记录，
  离线 3 passed；新的单次只读审计随后获准并完成，结果见下文。黄金历史行情补齐、
  真实矩阵验收与 8010/5174 浏览器验收仍未完成，未启动预览。所有临时 evidence 使用前须检查存在与完整性。

- `2026-09-09T04:32:40..04:34:19Z` 按新的单次批准在 `1f0ff619e` 完整执行黄金只读审计：
  `status=audited / complete=true`，12 个 section 窗口、132 项依赖全部完成，126 项
  `REPLAY_PREFIX_MISSING`、6 项 `DATA_READY`（AU2610 三周期在两个 as_of 边界），metadata proposal 为 0，
  无 source/integrity finding；主图仍为 0/9 ready，不能宣称页面恢复。provider、DB/Canonical writes、Redis、retry 均为 0。
  `/private/tmp/newow-au-audit-recovery-20260909-prepared/readiness.json` 文件 hash
  `1faddc07183e664bf861d410b79edab2c5f3b6a722eebdb72ec6ee12b3aeb0d5`。此成功不证明旧通用错误的真实原因。
  离线合并 21 合约的 63 个候选为 42 个 W1/60m 计划、904 个唯一物理分区；227 个独立 D1 窗口
  与 W1 伴随窗口逐项相同，故不重复执行。原生 provider target 计数 677 不是 public API 或 RPC 请求数。
  全部计划与 consumer provenance 见 `/private/tmp/newow-au-history-plan-20260909/consolidated.json`。
- 首批来源方案限定 `AU2304`，10 条精确交易所日行情请求覆盖 `2022-03-16..2022-12-30`，
  对应 2022-03..12 的 20 个 D1/W1 分区、196 根日线和 41 根周线。完整端点重建与原生 plan hash
  `9f4f789fc3cb0569bb43216c39d16f2b9f5cd8e60f1cb358ca4b14bf34853fad` 一致；独立 Review 已核验范围、
  日周去重与哈希。10 次调用仅是完整来源响应下的成功路径，必须用严格守卫拒绝缺日后的补充查询和越界调用。
  来源捕获守卫的 9 项离线测试通过，含缺日/重复/错合约及 timeout/GatewayError/PermissionDenied 单次派发，独立 Review 无代码阻塞；
  首批来源捕获随后按单次批准执行并停止，详见下文；Canonical 发布、补齐后矩阵与浏览器验收仍待完成。
- `2026-09-09T04:57:42..04:57:43Z` 在 `a54c51476` 执行 source-only 计划
  `e05dd542e8c35662a9cf0937bea5102ce7df350cc3bfd39089c2db7ac0107b91`，首个
  `AU2304 / 2022-03-16..2022-03-25` 请求完整返回 8 个源交易日后触发 `SOURCE_NONPOSITIVE_PRICE`，立即停批。
  实际 public API attempted/completed 均为 1，SDK RPC attempted/completed 均为 3（quota、type-list、日行情各 1）；
  原计划剩余 9 次行情请求未开始，无 retry，DB/Canonical writes 与 Redis connections 均为 0。
  结果 `/private/tmp/newow-au-history-plan-20260909/fetch-result.json`，逐请求事件同目录 `fetch-events.jsonl`；
  原始 `source-01.json` SHA256 为 `345ac234c465cb17e4e420e51fe5122e62f876038a550be29c1248b13ac17e17`。
  `2022-03-16/17/18` 三天均为 volume=0、open/high/low=0、close=400.12；其余五行 OHLC 均为正。
  现行 DATA_CENTER 零成交日规则允许用同一行有效 close 规范化全零 O/H/L，但本任务明确禁止填补原始零价，
  因而不能自动套用该规则写入或继续下载。仅离线生成三行前后对照并核验原响应未改动，见同目录
  `zero-volume-comparison.json`；该对照不是授权、真实修复或页面恢复。原捕获计划的执行意图已消费，
  当时停止等待零成交日处理口径；后续批准与剩余范围见下文，不重跑已取得的首个响应，不自动补取或发布。
- Owner 随后明确允许仅 `AU2304 / 2022-03-16、17、18` 三条零成交记录采用同一行 close 规范化 O/H/L。
  已通过现有原生纯函数生成独立本地候选，精确三行的 O/H/L 为 400.12，其他字段不变；原始来源 hash 保持
  `345ac234c465cb17e4e420e51fe5122e62f876038a550be29c1248b13ac17e17`。候选文件
  `/private/tmp/newow-au-remaining-source-20260909/approved-candidate.json` SHA256
  `945f2a26ec96494bfd5a294ca7c70d5f4333cda2cf213fcee1ea172943d3e5a9`；本步 provider、DB 与 Canonical 写入均为 0。
  本次例外不扩展到其他日期或合约，不等于 Canonical 发布授权。离线 21 passed，覆盖精确三行、原始响应保留、
  其他零价仅记录、OHLC 与其余五个来源数值字段的非有限值拒绝及剩余请求精确排除首个已完成窗口。
  新来源审计只包含原计划尚未启动的 9 个窗口、188 个源日期，范围 `2022-03-28..2022-12-30`，
  首批方案详见 `/private/tmp/newow-au-remaining-source-20260909/first-batch.json`。作为 raw source audit
  保留非正 OHLC 并列为 findings，不自动规范化或发布；连接、格式、身份、重复或覆盖错误仍立即停止且无 retry。
  此诊断用途与旧遇非正价格停批的捕获不同，随后取得新的精确单次批准，执行结果见下文。
- `2026-09-09T05:16:22..05:16:23Z` 在 `ccc93c1c7` 执行剩余来源审计，plan
  `d63b37c3f95c8be30fb3e24638aea6559b22d2c8343492915c0a2619620e4cc8`：9 次 public API、11 次 SDK RPC
  全部完成（quota/type-list 各 1、日行情 9），188 个日期完整，`captured_with_source_findings`；
  provider 操作无 retry，DB/Canonical writes、Redis connections 均为 0。逐文件哈希与事件见
  `/private/tmp/newow-au-remaining-source-20260909/fetch-result.json` 和 `fetch-events.jsonl`。
  唯一新增非正价格记录为 `AU2304 / 2022-03-31`：volume=0、open/high/low=0、close=397.26、open_interest=12。
  此日期不在已批准的三条例外中，保持原值，不自动规范化或发布。
  两批合并后 196 个源交易日与已捕获 Calendar 日期逐项相等、无重复；仅应用三条例外时 195 行通过原生
  CanonicalBar 校验，03-31 因 OHLC 包络失败。仅在内存假设增加 03-31 例外时，196 D1、41 W1 的原生
  构造与 20 个分区的离线范围校验通过；该对照不是授权或真实发布，未进行 fresh Catalog recheck、
  Parquet 写入/物理回读或页面验收。完整离线报告
  `/private/tmp/newow-au-complete-source-20260909/validation.json` SHA256
  `ddae25495bf8e6dacc70973ad0edc4e22480256d49d0061b58ea1ffb60079fe2`。
  首批全部源响应均已保留，后续不重查这 196 天；当时等待新增零成交日口径，后续批准见下文。
- Owner 随后明确允许本次黄金恢复的交易所日行情统一采用现行零成交日规则：仅 volume=0、
  O/H/L 全零且同一行 close>0 时，用该 close 规范化 O/H/L；原始响应保持不变，其他异常仍停批。
  该批准覆盖 AU2304 的 03-16、17、18、31 四日，不授权 Canonical/Catalog 正式写入。
  来源范围/失败锁定/归一离线测试 `5 passed`，只读准备脚本独立 Review 完成。
  `2026-09-09T05:35:49..05:35:50Z` 在 `a31962af3` 执行一次 fresh readonly preflight，
  `fresh_readonly_plan` 阶段返回 `OperationalError / PREPARATION_STOPPED`，立即停止、未重试；
  provider requests、DB/Canonical writes、Redis connections 均为 0。未保存异常原文，根因尚不确定，
  不能把本机 5432 端口存在监听当成 DB 连接成功。失败结果与审查版本脚本保留在
  `/private/tmp/newow-au-publication-prepare-20260909/result.json`、`prepare.py`。
  同轮 launchd 只读检查五项 installed/loaded root+commit 均为 v1.10.5/cdd72d750，旧 v1.10.4 根
  无相关进程 PID；After-market 为 not running、无 PID，不单凭此声明 idle 或整体 Runtime Ready。
  随后仅离线构建获批候选：196 D1、41 W1、2022-03..12 的 20 个临时 Parquet 严格写入/读回通过，
  完整 expected endpoints 来自已捕获 Calendar，重建 native plan hash 仍为
  `9f4f789fc3cb0569bb43216c39d16f2b9f5cd8e60f1cb358ca4b14bf34853fad`；不是从候选 Bar 自证覆盖。
  10 个源文件哈希不变。报告 `/private/tmp/newow-au-publication-prepare-20260909/offline-candidates.json`
  SHA256 `4dbc6b94d4822d26688d519daa9e4a2c8e52717d08a93fb67cf5db60fc05ec79`。
  该结果不含 fresh Catalog/Session 核对、正式发布或页面验收；本批发布准备仍被在线核对失败阻塞。
  随后获得一次新的精确只读诊断批准，`2026-09-09T06:06:03..06:06:04Z` 在 `4701c993e` 执行
  plan `e5cfd0e9a3706ae85b123effcb209b6684122ac8038200f4f36b71b55d342494`，仍在连接/只读事务阶段停止：
  `OperationalError / authentication_missing`，SQLSTATE 未提供；未进入 fresh planner，未重试，
  provider requests、DB/Canonical writes、Redis connections 均为 0。新结果单独保留在
  `/private/tmp/newow-au-publication-diagnostic-20260909/result.json`，不覆盖前次失败。
  离线定位为临时 runner 的初始化顺序错误：`find_spec(app.db.readonly)` 经 `app.db.__init__`
  提前导入 session 并创建缺认证 engine，随后加载 dotenv 不会更新既有 engine。配置本身存在所需认证，
  未输出凭据、未修改 `.env` 或 Runtime。禁止网络的 fresh subprocess 用合成配置复现旧顺序缺认证、
  新顺序有认证；新 runner 先加载既有配置和校验目标/认证存在，再检查模块来源，连接前再次校验 engine。
  `/private/tmp/newow-au-auth-order-fix-20260909/` 中范围、归一、错误脱敏与初始化回归测试 `13 passed`；
  当时新 runner 仅准备，等待新的单次 AU2304 只读执行意图；后续结果见下文。
- `2026-09-09T06:13:05..06:13:07Z` 在 `a88546307` 获准执行修正后唯一只读核对，plan
  `6da1eb2b633bd63d525fca8de6a03ae18939cba0976b61c1c868e3d9d4248bb0`，exit 0、passed；
  认证初始化阻塞关闭。native plan 仍为 `9f4f789fc3cb0569bb43216c39d16f2b9f5cd8e60f1cb358ca4b14bf34853fad`，
  fresh snapshot 确认 Dataset 1670/1671 已有，AU2304 的 2022-03..12、1d/1w 共 20 个 Catalog 键完全缺失。
  原生 adapter 仅读取 10 个保存的来源响应，4 行按获批规则规范化；196 D1、41 W1 经当前 Calendar/Session
  边界校验，20 个临时 Parquet 严格回读通过，字节 hash 与此前离线候选一致。provider requests、
  DB/Canonical writes、Redis connections 与 retry 均为 0，不能把 adapter 的本地来源读取计成新 RQData 请求。
  结果 `/private/tmp/newow-au-auth-order-fix-20260909/result.json`；fresh-plan 文件 SHA256
  `e4279976155fd8d26456e71e91b7acc580a2aa40afcbfe1a0c99f81e4842fa1b`；publication-plan 文件 SHA256
  `b63662b6db119c4d973095a61c7af48be32d66996a1adca9119ecddcdd3f9fac`。独立本地证据复核通过，未重复连接 DB。
  首批下一步仅规划新增上述 20 条 Catalog 分区记录与最多 20 个 immutable hash 文件，既有两个 Dataset 不变；
  精确 URI 本地扫描当前 20 个文件均不存在，执行仍须在原生维护锁内重查计划、缺失键、文件与消费者身份。
  `/private/tmp/newow-au-publish-once-20260909/` 已准备 captured-source 原生发布 wrapper；离线及独立 Review 各 `20 passed`，
  覆盖真实 SQLite flush/commit 事件、越界/更新/删除拒绝、候选与旧 Runtime 身份拒绝，以及原生
  `COMMIT_OUTCOME_UNKNOWN` 停止后续分区。SQL/Catalog 只允许目标单行 INSERT；逐分区提交，全成功后
  新开只读事务经 MDS 读回。失败保留成功分区与候选，无自动 retry、指针反转或旧 v1.10.4 回退。
  当时为 `EXTERNAL_GATE_PENDING`：首批尚未执行，后续获准结果见下文。
- `2026-09-09T06:27:22..06:27:27Z` 在 `955d3f016` 执行获准的唯一首批发布，execution-plan
  `1505d96db5c2a5ef1849310cfcd2c62705c2cb64fa65573c1bf25ae9972c321f`：exit 0、passed，AU2304
  2022-03..12 的 1d/1w 共 20 分区全部完成。锁内重查、五项现役消费者 v1.10.5 身份及 P1 源码核对通过；
  20 个精确文件目标原不存在，新增 20 个 immutable 文件及 20 条 Catalog 记录，20 次唯一 commit，
  无 Dataset/Calendar/Session/Scope/Redis 写入或通知。0 次新 RQData 请求、10 次保存来源读取、
  20 个 native logical provider targets 分开计数，无 retry。
  同次执行完成后的独立只读事务经 MDS 核验 20 个 URI/hash/全部 Bar 通过；readback SHA256
  `0bf9bde5e8481c1432ff8812ddf8fbea265442ec6aaf9cc51bec1bef69e6aaa4`，为 196 D1 + 41 W1。
  本地独立 Review 另按 exact manifest 读取正式文件确认全部 hash、237 端点、20 个唯一提交事件及来源 hash；
  evidence 位于 `/private/tmp/newow-au-publish-once-20260909/`。本批状态 `COMPLETED`，不代表完整矩阵恢复；
  已消费计划不得重跑。保留候选与已提交文件，不自动回收或回退旧 Runtime。
- `2026-09-09T06:35:26..06:35:43Z` 一次仅 AU 的剩余日/周只读规划通过；AU2304 D1/W1 剩余目标为 0，
  其余 AU2306..AU2608 的 20 个物理合约 native plan hash 逐一与原审计相同，合并 D1/W1 后尚有
  430 个分区（217 D1、213 W1）。按原生分组与当前 Calendar 逐窗口枚举为 231 次 `futures.get_exchange_daily`，
  3978 个不重复 contract-date，整体源日期范围 2022-05-17..2026-05-25；逐合约范围、请求与目标见
  `/private/tmp/newow-au-remaining-daily-plan-20260909/plan.json`，文件 SHA256
  `ae6834bf6036b340a8e5ce4598716efed1c50b317012f86c20105dad11ee0b8d`。本次 provider requests、DB/Canonical writes、Redis connections 均为 0。
  新 captured-source 查询脚本与计划位于 `/private/tmp/newow-au-remaining-daily-source-20260909/`，
  离线及独立 Review 各 `40 passed`；SDK 最多 231 次数据 RPC + 3 次初始化元数据 RPC，关闭 retry/pool/fallback。
  原始响应不改写，已批零量全零 O/H/L 且同 close>0 规则仅用于校验例外；其他价格、数值、覆盖、身份或
  来源错误立即停。当时仅准备；随后查询结果见下文，430 分区正式写入仍未执行。
  60m 所需 1m/60m 历史依赖、完整真实矩阵和 8010/5174 浏览器验收仍未完成，不能以此日/周计划替代。
- `2026-09-09T06:51:32..06:51:34Z` 在 `e0c9719c4` 获准执行唯一来源查询计划
  `bdf1fe1524f8bf7e85cbf8376cd634ee13c45972564d0dca442304d3d372c72d`，第 13 次 API 后失败停止，
  `SOURCE_CAPTURE_STOPPED`，无 retry。实际为 13 API attempted/completed、15 SDK RPC attempted/completed
  （quota/type-list 各 1、日行情 13），不是执行全部 231 次；218 次尚未开始。DB/Canonical writes、Redis connections 均为 0。
  AU2306 的前 12 个响应已按 hash 保存，202 个源日期完整；唯一非正价格记录为 2022-05-17 的已批准
  零量全零 O/H/L、正 close 例外，原始值未改写。该合约来源已齐，但 22 个分区的完整候选与写入未完成；
  新来源对应 missing D1 202 / W1 41，完整候选还须保留已有 14 D1 / 3 W1，不能仅以新来源替换完整月份。
  第 13 个请求为 `AU2308 / 2022-07-18..2022-07-29`，返回 10 行并通过合约与日期检查；
  随后在响应转换/编码/落盘范围内失败，`source-13.json` 未生成，具体异常类型及原响应未保留。
  不得推断前次实际含 NaN，也不得把后续新查询当成该次未保存响应。result 文件
  `/private/tmp/newow-au-remaining-daily-source-20260909/fetch-result.json` SHA256
  `86a64346317a10e4784ce2fdf55f7981221b4a5effae2926de6f2596cb979daf`；原始文件与逐请求事件保留在同目录。
  新单窗口诊断准备在 `/private/tmp/newow-au2308-source-diagnostic-20260909/`，仅 AU2308 上述 10 个日期，
  1 API、最多 4 SDK RPC；显式类型标签保存 NaN/Infinity/missing 等值，不替换为 0/null，不规范化或发布。
  增加安全 phase、error type/code、OS errno；离线及独立 Review 各 `12 passed`，当时未执行新查询。
  该阶段等待新的单窗口诊断意图，后续获准结果见下文；失败批次授权已消费，不重查已保存 AU2306，
  不自动启动余下 218 次请求，不写生产数据。
- `2026-09-09T07:10:32..07:10:34Z` 在 `042272852` 获准执行一次独立 AU2308
  `2022-07-18..2022-07-29` 诊断，计划 `da20b1f0833fa6ea53cde846243aaf5935db9b6d3f1b0727845291658782f1b7`。
  结果 `captured_with_findings`，1 API / 3 SDK RPC attempted/completed（quota、type-list、日行情各 1），
  10 个日期全部保留，DB connections/writes、Canonical writes、Redis connections、retry 均为 0。
  `2022-07-18/19/22/25/26` 五日的 O/H/L 均明确为 float NaN，volume=0、同一行 close>0；
  现有 DATA_CENTER 与原生 adapter 的同时全空 O/H/L 规则覆盖该形态，未改变合同、原始值或发布数据。
  本次新响应不能证明此前未保存的第 13 次响应内容，也不能被补写为此前失败轨迹。
  独立 Review 已核验计数、日期、原始类型与 hash。证据目录
  `/private/tmp/newow-au2308-source-diagnostic-20260909/`：typed-raw-source SHA256
  `6c2bbdc422fe1c43b32cf99a818ff9039936df0d16efad50fa0348881eede65d`；result SHA256
  `b4f38b8f954c77ec126e63b273bd87e4db37267b25e230af7ddc252ba7a50562`。
  剩余新计划在 `/private/tmp/newow-au-daily-source-resume-20260909/`：严格为原只读计划 public_requests[13:]，
  AU2308..AU2608 的 19 个合约、218 次日行情 API、最多 221 次 SDK RPC，3,766 个唯一合约日期，
  来源日期 `2022-08-01..2026-05-25`。已保存 AU2306 的 12 个窗口和本次 AU2308 窗口均排除；
  原始来源使用明确类型标签保存，检查复用原生全空/全零零量日规则；其他异常仍停止。
  新来源脚本离线与独立 Review 各 `62 passed`；计数、范围、保留源 hash、失败停止及无写入路径复核通过。
  新 218 次查询、后续正式日/周分区写入均未执行，分别需要新的单次明确意图；完整矩阵和本地浏览器验收仍未完成。

- 2026-09-09 AU2304／2022-03-16 的已获准单次时段查询确认：来源含夜盘，本地 SHFE Calendar
  id=46796 原为 `has_night_session=false`。owner 新的单次批准已于 `2026-09-09T03:13:36Z`
  消费：使用 `79c59ccb4` 受限入口，仅将该行夜盘标志更正为 `true`，其他字段不变，提交后独立只读核验通过。
  本次 `database_writes=1`，`provider_requests=0`、`session_writes=0`、`canonical_writes=0`，无重试。
  精确 plan hash `2384a9cc382c94fb1616d0f508006fd374b3a6b6c6673c5823ff301e574749a7`；
  原结果 `/private/tmp/au-calendar-apply-20260909-zQDruw/result.json`（临时 evidence 不保证长期存在）。
  单键更正为 `COMPLETED`，不代表 Newow 整体恢复；其后 Calendar/Session 与首批历史行情进展见上文，整体恢复仍未完成。
  独立规范/需求 Review 无剩余阻塞；完整后端与 engineering 非隔离回归合计
  `2967 passed, 16 skipped, 28 deselected`，另有单键隔离 PostgreSQL `7 passed`，
  Ruff/Mypy/OpenSpec/secret/diff 通过。旧批次计划已因前像变化失效；当时剩余的 173 个候选日期已由上文新来源审计区分。
  旧 613 次查询与旧单键更正授权均已消费，后续操作仍须重新核对范围，不自动重跑。
  不授权其他日期、RQData、Canonical、发布或 Runtime 切换，也不自动逆向恢复旧标志。具体边界见 `docs/DATA_CENTER.md`。

- P6工程已集成并发布，产品仍为 `P6_COMPLETE / PARTIAL_PRODUCT_EVIDENCE_REQUIRED`。
  [P6历史只读证据](docs/research/newow-v3.2.82/P6_TRUSTED_CLOSURE.md)归属v1.10.0：首30品种两轮及rb45项
  均HTTP500，`REAL_WORKSTATION_MDS_REQUEST_PATH=MEASURED`，成功路径性能未验收。
  MDS缺失映射转typed `NEWOW_DATA_UNAVAILABLE / HTTP409`的修复已包含在v1.10.4代码中；错误分类修复不补数据。
- 缺少截至as_of已生效owner时必须fail-closed。把owner窗口缩到最后completed display/performance日的方案
  已因破坏rollover与segment身份被拒绝，不能重试此“修复”。原2026-09-08只读repair计划已过期。
  后续使用现有bounded readiness审计重新枚举当前依赖，再区分metadata与physical warm-up；不得重跑旧hash。
- 2026-09-08获准的RB2701/RB2605/RB2610有界1m+60m补齐为39/39分区、15次RQData请求；
  三合约60m读回1,084/1,509/1,502根。该批准已消费，不授权其他周期/合约。
- 同一固定历史rb60m样本优化前后各五组新进程/同进程结果一致；DB语句2,433→89，冷/热HTTP中位数
  2,210/2,167ms→536/488ms，未清除OS/磁盘缓存。照妖镜12组有界绘图对照像素差0，
  不代表全产品、60品种SLA或在线全页面parity。该读取/显示改进已包含在v1.10.4代码中。
- 原件缺口继续为 `EVIDENCE_REQUIRED`：诊断token、六组合评分/排序、AI逐字copy、目标/吸筹的权威昨收与
  期货owner parity、比较器browser-final/tie golden；当前Core原包重放有接口漂移。
  杯柄D1 clean-room不是原页面精确公式；18个D1/60m OOS及9个W1执行事实不足不升级为新的`OOS_PASSED`。
- develop在v1.10.4之后另有有界旧窗口、快照/导航原子接受、只读readiness矩阵、分阶段metadata repair、
  默认关闭的本地候选预览与可信报价截止修复。代码入口和验证命令分别见架构文档与`TESTING.md`；
  这些代码没有因集成获得真实下载、DB/Canonical写入、release或Runtime授权。fixture不证明真实矩阵可用。

## 剩余 Gate

1. 发布并部署已审的身份解析修复后，重新完成exact-tag身份验收；自然completed Bar评估、当前60品种
   readiness及新版本自然盘后证据仍需独立核验。现有旧failure不得手工清除来制造通过。
2. Newow在当前权威owner/coverage完整后完成真实成功请求矩阵；原站parity与期货OOS/Walk-forward缺口独立处理。
3. Market 统一详情页实现、测试、独立 Review 与 owner 桌面/390px 视觉接受已完成；
   本轮仅授权 develop 集成，发布及 Runtime 切换仍不在授权范围。
4. HTDY目标61对Scope未应用；BU/BZ D1/W1异常未关闭。数据修复、Scope、真实通知、main/tag/release与Runtime
   操作均需新的目标/环境/范围明确的单次意图，不沿用本文历史授权。
