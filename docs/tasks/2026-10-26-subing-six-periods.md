# 苏冰参考交易六周期

## 任务与身份

用户交办六周期历史参考、页面与持续记录；保持不推送、不创建订单。实现基线
`058a7fed567c46dbc5691e9e34192ecd9dfb7f77`，隔离分支 `codex/subing-six-periods`。

历史新增5m/W1分别使用 `subing_ths_5m_v1`、`subing_ths_1w_v1`；原四周期身份保留。
持续记录新身份为 `subing_physical_prefix_forward_v2`，沿用现有flat seed、原子激活、
耐久journal、checkpoint和历史刷新线程。首根、换月和缺口恢复只预热指标，不继承历史持仓。
5m/15m/30m/60m读取真实completed观察原件；D1/W1读取已确认Canonical。

页面六周期开放实时参考收益和留存记录，失败不回退历史重算；消息筛选不再展示1分钟。
历史回算API与实时留存数据保持独立。周线以Calendar/Session证明完整周，显式结束日期不改变证明时点。

## 验证

- 苏冰和参考交易非PostgreSQL完整回归：995 passed、9 skipped、78 deselected；隔离存储单独验证。
- 可销毁PostgreSQL 55433与Redis 16389/11：六周期原子激活、持久化、历史刷新、journal及恢复78 passed，0 skipped。
- Web全量：1240 passed、3 skipped；类型检查及生产build/topology通过。
- 六周期浏览器读取与失败不回退：1 passed，覆盖全部六周期。
- 补充正常周/节假日短周/显式日期及周线API定向49 passed。
- OpenSpec12/12；独立高风险Review关闭首根水位、换月顺序、周截止和质量事实类型问题，允许集成develop。

隔离存储首次配置因测试URL等于runtime比较URL、Redis端点不符被安全校验拒绝；修正为两个独立测试库
和合同规定的Redis端点后才通过，没有修改测试安全校验或使用生产库作为测试库。
旧浏览器用例依赖已移除的筛选按钮，本次改为验证现役实时参考面板；不宣称旧布局逐项一致。

## 真实数据与待完成项

只读扫描冻结2023-01-01（或品种上市覆盖起点）至2026-10-23，as_of=2026-10-24T08:00Z；
这是明确的历史快照，不证明10月26日盘后数据已发布。RB/JM的5m/W1真实回放样本可读。
扫描与计划保留于任务工作区 `.task-evidence/subing-six-periods/`，尚未启用新流。39个源可证明的W1历史资产已按原生计划构建，独立读回全部READY，截止均为2026-10-23T07:00Z；RB/JM公共历史API读回200、persisted和正确周线公式身份。

CJ2305物理周线前缀有已分类NONPOSITIVE_CLOSE：2022-W20缺价日2022-05-19。
真实weekly质量入口返回45根正常周线与1个来源中断；保持数据不足，不补造价格或Bar。

全品种完整历史存在独立存储边界：例如AG15m原生计划22.54MiB超过CLI16MiB限制，
现有批次还重复保存完整来源指纹。完整历史存储改进与限定首版窗口需owner确定；不静默缩窗、
绕过CLI边界或直接写入大量重复manifest。360路扫描完成：296份计划、64路源/预算阻断；其中46份计划另超过CLI16MiB。39路W1已构建，其余历史、持续流启用、发布/切换与自然验收未完成。完整历史存储选择仍待owner决定。

代码已集成并推送develop `7bd191c41`；本地8002开发API已加载该代码，5175页面显示苏冰六周期。正式v1.16.7/十服务未切换。真实构建计划、结果与源扫描另存 `output/subing-six-periods-20261026/`，未重复执行任何已完成构建。

## 完整历史存储改进

owner明确选择保留2023年以来完整历史，不缩短窗口。计划文件保留16MiB描述符边界，
超出时使用同目录受限、逐块校验的压缩分片，完整解码上限256MiB；原逻辑plan hash不变。
刷新控制文件使用固定子目录中的内容寻址计划，原子完成标记与失败原件保留。
苏冰历史批次按同stream/revision的已提交inline锚点引用大来源向量，保留完整来源digest、
状态、交易与payload身份；旧资产和其他策略不重写，不进行schema migration。

新增存储、原生CLI、刷新、六周期capture及原子激活等隔离PostgreSQL/Redis回归102 passed；
FIFO/符号链接、损坏、越界、重复key、解码上限及失败恢复均拒绝。真实AG15m计划
23,637,634字节转为978字节描述符和12,867,765字节分片，原生dry-run确认plan hash不变，
没有生产写入。独立高风险Review关闭FIFO问题后允许集成。正式读取端仍v1.16.7，
升级前不生产新引用格式资产；39个已构建W1不重复执行。

统一候选合入并行develop后，参考交易/苏冰与部署交接回归1206 passed、9 skipped、79 deselected；
canonical一致性18 passed，Web类型/build/topology通过。独立合并Review另验后端69 passed/9 skipped、
Web103 passed，允许进入release candidate；应用候选版本1.16.8，尚未声明发布或Runtime切换。

## v1.16.8发布与现场阻断

PR487已合并main，annotated v1.16.8及GitHub Release exact
`9b559ce80b968f214347aa49abdb4d649aff915d`；正式树
`/Volumes/扩展盘/guiyi-quant-workstation/.worktrees/release-v1.16.8`的离线Python/前端依赖与Web构建通过。
原生整组plan v1仅只读即拒绝，未停服、未CAS：逐服务确认只有after-market空闲身份不成立，
PID25301仍运行。自然行情维护18:11已passed，消费者检查仍not_verified；不终止或重跑自然业务。
维护锁读回为既有客户端持有，45路仅预算/锁阻断路重新只读规划均SOURCE_BUSY，未启动apply。

296份原计划全部转为有界原生文件并逐份逻辑hash核对，保存在任务证据
`.task-evidence/subing-six-periods/packed-full-history-v1/`；尚未缩窗或生成新格式生产资产。
独立生产前像：56个苏冰流，55 READY/1 NOT_BUILT，enabled forward=0；39路已完成W1保留。
开发API仅重载本任务PID17069，替换后8002 health读回1.16.8；正式8000与十服务仍v1.16.7/gen29。

当前为PARTIAL / RELEASED，运行切换、剩余完整历史、v2激活和自然新Bar验收未完成。
下一触发条件是自然盘后PID退出且维护锁空闲；届时生成全新有效期内cohort计划，先切换所有读取端，
再执行精确历史计划。旧生产资产不删除；未知结果只读核对；不借回放补造自然记录，不新增监控任务。

### 后续现场读回（覆盖上一段当前阻断）

盘后PID随后自然退出，消费者审计incomplete；未将该结论改写为通过。全新cohort v2只读freeze通过，
但其计划父目录为公共/tmp，不符合原生安全读取合同，apply在attempt创建前拒绝；已证实不存在v2attempt。
转为0700私有目录及0600计划后，全新v3 hash
`3fe300223ac7ae36cdd2a1ef567cc94e942bedaacdb482c76d15da3da857469d`进入预热，随后原生取消。
state.json保留phase=cancelled、effects={}、error_type=CohortError；无停服/CAS，不复用该attempt。
单独Reference同预算只读预热定位为REFERENCE_WARMUP_TIMEOUT（120.01秒），堆栈在Canonical租约等待。

维护锁属于已有并行只读全量审计
`output/data-complete-audit-20261026/parallel-full-audit.py`，最近完成52/60，未干预该任务。
实际切换与新格式历史写入仍阻断。360路未来20:55开始的v2激活计划仅readonly生成、未apply；
原生registry/global phase守卫禁止在旧版本运行时激活；过期后必须生成新计划。
其私有意图保存在output/subing-six-periods-20261026/activation-v2/，不能据此声明流已启用。
剩余历史原生驱动仅准备并语法校验，未启动；保持原AL15m candidate和39路已完成W1，不覆盖旧事实。
下一步唯一前置是既有审计释放锁，然后用全新cohort计划重新完整预热和交接；无须owner重复授权。

### v4完整预热与排空取消；诊断向前补丁

并行审计最终60/60 passed，维护锁独立读回为空，故冻结全新v4计划
`b60835c2fe92db2f5a1108e2062c77a1fd55c919cdcf1c74c4397c47a972c689`。
完整候选预热全部通过：Alert413计算/7明确warming、Reference480、API18路由、Web构建hash、
Live/Feed60品种闭市及cursor=tail。随后原生calendars_off完成，但drain步骤取消；未CAS，
原日历自动恢复。全十服务独立readback均matched/v1.16.7/gen29，API/Web HTTP通过，
Feed恢复后PID40179，其余五常驻PID未变；全局runtime health仍blocked，不冒充自然READY。

原控制器仅保留error_type，具体排空拒绝码被外层取消码覆盖，无法据此猜测root cause。
1.16.9候选仅补齐failed_phase、安全CohortError协议码及已知排空服务名，不记录任意异常文本，
不改变停止顺序、时间预算、CAS与恢复条件。新增先红后绿回归，相关部署191 passed；
独立Review135项及服务名隐私补验通过，允许进入release candidate，不声称drain已修复。
旧tag/attempt原件保留，禁止以dirty Runtime继续切换。完整历史和360路激活仍未执行。

### v5定位preserve上限；1.16.10修复候选

v1.16.9已由PR488发布，exact cb6836a4abe3f733f59161242c0e4d9756acda20。
v5 hash a35564963002720b705612940dfc2c9cc74f202bbd8c83cc5d67dba7c4d8f44c
完整预热、calendars_off、drain、old_exited通过；诊断明确failed_phase=preserve、error_type=ValueError，
原生自动恢复并cancelled，未CAS。部分原件保留在私有attempt/originals，含私密配置，不搬到普通输出或展示内容。

现场相同控制文件：普通CohortHost.bytes抛ValueError，原安全file_snapshot使用其既有64,000,000上限完整成功，
当时2,276,292字节；自然控制继续推进至2,646,411字节。修复后相同安全读取得到完整长度及sha256，未改文件。
根因是交接读取上限与既有历史刷新控制合同不一致，非价格/公式问题。1.16.10候选仅在稳定目录下精确
newow-historical-refresh-state.json复用读写共享上限，普通配置/外目录/显式limit不变；不改drain/CAS/恢复。
新增先红后绿的2.27MB、超界、外目录与symlink测试。相关256 passed/2 skipped；独立141/2及Review通过；
统一写端同值常量后再验109/2，Web/type/build/topology、Ruff、secret0、diff通过。
旧v4/v5原件不复用，正式身份仍按实际恢复读回，不把发布9或候选10说成已切换。

### v6正式切换、真实存储与360路激活

PR489／tag v1.16.10 exact a80753c3cf32fb2759920d26f88a1ba6cbc8ea02。
v6 hash f6d42ea520c3ddfc99228961ac1fc74986486a3d09be9c0cb0705ab8921b2637原生switched；
十服务同root10/gen30；独立readback通过，两次132.5秒PID全相同。API/Web HTTP200/1.16.10，
整体runtime health仍degraded，版本切换不代表自然业务Ready。修复已通过真实preserve步骤，旧失败attempt均不重用。

原生完整历史驱动经独立Review后执行，固定exactv10导入根与正式配置，所有candidate跳过，
每路native计划/意图/回调/报告fsync；未知结果停写，20:45前取消不缩窗。日线60全部completed；
周线保留39、新增JD完成1、20来源不足blocked；60m及后续分钟继续，实时ledger单独保留。
真实AL日线43批42compact，所有引用完整digest一致、query_since2023-01-01、cutoff10/26；
公开API先请求多年窗被既有366天合同422拒绝，改用合法2026窗口200/persisted，未改变完整资产范围或API边界。

360路v4激活scope hash fc5eb4305c8a85b456dca0b806792f3fe9e186c54250b7520be3577af8c530a2，
在20:10:09有效期内成功apply全部360，逐条native receipt/fsync；与exactv10、v6 switched绑定，旧v2/v3意图未执行。
20:11独立DB六周期各60、policy=subing_physical_prefix_forward_v2、recording_start20:55一致，
receipt360、capture/action/trade均0；剔除授权新增360身份后的保护hash完全匹配v6，规则/通知/其他scope未变。
历史HISTORY_SOURCE_MISSING与质量阻断仍独立验收；seed/READY不是自然新Bar证据。
开发API与Vite已在精确PID核对后重载1.16.10；原5175浏览器保留，实际DOM六周期及全部周期，无1m；
截图/tmp/guiyi-subing-six-v10.png，不把已有历史预警显示当作本次forward自然验收。
