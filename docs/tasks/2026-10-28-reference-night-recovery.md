# 收盘后Reference恢复

Owner批准本线程完整方案，2026-10-28 03:00单次执行，08:00停止新生产单元，08:30前读回收尾。
范围：融合依赖/延迟动作解码、不可变Inbox恢复关联、现役历史资产刷新补建、真实原件与缺口恢复。
不变：原件/路由/旧BLOCKED、Scope、公式、收益口径、通知one-shot、auto_order=false。

## 进度

- 基线develop ec7351a29；正式v1.16.24/gen33另验；任务worktree独立，无初始dirty。
- 单次自动化已触发后删除，当前执行继续，不设后续调度。
- 前置证据在主仓库output/reference-night-recovery-20261028/，所有操作重新冻结计划。
- 待完成：定向修复→恢复合同/migration→测试/Review→发布与生产恢复→独立读回。

## 实施裁定

- 0053不可变触发器不修改；恢复通过append-only结果关联闭合，不能BLOCKED转PENDING。
- 历史原件和缺失观察分流；历史重算不是first-seen，缺失不能造退出价或收益。

## 03:00后实际进展

03:01只读preflight：60 CLOSED、下个Session均有权威事实，维护锁无占用，0053；Feed订阅0/pending0/无错误。
Inbox pending2279/blocked339/unknown0，接收原件游标全部追尾。
融合回归先红2failed/4passed，修复后相关31passed。新恢复回归先红5failed，初版组合32passed/5skipped。
0054真实隔离PG先红2failed，兼容与原件/结果trigger已实际验证；接收组合131passed，旧wrapper参数测试已修。
独立Review两P1已定位并新增回归：unknown不可重复claim、合法receipt停用不破坏历史闭合。
新增真实有界代际桥接及SuBing四分钟scope测试，定向28passed/4skipped；默认Newow H1合同保留。
全Reference扩大运行在无关capacity大负载处主动SIGINT：152passed/188.65s，不计全套通过。
当前尚未发布、migration或生产恢复，现役v24不变。

03:28完整只读缺口扫描passed：Source/Completed索引与Inbox合计44654唯一原件，294条全部prefix_gap，无内部空洞，单桥边界已证实。
Review新增P1（跨代结果漏验gap capture/calculation链）已补统一validator，断链拒绝及合法停用回归。
0054对旧0053保持additive，不修改原迁移/触发器。attempt按delivery固定到fence namespace，一次claim未知不重跑。

04:10代码候选验证：核心285passed/1skipped（含真实隔离PG、Redis）；扩展交接/前向/历史刷新156passed/2skipped；OpenSpec12passed，Ruff、secret scan及diff check通过。Review发现两处容量口径遗漏已按统一完整validator修复，新增先红后绿回归。同事务source commit guard现已传入恢复service。生产executor另审，当前未执行生产migration/恢复/切换。
