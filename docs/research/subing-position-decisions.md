# 焦煤苏冰3.2：持仓决策与离线动作回放

本轮实现独立离线决策内核 `subing_jm30_decision_v1`。只处理JM多头、固定30m技术条件与完成1m检查，首仓1手、每次加1手、最多3手。
不创建Broker订单，不接正式Runtime，不计算历史收益；完整执行、费用及账户事实适配留在3.3。

## 输入与职责

`DecisionModel(contract, run_id).apply(event)`接受显式观察或确认事件，返回before、facts、actions、after。
`checkpoint()`保存带版本及校验和的事件日志，`restore()`通过重放恢复；重复event_id及相同内容幂等，身份冲突、乱序和跨合约输入拒绝且不污染状态。

观察输入必须由调用方保证来自连续completed行情及权威Session；内核不代替MDS验证coverage。
每日方向必须携带严格早于观察时刻的来源时间。30m事实来自[阶段二联合条件](subing-joint-conditions.md)与[回踩因子](subing-price-factor.md)，没有第二套指标计算。
首仓复用五根金叉窗口；只在空仓、无未决动作、无等待/日停开、日线UP或NEUTRAL及显式准入通过时申请1手。

交易资格与阶段二展示资格分离：加仓使用持仓后新确认回踩的高点，严格后续完成1m收盘突破；不消费30m high的展示突破标记。
新增回踩可替换旧回踩；减仓及清仓清除交易资格，成交后重新等待新回踩。未知/失效回踩不能放行。

`admission`、`round_loss`、`day_loss`、`remaining_net`和`reconciled`由外部显式提供。
这些不是内核生成的资金证明：3.3负责10万元起始账户、2000元整轮净亏、5000元交易日净亏、70%权益保证金上限及费用计算。
缺少准入或风险事实时拒绝新增仓位，已经可知的退出条件仍处理；日终净浮盈未知不伪造为盈利。
日终区间由Session适配者确定为日盘14:50至结束，不用自然日推算夜盘交易日。

## 动作合同

1. 清仓优先于减仓，减仓优先于加仓。同一时点发生退出不加回。
2. 完成1m收盘低于加仓层实际确认价，退出该层；不受保留一手限制。
3. 30m收盘跌破前根low、高位死叉h>17各减1手；先排除保护退出层，再从剩余仓位最近层减，普通减仓保留至少1手。
4. 收盘破EMA、整轮亏损、日亏或日终非正净浮盈形成清仓义务；原因并列、仓位不重复退出。
5. 日线DOWN/UNKNOWN、日终区间、日停开、对账未通过及风险未知均禁止新增。已挂起开仓失去资格时发出取消请求，等明确确认后才解除未决状态。
6. 只有显式成交确认才更新逐手仓位。部分平仓确认只移除指定层；取消不算成交。确认必须晚于决策时刻。
7. 完全清仓确认后开始10根30m等待；第10根仅结束等待，之后新金叉才有效。期间旧机会不重播，跨休市不增加计数。
8. 交易日停开只允许下一交易日对账确认后解除，不清除尚未完成的冷却或退出义务。

价格、金额输入使用十进制字符串；确认输入仅是本回放的显式执行记录，不经此工具认证为Broker事实。未知成交不能通过取消或空账本伪造恢复。
清仓及减仓未决时仍保留原仓位；保护或清仓义务不会因取消某次平仓申请消失。

## 离线查看

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:services/quant-api:packages/quant-core services/quant-api/.venv/bin/python scripts/research/subing_decision.py --input tests/fixtures/subing_decision/lifecycle.json --output output/subing-decision-32
```

输出目录必须不存在，生成`replay.json`与单文件`index.html`，记录输入及源码hash；不覆盖旧结果。
页面支持事件前后导航、滑块和动作定位，显示原始输入、动作前后仓位、待确认动作与拒绝原因。
示例是明确标注的工程构造场景，覆盖首仓、加到3手、同根双减仓、加仓保护、日终禁开及清仓后等待，不能冒充真实历史案例。
其他输入使用相同JSON封包（kind、contract、run_id、source_note、events）；允许ENGINEERING_SCENARIO或EXPLICIT_OBSERVATION_REPLAY，后者也不证明来源真实性。

验证入口：`tests/unit/subing_decision`；回归范围：`subing_conditions`、`subing_trend`、`subing_macd`、`subing_volume`、`subing_price`。
3.3仍需验证实际行情到事件适配、物理合约成交与费用、账户对账和真实历史方法一致性；本阶段不宣称这些完成。
