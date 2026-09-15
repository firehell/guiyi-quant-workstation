# 牛哇周线剩余 1–3 项实施计划

## 2026-09-14 证据丢失后的执行修订（当前入口）

本节取代下方 P0–P6 中已经过时的执行步骤；下方保留为历史工程记录，不重新开发已集成的恢复工具。
Owner 本轮要求综合修订方案，并安排一个 `gpt-5.6-sol` / `high` 新任务直接推进。执行者使用
`superpowers:executing-plans`，一个主任务串行负责现场，阶段末做独立 Review，不另拆多个用户开发任务。

**目标：**恢复可持续保存的证据，重新冻结并完成剩余普通 W1 补数，集中处置 B2411 与九个 RS。
**架构：**沿用原生 readiness、Catalog/Canonical/MDS、warm-up 和 prepare/apply/inspect；历史数据事实与
历史操作证据分别核验。证据缺失不能通过修改数据、伪造回执或手工删除候选解决。
**技术与合同：**现有 Python/SQLAlchemy、原生 Parquet/八表 Catalog；本目录
[设计](remaining-123-design.md)、[总包方案](ordinary-full-closeout-plan.md)、[历史执行记录](remaining-123-execution-evidence.md)
及 `docs/DATA_CENTER.md` 的来源隔离合同共同适用，实际命令仍只维护于 `TESTING.md`。

### 当前事实与修订理由

- 主仓库核对基线为干净 `develop@8dd2c814e042188c258a0d6058f9051707c0566b`，包含 `91246a5f0`；执行时再次核对。
- `7265` 工作树已不在清单。主仓库持久证据根固定为
  `/Volumes/扩展盘/guiyi-quant-workstation/outputs/newow-weekly-recovery-attempts/`，不得迁到新 task worktree。
- 根下 `evidence-rebuild-20260914-001/README.md` 记录本轮恢复：旧审计四文件逐字节匹配，完整报告 SHA
  `3f4a5693194bf6844c8e4134e614297755535c2a83a97c4468cc51bdf9991ec1` 与历史文档一致，原生结构校验通过。
  它只证明补数前 1,117 PROPOSED / 9 REVIEW_REQUIRED，不证明当前余额。
- 新只读审计在数据库事务打开阶段返回 `OperationalError`，未进入原生审计、未生成新报告、未重试；
  不能仅凭该脱敏类型断言网络、认证或服务故障，更不能为排障重启 Runtime 或修改凭据。
- 1,014 单元、51 批、已准备 26 批及旧 102 成功对象全部退出候选，是丢失报告的历史线索。
  不能从这些数字恢复 manifest，也不能把旧 1,117 报告当作新输入。
- B2411 原始来源响应、journal 和旧总包关联证据仍缺失。九个 RS 为 RS2407、RS2409、RS2411、
  RS2507、RS2509、RS2511、RS2607、RS2608、RS2609；该名单只用于定位，当前分类由新原生审计决定。

### 允许范围与共同边界

本轮直接执行仓库/证据检查、脱敏只读连接诊断、新原生只读审计、离线来源分析、全部可完成的 prepare、
必要的最小工具修复、验证、独立 Review 及普通 develop 交付。用户这次请求允许从连接诊断重新开始，
不要求停在上一轮失败摘要；诊断原因和权限边界清楚后才开始新的审计尝试，不循环重试。
真实来源查询/下载、Canonical/生产写入各自仍需精确范围的新单次意图；旧批准不继承到新任务。
不发布、不切 Runtime、不改 Scope/通知/凭据，不开放日线或 60m，不执行完整策略/页面验收矩阵。
W1 必要的同源 D1 companion 属于本范围，不等于开放 D1 产品。

### 第一项：恢复证据与可信执行落点

- [ ] 在平台隔离工作树中确认代码包含最新 develop 依赖；避开首页性能任务、daily 工作树和 Runtime。
  不因平台默认起点而使用缺少恢复修订的旧代码，不清理任何正在工作的工作树。
- [ ] 使用主仓库已有证据根，先确认无运行中的恢复 writer、共用 guard 路径、目录身份及 maintenance 状态。
  新 campaign 的共同输出根固定于上述根，不为每个工作树另建可绕过互斥的 guard。
  原报告、响应、journal 直接落此处；独占创建 attempt，禁止覆盖。代码在隔离工作树，数据证据留主仓库。
- [ ] 有界检查已有文件与备份线索。能恢复的原文件核验 hash/身份；只有日志摘要的标为历史线索，
  找不到的明确标记 evidence missing。不得重造旧 provider payload、执行回执或未知提交结果。
- [ ] 通过既有私有配置 loader 做脱敏连接诊断，仅记录错误类型、SQLSTATE/安全错误分类及权限结果；
  禁止记录连接串、密码、内部地址或 traceback。若宿主权限不足，通过正常工具权限流程处理，不绕过。
- [ ] 连接正常后，用新的输出目录运行一次 fresh READ ONLY 原生 operational-60/W1 dependency-only 审计，
  固定 `as_of=2026-09-13T06:36:13+00:00`，完整保留 metadata/source/review/unknown、零 provider/生产写入。
  完整报告再派生摘要，不能用 compact 丢失冻结所需内容；不扩大到当前交易日。
- [ ] 以当前分区、Catalog/MDS 及 replan 证明数据现状。只有找到旧 102 的完整身份清单时才逐项比较退出；
  清单未恢复则明确无法重做历史逐项对账，不从排序或数量倒推出成功对象，也不把候选过滤掉。

验收：主仓库持久证据可读、历史与新证据分开，新审计 complete=true、budget_exhausted=false；
连接失败或不完整时不得进入真实执行。共享证据根不构成独立磁盘备份，不宣称防磁盘故障。

### 第二项：先核清异常，再冻结全部普通补数

- [ ] 从新原生审计派生当前普通与异常分类，不把 1,014 或 51 写成断言。B2411/RS 不隐入普通自动执行。
  当前 PROPOSED 与历史异常线索冲突时保留原报告、标记冻结阻断，不裁剪报告或伪装 REVIEW_REQUIRED。
- [ ] 对第三项的异常同步完成本地证据调查。完整旧执行证据若找回，使用现有 prior-campaign 校验入口
  验证原生结果、所有已开始响应、严格零提交、身份/hash 和当前 plan 匹配后，才形成排除绑定。
- [ ] 旧证据找不回则不能沿用旧排除：先准备 B2411 与需要再核验的 RS 的精确来源取证请求和独立 Gate。
  不为赶普通补数默许重下载 B2411。可以继续其余子包的只读准备，但没有合法全集排除证明时，
  不宣称普通 campaign 已冻结。新 source-only 证据若不符合现有导入合同，先给出最小合同修订和 Review，
  不制造假的 prior campaign/receipt，也不新增第二套缺口权威。
- [ ] 代码身份稳定后，通过现有执行器完成全部普通子包，每批最多 20 单元；全部 child hash、目标联合覆盖、
  总数/目标数/expected bars/missing endpoints、代码/config/root/as-of 身份一次核对。
  已准备 26 批的历史状态不复用，新的最终总包必须有全部子包；本轮未通过的包不得用于申请 apply。
- [ ] 形成一份可审的普通总包申请，包含 exact campaign hash/attempt、固定范围、异常排除证据、
  维护窗口、projection 影响及读回/失败规则。内部正常批间不重复请求授权，不估算 SDK 计费或配额。
- [ ] 取得新任务内精确单次执行意图后，按已冻结策略串行执行一次。仅满足现有 allowlist、完整来源响应、
  零提交和计划未变的来源质量异常允许隔离继续；网络/额度/锁/身份漂移/提交未知/读回失败均全局停止。
  停止后保存所有结果，不自动重试或续跑，不回滚成功分区。
- [ ] 新进程在 fresh READ ONLY 事务中逐单元 Catalog/Parquet/MDS 读回与原生 replan；再做相同截点全域审计。
  原生五类终态闭合完整分母；新发现的候选保留未完成，不自动扩包。普通候选归零才称固定范围普通补齐。

### 第三项：按原因处置 B2411 与九个 RS

- [ ] 优先复用主仓库早期来源核验与现存 Canonical 证据，逐对象列异常 timestamp、物理合约、D1/W1
  同源完整周上下文、缺失端点、来源覆盖及当前原生 plan；不把一个坏行外推到整份数据。
- [ ] 分别标记来源本身非正/缺失、本地与已保存来源冲突、读取或身份故障、证据不足；
  不将 B2411 的非零成交零 OHL 套用零成交规范化，不用 close/settlement 替换价格，不删除坏行造绿。
- [ ] 新来源核验只查询尚未被可信证据覆盖的精确请求，先冻结 contract/method/window/hash 和保存位置，
  再申请一次 source-only 意图；来源查询不授权 Canonical 写入，也不为额度探测初始化 provider。
  完整保存所有已开始请求的响应与 journal，失败结果未知时不补发请求补齐证据。
- [ ] 来源确认无效的对象继续 SOURCE_EXCEPTION，给出明确不能补齐的原因；来源缺失/未知保留阻断。
  只有当前权威来源有效且原生合同允许修复的目标，才形成独立专项修复包并申请新的写入意图。
  任何 adapter/规范化语义变更先完成设计和独立 Review，不将行情事实处理混入普通补数工具修复。
- [ ] 获批的专项一次执行后做三层读回及原生重规划；维护同一异常清单和证据链接。
  “分类完成”与“数据修复完成”分别报告，无效源异常可以得到处置结论但不能计为数据成功。

### 验证、交付与停止点

只读/离线工作不因尚缺真实 Gate 而停止；已经完成的恢复工具不再整体重写。仅有必要代码修复时，
按 `TESTING.md` 跑对应 recovery/campaign/readiness/adapter 定向测试和失败边界回归，再按影响扩展。
文档运行引用、适用工程测试、OpenSpec、secret scan 和 diff 检查。独立 Review 核验来源排除证明、
全集分母、稳定共同根、未知提交与失败停批；完成验证后按仓库流程提交并集成 develop。
不在执行中更新源码导致已冻结包失效；代码必须变更时，冻结包明确作废、重新只读准备及取得新意图。

唯一执行任务交付：本节清单、持久证据索引、当前完整审计、可用的精确总包、专项异常表、真实执行结算
或最小待批准 Gate。不新增重复治理账本。同步本目录执行证据文档，只有新事实支持时才更新 STATUS。
任务 worktree 在现场流程/证据交接完成前保留；本轮不安排自动清理。
最终三项分别列完成状态；数据未补齐或异常未修复时保持 PARTIAL/EXTERNAL_GATE_PENDING，
不声称 60 品种牛哇闭环完成。180 周线策略组合及完整页面验收是后续独立工作。

---

## 以下为证据丢失前的历史实施计划

> 执行者：一个 `gpt-5.6-sol` / `high` 新任务。按 executing-plans 技能连续完成有界工程步骤；独立 Review 可以使用 reviewer，不另起多个用户开发任务。

配套设计：[remaining-123-design.md](remaining-123-design.md)。状态：PLAN_REVIEW_COMPLETE（独立 Review：0 P1 / 0 P2；允许继续实现）。设计/工程委派已被本轮请求授权；下载、Canonical/生产写入、失败重试不继承旧会话意图。无发布或 Runtime 操作。

## 预计改动面

| 文件 | 责任 |
| --- | --- |
| `scripts/newow_weekly_recovery.py`（新增） | 薄编排入口；readonly prepare、本次 attempt、journal、readback；不包含新的行情算法 |
| `services/quant-api/app/market_data/rqdata_adapter.py`（必要最小修改） | 复用完整周来源日 helper；可选调用观察接缝；默认行为及 cache 不变 |
| `services/quant-api/tests/data_foundation/test_infrastructure.py` | 原生 W1 跨月、生命周期、同源 D1/W1 回归 |
| `services/quant-api/tests/newow/test_weekly_recovery.py`（新增） | 作用域、失败点、序列化、安全、幂等与单次执行证据 |
| `services/quant-api/tests/data_foundation/test_historical_data_manager.py` | 如需要补齐锁内 plan/hash 与部分成功失败停止回归 |
| `TESTING.md` | 唯一实际验证命令入口，新增本任务最小定向命令 |
| 本目录两份新计划与既有 execution-readiness 记录 | 当前状态及历史结果关联，不把旧任务状态整块覆盖最新 STATUS |

优先复用现有 composition、配置 loader、plan/result 类型和维护回读逻辑。若执行器复杂到需要生产域新模块，先缩减编排职责；实质改变数据合同/身份/授权的设计先回报。无新增 migration、HTTP API、常驻服务、公共 quota/planner 平台。

## P0：基线与证据导入

- [ ] 在新任务独立 worktree 中核对 branch/HEAD/dirty、最新 develop、其他 worktree。平台默认起点不等于 develop；安全建立 `codex/` 任务分支并纳入最新 develop，保留用户修改，禁止 reset/覆盖。完成前不清理父 worktree。
- [ ] 阅读 AGENTS、STATUS、DEVELOPMENT、futures-data 及对应 canonical；读取两份已审设计。当前参考基线 `b32d9b0f7`，保留最新 trading-day 下界修复。
- [ ] 只读核对 evidence 根、四批 Session、SI2308、EC 失败、41 来源核验点、有效 dependency audit。从旧分支 `40b1f05c6` 选择导入历史记录，不能误称已合入或带入旧主线状态。
- [ ] 登记当前生产配置/Canonical 根的非敏感身份、维护状态与预定 readback；此步骤不得初始化 provider、获取配额、下载、写 DB 或触碰 Runtime。
- [ ] 跑现有原生 adapter/manager 与 Newow readiness 定向基线；结果不绿先区分旧问题与本任务问题，不降低断言。

## P1：EC 回归先 RED，再实现原生来源观察

- [ ] 在离线 fake provider fixture 重现 EC April 周线需要 2026-03-30 来源行。新回归必须先在旧失败约束下失败，并证明失败是日期断言，不是配置或连接问题。
- [ ] 同时验证 W1/D1 共享来源快照、生命周期边界、Calendar 缺失 fail-closed、不调用分钟接口。
- [ ] 抽取并复用现有完整周来源 helper（仅在 preflight 需要时），实现最小观察接缝；不改原生聚合、零成交量规范化、hard validation 或提交顺序。
- [ ] 测试调用前 allowed contract/method/date 检查拒绝越界；测试错误 logical plan、hash 漂移、错误数据根均为零 provider call、零正式写入。
- [ ] GREEN 后检查 diff：没有 EC 专用硬编码允许列表、没有第二套来源周算法、没有 runtime configuration fallback。

核心断言示例（由真实 fixture 构建输入，不是静态测试实现）：

```python
assert april_source_start == date(2026, 3, 30)
assert weekly_april_3.source_dates[0] == date(2026, 3, 30)
assert not provider.minute_calls
assert daily_and_weekly_use_same_snapshot
```

## P2：可审计的一次执行与失败注入

- [x] 实现脚本的 readonly prepare 与受控 apply 分离；配置必须显式正确，准备阶段 provider 未初始化。来源包仅保存允许的行情字段，不保存 SDK repr、traceback 或凭据。
- [x] prepare/apply 要求 clean exact commit；apply 在首次 provider 调用前写入绑定 prepared hash、代码、配置、数据根和单元数的 invocation receipt，并在每单元前复核 checkout 与执行环境身份。
- [x] 先 RED：provider 返回后本地聚合异常，旧行为没有响应证据；新增 started/response_saved journal 与原子来源 payload 后 GREEN。
- [x] 先 RED：started 保存失败仍发请求；修为调用前 fail-closed。再覆盖 response 保存失败、timeout、进程中断残留 started、重复 attempt、输出路径逃逸、符号链接/覆盖保护。
- [x] 验证来源 payload 序列化保留 Decimal/日期/非正数含义，并有 hash；它不是自动 replay 可写资产。验证 unknown 只能只读对账，不可自动 retry。
- [x] 使用真实 manager 的测试路径覆盖锁内 replan、正常 projection invalidation、一次批准批次的串行执行、前项成功后后项失败及未尝试尾项；不要求 projection 路径不存在。
- [ ] 记录 projection 失效及恢复影响；COMMIT_OUTCOME_UNKNOWN 中断后只读查 Catalog/文件/MDS，不主动删文件或重设 active 指针。
- [x] 更新 TESTING 命令、定向测试、静态检查、自审；独立 Review 修正全部 P1/P2 问题后方进入真实执行准备。

关键失败断言示例：

```python
assert journal[0].state == "started"
assert response_receipt.exists()  # 后续聚合失败不抹掉已经保存的来源响应
assert canonical_writes == 0  # 本例在原生 validation 前失败
assert attempt.outcome == "failed"  # 已知失败，不改写成成功
assert retries == 0
```

## P3：当前队列与 EC 单次包

- [ ] 刷新冻结历史 as-of 的 dependency-only audit；严格保留 60 品种分母与非就绪对象，不跑第 4 项完整 acceptance matrix。
- [ ] 对比 1,139 PROPOSED 历史快照与现在，排除 SI2308 与已修复 targets；列当前普通、review、source、metadata、unknown 分类及变化原因。
- [ ] 单列 EC2607：现取 plan，比较旧 hash/8 targets/84 bars；不把旧 hash 当作当前有效。展示原生完整周 source 范围及环境，不估算流量。
- [x] 准备精确单次下载+写入包、代码身份、projection 影响、回读和失败停止规则。此包只是准备产物；在开发新任务中取得 owner 新的精确执行意图后才尝试。
- [x] 获批则一次执行，成功须 Catalog/文件 hash/MDS/原生 replan 均回读；失败立即停止，保留来源结果及已知/unknown，不自动执行第二次。
- [x] 即便 EC 外部 Gate 未获批，也继续 P4 的 readonly 队列和 P5 的本地调查、全部工程验证，不空等。

## P4：普通剩余项有限批次

- [x] 从当前 PROPOSED 清单按稳定 symbol/contract/through 排序，最多 20 个完整逻辑计划一批，D1/W1 同源作为同一 warmup 单元。
- [x] 每批冻结目标、hash、原生范围和失败影响，排除 source/review/metadata/unknown；不把所有历史 1,139 项视作一份无限执行授权。
- [x] 每个批次有 fresh 精确单次意图后串行处理；每单元重新验证锁内计划。漂移或任何异常停止整批并报告已完成、失败和未尝试尾项。
- [x] 写后严格读取与原生 replan；汇总真实余额，不使用成功请求数或二次人工清单作为 gap 权威。
- [ ] 未获批、失败或 scope 改变：可继续准备安全独立项，但下载/正式写入需新意图；不把“用户不要求配额计算”误读为自动重试授权。

## P5：RS2309 与 RS2311 专项

- [x] 只读定位当前 Catalog 分区、hash、物理文件、异常 timestamp、Calendar/Session 与完整周上下文；旧诊断月份仅定位线索。
- [x] 精确列出每个异常 bar、缺失 bar、损坏对象及其来源窗口；生成去重后的请求清单，禁止先猜一个请求数。
- [x] 为这两个 RS 单独取得当前一次来源下载意图，不继承原九个 RS 或 EC 意图；仅来源核验，禁止包含 Canonical 写入。
- [x] 测试并执行七字段/时间身份比较，分类 SOURCE_NONPOSITIVE_MATCH、LOCAL_SOURCE_CONFLICT、SOURCE_MISSING、UNKNOWN；每个分类注明证据覆盖和未验证范围。
- [x] 来源一致非正保持原阻断；缺失目标另列原生修复 plan、独立 Review 与精确写入意图。不从专项静默移动到普通自动队列。
- [x] 保存原 41 异常点证据及新增两合约证据的独立身份，不外推或覆盖旧事实。

## P6：工程收尾与事实交接

- [ ] 跑 adapter/manager/recovery/Newow 定向测试，必要时扩展 Catalog/MDS 下界回归；全部命令记 TESTING。生产下载不得作为单元测试。
- [ ] 跑适用 engineering 文档一致性、OpenSpec strict、secret scan、diff 检查；独立 Review 并修复，不能以历史 532/80 测试代替本轮结果。
- [ ] 仅集成本任务代码与已审文档到最新 develop，commit/push 和集成不授权发布或 Runtime。避免整批 cherry-pick 旧状态文档，保留 primary outputs 与所有 Runtime worktree。
- [ ] 交付唯一事实进度表、实际命令结果、Review、代码/develop 状态、数据真实成功/失败/unknown 与未执行 Gate。若数据尚待批准，使用 CODE_COMPLETE_EXTERNAL_GATE_PENDING，不写 COMPLETED 数据闭环。
- [ ] 完整页面/180/540 矩阵仍不在本任务；唯一下一步由剩余最小精确 Gate 决定。最终结论只能基于证据给“允许继续实现”或“允许集成 develop”等相应阶段，不宣称允许发布/Runtime。
