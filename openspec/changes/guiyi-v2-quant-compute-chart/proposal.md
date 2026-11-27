# 归一量化 V2 · 量化计算核心与图表指标体系

2026-11-26 · 基于 develop `bc1d85703fac7eb0a562c8e69589d46fc4e1f785`。本 change 定义计算、图表与独立包发布目标；不执行生产切换。

## Why

现有 `packages/quant-core` 已是独立 Python 包，但通用指标、Newow/HTDY/SuBing 专属计算、图表显示定义和前端图层生命周期仍分散在多个模块。Newow 已有主图趋势带/通道/形态、四类副图、特殊成交量显示和专属 Primitive；这些能力不能在精简基础指标时被遗漏，也不能为了统一而改写既有策略公式。

归一量化需要一套规模受控、计算高效、可复用、可独立发布的计算核心，以及与计算分离的图表指标管理体系。基础指标直接采用 TA-Lib；自主趋势特征和有限的公共形态识别由 Quant Core 管理；已有策略专属公式继续保留；主图、副图、成交量显示和图层生命周期由独立 Chart 包管理。

## What Changes

- 将 `guiyi-quant-core` 确立为唯一通用计算包：TA-Lib 提供 EMA10/21/60、MACD 12/26/9、ATR14、STDDEV、BOLL、HHV、LLV、OBV；量比采用轻量 NumPy 实现。通用指标不再并行维护自研公式，也不增加 SMA/WMA、RSI 等非白名单指标。
- 保留自主趋势因子，但首版只整理现有趋势方向、EMA 斜率、OLS 斜率及 ATR 归一化斜率；ABU 仅作特征组织思路参考，不引入整套系统或新增未经验证的因子。
- 建立有限的公共 Price Action Kernel：Swing Pivot、Support/Resistance、Breakout/Breakdown、Retest/Pullback。保留发生时间、确认时间和可用时间；回看展示不得冒充当时可知信号。
- 保留 Newow、HTDY、SuBing 的专属计算与公式身份。Newow 主图/副图、杯柄、趋势带、震荡通道、D1–D6、突破/影线、照妖镜、涨跌动能、主力控盘、趋势转折等均纳入可管理目录，不因通用指标精简而删除或改写。
- 新增独立前端包 `@guiyi/quant-chart`，复用现有 Lightweight Charts，统一主图、成交量 track、副图 Pane、Renderer、Layer Manager、Indicator Catalog 和 Chart Profile。
- 将计算定义注册与显示定义注册分离，以稳定 `indicator_id` 连接；支持新增、显示/隐藏、从当前图表移除、退役和安全删除。
- 保留通用成交量特殊着色、苏冰 2x/3x 档位和 Newow 专属成交量显示。纯显示变换不得生成策略信号或修改成交量原始事实。
- 为 Quant Core 和 Quant Chart 建立独立 SemVer、构建产物、测试和 Release；继续使用 Monorepo，不拆仓库、不引入微服务。API/Web 只消费锁定的精确包版本。
- 修改 Newow MACD 副图合同：改用 TA-Lib MACD 12/26/9 原始输出，不再依赖旧通用 `sma_window` 自研内核和额外 histogram ×2 缩放。该变化只针对通用 MACD 显示，不改写 Newow、HTDY、SuBing 策略内部的专属数学公式。

## Capabilities

- 新增 `quant-compute-core`：定义纯计算包、TA-Lib 指标白名单、趋势特征、公共形态、策略专属内核、计算模式和结果合同。
- 新增 `chart-indicator-system`：定义计算/显示注册、主副图布局、成交量显示、图层生命周期、Chart Profile 和诊断能力。
- 新增 `independent-package-release`：定义 Quant Core 与 Quant Chart 独立版本、构建产物、消费者锁定和兼容合同。
- 修改现有 `newow-product-reference-trading` 的 MACD auxiliary requirement，使其使用 TA-Lib 12/26/9。

## Scope / Non-goals

- 本 change 是架构与后续隔离实施合同，不修改当前生产公式、策略结果、参考收益、账户、订单、Alert、Runtime 或 `auto_order=false`。
- 不重写 Newow、HTDY、SuBing 的策略专属公式。其内部可能使用的 SMA/WMA/EMA、专属 MACD、状态机和历史复刻数学仍按各自版本保留；本次精简只约束通用指标目录。
- 不引入完整 ABU、TrendLib、PatternPy 或 GPL 源码；只借鉴可解释的 Pivot、支撑阻力和特征组织思想。
- 不增加 RSI、KDJ、CCI、ADX、复杂蜡烛图大全、机器学习形态库或持仓量衍生指标。
- 不替换 Lightweight Charts，不改变现有 Newow/Free/HTDY/SuBing 产品入口，不默认同时展开全部副图。
- 不把图表显示变换、回看重绘形态、策略 Hint 或账户事实混成通用交易信号。
- 不拆分 Git 仓库，不建设分布式计算平台，不引入 Kafka/Spark 等基础设施。
- 不在本 change 内实现正式 Runtime 切换、正式发布 main/tag 或策略晋升。

## Impact and precedence

- 现有代码入口：`packages/quant-core/guiyi_quant/indicators`、`packages/quant-core/guiyi_quant/newow`、`apps/quant-web/src/utils/mainIndicators.ts`、`apps/quant-web/src/utils/volumeDisplay.ts`、`apps/quant-web/src/utils/subingVolumeTierDisplay.ts`、`apps/quant-web/src/components/market/detail/newow`、`apps/quant-web/src/components/kline`。
- 当前 `guiyi-quant-core` 已是独立 Python 包（`packages/quant-core/pyproject.toml`，当前版本 0.1.0），但 API 开发依赖仍使用 editable path；本 change 要补齐发布制品和正式消费者锁定，不宣称当前已独立发布。
- 现有产品边界继续以 `PROJECT_SOURCE.md`、`DECISIONS.md`、`docs/ARCHITECTURE.md` 和 `STATUS.md` 为准。Newow 当前单一主图、同 Bar 成交量、单个选中副图及四个自定义副图的语义必须保留；SuBing/HTDY/Free 的既有偏好与成交量规则必须保留。
- `openspec/specs/range-detector/spec.md`、`openspec/specs/newow-product-reference-trading/spec.md` 及 HTDY/SuBing 相关合同仍是现行权威。本 change 只对 Newow MACD auxiliary 提交精确 MODIFIED delta；其他专属公式不因 TA-Lib 引入而改写。
- 本 change 不修改 `STATUS.md`、`PROJECT_SOURCE.md`、`DECISIONS.md` 或 active architecture。实施完成后再将已验收 delta 同步到 active specs 和对应 canonical，避免候选设计提前成为运行事实。
