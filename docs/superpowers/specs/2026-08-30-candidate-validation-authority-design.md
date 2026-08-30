# Candidate Validation Authority 收敛设计

Date: 2026-08-30
Status: draft / incomplete / implementation not authorized
Scope: SuBing Candidate Validation 的 manifest、protocol 与 typed loading seam；design-only

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

实施前后必须以同一 baseline bytes、typed values、service requests 和 report facts 做 field-by-field comparison；不能只比较“测试通过”或最终 JSON 大对象。

| Invariant | Before value/meaning | Required proof after authorized implementation |
|---|---|---|
| Candidate ID | `subing_lifecycle_v2_candidate_v1` | loader typed value、request equality check、report field逐项相等；same ID 任一 byte 改动拒绝 |
| Formula/policy identity | Candidate projection=`subing_lifecycle_v2`; lifecycle policy ID=`subing_lifecycle_v2_research_v1`; policy-internal formula=`subing_lifecycle_v2_structure_binding_v1` | authority 与 producer property、loaded lifecycle policy 逐项 equality；三者不改名、不互相替代 |
| Validation threshold | Candidate Validation 没有 pass/score/profit threshold；quality flags 仅为 factual flags | 证明 protocol 无 threshold/score/rank key，`test_quality_flags_are_factual_and_threshold_free` 语义保持；不从 policy/calibration复制阈值进 protocol |
| Horizons | `(3, 5, 8)` | protocol typed tuple、source result keys、window result keys逐项相等；增删/重排同 ID fail-closed |
| Embargo | JSON 无可调 `embargo` 字段；rolling reference 与 test 相邻且不调参；prospective fence 由 freeze 与 `first_trading_day=2026-08-20` 形成，freeze 前事实仅可作 causal warm-up、不得进入 prospective counts | 证明无新 embargo 参数；`reference_through + 1 day == test_since`；2026-08-18/19 为 pending 且无 prospective source call；首次 eligible request 精确从 2026-08-20 开始 |
| OOS boundary | freeze=`2026-08-19T20:57:00+08:00`; first trading day=`2026-08-20`; retrospective 不回填 OOS | raw fields、aware datetime、pending/evaluated transition、source request ranges逐项相等 |
| Cohort | authority 不绑定产品列表；一次 validation request 是一个 lowercase ASCII symbol，source result 必须是同一 `(symbol,)`; 历史 baseline 的 `jm` 不等于 Candidate scope | 证明 manifest/protocol 没有 products/cohort key；request normalization、active scope validation及 exact source products check 保持 |
| Source identity | `subing_lifecycle` + projection formula equality + lifecycle policy ID；source path保持 `SubingLifecycleResearchService -> ActualDominantResearchSegmentLoader -> MarketDataService` | composition dependency graph、formula/policy equality tests、wrong products/source failure tests；不新增 reader、fallback 或 source digest substitute |
| Error codes | 见下节 | 对每类现有 failure 逐一断言 exact code；不把所有失败折叠成新的 generic code |

“字段不变”也包括字段缺席不变。不得借 authority refactor 新增 acceptance threshold、cohort list、embargo tunable、promotion state 或 source override。

## 7. Error contract

以下 application-facing codes 必须保持：

```text
CANDIDATE_MANIFEST_INVALID
CANDIDATE_VALIDATION_PROTOCOL_INVALID
CANDIDATE_VALIDATION_REQUEST_INVALID
CANDIDATE_VALIDATION_IDENTITY_MISMATCH
CANDIDATE_VALIDATION_WINDOW_INVALID
CANDIDATE_VALIDATION_SOURCE_UNAVAILABLE
CANDIDATE_WINDOW_INVALID
CANDIDATE_ROLLING_FOLD_INVALID
CANDIDATE_STABILITY_INVALID
CANDIDATE_PROSPECTIVE_OOS_INVALID
CANDIDATE_VALIDATION_REPORT_INVALID
```

Candidate 文件失败只返回 `CANDIDATE_MANIFEST_INVALID`；Protocol 文件失败只返回 `CANDIDATE_VALIDATION_PROTOCOL_INVALID`。atomic authority loader 不得新增“半成功”对象。source exception 仍包裹为 `CANDIDATE_VALIDATION_SOURCE_UNAVAILABLE`，不返回 partial report。

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

本文件可供独立 Review，但没有授权写 implementation plan、修改 application code、更新 digest pin、变更 JSON、合入 `develop`、发布或 Runtime promotion。唯一下一步是由用户/主任务 reviewer 审阅“保持分离 + 原子 authority loader”的取舍及 field-equivalence proof；只有明确批准后才能规划实现。
