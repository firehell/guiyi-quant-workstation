# 收盘后Reference恢复

Owner批准本线程完整方案，2026-10-28 03:00单次执行，08:00停止新生产单元，08:30前读回收尾。
范围：融合依赖/延迟动作解码、不可变Inbox恢复关联、现役历史资产刷新补建、真实原件与缺口恢复。
不变：原件/路由/旧BLOCKED、Scope、公式、收益口径、通知one-shot、auto_order=false。

## 进度

- 基线develop ec7351a29；正式v1.16.24/gen33另验；任务worktree独立，无初始dirty。
- 单次自动化已触发后删除，当前执行继续，不设后续调度。
- 前置证据在主仓库output/reference-night-recovery-20261028/，所有操作重新冻结计划。
- 最终开发、发布、实际恢复与未完成数据分别见文末；不以早期检查点代替当前事实。

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

## 本轮最终执行与读回

开发、测试、独立Review、develop集成和正式发布已完成；数据交付为PARTIAL，技术切换成功，不能宣称整体RUNTIME_READY。
v25经PR527/528发布，v26经PR529向前修复整组切换的失败恢复：冻结真实parked owner原drain并沿用request；
旧读端仍活着则保留原PID停驻，已退出则绝不重启，保留restore_unknown待前向恢复。正式v26 exact
33040c99bcb5f9899d55a50a187c08024c4180da，原生cohort计划e468dd93cf2a517fed7097bb1e39217e963d047849bd4911702f3b1323e922d0
返回switched，运行绑定gen34，十身份、六owner、四calendar及API/Web实际读回通过，natural_acceptance=pending。

0054在生产实际提交，原0053触发器未改。首轮生产计划3c0fad618147144923d992a1a716670172e30460e3f8e38e12b96c30766df47e
完成258项既有资产刷新与A5m完整2023起窗口300856输入补建，共259项；在下一单元前对本任务orchestrator单次SIGINT，
未强杀服务。独立stop-readback证明49486d839d33d73713995d67dfa0dc1ed2d5ec790e8193a28e5da6aeb67e9980核实全部259资产、
原件与保护事实、无未闭合历史单元。原controller-outcome缺席事实保留，没有伪造终态或重跑旧apply。

新精确continuation计划f3233660d345467975638905da74e1e239b58421bd55ba41e08ee463f946d4f5完成115条缺口前原件、456路有界缺口、
2503条缺口后原件。06:47自然退出，停止项与unknown均空。恢复结果唯一关联2618原delivery，逐条重算原件/plan/link证明并验证
原生gap receipt/capture/consumed-calculation；逻辑pending/WAITING_HISTORY/blocked/UNKNOWN和pending capture均0。
原2722条COMPLETED及339条BLOCKED不改写。5340条投递原件摘要、冻结路由Scope、完整Source/Completed/index/cursor均不变。
456是流数，5301是逐路缺失端点计数，按physical contract/product/frequency/bar_end去重为4446个观察键，均不冒充Canonical缺失Bar。

正式Reference HTTP健康为现役1080路中960 READY、120 OBSERVATION_LAGGING。
后120为ap/cj/ec/jd/lc/lh/pd/pk/ps/pt/rs/sf/si/sm/ur各8路；120/120原生中断、代际与readback链一致，1395逐路缺失端点在完整原件集合中命中0。
60条SuBing无computed/observed水位，60条Newow保留10/26日盘末端，不能将中断计算冒充行情计算。
gap bar_end/interruption_end是10/27 15:00北京时间；observation_boundary_at为实际恢复记录时间，不能称为行情末端。
它们等待新的自然completed输入和原生计算/必要暖机，不是残余Inbox任务，也没有预先制造首次观察或收益。

历史完整性尚未关闭：06:57末端快照616 CURRENT、253 LAGGING、21 CANONICAL_SOURCE_REVISION_CHANGED、190 HISTORY_SOURCE_MISSING。
该CURRENT仅COMPUTED_ENDPOINT_ONLY；逐资产来源指纹证明与native plan/checkpoint另验。259项均有完整来源/窗口/批次读回，
10个正式HTTP代表样本revision/seq、原since/through与完成记录全等；HTTP coverage.complete_window_proven保守为false，
不以200或单个末端宣称全窗口完整。SR日线融合由既有RefreshThread推进为已知pending/INTERRUPTED，candidate/resume_index256已精确核对，未算完成或UNKNOWN。
剩余历史helper虽已审查并补齐20个无旧revision周线的完整窗口补建入口，但06:45截止时C尚在运行，故没有plan/apply，未在白盘补执行。

静态policy/Rule/身份/schema及配置文件hash与cohort plan相同；实际通知发送行726及hash
28755ed64cf2db74aa7703ff0e8cd32ccab90fd1d2e35b4644497eb9467254f3不变。
06:57相对切换前新增BATCH_PROCESSED837、EXPIRED_NO_SEND63并推进正常游标，所以不能说整张通知表字节不变。
既存199 FAILED_OR_UNKNOWN和527 PROVIDER_ACCEPTED没有重发，provider accepted不证明手机送达。
Runtime全局health仍degraded：Alert coverage/独立暖机与旧transport失败属于本次保护项，未混修。

07:20最终独立读回：全部2618恢复关联、零Inbox积压/阻塞/UNKNOWN/capture、Source与原件/Scope保护再次通过，实际transport仍726及原hash。
既有原生历史刷新继续有界推进，末端快照变为616 CURRENT、242 LAGGING、32源版本变化/重建中、190缺失；合计仍464项未追齐，不能宣称数据完整。
旧v24/v25先按966c74ce39d3d793d438efa84b2f88b0aef2bb5384a7f4c261480bed15a16b47原生sealed保留必要证据，
再两次fresh cleanup-plan确认精确身份与零引用后non-force移除；唯一正式运行/发布树保留v26。
删除后的历史审计/未决部署guard与十绑定已实际复验。后续仅用兼容恢复关联的读端或向前补丁，不能退回旧v24读端。
27份原始测试日志已逐文件hash核对保存到主output。应用拒绝移除本任务primary checkout，故保留该树，不以原生删除绕过保护；普通临时补丁树已清理。

本任务定向pytest的真实日志在
`output/reference-night-recovery-20261028/verification-original/`，核心285passed/1skipped、扩展156passed/2skipped、OpenSpec12passed。
整组切换实际执行下列6文件合计258passed（隔离任务树PYTHONPATH指向其api/core，使用v25锁定解释器）；Ruff、secret scan零发现、diff check通过：

```bash
python -m pytest services/quant-api/tests/test_runtime_cohort_parked.py services/quant-api/tests/test_runtime_cohort_async.py services/quant-api/tests/test_runtime_cohort.py services/quant-api/tests/test_runtime_cohort_host.py services/quant-api/tests/test_runtime_cohort_readback.py services/quant-api/tests/test_runtime_cohort_forward_recovery.py -q
```

一次性executor隔离PG/故障注入6passed、prefix guard3passed，未执行周线helper的故障测试4passed；不将这些测试算作生产资产完成。
正式v26 uv frozen/offline同步、lock check和Web typecheck/build/topology通过，独立高风险Review及生产只读审查均通过。
本地完整证据位于`output/reference-night-recovery-20261028/`；定时reference已删除，无新增每日维护、监控或推送任务。

下一最小步骤：下一自然Session只读验收120路的新completed输入、原生计算与合法暖机；剩余历史资产仅在后续安全窗口继续。
