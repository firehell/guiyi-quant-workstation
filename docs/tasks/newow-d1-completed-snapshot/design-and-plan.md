# 牛哇日线完整快照与每日更新闭环设计

日期：2026-09-18。状态：方案设计，未实施、未发布。

用户已选定“默认查看最近完整日线快照，独立表达当前信息”的方向。本文件进一步定义产品合同、
盘后衔接与六步执行安排；不授权新的 provider 下载、生产写入、发布或 Runtime 切换。
设计基线为 develop `0e792bd6f7ed98c07050ebb5aed4d8041abb77a3`，现役身份以 STATUS.md 为准。

## 1. 已确认事实与问题

- 9 月 16 日 180 项首载、9 月 17 日 chart/reference 验收均有固定收盘截止，不能证明次日盘中默认入口。
- 本次只读 Catalog 查询：operational 60 品种的 MainContractMap 最新日期均为 2026-09-17，
  2026-09-18 映射均不存在。本机 Web 入口的 180 项当前主图请求均为 MAIN_CONTRACT_MAP_MISSING。
- Newow 默认窗口按 completed days 选择 Bar，但 reader 按请求 as_of 检查已生效 owner，包含盘中交易日。
- 既有合同要求当前 owner 缺失时显式失败，且有无新 Bar 也必须识别已生效换月的测试。
  因而不能直接把共享 reader 的 owner 上界统一截到昨日。
- 盘后 update 在 18:05 同步当天映射、当天/下一交易日 Session，并维护 D1/W1/分钟数据。
  整体 passed 还依赖 Live 对账和清理。last_successful_trading_day 是任务状态，不是每品种日线可用证明。

## 2. 范围和不变量

范围是 operational 60 品种、Newow D1 趋势/震荡/主升浪、已开放面板及其每日更新闭环。
W1/60m 和跨周期 explanation 的开放范围维持 release capability 合同。

数据仍从 Catalog/MDS 读取 Canonical；不增加行情库、写入流水线或第二套缺口事实。
公式保持现有版本。展示截止与参考状态身份须明确版本化；已有固定 as_of 的历史数值不得改变。
如果实现确实改变参考配对/换月收益规则，则属于额外 reference_model 语义变更，必须先说明并决策。
auto_order=false；不新增策略通知、Scope、受众或策略晋升。

## 3. 页面和时间合同

默认日线模式命名为“最近完整日线”。它明确是收盘快照，不再把请求墙钟隐含当成全部历史输入截止。

服务端区分四个时间/日期概念，前端不自行按自然日减一：

| 字段 | 含义 | 权威来源 |
|---|---|---|
| requested_at | 用户打开/刷新页面的时间 | 服务端校验后的请求时间 |
| expected_trading_day | 当前本应已完成的最近交易日 | MDS Calendar/Session，按品种解析 |
| available_trading_day | 本次已验证完整的日线快照日期 | Catalog/MDS 实物与质量校验 |
| snapshot_as_of | 该快照的统一事实截止 | 对应交易日最后 Session 结束后一个微秒 |

维护进度另外表达，不并入 snapshot_as_of。首页报价、Live 时间、参考估值截止不得混用同一个标签。
所有日线面板以相同 product、frequency、snapshot_as_of 和依赖身份读取；自选参考统计窗口保留自己的
membership 和实际估值截止，不能冒充整张页面的最新状态。

默认显示“截至 2026-09-17 收盘”，使用“截至该日的策略状态/参考持有/参考浮动”等用语。
当日报价和合约若保留，放在独立区域标明日期与来源；未核实当前 owner 时显示未确认。
旧快照中的 OPEN 只表示旧截止的参考持有，不能声明当前合约仍持有。

### 3.1 新鲜度与业务可读性分别表达

| 场景 | 页面行为 |
|---|---|
| 今天盘中，昨日快照完整 | 昨日日线正常显示；今天日线未完成不是故障 |
| 今天收盘、18:05 前 | 保留明确标注的旧快照，显示“今日日线待更新” |
| 盘后正在更新 | 旧快照可用时继续显示，显示目标日期及更新中 |
| 新日期已验证 | 提供“有新日线，更新至 × 日”；切换生成新的快照身份 |
| 更新部分成功 | 按品种/面板显示实际截止及阻塞，不把全部 60 品种统一判失败或成功 |
| 维护失败、missed、stuck | 显示更新失败/未执行/卡住及数据日期，不清除故障事实 |
| 周末/节假日 | 按交易日历判断最新，不以自然日差直接判过期 |
| Calendar/Session 无法证明 | 新鲜度未知，不能显示“已更新至最新” |
| 输入冲突/损坏/历史内部未知缺口 | 相关结果失效并明确失败，不用更老快照掩盖 |

“可展示”“最新”“三策略均计算完成”是独立结论。PRICE_UNAVAILABLE、NO_TRADE、WARMING、
数据中断、参考交易中断继续使用已有业务状态，不能为了 ready 强行忽略或填补。

## 4. 唯一快照解析与一致性

在 Newow service 层增加单一 D1 默认快照解析职责，复用 MDS/Catalog 和已有 reader 验证。
已有显式历史快照入口保留；不修改共享 owner 校验来模拟回退，不让前端搜索日期。

解析规则：

1. 用权威 Calendar/Session 得到 expected_trading_day；缺事实立即返回明确诊断。
2. Catalog 的实际提交、映射与端点信息只提供候选边界，不能以 max(date)、分区存在或任务 passed 直接宣告完整。
3. 完整性必须覆盖目标窗口全部应有端点、rank1 身份、物理可读性、源质量证据，以及所用物理合约的
   生命周期预热。可信缺价按既有质量合同计入完整事实，不把它变成有效价格。
4. 允许展示既有完整前缀，只限缺失发生在尚未发布的最新后缀，且公开落后于 expected_trading_day。
   缺失进入已提交/已声明完整的区间、身份冲突或物理损坏时立即失败；禁止扫描更老日期直至凑出绿色结果。
   无法证明末尾是未发布还是历史损坏时，默认解析失败，用户仍可显式选择已验证历史快照。
5. 截止选择不依赖某套策略能否盈利、是否暖机完成或某面板是否 ready。选定截止后，面板独立返回业务状态。
6. 冻结全部实际依赖 revision/hash；读取结束再验证依赖未变化，不能混用盘后更新中的不同代数据。
   revision 不一致显式重建本次请求，不返回混合结果，不进行生产重试。

snapshot 身份包含所选日期、输入 hash/revision、策略/公式/参考模型和新增的快照政策版本。
沿用现有 token、缓存和取消机制。切换日期必须取消旧请求、更新 token、清除不兼容分页与定位。
新主图接收成功后才切换页面；其他面板处于未读取/加载中，不能残留旧日期统计。
分页过程中保持当前 snapshot。canonical_updated 只提示重查，不视为可用证明。

快照可用性可以缓存，但缓存不是行情权威。重启和新 Runtime root 必须能从 Catalog/MDS 重新解析，
不依赖旧 root 的盘后状态文件，不复制旧的 passed 冒充新版本自然验收。
已接受快照依赖被更正或撤销时，旧 token 必须失效，不能无限展示旧缓存。

## 5. 盘后更新需要修改的部分

### 5.1 数据更新与调度

继续使用既有 18:05、operational 60、HistoricalDataManager.update、维护锁和分区提交机制。
不为了盘中日线展示提前生成当天/未来主力映射，不增加日间生产抓取。
保留现有重试条件：只有 NEXT_TRADING_SESSION_NOT_READY 时最多一小时后再试一次。
新的牛哇验收失败不得触发额外 provider 下载、补数、整批 update 重跑或通知重发。

检查并修正日线完成进度的表达：按品种报告 D1 目标日、实际发布/验证日及安全错误原因，
不要让分钟数据耗时/失败覆盖已经验证的 D1 事实。进度是观察值，页面仍以快照解析结果为准。
现有 canonical_updated 事件含义维持不变，不改写成“所有牛哇已 ready”。

### 5.2 换月预热依赖

盘后更新必须能明确发现新主力合约的 Newow 同周期完整预热需求。不能只证明当天新合约有一根 D1。
复用现有维护 planner/readiness 检查：在已授权日常增量范围内更新；若需要扩大到新物理合约历史下载，
输出具体合约、窗口、缺口和维护计划，阻塞受影响新快照，并走独立数据批次授权。
不可借本设计自动扩大既有日常 provider 预算和写入范围。

### 5.3 增加消费端只读验收

在盘后编排层增加 Newow D1 验收，复用 readiness/service；不让 HistoricalDataManager 依赖策略领域。
在主更新已结束且释放生产维护锁之后执行，成功/部分提交/失败都记录此次可读性；禁止与 mutation 并行。
若发现另一维护任务已经开始或依赖发生变化，则 skipped_busy/input_changed，不能当 passed。

按 60×3 检查 chart/reference（360 项），并检查各策略已开放默认副图；复用同品种输入避免重复全历史 IO。
报告目标日期、实际截止、成功/失败/未检列表和原因。主图成功不替代 reference/副图验收。
先采用单 worker，总预算 15 分钟，单品种最多 60 秒；超时项目标记未完成，不自动重试或跳过后造绿。
这些是本方案的拟定资源上限，实施前用只读性能基线核对；若不足，调整明确预算或优化复用，不能削弱检查。

盘后既有主任务结果和消费验收结果独立保存。扩展既有状态载荷 consumer_checks.newow_d1，
绑定 run_id、目标日、运行版本、输入身份、checked_at 和覆盖列表；这是可重建诊断，不是可用性事实源。
新字段缺失表示 not_verified；更新写入需原子替换并避免覆盖已有主任务终态。
若旧状态解析器拒绝该扩展，必须在同次代码修改中完成版本适配与恢复兼容测试后才能交付。
主任务通过而验收失败时，主任务事实不被篡改，产品 health 显示 degraded。
消费验收仅更新现有 health，不新增真实通知或改变 one-shot 通知语义。

## 6. 必要回归与真实验收

至少覆盖：盘前、盘中、精确收盘边界、收盘未发布、完整发布、部分提交、分钟任务失败、维护未执行、
重启、周末、节假日、夜盘跨日、当日换月无完整 Bar、新合约预热不足、Calendar/Session 缺失、
源缺价/无交易、历史内部缺口、输入身份冲突、更新期间 token 冲突。

对每个既有固定 as_of 样本，比较策略 Frame/Marker、参考交易身份、配对和收益，要求保持原值。
保留现有 current-owner/换月测试；新默认模式的事实截止改变必须通过显式快照政策表达。

真实验收分层：

- 只读 API：60×3 主图及 reference，同截止默认副图、质量状态和身份；输出完整列表，不能只数 HTTP 200。
- 本机 Web：180 个新页面首载，核对 URL/品种/策略/周期、请求响应身份、DOM 状态、截止标签与参考面板。
- 公网 Web：同等真实页面矩阵，通过实际 nginx/FRP 链；每项等待本次请求完成并匹配响应品种/策略。
  不得从 AX diff 没有 ready、地址栏已变化或上一页面错误文本推断本项失败；不能用接口循环冒充逐页验收。
- 新版自然业务：至少一次自然盘后更新到新日线、随后首个实际交易时段的新鲜度与主图验证。
  若遇周末，等待首个实际交易日；不为了验收手工触发生产更新。

## 7. 六步执行安排

### 第一步：冻结合同并建立回归基线

- [ ] 核对最新 develop、Runtime、工作树冲突；执行代码工作前创建独立任务工作树。
- [ ] 更新 newow-product-reference-trading/spec.md、必要的 market-series-query/spec.md 与 docs/DATA_CENTER.md，
  明确默认收盘快照、显式历史入口、当前 owner 和每日更新边界；同步 API 政策版本定义。
- [ ] 在 test_product_reader.py/test_product_service.py 建立当前日期映射缺失、已完成日完整的最小场景，
  同时保留 test_night_session_boundary_uses_next_trading_day_without_natural_date_guess 等既有测试。
- [ ] 留存固定 as_of 策略/参考输出基线，明确允许变化只有新增模式、截止元数据与展示语义。

交付：不会通过删除换月校验来“修好”主图的完整可测合同。

### 第二步：实现统一日线快照解析与 API

- [ ] 以 newow/product_service.py 为组装点，增加职责单一的 D1 快照解析模块，复用 MDS、Catalog 和 reader。
- [ ] 改动 market_newow.py、market_newow_product.py 的类型合同，返回目标日、可用日、事实截止、新鲜度。
- [ ] 为全部 section 统一截止和 token 身份，保留自选参考窗口与显式历史模式。
- [ ] 验证未发布尾部、内部缺口、源质量、部分提交、依赖变更、重启重建和换月语义。

交付：当前请求可以明确获得已验证日线快照，所有数值有同一事实截止。

### 第三步：完成 Web 页面和切换行为

- [ ] 修改 useNewowProduct.ts、NewowProductWorkspace.vue、newowProduct.ts 及响应类型适配。
- [ ] 增加日期/更新状态文案，明确历史参考持有与当前报价/合约；不把运行状态暴露成无意义技术标签。
- [ ] 实现“新日线可用”提示、原子切换、取消旧请求和分页身份隔离。
- [ ] 测试 fresh/stale/pending/failed/unknown、主图成功而参考失败、快速切策略和跨日期旧请求晚返回。

交付：用户能看图，并能一眼确认看的哪天、是否该有更新。

### 第四步：衔接盘后更新、依赖检查和消费验收

- [ ] 修改 after_market.py 与运行编排入口，补齐 D1 进度和独立的只读消费验收结果。
- [ ] 复用 newow/readiness.py/readiness_composition.py 检查新主力生命周期预热与已开放面板。
- [ ] 保持数据领域不依赖策略计算；验收在维护锁释放后串行执行，超时/失败不触发生产重试。
- [ ] 测试状态格式兼容、主任务 passed/failed 与消费验证四种组合、部分成功、重启、资源预算和 one-shot。

交付：每日更新能够报告“数据做完了多少、牛哇真正可用了多少”，并说明具体未完成项。

### 第五步：完整验证、独立 Review、集成 develop

- [ ] 跑直接相关后端、Web、E2E；按结果扩展相关模块，检查 diff/secret/OpenSpec。
- [ ] 对实际 Canonical 做隔离只读预览，完成 60×3 页面验收和参考/副图核对，不伪造历史缺口。
- [ ] 独立 Review 重点审查时序、换月、质量失败、缓存身份、盘后锁和重试语义。
- [ ] 满足验证与 Review 后提交、推送并按仓库流程集成 develop，记录残留外部 Gate。

交付：经过验证的 release candidate；若出现真实数据缺口，列明单独数据计划，不声明全产品闭环完成。

### 第六步：受控发布、Runtime 切换和自然验收

- [ ] 准备 exact version 的发布/Runtime 包及可验证回退路径；核对旧客户端与状态格式兼容。
- [ ] 在明确授权下分别完成 main/tag/Release 和 Runtime promotion；新增验收运行范围纳入该授权。
- [ ] 完成本机和公网 180 页及参考/副图验收，保留每项身份、时间、响应和失败原因。
- [ ] 观察一次自然盘后及随后首个实际交易时段，确认日期推进、新鲜度、主力切换与缓存一致。

交付：用户默认入口实际可用，并有每日自然更新接续证据。
未完成自然交易日验证时，只声明部署与即时读回完成，不能声明全部闭环完成。

## 8. 验证入口与回退

后端定向起点（新增模块测试应纳入同一命令）：

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=services/quant-api:packages/quant-core \
  services/quant-api/.venv/bin/python -m pytest -q -p no:cacheprovider \
  services/quant-api/tests/newow/test_product_reader.py \
  services/quant-api/tests/newow/test_product_service.py \
  services/quant-api/tests/newow/test_historical_snapshot.py \
  services/quant-api/tests/newow/test_market_newow_product_api.py \
  services/quant-api/tests/newow/test_readiness.py \
  services/quant-api/tests/data_foundation/test_after_market.py \
  services/quant-api/tests/data_foundation/test_market_home_projection_after_market.py
```

Web：沿 TESTING.md 的 Newow 定向 tests、类型检查、production build 和
e2e/newow-product.spec.mjs、e2e/newow-detail-light.spec.mjs 扩展时钟与状态用例。
以上是未来执行入口，本次设计未运行这些工程测试。

回退仅切回已验证兼容的旧 exact Runtime，须纳入授权；不回滚 Canonical 或删除状态事实。
旧版本不识别的新快照 token 应公开拒绝并重新加载，不能静默接受。
本方案不需要新增 DB 表或 migration；现有生产数据缺口若被发现，独立处理。

## 9. 执行预算和完成标准

六步中，第一至第五步构成工程交付；第六步是独立发布与自然验收。
建议按三个工程批次推进：合同+后端，Web+盘后，完整验证+Review+develop 集成。
工程耗时应在第一步复现及新快照解析复杂度确认后估算；不把等待下一个实际交易时段计作代码耗时。

完成标准：60 品种日线默认入口按合同展示精确截止；真实未知缺口不被藏掉；三策略/面板状态可追溯；
自然盘后能推进日期且错误如实可见；次日盘中不因未发布的当日历史映射而清空已完成日线快照。
