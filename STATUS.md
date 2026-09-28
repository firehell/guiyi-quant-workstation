# 当前状态

更新：2026-09-28。本页只保存当前交付状态、证据入口和未完成事项。历史检查点从 Git 和对应任务证据查找，
不再把旧版本“当前状态”按时间堆在本页。执行授权见 [AGENTS.md](AGENTS.md)，版本维护见
[开发流程](docs/DEVELOPMENT.md#文档与版本的唯一入口)，产品边界见 [PROJECT_SOURCE.md](PROJECT_SOURCE.md)。

## Release 与 Runtime

最新正式发布为 **v1.10.39@653e736f5952146a2ea401634d32a605e7b9a0d5**。
PR #404、annotated tag 与非草稿/非预发布
[GitHub Release](https://github.com/firehell/guiyi-quant-workstation/releases/tag/v1.10.39) 已读回；main 源码树与验证候选一致。
新增日周 AI 分析、综合决策和状态摘要、双策略参考曲线与近一年记录，以及默认关闭的 RB 分钟历史候选。
发布说明见 [v1.10.39](docs/releases/v1.10.39.md)。候选验证：Web 719 passed / 1 skipped、后端245 passed、
数据352 passed、格式修正后19 passed、定向浏览器6 passed；build、lock、Ruff、Newow spec、secret scan通过。
旧 Newow fixture 扩展套件有合同漂移，本轮尝试保留失败输出并中断，不声明全套 E2E 通过。
本机原始日志仅保留于 `outputs/release-v1.10.39-20260927/`，未纳入本轮发布提交。

**现役 Runtime 已切换为 v1.10.39@653e736f5952146a2ea401634d32a605e7b9a0d5**。
源码根为 linked worktree `/Volumes/扩展盘/guiyi-quant-workstation/.worktrees/release-v1.10.39`，detached/clean。
冻结依赖和 build、render-only、Market preflight（non_trading_interval，60品种）通过；
Market/base/Alert/weekly安装完成，六服务 root/commit、API版本1.10.39、HTTP200连续读回通过。
运维状态脚本 overall=passed，runtime health=ok/readonly=true；新根盘后 pending，
休市 Live/Alert coverage仍unverified、Alert组件degraded、weekly missed独立披露。
health=ok只证明当前运维检查，不证明首次自然业务、全部Alert覆盖或RUNTIME_READY。

旧v1.10.38根clean且配置/loaded服务/进程引用均为零；盘后JSON逐字节保留后，以非force Git worktree remove退休。
现在仅保留最新发布树，不删除tag、数据、安全配置或用户outputs。历史23项weekly finding和P9阻断未解决。
本轮不重跑盘后/周检、不清除健康错误、不回放Event或补发通知；operational/Rule/Scope/audience及auto_order=false不变。
本机切换与退休证据位于 `outputs/release-v1.10.39-20260927/`，不提交原始运行日志。

首根自然completed Bar、盘后增量/MDS与weekly结果仍待验收，**不声明RUNTIME_READY**。

## 当前产品与验证范围

- Newow 日周三策略以及日周 CDV2 解释、独立双策略入口已随 v1.10.38 交付；主图、辅助、参考曲线分层；v1.10.39参考记录已扩展为近一年。
  Newow 60m 未开放，日周解释不构成 StrategyDecision、模型账户或真实交易。
- 正式 60 品种 D1/W1 默认快照、质量断点与预热披露已完成本轮数据/页面验收；不是每个组合均 READY 或盈利的声明。
  来源不足、WARMING、报价不可用及数据中断仍按合同表达。
- 正式 JM 日线页面主图/辅助/参考收益及双策略入口已读回；普通 74 笔累计 183.66 是页面参考统计，
  理论值与普通参考曲线具有独立口径，不是账户收益。
- v1.10.38 冻结发布验证：前端 691 passed / 1 skipped、后端定向 171 passed、隔离浏览器 6 passed；
  build、Ruff、Newow spec 与独立 Review 通过。工程检查 22 passed / 1 既有截图批准库存失败；
  旧分页 E2E 漂移与全模块测试中断已披露，未声明全量通过。以上仅归属冻结发布候选。
- 当前持续服务保持既有 operational 集合、Rule/Scope/audience（2）及 transport；reference worker 关闭，
  `auto_order=false`。本页不授权新增数据范围、通知、订单或可选定时任务。

日周数据与验收依据：
[W1 收尾](docs/tasks/newow-w1-closeout-20260926.md)、
[W1 页面验收](docs/tasks/newow-w1-page-acceptance-20260926.md)、
[日周发布及 RS 修复](docs/tasks/newow-d1-w1-release-v1.10.36-20260926.md)。
SuBing 已有自然 Event/实际收件闭环归属旧 exact `v1.10.5@cdd72d750`：2026-09-09 Event #143–#146，
owner 确认 #146 PT2610 14:00 对应微信收件。该完成事实不重开，也不证明当前版本或其他受众实际收到。

来源版本与公式复刻边界见 [当前研究复核](docs/research/newow-current-review.md)；历史原站证据不等于当前期货 OOS。

## FU 四周期历史候选暂缓（2026-09-28）

最新 P7 逐品种队列 **P7-01 FU：DEFERRED_DATA_BLOCKED，0/12页面闭环**。精确依赖84项中最终7项完整，未建保存流；仅FU2305新增8个1m源和32个派生分区，原351分区不变。FU2309首个1m源月（2022-09）`ATOMIC_PUBLISH_FAILED`后停止，无重试；49个七周期前像及SHA不变、失败目录空、零Catalog发布、共享维护锁0。失败请求实测计数缺失，按单月路径推断1但不伪记为零；当前供应商剩余额度1,050,811,952 bytes，同盘隔离发布读回通过。

独立Review允许安全暂缓；无本次已证实的持久共享污染或阻塞，失败底层原因仍UNKNOWN，不宣称FU专属数据质量问题。P7-02 MA按自身精确计划/存储/预算preflight可继续，由总控安排；本会话不创建下一项。正式发布/Runtime/Scope/通知/账户未变。实际plan/hash/attempt、40分区URI、12项状态和恢复边界见 [FU处理记录](docs/tasks/fu-minute-closeout-20260928.md)。

## JM 四个派生分钟周期历史候选（2026-09-28）

JM **5m/15m/30m/60m × 趋势/震荡/独立双策略，12/12 历史候选闭环完成**。95 个 5m 派生维护目标全部读回、零 provider；140 个完整物理前缀月、176,205 根 Bar 独立重算一致。5m 三条新保存流与其余九条复用流均 READY、disabled/generation=0，精确截止 2026-09-24；1m 仅聚合输入，不验收 Newow 1m 显示或策略。

候选冻结 `a9f3ab4a20bfbdecf3cd1cecebed1642a8da41b2`，产品源码与公式未改。任务维护脚本补齐首次创建目录的父目录 fsync，10 项定向测试通过；意外退出后独立证明融合六表零写入，保留原 attempt/plan，以受控零写入恢复完成原计划，不伪造 ResumeToken 或盲目重跑。152 API GET、325 浏览器响应、12 组合、37 张原图、日周 6 模式/112 响应、取消/超时及快照恢复均通过，最终独立 Review 允许集成 develop。同日分页 4 PASS/8 实际 NA，四个双策略均保持 50→100 条追加；W1 趋势转折仍如实预热，更早主图窗口分页未测。按本轮要求未反复全量检查。

JM 只读候选 API 8012/Web 5178 接替 J 预览，旧 I/J 资产、证据与工作树保留。正式 v1.10.39、Runtime、worker、Scope、通知、订单及 `auto_order=false` 不变；未发布/晋升。实际命令、证据与恢复边界见 [JM 分钟闭环](docs/tasks/jm-minute-closeout-20260928.md)。

## J 四个派生分钟周期历史候选（2026-09-28）

沿用相同范围，J **5m/15m/30m/60m × 趋势/震荡/独立双策略，12/12 历史候选闭环完成**。96 个 5m 派生维护目标全部读回、零 provider；141 个完整物理前缀月、179,310 根 Bar 独立重算一致。5m 三条新保存流与其余九条复用流 READY、disabled/generation=0、精确截止 2026-09-24；1m 仅可信聚合输入。

最终候选 `90c9808a5` 已集成 develop，修复页面内部融合读取排队及主图翻页后参考记录重置，固定服务端预算与公式不变。73 项定向测试、Web 754 passed/1 skipped、构建及独立 Review 通过；152 API GET、322 浏览器响应、十二组合/root 24 原图、日周六模式/112 响应/root 12 原图、取消/超时恢复/root 1 原图和快照恢复全部通过。同日分页 3 PASS/9 实际 NA，旧 429/分页失败保留，日周趋势转折预热如实披露。

J 只读候选使用 API 8012/Web 5178，I 两个旧预览进程已精确停止，I 资产/证据/工作树保留。正式 v1.10.39、Runtime、worker、Scope、通知、订单及 `auto_order=false` 不变；未发布/晋升。完整范围、命令和恢复边界见 [J 分钟闭环](docs/tasks/j-minute-closeout-20260928.md)。

## I 四个派生分钟周期历史候选（2026-09-28）

沿用 RB/HC 的 **5m/15m/30m/60m × 趋势/震荡/独立双策略**，I **12/12 历史候选闭环完成**。94 个 5m 派生维护目标全部读回、零 provider；139 个完整物理前缀月、173,286 根 Bar 独立重算一致。5m 三条新保存流及其余九条复用流均 READY、disabled/generation=0、截止精确 2026-09-24；1m 仅聚合输入。

固定第三候选端口支持 `604a338` 已集成 develop；API 8012、Web 5178 与 RB/HC 分离。实际 152 API GET、325 浏览器响应、十二组合及 24 原图审核、日周兼容、取消/超时/快照恢复和独立 Review 通过。正式 v1.10.39、Runtime、worker、Scope、通知、订单及 `auto_order=false` 不变；未发布/晋升。实际验证与恢复边界见 [I 分钟闭环](docs/tasks/i-minute-closeout-20260928.md)。

## HC 四个派生分钟周期历史候选（2026-09-28）

沿用 RB 的 **5m/15m/30m/60m × 趋势/震荡/独立双策略**，HC **12/12 历史候选闭环完成**。93 个 5m 派生维护目标全部读回、零 provider；138 个完整物理前缀月、173,385 根 Bar 独立重算一致。5m 三条新保存流与其余九条复用流均 READY、disabled/generation=0、精确截止 2026-09-24；1m 仅可信聚合输入。
冻结业务源码 `e936651187f1e074bf5e1f2205bf22ad03657f30`，无需业务代码改动；72 项定向测试、152 API GET、12 真浏览器组合/322 响应及 root 24 张原图审阅通过，高风险维护、构建、当前 PG、API/UI 与工具均独立复核。同日分页 3 PASS，3 无下一游标与 6 实际跨日保留 NA；日周六模式兼容回归和 12 张截图通过，W1 预热披露不变。
候选 API 8011、Web 5176 与 RB 分离；正式 v1.10.39、Runtime、worker、Scope、通知、订单及 `auto_order=false` 不变；未发布/晋升，也未外推其余黑色系品种。详细范围、实际输出与恢复边界见 [HC 分钟闭环](docs/tasks/hc-minute-closeout-20260928.md)。

## RB 四个派生分钟周期历史候选（2026-09-28）

owner 本轮调整分钟产品为 **5m/15m/30m/60m**；1m 仅可信聚合来源，Newow 1m 显示与策略产品留独立版本，旧入口 fail-closed。本轮 RB 趋势/震荡/独立双策略 **12/12 历史候选闭环完成**：95 个 5m 派生分区维护、零 provider、140 个全物理前缀月分区独立重算一致；12 条保存流 READY 且 disabled/generation=0。
冻结业务候选 `82a27a322e3b53631aa40b9f087d69ec7086a9e3`，develop 集成 `a15ab71f0`，生产源码一致；集成后 693 项定向测试通过。152 实际 API GET、12 真浏览器组合与 root 原始截图审阅通过；同日分页 4 PASS，其余实际无下一页/跨日 NA 保留。D1/W1 六模式初屏/曲线/记录/辅助/返回回归完成，W1 预热原因保留。
既有 D1 更早主图分页的报价截止/快照时间冲突仍失败，基线同样拒绝，未计为本轮回归通过。范围、真实命令/输出与证据见 [RB 分钟闭环](docs/tasks/rb-minute-closeout-20260928.md)。

本节覆盖下文旧 `1m/15m/30m/60m` 的本版范围；旧批次矩阵保持历史身份，不将移出 1m 写成通过，不外推其他品种。正式 v1.10.39 分钟入口、Runtime、worker、Scope 和 `auto_order=false` 不变；本轮仅本地只读历史候选，未发布/晋升。HC 同范围验收已完成，见上节；其他品种仍待逐个验收。

## 旧首品种历史候选证据

P0–P6 首轮工程与隔离验收已完成并快进集成 develop，集成后定向回归通过。RB `1m/15m/30m/60m × 趋势/震荡/独立融合` 的
4输入、8基础保存流、4融合流与12页面模式都有证据；36期货边界样本、48辅助、上市预热、同日分页、
容量/取消、真实Chrome及高风险独立Review已完成。精确实现候选为 `10d40faa05badc04c86cefb65c53525a11dba4fb`，
本节不把后续文档提交当另一轮业务实现。

P0–P6 首轮候选默认关闭、当时只在隔离preview对RB开放；资产只写隔离schema `newow_intraday_pilot_20260927`。
P0–P6 首轮复用已有Canonical，实际缺口为零，provider/Canonical/Market Catalog mutation均为零。
正式日周开关、worker、Scope、Runtime与 `auto_order=false` 未变。分钟工程源码随 v1.10.39 发布但正式入口仍关闭；P7全量、Runtime切换、观察启用、通知、
订单及因果/OOS研究未执行。SQL/hydrate取消有界但非即时；旧7项fixture漂移与既有reference-trading
OpenSpec结构失败单列，没有声明全套通过。详见 [首轮执行与验收](docs/tasks/newow-intraday-pilot-20260927.md)；
P7 首批 black + steel 八品种已进入隔离历史候选验收；与首轮范围不同，不沿用此处的零缺口结论。
精确维护、资产、当前 API/浏览器实测与 SS 阻断见 [首批任务记录](docs/tasks/newow-intraday-black-20260927.md)。
正式分钟入口仍关闭，整个 P7 未完成。

## 统一参考交易与数据恢复未完成项

P0–P8 工程和隔离验收已经集成；**P9 生产闭环未完成**。Newow 页面参考投影验收不等于持久化统一参考交易验收。

- 460 个 SuBing D1 质量候选已一次性原子发布；生产读回 `already_applied=460/460`、`old_count=0`。
  3,113 个源 Close=0 分类为 `NONPOSITIVE_CLOSE_SOURCE_FACT`，保留 5,175 根有效 Bar 与显式质量事实。
  精确备份及 journal：`outputs/reference-p9-d1-quality-20260925/`。
- 首波 175 单元 warm-up 中前 6 单元已提交、读回 80 个分区，已知 provider 请求 21 次。
  第 7 单元 `al/AL2302/15m` 为 `UNIT_OUTCOME_UNKNOWN`：22 个目标仍未发布、请求次数无法证明，
  **未重试，余 168 单元未启动**。结果不明保持阻断，不用重规划缺失证明请求可安全重试。
- 最近一次 600 流只读审计为 `SOURCE_READY=387 / BLOCKED=213`；之后 15 条 W1 流复核中 SC/SI 六条
  SOURCE_READY，PL/PX/RS 九条仍为 `REFERENCE_BOUNDARY_CONTEXT_MISSING`。这些是对应旧精确提交的审计，
  当前版本完整矩阵、历史构建与持续更新须重新绑定 exact code/input identity，不能沿用旧结论。
- 未完成 0048 migration、剩余历史构建、全局 persisted reader 切换和 reference worker 启用；
  P9 持久化“统一参考交易”面板的既有 503 未关闭。Newow 页面参考投影不受此结论替代。
- A2611 旧来源请求已按 `SOURCE_RESPONSE_IDENTITY_INVALID` 停止且禁止重试；后续 D1 修复后重审无新恢复目标，
  不是对旧请求的重试。六个 W1 新批次共 64 个 W1 与 64 个 D1 同源上下文目标通过，来源 journal 64 次请求。

完整 P9 证据与恢复边界见 [rollout](docs/tasks/unified-reference-trading-p9/rollout.md)，
`outputs/reference-p9-warmup-wave1-20260925/`、`outputs/reference-p9-source-inventory-20260925/`。
旧盘后 D/E/F 已关闭，不重跑；旧事故未证明的生产归因继续保持证据不足。

## 已接受的后续交付规划

日周交付 → 关闭已记录页面缺口与自然维护验收 → Web 体验改善与分钟数据准备 → 分钟产品独立验收开放。
当前日周交付已发布；不能再按旧 v1.10.8/v1.10.9 检查点把该阶段重开，或把最新切换认定为自然验收通过。

- Web 正确性随对应版本验收，纯 Web 改善不等待分钟补数；不顺带改变公式、参考收益或数据来源。
- 分钟准备由同物理合约 Canonical 1m 派生，复用 Catalog/MDS、Session、质量校验、维护锁与预算；
  去重窗口、有源先派生，只对明确缺失安排恢复，失败按合同停止。补数完成不自动开放产品。
- 分钟开放分别验预热、Session 聚合、换主力、completed Bar、参考记录、分页与故障状态；
  跨周期解释保留 bar_end/as_of，不用未来完成周线回填历史决策。
- 策略公式、页面参考、因果研究、OOS/Walk-forward、Shadow 和账户事实分别验收；解释评分不自动成为执行 Gate。

分钟 P0–P6 已集成并随 v1.10.39 发布源码；P7 首批八品种历史候选正在隔离验收，正式开放及后续批次未执行。
本批数据/资产/API读回代码冻结 `c576b3614ff79c26ee5a192cb3b0fb1449710240`：28/32 输入 READY、56/64 基础与28/32融合资产独立读回通过；96项真实 API 为84 READY、SS12 BLOCKED。owner 于本轮明确暂缓 SS 数据修复，当前验收范围为 RB、HC、I、J、JM、SF、SM 的84组合；原96项分母保留，SS12记为 `DEFERRED_DATA_BLOCKED`。第一版接受1m加载较慢，性能优化不作为收尾条件；身份、数据质量和页面正确性仍须逐项通过。reference快照恢复修复已集成develop `00cea970e7e87295ddcc89f7937a34430fb64b11`（97项定向测试、构建及独立Review通过）；新隔离页面/API验收实例为同树的 `9dd3714e596c1f5aebd6579b3f583fc2def93fe7`，原c576证据按后端依赖对象一致证明复用、保留原身份。真实页面84组合尚未终验，不能声明当前范围或整个 P7 完成；详见 `docs/tasks/newow-intraday-black-20260927.md`。

## 唯一下一步

按最新 exact Runtime 版本完成自然 completed Bar、盘后增量/MDS 和 weekly 的证据读回；
期间页面已确认缺口与 P9 未知结果分别按各自合同处理，不制造 Bar、不盲目重试，也不扩大现役运行范围。
