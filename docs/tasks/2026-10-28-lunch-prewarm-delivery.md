# 午休预热修复与安全交付

状态PARTIAL：开发、测试、独立Review及发布完成，Runtime promotion未完成；原生取消已独立读回。Owner明确批准此范围，12:50代码/Review、13:00新交接截止、13:15收尾目标均未被跳过。

基线正式v1.16.27。修复c6caa64eb：canonical_warmup_reader新增默认关闭allow_break和可测clock，只有原生cohort显式启用。CLOSED/BREAK均fresh验证current Session为空、next明确且>660秒，BREAK额外必须trading_day；读前后phase完整身份及物理/质量/来源证据重验。全Scope预热前后复用原生Feed.quiescent证明，false不回退实时窗口。正常Alert默认读取与公式、Scope、预热阈值不变。Feed工厂既有RQData认证初始化仍会发生，但预热没有调用行情查询/下载/订阅、创建Event、发送或推进cursor。

TDD新增第一批10与第二批5先红后绿；composition新3项先红后绿。最终相关7文件pytest316passed；独立Review82passed，无剩余ConfirmedIssue；Ruff/diff/secret0findings/OpenSpec strict通过。uv frozen offline与lockcheck、pnpm144包离线0下载、typecheck/build/topology通过。命令：services/quant-api/.venv/bin/python -m pytest services/quant-api/tests/test_closed_runtime_warmup.py services/quant-api/tests/test_alert_closed_warming.py services/quant-api/tests/test_subing_quality_rewarm.py services/quant-api/tests/test_market_read_service.py services/quant-api/tests/test_runtime_cohort.py services/quant-api/tests/test_runtime_cohort_host.py services/quant-api/tests/test_runtime_cohort_parked.py -q。

真实全Scope预热420路：413calculated/7legitimate warming，native_signals_verified=false；源app/core/project root均v28。PR531/main/annotated tag/Release v1.16.28 exact ed3f8aae5e8ca9d96a2b29cb40dcdf50ff44e355发布成功；GitHub创建请求EOF后先只读证实Release实际已存在，未重复创建。develop已集成8a56dbd60。

12:24全新私有0700/0600原生计划2b517dff7e9713794c7e8f2a7181ee3ae7ba7a89571480bed3906f62c7e76c50，目标gen35，过期12:39。单次apply全部六service prewarm通过（Alert413/7、Reference540calculated/60initialized），四calendar按原生暂卸载。drain遇COHORT_OLD_DRAIN_TIMEOUT/reference-worker，原生CAS前恢复，最终cancelled；无stop_old/install/CAS/新gen启动，无强park/kill/扩时重试。

独立实际读回：registry与plan.old、原hash全等，十identity matched；六owner原PID active且持锁/loaded相符；四calendar loaded、无PID且plist字节相同；本代Feed/Live/Alert/Ref drains cancelled，API/Web未被本轮触及的旧gen33控制不适用于现役gen34；unknown部署guard通过；native保护Scope/通知配置/规则/身份/文件hash全等。这不等于全原件表或通知流水逐行相等，不宣称自然业务就绪。

12:33actual v26/gen34；pending640/blocked0/UNKNOWN0/completed4632/lastcalculate12:31:40，比12:30completed4600有所推进；last_ingested12:33:23。Feed available/pending0/noerror，采集与基础依赖正常；Reference ready=false且报告间隔仍长，全局degraded。10秒drain短于可能不可中断的单delivery原子计算；已有每原件/每delivery的stop检查，不能依据stage=scan指认卡在scan或历史线程。CPU持续推进、PG无Lock等待/Canonical维护锁0，不属已证明死锁。后续须只读定位单元耗时再设计有界协作取消，不能只加timeout或强杀。

停止本次生产交接，不新增调度、不补历史、不制造信号/通知/订单。证据output/reference-lunch-v28/保留真实420预热、plan、取消state、独立readback及当前状态；原私有attempt不改写。发布v28不等于运行v28，旧v26/gen34继续服务。
