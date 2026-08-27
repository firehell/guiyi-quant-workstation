# N Structure 与 Multi-Candidate Robustness 退役设计

日期：2026-08-27

状态：Design only；implementation plan pending user review。

## 1. 决策摘要

本设计决定从归一量化 active surface 中完整退役 N Structure，并同时退役仅用于比较 SuBing Lifecycle Candidate 与 N Structure Candidate 的整套 Multi-Candidate Robustness。

目标不是隐藏入口、冻结功能或保留兼容层，而是关闭全部 active consumer 和 active reference，使 N Structure 不再属于 Market Web、Market API、research CLI、Historical Research、Candidate Validation、prospective OOS、Robustness、Runtime architecture 或稳定产品面。

本任务不以新的自动结构识别能力替代 N Structure，不把 Multi-Candidate Robustness 改造成单 Candidate robustness，也不把 LuxAlgo 或其他第三方指标接入归一量化。未来如需外部看盘辅助，应作为独立任务重新定义价值、数据边界和授权。

## 2. 背景与原因

当前 N Structure 的主要产品价值是 `actual_dominant + 5m` Historical completed-N range band，辅助人工看盘识别 N1-N2 支撑/压力区域。它已经具备独立 Swing reducer、completed-N pattern、range-band 生命周期、BULL/BEAR/RANGE structure、Candidate Validation、prospective OOS、Web 绘制、HTTP API 和 research CLI。

但当前实际使用判断是：自动识别结果长期不足以优于人工快速识别；该能力的主要用途又只是辅助人工看盘，没有进入苏冰正式决策链、Alert、Live evaluator 或 Runtime execution。继续维护会增加研究、API、Web、Candidate 和验证链路复杂度，而不能直接提升核心产品价值。

因此采用删除而不是继续优化。Git history 是唯一恢复来源，不保留 archive、legacy、backup、disabled implementation 或兼容副本。

## 3. 当前事实与设计约束

### 3.1 当前产品边界

当前稳定产品面将 N Structure 定义为可与主图 Overlay 组合的 `actual_dominant + 5m` completed-N Historical range-band 图层。它不是独立产品、第五个 Overlay、Alert 或 Runtime evaluator。

当前主图正式 Overlay 仍只有 `none | subing | htdy`；N Structure 是独立图表设置项，默认关闭。

### 3.2 当前 N Structure 组成

当前后端核心为：

```text
services/quant-api/app/research/n_structure/
  n_structure_swing.py
  n_structure_pattern.py
  n_structure_state.py
  n_structure_segment.py
  n_structure_policy.py
  n_structure_research_service.py
  n_candidate_validation.py
  n_candidate_validation_policy.py
  n_candidate_validation_service.py
```

相关冻结输入包括：

```text
data/research_policies/n_structure_5m_v1.json
data/research_candidates/n_structure_5m_candidate_v1.json
data/research_protocols/n_structure_validation_v1.json
```

### 3.3 当前 Multi-Candidate Robustness 组成

当前 `services/quant-api/app/research/robustness/` 仅包含 Multi-Candidate Robustness 相关实现：

```text
multi_candidate_events.py
multi_candidate_robustness.py
multi_candidate_robustness_policy.py
multi_candidate_robustness_service.py
```

其冻结 protocol 是：

```text
data/research_protocols/multi_candidate_robustness_v1.json
```

该 protocol 的候选固定为：

```text
subing_lifecycle_v2_candidate_v1
n_structure_5m_candidate_v1
```

N Structure 删除后，不再存在需要保留该“multi-candidate”抽象的业务目标，因此不改造成只剩 SuBing 的单 Candidate robustness。

### 3.4 苏冰不可破坏边界

N Structure 与苏冰 Strategy V1 没有执行依赖。苏冰 Strategy V1 的方向、Entry、Exit、Episode 和 Historical Projection 必须保持原语义。

特别禁止误删或改写：

```text
services/quant-api/app/market_data/subing_structure.py
```

该文件的 confirmed Pivot 是苏冰 Lifecycle / Strategy 自己的 5m 结构事实，与 `app/research/n_structure/*` 的 Swing / N Structure 是两套独立算法。

苏冰保留：

- Daily Context；
- Current Signal State；
- Formal Event；
- Factor / Signal / Calibration / Lifecycle；
- SuBing Lifecycle Candidate Validation；
- SuBing prospective OOS；
- SuBing Strategy V1 Historical Projection；
- SuBing Alert / Scope / Runtime seam；
- `subing_structure.py` confirmed Pivot、breakout、retest 语义。

## 4. 目标状态

完成后 active dependency graph 收敛为：

```text
RQData
  -> Canonical Parquet
  -> Catalog + MainContractMap
  -> MarketDataService
       -> Market Web / Market API
       -> SuBing Factor / Signal / Calibration / Lifecycle
       -> SuBing Daily Context / Current Signal State / Strategy
       -> SuBing Candidate Validation
       -> retained SuBing research CLI

Live / EOD
  -> Market Runtime
  -> SuBing / HTDY Alert evaluator
```

以下 active seam 不再存在：

```text
MDS -> N Structure -> Market
N Structure -> Candidate Validation
N Candidate -> prospective OOS
SuBing Candidate <-> N Candidate -> Multi-Candidate Robustness
Market API -> /research/n-structure/bands
Market Web -> N字区间
research CLI -> n-structure
```

## 5. 删除范围

### 5.1 后端 N Structure 内核

删除整个：

```text
services/quant-api/app/research/n_structure/
```

包括但不限于：

- causal Swing reducer；
- completed-N Pattern；
- N1-N2 range band；
- reentry / N2 break / origin break；
- BULL / BEAR / RANGE structure；
- trailing defense；
- 3/5/8 bar outcome projection；
- N Structure research result / event / range-band fact；
- N Candidate Validation contracts、service 和 policy loader。

不得把其中任一实现迁移到 `subing_*`、generic indicator、Market API 或新的 shared structure module。

### 5.2 N Structure policy / candidate / protocol

删除：

```text
data/research_policies/n_structure_5m_v1.json
data/research_candidates/n_structure_5m_candidate_v1.json
data/research_protocols/n_structure_validation_v1.json
```

N prospective OOS 从 active research contract 中终止。历史 evidence 不搬迁、不转换、不回填到 SuBing。

### 5.3 Multi-Candidate Robustness

删除整个 Multi-Candidate Robustness 实现及其独立 protocol：

```text
services/quant-api/app/research/robustness/
data/research_protocols/multi_candidate_robustness_v1.json
```

实现时如果确认 `robustness/__init__.py` 删除后目录为空，则整个 `robustness/` package 一并删除。

不得：

- 创建 `single_candidate_robustness`；
- 把原 Multi-Candidate report 简化成只含 SuBing；
- 保留 relationship DTO、event proximity、cross-symbol comparison 或 metric compatibility flag；
- 为将来“可能重新比较”保留 generic shell。

### 5.4 Research composition 与 CLI

从 `app/research/composition.py` 移除：

- N Structure research service composition；
- N Candidate Validation composition；
- Multi-Candidate Robustness composition。

从 `guiyi research` 删除 `n-structure` 命令以及全部 N-specific request / payload / dispatch seam。

最终 retained research CLI 只保留当前仍有 active consumer 的 SuBing research 命令，例如：

```text
subing-calibration
subing-lifecycle
```

CLI registry、parser、request union、payload serializer、dispatch 和 tests 必须同步收敛，不能保留未使用 N branch。

### 5.5 HTTP API

删除：

```text
GET /api/v1/market/research/n-structure/bands
```

同步删除：

- N Structure request / response DTO；
- N Structure band policy DTO；
- N Structure band schema；
- N-only API module / router registration，如果删除 N route 后该模块不再有其他 active endpoint。

目标是 endpoint 不再注册，而不是返回 retired、410、404 compatibility wrapper 或 feature-disabled response。

### 5.6 Market Web

删除所有 N Structure UI / state / rendering seam，包括：

- “N字区间”设置开关；
- `showNStructureBands` preference；
- N Structure API client；
- `useNStructureBands`；
- `NStructureBand` 等前端 types；
- `NStructureBandPrimitive`；
- KlineChart 的 N Structure props、render、hover、overlap group、badge、diagnostics；
- chart page 的 sync / pagination / error / loading 接线；
- N-specific E2E 与 unit tests。

N Structure 当前不是 Overlay，因此不得因删除它改变 `none | subing | htdy` 的 Overlay 语义。

### 5.7 Web preference schema

当前主图 preference schema 含 `showNStructureBands`。删除该字段时应同步收敛 schema。

推荐：

1. 将当前 preference schema 从 v6 升到 v7；
2. v7 不含任何 N Structure 字段；
3. 对 v6 进行一次轻量 migration，只拷贝仍存在的字段，例如 `selectedOverlay`、optional EMA、`showSubingInternalProcess`、period、realtimeFollow；
4. 对 v6 中额外的已退役字段直接忽略，不建立 N-specific compatibility object；
5. 旧 v1-v5 retirement 逻辑按现状最小调整，不扩大本任务。

迁移目标是保留用户现有主图偏好，同时彻底删除 N Structure active state。

## 6. 测试与验证删除范围

### 6.1 删除 N-specific 测试

删除只验证已退役实现的测试，例如：

```text
services/quant-api/tests/test_n_structure_*.py
services/quant-api/tests/test_n_candidate_validation*.py
services/quant-api/tests/research/test_n_structure_research_service.py
services/quant-api/tests/research/test_n_candidate_validation_service.py
apps/quant-web/tests/nStructureBands.test.ts
apps/quant-web/tests/nStructureBandPrimitive.test.ts
```

实际实现必须按 repository search 补齐其他 N-only fixtures / E2E / snapshots。

### 6.2 删除 Multi-Candidate 测试

删除：

```text
services/quant-api/tests/test_multi_candidate_events.py
services/quant-api/tests/test_multi_candidate_robustness.py
services/quant-api/tests/test_multi_candidate_robustness_policy.py
services/quant-api/tests/research/test_multi_candidate_robustness_service.py
```

以及只为这些测试存在的 fixtures。

### 6.3 修改共享测试

对于共享测试，不整文件删除；只删除 N / Multi-Candidate case，并保留对 retained surface 的覆盖。例如：

- research CLI registry；
- research composition；
- Market API route registration；
- Market Web toolbar / chart；
- preferences migration；
- SuBing Candidate Validation；
- SuBing Strategy；
- full Web build / backend lint-typecheck。

## 7. Canonical 与文档收敛

实现时必须同步更新 active canonical，避免“代码已删但文档仍宣称 active”。

### `PROJECT_SOURCE.md`

- 删除 N Structure 保留研究能力；
- 删除 N 与 SuBing Candidate 双候选措辞；
- 删除 Generic/Multi-Candidate Robustness active 产品描述；
- 在 Retired surface 中加入 N Structure 与 Multi-Candidate Robustness；
- retained Candidate 面只描述 SuBing Candidate Validation / prospective OOS，不新建单 Candidate robustness。

### `docs/ARCHITECTURE.md`

删除：

```text
MDS -> N -> MARKET
N research service
N Candidate Validation
CV -> ROB Candidate Robustness
Multi-Candidate relationship dependency
```

保留并简化：

```text
MDS -> SuBing research
SuBing Candidate Validation
SuBing research CLI
```

### `DECISIONS.md`

新增长期 retirement 决策：

- N Structure 不再属于 active surface；
- Multi-Candidate Robustness 不再属于 active surface；
- 恢复必须由新任务重新定义 consumer、公式、价值和 evidence，不得直接恢复旧模块；
- SuBing 的 `subing_structure.py` 不属于此次 retirement。

### `STATUS.md`

必须保持 release / Runtime 事实准确。

如果代码先合入 `develop`、但 production Runtime 仍停留在 v1.8.6，则不得把当前 Runtime 描述改成“已经没有 N Structure”。应明确区分：

```text
develop: N Structure retirement code complete / release pending
production Runtime: 仍是当前已批准 tag 的真实能力
```

只有未来 release/main/tag 与独立 Runtime promotion 完成后，才能把 production Runtime 当前能力改成无 N Structure。

### 其他文档

通过 repository search 更新 active README、TESTING、API/CLI 导航和当前计划引用。历史 Git commit 不清理；已完成历史 spec/plan 是否删除，以其是否仍被 active canonical 或入口引用为准，不建立 archive。

## 8. 数据、数据库、Runtime 与外部操作

本设计本身不授权任何外部 mutation。

预期 N Structure 与 Multi-Candidate Robustness 均为 read-only research surface，不拥有 production DB/Redis/Alert 数据合同。因此本任务预期不需要：

- Alembic migration；
- production PostgreSQL mutation；
- Redis mutation；
- Canonical / primary 数据删除；
- RQData 下载；
- Scope 变更；
- Alert Rule 变更；
- PushPlus 真实发送；
- Runtime switch / promotion。

实现阶段必须先验证该预期。如果发现 N / Multi-Candidate 实际拥有 production schema、persisted state 或 Runtime mutation consumer，立即停止并重新评估，不得顺手删除生产数据。

代码从 `develop` 删除不等于 production Runtime 已删除。release 与 Runtime promotion 保持两个独立人工 Gate。

## 9. SuBing 回归不变量

退役 N Structure 后必须证明以下 SuBing 事实没有语义变化：

1. Factor / Signal / Calibration formula identity 不变；
2. Lifecycle opportunity identity、stage、confirmation source 不变；
3. `subing_structure.py` confirmed Pivot / breakout / retest 行为不变；
4. Strategy V1 direction context 不变；
5. Strategy Entry 仍只来自 accepted Lifecycle confirmation source；
6. Strategy Exit 仍只认 EMA21、previous 15m extreme、bound SuBing Pivot、MACD high/low reverse cross；
7. action timing 仍为 completed 15m decision -> next existing same physical segment 15m open；
8. 不新增/删除加仓、减仓、反手、跨 physical segment 行为；
9. Alert Rule、Scope、audience、transport 不变；
10. SuBing prospective OOS 继续按自己的 protocol 独立累积。

任何 SuBing formula / policy / golden parity 差异都视为 retirement regression，阻塞集成。

## 10. 实施顺序约束

实际 implementation plan 应按 consumer 从外向内收敛，避免中间状态出现 dangling reference：

```text
1. 建立删除前引用清单和 retained invariants
2. Web 移除用户入口和 N rendering/state
3. API / CLI 移除 public/read-only surface
4. composition 移除 N 与 Multi-Candidate wiring
5. 删除 Multi-Candidate Robustness
6. 删除 N Candidate / protocol / policy
7. 删除 N Structure core
8. 删除或修改对应 tests / fixtures
9. 更新 active canonical / docs
10. 全仓 reference scan + backend/web regression
```

实际计划可以在同一 task branch 中按更安全的原子 commit 切分，但最终集成必须是一个自洽状态，不能把“入口先删、底层以后再说”作为长期中间态。

## 11. 验收标准

### 11.1 Active surface 清零

除本 retirement design/implementation plan、必要的 retirement decision 描述以及 Git history 外，active code/config/API/Web/CLI/test fixture 中不得残留可执行或可调用的：

```text
n_structure
NStructure
n-structure
n_structure_5m_candidate_v1
n_structure_validation_v1
multi_candidate_robustness
MultiCandidateRobustness
N字区间
```

如果 canonical 的 Retired surface 保留 `N Structure` 名称，只能作为“已退役能力”的历史标识，不得指向 active consumer。

### 11.2 Public behavior

- Market Web 不再显示 N 字设置；
- Kline 不再请求或绘制 N band；
- `/api/v1/market/research/n-structure/bands` 不再注册；
- `guiyi research n-structure` 不再是合法命令；
- repository 不再构造 N research / N Candidate / Multi-Candidate service；
- retained SuBing 和 HTDY UI/API 行为正常。

### 11.3 Research behavior

- SuBing Candidate Validation 保留；
- SuBing prospective OOS 保留；
- 不存在新的单 Candidate robustness；
- 不存在 SuBing↔N relationship、proximity、cross-symbol multi-candidate report；
- retrospective N evidence 不迁移、不冒充 SuBing evidence。

### 11.4 验证

至少完成：

Backend：

```text
N / multi-candidate active reference scan
retained research CLI tests
retained research composition tests
SuBing Candidate Validation tests
SuBing Lifecycle tests
SuBing Strategy policy / engine / causality / prefix invariance / golden parity tests
Market API tests
Ruff
Mypy
相关 backend pytest；按影响决定完整 pytest
```

Web：

```text
preference migration tests
main indicator / toolbar / chart tests
Market research / chart E2E 中 retained cases
pnpm unit test
pnpm build
相关 Playwright；按影响决定完整 E2E
```

Repository：

```text
git diff --check
active reference scan
secret scan / OpenSpec checks（如仓库当前流程适用）
```

任何 retained SuBing、Market、HTDY 必要验证失败，均不得声明完成。

## 12. 风险与控制

### 风险 1：误删苏冰 Pivot

控制：明确 `app/market_data/subing_structure.py` 为 retained boundary；测试必须覆盖其 Pivot、breakout、retest 以及 Strategy bound pivot exit。

### 风险 2：删除 N 后仍残留 Web preference / API type

控制：做全仓 active reference scan；preference schema 升级并测试 migration。

### 风险 3：Multi-Candidate 删除误伤 SuBing Candidate Validation

控制：只删除 `app/research/robustness/*`、N Candidate 和相应 composition；保留 `app/research/subing/*candidate_validation*` 及其 protocol/manifest。

### 风险 4：文档提前宣称 Runtime 已无 N

控制：`STATUS.md` 区分 develop code state 与当前 production Runtime exact tag；release 和 Runtime promotion 分别保留人工 Gate。

### 风险 5：为了“以后可能用”保留 dead abstraction

控制：YAGNI。没有 active consumer 的 N/Multi-Candidate interface、DTO、protocol、test、generic wrapper 都删除；恢复依赖 Git history + 新任务。

## 13. 非目标

本任务不做：

- LuxAlgo 集成；
- 新震荡区间指标；
- 新 Swing/ZigZag/N 字算法；
- 把 N 算法塞入 SuBing；
- 修改苏冰策略公式；
- 修改 HTDY；
- 创建单 Candidate robustness；
- 自动策略晋升；
- 正式回测平台；
- DB migration；
- production 数据删除；
- main/tag/release；
- Runtime promotion；
- 真实通知。

## 14. 完成定义

本 retirement task 的 `CODE_COMPLETE / TEST_COMPLETE` 定义为：

> N Structure 与专用于 SuBing↔N 的 Multi-Candidate Robustness 已从 develop 的 active code、Web、API、CLI、research contracts、candidate/protocol 和 tests 中完整移除；active canonical 已收敛；SuBing、HTDY、Market retained invariants 通过验证；没有 production mutation。

这不等于 `RELEASED` 或 `RUNTIME_READY`。

后续 release 到 `main`、annotated tag，以及 Runtime promotion，分别按仓库正式流程和人工 Gate 执行。