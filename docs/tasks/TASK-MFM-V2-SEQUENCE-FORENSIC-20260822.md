# TASK-MFM-V2-SEQUENCE-FORENSIC-20260822

状态：READY_FOR_CODEX_PLAN_REVIEW

日期：2026-08-22

设计：`docs/superpowers/specs/2026-08-22-main-force-mirror-v2-sequence-forensic-design.md`

实施计划：`docs/superpowers/plans/2026-08-22-main-force-mirror-v2-sequence-forensic.md`

## 1. 任务目的

在现有 `main_force_mirror_v2` historical research 链内增加 60m-only causal sequence forensic 能力，用最小代码回答：

```text
一次强方向压力之后：
是否衰减？
是否发生原方向 liquidation？
是否出现 opposite build？
累计压力是否反号？
这些事实最早在哪一根 60m Bar 可知？
```

本任务只研究这些事实，不创建正式 Phase 标签。

## 2. 价值 Gate

本任务通过编码前五问的理由只有两条：

```text
减少人工把多个 60m Bar 拼接成阶段判断的盯盘负担
增加 causal、可复算的复盘证据
```

如果 Task 5 retrospective 不能证明这两项价值，结论必须为 `STOP`，后续不建设 Phase。

## 3. Scope

### 允许

```text
60m Historical confirmed
actual_dominant | contract
existing MainForceMirrorV2Point
existing MainForceMirrorV2ResearchService
existing guiyi research main-force-mirror-v2
5 fixed sequence profiles
additive --forensic stdout JSON
existing 1/3/5/10 60m retrospective outcomes
```

### 禁止

```text
15m / 5m / 1m
修改 V2 Kernel 五状态/instant/EMA5/caution
正式 CLIMAX / UNWIND / TAKEOVER
Web/API active semantic
Alert / notification / Runtime / Execution Review
新 service / repository / endpoint / protocol / cache / checkpoint
MarketDataService / MainContractMap / Canonical / migration
真实 RQData / member snapshot --apply / research-data 写入
best profile / product-specific tuning / winner / PnL / Sharpe
main / tag / release / Runtime promotion
```

## 4. 文件白名单

```text
services/quant-api/app/research/main_force/main_force_mirror_v2_research_service.py
services/quant-api/app/guiyi_cli/research_parser.py
services/quant-api/app/guiyi_cli/research_requests.py
services/quant-api/app/guiyi_cli/research_payloads.py
services/quant-api/tests/data_foundation/test_main_force_mirror_v2_research_service.py
services/quant-api/tests/test_research_cli.py
TESTING.md
```

任何需要突破白名单的实现应立即停止并报告，不得顺手重构。

## 5. 固定 profiles

```text
balanced = peak_window 10 / q 0.90 / decay 0.40 / transition 2
fast     = peak_window  5 / q 0.90 / decay 0.40 / transition 1
slow     = peak_window 20 / q 0.90 / decay 0.40 / transition 3
loose    = peak_window 10 / q 0.85 / decay 0.25 / transition 2
strict   = peak_window 10 / q 0.95 / decay 0.55 / transition 2
```

不得增加组合笛卡尔积，不得搜索 best profile。`--forensic` 逐 Bar 只展示 `balanced`。

## 6. Codex 调度矩阵

| 阶段 | Lane | 入口 | 模型 | 推理 | 会话 | Plan | 工作区 | Gate |
|---|---|---|---|---|---|---|---|---|
| Tasks 1–3 实现 | Lane 1 | Codex App | Sol | 高 | 新开实现会话 | Plan-then-execute | `research/mfm-v2-sequence-forensic` task worktree | 本合同/Plan 范围确认 |
| Task 4 独立 Review | Lane 1 Review | Codex App | Sol | 高 | 新开独立 Review 会话 | Plan-only / review-only | 同 branch 只读审查 | 独立 Review 通过 |
| task → develop | Lane 1 integration | Codex App | Sol | 中 | 回到实现会话收尾 | Direct | task worktree + develop | 测试+Review 通过后允许自动集成 develop |
| Task 5 retrospective | Lane 1 | Codex App + CLI automation | Sol | 高 | 新开研究会话 | Plan-then-execute | clean develop worktree；只读 | 无真实写入；输出 STOP / ALLOW_PHASE_FREEZE_DESIGN |
| 未来正式 Phase | Lane 3 | Codex App | Sol | 高 | 未来新会话 | Plan-only | 未来独立 task worktree | 新设计 + 独立 Review + 人工 Gate |

### Worktree 规则

```text
实现 branch: research/mfm-v2-sequence-forensic
从: develop
集成到: develop
允许自动 task → develop: 是，但必须先通过 Task 4 独立 Review
PR: 默认不强制；个人仓库可使用本地/远端集成记录，若当时仓库规则要求则开 PR
清理: 确认 commits 已进入 develop 后删除临时 worktree 和已合并 branch
main/tag/runtime: 全程禁止触及
```

Tasks 1–3 是同一个可独立集成 feature 的 TDD checkpoints，不拆三个 branch/worktree，避免为机械边界增加维护成本。

## 7. 逐 Task 完成定义

### Task 1 — Pure sequence facts

必须完成：

```text
5 profiles frozen
strict-prior peak baseline
long/short mirror
first-occurrence decay/liquidation/opposite/reversal
same-contract reset
prefix invariance for every profile
```

不得接 CLI、不得改 active V2。

### Task 2 — Sequence retrospective summaries

必须完成：

```text
reuse _Observation/_outcome/_summary
sequence warning event time = evidence bar, not peak bar
pooled + yearly/product/side summary
5 profiles all retained
no best profile
no cross-roll outcomes
```

现有 caution/member summary 必须零回归。

### Task 3 — `--forensic`

必须完成：

```text
request.forensic default false
existing command additive --forensic
sequence_profiles always additive
forensic_points only when requested
forensic detail uses balanced only
member only copies existing relation; no new member formula
TESTING.md documents read-only usage
```

### Task 4 — Review / integration Gate

必须完成项目原生 V2 tests、Ruff、Mypy、secret scan、diff check、文件白名单审计和独立 Sol review。

Review 结论只能：

```text
允许集成 develop
要求修正后再集成
```

### Task 5 — Read-only evidence Gate

先 JM 2026-03 forensic，再用现有 CLI 外层 loop 跑 active60 2023-01-01..2026-08-20。不得新增 batch module/script。

最终只输出：

```text
STOP
```

或：

```text
ALLOW_PHASE_FREEZE_DESIGN
```

第二个结论也只允许进入未来 Lane 3 设计，不授权代码实现、Web、Alert 或 Runtime。

## 8. 验收命令

主力照妖镜 V2 原生套件：

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_main_force_mirror_v2.py \
  services/quant-api/tests/test_indicator_registry_v1.py \
  services/quant-api/tests/data_foundation/test_member_rank_snapshot.py \
  services/quant-api/tests/data_foundation/test_member_rank_snapshot_builder.py \
  services/quant-api/tests/data_foundation/test_main_force_mirror_v2_service.py \
  services/quant-api/tests/data_foundation/test_main_force_mirror_v2_research_service.py \
  services/quant-api/tests/data_foundation/test_market_api.py \
  services/quant-api/tests/data_foundation/test_cli.py \
  services/quant-api/tests/test_research_cli.py
```

静态验证：

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api ruff check \
  services/quant-api/app/research/main_force \
  services/quant-api/app/guiyi_cli \
  services/quant-api/tests/data_foundation/test_main_force_mirror_v2_research_service.py \
  services/quant-api/tests/test_research_cli.py

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
MYPYPATH=services/quant-api:packages/quant-core \
uv run --offline --project services/quant-api mypy \
  --explicit-package-bases --ignore-missing-imports \
  services/quant-api/app/research/main_force \
  services/quant-api/app/guiyi_cli

python3 scripts/engineering/secret_scan.py --json
git diff --check
```

## 9. 实现 Codex Prompt

```text
请先阅读 `STATUS.md`、`AGENTS.md`、`docs/DEVELOPMENT.md`、`DECISIONS.md`，
以及：
- `docs/superpowers/specs/2026-08-22-main-force-mirror-v2-sequence-forensic-design.md`
- `docs/superpowers/plans/2026-08-22-main-force-mirror-v2-sequence-forensic.md`
- `docs/tasks/TASK-MFM-V2-SEQUENCE-FORENSIC-20260822.md`

本任务为 Lane 1 historical research，使用 Sol + 高推理，严格 60m-only。
本次 Tasks 1–3 是同一个可独立集成 feature，请使用一个新 task worktree：
从当前 `develop` 创建 `research/mfm-v2-sequence-forensic`。
不得修改 main/runtime worktree。

目标：
在现有 MainForceMirrorV2ResearchService 内增加 causal sequence forensic facts、
5 个固定 profile summary 和 opt-in `--forensic` stdout JSON。
不得创建正式 Phase，也不得改变 active V2 Kernel/Web/API/Alert 语义。

严格按 implementation plan 的 Task 1 → Task 2 → Task 3 TDD 顺序执行：
每个 Task 先写失败测试、确认失败、最小实现、确认通过、单独 commit。

允许修改仅限任务合同白名单。
禁止修改 V2 Kernel、MainForceMirrorV2Service、member snapshot、MarketDataService、
Canonical、migration、Web、Alert、Execution Review、Runtime、STATUS/PROJECT_SOURCE/DECISIONS。
禁止调用 RQData、禁止真实 member snapshot --apply、禁止任何正式数据写入。

因果硬约束：
- current Bar 不得进入自己的 peak percentile baseline；
- sequence memory 不得跨 physical_contract；
- long/short 必须镜像；
- event 必须标在证据实际出现的 Bar，禁止回标 peak；
- prefix invariance 对 5 个 profile 全部成立；
- forward horizon 只能用于 retrospective summarizer，不得进入 sequence fact。

完成 Tasks 1–3 后运行 Task 4 的全部验证，但不要自行发布 main/tag、切 Runtime 或运行 Task 5 真实历史研究。
独立 Review 通过后，允许按仓库正式流程完成 task branch → develop；
确认提交进入 develop 后清理临时 worktree 和已合并 branch。

完成后输出：
修改摘要、每个 Task 的 commit、测试结果、文件白名单审计、独立 Review 结论、
集成/清理结果、风险和未完成项。
```

## 10. Task 5 Research Prompt

```text
请先阅读当前 `develop` 的 STATUS/AGENTS/DEVELOPMENT/DECISIONS，
以及 MFM V2 sequence forensic spec/plan/task contract。

这是新的 Lane 1 read-only research 会话，Sol + 高推理。
不得改代码，不得调用 RQData，不得执行 member snapshot --apply，
不得写 Canonical/DB/Redis/research-data，不得创建正式 report artifact。

先运行 JM actual_dominant 60m：2026-03-10..2026-03-30，使用 --forensic。
逐 Bar 找出用户关注高位段：peak、first decay、first liquidation、first opposite build、
first accumulated reversal 的最早 causal 时点，并确认 physical_contract 未跨越。

然后对 data/universe/active_products.txt 的 active60 使用现有 CLI 外层 shell loop，
范围 2023-01-01..2026-08-20，series_kind=actual_dominant，frequency=60m。
临时 JSON 只能放 OS temp 目录，汇总后删除；不得新增仓库 batch script/module。

比较 balanced/fast/slow/loose/strict 五个 profile 的样本数、1/3/5/10-bar retrospective metrics、
逐年和 long/short 分层稳定性。不得选择 best profile，不得按品种调参，不得输出 PnL/Sharpe/winner。

最终只给一个 Gate：STOP 或 ALLOW_PHASE_FREEZE_DESIGN。
若证据不稳定、样本不足、明显产品特化，必须 STOP。
ALLOW_PHASE_FREEZE_DESIGN 也只授权后续 Lane 3 设计，不授权实现。
```

## 11. 用户重点审查

用户 Review 时重点看：

```text
是否真的只解决“跨 Bar 解释盲点”而没有造 Phase 平台
5 profiles 是否已经足够，不应再扩参数网格
是否任何 sequence rule 偷看未来
是否把后续暴跌反向写回峰值
是否跨主力换月继承 memory
是否为了 member 数据又建了新缓存/数据层
是否触碰 Web/Alert/Runtime 或 active V2 formula
Task 5 是否能在证据差时真正 STOP
```

最终本任务在代码阶段的目标结论是：

```text
允许集成 develop
```

不是：

```text
允许进入 release candidate
允许发布 main/tag
允许 Runtime promotion
```
