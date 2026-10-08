# 牛哇四策略三周期持续记录

目标：operational 60 × trend/oscillation/main_rise/dual_fusion × 1w/1d/60m，共720路。completed-only，历史与自然观察分离，牛哇不推送、不下单，page_parity=true、executable=false。用户要求在独立工作树实施并继续完成未完成项；其余任务修改保留。

## 当前交付

- v1.14.3原交付CODE_COMPLETE / TEST_COMPLETE / REVIEW_COMPLETE；最新发布v1.14.3@00bc70899a4d8b6a519dd9d443caf6c2d256ac21，API/Web与记录worker已切换，85条旧历史刷新阻塞已恢复。Market/Alert/weekly组件仍为各自旧版本，不声明全服务RUNTIME_READY。
- 后续review确认23:00终场漏记136条（34品种×四策略）；本轮修复及精确数据恢复进行中，尚未完成验证/现场读回。下列180条与540条计数属于22:57及之前快照，不证明23:00覆盖完整。
- 720/720正式历史资产registered、active、READY；240日线使用owner_eligible_quality_boundary_v1。D1/60m截至2026-10-08 15:00，W1截至09-30最新已完成周；未完成本周不补造。
- 720/720 forward配置、启用、预热，activation_generation=1，recording_start=2026-10-08 21:59+08。59品种708使用scope plan1eed78946610b1d6bcfdb8ee9d801261ccd4b345aa64800edc1578aba80974c9；RM12使用经末端换月边界证明的新plan22e67a6267cce943a8eb3b63925084b9b38524c3714c85e2c2ab90d6f90af30c。旧blocked计划未复用。
- 45夜盘品种首22:00自然60m全部完成；每个60条1m源完整，统一聚合45/45完全一致，切换Market未丢已确认分钟。
- 180/180首小时实际capture/calculation与来源hash一致，observed_at为22:11:15–22:13:51，均晚于起点；180逐Bar状态全部ready，17策略Marker、17Hint，参考动作OPEN_LONG12/HINT17，seed动作0。CLEAR无observed entry时不造CLOSE或收益。
- 其余540路等待新日周或白天60m自然完成，seed不计observed。pending capture0，reject/diagnostic0；180 Live-to-Canonical reconciliation pending，Canonical尚未发布，不冒充matched。

## 数据与实现

0047→0048迁移已执行并独立读回，完整旧reference备份、旧六表计数和逐行摘要保持；0049未执行。14项current-owner预热串行完成，84次真实provider请求，198分区身份/内容独审。RM2701无已完成owner周仍为合法NOT_APPLICABLE。

Oct9正规Market preparation实际提交60MainMap、5Calendar、225Session，保留15Calendar/225Session equal；530facts独立逐值一致，60owner可解析，Oct8→9物理主力切换0。每日不可变proof按hash归档，稳定index及历史刷新state跨release保留。旧failedRecovery status unsupported在provider前停止，未绕过。

四策略按product/frequency共享行情读取，基础三策略先持久化、双策略读取同Bar基础事实；动作、Hint和逐Bar状态有独立稳定身份。completed Canonical用于历史/DW，completed Live用于60m观察；无订单、账户或Push transport。历史预热不携带参考头寸，D1边界只作用owner有效区间，完整raw/calculation质量事实保持。

生产验收修复已发布：合法null矩阵、当前D/W/H same-snapshot截止、MDS批量Session读取、末端换月边界精确预热证明、记录服务双层固定label名单、夜盘已保存交易日窗口、历史刷新/健康端点只发现Catalog已发布尾端。未来Canonical、内部缺口、物理/owner身份和未知提交仍failclosed；不缩窗、换resolver或自动清blocked。

## 实际验证

- 初始scoped Newow/reference3273 passed/2 skipped；reference499 passed/1 skipped；数据层1962 passed/59 skipped；Alert兼容220 passed；启动/刷新56 passed。
- 真实隔离PostgreSQL720持久化及重启通过，300路五轮1500记录容量通过；v1.14.3隔离720及相关backend39 passed，最终源端点定向42 passed/2 PostgreSQL skipped，扩大真实Catalog回归162 passed/2 skipped。
- 最新Web808 passed/1 skipped，typecheck/build/topology通过；OpenSpec10/10、Ruff、secret scan、diff通过。高风险改动独立Review无剩余Confirmed Issue。
- 候选v1.14.3对生产只读验收：720configured/enabled/seeded，180observed，180已发布历史端点READY；180最新观察交易日为10-09，540为null，pending0。首自然来源和实际记录分别独审；浏览器旧夜盘遗漏证据与修复读回分别保留。

## 首次切换前的历史阻断与恢复边界

以下1–2项为批准切换前的历史过程，现已由后文完成结果取代；保留失败与前像证据。

1. 宿主自动审批拒绝短暂停止referenceworker，理由是可能中断实时记录且缺少明确停用授权；用户决策已提出，未绕过。现役worker继续记录。v1.14.3历史刷新修复尚未进入该进程。
2. 旧worker在prepared Oct9 metadata上产生MAPPED_CONTRACT_DATASET_MISSING。精确只读扫描30个blocked均仅status/reason、没有plan/resume/维护attempt；720历史active revision、seq、checkpoint hash、dependency digest与初始化冻结来源完全一致。切换后须重新在排他锁下冻结精确清单，保留原state/hash，仅恢复已证明计划前失败条目；未知、inflight或有plan/resume条目不得清除，不复用旧失败输出。
3. 共享Alert切换另被自动审批拒绝，理由是既有外部通知副作用不在本轮不推送范围；原苏冰15m信号和HTDY既有配置保留，牛哇无Rule/Scope/通知。Market/Alert旧根有实际服务引用，未清理。
4. 余540自然周期及Live-to-Canonical reconciliation等待业务自然发生；不手工制造收盘或启用额外监控/补发/回填。

证据根：task worktree outputs/newow-realtime-recording-20261008/（迁移备份、history唯一intent/receipt、bootstrap、data-audit、browser-final、candidate-v1143-actual-health.json、refresh-recovery-scan）。主树output/playwright/newow-v1142-readonly-*保留旧bug，修复浏览器证据另有唯一目录。发布PR413/414/415/416及tag/Release保持，不移动旧tag。

## 记录服务批准切换后的验收（2026-10-08）

owner明确批准短暂切换至v1.14.3。原子安装器首次在mutation前因新树缺启用标记退出，旧worker保持运行；
核对旧标记enabled内容、600权限/501owner后复制到精确发布树，安装器loaded=true/services=1。
实际reference-worker PID64434，root release-v1.14.3、commit00bc70899一致，未切换Alert或发送通知。

22:55:30锁内校验720历史revision/seq/digest/checkpoint全部与冻结bootstrap来源一致；恢复85条
精确MAPPED_CONTRACT_DATASET_MISSING且无plan/resume/attempt的旧阻塞记录。0400原始字节备份
`refresh-recovery-preimage-20261008T145530.json`，前像SHA
`3f0ae4e5ca686c5bb9fe3badd7abcf903d1ed7b450c6e14dba7b7064a4b3132e`，
恢复后SHA `cc02e463d504ad34de25d489bf98455645a1bbb4e08f9426383b3684cb7c8a5b`。
随后自然轮询游标前进，routes为空，没有新增阻塞。原DB资产和失败维护attempt保持。

22:57:17生产只读验收720配置/启用/seed、180自然观察、180Canonical endpoint READY、pending capture0。
证据 `worker-v1143-post-switch-20261008T145717.json`、`refresh-recovery-applied-20261008T145530.json`
位于原task outputs目录。首次验收拒绝覆盖既有证据文件，旧证据保留，改用新时间戳文件后成功。
该22:57检查点尚未验收新版本下一根自然completed端点、完整720刷新轮次及180夜盘Live→Canonical匹配。后续review已发现23:00终场漏136条，须先修复并读回，不能继续将其全部归为等待自然业务。
本节取代前文“记录worker切换被host阻断”的当前状态；共享Alert切换仍未获准且未执行。


## 本轮review问题修复与验证（2026-10-09，尚未切换Runtime）

本轮处理三个已确认问题，代码与文档修复不代表生产恢复完成：

1. 23:00终场136条漏记：Newow专属completed H1读取在Session关闭后仍使用权威交易日、rank1物理合约与已保存Live观察；预期端点由Session独立生成。逐项完整桶、严格时间、重复、来源及二次身份检查保持，原Alert/Web实时读取边界不改变。forward观察时间仍为实际捕获时间，多根遗漏进入精确gap/recovery合同，不伪造早先观察。
2. 矩阵完整性与Runtime健康误报：区分配置/预热/自然观察、独立预期端点与实际落后；正式部署核对固定launchd服务的安装/loaded身份，跨root或无法验证的状态显式unknown/mismatch。Market核心身份不能由新root缺marker推定健康；合法默认OFF只有plist缺席、host明确未加载和实际启用marker不存在才成立。Alert/weekly/reference诊断不替代Market operational健康边界。
3. 文档当前/历史冲突：PROJECT_SOURCE与DECISIONS对齐v32日周60m合同，完整explanation section仍未开放；STATUS旧P7检查点及任务host阻断明确为历史，22:57计数不再当作23:00完整证明。

实际工程验证：

- 定向后端805 passed / 52 skipped；真实隔离PostgreSQL另行执行中，不将这些skip计为生产或隔离PG通过。
- 矩阵定向15 passed，Web typecheck/build通过。
- Web全量817 passed / 1 failed；失败为既有页面“查看依据”断言，在未改动develop也复现。保留失败，不声明Web全套通过。
- OpenSpec10/10，secret scan 0，Ruff本轮文件全通过，git diff检查通过。
- 两名独立review均无Confirmed Issue，相关独立定向验证分别141 passed与42 passed；不代替生产终场恢复验收。

数据审计仍在进行：截至本检查点完成25个以上品种/60，未声明全量完成。252个质量日的7字段与当前真实RQData逐值完全一致，没有正价修正；保留原始来源质量事实，不以策略有效输入过滤改写源行情。BZ五个fresh请求结果仍UNKNOWN，禁止盲目重试，不将其计为成功或数据已修复。

上述新修复尚未切换Runtime，136条终场精确恢复、实际源读回及完整数据审计仍未完成。后续在独立验证与精确身份检查通过后准备scoped v1.14.5候选；不混入其他线程attack/UI或SuBing0049迁移，不改旧tag/receipt。此处仅记录本检查点，不预写发布或运行成功。

本轮隔离 PostgreSQL实际回归完成：`test_forward_capacity_postgresql.py` 与 `test_newow_worker_recovery.py` 共40 passed（211.42s），仅使用 `guiyi_isolated_newow_20261008`，未写生产库。该结果验证新代码，不代替正式运行读回。

## 完整数据审计与整改（2026-10-09）

原完整审计67分11秒覆盖operational60、七周期、截至10/8的配置历史floor2023-01-01及新上市后范围，并检查Catalog已有physical warm-up月。原结果failed23全部RS W1，不改旧报告；此前单品种0finding进度被误作累计，已纠正。逐40端点/23月/9合约用既有D1整周质量证明全部解释，无未解释缺口。audit-only定点整改后217回归、独立5案例通过；新的RS七周期全范围audit passed/0finding/provider0/applied0。与原其余59品种无finding证据共同完成本次配置域审计闭环，不声明无限上市历史或正常正价W1。

原件与SHA manifest保存在task outputs的data-audit/full-history-manual-20261008T1636Z及rs-audit-remediation-20261008T1645Z。源质量再核验252/257日×7字段无差异；BZ5 fresh结果UNKNOWN，两个响应保存失败attempt未重试，旧typed来源事实保持。没有可证明应该改成正价的Canonical修复目标；下载仅35个未尝试单元的新源核验，无生产行情/DB写入。

最终v1.14.5候选扩大后端2934 passed/111 skipped，候选隔离PG40 passed，Web809 passed/1 skipped及build/typecheck/topology；午夜176+独审46、audit217+独审5，OpenSpec10/10、Ruff/secret0/diff通过。候选只读720 configured/enabled，584 READY/136实际漏记、180 source endpoint READY，混合部署身份诊断正确。PR417仍草稿：宿主明确拒绝ready/main merge，要求此次具体发布批准；尚无新tag/Release/Runtime切换或终场恢复。

最终待发布候选 `1820951bfa8c7cdc234a22cca85d698a3effba60`（PR417），包含本轮审计误判修复；此前34649e4ff为补充修复前检查点。尚未ready/main/tag/Release/Runtime。
