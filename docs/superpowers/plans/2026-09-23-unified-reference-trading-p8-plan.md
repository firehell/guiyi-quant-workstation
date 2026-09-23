# Unified Reference Trading P8 Implementation Plan

> 执行方式：superpowers:executing-plans；新任务 GPT-6 Sol / medium。完成验收工具、必要缺陷修复、测试、独立 Review 和满足条件的 develop 集成，不执行 P9。

**Goal:** 对 P0–P7 统一参考交易形成绑定精确提交的组合正确性、故障恢复、性能和页面证据，给出可审查的候选结论与 P9 剩余 Gate。

**Architecture:** 复用现有计算、仓储、historical/forward service、worker 和 API/Web；增加小型可复现验收入口与必要集成测试，不另建框架或第二套计算规则。

**Tech Stack:** 现有 Python/pytest、SQLAlchemy/PostgreSQL、Redis、FastAPI、Vue/Node/Playwright；使用专用可销毁实例与临时 Canonical/Catalog。

**Spec:** `openspec/specs/reference-trading/spec.md`；总体计划 `docs/superpowers/plans/2026-09-19-unified-reference-trading-plan.md` 的 P8；P6/P7细化计划 `docs/superpowers/plans/2026-09-23-unified-reference-trading-p6-p7-plan.md`。

## 1. 实际基线与范围

调查于 2026-09-23：develop `636d70059466b6ab9089b8627afdf817331d2de3`，已包含 P6/P7 `f3dd94eda`、隔离输入验证 `ee55815d3`。
STATUS 报告正式 v1.10.28，但 forward canonical 仍是默认关闭候选；不能把发布版本、代码能力、生产已启用混为一谈。
主工作树 CJ/OI 周线计划与 outputs 为其他任务未提交文件，不覆盖、不清理、不全量暂存。
实施开始重新核对 HEAD/worktrees/dirty、依赖和 migration head；在独立 codex/ 工作树从最新 develop 推进。

P8开发包括：补齐有实际缺口的组合测试、隔离真实服务验收、性能脚本、必要根因修复、独立Review、文档和候选证据。
不重做P0–P7，不新增策略/周期/业务模型，不制造固定finding数量；既有有效测试直接复用。
不执行真实provider下载、生产DB/Redis/Canonical写入、模型正式接受、Scope/reader切换、真实通知、服务安装启动、main/tag/release/Runtime promotion。
隔离临时服务和测试数据库允许；不得读取生产.env借用现役端口或卷。P9授权不由这份计划推导。

## Global Constraints

- `executable=false / auto_order=false`，历史与forward身份、统计、观察时间严格隔离。
- 未确认Bar不进入记录；物理合约/Session/quality/owner不明失败关闭；HTDY仅既有32 Bar latest-only first_seen候选。
- 公式、参考价格与收益不因修复测试而改变；若确实需要业务变化，仅暂停受影响部分说明决策项。
- GET零策略回放、零写入、零provider；capture/交易/checkpoint/水位遵守既有原子性与幂等合同。
- 测试fixture、隔离真实依赖、生产只读、自然运行证据分别标记；skip不是通过。
- P8通过仅证明候选工程质量，不批准HTDY模型或P9生产动作。

## Review Focus

1. disable/activation与在途capture/commit竞态：不得让旧generation在禁用后写入（T2）。
2. 历史截止同时受Bar和observed_at影响：迟到观察、mark、中断不泄漏到过去（T1/T3）。
3. 模拟进程退出或未知提交结果：只读核对后不重不漏，不自动补造first_seen（T2）。
4. 历史修订、owner/Session变化：旧snapshot不得混入新事实，不能只看Close判断未修订（T1）。
5. 多品种大窗口：分页不能全量扫描/全历史回放，慢流不能饿死其他流，错误路径不能无界重试（T4）。

## 2. 一份验收矩阵与一份结果

新增简短验收说明 `docs/tasks/unified-reference-trading-p8/acceptance.md`，最终只维护这一份汇总，避免重复report/receipt。
机器结果放任务输出目录，不提交大体积数据库、行情快照、截图集或凭据。
每条结果记录：case_id、层级、策略/周期/模式、source fixture/hash、expected、actual、命令、exit code、pass/fail/skip/blocked、code SHA、环境指纹。
最终汇总保留测试总数/失败/跳过与原因、性能数字、独立Review引用、外部Gate。
文档滞后可以修正；只能按证据更新STATUS，不能把工程完成改成生产ready。

### 必验维度

| 组 | 内容 | 实际证据 |
|---|---|---|
| Historical | 苏冰四周期、牛哇当前代码支持组合；build/resume/advance/rebuild、旧ID/价格/统计一致 | 临时Canonical/Catalog/MDS+真实P4+PG+查询 |
| Forward | 苏冰/Newow已支持组合、HTDY候选；FLAT seed、无信号推进、开平/反手/同向、mark | 实际capture/service/repository/worker组合 |
| Futures | 夜盘跨日、节假日、午休、短桶、主力切换及再进入、质量中断、未知缺口 | 权威Session/owner fixture；非法输入负向验证 |
| Time/version | 全量/随机切批/重启一致、源修订、旧snapshot分页、未来exit/observed_at过滤 | 精确字段与身份断言 |
| Isolation | 未接受HTDY/disabled拒绝、不同mode token拒绝、GET不写入、不创建AlertEvent/transport | DB前后读回与依赖spy；不是仅检查配置值 |
| External stores | NUMERIC、FK/唯一键、行锁、CAS、migration、Redis真实读取 | 专用一次性PG/Redis，非SQLite替代 |
| Web | 两模式、列表/统计/指标同快照、过去截止、分页、错误/缺数据/未启用 | 独立API/Web与真实保存结果，无route拦截替代业务链 |

产品未开放的组合可以做隔离fixture验证，但必须写fixture-only；不能据此扩大正式capability。
每个canonical Requirement至少映射到一个已存在或新增测试；先映射再补缺口，不机械新增同义测试。

## 3. T0：盘点与固定基准

文件：上述acceptance文档、现有TESTING.md、测试清单。
- [ ] 重新核对代码/产品capability、0047及后续migration、P6/P7实际能力；不直接沿用旧聊天测试数。
- [ ] 将canonical映射到现有tests/reference_trading、alembic、Alert/Live及Web测试；列真正缺口。
- [ ] 在未修改基线跑与缺口相关的现有组；若失败先固定基线复现，区别既有问题和新回归。
- [ ] 固定隔离目录/端口/库名guard、schema、依赖版本、fixture seed/hash、样本规模与资源预算。

出口：明确此次需新增/修复项；没有以全仓测试代替范围判断，也没有把P9待办算作P8代码失败。

## 4. T1：端到端数据与语义闭环

新增 `services/quant-api/tests/reference_trading/test_acceptance_pipeline.py`；复用现有fixture和driver，不复制实现。
- [ ] Historical：临时Canonical/Catalog/MDS -> plan/build -> persisted API -> 追加 -> 旧snapshot/new snapshot -> 修订拒绝/受控重建。
- [ ] Forward：完整seed -> 隔离activation -> typed Live输入 -> durable capture -> worker -> PG -> API，覆盖无信号和反手。
- [ ] 校验source action/trade身份、Decimal、OPEN mark、过去截止、输入hash和presentation，不能只断言HTTP200。
- [ ] HTDY逐次真实窗口观察后追加未来Bar，验证原动作不因重绘改写；不将最终回看结果作为first_seen预期。
- [ ] 检查通知/AlertEvent零副作用；历史与forward不能共享OPEN或曲线。

出口：计算、持久化和查询接成同一条链；新输入确实能在新快照读到，旧快照仍稳定。

## 5. T2：真实隔离存储与故障恢复

新增 `tests/reference_trading/test_acceptance_recovery_postgresql.py`，优先扩展已有真实PG tests；migration测试复用现有入口。
- [ ] 先证明空白可销毁库及非生产端口/卷，运行已有migration guards；原已发布migration不可改写。
- [ ] 用线程/进程同步屏障构造确定性交错：capture后退出、提交前回滚、commit成功但调用方未收到、disable抢先提交、两writer同批。
- [ ] 重开连接/服务读回batch、generation、seq、actions、trades、marks、checkpoint；不能用同一Session缓存冒充durable读回。
- [ ] 同ID同内容noop、不同内容conflict；未知提交先核对；未捕获停机区间阻塞，不补写first_seen。
- [ ] 验证capture耐久恢复、授权中断恢复、旧owner迟到、seed残缺、字节预算超限。
- [ ] 隔离Redis真实读取通过并证明清理仅作用本任务实例；未配置依赖记blocked/skip，不宣称通过。

出口：故障注入检查实际持久状态，不能只mock repository返回成功。

## 6. T3：真实查询与Web验收

复用P5/P6现有Web/E2E；缺失处新增 `apps/quant-web/e2e/reference-trading-acceptance.spec.mjs`。
- [ ] 独立后端+独立Web+隔离PG/Redis/MDS；禁止默认连接生产8000或使用生产.env。
- [ ] 至少苏冰历史/forward各一例、Newow历史/forward各一例、HTDYforward一例；包含OPEN/CLOSED/中断和两页以上记录。
- [ ] 操作切换策略/周期/模式、翻页、请求取消与并发新增；核对列表/统计/信号snapshot和实际价格字段。
- [ ] 展示未启用、未接受模型、无交易、缺展示数据、滞后、来源冲突；不能静默回到历史replay。
- [ ] GET测试以调用计数或禁止调用spy证明零Kernel/replay/写入；实际API链验证另行保留。
- [ ] 浏览器留最少必要截图与网络断言，记录console错误；route-intercept仅用于独立UI分支测试并明确标识。

出口：读写闭环到页面；production reader仍不切换。截图不能代替结果字段和来源校验。

## 7. T4：可复现性能与容量

新增小型 `scripts/reference_trading_benchmark.py` 与 `tests/reference_trading/test_benchmark_safety.py`，若已有等价入口则扩展，不重复造工具。
只接受隔离数据库与fixture参数，运行前输出计划/预算；固定seed、数据规模、硬件、Python/PG版本、代码SHA。
默认serial workload，显式配置并发；超时/预算失败停止，不连接生产或自动扩资源。

场景：
- 单流：长历史初始化一次后，连续100个新Bar；比较不同历史长度下每次增量处理成本，识别重复全历史回放。
- 60品种：同一完成边界60条流，分别记录无信号与有信号批次，验证公平轮转、积压清空和seq正确。
- 多策略：60品种×5个策略身份（牛哇三策略/苏冰/HTDY）×一个已支持分钟周期，共300条隔离fixture流；分批测，不声称生产capability。
- 查询：每流100/1000/10000条记录的页首、深页keyset、summary和过去cutoff；查询limit=50，检查索引计划和扫描范围。
- 修订：固定历史量的一个stream尾部修订，记录rebuild成本及其他stream可读性；不把正常append和异常rebuild混算。

每个场景分别记录冷启动与稳定阶段，至少5次独立重复；查询稳定阶段每次至少100个请求，报告样本数与p50/p95，
不得拿单次耗时算p95。记录peak RSS、进程CPU、PG表/索引字节增长、capture/action/mark行数、最老pending时长、错误数。
真实计算不能以sleep或空adapter替代；展示fixture性能不是生产收益/自然运行证据。

建议验收目标（T0在首轮测量前冻结）：索引页查询warm p95<=500ms，固定窗口summary warm p95<=1s；
60条分钟流一轮完成<=60s，300条流<=最短已支持周期时长；正常增量不重新遍历完整历史；错误路径无无限重试；
队列/单批payload不超过配置上限，完成队列后内存不随重复相同工作负载持续增长。
首次构建和rebuild先报告规模/耗时/预算，不设无依据的固定秒数。性能不足不能事后放宽目标写成通过；
应定位根因、必要范围内优化并同场景复测，或明确列Risk/未满足项。容量估算标注假设，不把fixture直接外推为生产保证。

出口：JSON原始数据+简短汇总；固定同硬件/同数据修复前后对照。只优化实测瓶颈，不改公式或另建缓存权威。

## 8. T5：回归、独立Review与精确提交绑定

- [ ] 每个confirmed defect先失败测试再最小根因修复；不顺手处理无关周线、首页或其他审计任务。
- [ ] 跑reference全组、受影响migration、Newow/SuBing黄金/统计、Alert/Live相关组和Web定向测试/build；Ruff/类型/OpenSpec/secret检查按范围执行。
- [ ] 按项目路由安排GPT-6 Astra独立审查时序/并发/模型/持久化与性能边界；reviewer独立读代码与证据，不只读实现者总结。
- [ ] Finding分Confirmed Issue / Risk / Optional；阻塞项修复后重验受影响场景，绑定最终commit/tree，不能复用修改前Review为通过。
- [ ] 如develop前进，先核对差异；集成后检查最终tree与验证tree关系，相关依赖有变则补对应测试，不机械重跑无关全仓。
- [ ] 提交/push普通任务分支并在条件满足时集成develop；不自动main/tag/release。

出口：CODE_COMPLETE/TEST_COMPLETE/REVIEW_COMPLETE可逐项举证；未解决阻塞则不给RELEASE_CANDIDATE结论。

## 9. T6：候选与P9交接

最终acceptance.md记录：精确SHA、所有case结果、实际命令与exit、skip原因、性能数字、独立Review、缺陷修复与已知限制。
更新TESTING.md为稳定可复现入口；STATUS仅记录工程事实并保留当前生产readback，不用计划覆盖已有发布身份。
列出下一阶段需要的精确项目：模型接受、schema差异、可启用stream/周期、历史构建覆盖、reader切换、
主机/服务/版本、预算/恢复政策、禁用与回滚、自然盘中/盘后证据。只产出候选建议，不替owner批准。
P8结论允许为“部分组合可进入候选，其他组合明确阻塞”；总报告必须给分母和排除原因，不泛称全周期ready。
任何必要真实隔离验证无法完成，保留EXTERNAL_TEST_DEPENDENCY_PENDING，不以测试工具存在冒充验收完成。

## 10. 执行命令与安全

先 `rg --files` 确认实际路径；现有基础入口：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q -p no:cacheprovider --tb=short \
  services/quant-api/tests/reference_trading \
  services/quant-api/tests/alembic/test_reference_trading_migration.py \
  services/quant-api/tests/alembic/test_reference_forward_migration.py \
  -m 'not isolated_postgresql'
git diff --check
```

真实PG/Redis依TESTING.md guard使用专用实例，单独跑对应markers；无配置的skip不算验收通过。
新E2E/benchmark入口必须在开发后写明实际命令、隔离变量与清理范围，不能把此文中的拟新增路径当已存在代码。
独立进程/数据库只清理本任务创建且验证身份的对象，不触碰共享工作树、生产卷和其他任务输出。

依赖：T0 -> T1/T2/T3 -> T4 -> T5 -> T6。普通缺陷修复嵌入所属任务，不延后成没有责任人的下一阶段。
