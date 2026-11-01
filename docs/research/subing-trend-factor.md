# 苏冰2.1：EMA21标准化趋势因子

独立研究工具，不改现役苏冰公式、Scope、订单、风险或Runtime。5°为owner指定的新候选阈值，须由owner核对案例，
不是图表像素角度，也不是收益有效性结论。首版只分析焦煤D1/30m。

原v1使用±20°，历史导出保留；v2只调整分类阈值，角度计算不变，日线与30分钟统一使用±5°。

## 计算合同

版本`subing_ema21_ols5_atr14_v2`。复用EMA21 SMA-window seed及ATR14 `wilder_sma_seed`，
沿用基础指标6位舍入。最近5个已完成EMA21以x=0..4拟合OLS直线，
`b=sum((i-2)*(EMA[i]-mean(EMA)))/10`，`s=b/ATR14[t]`，`angle=atan(s)*180/pi`。
角度不按展示舍入分类：>5 UP、<-5 DOWN、其余NEUTRAL。预热不足、ATR非正或无效输入UNKNOWN，
不能当作中性放行；非法OHLC清空计算状态并重新预热。合约/周期混用、重复或倒序时间拒绝。

MDS验证完整同合约生命周期前缀，质量或端点缺失失败，不缩窗、不补数。rank1决定展示区间；
合约切换独立预热；重复成为owner的同合约窗口暂显式拒绝。来源在每次读取及全部读取后校验，
主力映射在末尾复核。数据通过readonly transaction读取，无provider调用。因子内核依赖调用方保证completed和coverage。

图表按所选30m时点回看，日线严格早于该时刻，避免同时收盘到达顺序假设。历史完成时间重建不是实际历史到达延迟证明。
日线可展示同合约非主力期间预热背景，统计只计rank1有效区间。不能把原截图可能不同的均线输入/预热口径视为已对齐。

## 使用

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:services/quant-api:packages/quant-core services/quant-api/.venv/bin/python scripts/research/subing_trend.py --since 2026-07-13 --through 2026-09-11 --output output/subing-trend-20261101
```

输出目录必须不存在；已有运行不覆盖。私有配置只经既有安全加载器使用，不打印。
输出`data.json`保留行情数值、来源hash和代码hash；`index.html`是无外部依赖单文件，可离线打开。
按钮定位7月交易日附近和8月26日23:00已知截图光标，具体首仓人工标签仍需核对。
无交易、收益、参数搜索或自动晋升。页面不是完整策略回测。

验证入口：

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:services/quant-api:packages/quant-core services/quant-api/.venv/bin/python -m pytest -q -p no:cacheprovider tests/unit/subing_trend services/quant-api/tests/test_indicator_kernel.py services/quant-api/tests/test_indicator_kernel_v1c_macd_atr.py
```
