## ADDED Requirements

### Requirement: M01 唯一历史与现场权威

系统 SHALL 满足以下约束。历史走 RQData、staging 校验、Canonical、Catalog/MainContractMap、MarketDataService。一个部署的同一流只允许一个实时来源。现场证据带源和代次。

#### Scenario: 盘后修订

- **GIVEN** 同合约同端点同时有盘中原件与不同值的盘后修订
- **WHEN** Canonical 完成新发布
- **THEN** 研究使旧输入版本失效；现场快照、决策及成交仍可按原身份查回。

#### Scenario: 两源交接

- **GIVEN** 原源仍持有写入权
- **WHEN** 候选 CTP 源尝试推进
- **THEN** 拒绝推进；记录最终水位、停旧并验证新代次后，只处理未来新输入。

### Requirement: M02 Session 与完结性

系统 SHALL 满足以下约束。聚合严格按物理合约、交易日、Session、权威端点及完整输入进行。分钟、日、完整周各守完成时点。

#### Scenario: 跨段/无尾 Tick

- **GIVEN** 午休、夜盘跨自然日、尾分钟缺事实或成交量复位
- **WHEN** 构造 H1 或 W1
- **THEN** 对照既有端点与交易日；缺失段明确阻断，不跨段补价，不提前发布周线。

#### Scenario: 重复或迟到

- **GIVEN** 相同输入身份已处理
- **WHEN** 再收相同值、不同值或过期数据
- **THEN** 同值无第二次决策；异值隔离，过期只作诊断/预热，均不得补开仓。

### Requirement: M03 范围与容量

系统 SHALL 满足以下约束。研究能力、持续行情、策略部署、交易许可分别校验。范围变更必须原子生效；普通新增品种走现有配置、真实合约、权限及预热校验。

#### Scenario: 新增或越界

- **GIVEN** 已有 70 个行情品种或 20 个交易品种，含退出中品种
- **WHEN** 加入第 71 或第 21 个
- **THEN** 拒绝整个候选修订并保留当前版本；换月新旧物理订阅数另报。
