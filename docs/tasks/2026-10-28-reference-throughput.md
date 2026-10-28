# Reference 吞吐与协作收尾

Owner 已交办实现、验证、develop 集成、向前发布及权威收盘窗口内的原生交接。
基线 develop `84313d04eb1857c9c2763d3bc64f8adbaa57cffd`；性能对照为正式 v1.16.26/gen34。
已发布并实际切换v1.16.29/gen35；旧v26退出阻断已解决，现场退出/恢复验收通过，自然新输入吞吐待交易时段。
公式、Scope、参考收益、恢复合同、通知时效及 SimNow 不变。

## 实施记录

- 已完成只读定位：15:03 Inbox pending64/blocked0/UNKNOWN0；全部60品种CLOSED。
- 现役恢复关联完整校验2618条，单次cProfile约2.156秒；PB5m抽样context0.0128秒、checkpoint0.004秒、Session端点0.0261秒。
- 现有62项定向回归通过；这些检查不代表优化或Runtime验收完成。
- 任务1：阶段计时与真实前像已实现。冻结1020路已计算capture，SHA `652601715fc0ee5e31a4bbfb7f0953e1b496f0f637e0128caaaa2266606583ff`；另60路无可用计算前像，不制造替代。
- 任务2：批量扫描、单次校验复用、按需前缀与前台优先已实现，扩展验证中。
- 任务3：扫描/逐流/纯计算/物理分区/暖机的协作取消已实现；提交内不引入取消，后台实际关闭后才允许drained。
- 任务4：结果一致性、容量/故障回归及独立Review通过，develop已集成；实节奏soak和发布交付进行中。

实测现役scan 25.959秒/11731条SQL（首512键页）；候选scan 0.052秒/4条SQL。
首轮分页的229与240入队数不可直接当等量对照；候选批量查询已验证pending组与日周、分页及无任务分钟排除。
恢复关联同2618个ID的摘要保持 `213b03ea4258153a51ff9b4c50681d9a23e82264eb7c673c10531c580fc8dad1`，
本轮同类cProfile基线2.851秒、候选1.734秒；不跨事务缓存闭合结论。
最终选择性候选scan0.042秒/4SQL、恢复1.686秒/7SQL，ID摘要相同。
同一个READ ONLY / REPEATABLE READ快照完整遍历旧算法和新批量算法，240键及顺序完全一致；
摘要 `f345cdc415b37a9a9bcc5c4df5419ba2e4c946c47681501c0232920ea2c2fcdf`。

1020路真实纯回放的checkpoint全部逐值匹配；基线6.978秒、候选7.011秒，不宣称公式计算提速。
最终定向回归429通过/2项Redis跳过；随后精确16389隔离Redis实跑15通过（消除该项待验）。
启用真实隔离PG的事务/恢复/schema混合集合72通过（包含SQLite确定性用例，非72项均为PG）；
真实隔离PG的60/300路及MDS连续五根容量3通过。
1020路全部output_sha256与checkpoint_sha256一致，records只有独立耗时字段不同。
两项测试最初尝试写默认Runtime日志，被sandbox拒绝；之后明确使用私有临时测试日志目录，正式日志未改写。

峰值样本：最新收盘窗口并非60品种均已完成，严格拒绝；选择当日最近真实完整窗口13:55–14:25，
60品种×6根5m/360原件，SHA `7e29e9418b670052ada9952f0ebc016c1ef15860f193ebff61a6ae1087088052`。
隔离快速重放6波均60→0积压、全部checkpoint匹配，每波1.71–2.32秒，共11.72秒；无Runtime激活/provider/通知。
进一步经真实Inbox选头/Worker/Service提交的快速实验每波2.09–2.61秒、总13.60秒，360输入全部匹配。
首版任务脚本先导入应用导致开发连接池，及capture正文不含revision_id均已在隔离阶段定位修正；
旧失败schema保留待精确清理，不将失败测试记为生产维护attempt。

Ruling: 生产最新窗口不完整时只选真实完整的容量实验样本，明确窗口；不将此算作收盘业务追齐。
Ruling: Release只向正式main移植本任务提交，不整体发布develop内无关SimNow和研究改动。

Ruling: 单次调用内可以复用完全相同的不可变证明；不跨事务缓存闭合结论，不改排序和未知结果处理。
Ruling: 先提交可精确恢复的原子单元，再响应收尾；取消不得写BLOCKED/UNKNOWN或伪造drained。

独立Astra Review覆盖完整5d0b46753445f44b02e7ba0de7741e32f6e53cbe分支：确认P1定时对账吞取消，
active刷新下8次等待复现16.021秒。已补红测并修复：等待前检查、对账逐项检查及显式传播取消；
已进入提交事务仍完成，另有真实事务边界回归。其余memo、前缀、扫描及MDS默认行为无已证实重要问题。
复核af1722b23通过，独立76项测试通过，允许集成develop。develop集成aa639e028已push。
正式候选从v28仅选择性移植这两笔提交并将应用版本改为1.16.29，head38cca86b2，PR532。
该精确候选557项定向回归全通过（包含真实隔离PG、Redis及cohort），精确发布树另跑3项容量回归通过。
Web类型/build/topology、离线lock校验、OpenSpec、secret0、diff检查通过。
最终候选1020路回放6.597秒，所有output/checkpoint摘要与现役基线一致。
最终候选360原件经Inbox/Worker/Service快速重放每波2.36–3.82秒，全数匹配；实节奏30分钟另记。
实节奏soak实际1800.005秒通过，60品种/6波/360条真实5m原件，每波60→0、2.27–3.22秒、checkpoint一致。
此实验使用冻结真实capture输入及隔离PG，不含正式恢复历史负载，也不替代下一自然时段验收。

16:25只读现场：旧v26/gen34十绑定；60 CLOSED；Inbox pending640、completed7576、blocked/UNKNOWN0、
dependency_wait3，global degraded；存在旧维护锁。16:27再读维护锁已释放，原PID45204继续运行。
此处均为旧Runtime事实，不冒充新版本吞吐验收。

## 实际验证入口

统一pytest前缀：`GUIYI_LOG_DIR=/private/tmp/guiyi-reference-throughput-test-logs PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=services/quant-api:services/quant-api/tests:services/quant-api/tests/reference_trading:packages/quant-core python -m pytest -q -p no:cacheprovider`。
定向集合：throughput_control、forward_runtime/service/inputs、inbox/runtime/wake/recovery、worker_entry/diagnostics、
refresh_priority/historical_refresh_priority、subing_forward_model/six_period_capture、newow_input_cache/prewarm_input_sharing、
scheduled_reconciliation、market_read_service、closed_runtime_warmup、repository_postgresql、runtime_schema_compatibility、
live_wake、runtime_cohort/host/readback，共557 passed。
`test_forward_capacity_postgresql.py -k 'real_kernel_forward_worker_capacity or retained_worker_five_completed_bars'`：3 passed/2 deselected，103.05秒。
`pnpm -C apps/quant-web build`、`uv lock --check --offline --project services/quant-api`、
`openspec validate reference-trading --type spec --strict`、`python3 scripts/engineering/secret_scan.py --json`均通过。
隔离PG为15489的任务容器；Redis按现有实测合同使用16389/11；隔离库守卫始终启用。
冻结及计时原件保存在`output/reference-throughput-20261028/`，不提交真实原件到Git。

## 验收

冻结输入的指标、动作、参考交易、收益及checkpoint逐值不变；峰值5分钟边界任务在下一边界前完成；
隔离30分钟输入节奏下积压不持续增长；扫描、读数、计算、capture后、提交中、历史刷新中的drain均安全。
部署保持10秒预算；旧v26无法退出则保持原Runtime并明确交付阻断，不强杀或扩时。

测试、Review、发布、现场切换及自然业务验收分别记录，未完成时不得宣称RUNTIME_READY。

## 正式交付与现场结果

PR532已合并main，annotated v1.16.29及GitHub Release target均为
`94b488896c4078c57f057bbfe73fd091c13a905d`，树摘要与557项验证候选完全相同。
原生控制器首次只读冻结因漏带入口已有的observation/handover开关失败，未消费attempt；
定位后补齐控制器进程环境，原输出保留，正式配置未改动。

全新原生计划`6a6da51afd11938763abefe965b1afd1c8fbf22893d7d0b3172f7d0caf5b6087`
于16:47冻结v26/gen34→v29/gen35，完整预热通过：Alert420路413计算/7合法warming，
Reference540计算/60初始化，Live/Feed闭市静默及游标对齐。预热不等于自然业务验收。
单次apply在旧Reference10秒drain超时，原生`cancelled/COHORT_OLD_DRAIN_TIMEOUT`；
effects仅prewarm/calendars_off/bootout_requests，未进入stop_old/install/CAS。
按交办边界保持现役，不强杀、不扩预算、不再试切换。

独立恢复核验通过：原registry哈希、十plist/loaded日历、Scope/配置/evidence保护精确一致；
六原PID均active/持锁：Live45192、Alert45197、Reference45204、API45210、Web45216、Feed45348。
16:53现场：十服务v26/gen34，Inbox pending/blocked/UNKNOWN/dependency_wait均0，completed8302，
recovered2618及历史blocked339原件保留；计算水位16:30:13，维护锁空，global仍degraded。
无unknown部署guard阻断。`cancelled-readback.json`、`after-cancel.json`及原生私有attempt均保留。

工程CODE_COMPLETE/TEST_COMPLETE/REVIEW_COMPLETE/RELEASED；Runtime promotion未完成。
下一最小动作：单独处理旧v26原生安全退出的部署阻断，保持现役边界；新版本自然吞吐待切换后再验。
隔离PG/Redis临时容器已精确停止删除；冻结输入和结果仍保留在主工作区output。

收尾：应用版本提交5ab5a6c48已同步develop并push。无引用v1.16.28按原生精确计划538cea25…
再次扫描一致后non-force移除，4个marker原件/SHA保存在output；现役v26及本任务已发布v29保留。
本任务临时发布分支已从已合并main上下文non-force删除。
本会话task worktree调用Codex原生archive被宿主拒绝：`The task's primary checkout cannot be removed.`
因此保留此树，不换工具绕过保护；primary工作区中的交付记录与Git提交可独立读取。

## 17:17续办：退出阻断解决并实际切换

Owner继续交办解决旧v26退出、切换并验收。复用既有原生预停驻路径，无需修改或重发已发布源码。
`test_runtime_cohort_parked.py test_runtime_handover.py`：33 passed/3.08秒。
在60 CLOSED、Inbox/UNKNOWN/pending capture均0且未知部署guard通过后，对exact旧Reference/gen34发出一次原生drain；
19.603秒自然停驻，历史刷新/通知线程均关闭、锁由owner自行释放；旧PID45204保持parked等待接走。
这把旧版本完成在途工作的等待与正常交接的10秒预算分开，不强杀、不提前解锁。

全新计划`c50d1af551fe920e5108991c71723d17fd58450599eeafe5b4788898e4df7309`
冻结原request0838ce13…，单次apply终态switched；旧退出、安装/CAS、消费者/Feed及四日历恢复全部完成。
实际十绑定为v1.16.29/gen35/exact94b488896c；六旧PID均已实际退出，原取消attempt原件保持。
对新Reference65175/gen35做一次闭市drain/resume：1.336784秒停驻且后台资源全关；取消该精确请求后0.165秒同PID重新持锁，
全部1080流的checkpoint指针/状态摘要不变。不是强杀，也没有重放或补发。
17:15、17:17独立读回：身份matched、Inbox pending/blocked/UNKNOWN/dependency_wait0，completed8302，
source及completed的Live/Alert/Reference游标全部对齐原件尾部；水位16:30:13未回退，历史恢复2618、旧BLOCKED339保留。
新worker实测scan最大0.014806秒、背景等待最大0.085712秒；没有新自然输入时不把这些数值当作行情吞吐结论。
第一次独立探测启动早于cohort终态，被部署guard拒绝；终态后的两次读回均通过，无未知部署。

本轮仅运行原生运维及验收，没有修改公式/Scope、补历史、补发或涉及SimNow账户；没有新自动化。
工程切换和现场退出验收完成，global原有degraded/自然业务验收继续保留。
实际命令与新鲜证据位于`output/reference-v26-exit-20261028/`及原目录的new-runtime-after-switch/after-resume.json。
唯一剩余验收：下一自然交易时段观察新输入是否及时处理、积压是否持续下降。
