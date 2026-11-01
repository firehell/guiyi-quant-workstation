# 苏冰2.4：价格与EMA21事实

当前范围为JM已完成30m的价格关系纯函数。复用2.1同一条EMA21，不重算第二套EMA；
不改变已核对的趋势、MACD或量能规则，不生成持仓或交易动作。

版本 `subing_price_ema21_distance10_v1`，输入原始收盘Decimal及共享6位EMA值转为Decimal：

- close>EMA21：above_ema=true；close<EMA21：below_ema=true。
- close=EMA21：relation=ON，上方与下方都为false。
- distance=close−EMA21，单位为价格点；near_above_ema为0<distance<10，等于0或10都为false。
- near_above_ema仅表示“满足已确定回踩距离条件”，不要求隐藏的前根向下移动或最低价触线条件，
  也不自行检查是否持仓、之前是否减仓、量能、MACD、趋势方向。
- EMA未就绪为WARMUP/UNKNOWN；非法收盘或EMA为INPUT_INVALID/UNKNOWN，布尔字段null，不当作false或放行。
- below_ema是每根收盘在均线下方的事实，不要求前根在上方，也不代表已执行清仓。

completed、物理身份、前缀、时序和coverage由现有MDS加载层校验。页面只显示所选时点及以前的事实。

## 尚待确认的突破资格

本轮已向owner集中询问：连续新回踩替换还是保留原回踩、资格失效条件、首次突破后是否消费。
这些会影响加仓语义，在回复前不实现资格状态机，不输出突破或加仓条件。
原先阶段一确定盘中严格突破回踩K高点；只有30m OHLC时，只能在收盘后证明本根曾突破，
无法证明精确盘中触发时间或成交价格。后续必须区分历史Bar高点事实和实时/更细周期可执行触发。

## 使用

复用独立导出开关`--price`，可与`--macd --volume`组合。输出新目录不覆盖旧产物；保留价格因子版本及源码hash。

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:services/quant-api:packages/quant-core services/quant-api/.venv/bin/python scripts/research/subing_trend.py --since 2026-07-13 --through 2026-09-11 --macd --volume --price --output output/subing-trend-20261101/price24
```

验证入口：tests/unit/subing_price、tests/unit/subing_trend和既有趋势/MACD/量能及共享kernel测试。
