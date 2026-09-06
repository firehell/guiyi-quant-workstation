# SuBing Knowledge Foundation · Stage 1 Implementation Plan

日期：2026-09-06
状态：`PLAN_REVIEWED / IMPLEMENTATION_NOT_STARTED`
规划基线：`develop@6f6020f2cdd7280cddab69db89353069cff8e5fd`

> **For agentic workers:** REQUIRED SUB-SKILL: use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans`. Every code task uses TDD, fresh verification and review before integration.

**Goal:** 在不改变归一量化任何当前产品、行情、策略、Alert、Runtime 或 production fact 的前提下，在独立私有 workspace 中实现并发布 `SuBing Knowledge Foundation v1`。

**Architecture:** 原始课程资产只读；独立 Foundation repo 负责 `Source Calibration → Source Registry → Normalized Segment → Semantic Candidate → Human Review → Case/Evaluation Isolation → Immutable Snapshot`。Foundation Canonical 使用 UTF-8 JSONL + manifest；SQLite/FTS/embedding/vector/graph 仅允许未来作为可重建 Derived，本 Stage 不实现。

**Tech Stack:** Python 3.13、`uv`、Pydantic 2、Typer、orjson、python-docx、python-pptx、PyMuPDF、pytest、Ruff、Mypy；macOS legacy `.doc` 只用系统 `/usr/bin/textutil` 做只读转换。不增加云模型 SDK、数据库服务、Web 服务、RQData、Redis、PostgreSQL 或 Runtime 依赖。

**Spec:** `docs/tasks/2026-09-06-subing-knowledge-foundation-stage1-design.md`

**Owner planning exception:** Stage 1 Spec §3.2 原先只允许 Guiyi 仓库保存设计文档；Owner 本轮明确要求 Implementation Plan 提交 `develop`，因此本计划是额外允许的一份协调文档。该例外不授权把 Stage 1 实现代码、schema、测试、私有数据、课程内容、Adapter 或 Runtime 依赖写入 `guiyi-quant-workstation`。

---

## 1. Global Constraints

- Stage 1 实现代码与私有数据全部位于 `guiyi-quant-workstation` 之外；归一仓库只保存 Stage 1 Spec 与本 Plan。
- 原始课程根目录只读，不修改、移动、重命名、删除任何视频、字幕、PPT、PDF、transcript、note、learning-notes。
- 不读取 `MarketDataService`，不接 RQData、Canonical、Catalog、MainContractMap、production PostgreSQL/Redis、Market、Alert、PushPlus 或 Runtime。
- 不修改或复用 `subing_ths_alert_15m_v1` / `subing_ths_15m_v3`；不恢复已退役 SuBing 策略；`auto_order=false` 不变。
- 不实现 RAG、向量数据库、知识图谱、课程 QA、行情分析、Rule Evaluator、回测、OOS/Walk-forward/Shadow、微调、行为克隆、声音/形象数字人。
- 不自动参数化“附近、明显、远离、有效”等模糊表述；不自动综合 primary conflict；不用通用金融知识补课程缺口。
- 未经 Owner 对内容级外发单独批准，不把课程正文/视频/课件/截图/长段笔记发给外部模型/API。Stage 1 默认 `network_mode=disabled`，不实现模型网络调用。
- holdout outcome、隐藏答案和同案例派生答案必须进入 `Evaluation Quarantine`，不得进入普通 Foundation snapshot 或普通检索候选。
- Snapshot 发布后不可原地修改；修正必须产生新 `snapshot_id`。
- S1.1–S1.7 Gate 严格顺序执行，前置 Gate 未通过即停止。

实现期路径合同：

```bash
: "${SUBING_COURSE_ROOT:?existing read-only course asset root required}"
: "${SUBING_FOUNDATION_CODE_ROOT:?independent code repository root required}"
: "${SUBING_FOUNDATION_DATA_ROOT:?private working/snapshot data root required}"
```

三者 resolved path 必须互不相同；code/data root 必须位于 course root 与 Guiyi repo 之外；discovery 使用 `lstat()` 拒绝 symlink traversal。

独立 Foundation repo 使用本地 `develop` 为集成分支；每个实现任务创建 task branch/worktree，通过测试和 Review 后集成独立 repo 的 `develop` 并清理。Stage 1 不触及归一 `main`、tag、release 或 Runtime。

---

# S1.1 Five-course Source Calibration

**Pilot courses:** `002 / 003 / 004 / 012 / 016`

**Gate:** `READY_FOR_SEMANTIC_EXTRACTION` 或 `SOURCE_CALIBRATION_BLOCKED`

## Task 1 — Bootstrap independent repo and safety rails

**Create:**

```text
pyproject.toml
uv.lock
README.md
.gitignore
src/subing_foundation/{__init__.py,config.py,safety.py,cli.py}
tests/test_config_safety.py
```

`pyproject.toml` 固定 Python `>=3.13,<3.14`，依赖 `pydantic>=2.11,<3`、`typer>=0.16,<1`、`orjson>=3.11,<4`、`python-docx>=1.2,<2`、`python-pptx>=1.0,<2`、`PyMuPDF>=1.26,<2`；dev 依赖 pytest/Ruff/Mypy。console script：

```toml
[project.scripts]
subing-foundation = "subing_foundation.cli:app"
```

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class FoundationPaths:
    course_root: Path
    code_root: Path
    data_root: Path

def resolve_foundation_paths(env: Mapping[str, str]) -> FoundationPaths: ...
def assert_safe_roots(paths: FoundationPaths) -> None: ...
def assert_source_path(paths: FoundationPaths, candidate: Path) -> Path: ...
def assert_data_output_path(paths: FoundationPaths, candidate: Path) -> Path: ...
```

**TDD:** missing env、Guiyi 内路径、course-root 子路径、symlink escape、source 越界、output 越界均先写失败测试，再实现 fail-closed path validator。

**Verify:**

```bash
uv lock
uv sync --locked
uv run pytest -q tests/test_config_safety.py
uv run ruff check src tests
uv run mypy src
```

## Task 2 — Calibration-only asset discovery and read-only readers

**Create:**

```text
src/subing_foundation/calibration/{__init__.py,models.py,discovery.py,readers.py}
tests/calibration/{test_discovery.py,test_readers.py}
```

`CalibrationSourceKind`：`video/subtitle_word/pptx/pdf_note/transcript_txt/extracted_note/learning_note/unknown`。

```python
class CalibrationAsset(BaseModel):
    course_no: int | None
    source_kind: CalibrationSourceKind
    relative_display_name: str
    byte_size: int
    sha256: str
    readable: bool
    discovery_notes: tuple[str, ...]
```

Rules：文件名同编号只建立匹配候选；隐藏/cache/非核心文件保持 unknown；hash 流式计算；`.txt/.md` UTF-8 fail-closed；`.docx` python-docx；legacy `.doc` 用参数数组调用 `/usr/bin/textutil -convert txt -stdout source_path`，禁止 `shell=True`；PPT 按 slide text；PDF 按 page text；不 OCR；video 在此仅 hash/metadata，不重转录、不全量抽帧。临时文件只能写 `data_root/working/tmp/`。

测试 source stat/hash 前后不变。

## Task 3 — Calibration sampling, findings and gate

**Create:**

```text
src/subing_foundation/calibration/{sample_plan.py,findings.py,report.py}
tests/calibration/{test_sample_plan.py,test_findings.py,test_report.py}
```

```python
PILOT_COURSE_NOS = (2, 3, 4, 12, 16)
```

Finding types：`DIRECTIONAL_TERM_ERROR / NEGATION_LOSS / CONDITION_MERGE / OMISSION / ADDED_INTERPRETATION / LOCATOR_FAILURE / PROVENANCE_UNKNOWN / LEXICAL_VARIATION / OTHER`；severity：`CRITICAL_SEMANTIC / IMPORTANT / MINOR`。

每课必须有 `OPENING/MIDDLE/ENDING` 样本，所有识别出的核心交易规则增加 `KEY_RULE`，来源冲突增加 `CONFLICT`。以下语义差异测试必须为 `CRITICAL_SEMANTIC`：多↔空、金叉↔死叉、上破↔下破、有↔无、必须↔可以、开仓↔止盈/止损、否定词增删、多个条件错误合并。

`SOURCE_CALIBRATION_BLOCKED` 条件：任一 mandatory sample 缺失、KEY_RULE 无可重现 locator、任何 CRITICAL_SEMANTIC 未解决、mandatory locator failure、primary/derived provenance 无法辨别。其余全部通过才输出 `READY_FOR_SEMANTIC_EXTRACTION`。

报告写入：

```text
$SUBING_FOUNDATION_DATA_ROOT/working/calibration/s1.1/
  source-calibration.json
  source-calibration.md
  content-differences.jsonl
  gate.json
```

## Task 4 — Execute five-course calibration

先比较 transcript / Word subtitle / PPT/PDF / extracted note / learning-note；只有 critical difference 才回到原始视频/primary slide 仲裁，不完整重看或重转录五节课程。

结果必须明确：

```text
transcript_proxy_status = ACCEPTED | REJECTED
subtitle_proxy_status   = ACCEPTED | AUXILIARY_ONLY | REJECTED
extracted_note_status   = HUMAN_DERIVED | AI_DERIVED | AUXILIARY_ONLY | UNKNOWN
learning_note_status    = HUMAN_DERIVED | AI_DERIVED | AUXILIARY_ONLY | UNKNOWN
```

Run:

```bash
uv run subing-foundation calibration plan --courses 2,3,4,12,16
uv run subing-foundation calibration gate
```

S1.1 结果不是 `READY_FOR_SEMANTIC_EXTRACTION` 时停止，不进入 S1.2。

---

# S1.2 Source Registry / Authority / Normalized Segment

**Precondition:** S1.1 passed

**Gate:** `SOURCE_REGISTRY_V1_VALID`

## Task 5 — Canonical contracts and deterministic JSONL codec

**Create:**

```text
src/subing_foundation/contracts/{__init__.py,enums.py,source.py,knowledge.py,case.py,review.py,snapshot.py}
src/subing_foundation/codec.py
tests/contracts/*
tests/test_codec.py
```

Model exact Spec records：`CourseUnit / SourceAsset / SourceSegment / EvidenceCard / GlossaryTerm / RuleCandidate / Ambiguity / Conflict / CaseCard / CaseOutcome / ReviewRecord / FoundationManifest`。

Enums：

```text
SourceCalibrationStatus = UNVERIFIED / CALIBRATING / CALIBRATED / BLOCKED
SourceRole = primary_audio_video / primary_slide / text_proxy / derived_human / derived_ai / unknown
ProvenanceStatus = CONFIRMED / PARTIAL / UNKNOWN / REJECTED
RuleKind = HARD / PARAMETERIZED / JUDGMENT
FormalizationStatus = EXACT_CANDIDATE / PARTIAL / BLOCKED_AMBIGUITY / JUDGMENT_ONLY
KnowledgeReviewStatus = EXTRACTED_CANDIDATE / REVIEW_REQUIRED / APPROVED / REJECTED / UNRESOLVED
VerificationLevel = PRIMARY_VERIFIED / TEXT_PROXY_VERIFIED / DERIVED_ONLY / UNVERIFIED
CaseType = LIVE_DECISION / EX_POST_TEACHING / ILLUSTRATIVE_EXAMPLE / UNKNOWN
CasePartition = KNOWLEDGE / HOLDOUT
CaseOutcomeVisibility = review_only / evaluation_quarantine
ReviewerType = owner / human_reviewer / model_assisted
```

`model_assisted` 不能批准记录；`teacher_explicit` approval 只能由 `PRIMARY_VERIFIED` 或经 S1.1 校准通过的 `TEXT_PROXY_VERIFIED` 支持；DERIVED_ONLY/UNVERIFIED 不得支撑该归因。高风险 Rule Candidate 不能只依赖 DERIVED_ONLY。

JSONL：UTF-8、one object/line、sorted keys、禁止 NaN/Infinity、stable serialization、temp + fsync + atomic replace。

## Task 6 — Stable IDs, authority policy, registry and segmenters

**Create:**

```text
src/subing_foundation/{identity.py,authority.py,registry.py,segmenters.py,validation.py}
tests/{test_identity.py,test_authority.py,test_registry.py,test_segmenters.py,test_validation.py}
```

IDs：

```text
course_id = subing_course_001 ... subing_course_020
source_asset_id = "sa_" + sha256(course_id|source_kind|relative_display_name|content_hash)[:24]
segment_id = "sg_" + sha256(source_asset_id|locator_kind|locator|content_hash)[:24]
```

Equal content hash 只标 duplicate relation，不合并两个 SourceAsset。

Authority 不做全局 score/ranking：teacher oral wording 由 primary audio/video 仲裁；slide/on-screen wording 由 primary slide/画面仲裁；accepted text proxy 只能成为 `TEXT_PROXY_VERIFIED` 代理，不能覆盖冲突 primary；derived/unknown 不覆盖 primary；primary-primary 冲突创建 Conflict。

Segment rules：transcript 保留 line ranges；超长单行只按句末标点确定性拆分；docx 保留 paragraph/table order；legacy doc 使用 converted line range；PPT slide locator；PDF page locator；derived notes 保留 derived provenance；video 不做 bulk text segment。Stage 1 Canonical 不增加 token overlap。

Registry validator 拒绝 duplicate ID、orphan/self derivation、越界 source path、symlink、无 locator segment、S1.1 已拒绝代理被标 authoritative、cache/non-core file 静默晋升。

Run:

```bash
uv run subing-foundation registry build
uv run subing-foundation registry validate
```

Expected: `SOURCE_REGISTRY_V1_VALID`。

---

# S1.3 Five-course Semantic Extraction Pilot

**Precondition:** `SOURCE_REGISTRY_V1_VALID`

**Gate:** `SEMANTIC_MODEL_PILOT_VALID`

## Task 7 — Provider-neutral extraction packets/importer

**Create:**

```text
src/subing_foundation/extraction/{__init__.py,packets.py,importer.py,policy.py}
tests/extraction/*
```

Stage 1 不实现任何模型 HTTP client。工具只生成 bounded local `ExtractionPacket`，内容级外发必须另获 Owner 授权；返回 JSON 再由 importer 校验。

Importer 规则：model-assisted candidate 初始只能是 `EXTRACTED_CANDIDATE`；不得自标 APPROVED；不得引用未知 segment、伪造 locator/timestamp、越级 verification、用 derived-only source 标 teacher_explicit、把 PARAMETERIZED/JUDGMENT 偷升 HARD、把 Outcome 混进普通 semantic candidate。

语义 regression fixtures 用短句保护：零轴“附近”保持 Ambiguity；“三根K线不回区间”在计数/返回定义不明确时保持 Ambiguity；“背离用于减仓而非开仓”不得改用途；“五个满足三个”必须保留 source scope/timeframe，不能变全局规则。

## Task 8 — Execute 5-course semantic pilot

Only `002/003/004/012/016`。抽取 `EvidenceCard / GlossaryTerm / RuleCandidate / Ambiguity / Conflict`；Case 延后 S1.6。

每个 Rule Candidate 必须有 purpose、side、market/timeframe context、preconditions、conditions、invalidations、source evidence、kind、formalization status、ambiguity/conflict refs。来源不支持的字段保持 unknown/unresolved，不推断交易惯例。

Run:

```bash
uv run subing-foundation extraction packet --courses 2,3,4,12,16
uv run subing-foundation extraction validate-pilot
```

Expected: `SEMANTIC_MODEL_PILOT_VALID`。

---

# S1.4 Pilot Review / Schema Freeze

**Precondition:** S1.3 passed

**Gate:** `FOUNDATION_SCHEMA_V1_FROZEN`

## Task 9 — Append-only review workflow and schema generation

**Create:**

```text
src/subing_foundation/review/{__init__.py,actions.py,projection.py,export.py}
src/subing_foundation/schema.py
schemas/foundation-v1/*.schema.json
tests/review/*
tests/test_schema_freeze.py
```

Review action：`APPROVE / REJECT / MARK_UNRESOLVED / REOPEN`。`model_assisted` 不能 APPROVE；owner/human_reviewer approval 还必须通过 provenance cross-record validation。ReviewRecord append-only；REJECTED 保留 lineage 但不进入 active projection；UNRESOLVED 可作为明确未决事实发布。

Target：

```python
FOUNDATION_SCHEMA_VERSION = "1.0.0"
FOUNDATION_SCHEMA_FROZEN = False
```

测试从 Pydantic 重新生成 schema 并 byte-compare committed `schemas/foundation-v1/`。`validate-freeze` 在 `FOUNDATION_SCHEMA_FROZEN=False` 时必须拒绝 Gate。

## Task 10 — Human pilot review and freeze v1

Review：source 是否真实、statement 是否改义、入场/加仓/持仓/止盈/止损用途、周期/市场环境、禁止条件、冲突、模糊参数、JUDGMENT、未来信息。

若 schema 无法无损表达 Pilot，在 freeze 前修改 v1 draft 并重导 Pilot。Review 通过后设 `FOUNDATION_SCHEMA_FROZEN=True`，重新生成/byte-compare schema。

Run:

```bash
uv run subing-foundation schema validate-freeze
```

Expected: `FOUNDATION_SCHEMA_V1_FROZEN`。

---

# S1.5 Full 001–020 Expansion

**Precondition:** S1.4 passed

**Gate:** `COURSE_001_020_SEMANTIC_COVERAGE_COMPLETE`

## Task 11 — Incremental change detection

**Create:**

```text
src/subing_foundation/build/{__init__.py,change_set.py,full_course.py}
tests/build/*
```

`SourceChange = UNCHANGED / ADDED / REMOVED / CONTENT_CHANGED / PROVENANCE_CHANGED`。

Invariants：unchanged hash 不重复提取；content change 只使 working dependency 失效，不改旧 snapshot；removed source 仍保留在旧 snapshot lineage；provenance change 即使 bytes 不变也必须重新 Review。

## Task 12 — Execute full-course expansion

必须包含 `subing_course_001..020`。007/020 缺 PPT 记录为 coverage fact，不自动补齐。只有 S1.1 `transcript_proxy_status=ACCEPTED` 才允许 transcript 作为 20 课 batch text proxy；否则 S1.5 阻塞，不能偷偷换 derived source。

高风险方向/入出场/资金/止损规则、关键冲突、方向性错词回到 primary source。无法确认的内容保持 UNRESOLVED；“COMPLETE”表示 20 课进入 schema 管理，不表示所有 Rule 被解决。

Run:

```bash
uv run subing-foundation build validate-full-coverage
```

Expected: `COURSE_001_020_SEMANTIC_COVERAGE_COMPLETE`。

---

# S1.6 Case Library / Evaluation Isolation

**Precondition:** S1.5 passed

**Gate:** `CASE_LIBRARY_V1_CAUSALITY_VERIFIED`

## Task 13 — Case/Outcome separation and quarantine policy

**Create:**

```text
src/subing_foundation/cases/{__init__.py,identity.py,builder.py,quarantine.py}
tests/cases/*
```

Data layout：

```text
working/cases/case_cards.jsonl
working/cases/case_outcomes.review-only.jsonl
quarantine/cases/case_outcomes.holdout.jsonl
quarantine/cases/hidden_labels.jsonl
```

Validator 必须拒绝：Outcome 写入 decision_snapshot、holdout outcome 写入 normal path、同案例派生物跨 KNOWLEDGE/HOLDOUT、ex-post commentary 标 LIVE_DECISION、normal export 含 quarantine ID/hidden label。

## Task 14 — Build/review v1 case library

CaseType：`LIVE_DECISION / EX_POST_TEACHING / ILLUSTRATIVE_EXAMPLE / UNKNOWN`。LIVE_DECISION 必须有 decision-time evidence；“讲完以后看起来像当时会做”不能作为证明。

同案例 video/transcript/slide/PDF/note/outcome 全部继承同一 `case_id` 和 partition。Human review 验证 decision snapshot 只含当时可知信息、outcome 独立、teacher decision 时点有证据、normal export 无泄漏。

Run:

```bash
uv run subing-foundation cases validate-causality
```

Expected: `CASE_LIBRARY_V1_CAUSALITY_VERIFIED`。

---

# S1.7 Immutable Snapshot Publish

**Precondition:** S1.1–S1.6 all passed

**Gate:** `SUBING_KNOWLEDGE_FOUNDATION_V1_READY`

## Task 15 — Snapshot validator and atomic publisher

**Create:**

```text
src/subing_foundation/snapshot/{__init__.py,materialize.py,validate.py,publish.py}
tests/snapshot/*
```

Snapshot includes：APPROVED、显式 UNRESOLVED research facts、non-holdout `review_only` CaseOutcome、解释当前状态所需 ReviewRecord。Exclude：EXTRACTED_CANDIDATE、REVIEW_REQUIRED、REJECTED active projection、所有 evaluation_quarantine、Derived indexes/caches、raw media/content copies。

Manifest 至少：

```text
foundation_id = subing_knowledge_foundation
schema_version = 1.0.0
snapshot_id
created_at
included_courses
source_registry_hash
canonical_record_counts
canonical_file_hashes
review_summary
unresolved_ambiguity_count
unresolved_conflict_count
quarantine_policy_version = subing_eval_quarantine_v1
```

Hash 规则避免自循环：`canonical_file_hashes` 只记录 canonical JSONL，不包含 `manifest.json`；`source_registry_hash = sha256(course_units bytes + NUL + source_assets bytes + NUL + source_segments bytes)`；`canonical_aggregate` 对按 filename 排序后的 `filename + NUL + file_sha256 + NEWLINE` 求 SHA-256。manifest 写完后重新解析并逐文件 re-hash。

Snapshot ID：`subing-kf-v1-` + UTC `YYYYMMDDTHHMMSSZ` + `-` + `canonical_aggregate[:12]`。

Validator 拒绝 schema/ID/ref/hash/count 错误、orphan evidence/review、approved high-risk derived-only rule、被隐藏的 ambiguity、无 ReviewRecord 的 primary conflict resolution、quarantine ID、case outcome leakage、已有 target、manifest metadata 中的绝对私密路径/credential-like content。

Publish：写 `snapshots/.staging-$SNAPSHOT_ID` → full validate → fsync → 同文件系统 atomic rename 到 `snapshots/$SNAPSHOT_ID` → read-only chmod where supported；绝不覆盖已有 snapshot；失败不留下 final partial snapshot。

## Task 16 — End-to-end verification and v1 publish

Run independent repo full suite：

```bash
uv run pytest -q
uv run ruff check src tests
uv run mypy src
```

Gate validators in order：

```bash
uv run subing-foundation calibration gate
uv run subing-foundation registry validate
uv run subing-foundation extraction validate-pilot
uv run subing-foundation schema validate-freeze
uv run subing-foundation build validate-full-coverage
uv run subing-foundation cases validate-causality
```

Expected sequence：

```text
READY_FOR_SEMANTIC_EXTRACTION
SOURCE_REGISTRY_V1_VALID
SEMANTIC_MODEL_PILOT_VALID
FOUNDATION_SCHEMA_V1_FROZEN
COURSE_001_020_SEMANTIC_COVERAGE_COMPLETE
CASE_LIBRARY_V1_CAUSALITY_VERIFIED
```

Then：

```bash
uv run subing-foundation snapshot prepare
uv run subing-foundation snapshot validate-staging
```

Final human review checks provenance、purpose separation、ambiguity/conflict visibility、case causality、quarantine isolation、private boundary、record counts/hashes、zero Guiyi runtime dependency。通过后才执行：

```bash
uv run subing-foundation snapshot publish
```

Expected: `SUBING_KNOWLEDGE_FOUNDATION_V1_READY`。

该状态只表示 Foundation 可被后续独立 consumer 固定读取，不授权 Stage 2、行情、Guiyi Adapter、正式策略、通知、release、Runtime 或交易。

---

## 2. Review / Integration Policy

独立 Foundation repo 每个 code task：

```text
develop → task branch/worktree → failing test → minimal implementation
→ targeted/full affected tests → Ruff/Mypy → self-review → independent review
→ integrate develop → cleanup
```

每个 S1.x Gate 双轴 Review：

**Standards/Safety:** course assets read-only；Guiyi 零代码影响；无未授权 network/model 外发；无 credential/private-path leak；无 source authority 偷升；fail-closed。

**Spec/Semantics:** contracts 对齐 Spec；locator/provenance 可重现；入场/加仓/持仓/止盈/止损不混写；HARD/PARAMETERIZED/JUDGMENT 保留；ambiguity/conflict 显式；case/outcome/quarantine 因果隔离；snapshot identity immutable/reproducible。

Critical/Important finding 阻塞集成。Stage 1 Gate 不更新 Guiyi `STATUS.md`，因为它不属于当前 release/Runtime readiness track。

---

## 3. Final Acceptance Matrix

| Area | Acceptance |
|---|---|
| Source | 001–020 CourseUnit 均存在；known asset 全部 stable-id 或 explicit excluded/unknown |
| Calibration | 5 课完成校准；transcript proxy 有 evidence-backed ACCEPTED/REJECTED |
| Provenance | approved evidence 有 reproducible locator；human/AI/teacher role 可机器区分 |
| Semantics | HARD/PARAMETERIZED/JUDGMENT 保留；未解决阈值进入 Ambiguity |
| Conflict | primary conflict 保留，除非 human ReviewRecord 显式决议 |
| Review | model-assisted 不能自批；ReviewRecord append-only |
| Case | decision snapshot/outcome 分离；same-case derivatives 同 partition |
| Holdout | quarantine IDs/answers/outcomes 不出现在 normal snapshot |
| Snapshot | schema/hash/ref/count/manifest 全部通过；snapshot 不可覆盖 |
| Isolation | Guiyi source/runtime/product/DB/Redis/Alert/RQData 零变化；raw course content 不入 Git |
| Final Gate | 只有 S1.1–S1.6 + final review 后可声明 `SUBING_KNOWLEDGE_FOUNDATION_V1_READY` |

---

## 4. Plan Review Result

2026-09-06 完成双轴 Review：

```text
Standards / Safety Review = PASSED
Spec / Plan Review        = PASSED
Critical                  = 0
Important                 = 0
Minor                     = 0
```

Review 中发现并在提交前修正：

1. 增加 capability-based `authority.py`，避免粗暴全局 source 排名。
2. 修正 `teacher_explicit` approval：允许 PRIMARY_VERIFIED 或已校准 TEXT_PROXY_VERIFIED，继续拒绝 DERIVED_ONLY/UNVERIFIED。
3. 消除 manifest 自哈希循环：manifest 不进入 `canonical_file_hashes`，另设 canonical aggregate。
4. 将 schema generation 与 S1.4 human Gate 后的正式 freeze 分离。
5. 补齐 Source Calibration、provenance、case partition 等保守 enum；unknown/unresolved 默认 fail-closed。
6. 增加独立 CLI entrypoint、`uv.lock` 和 locked environment 要求。
7. 明确 Owner 本轮只额外授权本 Plan 进入 Guiyi `develop`，没有扩大 Stage 1 实现边界。

Review 结论：本 Plan 覆盖 Stage 1 Spec 的 S1.1–S1.7、Canonical/Derived、provenance、authority、review state、causality/quarantine、immutable snapshot、隐私隔离与归一零影响边界；允许进入后续独立实现，但本次不授权实际开始 Stage 1、外部模型内容发送、Stage 2、行情接入、Guiyi Adapter、正式策略、真实通知、Runtime 或任何交易能力。
