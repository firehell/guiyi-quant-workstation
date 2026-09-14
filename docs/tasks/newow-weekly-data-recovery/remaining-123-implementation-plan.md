# 牛哇周线剩余 1–3 项实施计划

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
- [ ] 准备精确单次下载+写入包、代码身份、projection 影响、回读和失败停止规则。此包只是准备产物；在开发新任务中取得 owner 新的精确执行意图后才尝试。
- [ ] 获批则一次执行，成功须 Catalog/文件 hash/MDS/原生 replan 均回读；失败立即停止，保留来源结果及已知/unknown，不自动执行第二次。
- [ ] 即便 EC 外部 Gate 未获批，也继续 P4 的 readonly 队列和 P5 的本地调查、全部工程验证，不空等。

## P4：普通剩余项有限批次

- [ ] 从当前 PROPOSED 清单按稳定 symbol/contract/through 排序，最多 20 个完整逻辑计划一批，D1/W1 同源作为同一 warmup 单元。
- [ ] 每批冻结目标、hash、原生范围和失败影响，排除 source/review/metadata/unknown；不把所有历史 1,139 项视作一份无限执行授权。
- [ ] 每个批次有 fresh 精确单次意图后串行处理；每单元重新验证锁内计划。漂移或任何异常停止整批并报告已完成、失败和未尝试尾项。
- [ ] 写后严格读取与原生 replan；汇总真实余额，不使用成功请求数或二次人工清单作为 gap 权威。
- [ ] 未获批、失败或 scope 改变：可继续准备安全独立项，但下载/正式写入需新意图；不把“用户不要求配额计算”误读为自动重试授权。

## P5：RS2309 与 RS2311 专项

- [ ] 只读定位当前 Catalog 分区、hash、物理文件、异常 timestamp、Calendar/Session 与完整周上下文；旧诊断月份仅定位线索。
- [ ] 精确列出每个异常 bar、缺失 bar、损坏对象及其来源窗口；生成去重后的请求清单，禁止先猜一个请求数。
- [ ] 为这两个 RS 单独取得当前一次来源下载意图，不继承原九个 RS 或 EC 意图；仅来源核验，禁止包含 Canonical 写入。
- [ ] 测试并执行七字段/时间身份比较，分类 SOURCE_NONPOSITIVE_MATCH、LOCAL_SOURCE_CONFLICT、SOURCE_MISSING、UNKNOWN；每个分类注明证据覆盖和未验证范围。
- [ ] 来源一致非正保持原阻断；本地可修复冲突另列原生修复 plan、独立 Review 与精确写入意图。不从专项静默移动到普通自动队列。
- [ ] 保存原 41 异常点证据及新增两合约证据的独立身份，不外推或覆盖旧事实。

## P6：工程收尾与事实交接

- [ ] 跑 adapter/manager/recovery/Newow 定向测试，必要时扩展 Catalog/MDS 下界回归；全部命令记 TESTING。生产下载不得作为单元测试。
- [ ] 跑适用 engineering 文档一致性、OpenSpec strict、secret scan、diff 检查；独立 Review 并修复，不能以历史 532/80 测试代替本轮结果。
- [ ] 仅集成本任务代码与已审文档到最新 develop，commit/push 和集成不授权发布或 Runtime。避免整批 cherry-pick 旧状态文档，保留 primary outputs 与所有 Runtime worktree。
- [ ] 交付唯一事实进度表、实际命令结果、Review、代码/develop 状态、数据真实成功/失败/unknown 与未执行 Gate。若数据尚待批准，使用 CODE_COMPLETE_EXTERNAL_GATE_PENDING，不写 COMPLETED 数据闭环。
- [ ] 完整页面/180/540 矩阵仍不在本任务；唯一下一步由剩余最小精确 Gate 决定。最终结论只能基于证据给“允许继续实现”或“允许集成 develop”等相应阶段，不宣称允许发布/Runtime。
