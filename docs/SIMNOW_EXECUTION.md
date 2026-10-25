# SimNow受控订单适配 v1

本模块实现已持久化HTDY账户提案到CTP报单/撤单请求的窄适配，以及原生回调到本地账户journal的事实接入。
交易规则、资金预留和订单状态机见[HTDY合同](HTDY_SIMNOW_V1.md)，登录及四类只读查询见[只读合同](SIMNOW_READONLY.md)。
只读CLI保持只读；本模块不登录、不注册前置、不确认结算、不创建行情源或后台循环，不修改 `auto_order=false`。

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
不得将开仓预算或预估费率当实际费用。缺费事实会阻断后续发送。当前没有自动费用归因或原生资金/今昨仓快照投影器；
完整 `Readback`、费用证明及恢复输入须由后续原生对账宿主提供并验收，不能据SDK结构测试宣称这些接线已完成。
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
费用及账户对账投影器、可交易时段的新合格信号，再对精确一手订单做报单/成交或撤单核对。
本次没有真实报撤单，没有持续交易宿主或交易启动CLI，不发布、不切Runtime。通过离线验证不表示可以开启全品种自动交易。
