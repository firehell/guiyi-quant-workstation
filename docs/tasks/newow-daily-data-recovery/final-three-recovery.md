# B / BZ / PG D1 恢复工程收口

2026-09-17。目标截止仍为 2026-09-15；当前累计候选验收 57/60，未据此更新完成状态。

## 已实现

- 复用 `newow_weekly_recovery` 的显式 D1 路径，提交后通过 Catalog 固定文件、Parquet 质量校验和 MDS 权威 Calendar/Session 逐端点读回；有效 Bar 与已核实 PRICE_UNAVAILABLE 必须恰好覆盖目标窗口，无遗漏、重复、重叠或错日。W1 及普通严格读取保持原合同。
- manager 返回后、独立 replan/readback 前，将原始 typed 执行结果落为 `warmup-result.json`；完整单元结果仍为 `unit-result.json`，两者用途不同。stdout 不再充当恢复成功的唯一凭据。
- journal、source response 和结果文件都检查写入字节数及 fsync；失败保留现场并停止，不执行下一单元或自动重试。
- CLI `provider_request_count` 是计划值，`provider_requests` 是实际值。

PG2410 / PG2411 旧执行使用独立 CLI 和 shell 管道，排除 Python redirect_stdout 默认参数假说；历史日志不足以确认 stdout 丢失根因，不能宣称已修复其底层原因。两者所需窗口只读重规划归零，不重新执行，也不补造旧 terminal 回执。新执行路径用已有来源日志及持久化结果解除对 stdout 的依赖；硬终止或收据缺失仍按未知结果停批，必须独立只读核对。

## 验证

- 恢复执行器、campaign、source verify、partial exception、CLI、Catalog/MDS、storage：421 passed。
- daily verification、HistoricalDataManager、CLI：282 passed（与上组有重叠，不相加）。
- 独立 Review 发现并关闭短写问题；复核三个相关测试文件 205 passed，允许集成 develop。
- Ruff 定向检查与 `git diff --check` 通过。
- 测试包括真实 SQLite/Parquet 普通、混合缺价和全缺价月；端点缺失、冲突、错日、回执失败停批、零写入和短写。测试使用隔离 fixture，未下载行情或写生产。

## 后续真实批次边界

重新冻结 B2411、BZ2605/BZ2610、PG 17 合约的原生计划、源请求、配置/Canonical/代码身份，再提交 owner 一次确认。每个合约使用牛哇实际所需 through，不给已到期合约扩展生命周期尾部。此前只读估计为 20 合约、182 目标月、3,526 待补端点；以新 prepare 为准。

按 B → BZ → PG 串行；任一未知来源异常、身份漂移、结果/收据不明或读回失败停止，保留已提交分区，不重试、不回滚、不扩范围。正式动作只涉及获批物理 D1、Catalog 及既有派生首页投影失效；不包含 Runtime、发布、通知或其他周期。

数据批次完成后才运行 B/BZ/PG 九个页面验收，并在同一 exact commit 和固定截止重验 60 品种、180 个首次加载三策略页面及历史参考收益。最新已完成交易日增量另做只读核查，新增缺口不得静默并入本批。
