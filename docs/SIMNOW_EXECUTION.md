# SimNow受控订单适配 v2

本模块实现已持久化HTDY账户提案到CTP报单/撤单请求的窄适配，以及原生回调到本地账户journal的事实接入。
交易规则、资金预留和订单状态机见[HTDY合同](HTDY_SIMNOW_V1.md)，登录及四类只读查询见[只读合同](SIMNOW_READONLY.md)。
只读CLI保持只读；core适配模块不自行登录或注册前置。一次性宿主与独立持续宿主显式连接固定第一套，均默认只读；新开仓入口保持关闭，`auto_order=false`。

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

本阶段只提供 `observe` 与 `manage`：observe不构造交易Adapter、不确认结算、不写账户命令、不创建提案/预留；
只读校验已有账本与原生快照，串行轮转检查各品种输入。manage接管已有义务，允许已知平仓/撤单，
通过持久的 `ManagedTickV1` 在创建OPEN或预留之前禁止新开仓，Host发送前再次拒绝OPEN。
旧Tick/Recover及v2账户hash不变；新管理Tick和按品种恢复命令各有独立版本，旧命令可逐条重放。
首次订单预算、全品种新开仓和正式Runtime启用属于后续范围，不能由配置改成execute或启用observe推导。

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
缺少合格报价则等待后续新报价，不能用过期价发送；原始策略输入阻断继续保留，人工意图不取得策略首次观察资格。

最终验收要求真实开/平成交、唯一实际手续费、完整原生空仓及无活动委托、资金预留释放和账本一致。
Release成功后drain尾事实并重查结果，未知提交/费用/清理失败均不报告通过。执行失败保留已有实际仓位与关闭义务。
这次受控入口不注册自动任务、不改变观察服务的observe-only模式，也不发布或切换正式十服务Runtime。
