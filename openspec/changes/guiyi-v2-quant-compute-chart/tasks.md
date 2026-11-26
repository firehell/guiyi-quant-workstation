# 实施任务 · Quant Compute Core 与 Quant Chart

本任务表以 [proposal](proposal.md)、[design](design.md) 和三份新增能力规格及 Newow MACD delta 为准。当前 change 只记录目标与实施顺序；未勾选项均未实施，不代表已有代码已通过新合同。

## A. 计算包与注册合同

- [ ] A1. 盘点通用指标、Newow/HTDY/SuBing 专属公式及所有消费者；标出哪些是通用显示、策略内部数学、回看展示或业务事实。
- [ ] A2. 定义 BarSeries、FeatureResult、IndicatorDefinition、Compute Registry、公式/参数/状态/结果 schema 身份。
- [ ] A3. 将 TA-Lib 纳入 `guiyi-quant-core` 独立依赖和锁定构建；确认 Python 3.13 / macOS ARM64 / CI 可安装。
- [ ] A4. 将通用指标目录收敛到 EMA10/21/60、MACD 12/26/9、ATR14、STDDEV20、BOLL20/2、HHV、LLV、OBV、Volume Ratio；不保留重复通用实现。
- [ ] A5. 保留并整理现有趋势因子；不扩展未经验证的通用因子。
- [ ] A6. 建立 Swing Pivot、Support/Resistance、Breakout/Retest 公共内核及因果时间合同。
- [ ] A7. 为现有 Newow/HTDY/SuBing 专属计算提供统一注册与结果适配，不改公式身份、状态机和权限。

## B. Chart 包与现有显示迁移

- [ ] B1. 建立 `@guiyi/quant-chart` 独立 TypeScript 包，定义 Display Catalog、Renderer Registry 和 Chart Profile。
- [ ] B2. 实现共享 Main Pane、Volume Track、Auxiliary Pane、Pane Manager 和共同时间轴/光标同步。
- [ ] B3. 实现 Line/Histogram/Band/Marker/PriceLevel-Zone/Primitive 通用 Renderer。
- [ ] B4. 迁移 EMA/BOLL/Range Detector/Donchian 等公共主图图层；保留现有 Newow 主图 Primitive。
- [ ] B5. 迁移 Newow 四类副图和现有副图选择行为；默认仍为一个选中副图，新增多 Pane 只作为显式能力。
- [ ] B6. 保留并验证通用特殊成交量着色、SuBing 2x/3x 档位、Newow 自有成交量显示。
- [ ] B7. 将动作、Hint、Alert、委托/成交等业务事实作为独立来源图层接入，不转成技术指标。
- [ ] B8. 实现 Add/Hide/Remove/Configure/Retire、偏好 schema migration、Profile 默认配置和图层资源释放。
- [ ] B9. 实现指标诊断与 Compute Registry / Display Catalog 兼容性检查。

## C. 独立发布与消费者迁移

- [ ] C1. Quant Core 独立 SemVer、wheel/sdist、包内测试及 Release artifact。
- [ ] C2. Quant Chart 独立 SemVer、package tarball、类型/渲染测试及 Release artifact。
- [ ] C3. API/Web 消费者锁定精确包版本和 artifact hash；开发 editable/workspace 与正式锁定安装分离。
- [ ] C4. 独立版本化 formula/state/result/chart schema；验证不兼容消费者 fail-closed。
- [ ] C5. 更新 Newow MACD auxiliary 使用 TA-Lib 12/26/9 原始输出的 active delta；保持 Newow API envelope、as-of、physical owner、warming 和 research-display-only 边界。
- [ ] C6. 迁移 Web/牛哇/回测/快期/苏冰消费者到统一接口；每个消费者只请求自身需要的指标。
- [ ] C7. 执行 60 品种 × 7 周期性能、内存、缓存、增量恢复、计算隔离和图表视觉回归。
- [ ] C8. 完成独立 Review、OpenSpec strict validation、受影响测试和 develop 集成；同步已接受 delta 到 active specs 与 canonical。

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
