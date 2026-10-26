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
