# Alert 可靠性与苏冰盯盘 15m V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` or `superpowers:executing-plans` to execute the packet plans. Every behavior change starts with a failing test. Every independently integrable packet uses a new Codex session, task branch/worktree and PR.

状态：`PLAN_READY_FOR_USER_REVIEW`

日期：2026-09-01

规划基线：`develop@606ef013e62139587c3a6f29d584517c1511464f`

批准的 Spec：`docs/tasks/2026-08-31-alert-reliability-subing-watch-15m-spec.md`

Issue：`#286`

设计 ID：`alert_reliability_subing_watch_15m_v1`

正式观察 ID / Rule code：`subing_watch_15m_v1`

正式名称：`苏冰盯盘`

## 1. Goal

交付下一版本唯一优先闭环：

```text
可信 completed Live 15m Bar
→ Session-aware expected set
→ 每个应处理边界可证明
→ subing_watch_15m_v1 透明观察
→ immutable AlertEvent
→ one-shot PushPlus
→ 用户打开图表并人工判断
```

系统必须明确区分：

```text
正常静默
数据不可用
计算失败
触发缺失
Event 持久化失败
通知准备失败
transport 失败
provider accepted 但尚未人工确认送达
```

本计划不实现自动交易，不把上下文标签升级为硬过滤，不删除 `subing_strategy_v1` 的研究能力，也不恢复或并行实施其他暂停策略。

## 2. Architecture

```text
TradingCalendar + TradingSession + operational_products
                         │
                         ▼
              Watch Boundary Expectation
                         │
Live completed 15m ─────┼─────> Watch incremental evaluator
                         │                 │
                         ▼                 ▼
                  Boundary Ledger   SubingWatchEvaluation
                         │                 │
                         └──────┬──────────┘
                                ▼
                  alert:watch-runtime-status
                                │
                       read-only Runtime health
                                │
                 shadow ────────┴──────── active
                                           │
                                           ▼
                                  immutable AlertEvent
                                           │
                                           ▼
                                  one-shot PushPlus owner
```

公式 authority 是一个纯增量 `step`。Historical、Current、restore、Shadow 和 Active Runtime 全部调用同一实现。Web 只读取后端投影并渲染，不重新计算正式 BUY/SELL。

## 3. Frozen Contracts

### 3.1 Base formula

```text
DIFF = EMA(close, 12) - EMA(close, 26)
DEA  = EMA(DIFF, 9)
MACD = 2 × (DIFF - DEA)
MA21 = SMA(close, 21)

BUY  = DIFF[t-1] <= DEA[t-1]
   and DIFF[t] > DEA[t]
   and close[t] > MA21[t]

SELL = DIFF[t-1] >= DEA[t-1]
   and DIFF[t] < DEA[t]
   and close[t] < MA21[t]
```

固定政策：

```text
series_kind=actual_dominant
frequency=15m
completed_bar_only=true
ema_seed_policy=sma_window
histogram_scale=2
round_digits=6
auto_order=false
```

这里的 `MA21` 是 SMA21，不是当前苏冰 Overlay 的 EMA21。原始同花顺公式没有说明 EMA 初始化细节，因此 V1 只声明 clean-room 公式实现，不声明所有历史 Bar 字节级等价。

### 3.2 Context-only

以下字段只帮助人工判断，不能改变 Candidate：

```text
ma21_slope_5_bps_per_bar
distance_to_ma21_atr14
macd_zero_distance_atr14
volume_ratio_20
range_state
higher_timeframe_alignment
```

任一 context unavailable 时，基础 Candidate 仍成立；对应标签必须显示“不可用”。

### 3.3 Boundary proof

`expected_symbols` 只能由以下权威解析：

```text
operational_products.txt
+ TradingCalendar
+ TradingSession
+ formal 15m bucket
+ current trading day
```

不能固定假设 `60/60`，不能由实际消息数量反推 expected set。

每个 expected symbol 的冻结终态只能是：

```text
evaluated_no_signal
evaluated_candidate
source_unavailable
processing_failed
missing_trigger
```

`normal_silence=true` 当且仅当：

```text
expected_count > 0
evaluated_count == expected_count
no_signal_count == expected_count
candidate_count == 0
source_unavailable_count == 0
processing_failed_count == 0
missing_trigger_count == 0
```

公开状态：

```text
key=alert:watch-runtime-status
schema_version=1
ttl_seconds=90
recent_boundaries<=8
recent_candidates<=20
current_open_boundaries<=4
```

它不是永久业务表；不新增 PostgreSQL boundary history table。

### 3.4 Alert and Rule lineage

Rule metadata 拆为：

```text
kind = indicator_observation | strategy_action
scope_authority = product | product_frequency
```

固定组合：

```text
HTDY:
  indicator_observation + product_frequency

Legacy SuBing Strategy:
  strategy_action + product

SuBing Watch:
  indicator_observation + product
```

稳定 production 最终仍恰好两条 Rule：

```text
htdy_original_15m
subing_watch_15m_v1
```

同一 release 只接受两种数据库 lineage 之一：

```text
pre-migration:
  htdy_original_15m + subing_strategy_v1

post-migration:
  htdy_original_15m + subing_watch_15m_v1
```

双 SuBing Rule、第三 Rule 或未知 Rule 均启动失败。pre-migration 只允许 Watch shadow；post-migration 才允许 Watch active。

正式 Watch Event 固定：

```text
result_codes=("buy",) | ("sell",)
action_id=null
strategy_payload=null
frequency=15m
identity=rule_id × symbol × frequency × bar_end
```

Event 先提交，再最多一次 transport；无 retry、queue、outbox、fallback、replay、backfill 或逐收件人状态。

## 4. Program Decomposition

本 Spec 跨公式、Runtime 可靠性、Web、Alert lineage 和 migration，不能安全放进一个巨大实现 PR。固定拆为六个独立集成 Packet：

| Packet | task branch | 目标 | Lane |
|---|---|---|---|
| P0 | `docs/release-identity-convergence-v1-9-7` | 收敛当前 release/Runtime 事实 | Lane 3 docs-only |
| P1 | `feature/subing-watch-kernel-research` | 公式、上下文、Historical/Current、诊断 | Lane 3 |
| P2 | `feature/subing-watch-boundary-shadow` | expected set、账本、Shadow Runtime、health | Lane 3 |
| P3 | `feature/subing-watch-web` | 状态卡、只读投影、深链、SMA21、marker | Lane 2，读取 Lane 3 事实 |
| P4 | `feature/subing-watch-alert-cutover` | scope authority、Event、通知、migration 代码 | Lane 3 |
| P5 | `docs/subing-watch-canonical-release-candidate` | canonical、OpenSpec、完整验证、RC packet | Lane 3 |

执行顺序：

```text
P0
→ P1 formula checkpoint
→ P2 Runtime checkpoint
→ P3 Web/API checkpoint
→ P4 Alert/migration exact-head Review
→ P5 canonical/full verification
→ release candidate Gate
```

一个 Packet：

```text
一个新 Codex 会话
= 一个从届时最新 origin/develop 创建的 task worktree
= 一个 task branch
= 一个 Draft PR
= 一次 exact-head 独立 Review
= 一次用户“允许集成 develop”Gate
```

前一 Packet 未合入 `develop`，后一 Packet不得从旧 feature branch 叠加。合入 `develop` 不授权 `main`、tag、GitHub Release、production migration、Runtime promotion、Scope 或真实通知。

## 5. Packet Plans

- P0：`docs/tasks/2026-09-01-subing-watch-p0-release-identity-plan.md`
- P1：`docs/tasks/2026-09-01-subing-watch-p1-kernel-research-plan.md`
- P2：`docs/tasks/2026-09-01-subing-watch-p2-boundary-shadow-plan.md`
- P3：`docs/tasks/2026-09-01-subing-watch-p3-web-plan.md`
- P4：`docs/tasks/2026-09-01-subing-watch-p4-alert-cutover-plan.md`
- P5：`docs/tasks/2026-09-01-subing-watch-p5-canonical-rc-plan.md`

这些文件共同构成一个 Implementation Program。Packet 文档定义精确文件、接口、TDD 步骤、验证命令、commit 边界和 Review Gate；本页定义全局顺序与外部 Gate。发生冲突时，以批准 Spec 为最高任务事实源，并 fail-closed。

## 6. Global Constraints

- P1 至 P4 每个行为先运行精确 RED，再实现 GREEN，再做最小 REFACTOR。
- Historical 只能经 `MarketDataService`；Live 只能经现有 Redis observation seam。
- 主力身份只认 `MainContractMap rank=1` 和冻结 Live contract；不得自判主力或跨合约继承递归状态。
- 每个物理段重置 MA21、MACD、previous DIF/DEA、ATR、量能和 Range state。
- Shadow 不创建 DB Rule、不写 Watch Event、不发送 Watch 通知。
- `STATUS.md` 只记录真实 release、migration、Runtime 和自然 evidence，不因代码/测试完成提前宣布 Ready。
- 不读取、输出、记录或提交 token、Topic code、provider reference、SQL、stack trace、私有路径或原始异常正文。
- 不实施自动下单、账户/委托/真实持仓/资金、加减仓、反手、止损价、目标价或仓位建议。
- 不把 60m、D1、Range、零轴距离、量能变成 V1 硬过滤。
- 不调整 HTDY 公式或生产 Scope。
- 不同时实施苏冰趋势策略-日、Newow 或其他新策略。
- 必要验证失败时只报告失败，不声明完成。

## 7. Cross-Stage Acceptance Matrix

| 领域 | 必须证明 | 禁止替代证据 |
|---|---|---|
| Formula | SMA21、12/26/9、exact CROSS、segment reset | 截图、人工目测、Web 重算 |
| Causality | completed-only、strict-before 60m、future-tail invariance | 全历史一次性向量结果 |
| Boundary | Session expected set、零触发可发现、normal silence | heartbeat 绿色、固定 60/60 |
| Runtime | restore parity、single-product isolation、startup no-backfill | synthetic message、手工补跑 |
| Status | TTL/stale/invalid/incomplete 显式降级 | global last_processed_bar_at |
| Alert | immutable Event、commit-first、one-shot | provider accepted 当作送达 |
| Migration | exact old head、atomic replacement、no downgrade | SQLite-only test、手工 SQL |
| Web | API/Kernel output、SMA/EMA 区分、formal bar_end | TypeScript 复制公式 |
| Release | main/tag/Release/API/Web exact identity | `develop` commit、RC packet |
| Delivery | owner 人工确认自然消息 | canary、测试、replay、provider reference |

## 8. External Operation Gates

以下不属于普通实现。每一步都需要新的、范围明确的单次授权；前一步成功不自动授权下一步。

### R1 — Release

前置：P0–P5 进入 `develop`、完整验证 fresh green、exact-head Review approved、release identity conflict 已关闭。

单独授权后才允许：

```text
release branch/worktree
→ release PR to main
→ merge main
→ annotated tag
→ GitHub Release
→ API/Web/version identity readback
```

不得同时切 Runtime 或执行 migration。

### R2 — Shadow Runtime promotion

使用 exact approved tag 的 clean detached root。production DB 保持旧 Rule lineage，Watch 自动为 shadow，旧 rollback root 保留。

必须读回：

```text
五项服务 exact root 一致
fresh completed Live Bar
Alert heartbeat ready
Watch status mode=shadow
首个 restart 后完整自然 boundary
Watch Event/transport counts 恒为 0
```

失败只允许一次回滚；重试需要新授权。

### R3 — Natural Shadow evidence

至少覆盖：

```text
完整日盘
自然夜盘进入下一 trading day
一次 restart 后首个完整 boundary
至少一个 normal_silence
至少一个自然 Candidate
rank1 切换若自然发生则验证 reset；未发生保持 pending
```

并人工 review 至少 30 个 Candidate；样本不足 30 时 review 全部。不得在 Shadow 中临时改 V1 公式。

### R4 — Production migration

单次授权只覆盖：

```text
只读 preflight
alembic upgrade 20260901_0043
readback Alembic head
readback exactly two Rules
readback Watch preserved product Scope
readback old Strategy Event count=0
```

不发送通知，不切 Runtime。migration 完成后，旧版本 Alert Runtime 不再是合法 rollback root。

### R5 — Active Runtime

使用同一 approved tag，Watch 自动选择 active。必须证明：

```text
no startup backfill
no delayed historical Event
自然 completed 15m boundary
boundary counters consistent
HTDY non-regression
Event commit-first
one-shot only
```

### R6 — Real delivery

分开核验：

1. owner canary：只证明通道；
2. 下一次自然 Watch Candidate：

```text
Candidate
→ immutable Event
→ transport attempt
→ provider accepted
→ owner 人工确认微信收到
```

provider accepted 不等于送达。只有 owner 人工确认后，才能在 `STATUS.md` 记录真实送达 evidence。

## 9. Completion Vocabulary

必须区分：

```text
CODE_COMPLETE
TEST_COMPLETE
EXTERNAL_GATE_PENDING
RELEASED
MIGRATED
RUNTIME_READY
NATURAL_EVIDENCE_COMPLETE
```

最终结论只能使用：

```text
允许继续实现
允许集成 develop
要求修正后再集成
允许进入 release candidate
允许发布 main/tag
允许 Runtime promotion
阻塞
```

## 10. Plan Self-Review

1. release identity 修正独立为 P0，产品代码不顺手修改部署事实；
2. 公式、Runtime、Web、cutover、canonical 拆为独立 PR；
3. expected boundaries 由 heartbeat 主动发现，覆盖“所有 trigger 都没来”的故障；
4. Watch 内核不依赖 legacy Strategy、Daily Context、1m/5m companion、Action 或 Episode；
5. 通用 MACD Registry 不被全局升级，只有 Watch scoped policy 获授权；
6. SMA21 与现有 EMA21 明确分离；
7. context-only 在 contracts、测试和 Web 中均不能改变 Candidate；
8. boundary status 独立于 rollback-sensitive `alert:runtime-status`；
9. pre/post migration 使用 single-lineage resolver，不长期保留第三 Rule；
10. migration 代码与 production execution 分离；
11. Web 只读取后端 projection，Event identity 保持 formal `bar_end`；
12. release、Shadow、migration、Active、canary 和自然送达保持独立 Gate；
13. `STATUS.md` 只在真实操作后更新；
14. 没有引入 queue、scheduler、永久 boundary 表或通用策略平台。

自审结论：

```text
无未解析占位符
无公式与 Spec 冲突
无隐藏硬过滤
无双 Rule 稳态
无自动 external operation
范围可由六个独立 PR 执行和 Review
```

## 11. User Review Gate

批准本 Plan 只允许 Codex 按 P0 → P5 的顺序开始仓库实现，不表示批准：

```text
自动合入 develop
main/tag/GitHub Release
production migration
Runtime promotion
Scope mutation
真实 PushPlus
```

每个 Packet 完成后仍须独立 Review 和明确的 `允许集成 develop`。P5 之后仍须分别取得 release、Shadow Runtime、production migration、Active Runtime 和真实送达授权。
