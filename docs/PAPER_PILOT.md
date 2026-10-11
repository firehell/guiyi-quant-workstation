# JM 本地 Paper 合同

本域是 owner 交办的前三步工程：因果候选验证、单手目标与风控、本地 Paper 账本。
它不复活已退役的策略/执行模块，不接 Broker，不启用 Shadow 或后台交易。
`auto_order=false`。页面参考、因果研究、Paper 模型成交、外部账户事实独立。

## 身份与输入

首个 profile 固定 JM、5m 双策略、LONG、初始现金 50000 元、净持仓 0/1 手、
日亏损比例 0.02。公式沿用原趋势/震荡动作；新的
`newow_dual_fusion_causal_target_v1` 适配只在同 Bar 原始动作排序完成后输出最终目标。
未来修改策略、成本、风险、执行或仓位语义须建立新版本，不覆盖既有账本。

信号与执行行情都从 MarketDataService 取得 completed Canonical，通过 Catalog 与
MainContractMap 验证物理合约及可观察区段。5m 用于决策；成交仅使用具体 JM 月份合约的 1m。
行情身份、输入窗口、source hash、profile、策略版本及 provider facts 共同绑定回放身份。
历史事实采集时间如实记录；有效日期与 captured_at 分开。回溯取得的手续费/保证金/限价标为
`retrospective_execution_facts`，不声称过去已捕获，不制造历史 known_at。
看过的筛选年只能形成固定规则分段诊断，不能称独立未见 OOS。

研究执行版本 `newow_causal_next_open_offset_costed_v2` 独立处理开仓、平今、平昨费用；
双策略同 Bar 排序为 CLEAR 优先、同动作震荡优先，然后压成最终 LONG/FLAT。
WF 的物理前缀仅用于指标预热，不需要不发生交易时的手续费；仍以同物理段首个 eligible
来源 tick 校验前缀 OHLC。可成交 Bar 的逐日成本与涨跌停必须完整，否则失败。
固定 1 tick 以及双滑点压力均为模型假设，不标为 provider 成交事实。

## 时间、目标与执行

BUILD 转换为最多一手开仓意图，CLEAR 转换为清仓/取消未成交开仓意图。
已持仓、挂起开仓、未知订单和取消等待都占用容量，重复目标不累加手数。
同一 decision/command 的稳定身份只允许相同 payload；冲突失败。
订单只能在 `bar.start > max(order.created_at, effective_after)` 的后续可交易 1m Bar
按 open 加减整数 tick 滑点成交。止损在 completed close 检测，不能倒填本 Bar open。
成交时间与记录时间分开；历史回放的 recorded_at 是模拟观察时间，不是实际系统观察。

费用区分开仓、平今、平昨，均为 Decimal。金额、tick、乘数、费率、保证金和日涨跌停必须有
exact physical contract / trading day 来源。开仓保证金只能用开盘时可知的价格/昨结算价及
当日有效比例，不用本 Bar close。额外保证金占用百分比未指定，只执行资金充足和单手限制。
无成交量、停市、触及执行方向涨跌停、订单限价不满足或事实缺失时不虚构成交。
OHLCV Bar 不是委托簿：成交仍属明确模型假设，不保证 SimNow 或实盘获得同样价格。

主力切换不允许新合约价格估值或清算旧仓；没有旧合约后续可执行行情就保留旧仓并停开。
首版没有自动换月，不将换月中断/期末未平仓默认为零成本清仓。

## 2% 日亏停机

日初权益为进入权威交易日时的账本权益（包括此前最后有效标价的浮盈亏）。
首日为 50000 元，阈值 1000 元；以后随各日初权益变化。权益包含已实现盈亏、浮盈亏和费用。
当 `equity <= day_start_equity * 0.98` 时持久停开，取消未成交开仓并创建旧合约强平意图。
已挂普通限价平仓也先取消，确认后替换为无普通限价的强平意图；未知订单未核清前不得重复发送。
新指令、同日重启和回放不解除停机；平仓在之后可执行时点发生，封板或跳空可能使亏损超过 2%。

交易日取权威输入，不按自然午夜切换。普通未停机持仓可经账本数量/合约对账跨日；
此前已停机但未平仓或仍有未终态订单时，新交易日继续保持停机并处理旧仓平仓。
只有进入下一交易日且平仓、订单终态、对账一致才复位。平仓完成当日不会立即重新开仓。

## 持久化与恢复

`guiyi_quant.paper` 为无 I/O 的命令/事件 reducer；`app.paper.ledger` 只负责 PostgreSQL 原子存储。
显式配置专用本地 `GUIYI_PAPER_DATABASE_URL`，不回退生产 DATABASE_URL，不在普通 API 启动建表。
要求 localhost、显式非 5432 端口、`guiyi_paper_*` 数据库、无 URI query 参数，并拒绝混有其他表。
网络地址检查只是防误操作边界；操作者仍须确认独立实例身份。

账户行锁串行化命令；命令唯一键、payload hash、事件序列和 hash chain 随同一次事务提交。
事件和命令表拒绝普通 UPDATE/DELETE/TRUNCATE。账户权益与持仓可从原始命令及事件全量重算；
读回校验事件内容、顺序、账户末端 hash 和命令回执对应关系。不声称防御数据库超级用户恶意改写。
连接中断不能推断未提交，返回 `PAPER_COMMIT_OUTCOME_UNKNOWN` 并停止 mutation；
只能先用同一 command identity 只读核对，禁止自动重试。失败事务不会保留半条成交。

历史回放用于工程验收，不能冒充持续 Paper、Shadow、Broker 对账或 SimNow 成交。
阶段晋升仍需明确交办和相应真实证据；盈利/测试通过都不会自动启用交易。
