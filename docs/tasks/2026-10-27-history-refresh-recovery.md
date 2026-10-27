# 历史参考资产刷新恢复

Owner批准从RB日线切入恢复既有历史参考资产更新，包含必要发布/正式整组切换，保持单发布树。
不补造观察、不下载行情、不补建缺失苏冰资产、不补发通知；Scope/公式/Broker/auto_order=false不变。

## 已确认事实和实现

RB趋势D1历史revision f0a513dafb5d463787966b1d234fb2c4/seq22完成到10/26 07:00Z；
10/27请求的新输入比旧资产多1根，原2572输入指纹及Calendar/Session旧前缀全部一致。
20:02 43条pending/REBUILD_REQUIRED；规划时增至48：36条compact60m与12条融合D1，均冻结advance/无resume。
逐checkpoint对比证明紧凑input_count/hash/query范围/来源证明变化以及融合source_dependencies变化，不能放宽为追加。
现有每tick单路、30秒间隔、advance拒绝后等待游标回绕才rebuild，造成续作延迟；不把pending当成未知提交。

公共HistoricalRefresh仅在原生advance明确blocked/REBUILD_REQUIRED、completed_bars=0、无batch/resume，
且committed回调数0时，同一工作单元转换为原endpoint/source_token/manifest hash的rebuild。
先持久化安全pending，再冻结新rebuild并落盘；取消/源漂移/原子写未知均保留原恢复边界。
两段共享1800秒（苏冰沿既有预算）的整体取消截止和原batch_limit，不增加单批提交量。
同一通路处理旧pending；非零effect拒绝转换。原source_identity/compact来源证明和旧revision保留。
现有Runtime报告增加安全刷新进度字段，不逐轮日志、不记录异常原文。

## 验证和交付进度

新增回归先红：2failed/1passed，确认旧实现只advance、不立即rebuild。
定向组合初轮113passed/2 PostgreSQL fixture skipped/8failed；其中6项为转换后让行分支，2项隔离日志目录缺失。
修复让行并补隔离目录后，仅原8项补跑全部passed；新增提交回调反证及安全诊断后仅transition6项passed。
Ruff通过。独立Review无Confirmed Issue；生产需冻结路由/端点，Catalog锁复用原生components scope。
未运行无关全量检查。当前尚未发布、切换或执行本任务生产历史刷新；以后续实际结果更新。

## 实际发布与恢复准备

补丁fdbfe26061集成develop；从main选择性发布，不含独立SimNow。PR524/main/tag/Release v1.16.24，
exact3985524157bf7439f34cf58a3f3184c578563451。候选及正式目录API/core来源、离线依赖、Web能力/类型/build/topology通过；
旧chunk-size警告保留，无下载。一次原生cohort95f474750409405f8ebc37bd1a71c7d7345d753b9f53a2702d6605fdbac0ef43，
20:23:48–20:28:38完成，正式十服务gen33；未重跑attempt。

恢复执行器独立Review先发现写后读回前过早清uncertain，已修正并复核允许执行；未知/验收未闭合保持parked。
两次只读准备分别因旧gen32 drain与SuBing manifest引用表达误拒绝，均无停服/历史mutation；
改用原生generation合同及resolve_manifest权威入口，分别独立复核；旧输出保留。
base002/f611e544691e3c9a961164e2aeb417f213d8cdc97c96b5d0d92d95c6d18fa132冻结434项/排除191项，
apply在正常park后因CHECKPOINT_PREIMAGE_DRIFT拒绝，route intent0、历史写入0，同PID12896/gen33恢复active。

为消除运行中plan→park竞态，准备改为部署/盘后锁内正常park、refresh线程退出/ownerfree后独占refresh锁冻结；
preparedreceipt绑定plan/control SHA、PID/gen/token及原control原字节；apply仅接管自有token，不重复drain。
该增量独立Review通过。base003稳定选择430项（4项已自然推进），排除191，plan
f322d9fb05f459807a5e81764e424ed3a7a4f8266bd3b905692caa3a7f2c14c3，prepared token836d44a438794936b314c3c63e534260；
单次apply中，截止20:57:40。基础完成后另冻结融合，当前未声明资产恢复完成。

## Owner要求开盘服务优先，暂停其余工作

20:41 Owner明确暂停其他修复，优先确保开盘服务。没有SIGTERM/kill历史writer；
经独立安全Review，使用官方Catalog lease在当前完整route结束后阻止下一components进入。
20:43:45.706捕获，10条完整结果；20:43:46.366执行器PID15834以SOURCE_BUSY真实exit1，20:43:46.367释放lease。
原attempt/parked-readback-required均保留，不把安全中止记作434/430项全部成功。

收尾首次检查器把身份字段集误认为含stream_id，KeyError发生在任何resume之前；原报告保留，
修正为原生StreamIdentity计算后，独立读回10个提交checkpoint/逻辑manifestdigest及完整结果；
第11项无nativeplan，checkpoint/control与冻结前像一致，整个refresh控制仅移除10完成项；
无inflight/unknown、原件count和journal/cursor保护不变。history-owner-stop-pre-resume.json保留恢复前证明。
20:46:26.817仅cancel自有token836d44a438794936b314c3c63e534260，20:46:27.026同PID12896/gen33恢复active且owner/source正确；
结果history-owner-stop-closeout-v2.json。随后仅执行一次最终服务跨轮只读组合。

本任务资产恢复PARTIAL并按Owner要求暂停：base430仅10条完成，融合未执行；v24已发布并正式十服务运行，
v23旧树暂保留待盘后封存清理，不执行新数据维护、重放、补发、Scope变更或Broker操作。

20:47:03–20:47:18最终一次跨轮只读组合通过：十identity matched v24/gen33，六active/fresh/source_matches/ownerlockheld，
Reference两轮completed receiving report，所有cursor=tail；四日历registered/enabled；API200/version24、Web200且匹配v24dist，
Live/Feed/Alert available=true、input_failure=null、Feedpending0（休市订阅0）。原件8956/唯一8956，inbox2546completed/63pending/44blocked/UNKNOWN0。
报告independent-v24-20261027T124718Z.json SHA b5099826bb75cb938aecd8c5ecda034478940e5210b9eafb244d376dd5879efa。
独立Reviewer仅对现有收尾报告/原件复核，确认source-entry fencing与Reference恢复闭合，未额外重跑现场检查。
当前结论：开盘前技术服务检查完成；新夜盘自然采集/信号/推送尚未发生，剩余资产恢复与旧树清理按Owner指令暂停。
