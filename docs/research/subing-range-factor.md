# 震荡／趋势与动态箱体研究因子

独立研究身份 `subing_dynamic_range_v1`，复用现有 `subing_ema21_ols5_atr14_v2` 的方向和ATR14。
只支持当前研究页的焦煤 D1/30m，不改变 Lux Range、现役策略、订单、Alert 或 Runtime。
这是依据 owner 交办方案实现的自定义研究算法，不宣称复刻任何 TradingView 私有公式。

## 市场状态与箱体分别表达

- `RANGE`：输入可用，但尚无连续确认的有效方向；包括窄幅盘整、宽幅无序及方向待确认阶段。
- `TREND_UP/DOWN`：20根 close 变动的 ER≥0.55，净位移方向与既有 EMA21 方向一致，连续2根成立。
- `UNKNOWN`：预热、无效价格/因子、coverage失败或箱体宽度失效；不能当作震荡放行。

“震荡较多”不是配额，实际占比随样本变化。方向阈值0.55与连续2根是本次实现的研究默认值，
未经标签准确率或OOS验证。EMA方向有延迟，低效率有方向的缓慢运动可能仍暂归震荡，须在核对页检查。
箱内即使已检测到方向，也保留市场趋势分类，独立的 `trend_candidate=false` 继续关闭新趋势候选。
候选只是研究事实，不是正式交易许可，也不管理已有持仓。

## 逐根合同

调用方提供同物理合约、同周期、权威连续 completed Bars 和同根共享趋势因子；导出入口复用
`subing_trend.load` 的 MDS 完整生命周期前缀、源校验与只读事务。不能仅凭时间间隔猜测合法session缺口。
预览、重复/倒序和身份混用拒绝；明确coverage失败、非法OHLC清空状态，重新预热。状态和输出均不可变。

ER=abs(C[t]-C[t-20])/sum(abs(ΔC),20)，零路径为0。
CHOP=100×log10(sum(TR,20)/(HHV(H,20)-LLV(L,20)))/log10(20)，约束到[0,100]；
零区间且正ATR时为100。TR使用同合约上一收盘价。ER和边界为Decimal；CHOP仅对数计算为浮点。

ER≤0.35、CHOP≥61.8、20根范围≤3 ATR，连续2根成立才确认箱体；首次完整ER需21根价格，
同时等待既有EMA因子完成预热。`FORMING`不回画；箱体ID含合约、周期、profile和确认时间。
框从确认时点可见，初始边界取当时窗口，不把边界画回窗口起点。

确认时冻结ATR参考。每根先用旧边界检查收盘是否严格越过0.2 ATR缓冲，然后才考虑扩展：

1. 越过缓冲：`BREAK_PENDING`，连续同向2根为`BREAK_CONFIRMED`，期间上下沿不动。
2. pending未继续越过同向缓冲：`BREAK_FAILED`，此根只记录旧突破失败；即使跨到另一侧，也从下一根才计新突破。
3. 仅收在边界外、缓冲内：`BOUNDARY_TEST`，不扩边、不开放候选。
4. 收盘在内、ER≤0.35且无明确高效率方向：单边每次最多扩0.25 ATR，总宽≤4倍初始ATR。
   不满足单次扩展条件时保留原边界；总宽超限则清箱重找，并在本根显示UNKNOWN。
5. 已确认突破的旧箱体冻结，下一根退休重找；无箱体时持续方向也能产生趋势候选。

每次扩展以新的Box快照和revision生效，旧Point/边界不修改。未来行情只影响未来输出。
窗口最多保留21根；保存完整State可接续，不依赖全历史回画。

## 三个预设与使用

`fixed`：不扩展、1根突破；`bounded`：有限扩展、1根突破；`bounded_confirmed`（默认）：有限扩展、2根突破。
其余阈值一致，分别检验扩展与确认的影响；不自动择优，不把已观察窗口称为OOS。

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:services/quant-api:packages/quant-core services/quant-api/.venv/bin/python scripts/research/subing_trend.py --since 2026-07-13 --through 2026-10-30 --range --range-profile bounded_confirmed --output output/subing-range-review
```

输出目录必须不存在。`data.json`保留输入/代码hash、逐根事实和参数；离线`index.html`有日线/30m状态、
逐根箱体边界、原始ER/CHOP及分布。日线取严格早于所选30m时刻的完成数据。
可与原有独立因子面板共同导出，但不会改动组合规则。期间参数变体禁止与本版震荡因子混用。

验证：

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:services/quant-api:packages/quant-core services/quant-api/.venv/bin/python -m pytest -q -p no:cacheprovider tests/unit/subing_range tests/unit/subing_trend services/quant-api/tests/test_indicator_kernel.py services/quant-api/tests/test_indicator_kernel_v1c_macd_atr.py
```

覆盖前缀一致、逐根接续、混合生命周期恢复、宽幅无序、缓慢单边、箱内方向、上下突破、假突破、
扩展上限、未知/数据缺口重置以及导出前缀与现有因子隔离。合成样例验证算法合同，不证明真实行情识别准确率。
