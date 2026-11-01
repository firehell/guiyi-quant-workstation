# 苏冰2.4：价格与EMA21事实

当前范围为JM已完成30m的价格关系纯函数。复用2.1同一条EMA21，不重算第二套EMA；
不改变已核对的趋势、MACD或量能规则，不生成持仓或交易动作。

基础距离参考字段（历史v1），输入原始收盘Decimal及共享6位EMA值转为Decimal：

- close>EMA21：above_ema=true；close<EMA21：below_ema=true。
- close=EMA21：relation=ON，上方与下方都为false。
- distance=close−EMA21，单位为价格点；near_above_ema为0<distance<10，等于0或10都为false。
- near_above_ema仅表示“满足已确定回踩距离条件”，不要求隐藏的前根向下移动或最低价触线条件，
  也不自行检查是否持仓、之前是否减仓、量能、MACD、趋势方向。
- EMA未就绪为WARMUP/UNKNOWN；非法收盘或EMA为INPUT_INVALID/UNKNOWN，布尔字段null，不当作false或放行。
- below_ema是每根收盘在均线下方的事实，不要求前根在上方，也不代表已执行清仓。

completed、物理身份、前缀、时序和coverage由现有MDS加载层校验。页面只显示所选时点及以前的事实。

## 回踩资格（owner 已确认）

版本 `subing_price_ema21_atr02_pullback_v2`。复用2.1的EMA21与ATR14。
最低价在 [EMA21−0.2ATR, EMA21+0.2ATR] 闭区间为触及；触及且收盘>EMA21为守住确认。
原0<收盘距离<10仅保留参考字段，不参与资格。没有额外趋势、阳线、量能、MACD或前根位置门槛。

确认K收盘后记录其物理合约、时间、高点。后续K高点严格大于资格高点，记录一次突破并消费旧资格；
收盘≤EMA21取消资格；新的确认K替换旧资格。当前K不能突破自身刚确认的高点。
同根先检查旧资格的高点突破，再处理收盘失效和新确认，因此突破事实与收盘失效可并存。
如果本根也确认了新的回踩，其新资格从下一根开始生效。突破不是订单或成交，
30m OHLC不能给出盘中精确发生时刻或成交价格；组合策略另行处理执行优先级。
无固定到期根数；切换物理合约拒绝继承；非法输入或指标未就绪清空资格并返回未知。

导出使用 --price（可组合 --macd --volume），输出新目录，保留版本与源码hash。
验证入口为 tests/unit/subing_price 和 tests/unit/subing_trend。
