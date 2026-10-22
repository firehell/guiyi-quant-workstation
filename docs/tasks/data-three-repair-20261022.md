# 10/22 三项数据修复

状态：PARTIAL；三项修复已执行，第三项自然验收尚未全部发生。用户交办顺序为实时链路、四合约D1、240路H1。原始观察缺失、可恢复的行情输入、Reference中断和自然验收分别记录；不把价格补取冒充原始观察。

## 已完成的实时与D1修复

- 正式身份保持v1.15.16/gen22/c559eb7a594dea5189c7a630b010a284032e89f4，无发布、公式、Scope、Rule、audience或交易阶段变更。
- Live PID62248经单次原生drain/cancel、同PIDparked/owner锁和四日原像核对后恢复。Feed PID62254原生关闭时退出，第一次attempt保留OWNER_CHANGED_READBACK_ONLY；独立只读证明旧进程不存在、新PID32887在同drain下未启动provider且日志原像不变后，用新的forward-only attempt恢复新实例。旧buffer未知和关闭失败保留，未重试旧关闭。
- 22:00–22:35的45夜盘品种各35根自然1m，source/completed共各1575根、权威端点缺失0。原始21:01–21:57缺口未伪造。恢复后既有原生Live recovery继续按既有配置运行，输入恢复与原始journal证据分开。
- AL2612/PG2612/PS2612/SI2612仅1d上市日至10/22：44次来源请求、44个月分区发布，原生后验计划均零目标；4旧文件和5根已存在Bar逐值/哈希保持。
- AL204、PS205、SI205有效日线；PG190有效Bar+5条来源零OHL事实，共195端点。5条事实日期为2/10、2/12、2/13、2/25、2/27，按rqdata-d1-zero-ohl-v1保留原数值和来源hash，不造价。第一次要求PG全为valid Bar的验收失败保留，随后独立核实为既有typed quality事实而非下载缺失。
- 四品种原生SuBing窗口/evaluator/内核只读验证均valid/ready；PG使用最后质量中断后的158根有效窗口。不写Event、不补发。

## H1修复、停止与独立续接

- 实时恢复后176 SOURCE_UNAVAILABLE消失；旧日故障使236路OBSERVATION_LAGGING、L四路DATA_CONFLICT。全60品种以实际21/22 source/completed journal/index、单调日注册23、旧消费者追尾、cleanup及Session/rank1证明旧日缺5个H1端点，只覆盖10/22 15:00。
- 原生同PID29965/gen22 Reference停驻后，L四路原子新建empty-reset未来FLAT版本，保留旧DATA_CONFLICT；另236份精确gap receipt和原生interruption calculation逐条完成。没有replay、ACK、改游标、通知或新Scope。
- 首caller在23:00报RECOVERY_PREFIX_GAP_REQUIRED安全停止：原先预期22:00 H1缺失，但恢复后的既有Live输入修复已使22:00与23:00共90根原件完整保留，且都在Reference游标之后。因此禁止补写180份假gap，不重跑旧attempt。失败记录与原始manifest原样保留。
- 独立post-stop读回证明236收据/计算全部提交、L4仍pristine、90原件与index/Session一致且未ACK、旧20108批次/6129核对/645动作无缺失改写。480路在此刻新冻结为续接前像；原caller只存内存的480摘要不能追溯补证明。
- L旧未来起点22:55会跳过真实22:00输入，故新增独立reference_retired_original_warmup_v1，仅接受此次L4 pristine empty-reset版本；用真实22:00、23:00原件原生kernel暖机，保留旧冲突及空reset版本，建立23:45未来FLAT版本。末尾重复核对原件/index、contract、端点和metadata；不创建维护Capture/action、不消费journal，health继续OBSERVATION_LAGGING。
- 新235文件冻结manifest SHA6628a67e77e6fa974800ab689e8b3015993cba87a1087943ea06018b02c6fccd。独立Review发现实时plan expiry fence缺失后已修正并复审通过，原发现保留。独立exact v16兼容8项、21定向测试通过后执行单次新continuation。
- 新attempt最终独立核对4新seed/checkpoint/manifest/activation、全部20592续接前批次逐字段hash、旧核对/动作、其他480路新前像、90原件和原游标不变后，取消原同PID/token停驻，恢复正常消费者。旧失败无重试。

## 23:13–23:15最终现场读回

- 完整正式health：720 enabled，656 READY、64 OBSERVATION_LAGGING；SOURCE_UNAVAILABLE=0、DATA_CONFLICT=0、pending Capture=0。source Live及completed Alert/Reference四日全部追尾。
- 44夜盘品种176路经正常消费者算至23:00：capture→committed calculation→原journal ID/原始confirmed/raw时间/hash核对通过；不是维护replay。原生融合依赖趋势/震荡两来源。
- 其余64路为15无夜盘品种60路（checkpoint仍10/22 15:00）与L4（真实原件已暖至23:00但新起点23:45）。原生权威Session证明全部下一H1为10/23 10:00，尚未自然发生；不能把存储health标签当业务验收。
- 176路中88趋势/主升浪availability ready；44震荡warming、44融合WARMING继续真实保留。中断后清空的策略内核需新增有效Bar暖机，不伪造历史连续性。
- 最终旧事实逐条无缺失/改写：20108旧batch、6129旧reconciliation、645旧action；正常消费新增记录独立保留（当前21308/6137/649）。
- 实时自然验收已扩至22:00–23:00：45品种各60分钟，source/completed各2700根，端点缺失0。23点部分收盘品种按窗口内22:30集合确定，保留首次错误检查断言；旧21:01–21:57原始观察缺口不被补价改称原件。
- Runtime保持v1.15.16/gen22；同PID Reference active，有新last_success。heartbeat pending_keys/ready与扫描阶段波动不替代完整health，不宣称全局RUNTIME_READY。

## 验证

- `python -m pytest services/quant-api/tests/data_foundation/test_historical_data_manager.py -q -k contract_warmup`：66 passed。
- 前两新测试及bounded/conflict/final-warm定向：41 passed、4 skipped；独立13 passed。新增original-warm及两retired模块：21 passed；exact v16 SQLite新暖机兼容8项通过。
- Ruff、`openspec validate reference-trading --strict`、`git diff --check`与精确文件secret scan通过，秘密发现0。
- exact v16隔离SQLite验证四路reset/rollback、原生连续gap receipt消费；实际repository/recovery/bounded模块均从正式发布树加载。它不是自然业务证据。

## 证据

任务证据统一在`output/data-repair-three-20261022/`：四日preimage与失败attempt、实时自然数据、D1计划/发布/后验/consumer验证、sealed-day preflight、独立Review、兼容验证、不可变事实基线及h1-attempt-1。原有`output/reference-recovery-20261021/`记录原样保留。

唯一下一步：10/23 10:00真实H1发生后核验剩余64路自然消费与指标暖机；本轮不新增定时任务。历史旧缺口、旧Feed buffer未知、PG五条来源质量事实原样保留；不以修复批次或Runtime身份宣称全局RUNTIME_READY。
