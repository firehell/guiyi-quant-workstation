# Strategy Center 架构设计

## 1. 设计结论

Strategy Center 是一个轻量的策略控制面（Control Plane），不是第四个策略计算/交易领域。

它统一管理：
- 策略身份和静态元数据；
- 公式、参数、政策和部署版本的引用；
- 产品能力、配置绑定、授权范围和实际运行状态的区分；
- Newow、HTDY/TQKQ、SuBing 三个领域的只读查询适配；
- 策略研究证据和生命周期展示。

它不拥有：
- 策略公式和业务状态机；
- 行情读取权威；
- 策略计算调度权；
- 账户、委托、成交、持仓、资金或收益事实；
- Alert Event 和通知事实；
- 回测引擎及研究数据权威。

## 2. 架构原则

1. **领域内聚，跨域只读。** 每个策略领域继续拥有公式、状态、运行时和结果存储。Strategy Center 通过 typed adapter 读取，不反向控制。
2. **静态目录，动态事实。** 六个策略定义由版本化代码目录提供；品种/周期能力、配置、部署和运行状态从各领域权威读取。
3. **引用优先，不复制事实。** 中心保存或返回来源身份、版本、时间和查询引用，不复制领域账本或维护第二份策略结果。
4. **公式、参数、部署分离。** Formula Version、Profile Revision、Policy Version、Binding Revision、Deployment Generation 和 Research Run 不能共用一个 version 字段。
5. **不强制统一粒度。** Newow 是策略×品种×周期系列；HTDY 是账户部署及品种子状态；SuBing 是一个共享组合及其品种成员。它们不应被压成同一种持久 StrategyInstance 表。
6. **计算复用，不重复实现。** 已登记的通用指标依赖 Quant Compute；策略专属公式仍由原领域内核计算。Fusion 消费基础策略结果，不重复执行基础公式。
7. **先读后写。** 首期 API 和页面均为只读。配置编辑、部署、启停、晋升和账户操作不属于本变更。
8. **能力不等于授权。** 支持、已配置、已授权、已启用、自然运行和验收证据是独立状态。
9. **正确性优先于并发数量。** 同一领域状态和共享账户提交遵守原有顺序；只在独立状态分区且已有合同允许时并发。
10. **单机模块化单体。** 不因策略目录引入微服务、消息总线或新的基础设施。

## 3. 目标逻辑架构

~~~mermaid
flowchart TB
    M["MarketDataService / validated inputs"]
    C["Quant Compute Registry / Runtime"]
    subgraph D["Existing Strategy Domains"]
      N["Newow kernels + Product Service + ReferenceTrading"]
      H["HTDY formula + account policy + TQKQ"]
      S["SuBing factors + shared Portfolio + Journal"]
    end
    subgraph A["Strategy Center · Read-only Control Plane"]
      R["Static Strategy Catalog"]
      P["Profile / Formula / Policy References"]
      B["Capability & Binding Resolver"]
      AD["Three Domain Read Adapters"]
      V["Runtime / Result / Evidence Projection"]
      R --> P --> B --> AD --> V
    end
    M --> N
    M --> H
    M --> S
    C --> N
    C --> H
    C --> S
    N --> AD
    H --> AD
    S --> AD
    V --> API["Read-only Strategy API"]
    API --> WEB["Strategy Workspace"]
    ALERT["Independent Alert Domain"] -. separate related view .-> WEB
    RESEARCH["Independent Research Domain"] -. evidence references .-> WEB
~~~

图中的箭头表示读取/依赖关系，不要求每个方框独立进程。Strategy Center 不向领域 Runtime 发送策略计算、账户命令或状态写入请求。

## 4. 核心领域对象

### 4.1 StrategyDefinition

不可变的静态目录条目，最小字段建议：

- strategy_id；
- display_name；
- domain_id；
- strategy_type：BASE / COMPOSITE / DOMAIN_STRATEGY / PORTFOLIO；
- description；
- formula_refs；
- policy_refs；
- supported_markets；
- input_requirements；
- feature_refs；
- capability_source；
- runtime_owner；
- result_owner；
- allowed_uses；
- catalog_status。

目录只描述身份和能力，不直接 import 或执行策略内核。Newow 每个策略/周期的实际公式身份从现有产品合同解析，不能把单个公式字符串硬编码成全周期版本。

### 4.2 StrategyVersionReference

版本引用按语义分型：
- FormulaReference：策略公式/Kernel 身份；
- ProfileReference：领域已有参数 Profile 及其 Revision；
- PolicyReference：账户、风险、撮合或组合政策；
- DeploymentReference：实际部署身份和 generation；
- ResearchRunReference：固定输入与研究结果身份。

这些引用不由中心统一生成。原领域仍是版本和内容的权威。HTDY 的原始公式版本不能与账户执行政策版本合并；SuBing 的 Portfolio Policy 不能冒充公式版本。

### 4.3 StrategyBindingProjection

只读的绑定投影，不是统一持久化实例表。

- Newow：按 strategy × product × frequency × physical-owner/series identity 读取现有 capability、scope 和 reference series。
- HTDY：按账户部署读取运行范围，并按 product 展示方向/账户子状态。
- SuBing：按唯一 portfolio run 展示共享组合及 16 个成员品种。

投影必须标明来源、读取时间和权威身份。目录条目不能自动创建绑定、Scope、订阅或部署。

### 4.4 StrategyRuntimeSnapshot

只读状态投影，至少包含：
- strategy_id / domain_id；
- domain_status（原始领域状态码）；
- display_status（有限展示分类）；
- deployment_id / generation（若来源提供）；
- run_id（若来源提供）；
- last_input / watermark（若来源提供）；
- heartbeat_at（若来源提供）；
- blocked_reason / diagnostics；
- source_ref / source_as_of。

不得从进程存活、HTTP 200、代码存在或旧 STATUS 文本推导自然策略已运行。来源缺失时返回 UNKNOWN/UNAVAILABLE，不填默认 READY。

### 4.5 StrategyEvidenceReference

只读指向现有证据：
- Newow：ReferenceTrading revision/run、动作/Hint 引用、产品能力合同；
- HTDY：原生信号、TQKQ journal/readback 和独立 AlertEvent 引用；
- SuBing：Portfolio run、Journal sequence、历史回放登记和独立 AlertEvent 引用；
- Research：RQAlpha Run、OOS、Walk-forward、Shadow 证据引用。

Evidence Reference 不复制或重新计算来源事实。

## 5. 三个领域的边界与接入

### 5.1 Newow Domain

目录身份：
- newow_trend：BASE；
- newow_oscillation：BASE；
- newow_main_rise：BASE；
- newow_dual_fusion：COMPOSITE。

产品周期遵循现有 Newow capability contract：5m、15m、30m、60m、1d、1w。实际产品支持范围和已保存 Scope 不能互相推导。

Newow 领域继续拥有：
- trend / oscillation / main-rise 内核；
- dual-fusion 组合规则和独立状态；
- Newow ProductIdentity、公式版本、Profile 和输入质量政策；
- Product Service、ReferenceTradeProjector；
- ReferenceTrading 的历史/前向记录及 checkpoint（只按其 active 合同）。

Fusion 的依赖图为 Trend Result + Oscillation Result → Fusion Kernel。Fusion 有独立结果身份和状态，但不得重复运行两套基础内核。共享计算只按完整 FeatureIdentity/Input Identity 去重，不能跨物理合约、计算段、周期、revision 或参数身份共享。

Newow 的 BUILD/CLEAR 是策略主动作；Hint 是 quantity_effect=none 的辅助事实。ReferenceTrade 是研究投影，不是账户、订单、成交、持仓或 PnL。

Strategy Center 不改变 Newow 的触发时机。当前 active 合同和 V2 盘后目标之间的差异由对应架构变更处理，不能在本中心中隐式切换。

### 5.2 HTDY Domain

目录身份 htdy_60m 引用：
- 原始公式 huotian_dayou_original_v0；
- 固定一手执行政策 htdy_60m_fixed1_signal_reverse_v1；
- 账户政策 htdy_60m_account_execution_v2 及其独立风险/报价政策；
- TQKQ 原生 Controller、Journal 和 Readback。

60m 方向信号和 1m 执行准入是不同输入。原始公式的 repainting / observation-only 属性必须保留；目录注册不授予回测、正式 Live、下单或自动交易能力。

HTDY 账户事实继续由 TQKQ/HTDY 领域拥有。账户级风险、资金预留、订单状态、撤单义务、成交核对和恢复不得迁入 Strategy Center。信号计算即使未来可按品种并行，账户级命令和风险仲裁仍必须遵循原账户合同的顺序。

HTDY AlertEvent 是独立 Alert Domain；不能由策略中心从图表 marker 或账户成交反推 Alert。

### 5.3 SuBing Domain

目录身份 subing_portfolio_16 引用唯一共享 Portfolio Policy：
- policy version：subing_portfolio_one_lot_v2；
- 16 品种：JM、LC、RB、SA、FG、MA、EC、V、PR、TA、UR、SH、SC、CJ、OI、I；
- 共享初始资金 1,000,000；
- 每品种最多一手；
- 单笔预算 5,000；
- 组合日亏预算 20,000；
- 保证金上限 70%。

持续模型和历史回放是同一组合的两种视图，不是两个策略身份。1m、30m、60m completed 输入按现有组合合同消费；1d、30m、60m 的历史前缀用于指标准备。实际端点顺序、同刻优先级和交易事实资格由现有 Portfolio Worker/Journal 合同决定。

SuBing 领域继续拥有 Factors、DecisionModel、Portfolio、PortfolioJournal、Run、共享资金和组合风险。16 个品种的因子准备可以在纯计算层评估是否并行，但 Portfolio Decision 和 Journal commit 必须按原有时间与固定品种顺序串行，退出先于新增风险。不得把组合拆成 16 个独立账户或并行资金事务。

SuBing AlertEvent 和历史参考资产与共享 Paper 账本保持分离。

## 6. Profile、参数与配置管理

不建设统一的可写 Profile Manager。

- Newow：读取现有 Newow Profile、ProductIdentity、formula_versions 和 capability contracts；每个策略/周期的实际 Profile Schema 由 Newow 领域决定。
- HTDY：Formula、Account Policy、Risk Policy、Quote Policy 分别引用现有版本。首期只读，不开放通用参数编辑。
- SuBing：引用固定 Portfolio Policy 与 Run Identity。首期不提供品种范围、资金、风险阈值的在线编辑。
- 新研究候选：在未来 Research Domain 中建立独立候选配置和 Run，不覆盖当前策略 Profile 或部署。

配置修改必须由其所有者领域校验、版本化并保留输入/代码身份。中心不得直接更新数据库配置、策略公式或 Runtime 文件。

## 7. 能力、配置、授权、运行和证据状态

至少区分以下维度：

| 维度 | 含义 | 权威来源 |
|---|---|---|
| Catalog | 代码中是否登记该策略身份 | Static Registry |
| Capability | 市场/品种/周期/用途是否支持 | 各领域 capability contract |
| Binding | 是否存在实际配置/系列/组合绑定 | 各领域配置或 scope |
| Authorization | 是否允许某个 Runtime 消费输入 | 现有部署和 Scope authority |
| Runtime | 当前进程、心跳、游标、阻断和运行状态 | 各领域 Runtime |
| Evidence | 历史/自然运行/研究验证是否有证据 | 各领域结果和版本化报告 |

不得用一个 READY 字段替代全部维度。Newow capability 的 1440 个理论支持组合不代表全部已绑定或启用；HTDY/SuBing 的代码和服务安装不代表当前可执行；研究回测通过不代表 OOS 或正式晋升。

展示层可以提供统一的有限状态标签，但必须保留原始 domain_status 和原因码。

## 8. 计算性能与并发

### 8.1 复用现有 Compute Runtime

继续使用 Quant Compute 的 Registry、FeatureIdentity、依赖解析、Batch/Canonical/Live 队列和检查点。Strategy Center 不再建设第二套指标 Registry、缓存、增量引擎或全局任务队列。

仅对已在 Compute Registry 中登记的公共特征复用计算结果。Newow、HTDY、SuBing 的策略专属公式不因统一目录而自动迁移成通用 Feature。

### 8.2 领域级并发约束

- Newow：同一策略系列、revision 和状态流必须有序提交；不同独立系列只有在现有 worker/仓储隔离和实测证明允许时才可有界并发。Dual Fusion 依赖基础策略结果。
- HTDY：可独立准备/计算的品种信号不改变账户级串行仲裁；同账户的风险、预留、SUBMIT/CANCEL、回报、对账和恢复由原 Controller/Journal 顺序处理。
- SuBing：独立品种的纯因子准备可作为后续性能实验，但组合决策、共享资金分配和 PortfolioJournal 提交保持单组合顺序。
- Batch / Research：使用既有独立资源预算，不得占用或锁住 Live/账户关键路径。
- Strategy Center 查询：只读聚合必须有界并发、单域超时和部分结果能力；不得在 GET 中触发历史计算或策略回放。

首期不引入 multiprocessing、不按策略或品种创建常驻 Worker，也不调整现有队列 worker 数。性能瓶颈必须先由同一冻结输入的基准测试证明，再单独变更。

### 8.3 性能验收指标

后续实现至少测量：
- 单领域读状态延迟 P50/P95/P99；
- 多领域查询的总延迟、部分失败和超时；
- Feature Cache Hit / Dedup Ratio；
- Newow 单系列与多系列吞吐、队列积压和提交延迟；
- HTDY 信号计算与账户提交延迟分布；
- SuBing 因子准备耗时、组合决策/Journal commit 耗时；
- Live 与 Batch/Canonical 并行时的延迟退化；
- CPU、RSS、swap 和进程数。

目标设备按 Mac mini M4 / 16GB 设计；本变更不虚构尚未测得的硬延迟阈值。

## 9. 存储与 API

首期不新增策略数据库、统一 State 表、统一 Evaluation 表或账户账本。

- Static Registry 随代码发布；
- Profile/Policy 从原领域读取；
- Binding 从 capability、scope、portfolio registration 和 deployment 投影；
- Runtime Snapshot 从原领域 health/status/heartbeat 读取；
- Result/Evidence 通过原领域只读 API/repository 查询并保留 source reference。

建议提供只读资源：
- GET /api/v1/strategies
- GET /api/v1/strategies/{strategy_id}
- GET /api/v1/strategies/{strategy_id}/bindings
- GET /api/v1/strategies/{strategy_id}/runtime
- GET /api/v1/strategies/{strategy_id}/evidence

路由为目标合同建议，不代表当前已存在。实现时优先复用既有 typed service/API，不得在新 GET 中重新运行公式、构建历史 Run、推进水位、创建账户或读取可写仓储。

任一领域暂时不可用时，目录仍可返回；该领域运行状态应明确为 UNAVAILABLE/UNKNOWN，并带诊断来源，不得用缓存状态伪装当前 READY。

## 10. Web 工作台

策略中心按领域组织：

- Newow：趋势、震荡、主升浪、双策略融合；
- HTDY：60m 原始观察规则及其独立账户/执行状态；
- SuBing：16 品种共享资金 Paper 组合。

详情页统一提供概览、公式/政策版本、支持范围、运行状态、历史结果/证据五个区域，但内容由领域适配器提供，不强制统一业务表格。

Newow 展示 Action、Hint、ReferenceTrade；HTDY 展示 Signal、账户风险、委托/成交/恢复；SuBing 展示组合资金、决策、模型成交、权益和 Journal 状态。Alert 作为相关观察能力独立展示，不能合并成策略动作。

首期没有策略启停、参数写入、订单操作、通知操作、候选晋升或 Runtime promotion 按钮。

## 11. 生命周期与治理

生命周期、运行状态和证据状态相互独立：

- Lifecycle：ACTIVE / CANDIDATE / RETIRED / RESEARCH_ONLY；
- Runtime：保留各领域原始状态，统一展示时仅做有限映射；
- Evidence：NOT_AVAILABLE / RESEARCH_ONLY / VERIFIED / EVIDENCE_REQUIRED 等来源证据分类，具体优先复用已有合同。

候选策略需绑定公式、参数、输入、数据、运行和研究 Run 身份。OOS、Walk-forward、Shadow 各自提供独立证据。只有明确人工批准后才能更新正式策略/部署引用。

AI 可以读取和分析证据、提出候选；不能修改 active 公式、Profile、账户政策或自动晋升。

退役策略不再出现在当前活动目录；旧 Run、账本、事件、研究文件及 Git 历史按原身份只读审计，不迁移、不改写、不作为新策略的默认配置。

## 12. 实施阶段

1. **目录与只读合同：** 固定六个身份、类型、领域所有者、版本引用、能力和结果引用。
2. **Newow 只读适配：** 读取 capability、Profile/公式身份、ReferenceTrading 状态和结果；验证 Fusion 只消费基础结果。
3. **HTDY 只读适配：** 读取原始公式/政策身份、TQKQ health、账户和 Journal 状态；不修改 Controller。
4. **SuBing 只读适配：** 读取唯一 Portfolio registration、Run、heartbeat、Journal 和历史登记；不修改组合 Worker。
5. **工作台：** 实现按领域分组的目录、详情、运行与证据视图。
6. **性能和故障验收：** 验证有界读取、部分失败、资源隔离、领域状态一致性和并发负载。
7. **研究生命周期后续接入：** 在 Research Domain 已有明确 Run/validation 合同后，再接入候选、OOS、Walk-forward 和 Shadow 证据。

Market 与 Compute 的正式消费者接管、Runtime 状态恢复和自然运行验收仍由各自变更处理，不因 Strategy Center 页面完成而自动通过。

## 13. 明确不做

- 不新增中央 StrategyScheduler、StrategyStateManager 或通用策略 Worker。
- 不迁移 ReferenceTrading、TQKQ、PortfolioJournal。
- 不将三领域输出转换为统一 BUY/SELL/ORDER。
- 不自动扩大现有 operational Scope 或启用全部能力组合。
- 不将 HTDY repainting 公式包装成回测/正式 Live 策略。
- 不将 SuBing 16 个品种拆成独立账户。
- 不修改现有 active canonical、生产 DB、Runtime、通知、发布和账户。
