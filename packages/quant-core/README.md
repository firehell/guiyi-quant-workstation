# quant-core — 量化核心库

归一量化的共享纯计算库，承载通用指标、Newow 策略与研究计算、苏冰历史参考投影。
当前产品范围见 [PROJECT_SOURCE.md](../../PROJECT_SOURCE.md)，版本与验收见
[STATUS.md](../../STATUS.md)；本页不另存完成状态。

## 模块

| 路径 | 职责 | 合同 |
|---|---|---|
| `guiyi_quant/indicators/` | EMA、MACD、ATR、Range、HTDY original/strict、SuBing 公式，以及 Registry/formal policy | [Indicator Kernel](../../docs/INDICATOR_KERNEL.md)、[SuBing Alert](../../openspec/specs/subing-ths-alert/spec.md) |
| `guiyi_quant/newow/` | 趋势、震荡、主升浪、共享解释与 Hint、参考交易/统计、页面比较器，以及因果研究和 Walk-forward 计算 | [Newow 产品与参考交易](../../openspec/specs/newow-product-reference-trading/spec.md) |
| `guiyi_quant/subing_reference.py` | 同物理合约内的苏冰历史参考信号、双向反手和独立窗口统计 | [稳定产品面](../../PROJECT_SOURCE.md#htdy-与-alert) |

## 边界

- 输入由应用层通过统一行情入口取得；本库不直接连接 RQData、数据库、Redis 或读取凭据。
- 指标算法与 formal policy 以 Python Kernel 为权威；Web 通用指标镜像不能拥有正式策略或通知权威。
- Newow 页面参考、因果研究与苏冰历史参考分别保留身份和口径；参考收益不是账户收益，
  研究计算存在不表示已经通过 OOS、Walk-forward 或候选晋升 Gate。
- `ReferenceTrade` 不创建 Order、Fill、Position、Ledger 或 AlertEvent。交易数值使用 `Decimal`。
- 旧 `strategies/` 与账户/执行域已退役，不提供 Broker、Gateway 或自动下单入口；历史从 Git 追溯。

验证命令统一见 [TESTING.md](../../TESTING.md)。
