# 苏冰2.3：分周期成交量因子

2026-11-01 owner最新调整：日线和30m均为本根成交量>前根即有效；30m再按放量倍数分三档。
第一档1<r<2；第二档2≤r<3；第三档r≥3。恰好2倍沿用此前包含边界的确认归第二档，3倍归第三档，避免边界遗漏。
v1的30m≥2倍旧产物保留，本轮不改写历史。仅作为独立量能条件，不能单独构成开仓，
不自动新增日线量能必需Gate、不强制用于加仓。完整组合规则由后续策略组合阶段确定。
2.1趋势±5°和2.2金叉交点[-4,4]/高位死叉>17已经owner核对通过，本次不修改。

版本 `subing_volume_d1_gt1_m30_tiers_v2`。输入为同周期、同物理合约连续已完成K线的MDS成交量Decimal；
逐根状态只保留前根量和完成时间。比较原始成交量，不按时长、时段或跨日进行归一化；
“前根”是连续行情前根，包括夜盘/日盘或交易日边界前根，不限同一自然日，不跨物理合约。
MDS加载完整前缀，因此rank1展示窗口第一根可以使用同合约成为主力前的真实前根，不使用旧主力量。

输出 current、previous、ratio、previous_end、effective、tier、reason。effective是true/false/null，
null表示未知，不能当作不满足或放行。首根缺少前根、非法负数/非有限/缺失量为未知；
非法输入清除前根，下一根也无法比较，直到连续两根有效输入恢复。零量是有效原始事实，不当缺失处理。
前根为零时ratio=null；两周期0→0均为false，0→正量为true。30m正量/零基数标记ZERO_BASELINE，
不把不存在的有限倍数强行归入第三档。30m未放量为NOT_EXPANDED；有效且前量>0时依次为TIER_1/2/3。
日线不分档，tier=null；缺失输入的30m tier也为null。分档直接比较原始量与前量×2、×3，
不使用舍入后的ratio。档位不是评分、加仓手数或开仓信号。

时间和合约身份不一致、无时区、重复或倒序输入拒绝。completed和coverage由现有MDS加载器负责。
页面日线取所选30m时刻严格早于的最后一根完成日线，不读取当日尚未完成的日线，不使用前视量。
页面30m浅蓝/蓝/紫分别为第一/二/三档，日线蓝色为满足；灰色不满足，橙色未知或零基数未分档；整体统计只计算rank1有效区间并明确是全窗口。
不生成订单、完整开仓信号、收益或OOS结论，不改变正式Runtime。

## 查看与验证

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:services/quant-api:packages/quant-core services/quant-api/.venv/bin/python scripts/research/subing_trend.py --since 2026-07-13 --through 2026-09-11 --macd --volume --output output/subing-trend-20261101/volume23-tiers
```

复用2.1只读加载及来源校验，--volume独立可选，默认2.1/2.2不附加量能输出。旧产物保留不覆盖。
新产物包含独立量能版本、输入来源hash及源码路径hash。验证入口为tests/unit/subing_volume、
tests/unit/subing_trend以及既有MACD与指标kernel测试。
