# 苏冰与火天大有预警修复及开盘准备 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. 只安排一个开发会话，模型固定 `gpt-5.6-sol`、reasoning `high`；需要独立审查时，审查者也只能使用 Sol high。

**Goal:** 修复 HTDY 不完整输入、苏冰失败去重/健康失真、共享错误误分类三个问题，验证已启用的 60 品种 HTDY Scope，并如实收敛 9 月 14 日夜盘输入恢复与自然验收。

**Architecture:** 保留模块化单体、唯一 MDS/MarketRead 输入与现有两套 kernel。通过现有 Calendar/Session/owner authority 证明 HTDY 的计算窗口完整，区分苏冰实际评价与去重，按真实失败阶段记录公开错误。生产 Scope 已由主控在本轮完成；周末恢复受现有身份和时钟合同阻断，开发任务不创建替代 snapshot 或旁路 provider。

**Tech Stack:** Python、SQLAlchemy、PostgreSQL Catalog、Redis Live、pytest、现有 guiyi CLI/API、OpenSpec。

**Spec:** `AGENTS.md`、`openspec/specs/subing-ths-alert/spec.md`、`docs/DATA_CENTER.md`、`docs/INDICATOR_KERNEL.md`；独立审计证据 `/private/tmp/guiyi-alert-preopen-20260913/conclusion.md`、`subing-review.md`、`htdy-transport-review.md`。

## 授权和基线

- 用户本轮明确要求“三个问题全部修复、全部规划好后安排一个 sol high 会话开发”。前轮已解释三项问题与最小方向；本方案范围内可连续实现、验证、独立 Review、commit/push 和 develop 集成，不机械追加设计确认。
- 现役 immutable Runtime：`/Volumes/扩展盘/guiyi-quant-runtime-v1.10.8-r1@82860ee3f5f63c49397ab11b0d0ab60c601376b9`。
- 编写时 develop：`505b73d737cc31c2ac2169bbb1ba6bc3b15be99d`，原有工作区 clean。这个提交整理了文档和孤立代码，不能退回审计时的旧 develop SHA；开工必须重新读 diff 和当前 HEAD。
- 在 Codex 原生新 worktree 执行。原生任务若默认从 main 建立，应在其已隔离的 worktree 内从最新本地 develop 建立本任务分支；不要修改 develop 主工作区、Runtime 或 recovery 根。此方案提交应随 develop 带入；不可遗漏本轮新 Scope 事实。
- 所有真实 provider、DB/Redis/Canonical 写入、通知、Scope、release、Runtime 操作依然各有独立边界。用户的本轮 Scope 单次意图已被下述成功批次消耗；新会话不得重做。
- 用户希望周日直接补齐夜盘；本轮新读回显示现行入口不能执行。此意图不授权虚构冻结 rank1、修改 Calendar、调用内部函数绕过入口、改变时钟或跨会话继续失败/blocked 的真实操作。

## 已完成的现场动作，禁止重做

2026-09-13T02:22:46Z，本轮用户明确要求后，主控从现役 API 对 operational 中除 `jm` 外的 59 品种各执行一次 `60m enabled=true`，逐项及全量 GET 读回通过。

- HTDY：60 品种、61 对；`jm=[5m,15m]`，其余 59 品种各 `[60m]`。
- 苏冰：60 品种各 `[15m]`，保持原值。没有增加焦煤 60m、其他周期、Rule、audience 或手工通知。
- 精确计划 SHA-256：`a8c2c5758461e89697e2375dff3a89b120bae5e86b5a2f3db53fca901841c6e3`。
- 证据：`/private/tmp/guiyi-alert-fixes-20260913/scope-plan.json`、`scope-apply.json`；执行 `status=passed`、59 项成功、HTDY 61 对、苏冰 60 对。
- 当前全休市；Scope 写入不是补丁上线或自然预警成功。已知 HTDY 输入缺陷也适用于新开启周期，60m 必须纳入修复和回归。
- 撤回需要新的精确意图，并通过既有 API 只关闭本批新增的 59×60m；不能全清 Rule Scope，也不自动回滚已成功项。

## Global Constraints

- 不修改苏冰/HTDY 公式、参数、公式版本或策略结果口径；不把信号修复做成 formula patch。
- HTDY 保留 actual_dominant 和既有各 Bar owner 语义，不擅自把跨主力合法策略窗口换成只取当前物理合约；SuBing 仍只使用完整同物理生命周期 replay。
- completed-only、strict-before、无 future tail、同频、Session/coverage/物理事实失败即拒绝。
- 不用连续时钟间隔判断交易连续性：午休、周末、夜盘、短 Session bucket 均由权威 Session 解释。
- Event 先 commit；真实 transport 最多一次；状态/CAS 失败 fail-closed；不新增 retry、replay、outbox、fallback、历史 Event 或测试推送。
- 保留 `alert:runtime-status` schema v6 的 bounded 字段与历史失败；不通过清状态、acknowledgment 或扩大健康条件使页面变绿。
- 保留 v1.10.8 不可变、D/E/F 和本周 840/840、120/120 既有证据。不重新维护整段历史，不重新启用周检，不推进无关牛哇开发。
- 发布与 Runtime promotion 未在本轮批准。修复完成后只冻结精确候选和待执行材料，不能发布或切换。
- 新代码/测试/文档必须有真实结果；审计中 490 passed 和 5 项故障复现是旧基线证据，不是修复版验收。
- 命令权威仍为 `TESTING.md`；新增可执行诊断/测试说明写在该文件，方案中使用测试文件/用例定位。

## Task 1：HTDY 窗口完整性，优先完成

**Files:**
- Modify: `services/quant-api/app/market_data/market_read_service.py`
- Modify if needed: `services/quant-api/app/market_data/market_data_service.py`
- Modify: `services/quant-api/app/alerts/evaluators.py`
- Test: `services/quant-api/tests/test_market_read_service.py`、`test_alert_evaluator.py`、`test_alert_runtime.py`
- Contract: `openspec/specs/subing-ths-alert/spec.md`，确需共享输入说明时更新 `docs/DATA_CENTER.md`。

**Interface responsibility:** `MarketReadService` 负责证明已解析窗口完整；需要新的 Calendar/Session/owner 查询时下沉至 MDS，evaluator 不直接查表、拼文件或复制 coverage resolver。保持既有 `evaluate_candidates(market_read, window)` 的消费者边界；不影响无关 Web 读页。

- [ ] 将 `/private/tmp/guiyi-alert-preopen-20260913/repro_htdy_15m_gap.py` 的合法 Session fixture 固定成仓库测试，移除运行期随机搜索。固定 full=buy、删除合法 Live 中间 Bar 后必须公开失败，不能返回普通空候选；先验证 RED。
- [ ] 增加 5m、15m、**60m** 的合法缺口案例；至少包含“数量仍超过 32 且 cutoff 存在”与“同一缺口修复后 full 结果保持”两个断言。
- [ ] 增加周五夜盘归周一、午休/周末合法间隔、短 Session 尾桶、历史与 Live 边界、合法换主力 owner 片段、当日 MainMap 未发布但 frozen Live identity 有效的正向用例。
- [ ] 最小实现：在 HTDY kernel 使用最后 32 根之前，通过既有权威计算该参与窗口从首根到 cutoff 的预期同周期端点及 owner；逐端点匹配、无缺失/重复/额外/错交易日，才能计算。authority 不可读时公开失败，不缩窗、补值或回退另一序列。若证明完整窗口所需的历史分页不足，沿正式分页读取，不能悄悄减少 warm-up 根数。
- [ ] 保留 SuBing lifecycle replay 的现有严格保护，不强制整个 HTDY 同物理生命周期预热，也不要求未来日 Canonical 主力映射。
- [ ] Runtime 测试确认缺口时无 Event、无 sender、Rule error 为公开输入/评价失败；恢复本身不 publish 历史消息，下一合法自然 cutoff 才可产生新事件。
- [ ] 运行定向测试并自审 diff；提交可独立审查的 Task 1 变更。

## Task 2：苏冰失败去重与健康事实

**Files:**
- Modify: `services/quant-api/app/alerts/evaluators.py`、`runtime.py`
- Test: `services/quant-api/tests/test_alert_evaluator.py`、`test_alert_runtime.py`、`test_runtime_health.py`
- Contract: `openspec/specs/subing-ths-alert/spec.md`。

**Interface responsibility:** evaluator 必须能让 Runtime 区分“这次实际成功评价”“成功旧 Bar 的去重”“前次未成功评价”；不能把三者都当作空候选成功。选择最小显式结果或 typed skip 机制，并同步所有正式调用者和 tests；不为此增加第二套 evaluator 或新的持久状态账本。

- [ ] 移植 `/private/tmp/guiyi-alert-preopen-20260913/test_subing_review.py` 中失败 cutoff/同 Bar 重复场景，改成期望正确行为；先 RED。
- [ ] 新测试固定：invalid/warming 后相同 cutoff 重复时，未实际成功重评不得清 Rule error、不得更新成功评价时间；后续真正成功的 15m 评价可以清当前错误但保留 last_failure_at。
- [ ] 读取并尊重当前 `test_subing_invalid_continuity_break_updates_cursor_without_candidate` 的状态连续性意图：纯 kernel 状态推进不等于评价成功。不能简单回滚所有 warming 状态导致永远无法预热，也不能用调整旧断言掩盖失败。
- [ ] 实现对失败结果与成功去重的明确处理。正常无信号必须仍是实际成功评价；正常重复不得生成第二条 Event/通知，也不得冒充一次新的成功评价来清除其他失败。
- [ ] 补充新主力之后迟到旧交易日/旧合约的单调保护测试；只有与真实当前窗口相容的 cutoff 可以被接受，不恢复旧合约游标或产生历史 Candidate。fixture 明确旧 snapshot 异常共存，不宣称当前生产会自然乱序。
- [ ] 针对“Candidate 后 Event commit 失败、同 Bar 重复、下一 Bar”增加集成测试记录当前 no-replay 边界和真实失败状态。**本批不新增重试/补发语义**；若修复去重必须改变此合同，停止该分支并报告精确选择，Task 1/3 等可独立部分继续。
- [ ] 验证成功路径 batch/incremental/restart/rollover parity、缺历史 fail-closed、仅最终 cutoff Candidate 和未来尾部隔离均保持；提交 Task 2。

## Task 3：共享 Runtime 错误误分类

**Files:**
- Modify: `services/quant-api/app/alerts/runtime.py`
- Inspect/modify only if needed: `services/quant-api/app/runtime_logging.py`。
- Test: `services/quant-api/tests/test_alert_runtime.py`、`test_runtime_logging.py`。

**Interface responsibility:** `ALERT_RECOVERY_GUARD_UNAVAILABLE` 只能对应 guard 获取/释放失败；处理体的 DB、status、evaluator、transport 编排失败保留各自实际阶段的 bounded 公共分类。日志不是新的状态权威，不改变失败后的 fail-closed 控制流。

- [ ] 移植 `/private/tmp/guiyi-alert-preopen-20260913/repro_alert_boundaries.py` 的 Event commit 后 status 异常：先 RED，断言没有伪报 guard failure。
- [ ] 分别注入 guard enter、guard exit、内部 status、内部 DB 和 evaluator 异常；确认恢复锁失败与处理失败可区分，错误传播/隔离符合既有合同。
- [ ] 最小调整异常边界。必要的脱敏诊断只保留 Rule、symbol、frequency、trading_day、cutoff 和公开错误码；不记录 provider 文本、SQL、地址、stack、凭据。
- [ ] 验证 status/CAS 失败仍不发送；Event 保留；不能为了日志准确而吞掉状态错误、刷新成功状态或调用 sender。后续不相关品种在合同允许的隔离范围继续。
- [ ] 验证日志 formatter 的白名单和 secret 测试，提交 Task 3。

## Task 4：已启用 Scope 与真实 60m 输入验收

**Files:** reuse `services/quant-api/app/api/alerts.py`、`app/alerts/service.py`、现有 MDS/MarketRead；只读报告放一次性任务 evidence 路径，最终状态归 `STATUS.md`。

- [ ] 首先读取主控 scope-apply 证据，fresh GET 验证现役 Scope 为 HTDY 61 对/苏冰 60 对。若变化，只报告前像差异；**不执行新的 PUT、SQL 或整体替换 Scope**。
- [ ] 以真实已完成交易日、当前 Catalog rank1/actual_dominant 入口，逐个核验新启用的 59 品种 60m 至少具备 HTDY 所需合法 completed context；JM 5m/15m 一并核验。历史只读诊断不构造生产 Live snapshot，不执行真实 evaluator Runtime/Event sender。
- [ ] 与 Task 1 的 60m 测试对应：休市边界、午休、夜盘和 owner 转换是合法间隔；缺端点必须明确记录合约、频率、日期和最小缺失范围。此任务不得自动下载/回填任何新发现历史缺口。
- [ ] 页面/API Scope 读回与有效输入分开报告：enabled 不等于 reliable、不等于自然信号或用户收件。

## Task 5：45 品种夜盘恢复路径及自然验收准备

**Current evidence:** `/private/tmp/guiyi-alert-fixes-20260913/night-readonly.json`、`live-flags.json`。目标交易日 2026-09-14；45 品种有 2026-09-11 夜盘 Session。当前自然日 2026-09-13、snapshot 不存在、exact physical contract 尚未绑定，provider/写入均为 0。

**Existing contracts:**
- 在线 worker 只对 TRADING/BREAK 产品调度，先由正式 Live 入口取得当日冻结 operational snapshot，再补完整 completed 前缀；恢复不发布历史消息。
- `runtime recover-live-captured` 要求同一自然日、既有 snapshot、已捕获源、恰好五根新增 Bar；不能用于周日提前补 45 品种整段夜盘。
- `9 月 11 日 rank1` 不能替代 `9 月 14 日 frozen rank1`；不能将交易日改成 9 月 11 日来迎合 API，也不能直接调用内部 recover_product 绕过调度/身份 Gate。

- [ ] fresh 只读检查日期、phase、snapshot、两条 heartbeat 恢复保护和9月14日 circuit；未知与缺失分开记录。
- [ ] 在隔离 fixture 复现周一 09:00：完整60品种真实形状 snapshot由正常入口生成后，45 夜盘品种 recovery 请求包含前一交易日夜盘，剩余日盘品种没有伪造夜盘；按交易日请求1m并严格验证 completed endpoints。
- [ ] 增加与 Task 1 联动的 60m 场景：恢复生成全部可完成桶，未完整桶不能进入 HTDY；恢复不直接产生 Event，下一自然 completed 触发才可评估。
- [ ] 核对60秒调度、每品种每Session最多三次、全日权限/额度 circuit、重启不重置、CAS/guard/TTL/幂等和部分结果不明后的停止；使用一次性无卷 Redis 跑实际 Lua，完成后清理该精确容器。
- [ ] 准备自然窗口只读验收顺序：snapshot60 → 每品种正确物理身份 → 夜盘/当日1m与15m/60m完整性 → 自然触发评价 → 有 Candidate 时 Event/acceptance/owner收件。无信号不算失败，恢复成功也不算通知成功。
- [ ] **现在不执行真实下载或 Live 写入。** 当前路径 blocked，不用上一会话的请求执行跨会话新尝试。若 owner 坚持周末预装，单列最小合同设计：权威目标日身份如何取得/冻结、CLOSED下的精确一次源获取、staging与Live消费资格分离、数据/版本冲突、审批与读回；仅形成方案，不能将其混入三项代码修复或擅自部署。
- [ ] 不创建定时自动写入或提醒任务；用户本轮安排的是开发会话，现有已启用恢复 worker 按原持续授权自然运行。

## Task 6：整批验证、独立 Review 与 develop 交付

- [ ] 每项先 RED→GREEN；最后按 `TESTING.md` 运行两套 kernel、evaluator、MarketRead、Alert runtime/service/notification/health/API/Scope、Live recovery 与日志的完整相关组。至少覆盖审计的 370+120 组及本次新增回归，结果来自当前修复 commit。
- [ ] 必要的新增测试应验证业务不变量，不复制实现。Lua 必须实际跑隔离 Redis；不能用 skipped 替代新修改的原子性验收。
- [ ] 运行相关 Ruff、Mypy、工程/引用/格式检查、OpenSpec strict、secret scan、diff check。按修改影响选择，不机械跑未改的 Web 全量构建；若 API 或页面行为改动则补对应验证。
- [ ] 一名与实现上下文独立的 Sol high 审查者 review 整批准确 diff，重点检查：60m覆盖、owner/Session边界、苏冰skip是否假成功、失败后是否偷重试、日志是否泄漏、Scope未重做、夜盘未绕过身份。必要返修后复审。
- [ ] Review 通过后正常 commit/push 并集成 develop；冲突只处理本任务变更，不覆盖其他已集成修改。冻结一个精确 patch candidate，记录 code/test/review 与 external Gate。
- [ ] 更新 `STATUS.md`：三项修复的真实阶段、已启用Scope、夜盘真实阻塞/自然待验收、候选SHA及证据路径；不把本批旧测试、运行heartbeat或历史成功写成 `RUNTIME_READY`。
- [ ] 返回简洁交付：完成项、实际测试命令/结果、Review、候选、未完成外部动作及唯一最小下一步。发布与 Runtime switch 分别等待新的精确意图。

## 完成标准与停止点

工程出口是三个问题修复、新增60m覆盖通过、独立Review通过、develop集成、精确候选可审；不是“已上线”。Scope出口本轮已完成，只需复核；夜盘出口可以是明确的 blocked + 隔离自然恢复通过 + 只读验收准备，不能把它写成补数完成。

只在合同语义、生产范围、权限、非本任务修改等真实冲突处停受影响部分；其余已授权工作持续完成。不得为了等真实交易窗口让三个修复任务空转。
