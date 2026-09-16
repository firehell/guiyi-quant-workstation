# Newow 期货无交易日输入适配实施计划

**目标：** 在不修改 Canonical 原始行情、不伪造价格的前提下，将权威期货日线中的严格全零无交易事实排除在 Newow 有效观察序列之外，并先用 PL 验证趋势、震荡、主升浪日线可正常重放。

**规则：** 仅 `OHLC=0 && volume=0 && turnover=0` 归类为 `NO_TRADE`。该事实保留在 Canonical/MDS，策略输入不生成 Bar、不推进指标或状态、不生成 Action/Hint/ReferenceTrade。部分零价、正成交量/额、缺失成交额等情况继续 fail-closed。

## 任务

1. 在 `test_product_reader.py` 写失败测试，覆盖严格识别、跳过后序列连续、readiness 计数，以及相邻异常仍报错。
2. 在 `product_reader.py` 增加单一输入分类/过滤 seam；保留原始 coverage 校验，并把原始、有效、无交易数量和策略输入政策版本写入 read source/proof。
3. 将 `FUTURES_ADAPTATION_VERSION` 升级为包含无交易日语义的新版本，并同步 typed API/Web 的精确版本合同。
4. 更新 `newow-product-reference-trading` canonical 与 `DECISIONS.md`，明确“原始事实保留、有效观察暂停、恢复后接前一有效 Bar”。
5. 跑定向后端、typed API/Web 测试及 diff/secret 检查；随后对生产只读 PL D1 readiness 与三策略 chart/reference 做验证，不执行任何数据写入。
