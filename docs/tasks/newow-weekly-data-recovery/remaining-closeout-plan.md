# 牛哇周线剩余工作：数据恢复与产品验收实施方案

日期：2026-09-15。状态：`PLAN_READY`，不代表数据、产品或外部 Gate 完成。
执行者：一个 `gpt-5.6-sol` / `medium` 新任务，在隔离工作树按 `superpowers:executing-plans` 连续推进。
本方案是当前执行入口；旧 `remaining-123-implementation-plan.md`、`ordinary-full-closeout-plan.md`
保留历史与已有设计，冲突的旧步骤/余额不再作为本轮输入。

## 目标与设计选择

完成固定历史截点的普通 W1 数据恢复、来源异常结算、60 品种三策略与真实页面验收；如权威来源无效，
交付明确未完成对象和证据，不承诺制造全绿。优先复用原生入口，必要的代码修改只用于已复现的阻断缺陷。
选择固定历史范围重新审计，便于与前次结果对账；不采用滚动扩大到当天的补数方案。
复用已保存来源，避免反复取相同坏数据；不重建丢失旧回执、不开发通用恢复平台。

唯一链路：RQData -> staging/hard validation -> Canonical -> 八表 Catalog/MainContractMap -> MDS。
W1 复用原生同源 D1 companion；不新增行情 resolver、替代价、插值、删坏行或跨频回退。
策略状态、页面参考交易与真实成交分离；page_parity=true、executable=false，不改公式/收益/配对语义。

## 当前基线与已有成果

- 本轮主仓库 HEAD `e6bff48bfb8967b37b9e07b8f59eebb43c935cc2`；开始执行时重新核对最新 develop。
- 隔离比较/失败诊断/严格整数修复 `43b073295` 已经由 `6547c7793` 集成并推送 develop；合并后相关测试
  558 passed，双轴 Review 0 finding。不得再次实现同一修复；最新工程规则采用 Sol medium 默认。
- 前次 attempt `ordinary-remaining-frozen-20260915-002-apply-001` 已消费并结束：39 成功、
  B2411 隔离1、BZ2605 停止失败1、974 未尝试、unknown0。39成功提交1,034 targets，补齐11,731端点，
  内置 Catalog/Parquet/MDS 读回及 remaining_target_count=0；尚缺新的独立读回及全域后审计。
- campaign-result SHA `224c8be90b99a74865f146350cc61d867b48637709544e3ff2686ca945d9ad0e`。
  974 只是前次冻结包未尝试数，不是当前原生审计余额。
- B2411 已重新 source-only 取证；BZ2605 两份原始响应/journal在，applied=0，已离线通过原生source proof。
  九个RS既有来源证据已核验，仍为来源非正与 REVIEW_REQUIRED；不能把原因查明计作修复成功。
- 旧102成功对象清单与旧执行总包仍缺失。新操作证据独立完整，不伪造历史证据连续性。
- 08:20完成的日/周/60m输入核查早于09:07结束的最新补数；8个日周完整品种结论不可冒充补数后最新统计。
- 当前正式 Release/Runtime 身份只看 STATUS；本任务不发布、不切换，也不以候选验收宣称线上已更新。

## 代码与证据落点

代码在平台创建的独立 worktree，必须纳入最新 develop 和本方案，默认起点若为 main 不能直接执行旧代码。
证据共同根固定 `/Volumes/扩展盘/guiyi-quant-workstation/outputs/newow-weekly-recovery-attempts/`，
位于主仓库，不移入任务工作树。所有执行器共用该根的原生 writer guard；不得另建可绕过互斥的根。
新 attempt/审计目录独占创建、不覆盖，原始证据保持不变；本任务结束前不清理任何相关工作树或证据根。
普通审计摘要、异常表和最终验收汇总沿用同一索引，不再制造第二套缺口清单或重复回执账本。

先读：AGENTS、STATUS、docs/DEVELOPMENT、docs/DATA_CENTER、相关数据 OpenSpec、
openspec/specs/newow-product-reference-trading/spec.md、TESTING，以及上述执行结果。
既有调查：共同根的 `fresh-audit-20260914-002/README.md` 和
`bz2605-isolation-diagnosis-20260915-001/README.md`。后者仅离线结构复现，不是当前DB重规划。

预计改动只在有缺口时发生：`scripts/newow_weekly_recovery.py`、`scripts/newow_weekly_recovery_campaign.py`、
`scripts/newow_weekly_acceptance.py`、对应 newow 测试、必要的 Newow 展示组件及其 E2E。
已有能力满足时只运行并整理证据，不为各阶段新增生产模块。命令统一维护 `TESTING.md`，状态更新执行证据文档。

## 阶段 A：独立写后读回与异常证明

- [ ] 核对 branch/HEAD/dirty、当前维护状态、guard/在跑attempt、配置与Canonical非敏感身份；
  只通过既有loader读取必要运行设置，不显示凭据、不source配置到输出、不重启服务、不抢占维护。
- [ ] 从真实campaign结果提取39个唯一成功身份，核验原始hash/终态、547 started/547 saved及其关联；
  使用新进程fresh READ ONLY事务做逐单元Catalog/物理分区/MDS读回和原生replan，全部零目标才关闭独立复核。
  不能只复算旧JSON里的remaining_target_count；失败保留具体对象，不重新下载。
- [ ] 重新验证B2411 source-only与BZ2605原始来源/journal/零提交证据，以当前原生plan做精确匹配；
  使用修复后的原生校验，形成可供新prepare使用的隔离证明。只有完整原生校验通过才允许排除下载。
- [ ] 用已有来源证据更新RS专项分类；同时保留全域审计发现的PF2611、RS2309/RS2311等其他异常，
  不将异常总数硬编码为B2411+BZ2605+九RS。旧102清单缺失继续披露，不从排序倒推或手工过滤。

阶段交付：39项独立读回结果、B2411/BZ2605隔离资格、当前异常表；任何未通过项不冒充已完成。

## 阶段 B：完整审计与新总包冻结

- [ ] 固定 operational60、W1 dependency-only、as_of=`2026-09-13T06:36:13+00:00`，运行一次原生完整审计；
  保存full report后派生摘要，要求complete=true、budget_exhausted=false、provider/writes=0。
- [ ] 证明39个成功对象自然退出候选；若仍有候选，调查根因，不按成功名单删除。metadata/source/review/
  unavailable/unknown 均保留在分母；任何新增目标按当前事实记录，不套974或51批的旧数字。
- [ ] 复用原生prepare切分每批最多20单元，合法绑定旧campaign异常和source-only异常；
  全部子包联合覆盖当前普通全集，检查targets、expected/missing、child hash、代码/config/root/截点及隔离清单。
- [ ] 冻结一份完整普通campaign和唯一新attempt申请，明确真实范围、维护窗口、影响、读回、失败停止和恢复方式。
  代码冻结后不再改执行代码；必须修改则旧prepared明确失效，重新只读准备和申请新意图。

阶段交付：全域当前余额与可审批总包。只读prepare不初始化provider，不为了估算额度额外查询provider。
若需要额度查询/新来源请求，先列精确目的与范围，单独取得意图；不得把targets数换算成计费请求数。

## 阶段 C：获批后的串行执行与异常处置

- [ ] 只有owner在本新任务批准exact campaign SHA和attempt后才执行一次；正常内部批间不重复询问。
  首次运行前input validation/preflight符合新意图，维护冲突不等待后自动重试，不安装调度或停止Runtime。
- [ ] 保持现有来源质量allowlist、完整响应、严格整数零提交及plan不变条件，合格异常隔离后继续独立单元。
  网络/额度/锁/漂移/提交未知/证据或读回失败全局停止并记录阶段原因，不自动续跑、回滚或重试。
- [ ] 成功/隔离失败/停止失败/未尝试/未知五类与冻结分母闭合；新进程逐单元独立读回，再同截点全域后审计。
  当前普通候选归零才能声明固定范围普通补齐；新候选或未量化异常继续待处理。
- [ ] 来源无效的异常保持SOURCE_EXCEPTION并说明影响；本地与有效权威来源冲突才形成独立专项修复包。
  任何新source-only请求或专项写入分别精确批准，不继承普通总包意图，不用价格替代/坏行删除造绿。
  改变数据规范化、公式或核心语义的设计先完成针对性方案与必要Review，不由本方案默许。

外部Gate待批准时，继续独立离线验收工具检查、异常分析与展示验证，不能停止所有安全工作。

## 阶段 D：周线三策略与完整合同验收

- [ ] 在同一明确截点运行原生matrix并保存完整结果。业务核心为60×3=180 W1策略组合；
  当前acceptance summary还要求完整540条合同条目：另外360条D1/60m明确未开放，不将其当作已开放数据ready。
  不能用“60品种×3周期的180项输入检查”代替180策略组合，也不能改小540校验制造通过。
- [ ] 逐W1组合验证主图、适用指标/副图、BUILD/HOLD/REDUCE/CLEAR/FLAT、INITIAL_CLEAR_NO_ENTRY、
  当前OPEN与历史CLOSED参考交易、收益、分页定位、换月中断及冲突展示。参考配对必须绑定物理合约、segment和版本。
  原生不适用、预热不足、来源错误、无信号等分类保留；不得给缺失信号补示例marker。
- [ ] 使用候选只读服务和真实数据做60品种×3策略页面加载、错误/未开放状态验收；无route mock或静态截图冒充。
  对交易配对、CLEAR无入场、换月、来源异常、无交易、正常有交易等真实场景验证API与UI一致；
  桌面/移动/全屏布局按代表场景补充。每组合留结果与必要证据，不要求生成重复180份截图。
  合同正确显示异常可记“异常展示通过”，但数据READY/交易正常通过数必须单列，不能混为全品种成功。
- [ ] 只修可复现且属当前展示/读取合同的缺陷，先红灯测试再最小修复，按影响跑后端/Web/E2E并复审。
  任何需要改变策略公式、收益口径、指标身份或ReferenceTrade配对合同的问题，先单列设计Gate，不顺手改变。

如冻结截点验收后要验证最新完成周，只能新增独立只读证据，清楚标注新截点；不得因此扩大原补数授权。

## 阶段 E：工程与证据交付

- [ ] 测试沿用TESTING：恢复/source-verify/campaign/readiness/acceptance与受影响模块；有实际代码变化再按风险扩展。
  不重新无差别跑全仓库，不降低断言。区分fixture测试、保存证据离线重放、真实只读验收及真实写入。
- [ ] 必要独立Review集中在最终有界diff和数据结算/540覆盖，不另拆多个开发任务。修复finding后验证，
  条件满足连续commit/push并集成develop；保留现有task/evidence直到交接完成，不触及main/tag/Runtime。
- [ ] 更新原execution-evidence与STATUS的对应事实，历史数值注明截点/已被替代，不覆写历史文件；
  输出普通余额、异常余额、W1数据READY数、180业务验收、540合同覆盖、UI结果、代码集成与外部Gate。
- [ ] 完成状态逐项给出。普通补齐、异常分类、策略页面验收、工程交付分别判断；
  无效来源无法修复时可完成调查与正确异常展示，但整体数据闭环保持PARTIAL，不伪称60/60已完整。

## 本轮授权与唯一开始动作

用户已要求本方案及一个Sol medium会话开发：允许执行全部只读/离线准备、既定范围内最小工程修复、测试、
Review和普通develop交付，不在这些阶段重复询问。真实取数/生产写入必须由新任务展示精确包后获得新单次意图。
不授权发布、Runtime切换、自动定时重试、通知、Scope/配置变更或交易。所有证据沿用主仓库持久根。
执行者唯一开始动作：确认现场身份并独立只读复核39个成功单元与BZ2605当前计划，而非再次规划项目战略。
