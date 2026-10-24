# 火天大有60分钟固定一手执行规则

Owner 已确认本规则。当前交付是离线纯状态机和显式输入适配器，不是 SimNow 接入或策略启用；
`auto_order=false`，账户总风控未配置，没有 transport、CLI、API、后台任务或生产账本写入。
现有公式、Alert first-seen、参考模型和收益保持不变。未来连接账号与持续运行分别验收。

## 身份与输入

- 执行政策：`htdy_60m_fixed1_signal_reverse_v1`；公式 lineage：`huotian_dayou_original_v0`。
- 一个专用账号，品种仅来自既有 operational loader，启动时冻结集合。每品种净仓位为 -1/0/+1 手；
  多品种可同时持有，但本规则不定义账户总保证金、最大持仓数或板块上限。
- 复用 `HtdyOriginalEvaluator` 和权威 `MarketReadService.validate_alert_window`；精确32根完成60m窗口，
  signal 保存来源身份、input hash、物理合约、前一端点、Bar结束和首次观察时间。
  输入端点、Session和rank1仍由现有数据域证明，不新增行情resolver。合法跨owner的指标窗口沿用现有合同。
- 显式 seam 只接受原生最新完成观察；不可用历史重算、恢复回填、通知是否成功或图表marker代替。
  生产调度与观察原件绑定尚未接入，调用者必须保留原观察身份和实际接收时刻。
- 原公式会重绘。已冻结的同品种同Bar不因后续方向、输入修订而再开仓；同一来源ID关联不同端点拒绝。

## 交易规则

首次启用要求账号空仓且无未完成委托，只接受启用后新完成Bar。空仓遇buy开多一手，遇sell开空一手；
同向不加仓，无信号持有，可跨日/夜盘。不设价格止损、止盈、持仓时长退出或每日强制清仓，不继承旧Paper日亏规则。
同时buy/sell记录冲突，不新开或反手，并撤销尚未成交的开仓意图；不因此清算已有仓位。

反向先平旧仓，实际平仓Fill确认后才允许反向开一手；等待平仓期间的新合格信号覆盖旧目标。
未决开仓、取消等待和成交回报缺失都占用容量。订单提案必须严格晚于信号实际可用时间；
成交时间必须严格晚于订单创建时间。休市不制造成交，已正常收到的信号可以等下一可交易时点。
本版没有固定分钟数过期参数。

## 故障、恢复与换月

断线或checkpoint恢复后先进入 `RECOVERY_REQUIRED`，核对同一账号的资金、持仓、订单和成交。
`readback_valid=false` 时连撤单提案也不产生；只有完成原生回读才允许执行动作。
未解释外部仓位/委托进入BLOCKED；未知订单、成交状态但缺少逐笔Fill、拒单均停止账户新动作，
不推断失败、不自动重发。只有已完成原生回报核对和完整输入证明后才恢复。

取消义务独立保存为 `cancel_required`，不会被后续同向信号覆盖。取消/拒绝回报本身不释放容量；
`AccountSnapshot.settled_order_ids` 必须由未来adapter在原生订单、逐笔成交和持仓完整核对后提供，
没有该证明保持待恢复。即使核对后仍出现矛盾的迟到Fill，也保存真实回报并取消其他未决开仓；
不能投影到一手模型的真实Fill单列 `unresolved_fill_ids` 并保持BLOCKED，重启不清除该阻断。
首启已核对的历史终态订单保存为baseline，后续原样读回合法；新的未知外部订单仍阻断。

恢复不补开旧信号：未完成开仓先取消，空仓等恢复后的新Bar信号；已有仓位与最新完整方向相反则只平仓，
随后等待新信号。相同方向的已有仓位接管持有，不因重启自行清仓。挂起旧平仓不变成恢复后的补开。
缺完整输入的品种单列阻断，其他已验证品种可以继续；不能证明离线方向时不猜测或补造。

权威主力owner变化时，取消旧开仓，按旧合约持仓创建平仓意图；晚到的旧开仓Fill也必须如实计入并平旧仓。
未成交时仍持有旧仓，不能用新合约价格结算。平仓后等待后续新信号，不搬仓，不消费切换期间的旧目标。
新合约数据不合格不得新开。

## 接口与后续边界

`guiyi_quant.htdy_execution` 提供 `start/apply/checkpoint/restore`；状态不可变，`Transition.effects`
只有SUBMIT/CANCEL提案，不调用Broker。`Fill`保存原生trade/order/account身份、实际价格、费用、成交和记录时间，
不计算或虚构模型PnL；持仓按逐笔Fill重放验证。命令ID+payload hash、trade ID和冻结Bar去重，冲突失败。
Audit保存命令内容、原因和目标/订单状态；checkpoint绑定政策/公式/hash，恢复永远要求账户readback。
hash用于损坏检测，不声称防御有权改写全部内容的操作者。

`app.htdy_execution` 提供 `start_operational` 和 `signal_from_window`，不挂接现有Alert、API或Runtime。
外部调用方负责证明最新原件、owner切换、恢复输入、账户快照和交易Session；不能把任意布尔值当生产验收。
`Advance.opening_allowed`与funding来源是显式资金准入输入，不是已实现账户风控；不满足则不创建开仓提案。
`CLOSE`为语义平仓意图，未来transport必须按原生持仓区分平今/平昨；本次不冒充该适配已完成。

真实发送之前仍需持久化命令/提案的原子提交、Broker adapter、账户总风控、行情准入、原生对账与独立运行验收。
不得直接把内存effects循环接到下单API；本模块没有可开启自动交易的入口。

## 验证

执行入口见 [TESTING](../TESTING.md#htdy-60分钟离线执行规则)。测试使用隔离fixture，不连接SimNow、生产数据库、
Redis或RQData，不证明策略收益、全品种数据ready、OOS、成交可得性或Runtime已启用。
