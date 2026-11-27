# 实施任务 · Quant Compute Core 与 Quant Chart

本任务表以 [proposal](proposal.md)、[design](design.md) 和三份新增能力规格及 Newow MACD delta 为准。勾选表示达到该条交付条件。部分完成、现场未验和既有基线问题见下方说明。

## A. 计算包与注册合同

- [x] A1. 盘点通用指标、Newow/HTDY/SuBing 专属公式及所有消费者；标出哪些是通用显示、策略内部数学、回看展示或业务事实。
- [x] A2. 定义 BarSeries、FeatureResult、IndicatorDefinition、Compute Registry、公式/参数/状态/结果 schema 身份。
- [x] A3. 将 TA-Lib 纳入 `guiyi-quant-core` 独立依赖和锁定构建；确认 Python 3.13 / macOS ARM64 / CI 可安装。
- [x] A4. 将通用指标目录收敛到 EMA10/21/60、MACD 12/26/9、ATR14、STDDEV20、BOLL20/2、HHV、LLV、OBV、Volume Ratio；不保留重复通用实现。
- [x] A5. 保留并整理现有趋势因子；不扩展未经验证的通用因子。
- [x] A6. 建立 Swing Pivot、Support/Resistance、Breakout/Retest 公共内核及因果时间合同。
- [x] A7. 为现有 Newow/HTDY/SuBing 专属计算提供统一注册与结果适配，不改公式身份、状态机和权限。

## B. Chart 包与现有显示迁移

- [x] B1. 建立 `@guiyi/quant-chart` 独立 TypeScript 包，定义 Display Catalog、Renderer Registry 和 Chart Profile。
- [x] B2. 实现共享 Main Pane、Volume Track、Auxiliary Pane、Pane Manager 和共同时间轴/光标同步。
- [x] B3. 实现 Line/Histogram/Band/Marker/PriceLevel-Zone/Primitive 通用 Renderer。
- [x] B4. 迁移 EMA/BOLL/Range Detector/Donchian 等公共主图图层；保留现有 Newow 主图 Primitive。
- [x] B5. 迁移 Newow 四类副图和现有副图选择行为；默认仍为一个选中副图，新增多 Pane 只作为显式能力。
- [x] B6. 保留并验证通用特殊成交量着色、SuBing 2x/3x 档位、Newow 自有成交量显示。
- [x] B7. 将动作、Hint、Alert、委托/成交等业务事实作为独立来源图层接入，不转成技术指标。
- [x] B8. 实现 Add/Hide/Remove/Configure/Retire、偏好 schema migration、Profile 默认配置和图层资源释放。
- [x] B9. 实现指标诊断与 Compute Registry / Display Catalog 兼容性检查。

## C. 独立发布与消费者迁移

- [x] C1. Quant Core 独立 SemVer、wheel/sdist、包内测试及 Release artifact。
- [x] C2. Quant Chart 独立 SemVer、package tarball、类型/渲染测试及 Release artifact。
- [x] C3. API/Web 消费者锁定精确包版本和 artifact hash；开发 editable/workspace 与正式锁定安装分离。
- [x] C4. 独立版本化 formula/state/result/chart schema；验证不兼容消费者 fail-closed。
- [x] C5. 更新 Newow MACD auxiliary 使用 TA-Lib 12/26/9 原始输出的 active delta；保持 Newow API envelope、as-of、physical owner、warming 和 research-display-only 边界。
- [ ] C6. 迁移 Web/牛哇/回测/快期/苏冰消费者到统一接口；每个消费者只请求自身需要的指标。
- [ ] C7. 执行 60 品种 × 7 周期性能、内存、缓存、增量恢复、计算隔离和图表视觉回归。
- [x] C8. 完成独立 Review、OpenSpec strict validation、受影响测试和 develop 集成；同步已接受 delta 到 active specs 与 canonical。

## 验收要求

- 基础指标白名单与 TA-Lib 参数准确；缺失/NaN/预热显式，不以 0 代替。
- 通用指标只有一个计算权威；Newow/HTDY/SuBing 专属公式及现有 golden 不因迁移而改变。
- Batch、Incremental 和受限 Live 的输入身份、状态恢复及结果发布可追溯。
- 主图、副图、成交量显示、Newow 四类副图和各产品 Profile 保留既有可见行为；新增/隐藏/移除不破坏其他图层。
- 显示样式变化不触发重计算；参数变化只使相关依赖失效；图层 dispose 后无残留 Series/Primitive/listener。
- 纯显示变换不产生 Action、Alert、订单或账户事实；回看形态不获得正式策略权限。
- Quant Core 和 Quant Chart 能独立构建、安装、测试、版本化和发布；消费者精确锁定版本，不自动升级。
- Batch/研究任务不能阻塞 Market、HTDY 或 SuBing 的独立运行；Web 请求不执行全历史重计算。
- 本 change 不发布 main/tag、不切换 Runtime、不修改真实数据/账户/通知，不改变 `auto_order=false`。

## 目标模式执行约束

后续实现属于架构与公式边界任务。实现时按仓库 `AGENTS.md`、`docs/DEVELOPMENT.md` 和当前 active canonical 选择 Lane、工作区与验证；涉及通用公式替换、因果性或 Newow MACD 语义的代码改动应做针对性独立 Review。包发布与正式消费者升级分别处理，不能把 develop 集成或 package Release 当作 Runtime 已切换。

## 集成验收与剩余依赖

- A7 已登记现有牛哇副图、HTDY、Lux Range 与苏冰同花顺合同。牛哇四类副图和首页主力控盘已通过专属登记入口计算。早期独立复核覆盖六个已开放周期、五种副图或形态和两个截点，60 组结果与原内核的历史前缀逐值一致。杯柄辅助 API 现也经同一注册入口，沿用 `newow_cup_handle_v1`、D1 趋势 profile、分段见证和 `NOT_APPLICABLE`。0.4.0 最终制品独立复核比较三个策略的六个开放周期，并核对杯柄确认前一微秒和确认时点，共 20 组完整结果与 0.3.0 原入口一致。牛哇五个已登记辅助分量各自绑定计算，仅允许六个现役周期的 Web 展示。正式消费者交接在 C6 联验。
- A7 HTDY 原始内核的历史回放、Alert 和快期候选共用登记入口及原有 FormalPolicy；严格版声明现有研究字段。苏冰六周期共用公式身份表及登记的状态初始化、推进，覆盖 Alert 与参考回放、预热和换合约。原冻结样本逐值验证 382 个 HTDY 末窗及苏冰 46,100 根 Bar 的状态和输出；HTDY 周线样本各物理段不足 32 根。独立复核确认 0.2.0 检查点由 0.2.1 恢复后，六周期最终编码与原版连续运行逐字节一致。
- A7 苏冰 Paper 专属因子已按既有调用注册。日线与 60m 只请求趋势，30m 请求趋势、MACD、量能、价格、回踩、区间、近期结构和退出事实。登记沿用原公式和固定参数，记录回踩与结构输出的条件字段。Core 0.3.0 候选在隔离进程中通过注册绑定原 Factors 调用，同 Core 0.2.1 对照了 36 个物理合约分组、5,642 次因子推进和 5,250 次分钟观察，逐步输出和状态摘要一致。OI 冻结日线缺失。46 个 run 身份校验覆盖文件匹配基线，正式接线仍须保留原 run 的恢复合同。
- B9 行情工作台、牛哇主图和盘后共享副图已提供图层诊断。主选、附加和共享副图统一复核物理合约、计算段与 Bar 截止，冲突时清除相应图层的旧数据与来源。共享副图区分加载、预热、就绪和输入冲突，主图建仓清仓图层在策略切换期间撤下旧来源。盘后保存价位显示参考版本及实际绘制截止，并在公式变化处断线。Free BOLL 可在浏览器读取公式与就绪状态，EMA/BOLL 区分缺输入、预热、源无效和计算错误。缺证据的牛哇预热计数和缓存状态留空。
- B9 预警、盘后/研究动作、快期原生执行、苏冰 Paper 成交以及 HTDY 原有快期成交标记已接入各自来源诊断。绘制、浮窗和标记诊断共同复核当前 Bar 的物理合约。共享行情画布保留独立 Preview 序列，快期与 Paper 成交按原始时间精度校验并绑定实际绘图合约。
- B9 牛哇主图趋势带、趋势通道、震荡区间、主升浪、形态、参考价与提示已提供各层诊断。目标价与吸筹价跟随实际采用的图例或解释来源，突破价位与服务端突破标记独立。切换清除旧策略来源，通道保留最新点的冲突或预热原因，公开形态核对原始 OHLCV、交易日和计算归属。
- B9 图层登记、同步渲染和后续绘制帧的失败各自有诊断。绘制故障立即禁用对应附件，原生帧退出后回收。Chrome 验证牛哇趋势带绘制失败后可重新显示，苏冰标记绘制失败后撤回图上来源并保留已存事件。真实默认标记工厂和 Fancy Canvas 注入文字绘制异常后状态栈深度恢复为 0，另重复 100 次正常挂载与移除，无原生附件或行情订阅残留。逐层诊断覆盖与正常渲染证据继续按验收要求核对。
- B9 通用行情画布分别读回已完成 K 线、预览与成交量的实际截止。苏冰倍量诊断使用最后一组实际评估的同段 Bar；同花顺 MACD 柱和交叉分别报告截止与 21 根预热进度。多 Bar 计算缺少完整输入凭证时来源留空。Lux Range 区分缺输入、预热、无效数据和就绪，并读回实际缓存状态。共享 K 线写入失败时撤下基于蜡烛归属的标记与来源，重试完整窗口后恢复；成交量与 MACD 的独立故障各自显示并恢复。
- B9 牛哇策略验证前的 K 线和成交量读回独立历史行情的截止、Bar 哈希及实际缓存命中，复用正式行情的物理合约解析。工作台切换只继承共享画布已经绘制的来源。动态箱体的点保留各请求的前缀哈希，分页及换月分别绑定物理合约；Canonical 水位撤销后重新读取。同一窗口的修订冲突会撤下旧结果，迟到的旧请求不影响当前窗口。
- B9 牛哇主选、附加、盘后共享副图统一从可绘数据读回正式 Bar 截止，保留历史显示并单独报告末根缺值、预热或刷新失败。MACD 按当前 Bar 及物理计算段匹配点状态。对当前 Compute Registry manifest 已执行 Display Catalog 兼容性校验。
- B9 火天大有原始观察线以实际写入的有限值判定就绪和末根时间。清空窗口后显示缺少输入并撤下截止，恢复后读回绘制截止。共享诊断单独记录当前错误时间，普通刷新保留时间，明确恢复后清除。独立复核覆盖同步渲染、延迟绘制与清理异常；Chromium 读回牛哇趋势带的绘制错误时间并验证重试。
- B9 牛哇附加副图的时间轴单独报告行情来源、频率及实绘截止，写入失败撤下同 Pane 指标并保留相邻 Pane。盘后保存价线逐线处理写入异常，撤销失效来源且可重试。Core 0.3.0 与 Web 锁定 Chart 0.1.6 的实际安装制品通过目录兼容性校验。
- B9 牛哇实验主图、成交量、通道、止损、参考动作、展示提示和测试 5 突破/影线可分层读回。共享 K 线创建或配置失败后在原 lease 重试。展示提示只以实际绘制且与视口相交的事件为截止，取不到 Canvas context 时撤下点击区和旧来源；无事件时返回空层。错身份响应标记来源无效。独立 Review 后通过 84 项 Web 定向测试和 16 项 Chrome 定向用例。
- C3 验证独立候选安装。Quant Core 0.3.0 的 wheel 和 sdist 两次构建逐字节一致，API、TQ Executor、RQAlpha、VeighNa 隔离环境均按精确消费锁安装。Web 锁定 Quant Chart 0.1.6 tarball，已复验其 Display Catalog 与 Core 0.3.0 的 Compute Registry 兼容性。正式消费者升级与候选构建分开。
- C3 最新候选 Core 0.4.0 的 wheel 和 sdist 各自两次构建逐字节一致，两个构建各通过 36 项包测试。API、TQ Executor、RQAlpha、VeighNa 按精确制品锁完成隔离安装，独立复核安装指向与已安装模块字节。Chart 0.1.6 的安装制品通过 Core 0.4.0 目录兼容性校验。
- C6 Web 历史指标已接入批量计算队列，牛哇 MACD 保留同 owner 前缀，RQAlpha 使用独立冻结输入通过 17 项回归。快期 HTDY、苏冰独立模拟的 completed 消费、权威修订回调和持久化游标须与 Market Foundation 接口联验。牛哇正式盘后参考继续读取原归档凭证；四类牛哇副图的在线计算入口和已保存结果的图表诊断均已定向验证。
- C6 Web 历史图表冷计算在返回前通过新只读事务复核同一 Canonical 窗口。隔离 Parquet/Catalog 验证仅失效旧修订的物理合约段，新请求按修订后的数据重算；缓存命中只使用本次 Market 读取。计算等待和复核共用既有时间预算。现场主动修订通知与独立模拟接线仍待联验。
- C6 快期 HTDY 的自然 H1 入场使用 Pub/Sub 唤醒，并只读核对完成日志、身份索引、物理合约和 32 根计算窗口末端。缺失、错配、提前确认及不可转发的原件均拒绝入场；沿用现有首次观察水位、信号身份与账本。独立 Review 通过，303 项定向及隔离 PostgreSQL、Parquet、Redis 的 42 项集成测试通过。正式 Market 来源启用与现场读回仍待联验。
- C6/C7 Compute Runtime 的 Live 恢复复核同修订的检查点前缀、提交 ID 和直接前驱。相同可用时间的多根 Bar 按提交端点各自恢复，拒绝重复或未订阅的检查点。固定样本复跑 60 品种、999 次 Live 提交，60 个 Runtime 重建后均可去重并与连续运行逐值接续。现有快期 HTDY 完成流入场、双 Redis 交接和苏冰 Paper 游标已用独立 PostgreSQL / Redis 回放复验，连同 Compute Runtime 共 76 项通过；专属消费者与新版 Compute Runtime 的正式接线和现场读回仍待验证。
- C6 苏冰在独立 PostgreSQL 和两个 Redis 实例复演跨交易日接续。原 run 从旧实例读回 16 品种水位、序号 2。恢复后的实际 Paper `consume_day` 使用旧实例无法提交下一交易日分钟，改用目标实例后从其中的夹具完成流提交首分钟，序号推进至 3。读回核对 16 品种新源代次、原 run 和代码身份、旧账本前缀与新收尾哈希。再次恢复并读同一批数据后，投影和账本保持一致。候选部署宿主的正式绑定与实际运行读回随 Market Foundation 联验。
- C6 2026-11-27 候选联验使用 `9c0cae568`。旧源只读预检确认快期 16/16 品种的物理合约和 H1 水位均与 11 月 26 日 15:00（上海时间）权威端点相符，苏冰 16/16 分钟水位同样对齐至序号 776。快期监控读回过期且 Scope 为 `FLATTEN_PENDING`，苏冰心跳为 `WARMING_UP`，正式预检保留阻塞。
- C6 以只读快照复制苏冰原账本至一次性 PostgreSQL，保留精确运行代码 `2be7a62af`、原 run、投影和 776 条前缀。Market 候选绑定使用复制的 Calendar、Session 和 rank1，受控 Tick 经实际 EventEngine、Feed 和完成流生成 11 月 27 日交易日首批 12 个夜盘品种的 21:01 M1 及 22:00 H1（均为 11 月 26 日上海时间），逐品种核对合约、端点与源代次。原 Paper 进程在固定回放时钟和隔离执行事实下提交首批 12 根 M1，12 个 producer stream ID 逐条对应候选原件，序号由 776 增至 777，原身份与前缀校验通过。单独启动同版解释器、重新预热并重读，序号仍为 777，账本和投影与首次提交后完全一致。C6 继续待验证正式宿主绑定、快期新源账户前进和主动 Canonical 修订回调。
- C7 [M4 冻结性能结果](evidence/performance.json) 使用独立安装的 Core 0.3.0，以相同输入三次复跑 415/420 个品种周期组合及 66,590 根已完成 Bar。可比批量耗时由 2.0681 秒降至 1.3824 秒，扩展指标准备、峰值内存和队列背压亦有实测。OI/RS 日线与 PD/PT/RS 周线有源缺口。已做工作台夹具与图层资源释放验证，未更新在基线上同样失败的旧截图。完整 420 组合与 Market/模拟进程并行现场尚待联验。
- C7 [11 月 26 日冻结性能结果](evidence/performance-2026-11-26.json) 通过 MarketDataService 只读重冻既有 60 品种七周期窗口。OI 日线恢复可读，矩阵扩至 416/420 组、71,172 根已完成 Bar。RS 日线价格不可用、PD/PT 周线缺少交易时段、RS 周线缺少已映射的数据集。Core 0.3.0 在新冻结样本三次复跑，可比批量耗时 2.2024 秒降至 1.4718 秒，压力测试队列峰值 4，结束积压为 0。[11 月 25 日同输入对照](evidence/performance.json) 继续保留。
- C7 [Core 0.4.0 制品性能结果](evidence/performance-core-0.4.0.json) 使用同一 11 月 26 日冻结输入。三轮可比批量累计耗时从 2.2142 秒降至 1.4519 秒。热缓存 P95 为 0.0315 ms，增量 P95 为 0.0901 ms。12 项指标请求的队列压力测试峰值占用 4，背压拒绝 420 次提交尝试并由现有测试循环重试，结束积压为 0，进程峰值 RSS 约 301 MiB。四个源缺口仍待 Market Foundation 补证。
- C7 2026-11-27 以只读事务重查相同的 actual dominant 固定窗口，截止仍为 11 月 26 日 16:00（上海时间）。RS 日线的 100 天窗口仍返回 `PRICE_UNAVAILABLE`，PD/PT 周线的 470 天窗口仍返回 `TRADING_SESSION_MISSING`，RS 周线同窗仍返回 `MAPPED_CONTRACT_DATASET_MISSING`。现有 416/420 性能覆盖维持待补证状态。
- C7 Market Foundation 候选用原脚本只读复验同一窗口。PD、PT 在 2025-11-27 挂牌，原查询误要求 70 个挂牌前交易所交易日的品种 Session。候选保留原请求身份并按挂牌后的 Calendar、Session、rank1 和 active Parquet 读回各 51 根周线，范围为 2025-11-28 至 2026-11-20。矩阵为 418/420、71,274 根已完成 Bar，原有 992 个物理合约段逐值一致。PD、PT 各 51 根周线仍不足 EMA60 预热。
- C6/C7 联验前置使用 Market Foundation A `0eb38d9c4` 与实际安装的锁定 Core 0.4.0。固定 418 路输入的三轮可比批量累计耗时为 2.3192 秒和 1.5382 秒，热缓存 P95 为 0.0359 ms，增量 P95 为 0.0938 ms，批次队列峰值 4 且结束积压为 0。[性能结果](evidence/performance-core-0.4.0-market-foundation.json) 以一次性 PostgreSQL 和两个 Redis 跑通 144 项 Compute Runtime、迟到输入、Canonical 修订、归档凭证、快期与 Alert 回归，另有 2 项苏冰独立账户交接测试通过。锁定 Chart 0.1.6 安装制品通过 Core manifest 校验及 12 项包测试，Web 区间、候选隔离与参考图层相关 88 项通过。B/C 合并候选、正式源接线和现场并发单独验收。
- C7 RS 日线应有 66 个端点。RS2609 的首个实际缺价端点是 2026-09-02 15:00（上海时间），同月 09-04、09-08、09-09 同为已证实的 `NONPOSITIVE_CLOSE`。月分区可读且质量摘要通过验证。RS 周线应有 66 个端点，13 个缺价周均已在相应物理合约的完整 D1 来源中找到 `NONPOSITIVE_CLOSE`。其中 7 个周端点所在月有 active W1 分区，另 6 个涉及 5 个未注册的 W1 月分区。首个是 RS2511 的 2025-10-24 15:00，起因是同合约 10-20 的 D1 缺价。严格日线、周线继续返回原错误码。
- C7 RS 若需核对源修订，已用既有 adapter 零下载预检 4 份物理合约、13 个完整周、63 个 D1 端点。RS2511 周末日为 2025-10-24、11-07，RS2608 为 2025-11-14，RS2607 为 2025-11-21、12-05、12-12、12-26、12-31、2026-01-09，RS2609 为 2025-11-28、2026-08-14、09-04、09-11。源读取须批准，预算为每周一次物理 D1、合计最多 13 次。若权威源有可验证修订，隔离 dry-run 先固定前像、原始响应及精确分区差异，范围上限为对应 9 个合约月份的 D1/W1。另获生产批准后才可在维护锁内复核前像与计划哈希、按物理合约原子发布。重复计划须先只读证明已提交或确无变化，结果不明先回读，旧分区及证据保留用于经批准的前向恢复。新事务独立验证 Catalog 指针、Parquet、D1/W1 同源一致和原 420 窗。
- C6/C7 在一次性 PostgreSQL Catalog 和独立 Canonical Parquet 复演同端点修订。计算中旧窗口返回 `MARKET_CHART_STUDY_WINDOW_MISMATCH`，只失效 JM2505 的旧修订，重新请求后 EMA10 从 100 重算为 103，JM2509 保持 200。工作队列的凭证重算、查重和前缀复用同批回归通过。候选绑定、快期原件入场、隔离修订及 Compute Runtime 共 68 项通过，另有 1 项现有 PostgreSQL 用例需单独显式启用。
- C6 隔离盘后归档已接通显式订阅的 Canonical 研究消费者。归档成功并保全凭证后，按同一 PostgreSQL Catalog 和 Canonical Parquet 复核物理合约及精确窗口；变化的输入进入 `submit_canonical()`，同一消费者进程内重复凭证与未变合约段复用既有结果。新结果的可知时间取发布凭证完成时间，晚到的旧日凭证不会回拨水位。计算期间若 Catalog 再次修订，保留最后一次已接纳结果，等新凭证重算。201 项定向回归与独立 Review 通过。现有默认归档配置未启用该订阅，正式接线和快期、苏冰 Live 计算仍待验证。
- C6 候选绑定的快期 H1 和苏冰 30m、60m 已显式接入 Compute Runtime Live 队列，沿用各自既有模拟内核和持久化水位。隔离 `RB2701` 使用完成流和原生 SQLite，从 11 月 26 日 10:00（上海时间）恢复，重复 H1 无推进，11:00 账本推进一次。苏冰以只读快照复制原 run 和 776 条账本，保留精确运行代码 `2be7a62af`。12 个夜盘品种的受控完成流推进到 22:00、序号 836。另起进程重建并重读相同原件，序号仍为 836。22:01 的下一批分钟推进至 837，核验原身份及完整账本前缀。138 项隔离回归通过。正式消费者启用与自然行情读回仍待批准和联验。
- C7 初始两根预览 Bar 的自动取景已与用户缩放分离。完整实验窗口按共享画布重新映射或自动适配，历史前插按旧首根在原生轴上的实际位移调整。测试 5 多标签旧用例原断言通过，验证突破、影线、键盘与切换；未改截图阈值或行情夹具。
- C7 视窗修正后通过 64 项 Web 定向测试和 13 项 Chromium 用例。Chart 0.1.6 在 180 秒持续复验中完成 285 轮工作台切换，卸载后跟踪的 Series、Primitive、监听和待处理读请求均为 0。
- C7 同一 Chrome 和固定夹具对照三种牛哇主图乘四种副图，以及 HTDY、SuBing、Free 的桌面图表。震荡初始视窗在原提交重复截图中也出现分歧，按同取景复拍后各组为 0 至 6 像素差。本次浏览器对照未覆盖自然行情、长时间运行或所有视窗尺寸。
- C7 [M4 持续压测](evidence/soak-results.json) 复用同一冻结输入及独立 Quant Core 0.2.1 wheel。每 30 ms 一次提交尝试的 120 秒对照中，Live 的稳态 P95/P99 从同进程混跑的 77.47/103.11 ms 降到两个独立 Compute 进程并跑时的 9.55/10.31 ms，Live 两轮均无拒绝。Canonical 两轮分别触发 9 次和 3 次背压，结束均无积压。60 个品种的 Runtime 重建、末根去重及下一根连续结果一致。浏览器完成 180 秒 284 轮切换及 70 秒 123 轮原生探针验证，卸载后本次跟踪的序列、Primitive 和监听全部归零。三组各 140 轮 Chromium 堆快照显示，增长最多的对象来自 V8 编译产物和 Chromium 网络调试记录。修正夹具对 Vite WebSocket 的误拦截后，堆中对应的 946 个异常降为 0。开发构建的 ChartModel、Series、PaneWidget 和 Vue ReactiveEffect 计数在切换期间稳定，卸载后归零。冻结回放覆盖真实计算代码，现场 Market 发布、持久化游标与独立模拟进程联验仍待完成。
- C8 实现提交 `a92f3343634242c15095316c45004289b4be6a0d` 已进入远端 develop。后端定向 315 项、Web 1,430 项、RQAlpha 17 项、浏览器 7 项、Chart 包 5 项和独立 wheel 27 项通过。两侧独立 Review 的阻断项已修正复验，本 change 和同步后的牛哇 active spec 均通过 strict validation。
