# AL已证回滚单次续接

Owner已批准实现、测试、Review、闭市发布与现场恢复。基线develop 732c1e4bf；当前隔离树复用，不修改现役v32。

## 执行边界

- 当前AL exact HTDY 60m身份；保留原BLOCKED、旧claim及原capture，禁止自动/递归续接、换namespace绕过或通知补发。
- 专用续接计划绑定父计划/claim、checkpoint、原capture及新fence/有效期；结果和投影同事务提交。
- 串行测试；并发/恢复独立Review；仅在fresh全部CLOSED、宽限结束及无维护/未知竞争时向前发布并原生切换。
- 验收：未解决BLOCKED/pending/UNKNOWN均0，历史刷新实际健康处理一轮，10秒内退出和恢复通过。

## 进度

- 只读确认原apply拒绝已消耗claim；普通pending处理遇BLOCKED回滚，不能释放队头。
- 已有锁重入根因是来源回调调用worker._read_input触发独立Session FOR UPDATE；来源入口必须只读Market。
- 使用executing-plans及TDD执行，最终独立安全Review；发布使用release-agent。
- 新增单次续接/Market-only来源入口；首个成功路径RED→GREEN，保留原apply拒绝与原BLOCKED。
- 新增底层service绕过claim、畸形proof、父目录symlink故障的失败复现，再转绿；读/写claim使用已核对私有目录fd和no-follow，FIFO读取不阻塞。
- 定向恢复/HTDY 40 passed；扩大Reference/原生handover/cohort 1280 passed、10 skipped、107 deselected。
  首次两项worker入口因沙箱不能写默认生产日志目录失败，改用专用0700 GUIYI_LOG_DIR后通过，未修改生产日志。
- 真实隔离15490 PG：来源持行锁返回、并发单次提交、回滚/重启与既有HTDY 8 passed/5 deselected；仅合成行情夹具，无SDK。
- 三模块定向Mypy、Ruff通过；OpenSpec12通过。全导入Mypy扫描暴露418项既有依赖错误，未宣称全仓类型通过。
- Ruling: 正式恢复前队头后的新自然输入可能超过原2条；显式续接仍仅AL原队头，后续全部由原生顺序处理，不扩大维护修复集合。
- 独立Review确认P1：失败后的marker可被底层service重用；已先复现失败，再新增调用级ContextVar permit，guard绑定同一Session，complete单次消费、finally撤销。
  同时先复现父计划仍有效时的回退绕过，再拒绝存在续接marker的父计划complete；原v1无续接marker时保持原行为。
- Review修正后Reference/handover/cohort1282 passed/10 skipped/109 deselected，真实PG8 passed；冻结真实AL原件/原capture/前置checkpoint
  SHA775e415e…，现役v32纯计算与候选隔离PG续接输出及checkpoint逐值相同。正式原件、claim和账本未改。
- 现场operator私有草稿output/al-rollback-20261029/closeout.py；部署锁+三owner FD锁/同inode、全CLOSED/宽限、exact bindings/控制/PID，
  fresh证明旧215596/215597 backend不存在、绑定旧cancel intent/独立rollback证据及原claim；来源持真实stream行锁预检先于claim。
  所有本次drain在finally精确cancel并独立确认同PID active；无runtime-pins之前不能执行，尚未运行生产续接。
- 独立Astra Review最终允许3b94bd403集成develop；operator两项P1/P2已修正：停驻前持原生after_market/catalog维护guard，
  三个prior control仅接受None或合法cancelled终态且逐项CAS核对；finally维护guard先释放再恢复owner。
  最终operator SHA95e31153fbc22768f30f58eb192481beecb33451b6a1a2b00c1f99399869be9d经独立AST/哈希/控制流Review通过。
  若新cohort遗留自身旧代drain，须先凭本次switched终态、原requestID及旧PID退出证明完成精确cancel收尾，不能覆盖其他请求。
- CODE_COMPLETE / TEST_COMPLETE / REVIEW_COMPLETE；生产AL仍待下一次合法闭市窗口执行，未发布、未切换、未消费续接claim。
- Ruling: 原生cohort的drain_old无条件要求pending capture=0（runtime_cohort_host.py），AL原capture使先切换再修复不可行。
  不放宽该原生合同：闭市先正式发布补丁，用已发布新代码做一次停写/持锁维护，明确分离maintenance_code身份与旧runtime owner身份；
  续接后旧owner按原生顺序追齐，证明pending/capture/未解决BLOCKED/UNKNOWN均0，再生成全新cohort计划并切换。
  该调整不改变永久consumer绑定、公式或恢复预算；未满足停写/互斥/来源证明时不消费claim。正式恢复与Runtime切换分别读回。
- Ruling: 仅本次AL闭市维护允许旧v32读者暂按原v1完整事实链校验读取新增JSON键；不声称其验证了新link。
  新维护代码原子执行新link校验，且必须新代码独立读回和冻结checkpoint对照成功后才恢复旧Reference writer。
  提交不明时仅独立读回；若无结果，须证明原事务已结束（未到提交guard则核对Reference写锁已释放）并再次读回/核对原checkpoint与capture。
  无法证明时仅Reference保留精确drain，Feed/Live仍安全恢复，并明确报告阻断，不以旧读者代替新link证明。
  这是生产未知结果fail-closed的必要例外，不能为满足finally全恢复而让未证实的Reference继续写入；正常与已证回滚路径仍finally精确恢复全部owner。
- 上述过渡兼容/未知结果分支最终独立Review通过，无新增Confirmed Issue；最终operator SHA
  dd0d6df9c345cd7d06a8faa5aa36d55a434bc0c5c3f9b21e18283e4571fa5951，执行副本保存在主树output/al-rollback-20261029/closeout.py。
  operator异常分支经静态审查，未冒称生产故障注入；core回滚/未知/重启/并发已由真实PG与隔离测试覆盖。
- v33选择性候选仅择取本任务3个提交及版本/状态更新；候选自身1282 passed/10 skipped/109 deselected、锁定离线uv/pnpm和Web类型/build/topology通过。
  09:02 fresh现场：旧v32/gen38六owner active，60 TRADING，源/完成游标追尾，Live订阅/覆盖60且ok；Alert处理ok，覆盖evaluation_lagging，无新增处理失败。
  权威60品种Session证明10/29日盘最后结束15:00；正式执行仍要fresh全CLOSED/宽限/互斥，不以时间点代替门禁。

## 10:05 发布候选与闭市交接

- 当前生产仍v1.16.32/gen38，AL生产续接从未执行。09:28独立读回completed11455、pending2、未解决BLOCKED1、UNKNOWN0；
  其余前台正常推进，Live覆盖/订阅60。Alert处理正常但coverage evaluation_lagging，整体degraded保留，不称全策略健康。
- 候选发布树`/Volumes/扩展盘/guiyi-quant-workstation/.worktrees/release-v1.16.33`，分支`codex/al-release-v1.16.33`；
  只择取本任务修复/测试/合同及版本状态，不发布develop中LMS等研究。主树develop保留其他研究。
- 候选自身锁定离线uv安装、pnpm安装及Web类型/build/topology通过；元数据及APP_VERSION均33；
  1282 passed/10 skipped/109 deselected、真实15490 PG 8 passed/5 deselected、health/version7 passed/17 deselected。
- 实际官方MDS/Authority/Reconciliation/worker factory组合另用冻结真实AL在15490隔离PG重放，
  `parity-native_composition.private.json`证实outputs_equal/checkpoint_equal=true。限定来源回调持stream行锁也能返回。
- 最终operator补齐官方Reconciliation的read_guard，持有既有维护fence前后核对；不创建新版本Runtime enable标记。
  六处真实构造签名检查通过，移除read_guard负向控制正确失败。实际maintenance尚未执行，runtime-pins及closeout-1未创建。
- 权威日盘最后结束15:00，计划15:10一次性续接；时间不是门禁，须fresh全部60 CLOSED及宽限、无未知/维护竞争。
  先发布33，再按上文有界过渡，用新发布代码修复旧32停写owner，独立验证新proof及冻结checkpoint，恢复旧owner追齐。
  追齐后再生成全新原生部署计划，不能复用旧计划或跳过pending capture gate。若原件/claim/checkpoint/fence漂移即拒绝。
- 正式续接必须运行主树最终SHA固定的私有operator；pins同时绑定新发布root/tag/commit和旧runtime_root/tag/commit/gen。
  原claim目录和原BLOCKED保留，不复制隔离测试namespace至生产；续接claim消费后失败/未知不能再次提交。
  具体私有证据目录`output/al-rollback-20261029`，原父计划/claim目录`output/overnight-first-four-20261028/htdy-native-closeout-1`。
- 切换后两次独立readback，证明未解决BLOCKED/pending/UNKNOWN/capture归零，历史刷新线程实际启动且健康处理一轮，
  10秒内drain/resume且finally精确撤销本次请求；自然输入/信号/参考交易仅由下一交易时段事实验收。
- SimNow observe不改，仍只读且交易关闭；其安装与配置固定引用旧32，所以发布33后暂保留32，不能按“旧树”盲目删除。
  全部测试完成后仅清理本任务15490临时PG及匿名卷，不碰5432/6379生产。

最终独立Astra增量Review：operator SHA `a30e6e61829e6fb0e99db75ea5538c4f1e4a1873f2d5dc89592ad722fced37cb`
无剩余Confirmed Issue，可以冻结执行；主树同名私有执行副本已原子更新并fsync。仅此SHA可执行，旧SHA均为过程草稿。
Review读取native_composition真实隔离对照，未执行生产；生产恢复/发布/切换仍未完成。

## 冻结交付与调度结果

候选exact `122327709888b1c4d74557717c3c461387ab1f76`，已推送，草稿PR536：
https://github.com/firehell/guiyi-quant-workstation/pull/536 。未合main、未tag/Release、未切换。
10:12现场只读健康：十身份matched，DB/Redis/Live/Alert处理ok，整体degraded，生产PID/root仍32。
本任务隔离PG容器guiyi-al-rollback-pg-20261029及匿名卷已删除，未触及生产依赖。

尝试创建15:10一次性闭市续接时，宿主自动审批明确拒绝，理由是未来自动执行生产发布、main/tag/Release、
数据库恢复和Runtime切换缺少明确自动化授权。没有创建任务，也不以替代脚本/后台轮询绕过。
状态HOST_APPROVAL_BLOCKED，仅阻断自动调度；人工当前交办的工程/恢复目标授权没有撤销，仍可在后续主动续接时执行。
需owner明确批准“一次性自动续接并执行闭市发布、AL生产恢复和Runtime切换”后按宿主流程复核；
原continuation claim、runtime-pins、closeout-1均未创建，不将调度拒绝记为业务attempt失败。
