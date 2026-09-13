# 预警输入与盘后边界补充修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: 使用 superpowers:executing-plans 顺序执行。一个开发任务，模型固定 `gpt-5.6-sol`、reasoning `high`；独立 Review 也只使用 Sol high。不要另开开发任务或并行改同一 Runtime 文件。

**Goal:** 关闭最新审查确认的苏冰输入回归、盘后空评价假成功、日周状态失败后误发送三项问题，并补齐周一 60 身份 / 45 夜盘恢复集成回归，形成可审的精确补充候选。

**Architecture:** 保留共享 MarketRead/MDS authority，但在 Rule 的正式输入边界选择正确的完整性合同；HTDY 32 根 actual-dominant 与苏冰完整同物理生命周期不混用。canonical 与 Live 共享相同的结果登记和一次发送不变量，不建设新的 dispatcher、持久队列或恢复旁路。

**Tech Stack:** Python、pytest、SQLAlchemy、临时 SQLite Catalog、临时 Canonical Parquet、隔离 Redis、现有 RQData adapter 的 fake SDK seam。

**Spec:** `AGENTS.md`、`docs/DEVELOPMENT.md`、`docs/DATA_CENTER.md`、`openspec/specs/subing-ths-alert/spec.md`；审查报告 `/private/tmp/guiyi-alert-c7-review-20260913.md`。执行命令权威为 `TESTING.md`。

## 授权、基线和完成范围

- 用户已经明确要求“把这几个问题规划后安排 sol high 处理”；这授权本方案范围的实现、测试、独立 Review、普通提交与条件满足后的本地 develop 集成，不需再次申请同一设计批准。
- 编写时 develop 为 `e0f1fbde5bcd1414aef6507742d990ba5835b12c`，clean。其父 `c7bc03360d4c16cde128fa83c69cd5916f4b60bf` 是受审补丁；e0f1fbde5 只整理 STATUS，问题代码未变。本计划提交会成为后续基线的一部分，开工重新读 develop，不回退到 main 或旧补丁基线。
- Git 当前只保留主 develop 与现役 Runtime。上一 Sol 任务的 worktree 已清理，不在那里继续执行。使用新任务的原生隔离 worktree；若默认从 main 建立，在这棵隔离 worktree 内从最新本地 develop 建立 `codex/` 任务分支。不得更改主工作区分支或修改现役根。
- 现役仍为 `v1.10.8@82860ee3f5f63c49397ab11b0d0ab60c601376b9`，根 `/Volumes/扩展盘/guiyi-quant-runtime-v1.10.8-r1`。v1.10.8 recovery 根已由其他 owner 任务清理，不能用已删除路径或旧验证声称具备当前恢复能力。
- 此前主控向公开 origin 推送含本机现场材料的计划曾被自动审批拒绝；不要在新任务借换工具、换凭据、重试或委托绕过。此次开发先完成本地提交、Review 和本地 develop 集成，远端 push 单列 pending。若读回发现他人已推送，只记录事实，不认领该动作。
- 本方案不授权 RQData 真实调用、生产 DB/Redis/Canonical/Scope 写入、手工通知、重启、main/tag/release、Runtime promotion、定时恢复或周检重跑。
- 工作出口是修正后的 code/test/review 与精确候选，不是 RUNTIME_READY。必要验证有失败必须处理；范围外现场阻塞只阻塞对应操作，不阻塞独立代码修复。

## Global Constraints

- 不更改苏冰或 HTDY 公式、参数、公式版本、策略结果与收益口径。
- HTDY 仍用 actual_dominant 的逐 Bar rank1 owner，最后 32 根按 Calendar/Session 精确匹配；不能删除保护，也不能改为 current-contract-only。
- 苏冰仍用当前物理合约完整生命周期 replay；缺当前合约事实必须失败，合法旧主力缺口不能成为不属于该输入的额外前置条件。
- 保留 completed-only、strict-before、同频、冻结 identity、recovery revision、同 Bar 幂等、旧合约迟到单调保护和无历史 Event。
- Event 先 commit；只有成功跨过该次状态登记边界的消息才能进入一次发送；状态失败保留 Event，不重试、不补发，不扩大受众。
- 无 Scope、不相关频率、无匹配窗口、duplicate/stale skip 不冒充真实成功评价。真实成功后按既有合同更新当前状态，同时保留历史失败时间。
- 保留当前 HTDY `jm × 5m/15m + 其余 59 × 60m` 共 61 对、苏冰 `60 × 15m`；不得重新 PUT、启用 D1/W1 或重做 D/E/F。
- 不读取 `.env` 或凭据，不把隔离数据、fake SDK、测试 Event/sender 结果说成生产验收。不得联网补数或人工构造生产 snapshot。
- 不为本批机械跑无关 Web 全量构建、不顺手重构牛哇或盘后维护架构。可从 active root 只读借用解释器并显式设置源码 PYTHONPATH，避免写入 active root 或重装其依赖。

## Task 1：隔离 HTDY 与苏冰的完整性合同

**Files:**
- Modify: `services/quant-api/app/market_data/market_read_service.py`
- Modify: `services/quant-api/app/alerts/evaluators.py`
- Inspect/modify only if needed: `services/quant-api/app/market_data/market_data_service.py`
- Test: `services/quant-api/tests/test_market_read_service.py`、`test_alert_evaluator.py`、`test_alert_runtime.py`
- Contract: `docs/DATA_CENTER.md`、`openspec/specs/subing-ths-alert/spec.md`

**Interfaces:** 保留 `bars_until()` 的合并、cutoff、owner provenance、snapshot/recovery current 校验。建议将 c7 的 32 根额外证明抽成 MarketRead 的显式上下文校验方法，由 HTDY 正式 `evaluate_candidates(market_read, window)` 调用；底层继续复用 MDS `validate_actual_dominant_alert_window`。上下文长度由 HTDY 已有 `context_bars=32` 传入，避免再复制常量。苏冰正式入口只追加既有 `current_contract_replay_window` 的物理生命周期保护。日/周 Canonical 不调用日内 Session 端点验证。

- [ ] 在隔离 task 内读取 `/private/tmp/repro_c7_subing_real_mds.py`，把固定 fixture 和断言移植到仓库测试；不能用较弱的 8-bar fake-ready kernel 复现替代。该强复现使用真实 SQLite Catalog、临时 Parquet、真实 MDS/MarketRead 与正式苏冰 kernel。
- [ ] 固定 RED：当前合约从上市日到 cutoff 的 120 根完整，旧 owner 缺一根，actual-dominant 页 64 根；苏冰应成功并产生固定的一个 Candidate，目前却在 `bars_until` 抛 `MARKET_READ_WINDOW_INCOMPLETE`。保留测试中逐端点完整性与期望 Candidate 断言。

```python
assert len(current_physical_bars) == 120
assert len(actual_page.bars) == 64
# 以上变量来自强复现同名数据迁入后的 fixture；这里断言业务结果，不能 mock kernel ready。
window = market_read.bars_until(query, trading_day=day, end=cutoff, limit=64)
candidates = SubingThs15mEvaluator().evaluate_candidates(market_read, window)
assert len(candidates) == 1
assert candidates[0].bar_end == cutoff
```

- [ ] 最小移动校验责任；evaluator 不直接读 DB、Session、Catalog 或文件。所有正式 HTDY 调用者必须跨过新校验 seam；不要以默认关闭 boolean 给调用者静默绕过的入口。
- [ ] 同一 fixture 让 HTDY 仍拒绝旧 owner 缺口；修回该 Bar 后 HTDY 原固定信号保持。补苏冰当前物理合约缺一根仍失败、换主力不继承旧状态、重复失败 cutoff 不清健康。
- [ ] 回归 5m/15m/60m 缺口、合法 owner 转换、当日 MainMap 未发布但冻结 identity 有效、Session 午休/周末/短桶；确认无关 Web history/observation 行为不变。
- [ ] 按 TESTING 的定向组跑 GREEN，检查 diff 后提交本项；不得删保护或降低旧断言让测试通过。

## Task 2：canonical 空评价与失败发送边界一次修齐

**Files:**
- Modify: `services/quant-api/app/alerts/runtime.py`
- Test: `services/quant-api/tests/test_alert_runtime.py`、`test_runtime_health.py`
- Contract: `openspec/specs/subing-ths-alert/spec.md`

**Interfaces:** `_process_canonical_updated` 以每个 Rule/symbol/frequency 的真实评价结果决定是否登记成功；每次评价使用局部待发送列表，成功登记该次状态后才合并到总列表。保留现有 `_record_rule_result`、`_record_processing_result`、`_send_messages_once` 和独立 Rule/品种隔离。必要的小型共用 helper 可以抽取，但不复制第二套状态策略或重建 dispatcher。

- [ ] 读取 `/private/tmp/test_canonical_status_boundary.py`，把两个用例移入正式测试，先确认 RED。

```python
# test_canonical_event_status_failure_must_block_sender
assert session.scalar(select(func.count()).select_from(AlertEvent)) == 1
assert sender.calls == 0
# test_unscoped_canonical_update_must_not_clear_processing_failure
assert status_after["processing_error_type"] == status_before["processing_error_type"]
assert status_after["last_processing_success_at"] == status_before["last_processing_success_at"]
```

- [ ] 以 D1 和 W1 参数化状态首次失败后恢复的场景；同时覆盖持续失败。Event 必须保留，当前失败项 sender=0；日志不得伪报 recovery guard。测试 sender 是内存 fake，不能使用真实 transport。
- [ ] 修正无 D1/W1 Scope、规则关闭、没有触发日匹配窗口等零实际评价路径：保留之前的全局失败和成功时间，不更新成一次成功。不是把所有 canonical 消息都无条件当作失败。
- [ ] 正常无信号属于一次真实成功评价；后续实际成功按现有 Rule/global 合同恢复当前状态，并保留 last_failure_at。typed evaluation error 的 Rule 与 global 语义按 canonical 区分，不吞掉异常。
- [ ] 补同一 Event 重复 canonical_updated 不补发、不重复 commit；一项失败不丢弃其他独立成功项已经获准的待发送消息，也不能将失败项消息混入其他项列表。
- [ ] 保持 Live 的 typed skip、状态失败禁止发送、guard enter/exit 公开分类回归。若发现共享小 helper 可同时防止两分支漂移，按测试结果做最小抽取，不能强迫两套输入路径合并。
- [ ] 定向测试 GREEN，自审后提交本项。

## Task 3：补足 60 snapshot / 45 夜盘的真实恢复链隔离回归

**Files:**
- Modify/test: `services/quant-api/tests/data_foundation/test_live_recovery.py`
- Reuse tests/seams: `services/quant-api/tests/data_foundation/test_live_market.py`、`test_market_read_service.py`、现有 provider adapter 与 Lua 隔离测试
- Inspect, only change on reproduced bug: `services/quant-api/app/market_data/live_recovery.py`、`live_market.py` 及现有 RQData adapter

**Interfaces:** 正常 Live snapshot 冻结入口 → 真实 Catalog Session authority → 现有 recovery request → 真实 provider adapter（SDK 网络 seam 注入固定响应）→ `recover_product` → Redis store/聚合 → MarketRead。只能 fake 外部 SDK/隔离存储，不能用 RecordingWorker 代替核心恢复或用 lambda Session 列表代替被验收的 Session resolver。

- [ ] 保留现有 `test_monday_open_freezes_60_contracts_and_schedules_45_night_prefixes` 作为调度单测；补集成测试，不把单测原有通过重命名成全链通过。
- [ ] 在隔离 Catalog 构造完整周五至周一 Calendar、60 product/contract identity、45 有夜盘与 15 无夜盘的明确 Session。合约为隔离 fixture，不宣称是周一真实 rank1。
- [ ] 由正常入口产生 60 冻结 snapshot 和 recovery requests；真实 resolver 将周五夜盘归属周一交易日。SDK spy 记录精确 contract、`1m`、目标交易日 2026-09-14，而不是以周五自然日期误请求。
- [ ] 通过真实 adapter 和 `recover_product` 完成这批隔离恢复；检查 SDK 请求只覆盖存在完整前缀缺口的合法目标，日盘品种在日盘尚未形成 completed 端点时不得凭空请求夜盘。
- [ ] 周一开盘与后续 cutoff 分阶段验证：15m/60m 的完整端点/owner/OHLCV 一致，短 Session 尾桶按 authority 解释；未完成桶不进入正式评价。所有预期端点由真实 Session authority 推导，不能用输出自身作为唯一 oracle。
- [ ] 固定失败注入：少一根夜盘分钟、错 trading_day、错 physical contract、future bar、snapshot 漂移。均不得提交不完整结果或发布历史消息；合法恢复不产生 AlertEvent/通知，下一新 completed trigger 才可跨 recovery barrier 评价。
- [ ] 通过前应有明确断言，例如：

```python
assert snapshot == expected_60_contracts
assert night_target_symbols == expected_45_symbols
assert all(call.frequency == "1m" and call.trading_day == monday for call in sdk_calls)
assert actual_completed_endpoints == expected_session_endpoints
assert recovered_bar_publications == []
assert historical_event_count == 0
assert sender.calls == 0
```

以上名字在集成 fixture 中明确绑定实际 SDK spy、Session 计算与存储/事件读回；不是新增生产 API。
- [ ] 若回归揭露现有恢复实现中的本批相关 bug，先证实根因，再在原 Session/身份/幂等合同内最小修复并复审。若修复必须新增周末运行合同、重试范围或生产身份来源，停止该变更并报告，不绕过入口。
- [ ] 实际 Lua 验证使用 TESTING 规定的一次性无卷、独立端口 Redis；只操作该精确测试实例，结束后清理。不得使用已有生产 Redis；若工具权限阻止启动，保留测试 Gate 未完成并继续其他工作。

## Task 4：整批验证、独立 Review、集成与交付

**Files:** `TESTING.md`、对应 canonical、`STATUS.md`；只改本任务实际影响的说明。

- [ ] 开始执行时在任务工作区修正 STATUS 中“候选全部修复”的过时结论，记录本批 REVIEW_REOPENED；不修改现役历史事实。完成后再写新 SHA 和真实阶段，不能提前宣称新代码生效。
- [ ] 将新增可执行测试命令写入 TESTING。先跑新复现，再运行 MarketRead/evaluator/Runtime/health、两 kernel/registry/service/API/notification/Scope、Live recovery/adapter/Session/Lua 的相关组。上一轮 364 passed / 1 skipped 和两个 RED 只作基线，不作本次结果。
- [ ] 运行受影响 Ruff、Mypy、文档引用/工程、OpenSpec strict、secret scan、git diff --check。完整后端测试按 Runtime/MarketRead 影响运行一次；无新变更或失败原因时不机械重复。
- [ ] 完成自审后让独立 Sol high Review 精确 base..candidate diff；不得只看测试数。审查必须重新验证：旧 owner 不阻塞合法苏冰；HTDY 仍拒绝缺口；canonical 零评价不回绿；status failure 不发送；同 Bar 不补发；45 夜盘真的走 adapter/recover 而非仅调度。
- [ ] 有实质发现就修正、重跑影响范围并复审；全部通过后 commit 并按当前 clean/并发状态本地集成 develop。若 develop 新增无关修改，保留它们，只解决本任务冲突；不能强制覆盖。
- [ ] 精确记录候选 commit、测试命令及结果、Review、生产零 mutation、尚未执行的远端 push/release/Runtime/natural Gates。已完成计划按仓库规范从 Git history 追溯，不建立第二套长期状态账本。
- [ ] 不为了清理去删除主 develop、现役 Runtime、其他任务 worktree。任务 worktree 的清理只在确认集成后按原生能力处理；无法安全自清则留作已合并待清理。

## 验收出口与唯一下一步

工程成功：上述三个行为正式回归 GREEN、夜盘集成证明完成、相关验证与独立 Review 通过、补充修复本地集成并冻结精确候选。
若隔离测试/Review 未通过，结论仍为要求修正后再集成，不得把问题移成已知限制以绕过候选 Gate。

交付用中文说明完成项、精确 SHA、实际测试、Review、未完成 Gate 和一个最小下一步。开发完成后先给可审候选；远端 push、发布与 Runtime 切换按各自边界处理，后续自然窗口另验 snapshot → 45 夜盘/当日完整输入 → 新 completed 评价 → 有信号时 Event/transport/收件。不执行这些真实动作，不重做 Scope 或 D/E/F。
