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
