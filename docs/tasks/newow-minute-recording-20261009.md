# Newow 短分钟持续记录

## 交付范围

在原日/周/60m四策略720路基础上，新增5m/15m/30m趋势、震荡、独立双策略540路，合计1260路。短分钟主升浪与Newow 1m保持关闭；不改变公式、参考价格、收益、通知、订单或账户语义。

统一recording scope用于bootstrap、矩阵、健康、worker分组和历史刷新。360个product/frequency key共用有界调度，基础状态先于融合保存。MarketReadService沿用同物理合约、Session、rank1、已确认Live来源和端点完整性校验；四分钟频率均保留收盘末根读取及同频Canonical核对。

capability v33六周期使用最新已发布completed Canonical，显式intraday_as_of=null；旧v31/v32证据与preview合同保持。主图历史计算不直接混入Live。持续记录面板显示实际观察的动作、Hint与逐K状态，空动作不是空状态。matrix v4枚举1260路，bootstrap scope v2可以精确选择新增三频九路，既有720路不重置。

## 验证

- 定向completed读取/页面截止：44 passed；扩展所有周期的重复、未来、错owner、缺Session拒绝。
- reference_trading模块（not isolated_postgresql）：513 passed / 3 skipped / 49 deselected，22.51s。
- capability/reader/readiness/diagnostics定向修复后：450 passed，1.98s。
- 隔离PostgreSQL：12 passed / 50 deselected，67.57s；1260路真实内核持久化、融合依赖顺序、重启幂等和事务校验。专用库guiyi_isolated_newow_minute_20261009，不连接生产作测试写入。
- Web三个定向测试文件53 passed；pnpm build含typecheck/topology通过。
- Ruff、secret scan（0 findings）、git diff --check通过。OpenSpec严格验证10/10通过。
- 独立Review：162 passed / 2 PostgreSQL skipped；未发现阻止集成的Confirmed Issue，允许集成develop；隔离PG另覆盖相关验证。

首次扩大reference+newow回归为3438 passed / 13 failed / 4 skipped，失败原件保留：10项诊断夹具在原develop同样缺replay_coverage字段，已仅补齐fixture初始化；其余3项为本轮capability序列化/版本断言，修正并定向复测通过。不能把首次扩大回归表述为全绿。

## 现场边界

生产只读preimage表明：当前720路forward均enabled，primary中尚无5m/15m/30m的Newow历史资产和forward route。本轮未生产构建、启用、迁移、通知、发布或切换Runtime；当前正式运行仍v1.14.5。

RB已只读冻结六份基础历史计划，输入分别55941/18649/9735 Bar；融合计划因基础资产尚未构建而返回REFERENCE_FUSION_SOURCE_NOT_READY，是依赖顺序，非允许绕过。后续先精确计划/apply基础六路，再计划/apply融合三路，最后在新鲜已完成来源、精确checkpoint、recording_start及Scope hash核对后启用九路。历史prewarm不算自然观察，旧720观察身份与时间保持。

代码和集成不证明线上逐K记录或牛哇完整页面parity。正式启用前须证明540主库历史资产可读、生产配置和来源新鲜度；切换后需实际自然completed Bar、吞吐、缺口及Live→Canonical readback。自然业务未发生时不补造验收，不新增后台监控。

证据位于任务worktree的output/newow-minute-recording-20261009/，包括生产只读preimage、隔离pytest原件与RB只读计划；不作为当前Runtime事实。
