## Purpose

定义历史数据 update、bootstrap、repair 与 audit 的统一行为，使 V1 Recent Trusted Window 可幂等构建与增量，并把 migration-only legacy 路径安全冻结至 Gate C 后删除。

## ADDED Requirements

### Requirement: 四动作统一维护接口
历史数据维护 SHALL 只公开 `update`、`bootstrap`、`repair` 和 `audit` 四个动作，并 MUST 复用同一覆盖规划、标准化、校验、月分区发布、聚合、TargetWindow 验证和 DataGap 生命周期算法。

#### Scenario: Direct 处理一致性
- **WHEN** update、bootstrap 或 repair 获得相同 provider bar batch 与目标窗口
- **THEN** 三个动作产生相同 CanonicalBar、校验结论和分区内容

### Requirement: 精确增量和固定水位幂等
`--since` SHALL 仅限制缺口检查下界而不授权覆盖已有正确分区；`--through` SHALL 固定本次水位，默认取各交易所最新完整交易日。已有 Dataset SHALL 检查范围内全部历史缺口。空 Dataset SHALL 从 `effective_start(symbol) = max(product_window_starts.csv 中的起点, active_history_floor)` 起算；V1 `active_history_floor` SHALL 为 `data/universe/active_history_floor.txt` 中的 `2023-01-01`，且 MUST NOT 改写 `product_window_starts.csv` 的长期事实。

#### Scenario: covered since 窗口
- **WHEN** 显式 `--since` 后的请求窗口已被正确覆盖
- **THEN** update 产生零目标、零写入且不调用 RQData

#### Scenario: 中间历史洞
- **WHEN** Dataset 尾部已到 through 但中间月份存在精确缺口
- **THEN** update 只计划缺失窗口而不是仅从尾部追加或覆盖完整月份

#### Scenario: 固定 through 重跑
- **WHEN** 成功更新后使用相同 `--through` 再次运行
- **THEN** 结果为 NOOP，目标数、写入数和 RQData 请求数均为零

#### Scenario: floor 抬高早期上市品种
- **WHEN** 品种在 `product_window_starts.csv` 的起点早于 `2023-01-01`
- **THEN** 空 Dataset 与覆盖规划从 `2023-01-01` 起算

#### Scenario: 晚于 floor 的上市品种
- **WHEN** 品种起点晚于 `2023-01-01`
- **THEN** effective_start 仍为其 listing/provider 起点，不得提前到 floor

### Requirement: 统一更新顺序
apply 模式 SHALL 按 Calendar/Session/MainContractMap/contract_specs、最新完整交易日、continuous Direct、rank1 contract Direct、Derived、严格读取验证的顺序执行。结构性 schema、database 或 canonical root 错误 MUST 全局中止；单品种数据失败 SHALL 允许无依赖品种继续但整体退出码非零。

#### Scenario: 元数据先于最终规划
- **WHEN** apply 开始时初始 bar 缺口为空但元数据水位可能过期
- **THEN** 系统仍同步元数据并基于刷新后的固定 through 形成最终精确计划

#### Scenario: 品种隔离
- **WHEN** 一个品种的 provider window 失败而另一品种无依赖
- **THEN** 后者继续处理且最终结果明确列出失败品种并返回非零退出码

### Requirement: rank1 真实合约保存窗口
contract Direct SHALL 只覆盖 MainContractMap rank1 的有效窗口，不得扩展到真实合约完整上市生命周期；每个连续 rank1 片段 SHALL 被精确规划到对应 contract Dataset。

#### Scenario: 新主力合约首次出现
- **WHEN** MainContractMap 新增一个此前没有 Catalog Dataset 的 rank1 合约窗口
- **THEN** update 发现并计划该真实合约的 direct 与相依 derived 目标

### Requirement: RQData-only Candidate 与 legacy freeze
新 Gate A Candidate 构建 SHALL 复用正常 `HistoricalDataManager.update`，仅允许最薄的隔离 composition（独立 Session + 隔离 Canonical root + RQData adapter），且 MUST 设置 `legacy=None`。既有 migration-only legacy 白名单 bootstrap 实现 MAY 保留至 Gate C，但 MUST NOT 新增能力、MUST NOT 继续作为新 Gate A 数据源；Gate C 通过后 SHALL 删除 legacy adapter 与相关 active references。Candidate Manifest 的 direct `source_kind` SHALL 为 RQData，derived SHALL 为 `derived_1m`；MUST NOT 产生 `legacy_staging` 或 `bootstrap_mixed` 作为新 Gate A 结果语义。

#### Scenario: 空 Candidate 仅用 RQData 构建
- **WHEN** 隔离 Candidate DB/Root 为空且以 fixed through 执行 apply update
- **THEN** 系统仅调用 RQData，不读取 legacy 白名单根，并发布 effective_start→through 的预期分区

#### Scenario: legacy 路径冻结
- **WHEN** 新 Gate A 或日常 update 组装 HistoricalDataManager
- **THEN** 生产与新 Candidate composition 的 `legacy` 为 None

### Requirement: C2.5 Candidate target 前置检查与有界诊断
单一 Candidate metadata SHALL 以不可变 identity 与可变状态分别记录 Candidate。identity 精确包含隔离 Catalog/Session identity、Canonical root identity、active-universe digest、active_history_floor、source policy（`RQData-only` 且 `legacy=None`）和 candidate code SHA；Canonical root 仅以稳定非敏感 identity 表达，不得保存完整本地路径。metadata 的唯一可变进度字段为 `recorded_through`。

首次运行 MUST 通过 fresh 检查：Candidate 为空且不存在可被读取的 Catalog/Canonical 状态。后续运行 MUST 通过 extend 检查：请求的不可变 identity 与 metadata 完全相同，且 `requested_through >= recorded_through`；成功后 MUST 将同一 Candidate metadata 中的 `recorded_through` 更新为 `max(recorded_through, requested_through)`。identity 不同、metadata 缺失、target 非空却声明 fresh 或 requested through 倒退时，系统 MUST 在构造 RQData client 或写入前失败。公开 Candidate 操作 MUST NOT 提供 reset、resume、清空或自动恢复语义。

Candidate 诊断的允许顶层字段精确为 `reason_code`、`mode`、`candidate_identity_digest`、`recorded_through`、`requested_through`、`planned_count`、`applied_count`、`noop_count`、`blocked_count`、`failed_count` 和 `samples`；`samples` MUST 最多包含 20 个样本。每个 sample MUST 是只含 `kind`、`symbol`、`series_or_contract`、`frequency`、`start`、`end`、`reason_code` 的无嵌套对象：前四字段精确组成 DatasetKey，`kind` SHALL 为 `continuous|contract` 且最多 10 个 ASCII 字符，`symbol` SHALL 匹配 `[A-Z0-9_]{1,16}`，`series_or_contract` SHALL 匹配 `[A-Z0-9_]{1,32}`，`frequency` SHALL 为 `1m|5m|15m|30m|60m|1d|1w` 且最多 3 个 ASCII 字符。`start` 与 `end` SHALL 为以 `Z` 结尾、最多 27 个字符的 ISO-8601 UTC timestamp，且 `start <= end`。sample 与顶层的 `reason_code` SHALL 只取 `CANDIDATE_TARGET_NOT_EMPTY`、`CANDIDATE_METADATA_MISSING`、`CANDIDATE_IDENTITY_MISMATCH`、`CANDIDATE_THROUGH_REGRESSION`、`CANDIDATE_SESSION_FACT_MISSING`、`CANDIDATE_UNSUPPORTED_OPERATION` 或 `CANDIDATE_PRECONDITION_FAILED`。MUST NOT 输出其他字段、嵌套对象/数组、provider raw payload、凭据、路径、SQL、异常文本/堆栈或任意 value payload。

#### Scenario: fresh 检查拒绝非空 target
- **WHEN** 声明 fresh Candidate 但隔离 Catalog 或 Canonical root 已含可读状态
- **THEN** 系统在任何 provider 请求或写入前拒绝该调用，并返回有界诊断

#### Scenario: extend 检查拒绝漂移 target
- **WHEN** 声明 extend Candidate 但请求 identity 与 metadata 不同，或 `requested_through < recorded_through`
- **THEN** 系统在任何 provider 请求或写入前拒绝该调用，并返回稳定 reason code

#### Scenario: extend 单调记录 through
- **WHEN** Candidate identity 匹配且 `requested_through >= recorded_through`
- **THEN** 系统仅在同一 Candidate metadata 中将 `recorded_through` 单调更新为两者最大值

#### Scenario: 诊断 schema 有界
- **WHEN** Candidate 前置检查失败
- **THEN** 诊断只包含允许顶层字段；samples 不超过 20 项，且每项只含合法四字段 DatasetKey、合法 UTC start/end 和枚举 reason code

#### Scenario: 诊断 sample 拒绝越界载荷
- **WHEN** 待输出 sample 含未知字段、嵌套对象/数组、超过字段长度上限的标识符、非 UTC ISO timestamp、`start > end`、未枚举 reason code，或路径、SQL、异常/value payload
- **THEN** 系统拒绝该 sample 而不把它序列化到诊断中

#### Scenario: 无 reset 或 resume 操作
- **WHEN** 用户尝试调用 Candidate reset、resume、清空或自动恢复操作
- **THEN** CLI 以参数错误非零退出且不触发 provider、数据库或 Canonical 副作用

### Requirement: repair 精确计划
repair SHALL 只接受包含明确 DatasetKey、窗口、月份、原因和预期操作的 exact plan；成功发布并严格复验后 SHALL 删除对应 DataGap，失败 SHALL 保留最后有效分区和缺口。

#### Scenario: plan 超出允许根
- **WHEN** repair plan 的目标路径或 Dataset 身份不能规范化到 canonical root 和允许 universe
- **THEN** 系统在任何写入前拒绝整个结构性请求

### Requirement: audit 业务验收
audit SHALL 只读检查 active 69 品种在 Recent Trusted Window 内预期的 continuous、全部 rank1 contract、七周期、Manifest/Catalog/Parquet 一致性、Map/spec 覆盖、DataGap 和 MarketDataService 探针，并以 finding count 非零作为失败。

#### Scenario: 完整 universe 验收
- **WHEN** 所有 expected Dataset 和元数据完整且严格探针可读
- **THEN** audit 返回 finding_count=0 且不执行 RQData、数据库或 Parquet 写入

### Requirement: 最小公开 CLI
用户级 CLI SHALL 只公开 `data update`、`data bootstrap`、`data repair` 与 `data audit`；`download`、`aggregate`、`sync`、`verify` 及 legacy task/migration/receipt 命令 MUST 不可调用。

#### Scenario: 旧命令调用
- **WHEN** 用户调用任一已删除公开子命令
- **THEN** CLI 以参数错误非零退出且不触发 provider 或 storage 副作用
