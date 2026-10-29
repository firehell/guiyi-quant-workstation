# 归一量化稳定产品面

更新时间：2026-10-29

归一量化是本地、单用户的国内期货研究工作站。稳定产品边界允许可信行情、Market Web、Newow 只读策略与参考交易、通用指标、HTDY/苏冰研究观察、Alert 与人工判断，以及独立 CLI 的 JM 本地 Paper 试点；当前不提供自动交易、实盘下单、Broker 账户管理、SaaS、多用户权限或 AI 自动晋升。所有图表、参考交易和通知都是研究观察，`auto_order=false`。Paper 模型订单、成交和账本不接入现有页面事实；合同见 [Paper 试点](docs/PAPER_PILOT.md)。具体代码、Release 与 Runtime 是否已经具备这些能力，仍以代码、测试和 `STATUS.md` 为准。

长期允许按人工 Gate 分阶段评估 `研究观察 → Paper → Shadow → Broker Read-only → 订单草稿 → 人工确认 → 半自动 → 受控自动`；这不是当前能力或晋升授权。AI 可自动研究，不能自动晋升、修改 active 策略或决定真实账户持仓。苏冰课程 Knowledge Foundation 属于独立 AutoTrade 项目，不在本仓库维护课程开发计划、代码、私有数据或 Runtime 依赖。

## Market Web

- Market 页面为 `/market` 与 `/market/chart`；独立历史研究入口为 `/research/new-subing`。
- Web 隐藏主连入口，仅保留真实主力及已有指定合约。旧 `series_kind=continuous` 链接在请求前迁移为真实主力，保留品种、视图与合法周期，清除旧合约及记录定位，替换地址并提示；旧显示偏好只迁移序列。不匹配当前序列的统计不展示。底层 continuous API、行情与内部研究能力保留。
- Market 首页分为市场与消息 Tab，以独立 bulk 只读资源展示 Runtime health、active completed D1/W1 generic overview、operational completed 1m 报价与 immutable Alert Events；浏览器不按品种请求、不重算指标或策略。人工点击品种或 Event 后进入 `/market/chart` 复核。
- 首页采用白色全宽卡片列表、期货板块本地筛选与涨跌幅表头三态排序；返回恢复成功快照、偏好与位置，必要更新在后台进行。分钟报价通过单个批量 WebSocket 更新，明确时间、来源与状态；较昨收涨跌幅只用同物理合约昨收。日周状态、量比、增仓率仍标明 completed-period 口径。趋势/震荡摘要、日周图标、目标/吸筹与展开后的普通参考收益来自版本化持久投影，首页交互不回放策略；源更新后预计算，缺失/失败保留明确状态。增仓率不能解释为做多。
- 消息 Tab 按规则、品种和交易日进行有界历史查询与稳定分页；原研究观察折叠入口移除。消息存在、尝试发送与实际收件不是同一事实，不提供删除、重发或 Scope 写入口。更多直接命名自由看盘，下拉使用统一 SVG 图标；日周未同向用独立分向图标，不表达空仓。
- 首页的红/橙/绿/蓝/灰图标仅表达冻结的 completed-period/数据状态，不表达策略、持仓、买卖建议、订单或交易结果。
- 通用 Research Overlay 仅 `none | htdy`；Newow 使用自身 typed API 和 Workspace 图层，不注册为通用 Overlay。SuBing 的正式 `S↑/S↓` marker 只来自 Event；专用页面另有独立历史参考标注，不注册为通用 Overlay。图表设置保留通用 EMA、MACD、Range Detector 与合约控制。
- Market 详情的已接受产品合同使用同一稳定工作台中的扁平导航入口：`震荡策略 / 趋势策略 / 双策略 / HTDY / SuBing / Free`；双策略是趋势与震荡的并列展示与独立单仓参考融合模式，不是第四套策略公式，主升浪仍保留独立策略身份和 URL/API。Newow 允许显示策略 `BUILD/HOLD/CLEAR/FLAT` 状态、主动作、Hint、ReferenceTrade 和明确标注的乐观参考摘要；主动作标签只连接服务端原始参考价坐标，不推导收益。旧 `view=trend` 页面链接显示一次迁移提示后规范化到 `view=newow&strategy=trend&series_kind=actual_dominant&frequency=1d`，`/api/v1/market/newow/trend-detail` 仍仅保留固定 D1 API 兼容语义。其他视角不得消费或复制这些 Newow 事实。
- 策略详情不显示模糊的“全历史策略效果”，不把账户收益、持仓、订单或成交混入参考交易，也不恢复已退役策略事件。首页独立 SimNow 监控可只读展示模拟账户事实；Newow 的固定统计窗口 ReferenceTrade 摘要是只读研究投影，与该账户事实分离。

## 期货双向策略独立研究

详情页显式 `strategy_model=futures_bidir_v1` 切换归一自有期货研究；未带参数的旧链接仍为牛哇原版。
趋势、震荡、双策略、主升浪及测试1～4名称不变，模型、公式、参考交易与10万元分层研究账户独立。
首轮JM/RB/AL/TA六周期，缺资金保留独立参考、缺行情/执行事实分别披露；周线test3无更高级别标不适用。
API只读SHA索引冻结结果，GET不回测、下载或写生产；页面明确历史截止而非当前账户持仓。
本能力不接入持续Paper、Scope、Runtime、通知或Broker；合同见[期货双向研究](docs/NEWOW_FUTURES_STRATEGY.md)。

## 新苏冰策略独立研究

修正版 `new_subing_v2` 使用独立[阶段/分层合同](docs/NEW_SUBING_STRATEGY_V2.md)，保留V1规则与结果。
10万元主结果及100万元诊断具有不同Profile；只读页面按版本与本金筛选，不能合并收益或从研究自行晋升。

`new_subing_v1` 是固定参数顺势波段研究版，规则与来源只由
[新苏冰合同](docs/NEW_SUBING_STRATEGY.md)定义。它采用 MA21、日线方向、5m/15m确认、
三项共振及统一净仓模型，首轮 AL/RB/TA 各自以10万元进行双向整数手历史研究。
CLI 经唯一 MarketDataService 读取冻结 Canonical；独立的有界 RQData collector 只采集成本与限价
证据，不修复或写行情。只读 Web/API 消费哈希绑定的研究结果，不启动回测或外部请求。
模型成交与账户收益独立于旧苏冰 Event、乐观参考、JM Paper 账本和真实账户。
缺口、未成交、换月中断、原案例未核验及 OOS 未证明均显式展示；不恢复旧研究或执行入口，
不启用 Runtime、通知、Shadow、Broker 或自动交易。发布与运行状态仍只看 `STATUS.md`。

## Newow 与参考交易

牛哇记录支持矩阵为 operational 60 品种 × 六周期（5m/15m/30m/60m/1d/1w）× 四策略（趋势、震荡、主升浪、独立双策略），共1440个支持组合。支持能力不自动创建、启用或扩展已保存Scope；实际持续记录范围、当前配置和自然验收只看 `STATUS.md` 及运行读回。历史资产由完成的 Canonical 重算；持续观察的四分钟周期来自实际捕获的 completed Live，日周来自 completed Canonical。动作、Hint与逐Bar状态独立保存，历史预热不算实际观察，不创建账户事实或发送通知。

- 本节冻结允许实现的稳定产品合同，不声明 Newow 三策略 × 六周期、ReferenceTrade 或新 Workspace 已发布、已部署或通过生产验收。
- 公共 `ReferenceTrading` canonical 已冻结两种不可混淆的记录口径：`historical_replay` 是可从固定 Canonical 输入和版本重建的研究投影；`forward_observation` 只记录明确启用后实际观察的 completed 输入，默认 FLAT 起点。统一域提供纯 contracts/reducer、checkpoint、历史 plan/build/resume/rebuild、前向 capture/recovery、仓储及 HTTP/Web 查询。worker 与消费者切换受显式启用约束；代码存在不代表生产 migration/bootstrap 或 Runtime 已启用，阶段事实只见 `STATUS.md`；详见 `openspec/specs/reference-trading/spec.md`。
- Newow 主产品范围为趋势、震荡、主升浪 × `5m/15m/30m/60m/1d/1w` 十八个独立组合；历史页面与研究计算只消费 completed Canonical `actual_dominant`，并继续通过 `MarketDataService`、Catalog 与 `MainContractMap` 取得行情和物理 owner。浏览器不聚合周期、不重算公式、不配对交易。
- Newow 详情采用局部白色全宽 Shell、单层策略入口、唯一周期入口、原位展开解释与原生弹窗；K 线、成交量和单一副图共享时间轴。同品种同周期切换 Newow 策略时只替换策略所属图层，加载态清空旧事实但保留兼容窗口元数据，并仅在新时间轴完全兼容时恢复缩放；身份或时间轴不兼容时清空旧图层并重置。默认 MACD 为既有内核的只读显示（12/26/9、sma_window、histogram×2），不声明牛哇 MACD 原站 parity；其他副图替换同一 pane。
- 日线收盘报价通过有界 `actual_dominant + 1d + limit=2` 独立读取并标记时间/非实时。参考记录随文档纵向滚动，首次可见读取一次、cursor 手动加载更多；解释和独立比较器按需读取。长身份/原始时间仍可在来源和详情中查询，缺失或不兼容证据不填示例值。
- 主动作只有各策略自己的 `BUILD/CLEAR`；J、D1–D6、4/7/11、阶段、风险和结构信息是 `quantity_effect=none` 的 Hint。无主动作是有效策略结果，不能与 `EVIDENCE_REQUIRED`、`NOT_APPLICABLE` 或照妖镜重绘混写成“无信号”。
- 主升浪完整物理 owner 生命周期从黄带开始、此前无真实或 warm-up BUILD、首次黄转蓝时，允许输出经 reader lifecycle evidence 证明的 `CLEAR + INITIAL_CLEAR_NO_ENTRY`。页面标为“清仓（无入场）”，不制造 BUILD、ReferenceTrade、零收益、订单或账户事实；裁剪窗口与分页不承担生命周期证明。
- ReferenceTrade 是可从固定输入与版本重算的只读投影，不是 Position、Order、Account、Execution、Fill 或 AlertEvent。趋势使用慢线 B、震荡使用 BUILD Low/CLEAR High、主升浪使用 MA45 作为语义参考价；价格与收益使用 Decimal，零手续费、零滑点，不推断手数、资金或真实可成交性。
- 未清仓记录保持 `OPEN`；主力区段结束但没有 CLEAR 时为 `ROLLOVER_INTERRUPTED`，只使用旧物理合约、旧区段、同周期最后 completed Close 单列参考浮动，不伪造 CLEAR、不跨合约或跨频补价、不计入 CLOSED 统计。
- 多周期解释必须携带各输入周期 `bar_end` 与快照 `as_of`，不能用未来完成的周线回填历史 60m 决策。`display_window` 与显式 `performance_since/performance_through` 相互独立；缩放或分页不改变参考交易身份与统计。
- 五窗口页面比较器保持独立页面身份；其同 Bar Close、样本末理论平仓或参数排名不能写入三策略 ReferenceTrade、主动作或正式图表参数。照妖镜保持 `repainting=true / formal_signal_eligible=false`，只供回看，不进入交易、收益或历史当时可知事实。
- 证据状态与策略结果分离为 `ACTIVE_CODE_VERIFIED / RESEARCH_EVIDENCE_ONLY / EVIDENCE_REQUIRED / OUT_OF_SCOPE`。缺精确证据的功能 fail-closed；现有 D1 兼容入口、其他已验证能力和 HTDY/SuBing/Free 不因此改写。

Newow 提供显式历史快照入口：当前数据缺失时可主动选择已验证完整的历史主图与照妖镜，持续显示截止时间并可返回当前；其他面板独立报告证据或数据不足。历史快照不代表当日输入恢复。

### 分阶段开放边界

分钟 Newow 产品周期为 `5m/15m/30m/60m`，使用同物理合约 Canonical 1m 独立聚合。
正式开放以capability的品种、周期与section为边界；v35六周期页面使用当前已发布completed Canonical截止，
显式历史as_of仍受快照身份校验，旧v31/v32固定截止证据保持原身份；页面明确来源与时间。
持续记录不由历史验收或源码发布自动启用，现场配置与验收见 `STATUS.md`。
1m仅承担行情事实和聚合输入，Newow的1m页面与策略产品后续单独版本处理；保留通用Market的1m能力。
RB四周期趋势、震荡及独立双策略是早期分阶段验收范围；当前开放与验收状态见 `STATUS.md`。

十八组合为当前代码支持面，不表示所有品种、窗口与面板均通过生产数据或Runtime验收。
日线、日周、60m和短分钟为历史分阶段交付顺序；当前支持范围以v35能力合同为准。
同周期主图、主动作/状态、选定副图和ReferenceTrade按各自输入独立验收；依赖未开放周期的
完整综合解释继续明确不可用。`decision_v2`及路径仍只接受1d/1w/60m，不将短分钟替换成60m。
旧链接、偏好和API必须与能力合同一致；不改变HTDY/SuBing/Free、通用分钟链路或正式运行配置。

缺少 60m 输入不能通过沿用原综合总分、补默认值或创造日周简化评分解决。跨周期能力恢复时仍须
按各周期 completed Bar、`bar_end` 与 `as_of` 验证；数据已下载/派生不等于产品已开放。
新版综合评分、公式、参考价格和推送不随日周恢复或 60m 开放自动变更。

实际分阶段开放由 `GET /api/v1/market/newow/product-capabilities` 作为 Web 与 typed API 的共同 authority；
当前 `newow_product_capabilities_v35` 使用 `daily_weekly_intraday_current`，对operational 60品种
声明趋势、震荡、主升浪及独立双策略的六周期支持；页面使用当前completed Canonical截止。
旧v31/v32历史截止、v33与v34候选wire保持冻结；不把旧合同限制用于当前v35，也不改写历史证据。
1m仅作为聚合输入。完整 `explanation` section仍显式未开放；独立 `decision_v2` 与分析入口
按各自合同读取已完成输入，不能据此声称所有解释面板均已开放。
旧 `/trend-detail` 固定 D1 兼容合同不变；当前发布身份、配置和自然运行验收仍只看 `STATUS.md` 与真实 evidence。

## 指标

- EMA、MACD、ATR 与 Range Detector 是通用指标，不拥有策略、下单或 Alert 语义。
- EMA21 斜率只保留 10K primitive：输入恰好 10 个 EMA21 值，以首尾差除以 9 个 bar interval，再除以当前 EMA21，输出 bps/bar。
- 不保留 Daily Watch 大方向过滤，也不保留 5m/15m 正式因子。
- Range Detector 只允许 `range_detector_readonly_display`，不能作为正式策略、Alert 或 Runtime 输入。

## HTDY 与 Alert

HTDY 60m 固定一手双向执行规则已有独立离线状态机及显式输入适配器，合同见
[HTDY_SIMNOW_V1](docs/HTDY_SIMNOW_V1.md)。它不接入现役 Alert/Runtime，提供独立离线账户风控、资金预留与本地命令journal，另有显式受控SimNow请求适配模块（见[订单适配](docs/SIMNOW_EXECUTION.md)），提供显式有界的一次性CLI、原生对账和费用投影。独立持续宿主另有 observe/manage/trade 实现及服务安装入口；当前启用模式与账户验收只看 `STATUS.md`，已有代码不等于允许开启交易。
它不代表持续 Paper、策略晋升或自动交易已启用；以下观察与参考口径保持独立。

HTDY 是 observation-only/repainting 产品，能力覆盖七个正式周期 `1m/5m/15m/30m/60m/1d/1w`。稳定 Rule code 为 `htdy_original_15m`，唯一 Scope authority 是 `scope_product_frequencies` 的 symbol × frequency。

HTDY 当前实时运行与页面实时记录统一为 operational 60 品种 × `60m`；其他周期保留历史研究图表和通用审计查询能力，不自动启用。旧 Event 与发送事实保留，不补发、不转换周期。实时参考交易流须独立建立，不能由 AlertEvent 或查询能力推断其存在。

HTDY 60m 实时参考采用 `htdy_first_seen_reverse_close_v1`：buy 开多、sell 开空，反向平旧开新、同向不加仓，
以 completed Bar close 计算零手续费/滑点的页面参考收益。它独立于 AlertEvent 和 Broker Fill；从精确启用起点空仓记录，
不回填旧信号交易。模型接受与原子启用合同见 [ReferenceTrading](openspec/specs/reference-trading/spec.md)，实际运行与自然验收看 `STATUS.md`。

持久 HTDY `AlertEvent` 是 forward-only first-seen 事实，只接受触发窗口的最新 completed Bar。repaint zone 中的历史 Bar 只供 Web retrospective 研究展示，不创建 Event 或通知。Event 创建后不可变，不因后续重绘消失、重现或方向变化而改写或重发。

苏冰预警是新的 observation-only 产品，身份固定为 `subing_ths_alert_15m_v1`，公式身份按六周期独立版本管理（15m 保持 `subing_ths_15m_v3`）。它消费 operational Scope 内的 completed actual_dominant 5m/15m/30m/60m/1d/1w，并按 MACD(12,26,9) exact CROSS 与 `EMA(CLOSE, 21)` 判定多头/空头预警；EMA 使用 `sma_window` seed。v3 不改变数学公式，只冻结 RQData 首分钟 session 锚点修正后的正式 Bar、时间与 Candidate。warm-up 与递归状态只在同一物理主力合约内延续，换月重新构建。零轴、Range、量能/OI、ATR、EMA 斜率与多周期共振都不是 V1 Gate。

苏冰六周期均静默记录，不推送。每个新 Event 原子关联 `subing_ema21_alignment_v1` 六周期 EMA21 方向快照，保留 PASS/FAIL/UNKNOWN；快照只用于研究筛选，不改变原公式信号。1m 不参与；旧 Event 不补写快照。

苏冰持久 Event 使用 `exact` identity：同一 Rule、symbol、frequency、bar_end 的事实完全一致才幂等，冲突 fail-closed。正式预警 Web 和通知只消费 Event，不复制公式；Event-backed `S↑/S↓` 不拥有 Overlay 或订单语义。

苏冰历史参考复用同一公式 Kernel，从 Canonical 同物理合约生命周期预热，仅在 rank1 有效区间生成历史参考信号；15m 沿用 `subing_ths_15m_v3`，30m/60m/1d 使用各自版本身份、历史参考与六周期正式 Event 独立。它不创建或补发 AlertEvent。15m/30m/60m 参考模型保持 `subing_reference_reverse_close_v1`；D1 候选合同使用 `subing_reference_reverse_close_quality_segment_v2`，只接受 Market Fact 权威的有效 Bar 与 typed quality break，每个 break 后重新预热，质量中断单列为 `DATA_INTERRUPTED`，不制造退出价、收益或当前浮动。第 1–33 根有效日线为预热，第 34 根指标已就绪但不可评价 exact CROSS，第 35 根起才可评价。公式仍为 `subing_ths_1d_v1`。历史资产独立标注“历史重算·乐观参考”，不是牛哇公式一致性、因果回测或账户收益；`executable=false`、`auto_order=false`。收益统计按显式交易日窗口固定，简单相加以百分点展示，不随缩放或分页变化。

苏冰与 HTDY 详情收益区仅消费 `forward_observation` 实时留存参考交易：共用曲线、快捷窗口、最近三笔卡片、按需分页及有界快照缓存；不在该区展示历史重算或 HTDY 重绘交易。缺失实时流时明确不可用，实际 AlertEvent 审计独立折叠，不以预警条数推算完整交易收益。历史研究 API 和资产仍独立保留，不改写已有事实。合同见 [Reference Trading](openspec/specs/reference-trading/spec.md#requirement-retained-forward-reference-performance-panel)。

Alert 是独立 Application Domain。0043 删除旧策略 Rule/Event 与专用列，0044 只增加 disabled + empty-scope 的新 SuBing Rule，0045 只规范化 RQData session 排他起点。HTDY 使用 `first_seen`，SuBing 使用 `exact`；两者均先提交 Event，随后最多一次 transport，无 retry、queue、replay、backfill、fallback 或订单路径。provider accepted 不等于送达。通用 Scope 写入拒绝 disabled Rule；首次 SuBing Scope/enable 只走专用原子 seam，且要求精确 0045，真实 apply 仍是外部 Gate。

## 数据与稳定入口

```text
RQData -> staging + hard validation -> Canonical Parquet
       -> 八表 Catalog + MainContractMap -> MarketDataService
       -> Market Web / indicators / HTDY + SuBing observation
```

- RQData 是唯一外部行情事实源，Canonical Parquet 是唯一 active Historical Bar 存储，PostgreSQL 不存 Bar。
- RQData `1m` session 首根时间是首根 `bar_end`；adapter 必须先减一分钟，将其规范化为统一 `(start, end]` 的排他 start。Canonical 仍只有一个 V2 当前事实，不并行创建 data-version。
- `active_products.txt` 定义研究能力；`operational_products.txt` 定义持续 Runtime 授权。即使内容相同也不合并。
- 物理 Dataset 只有 `continuous` 与 `contract`；`actual_dominant` 只通过 `MainContractMap rank=1` 有效区间拼接。
- `MarketDataService` 是 Historical consumer 的唯一入口；Redis Live 只承载当日 observation，不能提升为 Canonical。
- 同物理 contract 的上市有效期内真实 warm-up Bar 可与 rank1 required Bar 共存；它不改变 actual-dominant owner，且任何越界/非 session Bar 都 fail-closed。唯一维护入口是 hash-locked `data contract-warmup`：dry-run 只读，真实 RQData/Canonical apply 必须在 `AGENTS.md` 定义的交办范围内；数据补全或历史候选闭环无需逐批人工批准，由执行者冻结并校验 exact plan hash。

稳定 HTTP 面为 `/api/v1/market/*`、`/api/alerts/*`、只读 `/api/runtime/*`、`/api/v1/reference-trading/*`、`/api/simnow/monitor/*` 及独立只读 `/api/v1/research/new-subing/*`、`/api/v1/research/newow-futures/*`。
统一 CLI 为 `uv run --project services/quant-api guiyi`，active domain 为 `data`、`runtime`、`reference` 与 `home`。`reference` 提供精确计划及 build/advance/rebuild/resume，`home build` 显式构建首页派生投影；写入边界仍遵守各自合同。新苏冰离线研究使用上文专用脚本，不恢复退役研究产品。

## Retired surface

全部既有策略域（包括 `subing_strategy_v1` 及其 Daily Watch、5m/15m 因子、Historical Projection、Current State、Formal Event、Runtime、Scope、CLI、API、Web 和派生 cache）均退出 active 产品面。新 SuBing Alert 是新身份、新合同和新版本，不恢复或复用旧策略实现。旧身份只允许存在于不可变 Git/Alembic lineage、0043 删除迁移的断言和 `STATUS.md` 的真实未迁移生产事实中。

Attention、Trend Focus、Main Force Mirror、Five-Candidate phase assets、N Structure、Multi-Candidate Robustness、RQAlpha 与 Execution Review 同样不属于 active 产品、API、CLI、Web 或 Runtime。

## SimNow 独立账户观察与监控

独立交互式CLI支持固定SimNow测试环境及显式选择的第一套模拟环境认证、登录与资金/持仓/委托/成交两轮只读核验。
该一次性只读CLI不创建订单、管理账户或启动持续服务，本地快照与HTDY执行政策、Paper模型、页面参考收益保持独立。合同见 [SIMNOW_READONLY](docs/SIMNOW_READONLY.md)。

独立持续宿主与一次性CLI分开：observe按现有合同读取柜台账户并核验本地账本，manage/trade有独立执行边界；支持隔离服务安装、连接预算、持久阻断和只读监控。当前部署及待验收事实只看 `STATUS.md`，不从实现或observe运行推导交易开放，`auto_order=false`保持。

首页导航增加“模拟交易”：只读展示本地原生账户走势、持仓、执行链与待核事项，不提供交易操作。账户口径独立于策略参考收益，未接入或证据不足时明确待验。详见 [SimNow执行合同](docs/SIMNOW_EXECUTION.md)。
