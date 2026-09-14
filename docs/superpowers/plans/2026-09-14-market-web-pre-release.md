# AU/JM 发布前十一项问题统一修改方案

> **For agentic workers:** 使用 `superpowers:executing-plans` 在一个 `gpt-5.6-sol / high` 会话中顺序实施；不拆成多个开发会话。各批次按复现、失败测试、最小实现、回归、Review、提交推进，以 checkbox 记录完成证据。

**Goal:** 完成本轮指定的 11 项功能、性能、展示和状态文档收尾，再形成统一发布候选验收结论；本计划不授权发布或切换 Runtime。

**Architecture:** 保持唯一 MarketDataService 历史入口、现有 Newow/SuBing 服务及共享前端展示层。数据不足与实现错误分开处理；显示格式/布局不得改变源值、时间身份、Marker、ReferenceTrade 或公式。优先修复可用性与错误边界，再统一展示，最后真实页面验收。

**Tech Stack:** 既有 Python/FastAPI/SQLAlchemy、Canonical/Catalog、Vue/TypeScript、lightweight-charts、pytest、Node test、Playwright；不为此新增运行时依赖。

**Spec:** 本文为单一设计与执行方案。领域依据：`AGENTS.md`、`docs/DATA_CENTER.md`、`PROJECT_SOURCE.md`、`DECISIONS.md`、`openspec/specs/market-series-query/spec.md`、`openspec/specs/market-home-overview/spec.md`、`openspec/specs/newow-product-reference-trading/spec.md`、`openspec/specs/subing-ths-alert/spec.md`。命令统一维护在 `TESTING.md`。

## 一、基线与授权

设计基线为 develop `b823fc9cc4b6c6182e753a70f60f4b29e6f90d8c`；其中已包含首页修复 `54004dea247c90a0238b19f4dab41b2e6432160c`，后续合入 ordinary campaign 的部分执行及 source blocker 文档。进入开发时必须重新核对 develop 依赖及其他 worktree 的变更，不把此前的数据缺口视为仍然存在的当前事实。

本轮设计已核对的现状：

- 首页请求内日历复用、独立目录、五分钟缓存和 60 秒恢复已实现，禁止重复造一套缓存。真实只读计算约 11–12 秒；同事务基线约 50 秒、响应一致。尚不是候选 HTTP 的验收结果。
- `market_subing_reference.py` 会将多类 MarketDataError/ValueError 汇总成 `SUBING_REFERENCE_DATA_UNAVAILABLE`。15m 参考链另有完整交易日、Session、owner segment、真实合约 endpoints 和 physical/actual parity 检查。
- `NewowProductQuery` 要求小写；`public_product_error` 已有 INVALID→422 分类，但上游入口和 service/cache 的身份顺序仍须核查，不能认定只改错误码即修好。
- `ProductSelector` 选择后 close 再 focus，与 `@focus=show` 构成重新打开路径。
- `useSubingAlertFacts.ts` 的有效 Rule 文案硬编码“状态不可判定”；`marketDetailViewModel.ts` 的“5日涨跌”固定为横线。
- `formatMarketDecimal` 仅去尾零；Newow `formatDecimalString` 默认保留全部小数，指定小数位时仅截断；不存在已经完善的统一舍入显示合同。
- `referenceCalloutLayout.ts` 按固定 134×46 估算，compact 展开后尺寸和边界未重新布局；Newow 覆盖层使用 overflow:hidden。
- STATUS 顶部仍写 v1.10.9，先前 API 曾读到 v1.10.10；本轮尚未重新核验全套 release/promotion receipt。

本轮允许：方案内源码、隔离测试、只读诊断、当前状态文档、必要 canonical 更新、普通 commit/push 和满足条件的 develop 集成。用户明确要求设计后交给一个 Sol high 会话开发，无须在每个批次重新请求同一开发授权。

不授权：真实 RQData 下载/重试，Canonical 或生产 DB/Redis 写入，Scope/Rule/通知修改，main/tag/release，启用投影或切换 Runtime，真实交易。若某项只有数据补齐才能恢复，输出精确缺口与单独 Gate，继续其余批次；不可把诊断完成当作该功能已恢复。

## 二、顺序与需求映射

| 顺序 | 对应用户编号 | 独立交付物 |
|---|---|---|
| A | 10 的身份核验；全部基线 | 固定开发/Runtime 身份、当前复现矩阵，状态证据不足明确保留 |
| B | 1、2 | 苏冰失败根因和可修代码；API 大小写/非法输入边界 |
| C | 3 | 首页实际 HTTP 性能和恢复闭环，按测量决定进一步优化 |
| D | 4、5、8 | 选择器不重开；苏冰状态分层；移除详情伪占位 |
| E | 6、7 | 统一 Decimal 展示、北京时间与中文事实解释 |
| F | 9 | weekly partial 的可解释状态和完整区间操作 |
| G | 11 | 三视图参考动作标签可读、不裁切、可定位 |
| H | 10 的状态更新；全部 | 当前 STATUS、完整 AU/JM 验收、Review 与 develop 集成 |

每批只在其验收通过后标完成，不使用汇总 green 覆盖某一项真实数据或浏览器阻塞。

## 三、逐项设计与修改点

### A / 用户 10：先校准身份，最后更新发布事实

文件：`STATUS.md`、`deploy/README.md`、现有 release/promotion evidence；不修改已发布 Runtime 内的文件。

- [ ] 用只读方式记录当前 branch/HEAD/worktree/dirty、develop 是否包含 `54004dea2`，API/Web 版本、实际启动目录/commit、exact tag、release 和 promotion receipt、六服务身份。
- [ ] API version 只证明该 API 所报身份；tag、服务启动、自然闭环分别列证据，不推断 `RUNTIME_READY`。日期和核验时点进入记录。
- [ ] 对无法核验的 release 或 Runtime 事实明确写“未核验”；若已知旧断言错误，不能继续保留为当前真值，也不能猜测目标版本。既有批准和自然证据只归属其 exact version。
- [ ] H 批次根据本轮实际证据更新 STATUS 的当前事实和 pending Gate，保留必要历史。将“工程完成”“已发布”“已切换”“自然验收”分开，不修改 immutable tag。

验收：文档可追溯到实际读回，顶部、阶段表与正文一致；工程 canonical consistency、引用、OpenSpec 和 secret scan 通过。若缺 receipt，状态正确表达未知即可完成文档修正，但不能宣布发布 Gate 已通过。

### B1 / 用户 1：焦煤苏冰历史参考独立诊断与修复

主要文件：

- `services/quant-api/app/api/market_subing_reference.py`
- `services/quant-api/app/market_data/subing_reference.py`
- `services/quant-api/app/market_data/actual_dominant_research.py`
- `services/quant-api/app/market_data/market_data_service.py`（仅证据指向共享读取错误时）
- `services/quant-api/app/schemas/subing_reference.py`
- `apps/quant-web/src/composables/useSubingReference.ts`、`src/utils/subingReference.ts`、`src/components/market/detail/subing/SubingReferencePanel.vue`
- 测试：`test_subing_reference_service.py`、`test_subing_reference_api.py`、`test_subing_reference_projection.py`、`apps/quant-web/tests/subingReference.test.ts`、`e2e/subing-reference.spec.mjs`。

- [ ] 固定 AU/JM 的相同 since/through/as_of，实际只读复现。逐层定位 `_window → completed_trading_days/Session → SegmentLoader → _inputs → expected_contract_replay_endpoints → physical/actual parity → project_reference`，记录首个失败阶段、symbol、physical contract、frequency、起止交易日、预期/实际端点数量、有限原因码。
- [ ] 不只看返回的泛化 409；独立诊断进程捕获原始异常类型及允许公开的 code/reason，不记录凭据、SQL、内部路径或原始异常文本。当前缺口是否与牛哇有关必须由输入身份证明，不能直接套用 JM2305/32 根周线结论。
- [ ] 若是 reader/边界/异常分类错误，先用最小真实隔离 fixture 复现，再修窄责任模块；保持 completed-only、严格真实合约、换月中断、因果时序、原公式和收益口径。
- [ ] 错误展示保留兼容的顶层 `SUBING_REFERENCE_DATA_UNAVAILABLE`，必要时增加有限白名单 diagnostic：阶段、原因与安全上下文；前端正常解释已知原因，旧无 diagnostic 响应仍可显示通用错误。错误身份冲突仍为 conflict，预算不足/busy 仍单独分类。程序错误不得统称为数据缺失。
- [ ] 若确定是真实数据缺失，不缩窗、不跨频回退、不丢掉失败 segment，也不自动补数。输出最小数据修复对象及需单独批准的范围；该功能保留 `EXTERNAL_GATE_PENDING`，继续 C–H。

验收：AU 正常案例不回归；JM 成功则实际返回可复核参考，失败则定位到明确当前原因。测试覆盖缺 Calendar/Session、缺主力映射、端点缺失、physical/actual 冲突、无交易的合法空结果、预算/并发限制、分页快照变化及错误脱敏。真实数据未恢复时，不勾选“JM 页面已恢复”。

### B2 / 用户 2：Newow 大写品种入口规范化

主要文件：`services/quant-api/app/api/market_newow.py`、`app/market_data/newow/product_query.py`、`product_service.py`、`public_errors.py`；测试 `tests/newow/test_market_newow_product_api.py`、`test_product_contracts.py`、`test_product_inflight.py`、`test_product_snapshot_cache.py`。

设计决定：HTTP 品种路径接受 ASCII 大小写并在公共入口规范成小写，先于 active-universe 检查、query 构造、缓存键和 in-flight 身份。内部 query 继续小写严格合同。不要在各个 endpoint 散落 `.lower()`；复用现有边界 helper，无合适 helper 时只新增一个窄的公共解析入口。

- [ ] 先复现 AU/JM × trend/oscillation/main_rise 的六个大写 chart 请求；核查 chart/reference/auxiliary/历史快照共享入口。
- [ ] 构造参数化回归：`AU/au → au`、`JM/jm → jm`；非法空白、数字混入、Unicode 混淆输入明确 422，不变成 500。unknown/retired product 保留项目既有有限错误合同，不统一伪造成功。
- [ ] 大小写请求共享同一 canonical identity、缓存和去重；query/cursor 校验仍严格。真实小写请求的数据不足在大写请求中保持同类 409，而不是要求所有请求一律 200。
- [ ] 公共错误分类只接受有限已知代码，未知内部异常仍安全 500；不通过宽泛吞掉异常来制造成功。

验收：六组合大小写状态和规范化 identity 一致；成功 payload 除请求外壳外一致；不存在内部 500、缓存重复身份或游标错误放行。

### C / 用户 3：首页性能与真实 HTTP 验收

文件：`app/market_data/market_home_overview.py`、`market_home_projection.py`、`market_data_service.py`、必要时 `catalog.py`；Web `useMarketHome.ts`、首页及已有首页测试；依据现有 `outputs/market-home-latency-20260914/` 证据。

- [ ] 新基线保持 60 个品种与相同目标日，分别标识 projection hit/miss；测 identity、D1、W1、Catalog/SQL、分区读取、序列化和实际 HTTP。候选只用隔离本地端口、候选代码和只读数据连接，不重启生产服务。
- [ ] “冷启动”指新的候选进程/连接池；不清系统/生产缓存。测首次、连续三次、两个并发只读请求，以及浏览器硬刷新、SPA 返回、前后台切换。避免同时跑重型测试污染基线。
- [ ] 验证请求失败→保留可解释快照→自动恢复，行情失败时目录及消息筛选仍可用；失败注入使用 fixture，真实页面另行验证，报告不得混同。
- [ ] 若慢点仍来自 Catalog 往返，优先在单次读取内复用品种交易所等相同事实，或在既有 Catalog 接口内做有明确日期边界的批量读取；若来自文件读取，先量化重复，再考虑本次读取内去重。保持全量 60 品种、原窗口、完整性检查和逐值响应；新增优化前先做结果/异常一致性回归，不直接并发 60 份 DB 读取。
- [ ] 不提高 30 秒超时，不创建跨请求永久日历缓存，不自动启用 `.derived` 投影或 activation marker。若进一步优化收益不足，说明测量、残余成本和为何停止，而不是无限扩成架构重写。

验收口径：以真实 HTTP 冷/热均低于 10 秒为优化目标；该值尚未由旧证据证明。至少全部受测请求在 30 秒内成功、响应/分母一致、目录不等待 overview、恢复闭环成立。若仅满足 30 秒但未达 10 秒，保留性能目标未达记录，不自行宣称全部发布验收通过；继续完成其余项后交付明确剩余决策。投影命中低于 200ms 是独立路径，仅已有合法投影时测，不为验收写生产投影。

### D1 / 用户 4：品种选择后的焦点与弹层

文件：`apps/quant-web/src/components/market/ProductSelector.vue`、`tests/productSelector.test.ts`，首页/详情 E2E。

设计：选择后保留键盘焦点但不重新打开弹层；Esc、外部点击和用户主动再次 focus/open 区分。可用一次性的程序性 focus 抑制或正确的关闭/恢复焦点路径，禁止全局移除键盘访问，也不用任意延时掩盖竞态。

- [ ] 在真实组件复现点击选择→路由切换→弹层重开；补 Enter、Esc、Tab 和鼠标回归。
- [ ] 只改选择器焦点职责；一次选择只触发一次 select，保持输入可再次打开和搜索。
- [ ] AU→JM→AU 在首页及详情各走一遍，下一次页面点击不被残留遮罩截获。

验收示例：选择焦煤后 listbox 隐藏、路由为 jm、焦点位置合理；随后主动键盘/鼠标打开仍可选择黄金。

### D2 / 用户 5：苏冰状态按事实分层

文件：`useSubingAlertFacts.ts`、`SubingDetailWorkspace.vue`、现有 alerts/runtime types 与 view model；测试 `useSubingAlertFacts.test.ts` 和苏冰 E2E。

设计：将拼接长字符串改为页面所需的结构化展示模型，复用现有 typed response，明确四项：

1. 观察范围：当前品种 15m 是否启用；
2. Rule/Runtime：运行、停止、不可用、错误，说明它的全局/Rule 范围；
3. 最近评价：展示服务实际提供的时间与范围；无品种级时间时不能贴成“该品种最近已评价”；
4. 当前品种事件：只使用该 symbol × rule × frequency 的持久 Event。无 Event 为“当前范围暂无事件”，不能推成中性或系统故障。

- [ ] 删除无条件“状态不可判定”总括语。无策略状态事实时清楚写“未提供当前策略状态”，不从运行正常推导持仓、买卖或方向。
- [ ] 保留 symbol/frequency 校验、旧请求隔离、每一事实的失败状态；全局健康不能覆盖某资源不可用。
- [ ] 测试已启用且正常、禁用、未评价、Rule 错误、Runtime 错误、无当前品种 Event、有 Event、切品种晚响应。

验收：页面正常运行不呈现故障式总括状态；跨品种事件/全局时间不冒充 JM 当前事实，无新增通知或交易语义。

### D3 / 用户 8：删除详情“5日涨跌”固定占位

文件：`marketDetailViewModel.ts`、`tests/marketDetailViewModel.test.ts`、详情 E2E。

本轮选择移除该行。当前可用 `price_change_5d` 属于首页快照合同，详情支持 actual_dominant、continuous、contract 和不同截止时间；不能为了填一行另读首页全量快照或套用不匹配序列的数值。

- [ ] 删除固定 `{ label: '5日涨跌', value: '—' }`，保留其余已有真实来源的行情扩展项。
- [ ] 测试三种序列均无伪占位；确认首页自身的真实 5 日字段及统计不受影响。

验收：不存在“未实现功能伪装成数据缺失”的字段；本轮不新建研究指标/API，不修改收益计算。

### E / 用户 6、7：统一显示精度、时间与术语

主要文件：`src/utils/marketDisplay.ts`、`barTime.ts`、`productDirectory.ts`、`newowDetailPresentation.ts`、`newowProductViewModel.ts`、`subingReference.ts`、Newow/SuBing ReferencePanel/ChartStage/Workspace 及现有 callout builder；测试 `marketDisplay.test.ts`、`barTime.test.ts`、`newowReferencePanel.test.ts`、`subingReference.test.ts` 和对应图表测试。

**数值规则**：

- 普通报价有权威 tick/精度元数据时沿用既有格式；没有元数据时不猜交易所 tick。
- 计算型参考价格默认最多 4 位小数、去多余尾零；收益率、胜率、浮动和百分点合计最多 2 位小数，采用 Decimal 字符串十进制四舍五入，`-0` 规范为 `0`。极小非零百分比可显示 `<0.01%`/`>-0.01%`，详细原值可查看。
- 明确字段单位：ratio 需乘 100，`*_pct` 已是百分数，`*_percentage_points` 标“百分点”；严禁统一乘 100 或把合计当复利账户收益。
- 精确原值留在数据模型、身份、详情/复制数据属性；格式化返回字符串，不将展示值回写 API、图表坐标或参考计算。参考价格不是可执行成交价，不按 tick 舍入改数。
- 在既有 `marketDisplay` 扩展窄的 display helper；避免让全站所有调用无区别改变。先盘点已有两套 helper 的调用者，统一这次涉及的展示用途，不顺手重构无关模块。

**时间与术语规则**：

- 所有用户可见事件、评价、参考动作时间使用 `Asia/Shanghai` 并明确北京时间；日期字段是交易日的保留日期语义，不把日期当 UTC instant 转换。
- 跨年记录带年份；聚焦/匹配/API 参数/稳定 ID 仍使用原 ISO 字符串。
- 复用 `productSectorLabel`、现有 action/reason registry 和 `barTime/marketDisplay`。将 Performance window、reference cutoff、warming、OWNER_BOUNDARY、NEWOW_ESCAPE_D2 等已知键映射为中文解释；未知码显示“原因未识别”并在技术详情保留原码，不编造含义。

- [ ] 先建立手算例子：`449.320000000000000000 → 449.32`；`911.3633333333333 → 911.3633`；`66.66666666666666666666666667 → 66.67%`；`0.123456 ratio → 12.35%`；`2026-09-14T07:00:00Z → 2026-09-14 15:00 北京时间`。
- [ ] 覆盖负数、进位、超大整数、科学记数表示、null、非法值、负零、极小值；不使用 Number 处理高精度 Decimal 源串。
- [ ] 先统一表格/统计卡/事件运行信息，再统一图表 callout 文案，为 G 的尺寸布局提供最终文本。
- [ ] 以 AU/JM 三策略及苏冰参考核对原始 payload 数值/ID 不变；中文、北京时间和可展开技术信息贯穿各入口。

验收：主阅读区域无原始长尾数字、无无解释的内部码；UTC 与日期语义正确；测试包含 raw 值不变和 ratio/pct/percentage points 区分。

### F / 用户 9：weekly partial 解释与完整区间操作

文件：`NewowReferencePanel.vue`、`newowProductViewModel.ts`、`newowDetailPresentation.ts`；确实缺少权威边界时再修改既有 reference response builder/schema 与 `newow-product-reference-trading` canonical，禁止前端根据“上周五”猜测。

设计：并列呈现“用户选择统计区间”“参考计算截止”“实际完整可用截止”和“当前参考状态”。partial/warming 不等同于历史表格全部无效。

- [ ] 建立状态到原因的有限映射：本周未完成、owner 边界、预热不足、输入缺失各自解释；已有可信历史交易保留，其当前 OPEN/浮动状态不能借历史成功冒充可用。
- [ ] 增加“使用最近完整统计区间”操作，仅在后端已有精确、可验证的 completed-period 截止值时可用；点击后清楚展示将修改的截止，沿现有 reload 提交，并以新响应确认成功。
- [ ] `actual_available_through` 不自动等于完整周截止。开发者须核对字段合同；缺少精确截止时由现有服务复用 Calendar/Session/completed-boundary resolver 提供可选字段，明确其是否仅证明周边界，而非保证所有历史输入齐备。
- [ ] 不静默修改默认区间、不自动去掉未完成期间；不把“最近可用历史快照”当成修复参考窗口按钮；无完整边界时给出明确原因而非可点击空操作。
- [ ] 测试周一、节假日短周、跨年、完整边界但历史缺口、无边界、原有效记录可见；实际验证 AU/JM 三策略手动应用后区间身份与返回一致。

验收：用户能理解“为什么下面有历史、上面仍不可用”，操作只改显式选择的统计窗口；返回仍 partial 时准确解释，无造周 Bar、无收益口径变化。若现有后端字段已足够，本批不新增 API 字段。

### G / 用户 11：参考标签防重叠和边界布局

文件：`src/utils/referenceCalloutLayout.ts`、`src/types/referenceCallout.ts`、`NewowProductChartStage.vue`、`SubingChartStage.vue`、现有布局/图表单元与 E2E；若没有独立布局测试，新建 `tests/referenceCalloutLayout.test.ts`。

设计：沿用共享纯布局函数。输入包含投影锚点、实际/约束后的文字盒尺寸和主图可用区域；输出包含受约束的 box、紧凑状态和引线位置。先使用 E 的显示文本，必要时通过同一测量 owner/ResizeObserver 更新尺寸，避免 resize→测量循环。

- [ ] 用密集同 X/邻近点、主图四角、极窄尺寸、全屏/退出全屏、字体与容器尺寸变化构造失败回归。
- [ ] 所有完整卡片保持在价格主图区域内；碰撞检查同时考虑已放置完整卡片与紧凑节点。空间不足时使用紧凑可聚焦节点，而非丢掉 Marker。
- [ ] hover/focus/selected 展开时重新求解展示盒位置，必要时使用主图内独立浮层；引线仍指向原 Bar/price。不可只通过移除 overflow:hidden 把内容溢出到副图或工具栏。
- [ ] 选中节点有优先级，紧凑节点可逐个键盘/点击定位；稳定 id、时间、physical contract 与价格属性不变；同点密集时提供确定的可访问选择顺序。
- [ ] 图表缩放、平移、历史追加、pane resize、全屏和窄屏均触发布局更新；dispose 清理所有 listener/observer/RAF。

验收：盒体在可用区域内、完整标签不相交；密集模式不丢身份或操作；原始动作数量/数据不变。AU 趋势、震荡、主升浪及苏冰实际窗口加 fixture 密集极限；1440/1920/390 宽度和全屏均核对。若 JM 输入被 B1 数据 Gate 阻塞，单独记录限制，不能用 fixture 替代真实通过。

## 四、H 批次：验证、Review、集成与发布边界

- [ ] 每个实现缺陷先 RED 后 GREEN，测试真实行为而非匹配源码固定措辞；每批维护受影响 canonical 和 TESTING 的命令入口，按范围提交，不全量暂存其他任务文件。
- [ ] 针对 API 输入、参考错误、MDS 优化运行对应 pytest；共享读路径变化补分页、Catalog、完整性、reference projection、prefix/换月相关回归。只在实际涉及的风险范围扩测试，不机械全仓重跑。
- [ ] Web 完整 unit、typecheck/build、首页/详情/Newow/SuBing E2E 通过；记录既有 skip 和 warning，不抬截图阈值制造通过。precision 及布局更改需重新核对视觉结果。
- [ ] Ruff/Mypy、工程 canonical consistency、OpenSpec、secret scan、diff check 通过；具体可运行命令只追加到 `TESTING.md`，本计划不复制第二套命令权威。
- [ ] 用候选代码在隔离本地 Web 上真实点击 AU/JM：首页冷/热/刷新/恢复、消息筛选、品种切换、自由看盘七周期、Newow 三个 W1 策略、参考区间操作、HTDY/苏冰状态和事件时间、统计精度、密集标签及全屏；记录代码身份、数据身份和检查时点。
- [ ] fixture E2E、真实 HTTP、真实 Chrome 页面分别记录。未开放 D1/60m、未完成周、正常无事件均不修改为成功；本轮未列的苏冰详情扩建、HTDY 页签重排、指标解释扩建及牛哇真实补数不纳入范围。
- [ ] 独立 Review 针对完整 diff，关闭必要 finding 后复测受影响项。只读 Review 可按仓库流程安排，不另开第二个开发会话，不分拆给多模型实现。
- [ ] 所有源码改动通过必要验证、Review、范围检查后，沿普通流程 commit/push、集成 develop；重新检查 develop 并发变动，保留其他任务的内容。工程集成与数据/发布 Gate 分开。
- [ ] 最终维护 11 行验收矩阵：源码状态、隔离测试、真实只读/API、浏览器、外部 Gate、证据路径逐项列出。数据阻塞或性能目标未达不能从分母移除；报告唯一最小下一步。

最终报告必须区分 CODE_COMPLETE / TEST_COMPLETE / REVIEW_COMPLETE / EXTERNAL_GATE_PENDING。只有 11 项所需事实和用户指定产品验收全部满足，才建议进入 release candidate；不得自动 main/tag/release、启用投影或 Runtime promotion。

## 五、交接方式

本方案由一个新的 `gpt-5.6-sol`、`high` 会话承担主开发，使用从 develop 建立的隔离工作树。原方案在主工作区的绝对路径供读取，原始巡检与性能证据也在主工作区 `outputs/`，不要求它们预先存在于新 worktree。

执行会话开始时复制并核对本方案的完整内容作为本次工作计划，先读仓库最新合同再按 A→H 执行。普通实现连续完成；数据/运行 Gate 只停止相关动作，其余安全工作继续。若工具因宿主权限阻止访问，遵守审批路径，不读取其他工具的内部状态、不绕过权限。

计划完成后的临时计划文件按仓库既有规则处理：正式合同进入 active canonical，验证证据保留在合适输出目录，不让已完成实施笔记成为平行事实源。
