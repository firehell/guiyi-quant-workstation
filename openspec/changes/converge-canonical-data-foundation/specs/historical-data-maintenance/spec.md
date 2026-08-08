## Purpose

定义历史数据 update、bootstrap、repair 与 audit 的统一行为，使已有大规模历史数据只补精确缺口、固定水位可幂等重跑，并把一次性迁移安全收敛为日常增量闭环。

## ADDED Requirements

### Requirement: 四动作统一维护接口
历史数据维护 SHALL 只公开 `update`、`bootstrap`、`repair` 和 `audit` 四个动作，并 MUST 复用同一覆盖规划、标准化、校验、月分区发布、聚合、TargetWindow 验证和 DataGap 生命周期算法。

#### Scenario: Direct 处理一致性
- **WHEN** update、bootstrap 或 repair 获得相同 provider bar batch 与目标窗口
- **THEN** 三个动作产生相同 CanonicalBar、校验结论和分区内容

### Requirement: 精确增量和固定水位幂等
`--since` SHALL 仅限制缺口检查下界而不授权覆盖已有正确分区；`--through` SHALL 固定本次水位，默认取各交易所最新完整交易日。已有 Dataset SHALL 检查范围内全部历史缺口，空 Dataset SHALL 从 `product_window_starts.csv` 起算。

#### Scenario: covered since 窗口
- **WHEN** 显式 `--since` 后的请求窗口已被正确覆盖
- **THEN** update 产生零目标、零写入且不调用 RQData

#### Scenario: 中间历史洞
- **WHEN** Dataset 尾部已到 through 但中间月份存在精确缺口
- **THEN** update 只计划缺失窗口而不是仅从尾部追加或覆盖完整月份

#### Scenario: 固定 through 重跑
- **WHEN** 成功更新后使用相同 `--through` 再次运行
- **THEN** 结果为 NOOP，目标数、写入数和 RQData 请求数均为零

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

### Requirement: 一次性 bootstrap 白名单
迁移阶段 SHALL 只接受明确白名单的 actual contract raw、RQData continuous 候选及用于精确补缺的当前 Canonical/dominant 片段，并让所有候选通过同一标准化与六项校验。market samples、重复版本或身份不明文件 MUST NOT 直接合并；失败窗口 SHALL 形成精确 RQData 重下计划而不是逐行多源仲裁。

#### Scenario: legacy 候选通过
- **WHEN** 白名单候选身份唯一且完整通过六项校验
- **THEN** bootstrap 可将其发布到隔离候选 Canonical 而无需重复下载相同窗口

#### Scenario: 候选冲突
- **WHEN** 同一窗口存在无法唯一判定的多个 legacy 版本
- **THEN** bootstrap 拒绝合并并把完整问题窗口放入 RQData 重下计划

### Requirement: repair 精确计划
repair SHALL 只接受包含明确 DatasetKey、窗口、月份、原因和预期操作的 exact plan；成功发布并严格复验后 SHALL 删除对应 DataGap，失败 SHALL 保留最后有效分区和缺口。

#### Scenario: plan 超出允许根
- **WHEN** repair plan 的目标路径或 Dataset 身份不能规范化到 canonical root 和允许 universe
- **THEN** 系统在任何写入前拒绝整个结构性请求

### Requirement: audit 业务验收
audit SHALL 只读检查 active 69 品种预期的 continuous、全部 rank1 contract、七周期、Manifest/Catalog/Parquet 一致性、Map/spec 覆盖、DataGap 和 MarketDataService 探针，并以 finding count 非零作为失败。

#### Scenario: 完整 universe 验收
- **WHEN** 所有 expected Dataset 和元数据完整且严格探针可读
- **THEN** audit 返回 finding_count=0 且不执行 RQData、数据库或 Parquet 写入

### Requirement: 最小公开 CLI
用户级 CLI SHALL 只公开 `data update`、`data bootstrap`、`data repair` 与 `data audit`；`download`、`aggregate`、`sync`、`verify` 及 legacy task/migration/receipt 命令 MUST 不可调用。

#### Scenario: 旧命令调用
- **WHEN** 用户调用任一已删除公开子命令
- **THEN** CLI 以参数错误非零退出且不触发 provider 或 storage 副作用
