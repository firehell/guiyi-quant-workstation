# 牛哇日线差量恢复 Implementation Plan

> **For agentic workers:** 实施获批后使用 `superpowers:executing-plans`，按下面任务顺序执行并在出口复核。
> 本轮仅编写、审查和提交文档；未批准或开始恢复代码、真实下载、生产写入、发布或 Runtime 操作。

**Goal:** 用一次明确范围的日线任务完成原生依赖盘点、精确分批、受控恢复和三层结算。

**Architecture:** 在现有 recovery/campaign 中增加封闭 D1 profile，复用原生 planner、RQData adapter、
单分区 writer 与 strict reader。新增一个日线只读结算模块隔离独立进程 I/O 和汇总职责；
原始 audit、plan、journal 和 readback 仍是依据，不新增数据平台或完整性权威。

**Tech Stack:** Python、现有 argparse 编排、pytest、SQLAlchemy readonly transaction、Canonical Parquet、MDS。

**Spec:** [design.md](design.md)。复核记录：[review.md](review.md)。
计划核对基线为 `develop@c9ed8ec503bda9287f4b77967854a3d696c8014b`，恢复代码与原始设计基线 d653a8c 相同。

## Global Constraints

- 仅两个范围：`1d -> [1d]`、既有 `1w -> [1d,1w]`；显式 D1 不允许退回缺省七周期。
- 不修改 manager/adapter 的行情、normalization、发布、projection invalidation 或合约生命周期语义。
- completed、strict-before、physical contract、warm-up、owner/provenance 和 Decimal 合同不变。
- D1 public matrix 保持 UNOPENED；release_stage=weekly 与 frequency_scope=[1d] 合法共存。
- 不修改三策略公式、ReferenceTrade、capabilities、完整跨周期 explanation、60m、通知或账户。
- W1 旧 schema、policy、importer、失败规则及 exact 执行根不升级、不重写；新代码不能执行旧批准。
- 真实写入与 W1 恢复、自然维护串行；异常、漂移、部分提交或未知不自动 retry/resume。
- 全部执行命令集中在 [TESTING.md](../../../TESTING.md)；本文件的代码块为待实现接口/测试约束，非现有命令。
- 文档计划不写入 docs/superpowers，不提前修改 STATUS 为 Ready。开始代码工作前重新核对最新 develop 与工作树。

## 文件与职责

| 文件 | 本次计划中的责任 |
|---|---|
| scripts/newow_weekly_recovery.py | 封闭 scope/schema 校验，D1 子包 prepare/apply/零提交与事后读回，执行摘要 |
| scripts/newow_weekly_recovery_campaign.py | D1 原生报告验证、自动分批、总包身份、执行与独立验收接续 |
| scripts/newow_daily_recovery_verification.py（新增） | 只读独立进程、全范围 D1 audit、单元 replan、派生摘要和 Markdown |
| services/quant-api/tests/newow/test_weekly_recovery.py | 子执行器 D1 新测试及既有 W1 回归 |
| services/quant-api/tests/newow/test_weekly_recovery_campaign.py | D1 report/包/终态与跨批执行测试，保留原 W1 fixtures |
| services/quant-api/tests/newow/test_daily_recovery_verification.py（新增） | 最终审计、身份漂移、只读能力、分母与验收失败 |
| services/quant-api/tests/newow/test_readiness.py、test_product_reader.py | D1 同 owner/consumer、生命周期和比较器输入覆盖 |
| docs/DATA_CENTER.md、openspec/specs/historical-data-maintenance/spec.md | 实施时同步 D1 来源隔离与独立结算合同 |
| TESTING.md | 实施后的定向命令、prepare/apply/inspect/verify 用法及退出语义 |

除确有必要的只读 composition 提取外，不计划改 readiness、product service 或 native manager。
若真实只读组合需要提取 helper，复用现有 `app.guiyi_cli.main._run_data` 的 newow-readiness 分支及 `readiness_composition.build_newow_readiness` 的构造方式，
不另建 reader/resolver；新增执行/验证依赖进入 D1 execution digest。

## Task 1：封闭 D1 包合同和离线 prepare

**输入：** 原生 `ContractWarmupRequest`、完整 D1 readiness 报告、现有 W1 schema 和两个脚本。
**输出：** scope/schema 解析与离线 D1 包构造（fixture 身份）；现有 W1 调用仍按原规则工作。
本任务不验收真实完整 prepare。Task 2/3 使用显式注入身份的隔离 fixture；
完整 D1 execution digest 与真实代码根的成功冻结测试统一在 Task 4 完成，避免依赖尚未落地的验证模块。

在现有 recovery 模块内定义一个封闭 scope 解析点，不建注册器或泛型框架。计划接口为：

```python
RecoveryFrequency = Literal["1w", "1d"]

def _recovery_frequency(value: object) -> RecoveryFrequency:
    if type(value) is not str or value not in ("1w", "1d"):
        raise RecoveryError("RECOVERY_SCOPE_INVALID")
    return cast(RecoveryFrequency, value)
```

`prepare_bounded_units` 新增 keyword `recovery_frequency: RecoveryFrequency = "1w"`；
`_validated_unit`、`_validated_continuation_policy`、`source_isolation_policy`、
`_current_execution_code_sha256` 通过同名 keyword 接收范围，缺省仅保留原 W1 语义。
执行入口从已验证 manifest schema 解析范围，不接收 apply 时的频率覆盖。

| 对象 | W1 | D1 新身份 |
|---|---|---|
| prepare | newow_weekly_recovery_prepare_v1 | newow_daily_recovery_prepare_v1 |
| campaign | newow_weekly_recovery_campaign_v1 | newow_daily_recovery_campaign_v1 |
| continuation policy | newow_weekly_recovery_continuation_policy_v1 | newow_daily_recovery_continuation_policy_v1 |

D1 包记录 `frequency_scope=[1d]`；子包与总包的 schema、单元 frequency、DatasetKey 必须一致。
policy 沿用唯一错误码 `RQDATA_ZERO_OHL_INVALID` 和严格零提交条件，不新增 partial 隔离规则。
未识别 schema 直接拒绝，不能从目标或名字猜测范围。

- [ ] **1.1 写失败用例。** 在子执行器现有测试中使用 `_session`、`ExchangeDailyClient`、`_rows` 和 tmp_path，
  构造显式 `frequency="1d"` 的 ContractWarmupRequest，覆盖纯 D1、缺省/混合/W1 单元和不合法参数。
  保留现有 W1 fixture 不改；新增 D1 fixture 必须由真实原生 planner 产生计划，不把 W1 字符串批量替换成 D1。
  在 TESTING 中先登记测试命令，运行确认新增用例因未支持 D1 而失败。
- [ ] **1.2 实现 prepare。** 全部 target 先验证 scope，再交 adapter 生成 source requests；
  不通过过滤 W1/metadata/continuous target 掩盖输入错误。请求与目标必须匹配 symbol、contract 和生命周期。
  保存原生全目标/hash、source request expected dates、配置/Canonical 身份和 execution digest。
- [ ] **1.3 固定身份与 policy 接口。** 定义 D1 digest 的调用范围与包内绑定，测试使用显式 fixture digest；
  W1 原 digest 算法保留。最终验证模块及依赖文件在 Task 4 落地后加入 D1 摘要并做真实代码根冻结测试，
  不创建空文件满足摘要计算，不将本任务 fixture 包作为现场 prepare 产物。
- [ ] **1.4 验证后提交。** 新增失败场景转绿，旧 W1 serialization/policy fixtures 保持原值；
  D1 的错误 scope 在 provider、projection invalidation、写入前拒绝。复核 diff 后提交这一工程单元。

核心参数拒绝测试示例（在实现新增 helper 时落入测试文件）：

```python
@pytest.mark.parametrize("value", [None, "60m", "1m", "daily", 1, ["1d"]])
def test_recovery_frequency_rejects_other_scopes(value):
    with pytest.raises(RecoveryError, match="^RECOVERY_SCOPE_INVALID$"):
        _recovery_frequency(value)
```

此示例只覆盖参数；真正安全出口依赖原生 planner、完整 target 和副作用 spy 的组合测试。

## Task 2：D1 子批执行、隔离证明与严格读回

**输入：** Task 1 的 D1 prepare schema、原生 plan 和 journal。
**输出：** `execute_prepared_batch` 可执行 D1 fixture，全部异常路径使用同一合法范围。
外部签名继续接收 manifest 和当前身份；内部 `_zero_commit_readback`、replan 按已验证 scope 构造 request。

- [ ] **2.1 添加 RED 场景。** 沿用现有 adapter、临时 SQLite/Parquet 和 journal fixture，
  spy 记录每次 `ContractWarmupRequest.frequency`，覆盖 prepare、apply、零提交证明、post-commit 和最终 replan。
  同时记录 provider、projection invalidation、writer、readback 的调用顺序。
- [ ] **2.2 串通执行路径。** 修改显式 W1 固定点：`prepare_bounded_units`、`execute_prepared_batch`、
  `_zero_commit_readback`、`_validated_unit`、`_unit_requests`、load/inspect schema 与 CLI prepare。
  D1 CLI prepare 计划新增 `--frequency`，choices 仅 1w/1d、缺省 1w；apply 从包解析，不增加覆盖开关。
- [ ] **2.3 同步领域合同。** 修改 DATA_CENTER 的普通 W1 来源隔离条款和维护 spec 对应 Requirement，
  明确新 D1 policy 的完整响应、严格整数零提交、原计划未变、独立单元和受批准 policy 约束；
  manager 遇失败停止剩余 target 的原合同不变，W1 partial-exception 专有条款不扩到 D1。
- [ ] **2.4 验证 GREEN 并提交。** 每个正常 D1 单元由 Catalog/Parquet/MDS strict-read 与零目标 replan 证明；
  既有合法前缀和 through 之后合法同月 bar 保留。异常不能造成重复写或跨频派生。

| 场景 | 必须断言 |
|---|---|
| 零提交白名单来源错误 | 所有实际开始请求均有匹配响应/hash，未变 replan，policy 明确批准才隔离；不启动未开始请求补 journal |
| 第 n 分区提交后失败 | 整单元 failed，已提交分区保留；下一单元不启动，不能成为 isolated |
| COMMIT_OUTCOME_UNKNOWN / 缺响应 | 标 unknown 并停批，不能计入未尝试或自动重试 |
| 网络、额度、锁、漂移、readback/cleanup 失败 | 停止；来源相似错误不按白名单自动放行 |
| 端点数相同但内部日期变更 | 原生 plan hash 不匹配，在所有副作用前拒绝 |
| 合法全零零成交源事实 | 维持 adapter 与 consumer 的不同结论，不造正价，不强行 data-ready |

## Task 3：D1 完整总包、自动分批和安全接续

**输入：** 新完整原生 D1 dependency-only 报告、Task 2 子执行器、固定范围与持久证据根。
**输出：** prepare 一次生成全部子包；apply 顺序执行一次正常 attempt；终态完整保留每个单元。

现有 `prepare_campaign`、`partition_ordinary_units` 新增 keyword
`recovery_frequency: RecoveryFrequency = "1w"`；报告校验和目标校验沿调用链使用此参数。
`validate_campaign_manifest` 与 `execute_campaign` 从已验证 schema 解析范围，不允许调用者重解释包。

- [ ] **3.1 建立 D1 报告 fixture 与失败用例。** 使用原生 ReadinessRequest，frequencies 仅 D1、matrix=False，
  通过真实 NewowReadinessAudit 产出报告；保留 chart/auxiliary/reference 全部枚举及 explanation 的 UNOPENED 行。
  校验完整 operational 默认集合、active/non-retired、as_of、provenance 和 required-through 的原生合并结果。
- [ ] **3.2 实现完整性校验与 prepare。** 修改 `_validated_report_targets`、`_validate_native_report_sections`、
  `_validated_target_summaries`、`_validate_native_child` 及 manifest 验证中的 W1 限定。
  缺行、重复身份、未知/未开始、预算耗尽、元数据未证实时拒绝；已明确来源异常保留原分母。
  总包绑定报告 SHA、as_of、品种/hash、consumer/window、profile、stage、全部 children/hash/顺序和身份。
- [ ] **3.3 拒绝旧 W1 导入。** D1 不接受 `--partial-source-exception-attempt`，也不调用 W1 partial importer。
  `--prior-campaign` 只接收明确同 D1 schema 的零提交隔离证据，间接 partial binding 也拒绝。
  现有 W1 source-only prepared/attempt 组合不直接用于 D1 自动排除；首版可只读复核其原始响应，
  不据此改原生 repair status 或生成隔离成功。若需要自动跨 W1 来源证据复用，另补精确绑定测试后审查，
  不使它成为 D1 普通恢复首版前置。所有非法组合在打开执行环境/调用子包前拒绝。
- [ ] **3.4 批次与终态测试。** 0、1、20、21 个普通单元分别覆盖；21 个走两个真实 native fixture 子批。
  验证批尾不丢失、单次 attempt guard、所有子包先校验、批间漂移停止、已知失败与 unknown 不混写。
  N=passed+isolated+failed+unattempted+unknown，部分分区只属于 failed 明细，不再次计数。
- [ ] **3.5 零目标路径与提交。** 0 普通目标不生成空 native 子批、不调用 provider；
  仍保留初始 already-ready 和非普通异常，进入 Task 4 只读验收。只在所有 scope/终态与旧 W1 回归通过后提交。

若 owner 在正式准备前明确缩小品种范围，必须重做完整审计、冻结该集合；首版默认 operational，
不得在报告校验或运行中静默去掉异常品种来满足完整性。子集支持不能通过放宽现有 W1 全集校验获得。

## Task 4：独立只读结算与消费者输入验收

**输入：** 冻结 campaign、原始 audit、执行终态/journal/readback，以及 Task 3 的目标集合。
**输出：** 一个完整机器结果及由该结果渲染的可读摘要；不同层面的事实互不替代。

新增模块 `scripts/newow_daily_recovery_verification.py`，以下为签名合同，不是实现代码：

```python
def verify_daily_campaign(
    *, campaign: Mapping[str, Any], execution: Mapping[str, Any],
    run_audit: Callable[[ReadinessRequest], Mapping[str, Any]],
    replan_unit: Callable[[Mapping[str, Any]], Mapping[str, Any]],
) -> dict[str, Any]

def render_daily_summary(result: Mapping[str, Any]) -> str

def main(argv: list[str] | None = None) -> int
```

以上函数体在实施时按下列步骤完成。`replan_unit` 返回原生 plan 的可序列化摘要，
含 symbol/contract/frequency/requested_through/plan_sha256、targets 和明确状态；无 provider 能力。
CLI 使用已冻结文件及 expected hashes；纯函数只在 CLI 完成证据验证后消费输入，不把传入布尔值当证据。

- [ ] **4.1 写失败用例。** 新测试使用 tmp_path、原生 reader/plan 和可注入 callbacks；
  构造执行成功而 final audit incomplete/超时/抛异常/保存失败，以及配置/根/代码不匹配。
  增加只读 session 退出恢复、零 provider、零生产写入和下游 consumer 状态传播测试。
- [ ] **4.2 组合只读进程。** 复用既有 readiness CLI 的无下载 composition、readonly transaction 和资源限制；
  使用 campaign 冻结的 as_of/品种/D1 频率执行完整审计，并对已处理单元原生 readonly replan。
  校验父包/children/hash、当前配置/根/代码与冻结身份；使用现有维护互斥及只读边界，锁忙返回待验不等待循环。
  前后身份不能证明稳定或数据发生冲突时报告漂移/待验，不声称全局快照。
- [ ] **4.3 输出三层事实。** 执行计数从原始证据验证后派生；final audit 必须独立完整。
  品种×strategy×consumer 保留原生原因：可用、缺数、来源异常、完整性问题和待审；
  比较器研究样本不足另列证据状态，不转成补数任务。public matrix 和 capabilities 不变。
- [ ] **4.4 接到 D1 apply 终态。** 父进程先保存执行终态，再通过固定 executable/离散参数启动一次只读验证子进程；
  子进程超时、失败或输出缺失返回验收未完成，不能把执行结果覆盖为未尝试。父进程不捕获 raw stack/配置到摘要。
  停批后的可证明终态可进入只读对账；提交未知仍保留 unknown，验收不能消除未知提交而重新授权 apply。
- [ ] **4.5 独立 verify 与零目标。** 后续只读复验新建唯一观察目录并绑定原 attempt/hash，不覆盖旧终态或旧验收记录；
  没有普通执行目标时允许 execution 标为 not_required，仍验证原始分母和完整 D1 audit。
  verify 不提供 apply、retry、下载或动态缩范围参数。
- [ ] **4.6 完成 D1 digest 与真实代码根冻结测试。** 将两个编排脚本、验证模块、readiness/readiness_composition、
  product_reader/product_service/product_release、实际使用的 composition 与原 native 执行依赖完整纳入 D1 digest；
  与 Task 1 的显式 fixture 身份区别记录。新增/遗漏/变更验证代码必须使冻结身份失配，在来源请求前拒绝。
  运行真实干净临时代码根上的 prepare 成功和 drift 拒绝测试；此处才验收完整 D1 prepare，仍不连接生产。
- [ ] **4.7 补比较器输入与完整回归。** 默认 comparator 复用 chart 的 reader.load、replay_bars/owners，
  核对同 as_of/owner/prefix；自定义与翻页范围不外推。跑全部受影响 recovery/readiness/native scope 测试、
  OpenSpec、secret scan、diff check 和独立 Review；通过后提交并按批准范围集成 develop。

### 机器结果必须表达的内容

| 字段/层次 | 值与解释 |
|---|---|
| schema_version | newow_daily_recovery_verification_v1 |
| inventory_complete | 指本次最终原生审计；未取得完整结果为 false，保留原始 prepare audit 另行追溯 |
| execution | 原始执行结果/hash及五类计数；执行未知不得因 final audit 完整而抹除 |
| ordinary_recovery_complete | 所有冻结普通单元均有可靠 passed 证明；isolated、failed、unattempted、unknown 任一非零为 false |
| verification_status | verified / incomplete / failed / identity_changed；不与执行状态共用 |
| input_availability | 本次品种、三策略、consumer/window 的逐项状态和原生原因；默认范围之外不声明可用 |
| provenance | 原始/最终 audit SHA、campaign SHA、attempt、as_of、代码/配置/根身份与读取时点 |

初始零普通目标时 ordinary_recovery_complete 可以为 true，但不推出输入可用。
成功隔离并走完总包称“普通恢复已结算”，不称“全部恢复完成”。
新增验证 CLI 退出约定：0=执行结算明确且普通恢复完成、完整验收且承诺的行情输入均可用；
1=执行未知/未完成、缺数/来源异常/待验/失败；2=非法输入或身份。
比较器研究证据不足本身不改变行情验收退出码，必须在可读摘要中单独披露。
旧 W1 apply/inspect 退出码不随 D1 增加而修改。

## 验证层次与本轮文档检查

实现阶段按 TESTING 的 Newow recovery、readiness、data foundation 与工程检查选择定向命令，
新模块命令随其实现进入 TESTING；不提前提供尚不存在的正式执行命令。
需要扩展的既有测试文件包括 test_recovery_partial_exception.py、test_historical_data_manager.py、
test_newow_readiness_cli.py；W1 importer 旧测试必须保持通过，D1 不继承该 importer。
源码 fixture 验证无生产配置/数据连接，独立测试过程的 provider 必须为 fake 或拒绝调用的 spy。

本轮只验证文档链接、格式、secret scan、OpenSpec 与适用工程检查，实际结果记录到 review.md。
已知基线工程失败不通过修改模型配置、删除无关计划或降低测试断言消除。

## 工程后操作清单：必须重新取得精确执行意图

以下不是 Task 1–4 的自动尾步骤，未获授权时停止在准备就绪状态。

1. **现场只读审计和 prepare：** 确认 W1 attempt 终态、writer/自然维护时窗；使用共享写入结束后的新 D1 audit。
   冻结 as_of、品种/consumer/window、代码、配置、根、批次/目标 hashes、policy、资源上限和持久证据根。
   实测缺口数和批次数；不能引用旧 W1 成功数，不能承诺尚未测量的耗时。
2. **一次 D1 apply：** owner 明确批准该总包后进行 preflight，正常批次连续；失败或未知停止。
   前面合法分区保留，新执行必须重审余额并取得新意图，不做整包 rollback 或自动续跑。
3. **数据验收：** 固定 as_of 独立复核；报告全部异常和未尝试，不用页面开关制造通过。
4. **后续产品任务：** 三策略 D1 的 service/API/Web、参考交易、比较器、旧链接/偏好和 W1 回归单独验收；
   W1、D1 按既有次序收口，main/tag/release、Runtime promotion 各自批准。60m 与完整解释仍未开放。

## 自审与后续入口

Task 1–4 覆盖 design 第 4–9 节；四项补充分别落在 Task 2 合同、Task 3 导入拒绝、Task 4 最终失败与比较器验证。
整合约预取、跨 W1 自动证据导入和通用后台平台均不是前置。
本次文档提交后，唯一下一步是 owner 审阅并批准此计划的代码实施范围；不要自动进入现场操作。
