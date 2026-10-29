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
