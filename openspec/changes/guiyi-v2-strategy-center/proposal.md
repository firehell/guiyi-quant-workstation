# 归一量化 V2 · Strategy Center

> 状态：候选架构变更。本文定义策略管理与观察层，不代表相关策略 Runtime 已启用、健康或通过自然业务验收。

## Why

归一量化当前保留的策略已经收敛为六个策略身份，分别属于 Newow、HTDY 和 SuBing 三个业务领域。三者的运行触发、状态所有权、结果事实和账户边界不同。

此前将所有策略抽象成同一个 Strategy Runtime、通用状态机和统一结果存储，会重复建设已有能力，并可能把 Newow 参考动作、HTDY 账户事实和 SuBing 共享 Paper 账本混为一谈。

需要一个统一的管理入口，回答策略身份、所属领域、公式/政策版本、支持范围、配置引用、真实运行状态和研究证据；但不接管三个领域的公式、调度、状态、账户或结果存储。

## 当前策略目录基线

### Newow：四个策略身份

| strategy_id | 类型 | 定位 | 领域结果所有者 |
|---|---|---|---|
| newow_trend | BASE | 趋势基础策略 | Newow / ReferenceTrading |
| newow_oscillation | BASE | 震荡基础策略 | Newow / ReferenceTrading |
| newow_main_rise | BASE | 主升浪基础策略 | Newow / ReferenceTrading |
| newow_dual_fusion | COMPOSITE | 趋势与震荡融合，具有独立融合状态与结果身份 | Newow / ReferenceTrading |

Newow 产品支持周期为 5m、15m、30m、60m、1d、1w；具体品种、周期、页面 section、历史资格、当前 Scope 和自然运行状态分别由现有 capability、数据和运行权威决定。支持矩阵不得被解释为所有组合均已配置、启用或 READY。

双策略融合是独立的产品/结果身份，但不是第四套基础公式。它消费趋势与震荡的既有结果，不重复运行两套基础内核。Newow 的主动作、Hint 和 ReferenceTrade 保持现有语义；Hint 不产生数量或账户效果，ReferenceTrade 不代表订单、成交、持仓或账户盈亏。

### HTDY：一个独立领域策略身份

| strategy_id | 类型 | 定位 | 领域所有者 |
|---|---|---|---|
| htdy_60m | DOMAIN_STRATEGY | 火天大有原始 60m 方向观察规则，另有独立固定一手账户政策与 TQKQ 接入边界 | HTDY / TQKQ |

原始公式身份为 huotian_dayou_original_v0，具有已知重绘风险；当前指标登记将其标为 observation-only，不能因策略目录登记而获得历史回测、正式 Live 或自动下单资格。60m 信号、1m 执行准入、固定一手账户政策、账户风险、TQKQ 委托/成交回报和恢复必须继续遵守各自现有合同。代码存在、宿主存在和账户当前可执行是不同事实。

HTDY Alert 是独立 Alert Domain，不是该策略的第二个信号写入者。

### SuBing：一个共享资金组合策略

| strategy_id | 类型 | 定位 | 领域所有者 |
|---|---|---|---|
| subing_portfolio_16 | PORTFOLIO | 唯一保留的 16 品种共享资金 Paper 组合 | SuBing Portfolio / PortfolioJournal |

政策身份为 subing_portfolio_one_lot_v2。16 个品种为 JM、LC、RB、SA、FG、MA、EC、V、PR、TA、UR、SH、SC、CJ、OI、I。它们是一个组合内部的品种维度，不是 16 套独立策略或独立资金账户。

持续观察和历史回放是同一组合的两种视图。共享资金、组合风险、退出优先、固定品种顺序、Run、执行事实、模型成交和 PortfolioJournal 继续由 SuBing 领域拥有。

苏冰同花顺预警是独立 Alert Domain，不是 Paper 组合的策略实例或成交来源。

### 不纳入当前正式策略目录的内容

- HTDY 与 SuBing Alert、Newow Hint：分别属于 Alert 或策略输出，不作为独立交易策略注册。
- EMA、MACD、ATR、Range Detector 等：属于 Quant Compute；指标注册不代表策略注册。
- L.M.S 作者计划与 Near405：保留为研究模式，不是当前正式策略。
- 新苏冰 V1/V2、独立 JM 开发模型、14 品种组合、焦煤日线、四统一及环境—需求等旧研究：已退役。旧 Run、账本、事件、研究文件和身份只按原用途审计，不进入现役目录。

## What Changes

1. 建立六个当前策略身份的静态、类型化目录，明确领域、类型、公式/政策引用、输入能力、结果所有者和允许用途。
2. 将公式版本、Profile Revision、策略绑定、部署代次、运行状态和研究证据分开表达。
3. 通过三个只读领域适配器读取 Newow、HTDY/TQKQ、SuBing 的权威状态和结果引用。
4. 建立统一只读查询合同与策略工作台视图；领域详情仍保留各自语义。
5. 明确计算共享、状态串行、账户串行和后台任务隔离规则，禁止新增一个覆盖所有领域的通用 Strategy Scheduler。
6. 明确候选、验证、Shadow、人工批准和退役之间的治理边界。

## Scope

本变更只定义 Strategy Center 的目标架构、数据合同、领域适配、只读查询和产品交互。首期不新增策略执行内核，不迁移现有公式，不接管领域账本，不扩大任何品种、周期、Scope、Alert 或 Runtime 权限。

## Non-goals

- 不重写 Newow、HTDY 或 SuBing 公式、状态机和账户模型。
- 不建立通用策略脚本上传、任意 Python 执行、策略 DSL 或拖拽式策略编辑器。
- 不建立中央策略状态库、统一成交/持仓/账户/PnL 账本。
- 不为每个策略、品种或周期创建独立线程、进程或 Worker。
- 不重建 Quant Compute Registry/Runtime，不在策略中心重复计算指标。
- 不把 Alert、Hint、研究形态、指标或 L.M.S 模式包装成正式交易策略。
- 不改变 Newow 当前有效运行触发合同；V2 盘后目标与当前 active 合同之间的差异由其专门变更处理。
- 不改变 RQAlpha 数据域、回测撮合、生产数据、数据库、通知、TQKQ 或 Paper Runtime。
- 不改变 auto_order=false，不授权实盘下单、自动晋升、main/tag 发布或 Runtime promotion。

## Impact

本变更新增 Strategy Center 的目标能力合同，依赖现有 MarketDataService、Quant Compute、Newow Product/ReferenceTrading、HTDY/TQKQ、SuBing Portfolio、Alert 和 Research 领域。

本变更不修改这些领域的 active canonical。后续实现必须先以只读目录和只读适配开始；任何公式、数据时序、账户、Scope、Alert、运行触发、持久化或部署变更都需要独立的精确变更和相应验证。
