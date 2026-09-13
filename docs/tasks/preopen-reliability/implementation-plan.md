# 开盘预警可靠性修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans task-by-task. Steps use checkbox tracking.

**Goal:** 修复已复现的恢复队列预算耗尽与 HTDY Live 合约归属缺口，连续完成实现、验证、独立 Review 和 develop 集成。

**Architecture:** 保持 LiveRecoveryWorker 单后台线程与前台 Session/snapshot authority；在缺口分支领取 provider 预算前验证请求时钟，过期项不消耗预算，由下一轮正常调度重建请求。MarketReadService 的共享预警窗口复用现有 typed LiveBarObservation seam，逐 Bar 证明合约与交易日，不再从 snapshot 猜原始 payload 身份。

**Tech Stack:** Python、pytest、SQLAlchemy SQLite fixtures、FakeRedis、专用一次性 Redis Lua 验证。

**Spec:** `docs/DATA_CENTER.md` 当日 Live 缺口恢复；`openspec/specs/subing-ths-alert/spec.md` HTDY 输入与恢复水位合同。Owner 本轮明确要求先规划并直接一次性修复；前轮两项缺陷及最小修正已说明。

## 全局约束

- 基线 `ef2e087d1bec3af3b376e5051821e4674955f657`；范围为两个已证实缺陷及直接受影响的接口、测试和 canonical。
- 保留 60 秒提交时效、每品种每 Session 最多三次 provider 尝试、60 秒最小调度间隔、单 worker、权限/额度 circuit、Lua CAS 与共享锁。
- 不刷新后台 cutoff，不增加预算，不发布恢复历史 Bar，不补发旧通知，不清除历史失败。
- 策略公式、Rule、Scope、物理合约映射、盘后更新、真实通知、生产数据和 Runtime 配置不修改。
- Git 外审计数据与脚本只作本次回归辅助，不成为测试依赖；正式测试使用仓库自有合成 fixture。
- 命令只维护在 `TESTING.md`；本计划不复制命令矩阵。发布、Runtime promotion、实际补数各需另行精确意图。

## Task 1：恢复预算前的时效校验

**Files:** `services/quant-api/app/market_data/live_recovery.py`；`services/quant-api/tests/data_foundation/test_live_recovery.py`；`services/quant-api/tests/data_foundation/test_live_recovery_queue.py`；`docs/DATA_CENTER.md` 及相关 active spec。

**Interface:** 沿用 `recover_product(store, request, fetch, *, clock, commit_guard)` 与稳定错误 `LIVE_RECOVERY_CLOCK_INVALID`。缺失 1m 的分支在 `CLAIM_ATTEMPT` 前验证 `0 <= clock - request.cutoff <= 60s`；最终提交仍独立验证新时钟。纯 NO_GAP 无 provider/预算写入，既有幂等语义保持。

- [x] RED：过期请求不调用 provider factory/fetch，Redis预算、circuit、bars及水位不变；新鲜下一轮可成功。
- [x] RED：模拟60品种/45缺口的慢队列，新请求逐轮收敛，过期排队不能耗尽后排三次预算。
- [x] GREEN：提取同一时钟校验供预算前与提交时使用；没有隐藏 retry 或后台 authority 变更。
- [x] 验证 exactly 60 秒边界、未来/naive时钟拒绝、真正慢 fetch 仍计一次并拒绝超时提交、重启不重置预算。
- [x] 验证恢复后仍不发布历史bar、旧cutoff不具备通知资格，下一新鲜completed窗口保持资格。

## Task 2：预警窗口逐Bar provenance

**Files:** `services/quant-api/app/market_data/market_read_service.py`；`services/quant-api/tests/test_market_read_service.py`；直接依赖的 fixture；`openspec/specs/subing-ths-alert/spec.md`。

**Interface:** 使用既有 `bar_observations(trading_day, symbol, frequency, None, cutoff, inclusive_after=False, expected_contract=contract)`；只合并身份验证通过的 CanonicalBar。保持公开 `MARKET_READ_LIVE_UNAVAILABLE` 分类和 snapshot/recovery 双重读回。

- [x] RED：错误、缺失、非规范合约，错误交易日、重复端点及非法 typed observation 均失败；覆盖 JM 5m/15m 与其它品种60m。
- [x] GREEN：在共享 `bars_until` 入口读取 typed observation 并验证类型、contract、trading_day、cutoff、唯一端点；跨 Canonical/Live 相同事实仍允许去重，冲突拒绝。
- [x] 验证合法跨主力历史窗口、正确Live窗口、苏冰 replay、恢复水位与 Web 共享调用没有退化。
- [x] 移植审计最小复现为仓库测试，测试不依赖 `/private/tmp`、生产数据库或真实行情。

## Task 3：集成验证与交付

- [x] 更新 active canonical 及 TESTING；不建立新的并行 resolver 或恢复状态schema。
- [x] 跑定向MarketRead/Alert/Recovery/Live/health及盘后组、真实隔离Redis原子性测试；按差异运行静态与工程检查。
- [x] 独立 Review：核对计划/实现一致、budget不浪费、时钟仍fail-closed、身份不丢失、恢复/通知/盘后不串线。
- [x] 无未解决的重要 Review 发现；更新代码、测试和 Review 状态，形成可提交并集成 develop 的候选。
- [x] 在 STATUS 记录测试证据和剩余发布与 Runtime Gate；交付时读回精确 Git 提交。代码通过不承诺明日首个信号或真实收件。

## 验证结果与交付边界

- Task 1 RED：5 failed / 3 passed；Task 2 RED：21 failed。修复后完整后端 3692 passed / 16 skipped / 31 deselected。
- 单独一次性 Redis Lua：1 passed；容器已移除。独立 Review：218 passed / 1 同一可选 Redis skip，无阻塞问题。
- 工程一致性 22 passed；OpenSpec 9 passed；定向 Ruff/mypy、secret scan 和 diff 检查通过。
- 首次工程检查因新 worktree 缺依赖失败；确认锁文件相同后复用现有开发依赖，原检查复跑通过。未修改依赖或锁文件。
- 普通 develop 集成按本轮授权执行；main/tag/release、Runtime 切换、生产数据与真实通知不在本次执行范围。
