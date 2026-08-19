# Candidate Validation V1 设计规格

> 状态：Design basis approved（用户选择方案 B）；本文件经仓库 canonical 对齐与自审后用于 implementation plan，不代表 Candidate 已有效、已晋升或已获得任何 production 授权。
>
> 日期：2026-08-19
>
> 规划基线：`develop@b634e0c966284d511bcda0ad9e7395c2f03131d9`
>
> 上游设计：`docs/superpowers/specs/2026-08-19-subing-lifecycle-v2-design.md`
>
> 范围：Phase 4A SuBing Evidence Baseline + Phase 4B Candidate Validation V1。首版只验证现有 `subing_lifecycle_v2_research_v1`，不修改 SuBing V1/V2 公式、Alert、Scope、Clawbot、Execution Review、Data Foundation、release 或 Runtime。

## 1. 结论

SuBing Lifecycle V2 已经完成以下链路：

```text
exact research policy
→ causal lifecycle
→ Historical-only Shadow
→ funnel / confirmation / risk / close / 3/5/8 bar outcome summaries
```

下一阶段不继续堆新指标，而是增加一个**最小、研究专用、不可自动晋升**的 Candidate Validation V1，把已经存在的 Shadow 事实组织成：

```text
Candidate identity
→ retrospective evidence baseline
→ rolling historical stability
→ prospective OOS evidence
→ versioned CandidateReport
→ human review
```

Candidate Validation V1 不是传统交易回测平台，不模拟账户、订单、保证金、仓位、成交、手续费或组合收益。首版只回答：

1. 当前 Candidate 在不同历史窗口中的机会漏斗和结果分布是否稳定；
2. 3/5/8 Bar directional return、MFE、MAE、EMA21 failure 是否随窗口显著漂移；
3. FORMAL_V1 / MOMENTUM_HOLD / PIVOT_BREAK_HOLD / PIVOT_RETEST_REBREAK 的来源分布是否稳定；
4. V1/V2 overlap、risk/recovery/close reasons 是否集中在少数时期；
5. Candidate freeze 之后的真正 prospective OOS 样本发生了什么。

任何结果都只形成研究证据，不自动输出“可晋升”“可发 Alert”或“可交易”。

## 2. 当前事实与前置条件

规划基线下：

- `STATUS.md` 记录 production Git release 与 Runtime 已为 v1.6.1；SuBing Lifecycle V2 已 release / Runtime promoted，但仍是 `research_only`。
- `SubingLifecycleResearchService` 已只经 `MarketDataService` 读取 Historical Canonical，并按 true current-rank1 segment 独立复算。
- `guiyi research subing-lifecycle` 已输出 funnel、confirmation source、V1/V2 overlap、lead bars、same/cross-day、risk/recovery/close reason，以及 3/5/8 Bar directional return / MFE / MAE / EMA21 failure。
- 当前仓库没有 backtest API/Web/worker/queue，也没有账户、订单或通用 Strategy Plugin Engine。
- Data Foundation、Market Catalog、Historical Gateway、Historical/Live 分离边界保持冻结。

因此 Phase 4B 必须**复用**现有 Shadow 事实，不另写第二套 SuBing outcome 算法，不直读 Parquet，不复制 rank1 resolver。

## 3. 研究地位

本阶段只使用三类地位：

| 地位 | 含义 |
| --- | --- |
| `EXISTING_ACCEPTED` | 当前仓库已经冻结且有测试的 SuBing V1/V2 因果与数据语义 |
| `VALIDATION_PROTOCOL` | 本设计新增的 Candidate 识别、窗口、报告和 prospective OOS 协议 |
| `RESEARCH_PENDING` | 研究结果尚未形成足够证据，不能推导正式 Rule 或策略有效性 |

不得把 retrospective 结果改写成真实 OOS，也不得把 historical rolling simulation 称为生产 Shadow 或 live evidence。

## 4. Candidate V1 identity

首个 Candidate 精确为：

```text
candidate_id   = subing_lifecycle_v2_candidate_v1
source_kind    = subing_lifecycle
policy_id      = subing_lifecycle_v2_research_v1
formula_version= subing_lifecycle_v2
research_only  = true
```

Git-tracked manifest：

```text
data/research_candidates/subing_lifecycle_v2_candidate_v1.json
```

Exact payload：

```json
{
  "schema_version": 1,
  "candidate_id": "subing_lifecycle_v2_candidate_v1",
  "source_kind": "subing_lifecycle",
  "policy_id": "subing_lifecycle_v2_research_v1",
  "formula_version": "subing_lifecycle_v2",
  "research_only": true
}
```

规则：

- 同 `candidate_id` 内容漂移 fail-closed；
- 任何 SuBing lifecycle 公式、确认规则、风险/关闭规则或 exact policy 的语义变化必须产生新的 `candidate_id`；
- Candidate manifest 不绑定 Alert Scope、不绑定 Runtime、不绑定产品列表；
- 首份真实 Evidence Baseline 只运行 `jm`，不表示 Candidate 只支持 `jm`；
- Candidate manifest 不保存盈利结论、人工评级或 promotion 状态。

## 5. Validation Protocol V1

Git-tracked protocol：

```text
data/research_protocols/candidate_validation_v1.json
```

Exact payload：

```json
{
  "schema_version": 1,
  "protocol_id": "candidate_validation_v1",
  "research_only": true,
  "candidate_frozen_at": "2026-08-19T20:57:00+08:00",
  "retrospective": {
    "since": "2023-01-01",
    "through": "2026-08-18"
  },
  "rolling_stability": {
    "reference_months": 12,
    "test_months": 3,
    "step_months": 3,
    "first_test_since": "2024-01-01",
    "last_test_through": "2026-06-30"
  },
  "prospective_oos": {
    "first_trading_day": "2026-08-20"
  },
  "horizons_bars": [3, 5, 8]
}
```

### 5.1 为什么历史窗口不叫 OOS

Candidate 在 2026-08-19 之前已经可能接触过全部历史数据，因此：

```text
2023-01-01 .. 2026-08-18
```

只能叫 `retrospective`。

滚动历史窗口只能叫：

```text
rolling_historical_stability
```

不得叫 true OOS、真实 Shadow 或 prospective evidence。

### 5.2 真正 prospective OOS

本协议在 2026-08-19 20:57 +08:00 冻结 Candidate 验证边界，早于当晚 21:00 夜盘。第一份允许进入 prospective OOS 的 trading day 精确为：

```text
2026-08-20
```

只有 `trading_day >= 2026-08-20`、并且由后续 Historical Canonical 可复算的数据，才允许进入 `prospective_oos`。

缺少未来样本时：

```text
prospective_oos.status = pending
```

不得用 2026-08-19 以前历史数据填充。

### 5.3 Rolling historical stability

固定算法：

```text
reference window = 12 calendar months
next test window = 3 calendar months
step             = 3 calendar months
first test       = 2024-01-01 .. 2024-03-31
last test        = 2026-04-01 .. 2026-06-30
```

共 10 个 test folds。Reference 只用于说明“前 12 个月的背景分布”，**不得在 fold 内调参数、重选 Policy 或生成新 Candidate**。

Candidate 的 formula/policy 在所有 folds 中保持完全相同。

## 6. 数据与计算边界

唯一链路：

```text
CandidateValidationService
→ existing SubingLifecycleResearchService
→ MarketDataService
→ Historical Canonical
```

硬约束：

- 不直接读 Parquet、Redis、RQData、PostgreSQL Bar；
- 不调用 Live Overlay；
- 不增加第二套 actual-dominant / rank1 segment resolver；
- 不复制 `build_outcomes_at()` 或 lifecycle reducer；
- 不修改 existing Shadow CLI 的计算语义；
- 不写 DB / Canonical / Redis；
- 不创建 worker、queue、outbox、scheduler；
- 不从 AlertEvent 或 Execution Review 反向构造 Candidate；
- 研究价格/收益相关数值继续使用现有 Decimal 语义；
- 任一 window 查询的 rank1 identity、coverage 或物理可读性异常必须 fail-closed。

## 7. V1 domain contract

首版不建立 Strategy interface / plugin / registry。只增加最小通用报告合同和一个 SuBing adapter。

### 7.1 `CandidateManifest`

```python
@dataclass(frozen=True, slots=True)
class CandidateManifest:
    schema_version: int
    candidate_id: str
    source_kind: str
    policy_id: str
    formula_version: str
    research_only: bool
```

### 7.2 `CandidateValidationProtocol`

```python
@dataclass(frozen=True, slots=True)
class CandidateValidationProtocol:
    protocol_id: str
    candidate_frozen_at: datetime
    retrospective_since: date
    retrospective_through: date
    reference_months: int
    test_months: int
    step_months: int
    first_test_since: date
    last_test_through: date
    prospective_oos_first_trading_day: date
    horizons_bars: tuple[int, ...]
```

### 7.3 `CandidateWindowResult`

它是 existing `SubingLifecycleResearchResult` 的稳定投影，不重新计算 lifecycle：

```text
window_id
window_kind
since / through
sample products
segment_count
evaluable_boundary_count
funnel_counts
confirmation_source_counts
v1_v2_overlap_counts
v2_to_v1_lead_bars
same/cross-day counts
risk/recovery/close reason counts
3/5/8 horizon_summary
```

`window_kind` 首版只允许：

```text
RETROSPECTIVE
ROLLING_REFERENCE
ROLLING_TEST
PROSPECTIVE_OOS
```

### 7.4 `CandidateValidationReport`

```text
schema_version
candidate_id
policy_id
formula_version
protocol_id
research_only=true
symbol
retrospective
rolling_folds[]
prospective_oos
quality_flags[]
```

Report 不包含：

```text
KEEP
DROP
PROMOTE
PASS_STRATEGY
expected_profit
account_return
```

人工判断是报告之后的独立行为。系统只报告观察事实与不可用状态。

## 8. Evidence Baseline V1

第一份版本化证据只针对：

```text
candidate = subing_lifecycle_v2_candidate_v1
symbol    = jm
protocol  = candidate_validation_v1
```

必须至少包含：

1. retrospective 全窗口漏斗；
2. confirmation source 分布；
3. V1_AND_V2 / V2_ONLY / V1_ONLY；
4. V2→V1 lead bars；
5. same-day / cross-day；
6. risk / recovery / close reason；
7. 3/5/8 Bar directional return / MFE / MAE / EMA21 failure；
8. 10 个 rolling historical test folds；
9. prospective OOS 截止运行日的真实状态；若尚无样本必须是 `pending`。

首份 artifact：

```text
reports/research/candidate_validation/
  subing_lifecycle_v2_candidate_v1/
    2026-08-19-jm-baseline.json
```

CLI 本身继续只输出 stdout JSON；artifact 通过执行时的 shell redirection 写入仓库文件，不给 CLI 增加任意文件写能力。

## 9. CLI

新增 read-only command：

```text
guiyi research candidate-validation
  --candidate subing_lifecycle_v2_candidate_v1
  --protocol candidate_validation_v1
  --symbol jm
  --through YYYY-MM-DD
```

语义：

- `--candidate` 和 `--protocol` 首版只接受 exact frozen ID；
- `--symbol` 必须属于现有 active product scope；
- `--through` 只控制 prospective OOS 截止日期，不改变 retrospective/rolling frozen windows；
- `--through < 2026-08-20` 时 prospective OOS 为 `pending`；
- CLI 输出 `readonly=true`；
- 不支持动态修改 horizons、fold size、Policy、candidate identity 或 source formula。

## 10. Stability 解释边界

首版不创造一个综合“稳定性分数”。

系统只输出每个 rolling fold 的：

```text
ENTRY_CONFIRMED sample count
confirmation source distribution
V1/V2 overlap
risk / recovery / close reasons
3/5/8 bar outcome summary
```

并提供简单、无阈值的描述统计：

```text
fold_count
folds_with_entries
entry_count_min
entry_count_max
entry_count_median
```

不得自动把某个方向收益为正的 fold 判为 PASS，也不得根据历史 fold 自动调 Candidate。

## 11. Error / unavailable

以下情况 fail-closed：

```text
candidate manifest missing / malformed / same-ID drift
validation protocol missing / malformed / same-ID drift
candidate ↔ policy/formula identity mismatch
unsupported candidate / protocol
symbol outside active scope
retrospective or rolling window outside canonical history floor
prospective request attempts to include pre-freeze data
existing lifecycle research failure
rank1 segment mismatch / coverage failure / unreadable canonical
```

稳定错误码：

```text
CANDIDATE_MANIFEST_INVALID
CANDIDATE_VALIDATION_PROTOCOL_INVALID
CANDIDATE_VALIDATION_IDENTITY_MISMATCH
CANDIDATE_VALIDATION_WINDOW_INVALID
CANDIDATE_VALIDATION_SOURCE_UNAVAILABLE
```

任何 failure 不生成 partial“成功”报告。

## 12. 测试合同

必须证明：

- exact manifest/protocol loader 对 extra/missing/wrong value fail-closed；
- candidate formula/policy identity 与现有 lifecycle exact ID 一致；
- validation service 只调用 existing `SubingLifecycleResearchService`，不出现新的 MarketData reader；
- retrospective 固定为 `2023-01-01..2026-08-18`；
- rolling folds 精确为 12m reference + 3m test + 3m step，首 test 2024Q1、末 test 2026Q2，共 10 folds；
- fold reference 不修改 candidate 或 policy；
- prospective OOS 不允许吸收 `trading_day < 2026-08-20`；
- through 早于 prospective start 时输出 pending 而不是伪造空 OOS success；
- existing `guiyi research subing-lifecycle` payload zero regression；
- same input / same Canonical prefix 产生相同 Candidate report 事实字段；
- CLI 仍无 DB/Canonical/Redis/Runtime/notification side effect；
- Decimal serializer 与现有 research CLI 规则一致。

## 13. Non-goals / YAGNI

V1 不做：

```text
通用 Strategy Plugin Engine
Strategy Registry / online candidate selector
动态参数搜索 / optimizer / grid search
自动阈值选择
账户、订单、撮合、手续费、滑点、保证金、持仓或 equity curve
Portfolio Engine
DB candidate tables / research event store
Redis candidate cache
HTTP Candidate API
Candidate Web dashboard
worker / queue / scheduler
AI 自动 KEEP / DROP / PROMOTE
Alert Rule / Scope / notification
release / Runtime promotion
N1/N2/N3/N4
JDJ 1m
```

N 字进入项目时，再以第二个真实 Candidate 验证哪些 report/adapter primitive 值得抽成通用接口。

## 14. 实现拆分

Implementation plan 应拆为：

```text
Task 1 exact Candidate Manifest + Validation Protocol + immutable contracts
Task 2 pure CandidateWindowResult / CandidateValidationReport projection
Task 3 SuBing CandidateValidationService + retrospective/rolling/prospective orchestration
Task 4 read-only CLI + composition wiring
Task 5 causality / temporal leakage / zero-regression verification
Task 6 architecture/testing documentation + independent code review + develop integration
Task 7 exact-develop jm Evidence Baseline run + versioned report artifact
Task 8 evidence review + Phase 4B closeout
```

Tasks 1–6 是仓库开发；Task 7 是只读 Historical research + Git-tracked report artifact；Task 8 只做 evidence review。没有任何 Task 自动触碰 `main`、tag、release、Runtime、Alert Scope、真实通知、DB/Canonical 写入或订单。

## 15. 进入 N 字之前的 Gate

Phase 4B 完成不等于 SuBing 值得晋升。

只有当以下事实成立后，才允许开始 N 字 Structural Domain V1 的实现规划：

```text
Candidate Validation V1 contract implemented
+ candidate-validation CLI verified
+ jm retrospective baseline produced
+ rolling historical stability produced
+ prospective OOS boundary frozen and not backfilled
+ independent review has no Critical/Important defect
```

这只是“验证基础设施可用”的 Gate，不是“SuBing 策略有效”的 Gate。
