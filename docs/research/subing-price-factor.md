# 苏冰2.4：价格与EMA21事实

当前范围为JM已完成30m的价格关系纯函数。复用2.1同一条EMA21，不重算第二套EMA；
不改变已核对的趋势、MACD或量能规则，不生成持仓或交易动作。

基础距离参考字段（历史v1），输入原始收盘Decimal及共享6位EMA值转为Decimal：

- close>EMA21：above_ema=true；close<EMA21：below_ema=true。
- close=EMA21：relation=ON，上方与下方都为false。
- distance=close−EMA21，单位为价格点；near_above_ema为0<distance<10，等于0或10都为false。
- near_above_ema仅表示“满足旧版距离参考条件”，不要求隐藏的前根向下移动或最低价触线条件，
  也不自行检查是否持仓、之前是否减仓、量能、MACD、趋势方向。
- EMA未就绪为WARMUP/UNKNOWN；非法收盘或EMA为INPUT_INVALID/UNKNOWN，布尔字段null，不当作false或放行。
- below_ema是每根收盘在均线下方的事实，不要求前根在上方，也不代表已执行清仓。

completed、物理身份、前缀、时序和coverage由现有MDS加载层校验。页面只显示所选时点及以前的事实。

## 上涨背景下的回踩（v3研究解释）

版本 `subing_price_ema21_atr02_context_v3`。基础事实与形态资格分开，不改2.1趋势公式。
以下为owner要求结合四阶段示意图优化后的具体量化解释，供页面核对，不是盈利或实盘结论。

1. 已完成30m的共享趋势为UP（角度>5°），且close>EMA21+0.2ATR，建立背景，记录该根时间与收盘价；最新符合条件的背景覆盖旧背景。
2. 后续K的low低于进入本根前的背景收盘价，证明价格发生回落，而不只是均线上移追上价格。
3. low位于[EMA21−0.2ATR, EMA21+0.2ATR]，且close>EMA21，基础hold成立；同时满足既有背景、回落、当前趋势非DOWN，才qualified_hold成立。
4. 有效回踩记录其高点与时间；严格后续K的high>旧高点记录breakout并消费旧资格。新有效回踩替换旧资格。

背景用之前已完成K建立，当前K不能先建立背景再确认自身回踩，当前回踩也不能突破自己。
中性趋势保留背景，DOWN清除背景及旧资格；close<=EMA21仅取消旧资格，背景可保留以允许重新站回。
未知趋势/指标、非法输入清空全部状态；跨物理合约拒绝继承；未设置额外到期根数。

同根先检查旧资格的高点突破，再处理收盘失效/趋势转下及新确认；突破事实与失效可同时出现，
不表示该根收盘仍可交易。若本根另有新的有效回踩，其资格只对后续K有效。
30m OHLC不提供精确盘中时间或成交价格。组合策略仍须处理日线背景、持仓与风控等条件。

旧0<收盘距离<10仅为参考，不参与资格。没有额外阳线、量能、MACD、连续N根上涨或加仓门槛。
图表展示K线、EMA容差带、普通触及、有效回踩、突破和所选时点仍有效的高点参考线，按物理合约隔离。

导出使用 --price（可组合 --macd --volume），输出新目录，保留版本与源码hash。
验证入口为 tests/unit/subing_price 和 tests/unit/subing_trend。


## 镜像反弹（v4）

当前版本 `subing_price_ema21_atr02_context_v4` 增加空头镜像，使用同一方向参数化算法，方向进入状态身份，禁止混用。DOWN背景且close<EMA−0.2ATR；后续high高于已有背景收盘，high触及同一EMA±0.2ATR带且close<EMA，当前趋势非UP时确认有效反弹。冻结反弹low，后续向下突破；UP清空背景和资格，close≥EMA仅取消资格。预热、未知、同根不可自建背景/自突破等边界与多头一致。

导出`price_factor.rebound`使用共享结构，其中`armed_high`字段在该子结构表示空头冻结的反弹低点（历史共享结构命名）；账户适配明确转为`rebound_low`，决策意图使用无方向歧义的`breakout_level`。原`price_factor.pullback`仍为多头回踩，旧输出保留原版本。
