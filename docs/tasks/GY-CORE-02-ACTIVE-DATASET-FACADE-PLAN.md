# GY-CORE-02 ActiveDatasetResolver / MarketDataService 实施 Plan

更新时间：2026-07-30
状态：`PLAN_APPROVAL_REQUIRED`
计划基线：`develop@46bf563682c823d356edbd05530ef1be69879aec`
任务车道：Lane 3（active 数据选择）

## 1. 目标与结论

在不改变当前合法数据选择、lineage、API JSON 和错误码的前提下，新增只限 JM 的兼容
Facade：

```text
ActiveDatasetResolver
MarketDataService
DatasetDescriptor
BarsResult
```

首轮只迁移一个只读 caller：

```text
GET /api/v1/market/bars
  → MarketDataService
  → 现有 resolve_market_read_context / get_market_bars / readers
  → BarsResult
  → 原 MarketBarsResponse
```

本任务不是替换 Profile、MarketDataFile 或 Parquet reader。现有实现继续是选择和读取事实源；
Facade 只冻结、验证并统一表达其结果。

实现必须拆清两个 P0：

- strict rank-1 mapping 可在无 migration 前提下加入双 resolver 等价校验，歧义时 fail-closed；
- live `source_mode` 的 schema identity 当前无法在无 migration 下统一。首轮只支持显式 mode
  的 browser observation；strict live 固定 fail-closed。迁移另开 Lane 3，不伪装完成。

用户批准本 Plan 前，不创建产品代码、测试或 canonical 修改。

## 2. 当前仓库事实

### 2.1 历史读取

`market_workbench.get_market_bars()` 已具备成熟的 browser/research 双模式：

- browser 无 Profile 时读取所有合法
  `rqdata/local_parquet + primary + quality != failed` canonical assets，并按现有 provider
  优先级逐 bar 去重；
- browser 有 Profile 时允许 non-failed observation，warning 仍返回 200；
- research 必须有显式 Profile、唯一 active binding、单一 pinned file、passed quality、
  完整 source interval 和覆盖范围；
- lineage token 已覆盖 assets、binding snapshot、file IDs、version、provider、role、quality、
  checksum、coverage 和 source interval；
- expected file/token 漂移使用现有 409 `MARKET_LINEAGE_CHANGED`；
- Profile、quality、identity、range 错误使用现有稳定 422 `MARKET_*` code。

`MarketDataReader.load_bars_from_market_file()` 已支持 immutable file ID + provider/role/quality/
version/checksum/range 验证。generic `load_bars()` 是 browser 多资产兼容读取。

### 2.2 主力映射

`load_effective_main_contract_mapping()` 与 `load_strict_main_contract_mapping()` 均固定
`provider=rqdata / rule=volume_open_interest / rank=1`，但前者会在多个版本中选最新行，
后者会拒绝：

```text
ACTUAL_CONTRACT_MAPPING_INVALID
ACTUAL_CONTRACT_MAPPING_CONFLICT
ACTUAL_CONTRACT_MAPPING_DUPLICATE
```

`MainContractMap` 唯一键包含 `data_version`，数据库允许同日跨版本冲突。因此“当前实际主力”
必须提供 exact trading day，并由 strict resolver 判定唯一合法 identity。

### 2.3 live

`LiveMarketReader.get_bars()` 在 `source_mode=None` 时不筛 source；只展示 confirmed 且
quality 非 failed 的行。live 目前没有 historical 等价的 lineage token。

当前 P0：

- `live_minute_bars` 唯一键不含 `source_mode`；
- ingest checkpoint 唯一键包含 `source_mode`；
- 1m upsert 和 aggregation source query 未按 source mode 隔离；
- `live_aggregated_bars` 唯一键又包含 source mode。

因此首轮不能声明 strict live identity 已建立，也不能修改 schema、upsert 或 aggregation。

### 2.4 caller 边界

| Caller | 首轮处理 |
|---|---|
| `/api/v1/market/bars` | 唯一迁移 caller |
| workbench coverage | 保留旧入口 |
| indicators / MACD | 保留旧入口，继续共享旧 `get_market_bars()` |
| `/api/klines` | 保留 browser compatibility |
| live targets/coverage/bars | 保留旧 API，不迁移 |
| Backtest | 保留 frozen Profile/file/checksum 链 |
| Signal / HTDY | 保留现有 effective/strict mapping 与 writer Gate |
| Review | 保留 frozen report/event lineage |
| Web report contract/provider fallback | 保留 display-only 行为 |

修改 `market_workbench.get_market_bars()` 的内部选择会同时影响 bars、EMA 和 MACD，不符合
“首轮迁移一个 caller”。因此它保持 golden oracle。

## 3. 冻结设计

### 3.1 命名

公开 API 继续使用：

```text
access_mode=browser | research
```

文档中的 `strict` 对应现有 `research`。首轮不新增第三个 API 名称，也不改 Web 参数。

### 3.2 Domain model

新增 `services/quant-api/app/services/active_dataset.py`：

```python
DatasetContext = Literal["historical", "live"]
AccessMode = Literal["browser", "research"]
ContractSelector = Literal["explicit", "dominant_rank1"]

@dataclass(frozen=True)
class DatasetRequest:
    data_context: DatasetContext
    symbol: str
    contract_selector: ContractSelector
    contract: str | None
    period: str
    access_mode: AccessMode
    profile_id: str | None = None
    provider: str | None = None
    data_role: str | None = None
    live_source_mode: str | None = None
    mapping_date: date | None = None
    expected_market_data_file_id: int | None = None
    expected_lineage_token: str | None = None
    quote_mode: bool = False
    allow_continuous: bool = False

@dataclass(frozen=True)
class DatasetAsset:
    market_data_file_id: int | None
    provider: str
    data_role: str | None
    quality_status: str
    data_version: str | None
    checksum: str | None
    coverage_start: datetime | None
    coverage_end: datetime | None
    source_interval: str | None
    source_interval_basis: str | None

@dataclass(frozen=True)
class DatasetDescriptor:
    data_context: DatasetContext
    access_mode: AccessMode
    symbol: str
    contract_selector: ContractSelector
    requested_contract: str | None
    resolved_contract: str
    contract_role: str
    continuous_contract: str | None
    actual_contract: str | None
    period: str
    provider: str | None
    data_role: str | None
    live_source_mode: str | None
    quality_status: str
    strict_research_ready: bool
    profile_id: str | None
    quality_policy: str | None
    binding_snapshot: dict[str, Any] | None
    assets: tuple[DatasetAsset, ...]
    mapping_identity: dict[str, Any] | None
    coverage_start: datetime | None
    coverage_end: datetime | None
    source_coverage_row_count: int
    source_max_bar: datetime | None
    source_revision_hash: str | None
    lineage_kind: Literal["historical_asset", "live_response_snapshot", "unavailable"]
    lineage_token: str | None
    warnings: tuple[str, ...]

@dataclass(frozen=True)
class BarsResult:
    descriptor: DatasetDescriptor
    bars: tuple[dict[str, Any], ...]
    response_bar_count: int
    quality: dict[str, Any]
    coverage: dict[str, Any] | None
    response_request: dict[str, Any]
    message: str | None
```

规则：

- `assets[]` 是权威 asset identity；
- `contract_selector=explicit` 要求 contract；`dominant_rank1` 要求 exact `mapping_date`，
  contract 可为空，resolved contract 只能来自 strict mapping；
- strict historical 必须恰好一个 asset；
- browser 可以有多个合法 asset，descriptor token 绑定现有 lineage 顺序的完整集合；
- 单数 `file_id/checksum/version` 不以拼接字符串冒充多资产 identity；
- descriptor 不公开 file path 或 ORM 对象；
- `data_context` 与 live provider `source_mode` 分字段，禁止混用；
- 对外 API response 仍使用现有 Pydantic schema。
- historical `assets[]` 完全保持现有 `asset_evidence/market_data_file_ids` 顺序，不为展示
  重排，也不重算现有 token；live 没有 immutable file asset，固定
  `assets=()`，并通过 `source_max_bar/source_revision_hash` 表达本次只读 snapshot；
- live revision hash 版本固定为 `live-response-revision-v1`，对同一 response 中按
  `(time, live_bar_id)` 排序并按 response JSON 规范化后的完整 consumer-visible bar
  payload 做确定性 hash。字段至少包含：
  `live_bar_id/time/datetime/trading_day/symbol/contract/exchange/open/high/low/close/volume/
  openInterest/turnover/period/provider/data_version/bar_status/quality_status/source_mode/
  revision/confirmed_at/quality_reasons/source_bar_count/expected_bar_count/
  source_start_datetime/source_end_datetime`。空字段保留为 `null`；
  不查询第二次、不把它宣称为 DB schema identity；
- live `lineage_kind=live_response_snapshot`，token 版本固定为
  `live-response-snapshot-v1`，覆盖 symbol/contract/period/provider/source_mode、
  start/end/limit/tail 与 revision hash；它只证明一次返回窗口，不是 historical asset
  lineage 或完整 DB identity；
- historical `source_revision_hash` 由现有 lineage 顺序的 asset ID/checksum/token 派生，
  `source_max_bar` 使用本次 bars 的最大时间。
- `source_coverage_row_count` 来自 legacy coverage，`response_bar_count=len(bars)`；
  `source_max_bar` 是本次 response 的最大 bar time，空结果为 `None`，不等同于 coverage end。

### 3.3 ActiveDatasetResolver

新增 `active_dataset_resolver.py`，只做适配与验证，不复制 SQL、Profile 或 Parquet 算法。

#### Historical

```text
DatasetRequest
  → validate JM / contract / period / access mode
  → resolve_market_read_context()
  → existing MarketReadLineage / asset_evidence
  → normalized DatasetDescriptor
```

Resolver 必须保留现有：

- browser 多资产和 warning 语义；
- research Profile/quality/range/physical/source-interval Gate；
- provider/data-role mismatch；
- expected file/token 409；
- lineage token，不另造一套 historical token。

Profile binding 若已有 `market_data_file_id`，只接受该 pinned ID。遗留 binding 若 ID 为空，
现有 resolver 会按 `(symbol, contract, period, data_version, primary)` fallback；新 Resolver
只能对同一条件做候选数验证，不负责排序或另选：

```text
0 candidate  → DATASET_ASSET_MISSING
1 candidate  → 必须等于 legacy context 已选 file
>1 candidate → DATASET_ASSET_AMBIGUOUS
```

这是 fail-closed validation，不是第二套 active selector；不得增加 provider fallback。

新 domain 只允许下列稳定失败码；已迁移 historical API 必须把兼容场景映射回现有
`MARKET_*` code，不把新内部 code 泄漏成 API 变化：

```text
DATASET_REQUEST_UNSUPPORTED
DATASET_ASSET_MISSING
DATASET_ASSET_AMBIGUOUS
DATASET_LINEAGE_CHANGED
DATASET_ACTUAL_CONTRACT_MISMATCH
LIVE_ACTUAL_CONTRACT_REQUIRED
LIVE_SOURCE_MODE_REQUIRED
LIVE_SOURCE_MODE_MISMATCH
LIVE_SOURCE_MODE_IDENTITY_UNSUPPORTED
```

mapping invalid/conflict/duplicate 继续复用现有 `ACTUAL_CONTRACT_MAPPING_*`。

#### Rank-1 actual

只在 `contract_selector=dominant_rank1` 且请求声明 `mapping_date` 时执行：

```text
strict row = load_strict_main_contract_mapping(exact date)
legacy row = load_effective_main_contract_mapping(exact date)
compare id/contract/date/provider/rule/rank/data_version
verify strict contract == resolved contract
if request also supplied contract, verify requested contract == strict contract
  → exact match: freeze mapping_identity
  → missing/invalid/conflict/duplicate/mismatch: fail-closed
```

不修改 `LiveTargetContractResolver`、EOD、actual-history writer 或 mapping 表。

`contract_selector=explicit` 的 `jm.MAIN`/`JMxxxx` historical 请求保持原语义；不在没有
`mapping_date` 时猜测“当前”日期。

`dominant_rank1` 的 contract 可省略；若 caller 同时提供 actual contract，它只是 expected
contract，必须与 strict mapping 完全相等。mismatch 使用
`DATASET_ACTUAL_CONTRACT_MISMATCH`，并映射为稳定 422；不得改选请求值或 mapping 值。

#### Live

首轮：

- 只限 actual `JMxxxx`，拒绝 `jm.MAIN`；
- provider 必须显式为 `rqdata`；
- 1m `live_source_mode=poll_get_price_1m`；
- 15m `live_source_mode=live_1m_sequential_bucket`；
- live 首轮只允许 `tail=False`，保持现有 `LiveMarketReader.get_bars()` 的升序/limit 语义；
  `tail=True` 返回 `DATASET_REQUEST_UNSUPPORTED`，不得静默忽略；
- browser 调用现有 `LiveMarketReader`，逐 bar 验证 provider/source_mode，输出
  `strict_research_ready=false` 和 warning `live_source_identity_unverified`；
- source mode 缺失或不一致，稳定 fail-closed；
- research/strict 统一返回 `LIVE_SOURCE_MODE_IDENTITY_UNSUPPORTED`。

这套 live Facade 暂不迁移任何现有 API caller，因此不会改变当前 Web live 行为。

### 3.4 MarketDataService

新增 `market_data_service.py`：

```python
class MarketDataService:
    def get_bars(
        self,
        request: DatasetRequest,
        *,
        start: datetime | None,
        end: datetime | None,
        limit: int,
        tail: bool,
    ) -> BarsResult: ...

    def to_market_bars_response(
        self,
        result: BarsResult,
    ) -> MarketBarsResponse: ...
```

Historical 执行：

1. Resolver 只调用一次现有 context，冻结 descriptor、MarketDataFile 对象/IDs 和 lineage；
2. `market_workbench.get_market_bars()` 新增仅供内部注入的 optional resolved-context /
   frozen-file-IDs 参数；现有 callers 不传时行为不变；
3. 新 `MarketDataReader.load_bars_from_market_files()` 只接受冻结 IDs/evidence，不再查询
   active 集合；
4. generic `load_bars()` 与 exact 方法下沉到同一个私有
   `_load_bars_from_market_files()`，唯一 dedupe SQL 不复制；
5. `get_quality_status()` / `get_cross_file_conflicts()` 同样抽取共享的 frozen-file-set
   私有实现；Facade 的 quality/conflict 不重新选择第三次；
6. old workbench 继续负责 range、quality、coverage、message、request 和错误码；
7. Service 比较 response lineage 与 descriptor 的 file IDs、asset evidence 和 token；
8. 任一漂移使用现有 `MARKET_LINEAGE_CHANGED`，不重试、不换 provider；
9. `quote_mode/allow_continuous` 原样透传；old response 自然保留 coverage 派生的 start/end
   以及 caller 原始 expected ID/token，不做“整份 request 恢复”；
10. 返回统一 `BarsResult`，adapter 从 `response_request` 还原相同 MarketBarsResponse，
    API route 只取兼容 response。

Browser 多资产的 selection、bars、quality、conflict 和 lineage 至此绑定同一个冻结 file set。
Facade 不含 SQL/dedupe；formal consumers 仍不得使用 browser fallback。

Live 执行调用现有 `LiveMarketReader.get_bars()` 一次，基于同一 response 验证并生成
descriptor/result；不进行第二次可漂移读取。

## 4. 文件范围

### 4.1 实现时新增

- `services/quant-api/app/services/active_dataset.py`
- `services/quant-api/app/services/active_dataset_resolver.py`
- `services/quant-api/app/services/market_data_service.py`
- `services/quant-api/tests/test_active_dataset_resolver.py`
- `services/quant-api/tests/test_market_data_service.py`
- `services/quant-api/tests/test_market_data_facade_equivalence.py`

### 4.2 实现时修改

- `services/quant-api/app/api/market.py`
  - 只改 `/api/v1/market/bars` 的内部 caller；
- `services/quant-api/app/services/market_data_reader.py`
  - 新增 exact frozen file-set bars/quality/conflict seam；
  - generic 与 exact 入口共用同一私有 SQL/dedupe 实现；
- `services/quant-api/app/services/market_workbench.py`
  - 新增 optional resolved-context/frozen-file-set 内部 seam；
  - 所有现有 caller 省略参数时行为不变；
- `docs/ARCHITECTURE.md`
- `docs/DATA_CENTER.md`
- `TESTING.md`
- `STATUS.md`
  - 仅实现、测试、独立 Review 后记录 `CODE_COMPLETE_EXTERNAL_GATE_PENDING`；
  - 不写 Runtime/live identity/Ready 已完成。

### 4.3 明确不修改

- `profile_lineage.py`
- `data_profile_registry.py`
- `profile_target_resolver.py`
- `live_market_reader.py`
- `live_target_contracts.py`
- `actual_contract_semantics.py`
- `models/data_center.py`
- `alembic/versions/*`
- `live_1m_ingest.py`
- `live_multi_tf_aggregation.py`
- EOD、after-market、HTDY、Signal、notification、Runtime；
- `configs/data_profiles/*`；
- Web；
- report 14/15、旧 S6-10、receipt/evidence；
- 真实 PostgreSQL、Redis/RQ、RQData、Parquet 和 Profile binding。

若实现证明必须修改上述文件，停止并重新请求 Plan 批准，不扩大 diff。

## 5. 实现步骤

### Task 1：冻结 domain contract

- 新增 frozen request/asset/descriptor/result；
- 固定 JM、contract role、period、access/context 组合；
- 固定内部 error code 与无 path/secret 输出；
- 单元测试 token 确定性、asset 排序和非法组合。

### Task 2：Historical resolver

- 委托现有 `resolve_market_read_context`；
- 映射现有 lineage/asset evidence，不重算 historical token；
- 增加 rank-1 strict/effective identity comparison；
- 覆盖 `jm.MAIN`、显式 actual、rank1 actual 和失败矩阵。

### Task 3：MarketDataService

- 先在现有 reader 抽取 exact frozen file-set 的共享读取/quality/conflict seam；
- 让旧 `get_market_bars()` 可选消费同一个 resolved context/file set；
- Facade 调用该兼容 seam，禁止 bars/quality/lineage 重新选择；
- 生成 BarsResult；
- adapter 保持原 response，包括 quote/continuous 和 coverage 派生 request；
- 增加显式 live browser/read-only 与 strict unsupported 分支。

### Task 4：单 caller 迁移

- 只把 `api.market.market_bars()` 改为 service；
- route 参数、response model、HTTP status、JSON、message 和 error code 不变；
- coverage、indicator、MACD、live route 保持旧调用。

### Task 5：等价和零写入验证

- SQLite in-memory + `tmp_path` Parquet；
- 旧 `get_market_bars()` 是 golden oracle；
- 新旧 response 全量 JSON 比较；
- 表 row count 与 SQLAlchemy `new/dirty/deleted` 前后相等；
- 不连接真实环境。

### Task 6：文档、独立 Review 和 PR

- 记录兼容 Facade、唯一 migrated caller、live P0 未完成；
- 独立 spec/quality Review；
- 修复 Critical/Important；
- 测试全绿后 commit、push、draft PR；
- 用户手动 merge。

## 6. 等价与测试矩阵

### 6.1 Fixtures

- `jm.MAIN / 15m / rqdata / primary / passed`；
- `JM2609 / 15m / rqdata / primary / passed`；
- DataProfile、active binding、quality report；
- warning、unchecked、failed；
- rqdata/local_parquet browser 多资产与重复 bar；
- missing Profile/binding/file、missing physical file、uncovered range；
- mapping 唯一、同 contract 多 version、不同 contract、同 version duplicate、空/`.MAIN`；
- live 1m/15m passed/warning/forming/rejected/partial、显式/多 source mode。

### 6.2 Historical assertions

对旧函数和新 service adapter 比较完整
`MarketBarsResponse.model_dump(mode="json")`，并逐项比较：

- profile ID、file ID/IDs、binding snapshot；
- contract role、continuous/actual contract、period；
- provider、data role、quality、version、checksum；
- coverage start/end/row count；
- source interval/basis、lineage token；
- bar 数量、顺序和 key；
- time/datetime/trading_day/exchange；
- OHLCV、open interest、turnover；
- provider、data version；
- limit、tail；
- quality、coverage、request、message、`strict_research_ready`；
- `quote_mode/allow_continuous` 的 `.MAIN` 允许/拒绝行为；
- start/end 省略时 response request 使用旧 coverage 派生值；
- caller expected file/token 为 `None` 与非 `None`；
- HTTP status 与稳定 `MARKET_*` code。

两类 owner-approved fail-closed 差异必须单列，不得包装成等价：

1. ambiguous rank1 mapping：旧 effective 会选一条，新 strict 必须失败；
2. legacy Profile fallback：pinned ID 缺失时旧 resolver 可能按 data version 回退，或在多个
   candidate 中取 scalar；新 Facade 要求 pinned ID 存在，fallback 只能恰好一个 candidate。

稳定 API 映射：

```text
pinned ID missing / fallback 0 → 422 MARKET_PROFILE_FILE_MISSING
fallback >1                  → 422 MARKET_PROFILE_IDENTITY_MISMATCH
fallback 1 but context differs → 409 MARKET_LINEAGE_CHANGED
```

测试必须覆盖 pinned-ID-missing、fallback 0/1/>1；合法 fallback 1 保持完整 response 等价。

### 6.3 Live assertions

- browser 1m/15m 在显式 mode 下与旧 reader 逐 bar相等；
- warning/partial 元数据保留；
- source mode 缺失/混合/错误不 fallback；
- strict live 固定 `LIVE_SOURCE_MODE_IDENTITY_UNSUPPORTED`；
- live `tail=False` 等价；`tail=True` 固定 `DATASET_REQUEST_UNSUPPORTED`；
- live `.MAIN` 拒绝；
- 不迁移 live API route。

### 6.4 命令

新测试：

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_active_dataset_resolver.py \
  services/quant-api/tests/test_market_data_service.py \
  services/quant-api/tests/test_market_data_facade_equivalence.py
```

Market/Profile 回归：

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_actual_contract_semantics.py \
  services/quant-api/tests/test_data_profile_registry.py \
  services/quant-api/tests/test_profile_target_resolver.py \
  services/quant-api/tests/test_market_data_reader.py \
  services/quant-api/tests/test_market_data_api.py \
  services/quant-api/tests/test_market_dual_mode_contract.py \
  services/quant-api/tests/test_market_indicators_api.py \
  services/quant-api/tests/test_market_macd_indicator_api.py \
  services/quant-api/tests/test_live_market_reader.py \
  services/quant-api/tests/test_live_target_freshness.py
```

下游未迁移合同：

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_backtest_profile_contract.py \
  services/quant-api/tests/test_signal_review_profile_lineage.py \
  services/quant-api/tests/test_review_center.py
```

静态与工程 Gate：

```bash
uv run --project services/quant-api ruff check \
  services/quant-api/app/services/active_dataset.py \
  services/quant-api/app/services/active_dataset_resolver.py \
  services/quant-api/app/services/market_data_service.py \
  services/quant-api/app/services/market_data_reader.py \
  services/quant-api/app/services/market_workbench.py \
  services/quant-api/app/api/market.py \
  services/quant-api/tests/test_active_dataset_resolver.py \
  services/quant-api/tests/test_market_data_service.py \
  services/quant-api/tests/test_market_data_facade_equivalence.py

bash scripts/engineering/test.sh docs
TMPDIR=/private/tmp bash scripts/engineering/test.sh engineering
bash scripts/engineering/check-secrets.sh
git diff --check
```

禁止运行 Alembic upgrade、真实 PostgreSQL/RQData/Runtime Gate。

## 7. 风险与回滚

| 风险 | 控制 |
|---|---|
| Facade 变成第二套 selector | 只委托现有 context/reader；新旧 response golden 对照 |
| browser 多资产被误当唯一资产 | `assets[]` 权威；strict 才要求单一 asset |
| browser bars/quality/lineage 读取不同 file set | 单次 context + frozen IDs；existing reader 内共享唯一 SQL/dedupe |
| Profile/file 在读取期间变化 | exact IDs/evidence 校验；漂移 409，不重试 |
| API request 漂移 | old workbench 继续构造 request；覆盖省略 range、quote 和 expected token |
| strict mapping 改变旧选择 | 只用于新 rank1 selector；歧义 fail-closed；不迁移旧 writer |
| live source mode 被伪装统一 | browser 显式 mode + warning；strict unsupported；另开 migration |
| 影响 indicator/backtest/signal/review | 只迁移 route caller，shared old function不改 |
| 读取产生写入 | session/table baseline + `new/dirty/deleted` 零变化 |

代码回滚只使用 PR/merge commit 的 `git revert`。本任务不产生数据、migration、Runtime 或
部署回滚。

## 8. 验收标准

- 四个新边界存在且没有复制现有选择/reader 算法；
- browser 多资产 selection/bars/quality/conflict/lineage 绑定同一 frozen file set；
- 仅 JM；
- historical `.MAIN`、explicit/rank1 actual 与 live 1m/15m 支持矩阵符合本 Plan；
- `/api/v1/market/bars` 是唯一 migrated caller；
- 合法输入新旧完整 response 等价；
- ambiguous mapping 按批准政策 fail-closed；
- live strict 明确 unsupported，不声明 unified identity；
- 不修改禁止文件；
- 测试、Ruff、docs、engineering、secret、diff 全绿；
- 独立 Review 无 Critical/Important；
- 状态只能是 `CODE_COMPLETE_EXTERNAL_GATE_PENDING`，不得发布任何 Ready。

## 9. 用户批准项

批准本 Plan 等于同时接受以下推荐决策：

1. 公开 API 保留 `access_mode=research`，文档中的 strict 只作语义别名；
2. browser 多资产使用 `assets[]` 表达，strict historical 必须唯一 pinned asset；
3. ambiguous MainContractMap 从旧 latest-selection 改为新 Facade 内 strict fail-closed；
4. Profile pinned ID 缺失或 fallback 多候选时新 Facade fail-closed，不再静默选一条；
5. 首轮 live browser 强制显式 provider/source mode 且只支持 `tail=False`，
   strict live 1m/15m 固定 unsupported；
6. live source-mode schema/upsert/aggregation 修复另开 Lane 3 Plan，并在
   `GY-CORE-05` Shadow 前完成；
7. 唯一 migrated caller 为 historical `/api/v1/market/bars`；
8. 允许在现有 reader/workbench 抽取 frozen file-set 兼容 seam，但不改变默认 caller 行为；
9. live token 只是 `live-response-snapshot-v1`，不是 DB/schema identity；
10. 实现阶段仍禁止 migration、真实数据、Profile binding、Runtime 和通知。

若接受，用户结论：

```text
允许继续实现 GY-CORE-02
```

该结论只批准在本 task worktree 实现上述文件和测试；不批准 P0 live migration、真实写入、
Runtime、release、main/tag 或部署。
