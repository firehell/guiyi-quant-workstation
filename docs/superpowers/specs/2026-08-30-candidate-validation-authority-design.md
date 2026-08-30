# Candidate Validation Authority 收敛设计

Date: 2026-08-30
Status: draft / incomplete / implementation not authorized
Scope: SuBing Candidate Validation 的 manifest、protocol 与 typed loading seam；design-only
Review disposition: user-review-only branch artifact; MUST NOT be merged or cherry-picked into `develop`

## 1. 结论

保留两个 JSON 文件及其不同职责，不把 Candidate identity 合并进 Validation Protocol：

```text
data/research_candidates/subing_lifecycle_v2_candidate_v1.json
  -> Candidate identity authority

data/research_protocols/candidate_validation_v1.json
  -> Validation schedule authority
```

未来若另行批准实现，应用侧应以一个原子 `CandidateValidationAuthority` interface 同时加载两份 JSON，删除 Candidate Validation Python 中逐字段复制的 `_EXPECTED_CANDIDATE`、`_EXPECTED_PROTOCOL` 及 identity/window 常量。JSON 是字段值的唯一 authority；Python 只保留：

1. schema、类型、关系和安全不变量；
2. 每个已冻结文件的 raw-byte SHA-256 pin；
3. stable domain error code；
4. source producer 与 Candidate identity 的运行时交叉校验。

SHA-256 pin 不解释任何业务字段，不是第二份字段 authority。它只回答“这个已冻结 ID 对应的原始 bytes 是否仍是审核过的 bytes”，从而保留 same-ID byte drift fail-closed。

本设计不授权实现，不修改现有 JSON、policy、loader、Candidate reducer、Strategy Action、Canonical reader、Alert、Runtime 或 OOS 边界。

本文件只存在于 `refactor/research-policy-authority` review branch，供用户和独立 reviewer 判断取舍。它不是 tracked current fact、accepted canonical 或 implementation plan，绝不合入或 cherry-pick 到 `develop`；若设计被接受，后续任务从 review commit 读取结论，但在新的 implementation branch 以代码、测试和既有 current documents 交付，不搬运本 draft。

## 2. 当前仓库事实

当前树只有一个 Candidate manifest 与一个 Validation Protocol：

| Fact | Current value |
|---|---|
| Candidate file | `data/research_candidates/subing_lifecycle_v2_candidate_v1.json` |
| Candidate raw SHA-256 | `c597d7821cf98e933f9d818fa7995d4f2c2628d69afe122d4fdb644fcbdac78c` |
| Candidate ID | `subing_lifecycle_v2_candidate_v1` |
| Candidate source kind | `subing_lifecycle` |
| Candidate policy ID | `subing_lifecycle_v2_research_v1` |
| Candidate projection formula version | `subing_lifecycle_v2` |
| Protocol file | `data/research_protocols/candidate_validation_v1.json` |
| Protocol raw SHA-256 | `8da442e75b315a2684d5353cc2977afc8af839df153cb677b311a35d5d8cf438` |
| Protocol ID | `candidate_validation_v1` |
| Freeze | `2026-08-19T20:57:00+08:00` |
| Retrospective | `2023-01-01..2026-08-18` |
| Rolling schedule | 12 months reference / 3 months test / 3 months step; 2024Q1 through 2026Q2 |
| Prospective OOS first trading day | `2026-08-20` |
| Horizons | `3, 5, 8` bars |

`candidate_validation_policy.py` 当前同时保存 JSON 和 Python `_EXPECTED_*` 的完整字段副本，然后由 `load_exact_json()` 比较解析后的 Python object。它能拒绝 extra/missing/wrong value、bool/int 混淆、missing/malformed/non-UTF-8 文件，并生成 frozen typed dataclass；但字段值有两份 authority，且当前比较不锁定 key order、空白或末尾换行等 raw-byte drift。

`SubingCandidateValidationService` 当前另外保护两项 source identity：

- producer 的 `candidate_projection_formula_version` 必须等于 manifest 的 `formula_version`；
- 每个 source result 的 `products` 必须精确等于请求的单一 `(symbol,)`。

`SubingLifecycleResearchService` 自身要求注入 policy 的 `policy_id=subing_lifecycle_v2_research_v1`，并且只经 `ActualDominantResearchSegmentLoader -> MarketDataService -> Historical Canonical` 读取 source。Candidate manifest 中的 `formula_version=subing_lifecycle_v2` 是 Candidate projection identity；它不等于 lifecycle policy JSON 内部的公式版本 `subing_lifecycle_v2_structure_binding_v1`，两者不可在本次 authority 收敛中静默改名或合并。

当前 Candidate Validation 没有 Web/CLI 日常入口，不是 Runtime evaluator，也不生成自动 rank、winner、promotion、盈利或可交易结论。

## 3. 方案比较

### A. 把 Candidate identity 嵌入现有 Protocol

优点是只剩一份 JSON，pair binding 肉眼可见。缺点是不可接受：

- 向 `candidate_validation_v1.json` 增加 Candidate 字段会在同一 `protocol_id` 下改变 bytes，违反 same-ID drift fail-closed；
- 若为此创建新 protocol ID，则必须重新决定 freeze、prospective OOS 与 evidence lineage，超出“字段与 OOS 边界不变”；
- Candidate formula identity 与 validation schedule 具有不同变更原因，合并会让公式版本变化和研究窗口变化互相污染；
- 这不是当前单 Candidate/单 Protocol 所必需的抽象。

结论：拒绝。

### B. 保留两个独立 public loader

优点是改动最小。缺点是 composition 可分别加载，调用者需要知道 pair 组装顺序，字段副本与分散 identity check 继续存在，interface 仍接近实现复杂度。

结论：不作为目标状态。

### C. 保留两份 JSON，由一个原子 authority module 加载（推荐）

两份 JSON 保持不同领域职责和独立 digest；一个小 interface 隐藏 read/decode/typed validation/digest/pair validation。composition 只能获得完整 authority，不能得到半加载 pair。

这在不改变任何当前字段、ID 或 OOS boundary 的情况下获得 locality：same-ID drift、schema、错误映射与 pair 组装只在一处维护。

## 4. 目标 module 与 interface

未来实现只应提供一个 application-facing interface：

```python
@dataclass(frozen=True, slots=True)
class CandidateValidationAuthority:
    manifest: CandidateManifest
    protocol: CandidateValidationProtocol
    manifest_sha256: str
    protocol_sha256: str

load_candidate_validation_authority() -> CandidateValidationAuthority
```

`CandidateManifest` 与 `CandidateValidationProtocol` 继续是 frozen typed value objects。原来的 `load_candidate_manifest()` / `load_candidate_validation_protocol()` 不作为两个并行长期 public interfaces 保留；composition 改为一次注入完整 authority。若测试需要指定临时文件，路径注入只属于 loader 的 test seam，不建立 registry、plugin 或多 Candidate dispatch。

内部顺序固定为：

```text
read candidate/protocol raw bytes
-> UTF-8 + JSON object parse
-> exact key set + strict scalar/container type validation
-> domain relationship validation
-> raw SHA-256 compare with frozen pins
-> construct frozen typed values
-> return one atomic CandidateValidationAuthority
```

说明：typed validation 先于 digest comparison，便于证明 schema/invariant 仍真实执行；任何失败最终仍只暴露稳定 domain error，不泄露 path、payload 或内部异常。一个语义正确但仅改变空白、key order 或末尾换行的 same-ID 文件会在 digest gate fail-closed。

固定 filename 与解析出的 ID 必须一致：Candidate filename stem 等于 `candidate_id`，Protocol filename stem 等于 `protocol_id`。该关系由文件与 JSON 自证，不在 Python 再复制 ID 字符串。

## 5. JSON 唯一语义 authority

实现获批后，Candidate Validation application code 不再硬编码以下业务值：

```text
candidate_id
source_kind
candidate policy_id
candidate projection formula_version
protocol_id
candidate_frozen_at
retrospective dates
rolling 12/3/3 and first/last dates
prospective first_trading_day
horizons_bars
```

代码仍可硬编码 schema contract，例如 `schema_version == 1`、日期必须有时区、月份必须为正整数、horizons 必须是正整数且严格递增、`research_only is True`、未知字段拒绝。这些是类型/不变量，不是某个 frozen document 的字段副本。

Candidate report 和 window validation 需要 authoritative values 时，从已加载 authority 注入或由 authority-bound factory 构造；不得继续使用 `_CANDIDATE_ID`、`_POLICY_ID`、`_FORMULA_VERSION`、`_PROTOCOL_ID` 或 Candidate 层 `_HORIZONS` 的镜像常量。

source module 自己的 formula/policy identity 仍由 source module 与 lifecycle policy authority 拥有。Candidate authority 只声明它绑定哪个 source identity，然后在 service seam 做 equality check；Candidate JSON 不驱动或改写 lifecycle 公式。

## 6. 逐字段等价证明

实施前后必须以同一 baseline bytes、typed values、service calls、consumer-visible report facts 和字段缺席集合做 field-by-field comparison；不能只比较“测试通过”、dataclass equality 或最终 JSON 大对象。

### 6.1 Candidate manifest 全字段

| JSON field | Before JSON / typed value | Required after typed value | Service parity proof | Consumer/report parity proof |
|---|---|---|---|---|
| `schema_version` | JSON number `1` -> exact Python `int(1)`；`bool` 不接受 | `authority.manifest.schema_version` 的 exact type/value 仍为 `int(1)` | authority 构造前拒绝 `true`、`1.0`、缺失或其他版本 | `CandidateValidationReport.schema_version` 仍为 exact `int(1)`；serialized report 不增 manifest schema wrapper |
| `candidate_id` | string `subing_lifecycle_v2_candidate_v1` | 同一 string；filename stem equality 成立 | request 的 `candidate_id` 必须逐字相等，mismatch 在任何 source call 前返回 identity error | report `candidate_id` 逐字相等；CLI/Web surface 仍不存在 |
| `source_kind` | string `subing_lifecycle` | 同一 string | composition 仍只构造 `SubingCandidateValidationService` + lifecycle producer；不增加 source dispatch/fallback | report 继续不含 `source_kind` 字段；consumer-visible payload 零新增 |
| `policy_id` | string `subing_lifecycle_v2_research_v1` | 同一 string | 与 loaded `SubingLifecyclePolicy.policy_id` 逐字 equality；wrong policy 在 validation 前 fail-closed | report `policy_id` 逐字相等 |
| `formula_version` | string `subing_lifecycle_v2` | 同一 string | 与 producer `candidate_projection_formula_version` 逐字 equality；不得替换成 policy-internal `subing_lifecycle_v2_structure_binding_v1` | report `formula_version` 逐字相等 |
| `research_only` | JSON boolean `true` -> exact Python `bool(True)` | exact type/value 仍为 `bool(True)` | authority 与 protocol 均须为 true，false/1/missing 均 fail-closed；不产生 promotion consumer | report `research_only is True`；不新增 KEEP/DROP/PROMOTE |

Candidate manifest 的 before/after exact key tuple 都必须是：

```text
schema_version, candidate_id, source_kind, policy_id, formula_version, research_only
```

### 6.2 Validation Protocol 全字段

| JSON field | Before JSON / typed value | Required after typed value | Service/window parity proof | Consumer/report parity proof |
|---|---|---|---|---|
| `schema_version` | JSON number `1` -> exact Python `int(1)` | `authority.protocol.schema_version == 1` 且 exact type 为 `int` | invalid version/bool/float 在 schedule 构造前 fail-closed | report schema 仍为 exact `int(1)`；不新增 protocol schema wrapper |
| `protocol_id` | string `candidate_validation_v1` | 同一 string；filename stem equality 成立 | request `protocol_id` 必须逐字相等，mismatch 时 source calls 为空 | report `protocol_id` 逐字相等 |
| `research_only` | JSON boolean `true` -> exact Python `bool(True)` | exact type/value仍为 `bool(True)` | 与 manifest `research_only` 同为 true；false/1/missing fail-closed | report `research_only is True`，无 promotion/Runtime side effect |
| `candidate_frozen_at` | RFC3339 string `2026-08-19T20:57:00+08:00` -> aware `datetime`，相同 offset | exact aware datetime 与 `.isoformat()` string 均相等 | 不被重解释为 request cutoff、UTC naive time 或 source window；freeze 后第一 OOS trading day关系保持 | report 当前不输出 freeze field，after 也不得新增；evidence lineage 仍由 protocol identity表达 |
| `retrospective.since` | ISO date string `2023-01-01` -> exact `date(2023, 1, 1)` | 同一 exact `date` | 第一个 lifecycle source request `since` 逐项相等 | retrospective result/report `since` 逐项相等 |
| `retrospective.through` | ISO date string `2026-08-18` -> exact `date(2026, 8, 18)` | 同一 exact `date` | 第一个 source request `through` 相等；request `through` 更早时仍 window error 且零 source call | retrospective result/report `through` 相等；不进入 prospective counts |
| `rolling_stability.reference_months` | JSON number `12` -> exact Python `int(12)` | 同一 exact `int` | 每个 fold reference 从 test start 回退 12 calendar months；10 个 reference source requests逐项相等 | report 中 10 个 `reference.since/through` 全序列相等；不新增参数字段 |
| `rolling_stability.test_months` | JSON number `3` -> exact Python `int(3)` | 同一 exact `int` | 每个 test window 为连续 3 calendar months；10 个 test source requests逐项相等 | report 中 10 个 `test.since/through` 全序列相等 |
| `rolling_stability.step_months` | JSON number `3` -> exact Python `int(3)` | 同一 exact `int` | 相邻 test fold start 前进 3 calendar months，fold IDs 仍 `fold_01..fold_10` | report fold order/count/IDs 逐项相等 |
| `rolling_stability.first_test_since` | ISO date `2024-01-01` -> exact `date(2024, 1, 1)` | 同一 exact `date` | `fold_01.test.since` 与首个 test source request相等 | report `fold_01` reference/test dates相等 |
| `rolling_stability.last_test_through` | ISO date `2026-06-30` -> exact `date(2026, 6, 30)` | 同一 exact `date` | `fold_10.test.through` 与最后 test source request相等；不生成第 11 fold | report `fold_10` dates相等且 fold count 仍 10 |
| `prospective_oos.first_trading_day` | ISO date `2026-08-20` -> exact `date(2026, 8, 20)` | 同一 exact `date` | through=2026-08-18/19 时 pending 且不调用 prospective source；through=2026-08-20 时 source request精确为 `2026-08-20..2026-08-20` | `ProspectiveOosResult.first_trading_day/status/through/result` 逐项相等；不回填 freeze 前事实 |
| `horizons_bars` | JSON array `[3, 5, 8]` -> exact tuple `(3, 5, 8)` | 同一有序 `tuple[int, ...]`；元素不得为 bool/float，增删/重排 fail-closed | lifecycle source horizon keys、projection validation keys与 protocol tuple逐项相等 | 每个 retrospective/reference/test/prospective window 的 `horizon_summary` key order/value逐项相等 |

Protocol 的 top-level before/after exact key tuple 必须是：

```text
schema_version, protocol_id, research_only, candidate_frozen_at,
retrospective, rolling_stability, prospective_oos, horizons_bars
```

Nested exact key tuples 必须分别是：

```text
retrospective: since, through
rolling_stability: reference_months, test_months, step_months,
                   first_test_since, last_test_through
prospective_oos: first_trading_day
```

### 6.3 字段缺席等价

字段缺席也是 frozen contract；typed loader 的 exact-key validation 和 report serialization 都必须证明 before/after 缺席集合一致。

| Absent field/category | Before meaning | Required service/consumer/report parity proof |
|---|---|---|
| Manifest 中无 `protocol_id`、freeze、retrospective、rolling、OOS、horizons | Candidate identity 不拥有 validation schedule | authority 仍以两个 typed values分工；不把 schedule 填入 manifest，不合并 JSON |
| Protocol 中无 `candidate_id`、`source_kind`、`policy_id`、`formula_version` | Protocol 不拥有 Candidate/source formula identity | atomic loader 只配对当前固定文件，不把 Candidate fields 注入/序列化到 protocol |
| 两文件均无 `threshold`、`score`、`pass`、`rank`、`winner` | Candidate Validation 无 acceptance/profit threshold | `test_quality_flags_are_factual_and_threshold_free` 语义保持；report 只含 factual flags |
| 两文件均无可调 `embargo` | rolling reference/test 相邻且不调参；prospective fence由 freeze + first trading day表达 | `reference_through + 1 day == test_since`；2026-08-18/19 pending，2026-08-20 首次 eligible；report 不新增 embargo field |
| 两文件均无 `products`、`cohort`、`symbols` | Candidate 不绑定 product cohort；一次 request只处理一个 symbol | active-scope validation、lowercase ASCII normalization与 source `products == (symbol,)` 保持；report `symbol` 单值和 window `products` 单元素保持 |
| 两文件均无 source path/reader/fallback override | source path由 application composition与 producer identity约束 | dependency graph仍是 `SubingLifecycleResearchService -> ActualDominantResearchSegmentLoader -> MarketDataService`；report 不暴露可选 source |
| 两文件均无 digest/self-hash field | raw-byte pin 是 code-side acceptance lock，不是可随 JSON 同步改写的 self-attestation | JSON bytes/key sets零变化；authority object可持有 digest，但 manifest/protocol/report payload不新增 digest field |
| 两文件均无 KEEP/DROP/PROMOTE/Runtime/Alert state | 人工审阅与运行授权独立 | report payload、composition consumer、side-effect surface零新增 |
| Report 中无 `source_kind`、`candidate_frozen_at`、schedule parameters、digest | 当前 report只输出研究事实和必要 identity | before/after serialized key set逐项相等；不得因 authority consolidation扩展 report schema |

Candidate report top-level before/after field sequence 必须逐项保持：

```text
schema_version, candidate_id, policy_id, formula_version, protocol_id,
research_only, symbol, retrospective, rolling_folds, rolling_stability,
prospective_oos, quality_flags
```

`source_kind`、freeze、rolling parameters 与 authority digests 只参与 identity/编排验证，不得借本重构扩展 report 或创建新 consumer。

### 6.4 Identity、window、OOS 与 error parity

- formula/policy 三身份逐项保持：Candidate projection=`subing_lifecycle_v2`、lifecycle policy ID=`subing_lifecycle_v2_research_v1`、policy-internal formula=`subing_lifecycle_v2_structure_binding_v1`；三者不改名、不互相替代。
- source identity 保持 `subing_lifecycle` + producer formula equality + exact single-symbol products；source failure仍不返回 partial report。
- window parity 以完整 source request sequence证明：1 retrospective + 20 rolling requests，pre-OOS 共 21 次；首个 prospective day共 22 次。只核对最终 fold count不充分。
- prefix determinism、source-specific causality、strict-before、prefix invariance 与 golden parity tests不得由 document digest tests替代。
- 下节列出的每个 exact error string before/after逐项相等；manifest/protocol atomic loading不引入 generic authority error，不泄露半加载对象。

不得借 authority refactor新增 acceptance threshold、cohort list、embargo tunable、promotion state、source override或 consumer-visible report字段。

## 7. Error contract

以下 application-facing codes、before trigger 与 after observable behavior 必须逐项保持：

| Exact code | Before trigger | Required after parity proof |
|---|---|---|
| `CANDIDATE_MANIFEST_INVALID` | Candidate missing/malformed/non-UTF-8、wrong type/key/value、same-ID semantic drift | 相同输入仍返回 exact code；新增 raw-byte-only drift也复用此 code；不暴露 protocol half-object |
| `CANDIDATE_VALIDATION_PROTOCOL_INVALID` | Protocol missing/malformed/non-UTF-8、wrong type/key/value、same-ID semantic drift | 相同输入仍返回 exact code；新增 raw-byte-only drift也复用此 code；不暴露 manifest half-object |
| `CANDIDATE_VALIDATION_REQUEST_INVALID` | candidate/protocol identifier syntax、symbol syntax 或 through type invalid | request dataclass在 service/source call前返回 exact code；normalization行为相等 |
| `CANDIDATE_VALIDATION_IDENTITY_MISMATCH` | request candidate/protocol ID不等或 producer formula不等 | exact code、零 source calls与无 report行为相等 |
| `CANDIDATE_VALIDATION_WINDOW_INVALID` | through早于 retrospective through，或 rolling/prospective date math invalid | exact code、零/停止后续 source calls与无 partial report行为相等 |
| `CANDIDATE_VALIDATION_SOURCE_UNAVAILABLE` | lifecycle producer exception、wrong result type 或 products identity mismatch | exception继续被包裹成 exact code；不泄露内部 source message，不返回 partial report |
| `CANDIDATE_WINDOW_INVALID` | projected window ID/kind/date/products/count/maps/horizons invalid | exact ValueError string与拒绝时点相等 |
| `CANDIDATE_ROLLING_FOLD_INVALID` | fold ID 或 reference/test kind invalid | exact ValueError string与无 report行为相等 |
| `CANDIDATE_STABILITY_INVALID` | fold summary count/median contract invalid | exact ValueError string与 Decimal semantics相等 |
| `CANDIDATE_PROSPECTIVE_OOS_INVALID` | pending/evaluated status、date或 result presence/kind不一致 | exact ValueError string；pending/evaluated边界行为相等 |
| `CANDIDATE_VALIDATION_REPORT_INVALID` | report identity/schema/symbol/folds/summary/prospective/flags invalid | exact ValueError string；authority-bound construction不削弱 direct report invariant |

Candidate 文件失败只返回 manifest code；Protocol 文件失败只返回 protocol code。atomic authority loader 不得新增 generic authority error 或“半成功”对象。source exception 仍映射为 source-unavailable code，不返回 partial report。

## 8. Digest 与 drift 测试合同

未来实现至少增加以下 interface-level tests：

1. 当前两份 tracked bytes 的 SHA-256 分别等于本设计记录的 pins，并成功构造 authority；
2. 同 ID 改任一业务 byte，typed validation 或 digest gate fail-closed；
3. 同 ID 仅改 key order、空白、缩进或末尾换行，typed values 虽可解析但 raw digest gate fail-closed；
4. missing、malformed、non-UTF-8、non-object、extra/missing nested key、bool/int 混淆继续返回原错误码；
5. typed objects 和 authority 均 immutable；
6. 单个文件失败不暴露另一个 typed value；
7. source formula mismatch、wrong candidate/protocol request ID、wrong source products、source exception 继续 fail-closed；
8. 现有 retrospective、10 folds、prospective pending/evaluated、prefix determinism 与 threshold-free quality flags zero regression；
9. git diff 证明三份 source facts的 bytes 均未变化：Candidate manifest、Validation Protocol、SuBing lifecycle policy。

现有 source-specific causality、strict-before、prefix invariance 与 golden parity 保护不得删除或降级；authority 重构只能在这些测试之外增加 document-identity tests，不能用 digest test 替代计算语义测试。

Digest pin 更新规则：同一 ID 不允许“顺手更新 hash 让测试变绿”。业务字段或 bytes 需要变化时必须由新设计解释 identity/version 迁移；本设计不提供该迁移授权。

## 9. HTDY strict / original 与 legacy policy 边界

本 authority 只属于 SuBing Candidate Validation。不得顺带整理 `packages/quant-core/guiyi_quant/indicators/registry.py` 或 `policy.py`：

- `huotian_dayou_original_v0` 是 repainting、`observation_only`，仅允许明确命名的 Web/current-bar observation consumer；
- `huotian_dayou_strict_v1` 是 causal `strategy_candidate`，仅允许 historical research/backtest consumer，不允许 Web/live/Alert/notification；
- EMA/MACD/ATR 的 frozen legacy policies 也各自绑定既有 consumer 与公式身份。

这些不是 Candidate manifest 与 Validation Protocol 的重复常量，而是独立 Indicator Kernel strategy identity。合并、重命名、迁移到 JSON、共享 digest loader 或删除 legacy policy 都可能改变公式、consumer capability 与研究 lineage，必须是另一项明确的策略身份设计。当前任务对其唯一允许的验证是零 diff 与现有 registry/policy tests 通过。

## 10. 明确禁止项

本设计及任何未获单独批准的后续工作不得：

- 修改或重写 Candidate manifest、Validation Protocol、SuBing lifecycle policy JSON；
- 改 lifecycle reducer、Factor/Signal/Calibration、Strategy Action、Episode 或成交语义；
- 改 `MarketDataService`、Canonical/Catalog/MainContractMap reader 或 source window；
- 改 retrospective、rolling、embargo/prospective OOS 边界或回填历史 OOS；
- 新增 threshold、rank、winner、KEEP/DROP/PROMOTE 或自动参数选择；
- 新建 registry、plugin、通用 Candidate adapter、DB、cache、worker、queue、HTTP、Web 或 CLI surface；
- 修改 HTDY original/strict 或 frozen legacy indicator policy；
- 改 Alert Rule/Scope/Event、notification、Runtime、launchd、production 配置；
- 执行 RQData、Canonical、PostgreSQL、Redis 或其他真实数据写入；
- 声称 design approval 等于 implementation、release 或 Runtime promotion 授权。

## 11. 预计实现范围（未授权）

若用户另行批准 implementation plan，最小候选范围是：

```text
services/quant-api/app/research/subing/candidate_validation_policy.py
services/quant-api/app/research/subing/candidate_validation.py
services/quant-api/app/research/subing/subing_candidate_validation_service.py
services/quant-api/app/research/composition.py
services/quant-api/tests/test_candidate_validation_policy.py
services/quant-api/tests/test_candidate_validation.py
services/quant-api/tests/research/test_subing_candidate_validation_service.py
```

三份 JSON、source lifecycle implementation、HTDY/legacy policy、Canonical reader、Strategy 与 Runtime 均不在预计修改范围。实施必须采用 TDD，先固定本设计的 field-equivalence matrix 与 raw-byte drift tests，再替换 loader/interface；不得保留新旧两套 active authority。

## 12. 当前 Gate

状态保持：`DESIGN_DRAFT_INCOMPLETE`。

本文件只供用户与独立 reviewer 在未合入 branch 审阅；无论 review 结论如何，本 draft commit 都不得 merge、squash merge 或 cherry-pick 到 `develop`，也不得复制进 `STATUS.md`、`AGENTS.md`、`PROJECT_SOURCE.md`、`DECISIONS.md` 或 `docs/ARCHITECTURE.md`。

当前没有授权写 implementation plan、修改 application code、更新 digest pin、变更 JSON、发布或 Runtime promotion。唯一下一步是审阅“保持分离 + 原子 authority loader”的取舍及上述逐字段 proof；若用户明确批准设计，应另开 implementation task/branch，以既有 current facts为准执行，不合入本 draft。
