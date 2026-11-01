# 苏冰2.3：分周期成交量因子

2026-11-01 owner确认：日线本根成交量>前根；30m本根成交量≥前根×2，恰为2倍有效。
此规则替代本轮阶段一此前的30m仅大于前根规则。仅作为独立量能条件，不能单独构成开仓，
不自动新增日线量能必需Gate、不强制用于加仓。完整组合规则由后续策略组合阶段确定。
2.1趋势±5°和2.2金叉交点[-4,4]/高位死叉>17已经owner核对通过，本次不修改。

版本 `subing_volume_d1_gt1_m30_ge2_v1`。输入为同周期、同物理合约连续已完成K线的MDS成交量Decimal；
逐根状态只保留前根量和完成时间。比较原始成交量，不按时长、时段或跨日进行归一化；
“前根”是连续行情前根，包括夜盘/日盘或交易日边界前根，不限同一自然日，不跨物理合约。
MDS加载完整前缀，因此rank1展示窗口第一根可以使用同合约成为主力前的真实前根，不使用旧主力量。

输出 current、previous、ratio、previous_end、effective、reason。effective是true/false/null，
null表示未知，不能当作不满足或放行。首根缺少前根、非法负数/非有限/缺失量为未知；
非法输入清除前根，下一根也无法比较，直到连续两根有效输入恢复。零量是有效原始事实，不当缺失处理。
前根为零时ratio=null，effective仍按原不等式：日线0→0为false、0→正量为true，30m两种都为true。
特别是30m 0→0只是满足该算术不等式，不意味着流动性有效或可开仓；数据质量和可执行性由对应层负责，
本因子不静默增加owner未指定的成交量Gate。比例只展示，不经舍入比例做判定。

时间和合约身份不一致、无时区、重复或倒序输入拒绝。completed和coverage由现有MDS加载器负责。
页面日线取所选30m时刻严格早于的最后一根完成日线，不读取当日尚未完成的日线，不使用前视量。
页面蓝色柱为条件满足，灰色为不满足，橙色为未知；整体统计只计算rank1有效区间并明确是全窗口。
不生成订单、完整开仓信号、收益或OOS结论，不改变正式Runtime。

## 查看与验证

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:services/quant-api:packages/quant-core services/quant-api/.venv/bin/python scripts/research/subing_trend.py --since 2026-07-13 --through 2026-09-11 --macd --volume --output output/subing-trend-20261101/volume23
```

复用2.1只读加载及来源校验，--volume独立可选，默认2.1/2.2不附加量能输出。旧产物保留不覆盖。
新产物包含独立量能版本、输入来源hash及源码路径hash。验证入口为tests/unit/subing_volume、
tests/unit/subing_trend以及既有MACD与指标kernel测试。
