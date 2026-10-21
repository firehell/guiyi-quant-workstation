# 牛哇指标基础上的期货双向研究 v1

本canonical落实owner批准的2026-10-20计划。`strategy_model=futures_bidir_v1`是归一自有研究假设，
不是牛哇原公式，不替代Newow page-parity，也不是正式策略晋升或持续运行授权。
八个界面名称不变，底层新公式、持仓、风险、执行、账户、参考版本独立。

## 冻结指标与策略

所有价格与金额采用Decimal，完整窗口；T=(H+L+C)/3，快慢线SMA7(T)/SMA10(T)，
ATR20为20根TR算术均值，需要此前收盘；通道为当前根之前10根HHV/LLV。
多头背景要求C>慢线、快慢差>=0.1ATR、慢线较三根前上涨>=0.1ATR；空头对称，其余neutral。
缺失或ATR<=0为unavailable，不能归为neutral/flat。物理/owner/计算段独立预热。

| variant | 首次入场 | 未升级时普通退出 |
|---|---|---|
| trend | 背景同向且C突破此前3根H/L | 持有周期连续两根C位于MA10反侧 |
| oscillation | neutral、此前10根宽度>=2ATR；多头L<=下沿且阳线、下沿<C<上沿；空头对称 | C到达对侧滚动边界 |
| main_rise | MA35/MA45同向，间距>=0.25ATR，MA45三根斜率同向，C突破此前11根H/L | 连续两根C穿过MA45 |
| dual_fusion | directional用trend、neutral用oscillation，只持一份净仓 | 固定入场分支，不静默切换 |
| osc-test | oscillation、1.5ATR初始保护，其余2ATR | 同oscillation |
| osc-test2 | oscillation | C到入场冻结对侧边界 |
| osc-test3 | oscillation且下一持有级别背景同向 | 同oscillation |
| osc-test4 | oscillation | 到对侧目标记录C，之后刷新有利C极值，后来C反穿参考价退出 |

test3的1w没有受支持的更高持有级别，矩阵与页面明确NOT_APPLICABLE/NO_HIGHER_HOLDING_LEVEL，
不生成成功零收益，不擅自引入月线或使用同周期冒充高周期。

每次只产生一项仓位调整；没有入场时保持FLAT不产生账户事实。多空不同时持有。
J/D/照妖镜/旧评分不是Gate。不得通过只改显示名称生成空单。

## 周期与保护

5m/15m→30m→60m→1d→1w；30m→60m→1d→1w；60m→1d→1w；1d→1w。
每次至少曾达1R，下一周期需出现entry/stage_at之后新完成且严格早于当前决策的同向背景Bar；
每基础Bar最多升级一级。所有高周期须同物理owner/计算段，不做跨频缺口兜底。
震荡分支还需C突破入场冻结对侧边界，升级优先于普通目标退出。
升级后核心依据持有周期MA10连续两根反侧退出，不受入场周期普通目标退出。
持有周期Bar只计一次；同一高周期快照不能重复累计反侧次数或升级。

初始stop=信号C±(2ATR，test1为1.5ATR)，按tick向外取整；跳空成交前重新核算风险。
R=首次锚点至初始stop距离，首次成交后固定。达到1R后stop至少覆盖预计平仓费用；
随后按当前持有周期有利收盘极值±3ATR只收紧。更换持有周期重置该周期有利收盘极值为
已知当前标价，不能用小周期历史极值与高周期ATR拼接；旧stop仍不能放宽。
保护在completed 1m close检查，不能倒填本Bar open或声称真实触价止损。

分钟跨日须holding>=60m、曾达1R、已知日线背景非反向。曾达1R资格锁存；日线缺失不视为neutral。
不具资格时交易日最后Session结束前2分钟安排平仓，禁止开/加。
跨日资格走坏在下一基础决策安排平仓；已持仓遇输入不完整则显式中断，不能伪造退出。
日周按波段跨日。交易日与Session来自Market Fact，不按自然午夜或固定15:00推断。
平仓完成后至少经过一根完整基础周期Bar才可重入；不存在同根反手。

## 账户与事件顺序

独立10万元、首次风险0.5%、总风险1%、保证金30%，首次保证金预算10%。
两次加仓风险/保证金预算为冻结首次预算的2/3、1/3；要求新升级与至少1R/2R、当前盈利。
升级但资金或整数手数不满足只记录拒绝，不伪造加仓层；减仓后本轮禁加。
所有手数取风险/保证金/可用资金上限的向下整数；风险含往返费用和不利滑点，
保证金使用逐日多/空有效比例、开仓当时可知价格/昨结算；不得用未来close算开仓资金。
加仓层stop不放宽已有保护；预算与上限在实际成交价再次核验，只允许缩量/拒绝。
升级后入场周期C反穿MA10，先全平最新加仓层；无加仓层时减ceil(core×20%)，保留至少1手；
仅1手记录不可拆分、不得造部分手或擅自全清。层按稳定身份保留，不能借减仓重置首次风险。
权益<=日初权益98%时停开、取消开仓、安排全清；跳空/封板可越过2%，不声称损失保证。
下一权威交易日且flat/无未决指令才复位。模型不继承苏冰当日锁方向/开盘20分钟等规则。

顺序：数据/合约边界→账户风险/保护→持有周期退出→日内收尾→周期升级→普通目标退出→
减仓→加仓→新入场。升级可伴随一项加仓意图，但不能与另一个仓位动作同根并发。
pending开/加遇更高优先级退出必须取消；同一position只能有一个未决调整。

## 数据、执行与研究

首轮JM/RB/AL/TA×六周期×八策略，固定请求2024-10-14..2026-10-19。
只通过MDS/Catalog/MainContractMap/权威Session，完整物理生命周期前缀预热，eligible期间发射。
BAR completed reconstruction只表示历史回算，不声称当年实际接收时点。特征/状态hash固定。
逐日物理合约tick、乘数、费率、多空保证金、昨结算、涨跌停缺失则EXECUTION_FACTS_MISSING。
模型仅bar.start>max(decision_at,effective_after)的后续1m open按不利1tick执行；
零量、执行方向封板保留未成交；手续费分开/平今/平昨。双手续费/双滑点独立账户。
持仓/挂单跨owner标ROLLOVER_INTERRUPTED；旧合约原事实保留，不用新合约价格退出。
无持仓无挂单的owner切换可带现金继续；发生中断后全窗账户不再伪造完整收益，另做owner独立诊断。
样本尾部OPEN只mark，不伪造CLEAR/Fill。缺行情不缩窗、不插值、不替代。
未见OOS不成立，保留OOS_NOT_PROVEN；固定前后年与季度独立窗口只作历史稳定性诊断。

参考投影使用同一策略与位置政策但以completed信号C作为锚点、零成本、固定单位层，
标为executable=false；模型以真实模拟fill为锚点，所以状态/升级路径可以不同，二者不能混账。
参考入场不依赖账户资金，资金不足时仍可展示；缺行情则两者均不能伪造。
每格输出long/short、intraday/overnight、added/not-added、holding frequency归因及拒绝/中断。

## 只读交付合同

冻结packet schema_version=1，metadata含model/strategy/product/frequency/scenario/profile_id/versions、
请求窗、input_snapshot_hash、execution_facts_hash、code_revision、as_of、status、auto_order=false。
顶层summary为10万模型账户，reference包含独立summary/trades/equity/snapshot/actions；
chart为来源明确的bars/frames；其余decisions/fills/trades/equity/diagnostics均独立。
trade至少含稳定id、side、合约/owner、entry/exit、qty、holding_frequency、pnl/return与status。
参考trade的qty为本轮累计开立的固定参考单位层数：首次入场为1，每次ADD增加1，REDUCE不扣减累计值；它不表示账户手数或当前剩余层数。
价格/金额Decimal序列化为十进制字符串；时间ISO8601含时区；拒绝原因使用稳定code。
发布到显式结果根的SHA256索引；GET仅校验索引/文件/身份并有界分页，不启动回测或写生产。
接口前缀/api/v1/research/newow-futures，profiles/runs/snapshot和runs/{run_id}/parts。
snapshot查询product/strategy/frequency/scenario=baseline，返回匹配的最新冻结历史packet摘要与图表。
无对应run返回明确RESULT_NOT_FOUND；非首轮品种返回RESEARCH_NOT_COVERED，不回退牛哇。
GET绑定as_of，不声称冻结研究状态是当前实时持仓。

页面仅显式strategy_model=futures_bidir_v1使用新结果；旧链接默认原版。
同策略名称、六周期、测试菜单保持；期货双向模式独立价格图/动作/状态/参考/账户/说明，
不引用旧评分/理想收益/AI排名。切换后旧请求不得覆盖，引用和定位必须同run/hash/model。
原版不支持组合显示未开放、不悄悄换周期。结果未覆盖/资金不足/未知/空仓分别表达。
默认结果根使用仓库output/newow-futures-bidir-v1-20261021，支持显式环境配置；不改生产.env。
