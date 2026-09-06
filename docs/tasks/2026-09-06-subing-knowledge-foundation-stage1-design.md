# SuBing Knowledge Foundation · Stage 1 Spec

日期：2026-09-06  
状态：`SPEC_INTERNAL_REVIEW_PASSED / IMPLEMENTATION_NOT_STARTED`  
规划基线：`develop@5844958b4075b393000522e2d3597c29d065077d`  
任务来源：2026-09-06 已完成的苏冰课程资料只读盘点，以及 Owner 已确认的“共用知识基础数据独立建设、其他应用单独开发、当前归一量化不受影响”原则。

> 本文只定义 Stage 1：`SuBing Knowledge Foundation`。它是后续课程知识助手、行情研究助手、案例/评测系统与可选专家化模型共同消费的私有研究数据底座，不是归一量化当前稳定产品面的扩展。Stage 1 不修改现有 SuBing Alert、Market、Newow、HTDY、Canonical、Runtime、AlertEvent 或任何交易合同。

---

## 1. Stage 1 最终目标

Stage 1 的唯一目标是把现有 20 节苏冰课程资产加工成一套：

```text
可追溯
可校准
可审查
可版本化
模型无关
应用无关
可被后续研究模块只读消费
```

的共享知识基础数据。

Stage 1 完成后，系统应能够可靠回答以下“数据层”问题，而不依赖某个 LLM：

1. 某个知识点来自哪一节课程、哪个原始资产、哪个位置；
2. 某条表述是老师明确表达、原始课件内容、文字代理、人工派生，还是 AI 派生；
3. 某个交易方法是明确规则、参数仍未解决的规则，还是只能保留为经验判断；
4. 不同课程或不同材料之间是否存在冲突、语义变化、遗漏或新增解释；
5. 某个课程案例在“当时可见信息”与“事后结果”之间如何严格分离；
6. 当前发布的知识快照具体包含哪些课程、哪些已审核记录、哪些未决项，以及它的不可变身份。

Stage 1 **不负责**回答“当前某品种能不能买”，也不负责把课程规则实现成交易策略。

---

## 2. 已知资料基线

2026-09-06 只读盘点确认资料根目录共有 149 个文件，无符号链接，且未修改原始资料或归一仓库。当前已确认的资产覆盖为：

| 资产 | 数量 / 覆盖 | 当前已知状态 |
|---|---:|---|
| 课程视频 | 20 | 001–020 完整，约 3.55 GB，合计约 20:53:35，均含音频与视频流 |
| 字幕 | 20 | 10×`.doc` + 10×`.docx`；是否存在完整时间戳尚未确认 |
| PDF 笔记 | 22 | 001–020 均有；001 有重复；另有 1 份非核心编号资料 |
| 课件 | 18×`.pptx` | 缺 007、020；另有 6 个隐藏下载/缓存型文件，来源性质未核验 |
| `extracted/transcript` | 20×`.txt` | 001–020 均有；准确性与 provenance 尚未完成内容级核验 |
| `extracted/note` | 20×`.txt` | 001–020 均有；属于摘录、人工总结或 AI 派生尚未冻结 |
| `learning-notes` | 20×`.md` + README | 001–020 均有；来源性质和是否可作为可信派生知识尚未冻结 |

跨目录同编号、相近标题的文件当前只属于**匹配候选**。文件名一致不能替代内容级校准。

Stage 1 第一批校准样本固定为：

```text
002 进场条件
003 开平仓原则
004 止损原则
012 不同周期的交易策略
016 震荡行情中的交易机会
```

选择这些课程的目的，是同时覆盖入场、出场、止损、多周期与震荡/趋势等核心语义，不代表其他课程优先级较低。

---

## 3. 与归一量化的隔离边界

### 3.1 当前归一产品面保持零影响

Stage 1 不得修改或复用以下 active identity / contract：

```text
subing_ths_alert_15m_v1
subing_ths_15m_v3
HTDY Rule / Event
Market Web
Newow
MarketDataService
Canonical Parquet
Catalog / MainContractMap
production PostgreSQL / Redis
Runtime / launchd
PushPlus / Alert transport
```

现有 SuBing Alert 仍然只代表当前仓库已经冻结的 15m observation 合同。课程知识中出现的零轴、量能、持仓量、多周期共振、震荡过滤或其他方法，不得通过 Stage 1 反向修改现有 Alert 公式或解释。

### 3.2 Stage 1 运行位置

Stage 1 的原始课程资产、标准化文本、知识卡、案例卡、Review 记录和发布快照必须位于 **`guiyi-quant-workstation` 仓库之外的私有本地研究根目录**。

Stage 1 后续实现代码也使用独立本地 workspace / 独立 Git repository 管理，不作为 `services/quant-api`、`apps/quant-web` 或 `packages/quant-core` 的子模块或依赖。该独立工程可以读取 Owner 明确授权的课程根目录并生成 Foundation snapshot，但不得反向 import 归一运行代码或写入归一 Runtime。

当前归一仓库在 Stage 1 只允许保存：

```text
本设计文档
```

Stage 1 的 schema、processing tooling、validation tests 与私有数据都进入独立 Foundation workspace/repository；在未来 Guiyi Adapter 获得单独设计和批准前，不向当前归一源码树增加 Stage 1 运行依赖。

不得提交：

```text
完整课程视频
完整字幕
完整 transcript
PDF/PPT 课程正文
课程截图
长段课程笔记
发布后的私有 Knowledge Foundation 数据快照
```

### 3.3 后续消费方式

后续课程助手、行情研究助手、案例评测和可选专家模型必须以 **发布快照的只读合同** 消费 Foundation，不直接扫描原始课程目录。

归一量化如未来需要读取苏冰研究能力，只能在新的独立设计和人工 Gate 后增加 typed read-only Adapter；Stage 1 本身不创建该 Adapter。

---

## 4. 非目标

Stage 1 明确不做：

```text
RAG / 向量数据库
知识图谱
课程问答 UI
行情读取或实时行情分析
MarketDataService 接入
策略 kernel / Rule Evaluator
参数优化或阈值搜索
回测 / OOS / Walk-forward / Shadow
Alert / PushPlus / Runtime
自动下单、账户、委托、持仓
模型微调、SFT、行为克隆
声音克隆、数字人形象
将模糊课程表述自动参数化
将课程之间的冲突自动统一
```

Stage 1 的输出是**知识事实与 provenance**，不是正式交易规则或正式策略结论。

---

## 5. 总体架构

```text
Private Course Assets
(video / subtitle / ppt / pdf / transcript / note / learning-note)
        │
        ▼
Source Registry + Content Hash
        │
        ▼
Source Calibration
        │
        ▼
Normalized Source Segments
        │
        ▼
Semantic Extraction
        │
        ├── Evidence Card
        ├── Glossary
        ├── Rule Candidate
        ├── Ambiguity
        ├── Conflict
        └── Case Candidate
        │
        ▼
Human / Explicit Review State
        │
        ▼
Immutable Foundation Snapshot
        │
        ├── future Course QA
        ├── future Market Research Engine
        ├── future Case/Evaluation
        └── optional Expert Model
```

核心原则：

> **原始资料是证据，Foundation 是经过 provenance 和 Review 管理的结构化知识；模型只是提取与辅助解释工具，不能成为知识事实源。**

---

## 6. Canonical 与 Derived 的边界

### 6.1 Foundation Canonical

Stage 1 Canonical 使用**文本友好、模型无关、可校验的版本化文件合同**。推荐 canonical record 使用 UTF-8 JSONL，snapshot 由 manifest 冻结。

Canonical 至少包含：

```text
manifest.json
course_units.jsonl
source_assets.jsonl
source_segments.jsonl
evidence_cards.jsonl
glossary_terms.jsonl
rule_candidates.jsonl
ambiguities.jsonl
conflicts.jsonl
case_cards.jsonl
case_outcomes.jsonl
review_records.jsonl
```

选择 JSONL 而不是把 SQLite、向量库或某个模型索引作为 canonical，原因是：

- 数据量可控；
- 每条记录有稳定 ID 与 provenance；
- 易于 schema 校验、hash、导入导出和独立 Review；
- 不绑定未来检索技术；
- 任何 SQLite / FTS / embedding / vector index 都可以从发布快照重建。

### 6.2 Derived

下列内容只能是可删除、可重建的 Derived：

```text
SQLite / DuckDB query cache
FTS index
embedding
vector index
Graph projection
LLM summary cache
UI search index
```

Derived 不得反向修改 Canonical，也不得成为冲突仲裁来源。

---

## 7. 稳定身份与字段合同

### 7.1 Course Unit

每节课程使用稳定身份：

```text
course_id = subing_course_001 ... subing_course_020
```

最小字段：

```text
course_id
title
sequence_no
asset_refs[]
coverage_status
calibration_status
notes
```

### 7.2 Source Asset

每个文件必须拥有独立 `source_asset_id`，不能只靠路径作为身份。

最小字段：

```text
source_asset_id
course_id | null
source_kind
relative_display_name
content_hash
byte_size
source_role
provenance_status
created_from_asset_id | null
content_scope
```

`source_kind` 至少区分：

```text
video
subtitle_word
pptx
pdf_note
transcript_txt
extracted_note
learning_note
unknown
```

`source_role` 至少区分：

```text
primary_audio_video
primary_slide
text_proxy
derived_human
derived_ai
unknown
```

如果 `note` 或 `learning-note` 的来源性质不能证明，必须保持 `unknown`，不能因文本质量较高就提升 authority。

### 7.3 Source Segment

知识抽取不得直接只引用整节课程。所有可被下游引用的内容必须落到 segment。

最小字段：

```text
segment_id
source_asset_id
course_id
segment_order
text
locator
locator_kind
primary_verification_status
content_hash
```

`locator_kind` 允许：

```text
video_time_range
slide_page
pdf_page
word_paragraph
transcript_line_range
text_offset
unresolved
```

没有视频时间戳时允许先使用可重现的文字 locator，但不得伪造 timestamp。

### 7.4 Evidence Card

Evidence Card 表达“资料明确支持了什么”，不是模型认为应该是什么。

最小字段：

```text
evidence_id
topic
statement
course_id
source_segment_refs[]
evidence_scope
speaker_attribution
review_status
verification_level
confidence_note
```

`speaker_attribution` 必须明确区分：

```text
teacher_explicit
slide_explicit
human_derived
ai_derived
unknown
```

只有 `teacher_explicit` / `slide_explicit` 且 provenance 可证明的内容，才能被描述为课程明确依据。

### 7.5 Glossary Term

Glossary 只保存术语在课程体系中的用法和证据，不用通用金融知识偷偷补定义。

最小字段：

```text
term_id
term
course_definition_refs[]
usage_refs[]
resolved_definition | null
ambiguity_refs[]
review_status
```

例如“时空平衡”“有效突破”“附近”“明显放量”等，如果课程没有足够明确的统一定义，应保持 unresolved。

### 7.6 Rule Candidate

Stage 1 只产出 **Rule Candidate**，不产出正式策略 Rule。

最小字段：

```text
rule_candidate_id
name
purpose
side
market_context
timeframe_context
preconditions[]
conditions[]
invalidations[]
source_evidence_refs[]
rule_kind
formalization_status
ambiguity_refs[]
conflict_refs[]
review_status
```

`rule_kind` 固定为：

```text
HARD
PARAMETERIZED
JUDGMENT
```

含义：

- `HARD`：课程表达足够明确，理论上可以直接程序判断；
- `PARAMETERIZED`：语义明确但阈值、窗口、计数或边界仍需冻结；
- `JUDGMENT`：本质依赖图形、经验、上下文或盘感，不允许伪装为硬阈值。

`formalization_status` 固定为：

```text
EXACT_CANDIDATE
PARTIAL
BLOCKED_AMBIGUITY
JUDGMENT_ONLY
```

Stage 1 不得把 `PARAMETERIZED` 或 `JUDGMENT` 自动升级为 `HARD`。

### 7.7 Ambiguity

所有会影响未来机器判断的模糊项必须显式建模。

示例：

```text
“MACD 在零轴附近”中的“附近”
“明显放量”如何比较
“远离均线”的距离
“三根 K 线不回到区间”是否包含突破当根
“回到区间”按盘中触达还是 completed close
```

最小字段：

```text
ambiguity_id
term_or_rule
problem_statement
source_refs[]
known_interpretations[]
status
approved_resolution | null
```

Stage 1 默认 `approved_resolution = null`。只有后续专门规则设计和人工批准才能冻结参数解释。

### 7.8 Conflict

真实冲突不得在抽取阶段被“综合”。

最小字段：

```text
conflict_id
topic
source_refs[]
conflict_type
summary
context_difference
resolution_status
approved_resolution | null
```

`conflict_type` 至少区分：

```text
numeric_difference
scope_difference
semantic_difference
temporal_evolution
source_derivation_difference
unknown
```

如果两个 primary source 本身存在不同表述，Foundation 必须保留两者，不允许仅按 authority 排序删除其中一个。

### 7.9 Case Card

Case Card 用于未来案例检索与评测，但必须从 Stage 1 起保护 causality。

最小字段：

```text
case_id
course_id
case_type
instrument_reference | null
timeframe_reference | null
decision_snapshot
teacher_decision | null
rationale_evidence_refs[]
invalidation_evidence_refs[]
outcome_ref | null
partition
review_status
```

必须严格分离：

```text
decision_snapshot = 当时可以知道的信息
case_outcome      = 后来发生的结果 / 事后复盘
```

`case_outcomes.jsonl` 与 `case_cards.jsonl` 是两个独立合同。普通 Knowledge Retriever 默认只允许消费 Case Card 的 decision-time 字段；Outcome 需要显式的复盘/评测权限才能读取。Snapshot 内的 `case_outcomes.jsonl` 只允许包含非 holdout 的 `review_only` Outcome；Holdout case 的 Outcome 必须放入 Evaluation Quarantine，不能跟随 Foundation snapshot 进入普通 derived index。

### 7.10 Case Outcome

Case Outcome 只表达 decision 之后才知道的结果，用于未来复盘和评测，不属于正常知识检索输入。

最小字段：

```text
outcome_id
case_id
outcome_summary
outcome_source_refs[]
observed_through | null
outcome_kind
visibility
review_status
```

`visibility` 固定区分：

```text
review_only
evaluation_quarantine
```

Foundation 普通检索路径不得自动读取 Case Outcome。

### 7.11 Review Record

所有 authority 升级、Rule Candidate 审核、冲突决议和 Foundation 发布都必须有 Review Record。

最小字段：

```text
review_id
record_type
record_id
review_action
reviewer_type
reviewed_at
source_refs[]
notes
```

`reviewer_type` 至少区分：

```text
owner
human_reviewer
model_assisted
```

`model_assisted` 本身不能把记录升级为“人工确认”。

---

## 8. Source Authority 与校准原则

### 8.1 不采用一个粗暴的全局单序列

Stage 1 不冻结“video > ppt > transcript > note”这样的无条件总排序，因为不同资产承载的信息不同：

- 老师口头表述以原始音视频为主要仲裁源；
- 屏幕或原始课件上明确出现、但口头未完整复述的内容，应由原始画面/课件承担证据；
- transcript / Word 字幕只是文字代理，必须经过抽样校准后才能承担批量检索；
- PDF 笔记、extracted note、learning-notes 必须先证明 provenance，再决定是否属于 human-derived、AI-derived 或 unknown。

### 8.2 冲突处理

处理顺序：

```text
判断是否是同一个 statement
→ 判断 source role
→ 判断是否属于转录错误 / 摘要遗漏 / 派生解释
→ 必要时回到原始视频或原始课件
→ 记录 calibration finding
→ 若 primary source 仍真实冲突，则创建 Conflict
```

不得通过“挑一个更合理的版本”消除真实冲突。

### 8.3 文字代理准入

`extracted/transcript` 只有在 5 节样本校准达到可接受质量后，才可成为后续 20 节批量语义抽取的主要文字代理。

这里的“可接受”不由主观整体印象判断，而由以下问题共同决定：

```text
是否存在方向性错词（多/空、金叉/死叉、上破/下破）
是否漏掉关键否定词
是否错误合并不同条件
是否大面积缺失课程段落
是否能稳定回到原始课程位置进行仲裁
```

只要发现会系统性改变交易语义的错误模式，就不得直接全量扩展。

---

## 9. Review 状态机

### 9.1 Source Calibration

```text
UNVERIFIED
→ CALIBRATING
→ CALIBRATED
   or BLOCKED
```

### 9.2 Knowledge Record

```text
EXTRACTED_CANDIDATE
→ REVIEW_REQUIRED
→ APPROVED
   or REJECTED
   or UNRESOLVED
```

下游语义：

- `APPROVED`：可进入发布 Foundation snapshot；
- `UNRESOLVED`：可以作为未决研究事实发布，但不能被未来 Rule Engine 当成通过条件；
- `REJECTED`：保留 Review lineage，但不进入 active knowledge set；
- `EXTRACTED_CANDIDATE / REVIEW_REQUIRED`：不得被下游描述为“已确认的苏冰规则”。

### 9.3 Verification Level

Evidence 至少区分：

```text
PRIMARY_VERIFIED
TEXT_PROXY_VERIFIED
DERIVED_ONLY
UNVERIFIED
```

高风险交易条件如果仅为 `DERIVED_ONLY`，不得进入 `APPROVED` Rule Candidate。

---

## 10. Evaluation Holdout 与信息泄漏隔离

Stage 1 必须提前建立 Evaluation 隔离边界，避免 Stage 3/4 再补救未来函数。

### 10.1 两个逻辑空间

```text
Foundation Knowledge
Evaluation Quarantine
```

`Evaluation Quarantine` 中的以下内容不得进入普通检索索引：

```text
隐藏答案
事后走势结果
老师在事后直接给出的最终判断
由结果反推的标签
同一 holdout case 的派生总结
```

### 10.2 同案例派生物必须同分区

同一案例的视频片段、字幕、笔记、截图、AI 总结和 outcome 必须继承同一个 `case_id` / `partition`。

不得出现：

```text
测试截图在 holdout
但同一案例的 learning-note 在正常知识库
```

这种形式等同于答案泄漏。

### 10.3 Stage 1 不评价收益

Stage 1 只建立可用于未来盲测的素材与 lineage，不计算胜率、收益率，也不宣称“复现苏冰本人”。

---

## 11. 私有数据目录设计

Stage 1 不重组或改名现有原始课程目录。Foundation 使用独立输出根目录，推荐：

```text
<PRIVATE_RESEARCH_ROOT>/subing-knowledge-foundation/
├── working/
│   ├── registry/
│   ├── normalized/
│   ├── extracted/
│   └── reviews/
├── quarantine/
│   └── cases/
├── snapshots/
│   └── <snapshot_id>/
│       ├── manifest.json
│       ├── course_units.jsonl
│       ├── source_assets.jsonl
│       ├── source_segments.jsonl
│       ├── evidence_cards.jsonl
│       ├── glossary_terms.jsonl
│       ├── rule_candidates.jsonl
│       ├── ambiguities.jsonl
│       ├── conflicts.jsonl
│       ├── case_cards.jsonl
│       ├── case_outcomes.jsonl
│       └── review_records.jsonl
└── derived/
    └── <snapshot_id>/
```

原始资产继续留在现有资料根目录。`source_assets.jsonl` 使用受控 display path / relative reference 与 hash 建立关联，不要求复制 3.55 GB 视频。

路径不得记录用户凭据、token 或与研究无关的个人文件信息。

---

## 12. Snapshot 与版本规则

### 12.1 Snapshot 是唯一可被下游固定引用的知识身份

Working 数据允许修正，Snapshot 一旦发布即不可原地修改。

每个 Snapshot manifest 至少记录：

```text
foundation_id = subing_knowledge_foundation
schema_version
snapshot_id
created_at
included_courses[]
source_registry_hash
canonical_record_counts
canonical_file_hashes
review_summary
unresolved_ambiguity_count
unresolved_conflict_count
quarantine_policy_version
```

### 12.2 修改规则

如果发布后发现错误：

```text
不得改写旧 snapshot
→ 修正 working 数据
→ 追加 Review Record
→ 发布新 snapshot_id
```

未来课程助手、行情研究助手和评测必须把使用的 `snapshot_id` 固定到自己的分析记录中。

---

## 13. Stage 1 分阶段开发

## S1.1 五节课程 Source Calibration

目标：证明现有文字代理与派生材料是否可以安全复用。

输入：

```text
002 / 003 / 004 / 012 / 016
video + subtitle + ppt/pdf + transcript + note + learning-note
```

执行原则：

- 文本优先；
- 开头、中间、结尾抽样；
- 关键交易规则段必须核验；
- 来源冲突时才回到视频/原始课件仲裁；
- 不完整重看或重新转录 5 节视频；
- 不建立知识卡，不进入行情规则实现。

产物：

```text
source calibration findings
source role / provenance classification
transcript quality assessment
learning-note usability assessment
content differences
```

Gate：

```text
READY_FOR_SEMANTIC_EXTRACTION
or
SOURCE_CALIBRATION_BLOCKED
```

---

## S1.2 Source Registry、Authority 与 Normalized Segment

前置：S1.1 = `READY_FOR_SEMANTIC_EXTRACTION`。

目标：冻结所有后续抽取共同使用的 Source Registry 与 locator 规则。

内容：

1. 为 20 节课程和现有资产生成稳定 ID + content hash；
2. 排除或隔离未确认归属的隐藏缓存文件与非核心 PDF，不偷偷归类；
3. 冻结 source role / provenance status；
4. 建立 normalized segment；
5. 冻结 locator 生成方式；
6. 建立重复文件检测和衍生关系。

Gate：

```text
SOURCE_REGISTRY_V1_VALID
```

---

## S1.3 五节课程 Semantic Extraction Pilot

前置：S1.2 通过。

目标：用 5 节课验证数据模型是否足以表达课程方法，而不是追求数量。

抽取：

```text
Evidence Card
Glossary
Rule Candidate
Ambiguity
Conflict
Case Candidate
```

禁止：

- 自动给 `PARAMETERIZED` 规则补阈值；
- 将止盈条件误标成开仓条件；
- 将经验性描述强行转为 Hard Rule；
- 用一般交易知识填补课程未说内容；
- 把 AI 整理语言归因给老师。

Gate：

```text
SEMANTIC_MODEL_PILOT_VALID
```

---

## S1.4 Pilot Review 与 Schema Freeze

目标：人工审查第一批高价值知识，修正 schema，而不是修正课程本身。

重点 Review：

```text
来源是否真实
statement 是否改变原意
用途是否正确（入场 / 加仓 / 持仓 / 止盈 / 止损）
时间周期与市场环境是否丢失
禁止条件是否被遗漏
冲突是否被错误“综合”
模糊参数是否被偷偷量化
case 是否混入未来结果
```

如果现有 schema 无法无损表达课程内容，允许升级 schema_version 后重新导出 Pilot；不允许通过删掉复杂信息来让 schema 看起来简单。

Gate：

```text
FOUNDATION_SCHEMA_V1_FROZEN
```

---

## S1.5 扩展至 20 节课程

前置：S1.4 通过。

目标：在冻结 schema 上处理 001–020 全量课程。

策略：

- transcript 若已在 S1.1 证明可用，则作为批量文字代理；
- 对高风险交易规则、关键冲突、方向性错词、重要案例回到 primary source；
- 不为了“全覆盖”把无法确认的内容强行标成 approved；
- 007/020 缺 PPT 属于 source coverage 事实，不视为数据错误；
- 隐藏缓存文件和非核心 PDF 未完成 provenance 前不进入 authoritative source set。

Gate：

```text
COURSE_001_020_SEMANTIC_COVERAGE_COMPLETE
```

这里的 `COMPLETE` 表示 20 节课程均经过 schema 管理，不表示所有 Rule Candidate 都已解决或批准。

---

## S1.6 Case Library 与 Evaluation Isolation

目标：把课程案例从普通知识片段升级为具备 causality 的 Case Card。

要求：

1. decision snapshot 与 outcome 分离；
2. 同案例派生资产归一到同一 case identity；
3. 标记现场判断、事后教学、纯示例；
4. 建立 `Foundation Knowledge / Evaluation Quarantine` 分区；
5. 未能证明“老师当时做出判断”的案例，不标记为 teacher live decision；
6. 结果字段不进入普通检索索引。

Gate：

```text
CASE_LIBRARY_V1_CAUSALITY_VERIFIED
```

---

## S1.7 Knowledge Foundation v1 发布

前置：S1.1–S1.6 Gate 全部通过。

目标：发布第一个可供后续应用固定读取的 immutable snapshot。

发布前必须：

```text
schema validation pass
stable-id uniqueness pass
source reference integrity pass
content hash pass
no orphan evidence pass
review status consistency pass
ambiguity/conflict counts explicit
quarantine isolation pass
manifest hash pass
private data boundary pass
```

最终状态：

```text
SUBING_KNOWLEDGE_FOUNDATION_V1_READY
```

该状态只表示共享知识基础数据可被后续独立应用读取，不表示：

```text
COURSE_QA_VERIFIED
SNAPSHOT_ANALYZER_VERIFIED
TRADING_VALUE_VERIFIED
RELEASED
RUNTIME_READY
```

---

## 14. Fail-closed 规则

遇到下列情况必须停止升级对应记录：

1. 文件名匹配但内容无法证明对应；
2. transcript 出现影响方向或交易语义的系统性错词；
3. derived note 与 primary source 冲突；
4. 来源归属无法证明；
5. statement 找不到可重现 locator；
6. 规则用途无法判断是入场、加仓、止盈还是止损；
7. 模糊参数缺少明确口径；
8. 同主题 primary source 真实冲突；
9. Case Card 无法把 decision snapshot 与 outcome 分离；
10. holdout 派生物可能进入普通检索；
11. Foundation snapshot hash 或引用完整性不一致。

Fail-closed 的正确输出是：

```text
UNRESOLVED
BLOCKED
UNKNOWN
```

而不是猜测一个看起来合理的答案。

---

## 15. 隐私、安全与版权边界

1. 原始课程与 Foundation 私有快照默认仅在本地私有研究目录处理；
2. 未经 Owner 明确批准，不把完整课程正文、视频、课件或大量截图发送给外部模型/API；
3. 可以使用模型辅助处理经授权的必要片段，但必须保留 `model_assisted` provenance；
4. 不读取、记录或提交 YouTube cookie、登录凭据、token 或账号信息；
5. 不要求把 Private/Unlisted 视频改为公开；本地原始文件是 Stage 1 的优先输入；
6. 归一仓库不得成为课程内容分发仓库。

---

## 16. 性能与可维护性约束

Stage 1 是离线知识构建流程，不承担浏览器实时 SLA，但必须为后续应用避免以下架构债务：

- 不在用户每次提问时重新转录视频；
- 不在每次行情分析时重新扫描 20 节课程原文件；
- 不把某个 embedding 模型或向量数据库固化成知识身份；
- consumer 读取 immutable snapshot，索引在 snapshot 之上增量/重建；
- source hash 未变化时，后续构建应能避免重复处理不变原始资产；
- 每个记录体保持单一职责，避免把原文、规则、冲突和案例混成一个“大总结”。

Stage 2 以后再通过实际 QA/检索性能基线决定 FTS、SQLite、vector 或其他 derived index，不在 Stage 1 预设复杂基础设施。

---

## 17. Stage 1 验收标准

Stage 1 只有同时满足以下条件，才允许声明 `SUBING_KNOWLEDGE_FOUNDATION_V1_READY`：

### 17.1 Source

- 001–020 均存在 Course Unit；
- 已知资产全部拥有 stable source identity 或明确 excluded/unknown 状态；
- 5 节样本完成 source calibration；
- transcript 是否可作为文字代理已有证据结论；
- 未确认的缓存文件、非核心资料没有被偷偷纳入 authority。

### 17.2 Provenance

- 每个 `APPROVED` Evidence Card 至少拥有一个可重现 source locator；
- 高风险 Rule Candidate 不能只依赖 `DERIVED_ONLY`；
- AI 派生、人工派生与老师原始表述可被机器区分；
- 真实 primary conflict 没有被静默覆盖。

### 17.3 Semantics

- Rule Candidate 完整区分 `HARD / PARAMETERIZED / JUDGMENT`；
- 所有未解决阈值进入 Ambiguity；
- 入场/加仓/持仓/止盈/止损用途不会被混写；
- 没有用通用金融知识补齐课程缺口。

### 17.4 Causality / Evaluation

- Case Card 分离 decision snapshot 与 outcome；
- holdout 及其派生物可从 normal retrieval 逻辑隔离；
- 没有用后验结果给历史 decision 添加当时不可知标签。

### 17.5 Snapshot

- canonical schema 全部验证通过；
- stable ID、source refs、hash、manifest 一致；
- snapshot immutable；
- unresolved ambiguity/conflict 显式计数；
- 后续应用能够只凭 snapshot_id 固定同一知识输入。

### 17.6 Isolation

- 不修改现有归一策略、数据、Web、Alert、Runtime 或 production state；
- 不向归一 Git 提交课程正文或私有 Foundation snapshot；
- 不恢复任何已退役 SuBing 策略身份；
- `auto_order=false` 边界没有变化。

---

## 18. 后续阶段接口，但不在 Stage 1 实现

Stage 1 对后续仅承诺一个只读概念接口：

```text
FoundationSnapshot(snapshot_id)
→ Evidence
→ Glossary
→ RuleCandidate
→ Ambiguity / Conflict
→ Case
→ Provenance
```

后续阶段分别独立设计：

```text
Stage 2 Course Knowledge Assistant
Stage 3 Market Research Engine
Stage 4 Evaluation / Shadow Research
Stage 5 Independent Research Workspace
Stage 6 Optional Guiyi Read-only Adapter
Stage 7 Optional Multimodal / Expert Modeling
```

任何后续阶段都不能通过“Foundation 已就绪”自动获得归一集成、正式策略、通知、Runtime 或交易权限。

---

## 19. Stage 1 开发顺序与 Gate 总览

```text
S1.1 Source Calibration
  → READY_FOR_SEMANTIC_EXTRACTION

S1.2 Source Registry / Normalized Segment
  → SOURCE_REGISTRY_V1_VALID

S1.3 Semantic Extraction Pilot
  → SEMANTIC_MODEL_PILOT_VALID

S1.4 Pilot Review / Schema Freeze
  → FOUNDATION_SCHEMA_V1_FROZEN

S1.5 Full 20-course Expansion
  → COURSE_001_020_SEMANTIC_COVERAGE_COMPLETE

S1.6 Case Library / Eval Isolation
  → CASE_LIBRARY_V1_CAUSALITY_VERIFIED

S1.7 Immutable Snapshot Publish
  → SUBING_KNOWLEDGE_FOUNDATION_V1_READY
```

每个 Gate 都是独立事实。前一 Gate 没有通过，不得以“效果看起来不错”为理由跳过。

---

## 20. Design Review Checklist

本 Spec 提交前必须通过以下 Review：

### Standards Review

- 与 `AGENTS.md` 的当前工程授权和 `auto_order=false` 一致；
- 与 `PROJECT_SOURCE.md` 的 active SuBing Alert 身份隔离；
- 不改变 `STATUS.md` 的 release / Runtime / natural evidence Gate；
- 不建立第二套行情事实链；
- 不恢复已退役策略实现；
- 不隐含真实通知、生产写入、main/tag/release 或 Runtime 权限。

### Spec Review

- Stage 1 是否只有一个明确目标；
- Canonical / Derived 是否分离；
- Source / Evidence / Rule / Ambiguity / Conflict / Case 是否职责单一；
- provenance 是否能回到真实资料；
- authority 是否避免粗暴全局排序；
- ambiguity/conflict 是否 fail-closed；
- case 是否从一开始保护 causality；
- Evaluation Holdout 是否与普通检索隔离；
- 数据版本是否可以 pin 到 immutable snapshot；
- 是否避免过早引入 RAG、向量库、知识图谱和微调；
- 是否避免让 Stage 1 影响当前归一产品面。

Review 未通过时不得进入 S1.1 实现。

### Review Result

2026-09-06 提交前完成内部双轴 Review：

```text
Standards Review = PASSED
Spec Review      = PASSED
Critical         = 0
Important        = 0
Minor            = 0
```

Review 中发现并已修正一个设计风险：最初 Case Card 将事后 `outcome` 与 decision-time 数据放在同一记录中，存在未来普通检索误读 Outcome 的风险；最终设计已拆分为 `case_cards.jsonl` 与 `case_outcomes.jsonl`，并要求 Holdout Outcome 进入 Evaluation Quarantine。

本 Review 只批准 Stage 1 设计进入后续独立实现规划，不批准 Stage 2、行情接入、归一 Adapter、正式策略、真实通知、Runtime 或任何交易能力。
