# 盘后增量修复与遗漏数据恢复

## 目标

允许 Runtime-bound current-day metadata 与 daily recovery 在严格验证的合法 schema-v3 failed 终态上运行，恢复 operational 60 品种截至 2026-09-22 的遗漏增量，补齐 2026-09-23 自然盘后前置元数据，并准备精确发布候选与 Runtime promotion。

## Task 1：failed 终态恢复绑定

- 先增加失败测试：合法 schema-v3 `failed/UPDATE_FAILED` 可建立 recovery binding；损坏状态、产品范围不一致、时间顺序异常继续拒绝。
- 新增仅供 daily/current-day recovery 使用的 failed-terminal 模式；closeout、interrupted 与 promotion 行为不变。
- 将 binding 失败分类为有界公开错误码，CLI 不再退化为空 `ValueError`。
- 运行 closeout binding、daily recovery、current-day metadata 与 promotion 定向测试。

## Task 2：Calendar 夜盘与恢复回归

- 重跑周一 ISO 周 Calendar/night authority、下一交易日 Session 与 rank1 的既有回归。
- 如测试暴露缺陷，先增加失败用例再修正 metadata 共享实现。
- 运行 metadata、after-market、historical session preservation 回归。

## Task 3：候选验证和独立 Review

- 运行定向测试、相关完整模块测试、diff/secret 检查和 Web/launchd render-only。
- 提交代码并执行一次全分支独立 Review；重要问题按 TDD 修复。
- 形成精确 release candidate，记录 commit/tree、测试和 rollback root。

## Task 4：受控 metadata 与 daily recovery

- 只从受审候选 CLI 绑定现役 Runtime/status，按日期 capture → plan → apply 9 月 21–23 日所需 metadata；9 月 23 日仅写已由 source 证明且合同允许的事实。
- 生成截至 9 月 22 日的 exact daily recovery plan；若出现更早缺口，停止并报告，不扩大批次。
- 使用 exact plan hash 执行一次 apply，随后独立读回 rank1、Catalog、Parquet、七周期和消费者状态。

## Task 5：发布与 Runtime 切换

- 将候选集成 develop 并准备 release PR、annotated tag、GitHub Release 和独立 Runtime root。
- 发布和 Runtime promotion 使用精确候选 Gate；fresh preflight 通过后切换已启用服务。
- 核对服务身份、HTTP/health、自然 Live 与 18:05 调度；自然盘后完成前不声明 RUNTIME_READY。

## 全局边界

- 保留 9 月 21、22 日失败事实，不手工运行 after-market，不新增 retry、Scope、通知或订单行为。
- provider/metadata、Canonical/Catalog、release 与 Runtime mutation 各自使用精确计划和 readback。
- 任一 partial、commit unknown、身份漂移或 preflight block 立即停止受影响 mutation，不自动重试。
