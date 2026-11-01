# 苏冰2.2：MACD交叉与高度

独立研究因子，不创建交易动作，不修改active苏冰、Runtime或账户。趋势沿用owner已核对通过的2.1 ±5°版本。
本轮依据2026-11-01阶段一会话 `01a19590-7dfe-7831-b35a-e552ed2e0104` 最新确认：只做JM，固定30m，
金叉交点高度在[-5,5]（含端点），高位死叉交点>17。旧10月笔记的15m、两条线同时在[-10,10]不适用于本轮。

## 研究计算口径

版本 `subing_macd12_26_9_segment_cross_v1`。复用共享MACD12/26/9、EMA SMA-window种子、6位精度，柱值2×(DIF−DEA)。
完整同物理合约前缀计算，先完成34根预热获得有效DIF/DEA，再有连续两个有效点才能判交叉；无效输入重置预热。
仅支持30m；合约切换独立计算，拒绝重复/倒序时间和身份混用。行情coverage与completed由现有MDS导出层验证。

设前根DIF/DEA为p/q，本根为d/e，a=p−q，b=d−e：

- a≤0且b>0：GOLDEN；a≥0且b<0：DEATH；其余NONE。
- 当前两线相等不触发，等值后严格分开时判断；触碰相等后同侧离开也会依上述定义记录一次交叉。
- 两条相邻收盘连线交点比例f=−a/(b−a)，高度h=p+f×(d−p)。计算使用由共享指标十进制字符串构成的精确有理数，避免1/3等交点比例产生阈值舍入偏差，分类前不按页面精度舍入。
- GOLDEN且−5≤h≤5输出near_zero_golden；DEATH且h>17输出high_death。没有交叉时高度为空、两个条件false；预热/无效时为UNKNOWN且条件为null。
- 因子只报告条件，不检查趋势、量能或仓位，不代表完整开仓/减仓。

交点高度的线段插值、等值边界和共享指标种子是明确展示的研究实现口径，仍需owner案例核对。
线段比例不是实际盘中触发时间；事件只在本根completed后可知，禁止把事件回填到前根或插值时刻成交。
图中圆点横坐标落在确认K线上，纵坐标为交点高度，不表示几何交点的横坐标。
现有截图MACD逐值一致性尚未证明。无收益、OOS或候选晋升结论。

## 数据与查看

复用2.1的只读MDS加载、主力有效区间、完整物理合约预热和来源/映射复核，不新增行情resolver。
日线仅保留2.1趋势背景，MACD不作为日线隐藏条件。页面交叉表为全窗口事后导航，明确包含未来案例；
当前图表只显示所选时刻及以前的完成数据，日线仍strict-before。

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:services/quant-api:packages/quant-core services/quant-api/.venv/bin/python scripts/research/subing_trend.py --since 2026-07-13 --through 2026-09-11 --macd --output output/subing-trend-20261101/macd22
```

输出目录不得存在；保留2.1旧导出。新产物保留input_hash、趋势版本、MACD版本和代码hash。

验证：`tests/unit/subing_macd`、`tests/unit/subing_trend`、共享indicator kernel与MACD/ATR测试。
