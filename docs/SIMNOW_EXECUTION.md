# SimNow受控订单适配 v2

本模块实现已持久化HTDY账户提案到CTP报单/撤单请求的窄适配，以及原生回调到本地账户journal的事实接入。
交易规则、资金预留和订单状态机见[HTDY合同](HTDY_SIMNOW_V1.md)，登录及四类只读查询见[只读合同](SIMNOW_READONLY.md)。
只读CLI保持只读；core适配模块不自行登录或注册前置。一次性宿主与独立持续宿主显式连接固定第一套，均默认只读；持续新开仓代码须显式trade双重匹配；正式启用状态只看STATUS，当前`auto_order=false`。

## 接入和事实责任

`guiyi_quant.simnow_execution` 注入当前已登录API、SDK、`LocalStore`及独立私有`Journal`。
`Session`必须来自实际登录、交易日、FrontID、SessionID、MaxOrderRef和已确认结算事实；
只接受固定第一套 `SIMNOW_FIRST`、Broker9999、30001；不fallback到测试副本或其他券商。
账户身份沿用只读工具的环境/Broker/User摘要；投资者代码只在内存中填充请求，不写日志、报告或Git。

- `Contract`由权威合约元数据明确绑定Canonical物理合约与原生InstrumentID/ExchangeID，CZCE三位原生月份不能自行猜年。
- `Inventory`保存同物理合约完整核验的今/昨仓与方向；SHFE/INE用平今3或平昨4，其他交易所使用平仓1。
  不允许对锁、超过一手或无法解释的仓位进入该单仓适配。
- `ExecutionInput`继续由既有行情/Session入口提供新鲜度和对手价事实，不另建resolver或用测试行情替代自然输入。
- 当前初始profile要求初始空账户Readback权益10万元，原生交易日不早于20261027；实际生效必须通过第一套读回验收。
  本地日期或Session对象本身不能代替原生资金验收。已运行后的账户不要求始终保持10万元。
- 输入事实及来源ID均须由受信任宿主从原生或权威数据生成；数据类不是密码学证明。
  本适配器不能从注入API对象反查其连接地址，宿主必须证明实际API与Session来自同一次固定第一套登录。

## 单次发送与恢复

调用 `action_hash(state,effect,session,contract,inventory,execution)` 生成精确计划身份；
宿主为具体动作提供 `Permit(intent_id,account_id,trading_day,action_hash,issued_at,expires_at)`，有效期最多60秒。
Permit是有界执行意图，不是数字签名或后台自动许可；本模块不自行生成授权、策略信号或递归追单。

`Adapter.dispatch`执行前重新校验精确状态、账户、来源时效、当前对手价、Session、持久预留和收盘截止。
`LocalStore.dispatch_guard`持有账户SQLite writer锁覆盖同步SDK请求受理调用，防止另一writer同时更改审核状态。
原生回调在此期间只stage到独立发送journal，退出后在宿主受控主循环中drain，不能在回调中调用账户事务。
原生SDK阻塞时锁也会保留；没有声称为本地C++调用提供硬超时，应停止进程后先核对，不能重发。

发送journal以0600保存；BEGIN IMMEDIATE原子领取每个order/action并分配OrderRef/RequestID，领取成功才调用SDK。
同一动作包括崩溃、异常及非零返回都不重发。领取与网络调用无法组成分布式事务，崩溃后“领取但未发/已发未知”
必须查询柜台，不能把它当成安全重试。写入结果未知时停止发送，不更换文件绕过领取记录。
撤单使用原单FrontID/SessionID/OrderRef；撤单拒绝、超时或结果未知不释放资金、不创建替代单。
SDK返回0只是请求受理；`expire_unacknowledged`由宿主在受控轮询中检查25秒无原生确认，转未知待核，不重试。

## 回调与精度

`Callbacks`是无副作用SPI mixin，放在宿主已登录SPI基类前并绑定 `execution_adapter`；
提供OnRtnOrder/Trade、OnRsp/OnErrRtnOrderInsert/Action及断线stage，不自动RegisterSpi/Init或重连。
账户/交易日/物理合约/方向/开平/数量/价格/原生身份逐项核验，白名单事实先独立持久化，再由 `drain` 幂等写账户journal。
交易日关联持久原单而非新会话日，允许前日已知单的迟到回报。

成交须与已保存的交易所OrderSysID唯一一致；缺失/冲突保留pending，不能投影为本程序成交。
未知成交保留白名单quarantine和fault；不可解释成交不会被丢成空仓。fault阻断该adapter继续发送，需完整核验后重建会话。
断线、FILLED/UNKNOWN等回报在重开后仍能落事实；存在unresolved成交时全链保持BLOCKED。

CTP TradeTime/InsertTime为秒级，不能把向下取整时刻当精确先后。新增 `NativeFill` 保留原始秒端点、
`native_precision_seconds=1`、实际请求开始时间、持久dispatch来源及原生SystemID。
关联订单证明因果，原生秒区间须与发送时点相容；不增加虚构微秒，不在信号Bar假装成交。
原精确 `Fill` 的strict-after约束不变，旧公式、Alert及参考收益不改写；新事件身份独立序列化并可重放。

CTP逐笔Trade没有实际手续费字段。适配器保存待核成交，只有具有实际费用来源的 `Fee` 证明后才生成完整NativeFill；
不得将开仓预算或预估费率当实际费用。缺费事实会阻断后续发送。当前由 `inventory/finance/evidence/host` 接通完整原生资金/今昨仓快照投影及有界费用归因。
实际费用仅在同账号同交易日、非重叠的两轮稳定快照之间恰好一笔新成交、旧成交不变、无现金流或其他订单变化、原生订单及SystemID吻合时，使用原生累计Commission差额。
多笔、跨日、旧事实变化或无法唯一归属时保留待核，阻断新发送；不把预算费率当实际费用。
原生终态回报仍不直接释放预留；只有完整资金/仓位/委托/成交核对可使账户状态机释放。

## 验证与剩余实测

无网络兼容性工具：

```sh
/path/to/isolated/python -I scripts/broker/simnow_order_compatibility.py
```

工具使用明确synthetic fixture和真实Mac `openctp-ctp==6.7.7.1`请求结构，不创建原生API、不读凭据、不注册前置。
`SDK_STRUCT_COMPATIBILITY_PASSED`只证明请求字段与SPI mixin兼容，`broker_e2e_passed=false`保持。
离线测试命令见[TESTING](../TESTING.md#simnow-受控订单适配)。

真实受控端到端须完成：第一套登录与两轮账户读回、10万元生效、结算确认和原生元数据/新鲜报价绑定、
已实现宿主的现场读回、可交易时段的新合格信号，再对精确一手订单做报单/成交或撤单核对。
真实报撤单及成交闭环仍单独验收；持续宿主范围见下节，不发布、不切正式Runtime。通过离线验证不表示可以开启全品种自动交易。

## 全品种持续宿主（simnow_continuous_v1）

`scripts/broker/simnow_supervisor.py --config <private.json>` 使用一个交易连接、同一账户锁、账本、发送journal、
资金预留和持久信号队列，覆盖冻结的operational集合。禁止用60份单品种脚本扩展。账户根仍为
`PROJECT_ROOT/output/simnow-controlled/<fingerprint>`，不复制、初始化或迁移已有AL账本。

原v1提供 `observe` 与 `manage`：observe不构造交易Adapter、不确认结算、不写账户命令、不创建提案/预留；
只读校验已有账本与原生快照，串行轮转检查各品种输入。manage接管已有义务，允许已知平仓/撤单，
通过持久的 `ManagedTickV1` 在创建OPEN或预留之前禁止新开仓，Host发送前再次拒绝OPEN。
旧Tick/Recover及v2账户hash不变；新管理Tick和按品种恢复命令各有独立版本，旧命令可逐条重放。
全品种新开仓的v2入口见下节；正式Runtime启用不能由配置改成execute或启用observe推导。

- 一个共享RQData入口及Redis pubsub接收全部60m自然完成Bar；信号以首次观察时间、品种、来源ID排序。
  `(product, bar_end)`及来源身份冻结首次payload，重绘不覆盖；账户commit后才ACK。重启有commit的查receipt，
  无commit旧队列丢弃，不能补做历史开仓。预开盘只准备连接，首次实际交易时段前不接信号。
- Calendar/Session决定交易日与开盘，最多提前120秒登录；日期无法证明则不消费信号或执行。正常午休
  保留连接与已接收信号，不当故障；各品种交易及最终收盘仍以自身Session为准。
- 新连接/日切先原生资金、持仓、委托、成交完整读回；已claim的离线成交先验证身份、接入真实回调及费用，
  再做完整持仓对账。已核成交跨日不要求当天查询重新返回历史记录；不伪造费用和跨日现金流。
  manage在ownership证明后查询/必要时确认当天结算，再构造同次登录的Session。Session有效上界为已核交易日
  次日00:00，覆盖周五夜盘归属周一，不把自然日期当作交易日。
- 单品种warming/数据问题按品种列阻断；`ProductRecoveryV1`只恢复明确blocked产品，健康产品信号与目标保持。
  首个待平品种报价不合格时尝试其他待平品种；全局一次最多一个未对账SUBMIT，避免多成交无法唯一归费。
  平仓/撤单不受旧有界脚本的总次数或deadline限制，仍须新鲜账户/今昨仓/合约/Session/对手价事实。
- 两轮快照变化只等待同连接新读回，不当空仓或重登。只有明确连接中断/超时才按60秒退避建立新连接，
  每权威交易日最多3次连接attempt，进程重启不重置。身份错误、callback异常、未知commit或未知订单结果
  持久阻断当日，cleanup失败同样阻断；不重发已领取动作，不释放未证明的资金。
- 原生执行报价继续来源年龄<=8秒及接收后3秒TTL。先查费率、最后取盘口，避免批量60次查询用老价；
  未成交3分钟及收盘前1分钟取消等规则沿用账户状态机。没有可信报价时不得重新定价。

配置为0600 owner文件，精确字段：`schema=1,account_id,state_root,project_root,sdk_python,api_env,mode,enabled`。
SDK使用独立同ABI Mac ARM64 `openctp-ctp==6.7.7.1`环境，`api_env`是既有API依赖venv目录。
凭据通过 `scripts/broker/simnow_credentials.py provision` 在本机TTY隐藏输入，直接存macOS Keychain；
不保存到JSON、参数、日志或聊天，headless Keychain不可用/锁定/拒绝即停止。首次配置需要本机输入一次，
不能从旧聊天、一次性进程或代码中复用密码。
既存项需要更正时，使用 `update --expected-account-id <fingerprint>`；先校验身份再隐藏输入，仅通过
SecItemUpdate修改既有项的值，不先删除、不创建缺失项、不改变ACL，写后读回匹配才报告本机成功。
本机保存成功不等于柜台接受交易密码。

`scripts/ops/macos/simnow-service.py --config ...` 默认仅render/plan；显式 `--install-observe` 才安装可选
`com.guiyi.quant-simnow` plist，不调用launchctl，不改既有十服务。安装入口只接受enabled observe，
ProgramArguments固定 `-I ... --observe-only`；日后JSON改manage也不能使该自动启动项升级执行。
RunAtLoad、失败KeepAlive和60秒Throttle负责进程启动；业务恢复仍须上述完整读回、预算和耐久阻断。
`--check`只校验配置与SDK兼容，不读Keychain、不连接Broker。关闭方式为先停止可选服务，再保持enabled=false；
保留全部账户、claim、队列及原生证据，不能删除重建以绕过恢复。
普通stdout/stderr位于 `~/Library/Logs/GuiyiQuant/SimNow`（0700）；launchd在启动解释器前打开日志，
不能将其放在受保护扩展卷。账户及证据根保持原位置。启动依赖沿用既有本地启动器的认证口径：
空或文档默认Redis URL补入既有REDIS_PASSWORD/POSTGRES_PASSWORD，自定义URL不改写，配置值不输出。
`--check-keychain`在SDK、行情订阅或宿主创建前仅检查本进程能否读取预期Keychain项；与`--check`互斥，
可用于一次性后台加载验收，不发起Broker请求、不解除block。启动异常只输出固定阶段和异常类；
宿主异常在释放前以0600独占保留阶段及既有脱敏原生协议诊断。诊断记录失败同样阻断重连，不能因重启丢失。

持续宿主发布私有原子 `continuous.json` 状态及现有监控索引，native来源和账本摘要分别绑定；
发布失败不改变交易行为。观察模式未更新账户策略投影时，页面不得将旧账本预算称为当前已对账。
编码、离线验收、本机凭据/启动验收、自然跨日/断线以及首笔柜台交易分别报告。

## 独立关闭态准备（schema 3）

schema 3 沿用 schema 2 的精确字段，但仅接受 `mode=observe`、`enabled=false`。
`state_project_root` 必须是独立的0700目录，`state_root`仍为其`output/simnow-controlled`；
该状态根只能不存在或为空，路径别名、symlink、已有账户内容均拒绝。配置为0600单链接文件。
账号指纹只绑定未来对账对象，不证明旧账户已空仓；旧状态保持UNKNOWN，新账本保持UNINITIALIZED。
不复制四库、不初始化余额、仓位、订单或发送记录，不修改正式监控来源。

`simnow-service.py --preflight-preparation`只验证上述合同并用配置指定的SDK解释器运行
`simnow_supervisor.py --observe-only --check`。不读Keychain、不连接Broker、不订阅行情、不创建锁/账户库、
不安装或加载服务；SDK检查前后都重新验证配置和空状态根。结果使用`simnow_preparation_preflight_v1`，
仅`preparation_valid=true`，账户/余额/持仓未核验，`runtime_ready=false`、`execution_permitted=false`。
schema 3不能启动、检查Keychain、渲染/安装服务或取得账户运行锁。schema 1/2原有规则不变，
尤其schema 2缺四库仍拒绝；准备通过不解除以后真实账户对账、账本初始化及运行准入限制。

### 显式只读核验与 observe 初始化

`scripts/broker/simnow_observe_bootstrap.py` 要求精确私有schema3配置、新0600输出路径、带时区
`--deadline`，且必须二选一 `--read-only` / `--initialize-observe`。这是独立账户操作，
不解除schema3的启动、安装及准备预检限制。两种动作先取得与正式宿主相同的全局账户互斥，
再从既有Keychain加载凭据，通过固定SDK完成两轮资金、持仓、委托、成交查询；原生API白名单
不含结算确认和报撤单。原生输出静默，结果及有限诊断只写私有文件；连接必须关闭。

只读动作不创建四库，旧账户保持UNKNOWN，新账本保持UNINITIALIZED。初始化动作必须在fresh全部
CLOSED且确认宽限结束时重新查询，并在发布前重验闭市、配置、截止时间和30秒快照新鲜度。
空仓、无活动或未知委托、无未解释占用均成立后，使用柜台真实资金建立独立平仓基线，不继承旧历史。
占用字段须为零且Balance与Available一致；不猜测未采字段导致的资金差额。
四库与disabled schema2/observe配置先在同一私有临时账户目录创建、关闭及完整验证，再原子rename
到正式账户目录；部分失败保留临时证据，不启用、不覆盖已有账户，重复初始化拒绝。

observe宿主可在fresh全部CLOSED、无当前Session且下一场仍在未来时建立账户只读连接，
状态为`OBSERVING_CLOSED`；不领取执行输入、不构造交易Adapter。manage/trade仍沿用原交易及
开盘前120秒连接规则。此连接许可不代表交易许可；正常schema2启动与四库完整性校验仍保留。
闭市连接还要求已持久原生证据的交易日与计划一致；柜台尚属旧交易日时等待原开盘前连接窗口，
不提前消耗或阻断下一交易日的连接预算。

observe连续两轮真实账户对账完成后，可原子发布
`~/Library/Application Support/GuiyiQuant/simnow-monitor.private.json`，内容为已启用schema2/observe
私有配置副本。API逐请求使用既有严格settings及四库校验读取绑定，无需重启；文件不存在时沿用
原监控来源，存在但无效则显式503，不静默回退。该绑定仅决定只读监控来源，不启动宿主或授予交易。

## 持续交易候选（simnow_continuous_v2）

本版本增加 `trade`，仅schema2且启动参数 `--trade` 同时匹配才进入；旧观察plist仍固定
`--observe-only`，仅改JSON不能升级。trade复用同一账户风险/预留/订单状态机，新增不可变命令
`ContinuousTradeTickV1` / `htdy_60m_continuous_trade_v1`。observe不构造Adapter；manage仅管理义务，
不新开、不强平。旧账本事件与hash、旧Tick和人工关闭版本的语义不改写。

schema2是在schema1精确字段基础上增加 `state_project_root`：`project_root`绑定当前代码，
`state_root`固定为既有 `state_project_root/output/simnow-controlled`。必须已有同账户四库
account/dispatch/signals/native-evidence、正确scope、0700目录和私有单链接常规文件；只读校验拒绝WAL，
不创建sidecar、初始化、复制或迁移账户。缺库或身份漂移即停止。新持续宿主及新版一次性执行入口
共用用户私有账户指纹全局锁，并保留原host.lock；旧版本的既有进程仍由原账户根host.lock互斥。
所有受支持执行入口须使用唯一已核验账户根，禁止另建目录绕过状态或预算。


- 原生输入获取与状态机共用首次观察时间/品种/来源排序；已有未对账提交优先，全账户最多一个。
  无未决订单时串行查候选的合约/保证金/手续费，再完整刷新账户并重新核对目标，最后取盘口。
  当前候选变化则下一轮重排；临时闭市、零对手量、非tick价格或单品种输入无法证明不消耗目标，
  继续后续合格品种。资金拒绝、最小开仓量不合格及收盘截止按原规则永久放弃该信号。
- 每品种净持仓最多一手、70%上限、无板块和同时持仓数量上限、对手价、180自然秒撤单跟进、
  最终收盘前一分钟放弃新开，均不改。报价来源年龄<=8秒和接收后3秒TTL不放宽；发送前重验。
- 提案与预留先在账户事务中提交，之后发送journal领取唯一身份。未知结果不重发；撤单未知不释放预留，
  不造替代单。正常成交完整对账后保留反手目标；断线/重启的恢复才不补历史开仓。
  冷启动需要撤单但盘口/费率缺失时，从不可变原Tick恢复原Instrument，重核当前物理binding/Session，
  仅构造quote=None撤单事实；旧费率不用于提交，新单仍须全套新鲜输入。
- trade复用Keychain、权威Session、跨日结算、完整原生接管、退避及每日3次连接预算；日切不重置账本。
  旧合约平仓使用旧合约事实。切manage后停止新开并取消本程序未完成开仓，已有仓位按义务管理。
  本地可证明的单品种缺失/异常不拖停其他品种；原生gateway的未分类错误、身份错误及结果未知仍保守
  阻断全账户，不把未知柜台错误擅自降级为品种问题或清除耐久block。
- `continuous.json`升至v2；监控索引仍v1并增加可选mode/opening_enabled/host_status，兼容旧索引。
  等待/阻断时保留最后有效native-source/hash成对绑定，财务只读到该来源，未发布来源不冒充当前核验。
  当前运行/连接与最后核验快照分别展示；仅成功trade轮、账户新鲜且无未对账订单时声明开仓资格。
  STOPPED/等待/数据延迟/待核时开仓资格为false；费用及跨日收益缺证据继续待核。

### 收盘后部署与失败恢复

1. 独立SimNow服务采用 `simnow_night_only_deployment_window_v1`：按当日权威Calendar/Session的
   `is_night` 与 `has_night_session` 确定夜盘品种集合，确认该集合全部夜盘结束、当前无交易Session且
   下一Session至少还有660秒。无夜盘品种不参与本次切换窗口判断，但仍保留各自账户恢复和新输入开仓门禁。
   不允许在夜盘交易期间切换；未知日历、Session或交易日身份仍阻断。本规则仅适用于独立SimNow服务，
   不改变正式十服务的cohort部署窗口。记录现役代码、启动参数和同账户锁/账本身份；
   保留现有观察plist与私有配置前像。若尚有未清订单/未知回报，保留事实并先核对，不能跳过恢复。
   owner交办午间切换时，显式选 `--window midday` 的 `simnow_midday_deployment_window_v1`：由同一权威
   Calendar/Session证明operational全60品种上午非夜盘Session已结束、当前均BREAK/CLOSED且无交易Session，
   下一场必须是当日权威下午Session、距今至少660秒。不得仅凭11:30本地时钟执行，不将BREAK伪作CLOSED，
   不假定13:00重开；下午已开盘、未知或余量不足时拒绝。两种窗口互斥选择并绑定精确计划，不自动fallback。
2. 通过正常发布流程准备固定代码候选；schema2候选配置绑定其代码目录和原账户anchor，账号指纹不变，
   配置0600，不读取或复制Keychain秘密。首次准备可用enabled=false。API监控仍指向原state_root。
3. 用该候选的同ABI SDK解释器执行以下无Broker命令；`--check`验证配置/SDK，不读Keychain；
   preflight只读四库/scope及现有锁，不创建锁，缺锁或持锁时writer_idle=false，不能据此启动：

   ```sh
   /path/to/sdk/python -I /path/to/code/scripts/broker/simnow_supervisor.py --config /path/to/private-trade.json --trade --check
   /path/to/sdk/python -I /path/to/code/scripts/ops/macos/simnow-service.py --config /path/to/private-trade.json --render-trade
   /path/to/sdk/python -I /path/to/code/scripts/ops/macos/simnow-service.py --config /path/to/private-trade.json --preflight-trade
   ```

   render仅输出带 `--trade` 的同label候选plist；preflight的candidate_valid仅代表静态可部署，
   execution_permitted永为false，不证明已连接或输入合格。没有trade安装/自动切换入口。
4. 切换任务中才停止原观察进程并确认原host.lock释放、原账本未改变。首次升级若缺全局锁，
   在该任务中离线调用共用account_lock取得再释放账户锁，仅初始化并核验锁文件，不连接Broker、不写journal；
   然后重新preflight确认writer_idle=true并核对配置，再安装固定候选并启动；
   仍使用同一label，不并起两份writer。按当前账户、当天结算、自然新输入逐品种准入，15个无夜盘品种
   沿用阻断，待下一交易时段合格。启动成功不等于自然策略订单验收。
5. 失败时停用trade入口并确认退出/锁释放，保留所有journal、claim、队列、原生与失败证据；
   恢复前像observe入口或新代码manage（另行显式启用），不删除block、不重置attempts、不补开旧信号。
   若账本已写入ContinuousTradeTickV1（即使尚无订单），恢复工具必须能重放新命令；旧代码若不支持新事件，不能直接重开旧账本。
   观察入口的启动参数可恢复，代码必须选择兼容该账本的已验证版本。

上述持续trade首次代码交付仅开发集成及隔离假柜台闭环，未连接柜台、读取凭据、修改正式配置或安装/切换Runtime。
真实持续开平/撤单、跨日、断线重启、换月和费用闭环仍逐项待验，不能由fixture成功推导。

### 一次性切换工具

`scripts/ops/macos/simnow-trade-switch.py` 默认只读生成60秒有效的 `simnow_trade_switch_plan_v4` 精确计划；显式 `--tag vX.Y.Z`、
`--config`、`--candidate-plist` 与私有 `--state-dir` 绑定同一候选，`--plan` 指定独占计划文件。
候选必须是干净的 `release-<tag>` 目录、annotated tag/peeled commit/HEAD一致，SDK无Broker检查通过；
当前observe的代码/SDK、配置、监控绑定、PID和双锁同样冻结。窗口按上节已选night/midday合同证明；
plan顶层window_policy与snapshot及执行backend必须一致，旧v1/v2/v3计划和跨窗口执行均拒绝，旧失败意图只留历史读回。
本工具仅限20261030、既有60品种独立空账户接管；任何原生或账本持仓、订单、成交、未解释预留均阻断。
不创建账户、不清空四库、不重置连接预算或block、不连接柜台取证。新计划及首次SIGTERM前必须证明
当日尚有至少一次普通连接额度，或已验证下述本次午间单次连接例外，且无当日block；
预算或队列身份在计划后变化也拒绝停服。账户证明只读复用既有原生来源、
归属检查及Recover，切换计划要求来源仍在30秒有效期内；旧证明不能当部署时的新鲜账户事实。

`--apply --plan <exact file>` 在取证后及首次停止前复查TTL与前像，独占持久意图只消费一次；
协作停止observe，证明STOPPED/PID退出、双锁释放及账本/预算/原生历史前缀未改，锁内安装同label，
释放锁后启动trade并两轮核对进程/模式/代码、双锁和监控绑定。`--readback` 只读取持久阶段。
每个原生历史rowid/source/payload及SQLite schema摘要均受保护，不允许改写或删除。
停止边界仅允许native证据追加：旧PID已退出、STOPPED及同进程持有的两把真实FD锁证明后，逐条检查
原计划前缀之后的每份真实持久Snapshot，包含连续rowid、source native_hash、账户/交易日、采集时序、
CNY和全部10维资金原始校验及逐维Decimal不变、空仓/无订单成交/预留、归属与Readback/Recover无effects。
最新记录还须绑定当前STOPPED monitor的原run/account/ledger/source，发布时间与停止时点不早于采样，
且真实最新source年龄<30秒。旧冻结proof只作历史锚，不能伪造新鲜proof或重建虚假的双轮原始报告。
账户、dispatch、signals/预算/block、SDK/配置/锁身份仍严格不变；任一中间追加坏行同样拒绝。
offline结果区分protected_state_unchanged、native_prefix_unchanged与native_appended_count，
不能把合法追加表述为四库整体字节未变；不能证明时仍保守停止，按既有受限路径恢复observe。

`--recover-observe` 只适用于STOPPED/INSTALLING/INSTALLED且从未进入START_REQUESTED的失败阶段；
恢复前重核旧release整树、runner/SDK、空账户、双锁与四库/预算及前像，只恢复原observe启动项和绑定。
START_REQUESTED及之后、未知提交或未知启动结果禁止自动恢复或重复apply，先只读调查。
恢复时允许冻结的旧只读证明已过期，仅用其校验历史绑定，不宣称新鲜账户恢复。工具不操作正式十服务。
切换成功只证明宿主部署；闭市WAITING_SESSION/opening=false合法，原生接管及自然交易仍分别待验。

### 20261030午间部署单次连接例外

Owner明确选择“仅为本次午间部署额外允许1次连接”。普通每交易日最多3次的规则及原attempts/block
不变，不将总上限永久提高为4。例外只适用于20261030午间部署的固定trade候选、原账户及唯一切换意图，
不适用于observe/manage、其他配置/版本/交易日或第二次切换；已有block不能豁免。

正式十服务仍运行原版本；API私有monitor源配置仅为原账户及state_root的只读身份锚，切换时保留。
实际trade/observe、run与opening状态只从同账户monitor.json/continuous.json读取，不从该只读入口推断。
不能把含例外字段的trade运行配置覆盖给旧版API读取器，也不为此升级正式API。

schema2 trade配置可增加精确可选字段 `deployment_connection_permit`，路径指向本次0700独占state-dir内
`deployment-connection-permit.private.json`，准备阶段该文件必须不存在。plan v4冻结账户/交易日/配置SHA/
exact release/SDK/意图路径及权威下午Session；安装后先持久生成grant，再进入START_REQUESTED。
首次startup独占绑定run；后续VERIFYING/COMPLETE阶段保留该run的首次连接资格，其他run拒绝。
有效连接窗口为权威下午Session开始前120秒至开始后120秒，过期不续期、不消耗其他交易日预算。

额外连接在SDK连接调用前持久消费，登录/查询失败、未知结果、断线或进程重启均不返还、不复用；
不会给予有界observe恢复第二次额外连接。午间部署不强制提前连接柜台，宿主仍按权威Session等待
首个下午连接准入；授权只覆盖该首次连接窗口，不能通过延长有效期变成持续重连额度。
plan仍须现场证明空账户接管、新鲜原生证据、双锁、配置/SDK/四库前像及午间窗口，单次例外
本身不是账户恢复、执行输入或订单许可。切换前失败可保留observe，START_REQUESTED之后未知
仍仅只读核对，禁止重复apply或自动恢复。

### 执行输入诊断与成功证据

`simnow_execution_input_check_v1` 在连续状态文件逐品种保存最近一次检查。成功记录包含固定物理合约、
交易所、合约/保证金/手续费/盘口/Session的来源摘要与各自采样时点、checked_at和最早valid_until。
它只证明输入事实已构建，明确 `FACTS_ONLY_NOT_ORDER_PERMISSION`，保留Session可交易性及买卖量，
不代替账户、信号、资金、价格、风险和发送前门禁。未检查或旧版本没有成功证据时为NOT_CHECKED，
不能由issues缺席推导成功；后续失败覆盖此前成功记录。状态文件不持久化可被误用的当前fresh布尔值。

`scripts/broker/simnow_input_readback.py --status <private continuous.json>` 无Broker/数据库/凭据访问，
读取时按当前时间、宿主连接/时点和有效期重算fresh；过期、宿主未来时间或断线均不能显示新鲜成功。
输出永为 `execution_permitted=false`，只读诊断不放开订单。

原 `simnow_native_input_v2` 的8秒来源年龄和接收后3秒Quote TTL不变；时间在未来也仍拒绝。
失败诊断区分SOURCE_OLD_BEFORE_QUERY、QUERY_CROSSED_SOURCE_AGE_LIMIT、SOURCE_TIME_IN_FUTURE，
不凭分类推断柜台根因或改写ActionDay。Gateway保留含1.1秒节流的调用起点、SDK发送、匹配目标行回调、
终止回调、返回时点与总耗时；原elapsed_seconds不含该节流，其语义不改。诊断仅白名单时间/数量/摘要，
无原始账户行、地址、凭据或异常原文。旧版只有NATIVE_BOOK_STALE时，无法追溯区分旧价、延迟和未来时间。

## 一次性宿主与只读预检

`scripts/broker/simnow_controlled.py` 复用既有只读Probe认证/登录及四查询两轮协议；可选SDK仅在隔离Mac环境加载，API依赖以相同Python ABI的既有venv只读加载，不向API安装CTP。
`simnow_native_gateway.py` 额外读取结算状态、原生合约、保证金、手续费预算及执行盘口，敏感账户字段只在内存中完成关联。
账户所有资料写入 `output/simnow-controlled/<account_fingerprint>/` 的0600 SQLite；目录0700，运行持有独占账户文件锁。

```sh
# 默认仅预检：实际登录与原生读取，无报撤单、无结算确认
/path/to/isolated/python -I scripts/broker/simnow_controlled.py --product rb
# 首次10万元空账户已实际核验后，明确启用本次有界验证
/path/to/isolated/python -I scripts/broker/simnow_controlled.py --product rb --execute --initialize --max-seconds 600 --max-submits 1
# 后续接管已有账户，不能再次initialize或覆写旧journal
/path/to/isolated/python -I scripts/broker/simnow_controlled.py --product rb --execute --max-seconds 600 --max-submits 1
```

`--api-env`可显式选择同ABI既有API依赖venv，默认项目自身venv。只接受本机TTY投资者代码和隐藏密码；不读聊天、参数、管道或文件中的密码。
execute包括必要的本次结算确认，必须先完成实际资金、账户和执行输入预检；默认preflight绝不确认。
本次只控制一个operational品种，每单一手；10..3600秒、1..3次submit，默认600秒/1次。该限制是验证范围，不改变正式70%账户规则或未来全品种目标。

- `MarketBridge`通过统一MarketDataService、Catalog、主力映射及Calendar/Session绑定物理合约，午休不作最终收盘；旧仓仍使用旧合约事实。
- owner于2026-10-25明确允许SimNow原生盘口仅作为执行报价。盘口ActionDay/更新时间、毫秒、交易日、合约、买卖盘及涨跌停逐项核验；旧盘口、异常/缺失值不报单。报价不写Canonical、不进入公式或历史研究。
- 自然信号只从本次订阅后的最新completed 60m原件进入；startup队列清空，旧Bar、非最新原件、历史补取、重绘及恢复输入不能取得首次交易资格。
- 恢复通过统一reader验证32根预热加离线完整区间，必要时将只读前缀有界扩至2000根；每个离线端点仅按其当时32根前缀复算方向，不创建历史开仓信号。仍无法证明完整则品种阻断，已有平仓义务保留。
- 正常FILLED回报只令readback失效、等待逐笔与资金核对，保留最新反手目标；故障/重启才走不补开恢复。已知迟到成交即使缺费用，也立即重新锁定原预留，完整Fill待实际费用证明后写入。
- 从未领取发送claim的本地PROPOSED可在账户writer锁内核对否定证明，写为 `LOCAL_ABORTED` 并释放本地预留；这是本地未发送事实，不伪装柜台拒单。已领取/结果未知禁止此路径。重开仍可记录该事实，但不能绕过恢复。
- submit预算包括未知/非零结果；到期不新增提交。仅取消本程序未成交开仓，不强制平已有仓；未核清委托、预留、持仓和平仓义务全部保留。
- SDK退出时先注销/释放原生回调，再drain尾部事实，最后关闭journal。未知、阻断、缺费用或未核清订单返回 `CONTROLLED_RUN_REQUIRES_RECOVERY` 和非0退出码；结果列出订单、预留、成交和持仓完整性，不能据空列表推断空账户。

账户收益使用原生Balance及实际Deposit/Withdraw调整，手续费来自原生事实而非参考交易；当前可证明同日区间净收益。
跨日没有完整现金流/结算连续性时，继续展示原生权益、持仓损益及费用，累计区间收益保持 `CASHFLOW_CONTINUITY_REQUIRED`，不能猜零现金流。
所有fixture输出 `broker_e2e_passed=false`；实际第一套、资金生效及原生订单仍须分别验收。一次性受控程序不安装launchd或启用全品种持续自动交易。

## 首页只读监控（simnow_monitor_v1）

首页“市场 / 消息 / 模拟交易”第三项只展示已留存的原生账户走势、持仓、执行链及待核事实，
不提供报撤单、连接、结算确认或恢复按钮。页面可见时每5秒读取；隐藏、离开和卸载后暂停。
默认近7天按北京时间记录时间筛选；原生交易日仅在原始来源存在时另列，不从自然日期推算。
翻页/抽屉期间新快照仅提示，不替换当前列表或选择；失败保留最后快照和核验时间。

现有一次性受控宿主继续使用 PROJECT_ROOT/output/simnow-controlled 作为唯一监控根。
GUIYI_SIMNOW_MONITOR_ROOT 仅为API显式选源配置；默认是API自身工作区的上述根，跨工作区开发
必须指向宿主实际的同一根。它不改变宿主既有输出位置，不通过目录扫描、mtime或PID寻找当前账户。
根下 monitor.json 由宿主在既有控制流中以私有权限、独占短锁及原子替换发布，绑定账户指纹、run、
运行开始/查询中/最后更新时间/结束、来源ID及账本摘要。索引仅是观察状态，非财务权威；
账户冲突或发布失败只让监控不可用，不改变交易决定，不新增线程、查询或定时采集。

只读API为：

- GET /api/simnow/monitor/overview
- GET /api/simnow/monitor/records：kind、product、status、start_day、end_day、cursor；每页50条，
  窗口相隔最多93天，最多读取5000条记录，覆盖受限明确返回partial。
- GET /api/simnow/monitor/records/{id}：精确稳定身份关联信号、风控、订单、实际成交。

reader分别以SQLite mode=ro、query_only和读取事务访问 account.sqlite、dispatch.sqlite、
native-evidence.sqlite；不构造执行LocalStore、不触发恢复、不调用Broker或创建缺失文件。
现有库为rollback journal；reader在连接前检查文件头，拒绝WAL，避免SQLite只读连接创建共享内存文件。
缺失、损坏、账户/schema/hash不匹配或未来来源均不回退到零资金/空仓。多库不是跨库原子快照，
原生核验和账本时点分别公开；原生来源与账本未匹配、待核成交/异常持仓时保留原始事实，预算完整性待核。
缺失监控索引为未接入；记录读取失败不等于账户无持仓。

财务投影复用 finance.performance 与账户 local_occupancy，金额/比率输出普通Decimal字符串。
原生权益、当日Commission与本地成交归属费用分别显示，不在前端推算预算。
跨日现金流无法证明时net_profit/return_ratio为空，曲线断开；原始权益仍保留。
未经核对的成交只进待核事项，不捏造成已入账Fill。原始Live缺口、策略参考收益与账户事实始终独立。
索引状态过期或运行结束后不宣称当前连接正常；历史登录成功不构成当前连接证据。

observe 宿主在原生双轮快照经账户纯函数校验并成功留存后，才在同一原子 monitor.json 中附带
`simnow_observe_reconciliation_v1` 证明。证明绑定账户、run、品种、原生 source、当前账本摘要及
校验时间，最长有效至原生快照后30秒；新来源、账本变化、断线、停机、换run或模式均不得复用。
`observe_reconciliation_ready` 仅表示当前账户只读核验通过，不改变原账本、持仓投影、执行输入或交易许可。
缺失证明仍兼容旧索引但保持未核验；损坏或关联不符使监控不可用。前端在证明到期、读取失败或暂停观察后
撤销就绪提示，不能以最后一次成功快照维持当前就绪。

observe 的可选合约、保证金、手续费和盘口查询，仅对 SDK 明确未接受且没有任何回调的 -2/-3
返回保留该品种待核，不影响后续账户查询；不重试、不新增连接。其他 ErrorID、超时、断线、身份异常、
迟到或矛盾回调仍按原合同阻断，同轮失败不得发布账户就绪。

API不公开完整账号、凭据、文件路径或原始异常；账户身份仅返回不可逆展示key与别名，
关联来源摘要在抽屉折叠展示。此实现不安装服务、不启用持续交易、auto_order不改变。
没有实际受控账户记录时以可核验空态交付，真实账户自然数据另验。

### 原生事实查询诊断

一次性宿主结果附带 `native_query_diagnostics`，逐项记录合约/结算状态/保证金/手续费/盘口查询的
固定类型、请求ID、SDK受理码、回调和有效行数、结束回报、完整性、超时、耗时及白名单错误分类。
不包含原始行、账号、前置、密码或异常文本，不改变原有15秒等待、请求参数及失败停止边界。
SDK返回0只证明受理，仍需完整回报；有行但缺结束、回调身份错误、柜台拒绝或超时均不得升级为通过。
失败结果保持，无自动重试；一次性只读预检通过也不等于全品种、持续Runtime或报单成交验收。

宿主合约资料查询必须按权威交易所与CTP产品代码限定，禁止无筛选全市场查询。
产品代码仅定义查询范围：CZCE/CFFEX大写，其余支持的SHFE/DCE/INE/GFEX小写；未知交易所或非法产品拒绝。
回报交易所或产品偏离范围即失败，仍须完整结束回报；随后bind_contract按完整交割年月和生命周期绑定物理合约，
不能把产品筛选或本地拼出的月份当作成交合约权威。同品种旧月仍在此范围，跨品种仓位继续阻断。

盘口查询返回完整批次后，仅按已绑定的原生InstrumentID+ExchangeID精确选择唯一记录；缺失及任何重复均拒绝，
不能选择首行、其他月份或交易所代替。预检和有界运行循环共用选择与原有交易日/8秒来源新鲜度/数值校验。
本地结果记录匹配数量与可解析的来源年龄，避免将批次多行直接误报没有行情；不保存整批原始回报。
只读预检成功时记录合约、费率/费用预算及买卖盘的Decimal字符串与检查时间、有效期，口径为
OBSERVED_INPUT_NOT_CURRENT_ORDER_PERMISSION；后续账户查询可能使该盘口过期，预检结果不能授权使用旧报价下单。

费率身份使用 `native_rate_query_scope_v1`：margin/commission请求显式携带已绑定的交易所与原生合约，
SDK不支持ExchangeID字段则拒绝；账号和Broker回报先由Gateway核验。只有完整终态之后才给返回副本附加
schema、查询种类、请求合约、交易所和请求ID，原生行及其空ExchangeID保持不变。
若回报ExchangeID为空，执行输入仅在上述请求上下文完整且与物理绑定逐项一致时采用请求范围确定交易所；
原生合约或Broker不符、非空交易所冲突、上下文缺失/矛盾均拒绝，不推测或改写回报。来源hash包含原生值与上下文。
只读结果分别展示原始ExchangeID及QUERY_SCOPE/RESPONSE_FIELD绑定口径；保证金和费用数值不因绑定方式改变。

## 2026-10-26 盘口来源年龄口径

owner明确将接收时来源年龄上限改为8秒（含8），未来时间及超过8秒拒绝；只改变此输入准入参数。
`simnow_native_input_v2` 把版本与8秒上限纳入报价source hash，`simnow_ctp_controlled_v2`进入action hash，
避免旧执行意图身份复用。接收后原有3秒Quote有效期保持，发送仍需重新检查有效期及其余账户/Session条件。
执行报告显式记录输入版本及max_source_age_seconds，不改写旧5秒失败记录，不改变RQData策略行情或Canonical。

## 有界宿主等待旧盘口（simnow_bounded_host_v2）

初始预检仍须合格的新鲜盘口。运行循环中仅当账户READY且readback_valid、没有任何订单/持仓/预留/
未核成交/待核回报/adapter fault/清仓或换月义务，且错误确为来源年龄>8秒时，允许跳过本次Tick及发送，
继续原有有界对账和读取，等待计数写入结果。不得使用旧价或延长deadline；请求失败、未来时间、身份错误不走此路径。
费率身份在读取盘口前独立验证，与执行输入复用同一校验。已有任何账户义务保持原停止/撤单/恢复合同。
已有SQLite后只能按恢复模式接管，不能重新initialize、删文件重建或重新发送未知动作；新activate前队列仍清空，
恢复旧信号不能取得开仓资格。等待自然新信号且无报单的结果不构成成交或端到端交易通过。

宿主最终结果附带 `inventory_diagnostics`，覆盖认证/登录及资金、持仓、委托、成交两轮协议的
固定状态、阶段、数字返回码、回调/完整性/超时计数，不包含账户行、完整账号、前置、凭据或异常文本。
它只解释原有失败，不升级不完整快照、不改变等待或重发请求；无法获得稳定快照时继续禁止接管和发送。

## 人工验收往返（simnow_manual_roundtrip_v1）

本入口只执行owner明确交办的RB权威主力开多一手，首次完整原生读回确认真实开仓成交后等待600自然秒，
再发起平仓。它不是HTDY信号，不构成策略信号端到端或全品种自动交易验收，auto_order=false保持。
`ManualBeginV1`/`ManualTickV1`及审计派生计时使用独立policy；订单来源为manual:UUID，State.signals保持原件。
不改变旧State/Order序列化、检查点hash或既有账户/订单/失败事实；不重新初始化账本。

运行前停独立observe宿主，取得同一账户host.lock。账户须完整平仓/无未决订单、资金预留及费用待核；
从统一MarketDataService解析当前物理主力及Session，开仓时当前连续可交易段剩余至少900秒。
午休或短休不能使用日间最终收盘时间冒充连续可交易时间。原生合约、保证金、手续费、盘口8秒来源年龄、
3秒接收有效期、70%资金上限、平今/平昨与幂等检查保持。

新人工任务单独持久保存一次连接预算，旧observe连接次数及block不清零。首次manual Begin及唯一OPEN提案
共同限制开仓，已发送/未知/撤单均不重新开仓；无法证明发送结果时只核对。开仓等待180秒取消，不重开。
开仓成交但费用或账户尚未完整核验不开始持有计时；确认起点由不可变Readback/Recover与NativeFill身份派生，
重启不会重置。到期仅平对应真实持仓，不反手；平仓与必要撤单不受开仓期限或次数上限影响。
只有首次人工连接在开仓前失败、account/dispatch/signals三份前像完全未变且尚无ManualBegin/订单/成交时，
可按`simnow_manual_preflight_recovery_v1`显式恢复：同一test_id先独立只读诊断一次，再最多一次恢复执行连接，
本人工任务累计最多三次，不清除原登录预算或失败原件。恢复计划绑定失败状态、诊断事实/回执/预算、账户指纹、
三份数据库SHA及短期有效期，恢复claim独立O_EXCL；诊断不会自动继续交易，现场仍须全新完整预检。
恢复状态写入独立recovery-status，不能覆盖首次失败记录。此入口不接管已有ManualBegin，不构成未知订单重发。

本次人工宿主显式使用`initial_funds_timeout=45`：每次连接仅首次快照的第一笔资金查询拥有一次45秒宽限，
在发请求前消耗；其余七次及后续快照维持15秒。Probe/Gateway/NativePortfolio默认仍15秒，不改变观察宿主。
原生响应完整性、Session、3秒Quote及8秒来源年龄不变；诊断观察到首笔资金响应22.925秒，不据此推断旧超时根因。
缺少合格报价则等待后续新报价，不能用过期价发送；原始策略输入阻断继续保留，人工意图不取得策略首次观察资格。

最终验收要求真实开/平成交、唯一实际手续费、完整原生空仓及无活动委托、资金预留释放和账本一致。
CTP金额double的原值继续以Decimal字符串保留；仅最终权益差额对账及Available−Balance采用绝对残差<=1e-8元，
显式输出有符号残差与界限，不改写原生金额、费用或Ledger。CloseProfit差额仍须精确相等；此边界不用于风险、
价格、保证金、数量、身份或时间校验，真实分币差额继续拒绝。
Release成功后drain尾事实并重查结果，未知提交/费用/清理失败均不报告通过。执行失败保留已有实际仓位与关闭义务。
这次受控入口不注册自动任务、不改变观察服务的observe-only模式，也不发布或切换正式十服务Runtime。

### 已认领人工成交的关闭恢复

`simnow_manual_close_only_v1` 仅管理同一已认领RB一手OPEN，不重开、不反手。它用独立一次管理连接预算
（本任务累计4，前三次原件不改），绑定原三份数据库SHA、ManualBegin、原订单/成交/系统号、开仓前原生baseline；
在Host与Adapter两层拒绝OPEN。当前完整四类原生读回先证明该订单成交及RB实际多一手，随后才恢复账本和关闭义务。
恢复初期不要求新盘口或估计费率；实际CLOSE仍重新验证完整账户、原生费率、实时对手价与Session。

新增仅供人工订单的`CorrelatedNativeFillV1`／`simnow_manual_correlated_fill_v1`。CTP原生Insert/TradeTime与本地
request_started_at属于未校准的两个时钟域，保留全部原始值，不加秒或回写时间。新类型须由完整快照内容hash、
同账户/交易日、已持久OrderRef/FrontID/SessionID、物理合约/方向/一手、同一非空OrderSysID/TradeID及实际费用证明；
原生时间另经权威Calendar/Session校验。本地观察/完整证明时间不早于本地请求，建立身份因果；旧NativeFill严格时序与旧重放不变。
未被完整快照解释的成交保持待核并阻断发送/成功，未知身份立即阻断；已知中间订单状态可由同身份终态快照覆盖。
只在首次完整读回确认关联成交后开始600秒计时，已有confirmed_at/due_at不重置；前次回调不是完整核验，不伪造已等待事实。
只读状态/原恢复失败原件继续保留，关闭恢复状态使用独立close-only-status。退出前仍须真实平仓、费用/权益/预留及尾回调对账。

## 普通策略原生关联协议（simnow_strategy_correlated_fill_v1）

普通有界宿主和持续宿主的manage对账路径使用独立`StrategyCorrelatedNativeFillV1`，
接入codec、账户校验和恢复重放。旧`NativeFill`及人工专用`CorrelatedNativeFillV1`语义和历史hash保持。
新增协议不开放持续新开仓；observe不构造订单Adapter，manage和Host的OPEN禁令不变。

- 原生InsertTime/TradeTime原样保留，不与本地请求/接收时钟比较；本地请求不得早于本地订单创建，
  本地记录不得早于请求。原生事件通过既有MarketBridge/PortfolioMarket核验其产品、交易日、
  实际物理合约和Session。夜盘可归属后续交易日，旧合约平仓不要求其仍为当前主力。
- 完整两轮快照、持久发送身份、OrderRef/FrontID/SessionID、交易所SystemID/TradeID和
  方向/开平/数量/价格须唯一相符；原生实际手续费差额可唯一归属后，才接入定价成交。
  新策略OPEN须关联已有冻结Signal，人工订单不能借新类型取消原人工范围限制。
- 已知但尚未完整证明的回调持久待核并阻断发送。普通策略已知成交回调可保守标记订单待成交核验，
  重锁已释放预留；这不构成定价Fill，不代表持仓完整。未知身份或冲突保留fault并阻断。
  无成交终态不能擦除未证明trade；完整核对后仍按原幂等身份消费，不重发已claim动作。
- 普通宿主新连接的第一轮首笔资金查询最多45秒，仅消费一次；其余查询和后续快照仍15秒，
  首笔失败也不恢复额外等待预算。低层Gateway原默认15秒及显式旧配置保留；连接次数预算不变。

代码集成、发布/运行切换、自然信号及实际策略订单闭环分别验收。开盘期间仅隔离开发和只读审计，
不发布或切换；本次不创建原生报单/撤单、不确认结算、不修改真实账户journal。


### 20261030统一发布的待恢复trade接管

Owner明确交办统一十一服务及发布树，并选择待恢复trade部署：该显式路径在切换前只重放原账本、
冻结四库、完整native历史前缀及配置/SDK/双锁/预算block，不把旧快照解释为当前账户事实。
原普通切换的新鲜账户门禁保持，仅此显式路径将新鲜柜台接管核验推迟到新trade宿主同一连接内完成。
午间必须公开mode=trade/account_takeover_pending=true/opening_enabled=false；旧快照不能解除待核状态。

原attempts和block历史原样保留。只允许本次固定版本/配置/账户/唯一意图/首run的额外一次连接，
且仅覆盖20261030精确冻结的CONNECTION_BUDGET_EXHAUSTED block；其他原因、变化或未知义务均拒绝。
许可过期不延期，失败、断线、未知或重启不返还；下午连接窗口仍由权威Session决定，不提前探测登录。
直到该连接完成资金/持仓/委托/成交/归属、当天结算及原账本完整Recover前，submit/cancel/open全部禁止。
新鲜完整接管通过后才解除pending，逐品种输入门禁仍独立，旧上午信号不补开；次交易日普通预算规则不改。

正式十服务和SimNow使用同一新fixed release；API监控身份锚也迁向该代码根，state_project_root及四库原位。
使用原cohort工具和独立SimNow切换工具分别执行与读回，任何一部分失败都不得为凑单树强删旧运行根。
全部服务根统一、身份/健康读回后才能逐旧树完成证据封存、零引用复核和non-force清理；自然账户恢复、
策略执行输入、真实成交及跨日换月验收分别记录，不把trade部署当已通过。

待恢复路径须在Supervisor/Host/Adapter分别阻止订单类写入；不能把Recover的READY或now+30派生TTL
当作原生快照新鲜。核验必须绑定本次连接source、真实snapshot.at及其30秒期限，在可能耗时的查询/
adapter/恢复步骤后重新读时。新鲜性不足保留pending，不落成“已接管”，也不借重启/重试取得第二次许可。

本次额外连接另有账户/交易日固定的O_EXCL持久标记，与本grant/plan/intent严格绑定；部分写入或fsync失败
不返还，换config或state-dir也不能重新签发。只读plan及SIGTERM前必须拒绝已占用标记，最终issue仍以
O_EXCL处理并发。此标记只是本次一次性授权事实，不修改用户级配置或扩展为通用额度服务。
原生窗口查询、grant持久化及SDK校验后的最终bootstrap前均重新读时；过窗/未知不启动、不refund或重试。

### 原账户 profile、闲时输入验收与普通预算升级

原账户自动交易使用显式 `original_anchor_v1` profile，schema2 私有配置中的
`account_profile` 精确绑定既有 account_id 和原始 initial_readback 的完整规范摘要。
该配置不改变资金、账本或历史。缺省仍是 `legacy_100k_v1`，保持原10万元基线限制；
错误账户、摘要或宿主与Adapter profile不一致均在dispatch claim/SDK发送前拒绝。
已AbortUnsent/LOCAL_ABORTED的旧信号不恢复发送。dispatch诊断只保留固定阶段、固定错误分类和单调耗时，
不输出异常正文、SQL或秘密。完整账本inspect在私有一致性副本上重放；原文件只参与有界只读快照，
现场轻量监控不以全历史重放挤占执行。

全品种输入验收复用trade宿主的原SDK连接，每次只执行一个串行查询阶段，沿用限速；
回调、订单、账户对账及新自然信号优先。未决义务、恢复未完成、未知Session边界或距下一60m/Session
边界不足20秒时暂停并丢弃部分采样。每品种保存来源、采样、有效期和失败原因，
`purpose=audit` 不产生执行事实或统一全品种开仓Gate。来源8秒、Quote TTL3秒保持，
读回重算新鲜度；NOT_CHECKED、失败、断线和成功后过期均不能作为当前合格。
报单重新核验，audit成功不代表允许报单。AG/J/PB/ZN历史缺完整时序的失败仍须新样本区分根因。

trade→trade使用新计划和普通预算待恢复接管。冻结原账户profile、四库历史前缀、原生锚、配置、SDK、
原PID/双锁及预算/block；未知发送、待核成交及未解释预留继续拒绝。
普通许可与历史额外连接许可互斥，不迁移或返还旧许可、不清任何历史计数/block。
目标交易日与可连接窗口由统一权威Session入口确定；唯一意图及首次run先持久绑定，
每次连接仍使用原普通attempt计数。固定事实漂移、目标日block、预算不足、过期、重启复用和未知状态拒绝。
新宿主公开pending=true/opening=false；同一连接的新鲜结算、资金/持仓/委托/成交及原账本Recover
完成前禁止订单类动作，随后只接收自然新信号。下一权威交易日恢复原普通预算，不借其他日期额度。
START_REQUESTED以后结果不明只读核对，不能重复启动；停止阶段恢复使用独立明确意图，
不能自动重启已消费额外许可的旧run。代码/离线验证、固定候选、发布、切换和自然验收分别记录。

停止阶段恢复使用独立0700目录、新私有配置中的ordinary permit路径，先以
`--plan-stopped-recovery --source-intent <旧intent> --plan <新plan>`生成60秒计划，再以`--recover-pending-trade --plan <新plan>`执行。
恢复需非阻塞取得原意图目录现有`switch.lock`并持至完成，在源锁内重新读取原phase/hash；
原协调器仍活、锁被替换或原phase已到START_REQUESTED时零claim/安装/启动。
原源claim与新恢复意图分别独占，不允许恢复链式重试。

### 收盘部署窗口与执行合约分离（普通接管v2）

`simnow_ordinary_next_session_v2`部署窗口只冻结权威Calendar/Session及全60品种范围：当前均无Session、
下一场严格超过660秒，目标交易日按实际下一Session确定。未来交易日主力映射缺失不作为休市判定输入。
最新已完成交易日的全60物理映射通过独立历史锚进入部署前像，切换和停止阶段恢复须重新比对；
该历史锚不赋予未来交易日合约身份或订单权限。运行时许可的静态Session hash不受历史主力更新影响。
交易入口仍只接受目标交易日权威主力、物理合约及新鲜执行输入，缺失保持fail-closed，不以旧主力代替。
普通许可使用v2、切换计划使用v6，旧v5及旧普通许可不得混用或重新apply；历史状态仅读回。

### 普通许可静态事实边界（v3 / 切换计划v7）

普通许可仅冻结window的policy、trading_day、session_start、connect_after、connect_until、sessions和
session_facts_sha256；gap/checked_at等动态读回不进入不可变许可身份。每次fresh仍重新查询全60权威
Calendar/Session并要求当前无Session、下一场严格超过660秒，不能用冻结值代替当前窗口证明。
旧v6计划仅历史读回，旧v2许可不激活；账本/SDK/配置/预算/双锁/历史锚及未知启动门禁保持。
