# Unified Reference Trading Implementation Plan

> **For agentic workers:** 使用 superpowers:executing-plans 按本计划逐项执行；若 owner 明确选择分派，再采用 superpowers:subagent-driven-development。步骤完成后以实际证据勾选，不因计划存在视为已实现。

**Goal:** 为牛哇、苏冰及 HTDY 建立统一参考交易存储、历史增量、盘中观察与查询能力，保留各策略公式和历史/观察区别。

**Architecture:** 纯策略适配与 Reference Reducer 输出确定性结果；应用模块通过现有 PostgreSQL 原子保存批次、检查点、动作、交易与估值。后台 worker 推进明确启用的流，API 只查询，Alert 独立。

**Tech Stack:** 现有 Python/Decimal、SQLAlchemy/Alembic/PostgreSQL、FastAPI、Vue/TypeScript；无新消息中间件、数据库或服务框架。

**Spec:** [统一参考交易详细设计](../specs/2026-09-19-unified-reference-trading-design.md)，以下章节号指该文档。

初稿只产出设计与开发步骤。2026-09-19 owner 要求细化 P0/P1 并安排 Terra Medium 独立任务开发，
因此当前授权执行范围为 P0/P1；P2–P9 仍为后续计划。命令是验证入口，不是已执行的测试声明。

## Global Constraints

- `executable=false`、`auto_order=false`；行情仍为 RQData -> Canonical -> Catalog/MDS。
- `historical_replay` 与 `forward_observation` 是不同 stream；不拼接收益、不补造 first_seen。
- 老策略 source signal/trade ID、公式、参考价格和统计语义保持；新模型独立版本。
- HTDY具体模型未接受则 `MODEL_NOT_APPROVED`，不影响牛哇/苏冰；不新增重绘历史交易收益。
- GET 不完整 replay、不写库、不下载、不启用流；写入与 checkpoint/水位原子提交。
- 新 schema、生产构建、enable、发布与 Runtime 按 AGENTS.md 的明确批次授权执行。
- 当前四周期苏冰及其他周期开放任务必须先检查实际集成依赖，不能从旧 HEAD 开始覆盖其工作。

## Review Focus

- 任意过去截止不能看见未来 exit/mark：P3、P5 验证版本查询与统计。
- EMA 修订影响超出最近窗口：P2、P4 验证从有效 checkpoint 到最新的尾部重算。
- 无信号 Bar 或旧 owner 迟到不能丢进度/污染新状态：P2、P6 验证。
- 首次启用、停机和 HTDY重绘不能补造当时观察：P6、P7 验证。
- 候选构建时 Canonical 修订、提交结果未知不能混代或重复：P3、P4、P8 验证。

## 文件归属与接口

拟新增纯域目录 `packages/quant-core/guiyi_quant/reference_trading/`：
`contracts.py`（类型/身份）、`reducer.py`（纯状态迁移）、`adapters.py`（策略适配注册与接口）。
策略具体算法继续放原策略目录，避免搬动无关指标；新 HTDY 模型可放 `reference_trading/htdy.py`。

拟新增应用目录 `services/quant-api/app/reference_trading/`：
`models.py`、`repository.py`、`service.py`、`query.py`、`inputs.py`、`runtime.py`、`composition.py`。
职责依次为 schema 映射、事务、构建/增量编排、只读查询、既有 reader 组合、调度、依赖装配。
`inputs.py` 不实现新的 rank1/Session/coverage resolver。

拟新增 `services/quant-api/app/api/reference_trading.py`、`app/schemas/reference_trading.py`、
`app/guiyi_cli/reference_commands.py`；复用现有 API/router/CLI 注册。
拟新增 Web `src/api/referenceTrading.ts`、`src/types/referenceTrading.ts`、`src/composables/useReferenceTrading.ts`、
`src/components/market/detail/reference/ReferenceTradePanel.vue`；原策略 workspace 保留自身图表及解释。

类型合同（在 P1 实现，非当前已存在代码）：

```python
@dataclass(frozen=True)
class StreamIdentity:
    strategy_code: str
    formula_versions: tuple[str, ...]
    profile_id: str
    reference_model_version: str
    futures_adaptation_version: str
    product: str
    frequency: str
    series_kind: str
    recording_mode: str
    observation_policy_version: str

class StrategyAdapter(Protocol):
    def seed(self, identity: StreamIdentity, inputs: ValidatedInputBatch) -> StrategyState: ...
    def advance(self, state: StrategyState, inputs: ValidatedInputBatch) -> StrategyTransition: ...

def reduce_reference(state: ReferenceState, transition: StrategyTransition) -> ReferenceTransition: ...

class ReferenceRepository(Protocol):
    def load_checkpoint(self, stream_id: str) -> Checkpoint: ...
    def commit_batch(self, expected: Checkpoint, batch: PreparedBatch) -> CommitResult: ...
    def publish_revision(self, stream_id: str, revision_id: str, expected_version: int) -> None: ...

class ReferenceService:
    def build(self, request: BuildRequest) -> BuildResult: ...
    def advance(self, stream_id: str, target: InputTarget) -> CommitResult: ...

class ReferenceQuery:
    def trades(self, query: TradeQuery) -> TradePage: ...
    def signals(self, query: SignalQuery) -> SignalPage: ...
    def summary(self, query: SummaryQuery) -> ReferenceSummary: ...
```

P1 只实现下列类型中纯域迁移实际需要的部分；应用 DTO 和仓储接口在 P3/P4/P5 实现，不生成空壳实现。
类型目标内容：`ValidatedInputBatch` 包含 source/mode、物理 Bar 序列、owner/calculation segments、质量边界、observed_at 与 dependency manifest；
`StrategyState` 包含 schema/version/hash 与完整指标状态；`StrategyTransition` 包含有序动作、末状态和估值输入；
`ReferenceState/Transition` 包含 OPEN 关联及交易变化，不含 IO；`Checkpoint` 包含 revision/seq/row_version、状态与水位；
`PreparedBatch` 包含 checkpoint 前提、输入证据、actions/trades/marks 与末水位；`CommitResult` 为 committed/noop/conflict。
`BuildRequest` 包含固定 stream 清单、日期、cutoff、dependency hash、budget 和 dry_run；`BuildResult` 逐流汇报，不隐去失败。
`InputTarget` 是来源确认的目标截点而非墙钟 now；查询类型含 stream、显式窗口、snapshot、分页 limit/cursor。
所有运行时加载的状态严格校验 schema/version；禁止 pickle 或任意对象反序列化。

## P0：冻结合同和实施基线

依赖：无。覆盖设计 §1–5、§14。

文件：新增 `openspec/specs/reference-trading/spec.md`；按接受范围修订 `PROJECT_SOURCE.md`、`DECISIONS.md` 和相关 Newow/SuBing canonical。
尚未实现的能力写 proposed/planned，不提前把 ARCHITECTURE/STATUS 描述成 active。

- [ ] 重新核对 branch/HEAD/dirty/worktrees、四周期苏冰依赖、Newow capability、Alembic 唯一 head。
- [ ] 固定 identity、两种模式、统计、状态、输入/输出和禁用默认；明确 HTDY v1 是否接受，不允许工程师自行决定。
- [ ] 写出首批 capability 矩阵：策略×周期×historical/forward；代码支持、已验、已启用分列。
- [ ] 将上述设计合同映射为 OpenSpec 场景：正常、缺口、重绘、停机、修订、并发和查询快照。
- [ ] 对照现有 golden 确定兼容字段与明确新增字段，完成文档 diff/引用检查。

出口：无隐藏业务决策；计划可以按模式/策略独立推进，未接受 HTDY 保持禁止生成交易。

## P1：纯域合同和通用状态迁移

依赖：P0。覆盖设计 §4–5、§9。

文件：新纯域 contracts/reducer/adapters；新增 `services/quant-api/tests/reference_trading/test_contracts.py`、`test_reducer.py`。

- [ ] 先写身份隔离、同 Bar 反手、同向信号、明确配对、中断、无入场 CLEAR、Hint 无仓位效果的失败测试；启用时 HOLD 后的 CLEAR 只记 NO_OBSERVED_ENTRY，不伪造完整生命周期初始 CLEAR。
- [ ] 实现上文类型与 Decimal wire 合同；拒绝非法 enum、日期、非有限价格、重复 sequence、跨 segment/版本关联。
- [ ] 实现 reducer；OPEN->CLOSED 必须指定 entry 身份，中断没有虚构 exit/return。
- [ ] 新状态 `OBSERVATION_INTERRUPTED` 只用于 forward，原历史状态和版本不变。
- [ ] 定向测试、自审、diff check；按任务文件提交，不包含其他任务修改。

接口出口：`reduce_reference` 无 DB/Redis/provider 依赖；同输入确定性；不同周期/模式不会碰撞。

## P2：苏冰与牛哇适配、全量/增量统一

依赖：P1。覆盖设计 §2、§4、§7、§10.1。

文件：原 `subing_reference.py`、`newow/reference_trades.py`、`newow/product_adapters.py` 及相应指标状态入口；
新增 `tests/reference_trading/test_strategy_parity.py`、`test_checkpoint_parity.py`。

- [ ] 固定现有苏冰四周期、牛哇三策略真实实现 golden，记录现有 ID/价格/收益/Hint/期初归属。
- [ ] 将旧全量入口改为同一 transition 的 fold；测试和正式实现不复制一套公式。
- [ ] 提供状态 schema、seed/advance；窗口型算法明确完整回看需求，不能随意截取预热。
- [ ] 对同一有效输入验证全量、单 Bar、随机切批、序列化重启一致；增加无信号推进和 34/35 Bar 等实际预热边界。
- [ ] 验证 old/new owner、D1缺价、同 Bar 多动作、完整生命周期初始 CLEAR 与各统计窗口兼容。

核心测试形态（由具体 fixture 提供 `bars` 与原实现输出）：

```python
expected = legacy_projection(bars)
actual = replay_with_checkpoints(bars, batch_sizes=[1, 7, 2, 31])
assert actual.actions == expected.actions
assert actual.trades == expected.trades
assert actual.summary == expected.summary
assert resume_after_serialization(bars) == actual
```

出口：历史兼容；正常新增数据不重新回放无界历史前缀。若算法仍需全历史回放，不以“已经落盘”宣称增量完成。

## P3：数据库、原子批次与快照仓储

依赖：P1，可与 P2 的策略适配独立实施；集成前接口一致。覆盖设计 §6、§8。

文件：应用 models/repository；新增 Alembic revision（编号根据实施时唯一 head 分配，不硬写 0046）；
新增 `tests/reference_trading/test_repository.py`、`test_repository_postgresql.py`、`tests/alembic/test_reference_trading_migration.py`。

- [ ] 建立六张新表、NUMERIC、必要索引、复合外键、唯一键、状态和序号校验；默认无 enabled 流。
- [ ] 编写隔离 PG 行锁/CAS、两 writer、同 batch 重放、同 ID 内容冲突、事务回滚、提交未知读回测试。
- [ ] 实现 candidate 发布、trade validity interval 和 marks 截止查询；普通 Bar 不复制全部交易；forward 投影重建引用原动作而非复制观察事实。
- [ ] 实现 durable batch evidence/checkpoint 分块、启动状态版本校验；测试残缺初始化不能激活。
- [ ] 在专用可销毁 PG 验证迁移与 schema 兼容，禁止用生产 URL；缺 PG 时报告未完成，不能以 SQLite 代替。

出口：提交全有或全无；历史快照可重复读；进程 crash 后无重复交易和水位跳跃。

## P4：历史构建、增量、修订与 CLI

依赖：P2、P3。覆盖设计 §7、§10.2、§10.4。

文件：应用 inputs/service/composition；新 CLI reference_commands 及现有 main 注册；
新增 `tests/reference_trading/test_bootstrap.py`、`test_historical_incremental.py`、`test_revision_rebuild.py`、`test_reference_cli.py`。

- [ ] 组合既有 MDS/readers，实现只读 plan/dry-run：精确 streams、日期/预热、目标输入、预计批次和预算。
- [ ] 实现受明确范围约束的 build/resume；分块 candidate 对用户不可见，全部校验后发布。
- [ ] 新 Canonical 到达只处理缺少的尾部；每次验证历史依赖，修订从有效检查点重算到最新。
- [ ] 测试预热修订、EMA 长尾、源发布中途变化、单流失败其他流成功、重启恢复、无信号新增日。
- [ ] dry-run 不写 DB、不调用 provider；apply 不扩大 plan；报告包含 failed/blocked 明细。

出口：牛哇/苏冰历史结果可提前保存并持续增量；源漂移不能发布混代结果；无生产操作。

## P5：统一只读接口与 Web 迁移

依赖：P4。覆盖设计 §11。

文件：新 API/schema/query、Web 公共类型/api/composable/panel；
修改 `app/market_data/newow/product_service.py`、`app/market_data/subing_reference.py`、相应策略 workspace。
新增 `tests/reference_trading/test_query.py`、`test_api.py`、Web `tests/referenceTrading.test.ts`、`tests/useReferenceTrading.test.ts`。

- [ ] 实现设计 §11 五类 GET；snapshot 绑定所有身份/窗口；禁用、未构建、无交易、滞后、失效各自展示。
- [ ] 让旧 reference 入口作为薄适配读统一查询，最终移除重复 HTTP 计算分支；图表/auxiliary 不扩大改动。
- [ ] 测试翻页时平仓、换 revision、伪造 token、过去截止、期初交易、无可用 mark、不跨模式总计；forward 同时约束 Bar 和 observed_at，不让迟到观察泄漏到过去。
- [ ] 查询测试将策略 replay 替换为会抛错的 spy，确认访问/刷新/分页完全不调用 replay。
- [ ] Web 验证切换策略/周期、请求取消、来源/截止、Alert 精确定位与交易缺失提示；统计与列表同快照。

出口：页面只查保存结果；不通过 silent fallback 隐藏后台失败；旧公式/统计展示兼容。

## P6：盘中 worker、数据完整性与断线恢复

依赖：P2、P3、P5。覆盖设计 §8–10、§12。

文件：应用 inputs/runtime/composition、现有 Live reader/Session clock 的必要公共调用点、
`app/market_data/after_market.py`（只增加轻量唤醒组合）、部署与 health 注册。
新增 `tests/reference_trading/test_runtime.py`、`test_live_inputs.py`、`test_observation_recovery.py`、`test_after_market_reconcile.py`。

- [ ] 默认 disabled 单 worker，scope 与 Alert 独立；实现有界唤醒与持久进度扫描，不把 Pub/Sub 当队列事实。
- [ ] 按 period 完成条件调度；分钟完整输入、夜盘/午休/短桶、D1/W1来源不足均独立测试。
- [ ] 持久保存实际观察输入与时间后原子推进交易；失败不发送通知，不影响 Alert 既有 one-shot 合同。
- [ ] 测试停机：有耐久输入的恢复保持 observed_at；未捕获区间不补 first_seen，默认阻塞并保留 gap。
- [ ] 实现经明确恢复策略授权后的 OBSERVATION_INTERRUPTED/重新预热/FLAT 新起点；不携入旧历史 OPEN。
- [ ] 盘后核对相同与冲突两路；原观察不改，历史另 revision；更新失败与 Market 成功分开报告。

出口：隔离 Runtime 验证通过；未自然启用、未创建生产 Scope、未发送通知。D1/W1 缺合同的 forward capability 保持 unavailable。

## P7：HTDY first_seen 参考适配

依赖：P0具体模型接受、P6。覆盖设计 §3.3、§10。

文件：新纯域 HTDY 适配；复用 `app/alerts/evaluators.py` 中纯评价规则及原 Kernel；
如需抽取，双方调用同一个纯入口，不复制 first_seen 政策。
新增 `tests/reference_trading/test_htdy_observation_model.py`、`test_htdy_repainting_boundary.py`。

- [ ] 实现独立 model/version：buy 开多、sell 开空、同向忽略、反向 Close 配对；未接受模型负向测试。
- [ ] 两方向冲突保存诊断并阻塞，valid watermark 不越过冲突，不猜动作顺序。
- [ ] 扩展未来 Bar 导致旧信号消失/变向时，原 observed actions 不变；不与最终 retrospective 曲线比较。
- [ ] 默认不导入旧 AlertEvent、不生成历史回看收益；输入证据和恢复后的重复信号幂等。
- [ ] Web 显示“首次观察参考 / 启用时间 / observation-only”，不显示虚构启用前交易。

出口：HTDY共用存储和查询，独立正确语义；模型批准与生产启用分开。

## P8：独立审查、资源验收与候选交付

依赖：P1–P7（HTDY未接受时明确标出排除范围，不能报全部完成）。覆盖设计 §12–13。

文件：上述定向测试、相关 canonical、`TESTING.md`、部署文档；新增必要性能测试，不堆重复报告。

- [ ] 定向测试通过后运行策略、DB、API/Web、Runtime/Alert 必要回归；golden 不因迁移重录掩盖差异。
- [ ] 专用 PG/Redis 验证并发和恢复；API/Web真实隔离预览验证来源身份和切换。
- [ ] 记录单流/60品种/多策略容量、查询 p50/p95、增量延迟、内存、写入增长和全量修订耗时，确定预算。
- [ ] 数据时序、公式、并发、迁移由独立 reviewer 审查；修复 Confirmed Issue 后再集成。
- [ ] 完成 develop 集成与候选文档；准确区分 code/test/review 与尚未执行的外部 Gate。

出口：release candidate 工程条件明确，不等于生产数据库已迁移或盘中已运行。

## P9：生产迁移、构建、切换与自然验收

依赖：P8及精确生产批次授权。无授权时停留在候选，不阻塞已授权的普通开发。

- [ ] 只读盘点 exact code、schema、数据依赖、策略周期矩阵、目标主机和可恢复旧版。
- [ ] 提交一次性批次范围：schema、新增表、历史 streams/日期、输入预算、失败/恢复边界、发布与 Runtime 项分别列明。
- [ ] 按授权迁移空表、构建 candidate、逐流对照、发布结果；失败流保持未切换，绝不伪造零交易。
- [ ] 切换查询并读回；单独明确 forward scope/start/model 后启用 worker，不改变 Alert 收件与周期。
- [ ] 验证自然 completed Bar、无信号推进、真实新信号配对、重启、盘后核对；未发生场景保持待验。
- [ ] 回滚演练先停写、保留证据/表/水位，不用 schema downgrade 删除观察事实。

出口：已批准组合逐项达到自然运行证据；未批准/未具备数据/未发生场景分别列出，不泛称全策略全周期上线。

## 验证命令模板

仅在相应新文件已创建后执行，先用 `rg --files` 确认。开发测试不得读取生产 `.env`。

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q -p no:cacheprovider --tb=short \
  services/quant-api/tests/reference_trading

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q -p no:cacheprovider --tb=short \
  services/quant-api/tests/test_subing_reference_projection.py \
  services/quant-api/tests/test_subing_reference_service.py \
  services/quant-api/tests/newow/test_reference_trades.py \
  services/quant-api/tests/newow/test_reference_interruptions.py \
  services/quant-api/tests/newow/test_reference_statistics.py \
  services/quant-api/tests/newow/test_product_replay_invariants.py

pnpm_config_verify_deps_before_run=false pnpm -C apps/quant-web exec node --test \
  tests/referenceTrading.test.ts tests/useReferenceTrading.test.ts

git diff --check
```

PG migration/transaction 测试遵循 `TESTING.md` 的专用可销毁库与 URL guard；Redis 按同文档专用非生产端口执行。
缺隔离依赖的 skip 是待验，不是通过；不得临时连接生产库“补测试”。

## 依赖与自审覆盖

```text
P0 -> P1 -> P2 --------+
          +-> P3 -----+-> P4 -> P5 -> P6 -> P7 -> P8 -> P9
```

P2/P3 可以在接口冻结后独立开发；触碰同一公式/共享 reader 时合并处理，生产操作始终按共享状态串行。
§1–5 -> P0/P1/P2；§6/8 -> P3/P6；§7 -> P4；§9/10 -> P2/P4/P6/P7；§11 -> P5；§12/13 -> P8/P9；§14 -> P0/P7。
最小首个可用交付是 P0–P5：牛哇与苏冰持久化历史查询。完整目标还包括 P6/P7 的盘中链和 P9 的实际启用验收。

## P0/P1 本次执行细化（2026-09-19）

### 授权与基线

owner 指定一个 `gpt-5.6-terra`、`medium` 独立开发任务。主树调查 HEAD 为
`f5744d32466149561f029361a6b73fadc60033ba`；本设计/总计划当时是本任务生成的未跟踪文件。
新任务须先从下述主树绝对路径读取并复制这两份文档至自己的 task worktree，核对内容，再将其纳入自己的精确提交。
不得遗漏未提交设计，也不得全量复制主树或清理其中的文件。

```text
/Volumes/扩展盘/guiyi-quant-workstation/docs/superpowers/specs/2026-09-19-unified-reference-trading-design.md
/Volumes/扩展盘/guiyi-quant-workstation/docs/superpowers/plans/2026-09-19-unified-reference-trading-plan.md
```

新 worktree 默认起点可能不是 develop；执行者先核对并以最新已验证 develop 创建 `codex/` 任务分支，保留已有修改。
若 develop 已有重叠实现，先核对吸收，不能以本计划旧 HEAD 回退其他任务。

### 本次范围

- P0：新增公共 canonical；记录已有能力矩阵、兼容身份、两种记录模式、默认禁用及不可混淆的状态。
- P1：实现纯域 contracts / identity / reducer / 必要的 adapter Protocol 和直接定向测试。
- 不实现具体策略 adapter、不改现有 projector 调用链，不做数据库模型/迁移、worker、API/Web、生产数据或通知操作。
- HTDY新模型保持 proposed + MODEL_NOT_APPROVED；不把本次基础模块开发要求解读为批准 HTDY具体收益语义。
- P0 可以完成公共合同冻结，HTDY模型另列为 P7 前置决策，不让它阻塞公共基础开发。
- 普通 commit/push、验证及独立 Review 通过后的 develop 集成在任务范围内；不做 main/tag/release 或 Runtime。

### 第一步：取证并完成 P0

1. 检查 AGENTS、STATUS、当前 worktree/HEAD/dirty、develop依赖和 Alembic head（只读），不读取凭据。
2. 阅读 Newow/苏冰 projector、identity、statistics、相关 golden，以及 HTDY first_seen合同。
3. 从实际代码生成静态文档矩阵：策略×周期×模式，区分已有实现、待适配、已验证、未知运行状态；不推导生产 enabled。
4. 建立新 OpenSpec；每个 SHALL 配 Given/When/Then 场景。已有 canonical 只增加公共模块关系与不变约束，不批量重写原策略规则。
5. PROJECT_SOURCE/DECISIONS 只记录已接受的公共基础设计；持久化/运行能力仍是 planned，STATUS 不提前报整体完成。
6. 检查场景覆盖：跨周期/版本隔离、精确配对、无入场动作、换月/缺价/观察中断、无信号推进、同 Bar 顺序、重复/冲突输入。

P0出口：canonical 可指导 P1，P2之后的合同有明确阶段归属；HTDY不确定项已安全隔离，无需反复询问 owner 才能写基础模块。

### 第二步：P1 公共类型与身份

核心文件允许按规模拆为 `contracts.py`、`identity.py`、`reducer.py`、`adapters.py`、`__init__.py`。
只创建实际使用文件，不创建 application/storage 空壳。

- 强类型：recording mode、action kind、side、trade status、boundary reason。
- `StreamIdentity`：沿本计划字段；canonical serialization/hash 不依赖字典插入顺序或 Python进程 hash。
- `ReferenceAction`：stream、source signal/action ID、物理合约、owner/calculation segment、Bar/交易日、sequence、参考价/价型、显式 entry关联。
- `ReferenceBoundary`：以权威输入给出的换月/已证明缺价/观察中断推进，不自行识别市场缺口或主力。
- `ReferenceState`：所属流、最后有效输入位置、当前 OPEN及必要配对状态；不保存无限长历史列表作为每步状态。
- `StrategyTransition`：确定顺序的动作/边界、完成 Bar 的估值与计龄输入；空动作 Bar 仍能推进。
- `ReferenceTransition`：新状态、已变化交易、估值、诊断；参数不可变，错误时原状态不改变。
- `StrategyAdapter` 只定义 seed/advance纯接口；真实苏冰/牛哇接入保留给 P2。

持久 JSON checkpoint codec属于后续真实适配/仓储；P1 只固定版本字段和稳定 wire/身份所需序列化。
所有时间带时区，内部统一 instant；trading_day必须由输入提供，不从 bar_end.date() 推算。
Decimal拒绝 float暗转、NaN、Infinity及不符合现有价格合同的值；继承原公式精度/舍入政策，不顺手更改收益语义。

### 第三步：P1 reducer 精确行为

| 输入 | 输出与拒绝条件 |
|---|---|
| FLAT + OPEN | 建立有唯一entry关联的OPEN；保留源ID，通用身份外包stream namespace |
| OPEN + CLOSE | 必须明确关联当前entry且流/合约/段/版本一致，按给定参考价产生CLOSED |
| 同Bar反手 | CLOSE和OPEN有严格sequence，原子计算整次transition，不接受倒序或缺失关闭关联 |
| 已OPEN再次OPEN | 未经策略适配规范化的重复开仓拒绝；同向忽略由适配输出无动作，不能让公共层偷偷加仓 |
| HINT | 不改变OPEN/CLOSED或收益，不伪造减仓 |
| 无入场CLEAR | 保留源动作并输出诊断；forward的NO_OBSERVED_ENTRY不能冒充牛哇生命周期初始CLEAR |
| 无信号完成Bar | 推进水位，按权威有效Bar计龄并更新OPEN估值，不能按墙钟间隔估算holding_bars |
| 换月/已证明缺价 | 生成对应中断状态；不填exit_reference_price/exit_return，不跨段继承OPEN |
| 观察中断 | 仅forward允许OBSERVATION_INTERRUPTED，历史模式拒绝；新段默认FLAT |
| 旧owner/跨流/倒序/同身份不同内容 | 类型化错误，原状态不变，不能静默覆盖或跳过 |

输入幂等分层：P1验证同一次transition内的重复/冲突和相同最后输入的精确重放；
P3才承担跨进程、任意历史批次的耐久去重。P1不得为了伪装数据库幂等维护无限增长的已处理ID集合。
一笔交易的实际收益与未平参考收益分开；短头收益方向、零成本、计龄和中断null语义须有数值例子。

### 第四步：测试顺序和独立审查

新增 `tests/reference_trading/test_contracts.py`、`test_reducer.py`；必要时独立 `test_identity.py`。
先针对行为写失败测试，再实现；至少覆盖以下矩阵：

1. 模式/周期/策略/版本/物理段不同导致身份隔离；字典顺序不影响稳定hash。
2. 多头100->110收益+10%，空头100->90收益+10%；反向亏损；拒绝float/非有限/非法价格。
3. CLOSE错误entry、不同owner、同Bar倒序/重复sequence、Hint不能改变交易。
4. 无信号Bar仍推进且正确计龄；缺价/换月/观察中断没有虚构平仓价或已实现收益。
5. 启用处于HOLD后CLEAR只有NO_OBSERVED_ENTRY；原INITIAL_CLEAR生命周期证明不放宽。
6. 相同末输入重放结果不重复，相同身份不同内容拒绝；晚到旧输入不让状态倒退。
7. 整批与逐项合法切批的reducer结果一致；错误发生在批次中间时调用方原状态完整保留。
8. 无网络、无DB、无Redis、无时钟now或随机ID依赖；原策略回归结果保持。

运行新目录定向pytest，再执行已有苏冰/Newow参考投影与统计相关回归；按实际文件运行Ruff、OpenSpec校验、secret scan及diff check。
新公共纯模块不触发无关Web build或生产连接。独立review重点审查时间因果、原子纯迁移、身份、精度及范围越界。
发现问题由同一任务修复重测，不停在“已写代码”。测试/独立Review通过后精确提交、push并按当前仓库流程集成develop。
集成存在并发冲突时先保留各方改动并解决；不使用force push或覆盖主树未提交文件。

### 本次交付报告

列出P0/P1完成项、实际命令与结果、Review结论、提交/集成身份和剩余边界。
明确P2策略适配、P3数据库、P4持久构建、P5页面、P6/P7盘中接入均未实现；不得把纯域完成表述为“参考交易已开始持续记录”。
