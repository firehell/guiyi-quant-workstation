# Unified Reference Trading P3 Implementation Plan

> 执行：新的 Sol / medium 任务，使用 executing-plans 完成实现、隔离验证、独立 Review 和条件满足的 develop 集成。用户已要求设计后直接安排开发，不重复申请工程计划批准。

**Goal:** 为已完成的 P0–P2 提供 PostgreSQL 持久化、原子批次、checkpoint 恢复和固定版本读仓储。
**Architecture:** 纯域不依赖 DB；应用 DTO 校验现有 reducer/adapter 输出，repository 用短事务锁及 CAS 提交。六张新表保存独立流、代际、批次、动作、交易版本和估值。
**Tech Stack:** 现有 SQLAlchemy 2、Alembic、PostgreSQL、Decimal、pytest；不增加数据库服务或中间件。
**Spec:** [总体设计](../specs/2026-09-19-unified-reference-trading-design.md)、[P0 canonical](../../../openspec/specs/reference-trading/spec.md)。本文件细化 P3，不批准后续 Runtime 或生产写入。

## 1. 基线与范围

- 设计核定 develop：`21204c9272a5a7f66ca2054ab68c26753bd11e12`，包含 P2 closeout merge `a86ae0122`；旧 P2 不完整候选不能作为完成基线。
- P2 closeout 记录 545 项联合回归、Ruff、OpenSpec 10/10、独立 Review。它是既有证据，不代表本轮已重跑。
- 当前主树有其他任务周线计划与 outputs 未跟踪内容，必须保留；本计划是本任务唯一新增主树文件。
- 实施前重新核对 develop 是否已领先本基线；任务 worktree 必须包含上述提交，不能在默认 main 上直接实现。
- 调查所见最新 migration 为 `20260916_0046`；用 Alembic ScriptDirectory 无连接检查唯一 head，再分配新 revision，不能硬编码旧 0045 或形成双 head。
- 包含 ORM、migration、repository、仓储 DTO、隔离测试和 canonical 持久化条款。
- 不包含 MDS 构建/下载、历史扫描 CLI、HTTP API/Web、worker/Scope enable、HTDY新模型、生产 migration/DB/Redis/Canonical、通知、main/tag/release/Runtime。
- 新表迁移不插入 enabled stream，不修改原 Alert/Catalog 表或数据。`executable=false`、`auto_order=false`。

## 2. 必须复用的真实 P2 接口

- `reference_trading/contracts.py`：StreamIdentity.stream_id、ReferenceAction、ReferenceTrade、ReferenceMark、ReferenceState、ReferenceTransition.changed_trades/marks/diagnostics。
- `adapters.py`：AdapterCheckpoint（完整 strategy_state + reference_state + 水位和物理身份），CompletedStrategyInput，advance_checked。
- `checkpoint.py`：checkpoint_to_json / checkpoint_from_json 是纯 ReferenceState codec，不能把它当完整策略恢复。
- `strategy_checkpoint.py`：adapter_checkpoint_to_json(checkpoint, strategy_schema=...)；adapter_checkpoint_from_json(value, expected_stream=..., expected_strategy_schema=...)。
- 策略已有 ReturnPolicy/数值顺序及旧公开 ID 均保持；repository 不重新算收益、不排序改写同 Bar 动作、不生成 signal ID。
- 完整 checkpoint 存 TEXT，读写均调用现有严格 codec，保留原规范 JSON；不要先转 JSONB 丢掉重复 key 证据再校验。
- P1 允许未封口同 Bar 分批。P3 可以保存其 last_event_key，但只有 sealed completed 输入才能推进 computed_through；不能强制每笔提交水位严格增长而拒绝合法子批。

## 3. Schema：六表与约束

统一时间 TIMESTAMPTZ、交易日 DATE、序号 BIGINT、Decimal 无隐式量化 NUMERIC；JSONB 只保存已严格验证的 manifest/evidence。
应用层和必要 DB CHECK 拒绝 NaN/Infinity、负计龄、非法状态、缺失关联和不完整 exit。返回值不经 float。

| 表 | 主键/关键字段 | 必须保证 |
|---|---|---|
| reference_streams | stream_id PK；完整 identity；enabled=false；active_revision_id；row_version；health | 写入 identity 重新计算 hash；重复创建同身份 no-op，hash相同内容不同拒绝；enabled 无公开修改方法 |
| reference_revisions | (stream_id, revision_id) PK；status、last_seq、checkpoint_batch_id、dependency_digest、parent_revision | candidate/active/superseded/invalid；stream active 指针只能指向本流；候选 checkpoint 不覆盖正式进度 |
| reference_batches | batch_id PK；stream/revision；batch_key、payload_hash、kind/outcome、seq、expected_seq、pre/post hash、checkpoint_text、schema、watermarks、evidence、diagnostics | unique(stream,revision,batch_key)，committed seq>0且 unique(stream,revision,seq)；诊断 seq=null、不修改有效 checkpoint；初始化由独立种类表达 |
| reference_actions | action_pk PK；stream、origin_revision、source_action_id、kind、event sequence、物理/段、Bar/观察时间、价格、entry关联、batch_id | historical unique(stream,origin_revision,source_action_id)；forward partial unique(stream,source_action_id)，不因重建重复观察；原动作不可更新 |
| reference_trades | (stream,revision,trade_id,valid_from_seq) PK；valid_to_seq；entry/exit action_pk；side、status、prices、return、segment、holding | 半开有效区间[from,to)；每个trade至多一个 current 行；外键不得跨流；同 revision 生命周期不倒退、不重开已结束trade |
| reference_marks | (stream,revision,trade_id,batch_seq,bar_end) PK；entry_action_pk；价格、计龄、收益、交易日 | 只来自 reducer marks；引用同流/同版本有效trade，禁止孤儿mark；批次序号参与身份，合法同Bar分批可区分 |

所有 batch/action/mark 均通过组合外键或等价 DB 约束关联所属 stream/revision/batch；不能仅有一个无所属校验的全局 ID。
trade 对 action 的 FK 为 `(stream_id, action_pk)`，源 revision 独立存储：historical 必须同 revision；forward 重投影允许引用本流旧源 revision 的不可变观察动作。后者由锁内校验，不删改旧动作。
trade interval 的非重叠由 repository 单 writer行锁 + current partial unique + valid_to>valid_from 保证；不要求安装 btree_gist 扩展。
marks 可引用稳定的首个 trade version（birth seq）；查询按快照先选有效trade version，再选相同cutoff内最新mark。
索引覆盖 stream identity、revision+seq、entry_bar_end+trade_id 倒序、action event key、trade marks 截止、batch_key。
初始化状态、准备中的输入分块存 reference_batches 的 seed_chunk 种类：seq=null，声明 chunk index/count/root hash；最后 seal 验证完整hash和完整codec后才成为可读 checkpoint。每块唯一且有长度上限。
不建立第七张 scheduler/ledger 表，不创建启用命令；数据库不是行情权威。

## 4. 应用 DTO 和仓储边界

新增 `app/reference_trading/{__init__,contracts,models,repository}.py`，量大时按事务写与快照读拆文件，不散入市场数据模块。
新增 app 级类型（不改变 P1 DTO）：

- `CheckpointToken(stream_id, revision_id, seq, row_version, state_hash)`：CAS前提；reference水位、last_event_key和完整adapter state来自codec。
- `PreparedBatch`：stream/revision/batch_key、expected token、dependency manifest、source actions、ReferenceTransition序列、完整末checkpoint、source evidence、策略schema。不得只传最终trade集合丢失同Bar中间结果。
- `CommitResult(outcome, revision_id, seq, checkpoint_hash)`：outcome为 committed/noop；冲突抛稳定错误，不携SQL/URL/stack。
- `SnapshotIdentity(stream_id, revision_id, seq)`：P3只提供内部快照身份，P5再实现HTTP token/cursor。
- `StoredPage(items,next_key,snapshot)`：内部keyset分页，确定性排序；不提供全站无界读取。

仓储公共方法：

```text
ensure_stream(identity) -> stored disabled stream
create_revision(stream_id, expected_row_version, dependency_digest) -> candidate revision
stage_seed_chunk(revision_id, chunk) / seal_seed(revision_id, manifest, checkpoint) -> CheckpointToken
load_checkpoint(stream_id, revision_id=None) -> (CheckpointToken, AdapterCheckpoint)
commit_batch(expected, prepared) -> CommitResult
record_diagnostic(stream_id, revision_id, batch_key, evidence, code) -> diagnostic receipt
publish_revision(stream_id, revision_id, expected_row_version, expected_dependency_digest) -> SnapshotIdentity
invalidate_revision(stream_id, revision_id, expected_row_version, reason) -> None
read_batch(stream_id, revision_id, batch_key) -> durable outcome or absent
read_trades/read_actions/read_marks(snapshot, cutoff, limit, after_key) -> StoredPage
```

Repository接收明确Session factory；每个写方法拥有自己的短事务，无外层隐式commit。read方法使用只读session，一次调用固定snapshot。
禁止导入 app config 自动加载生产配置；不在import建engine。调用者负责连接与授权范围，P3不读取 `.env`。

## 5. commit_batch 精确算法

1. 事务外做类型、长度、完整checkpoint codec、hash和source evidence验证。只接受事先计算结果，不调用策略重算或provider。
2. 开事务，按固定顺序锁 stream -> revision；查询同 stream/revision/batch_key 的既有批次。
3. 已存在且payload_hash相同返回原receipt/noop，即使expected旧；不同hash返回 BATCH_CONTENT_CONFLICT，不覆盖。
4. 无既有批次时检查 expected revision/seq/row_version/state_hash、状态允许写、previous checkpoint与payload前提一致。失配 STALE_CHECKPOINT；不隐式重试。
5. 校验P2末state与trade deltas、marks和actions同流同段、explicit entry、有效event顺序与水位；末OPEN必须与数据库更新后的唯一OPEN一致。关闭交易的所有字段与原entry一致。
6. 同批相同trade多次变化允许OPEN->CLOSED：按P2输出顺序fold，存该batch末版本；动作全部保存。初建即同批关闭的trade不产生零长度版本。跨batch保留[from,to)版本。
7. 只有mark/计龄变化不追加trade结构版本；存marks和checkpoint，查询时组合OPEN mark。真正开/平/中断才生成新trade版本。
8. 原子写batch/actions/trade changes/marks/post checkpoint；revision seq+1，stream row_version+1；只有active revision更新对外进度，candidate保持隔离。
9. commit，返回固定receipt。任一异常rollback，不局部落库、不推进seq。

幂等key不使用输出hash本身；由revision、前提位置、输入身份和目标事件范围确定，payload_hash独立检测“同identity换内容”。
checkpoint变但watermark不变只允许合法未封口子批；诊断不能伪装这种计算批。无信号sealed批仍提交有效state/marks/进度。
commit结果未知：由调用者先按read_batch查询；P3提供原子接口和精确receipt，不自动sleep/retry。尚未确认结果不得直接重算重提交。

## 6. 发布、读快照与修复

- publish锁stream/revision，候选必须seed sealed、无损坏、expected dependency hash一致且seq匹配；短事务切active指针并supersede旧版。
- 发布调用者（P4）负责权威源依赖再次核定；P3的hash相等只是防止发布错候选，不能假装已查询Canonical。
- 旧revision仍有效且未invalid时，显式旧snapshot可读；invalid明确抛 SNAPSHOT_INVALIDATED。查询不静默换active。
- valid_from_seq<=snapshot.seq<valid_to_seq（to为空则无上界）；marks/actions/batches同样限制seq。
- cutoff不是仅过滤entry：若选中版本exit在cutoff之后，必须定位该cutoff前的版本/事件及mark，不能将未来退出状态带回过去。P3提供底层按事件截止的读取能力，P5再实现完整统计。
- forward额外约束observed_at；批次不能用一个最晚时间替代动作/输入实际时间。同Bar多动作按完整sequence返回，分页不丢项。
- 建议P3限制一个sealed completed Bar一计算批（可有同Bar未封口子批），历史构建分块可以由多批在应用循环推进；避免单批跨多个Bar把所有交易末态都盖成同一个seq而无法查询中间历史。
- forward观察动作不可变；本流新投影revision只能引用原动作。跨流/模式/公式引用拒绝；historical重建actions属于新revision。
- 生产rollback不执行drop table。migration downgrade使用显式unsupported保护；隔离测试通过销毁本次专用schema恢复，不删除共享库。

## 7. 任务与验收

### T1：Schema和migration

- [ ] 新增六表ORM、DTO及metadata注册（检查 `alembic/env.py` 和 `app/models/__init__.py` 的必要入口）。
- [ ] 使用无连接ScriptDirectory核对head，新增forward-only migration；无生产DML、无初始enabled流。
- [ ] 新增 `tests/alembic/test_reference_trading_migration.py`，真实隔离PG验证升级、表/约束/索引、旧Alert/Catalog数据保持、downgrade拒绝。

### T2：严格序列化、seed与revision

- [ ] 新增 `tests/reference_trading/test_repository_contracts.py`、`test_repository_seed.py`。
- [ ] 用现有苏冰和牛哇真实checkpoint做round-trip；缺key/重复key/错schema/错stream/bool假int/NaN/时区错误拒绝。
- [ ] seed缺块、重复换内容、root hash错、超限均不能seal/publish；相同块幂等。
- [ ] seal后load_checkpoint恢复策略尾部与不中断计算一致，不只比较JSON字节。

### T3：提交、幂等、并发和故障

- [ ] 新增 `test_repository.py`、`test_repository_postgresql.py`；仅单元替身测试不算PG完成。
- [ ] 同batch两连接竞争仅一提交、另一noop；不同payload冲突；不同batch争相同expected仅一成功。
- [ ] 注入actions后/trade后/checkpoint前/commit前异常，读回全部rollback；commit后响应丢失读回原receipt。
- [ ] 无信号Bar、同Bar未封口/封口、同批OPEN->CLOSED->新OPEN、重复mark、跨流FK、段/entry漂移全部覆盖。
- [ ] mutation无前台AlertEvent/transport副作用；价格NUMERIC精度与P2一致。

### T4：快照读与发布

- [ ] 新增 `test_repository_snapshots.py`，连接A捕获seq1 OPEN，B提交seq2 CLOSED后A按旧snapshot仍OPEN且旧mark。
- [ ] candidate不可见；发布前/后reader只见一个完整revision；失效返回明确错误。
- [ ] cutoff早于exit时不泄漏exit/return；forward晚观察不泄漏到过去；同Bar动作分页稳定。
- [ ] forward重投影不重复source action；历史revision更换保留独立actions，跨模式引用拒绝。

### T5：独立Review与集成

- [ ] 更新 reference-trading canonical 的持久化条款、TESTING入口及必要实际状态；不写worker/API已完成。
- [ ] 运行本P3所有测试及原P0–P2组；Ruff、OpenSpec、secret scan、diff检查按仓库入口执行。
- [ ] 做独立Review，重点检查PG真实并发、外键、过去快照、数值与codec、原子失败、schema head兼容；修复阻断项后复验。
- [ ] commit/push任务分支；确认共享develop提交归属后按流程集成和推送，不顺带处理周线outputs，不force，不发布main/tag。
- [ ] 完整汇报候选hash、实际测试计数、PG隔离证据、Review、develop集成状态及剩余外部Gate。

测试命令（对应文件创建后）：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q -p no:cacheprovider --tb=short \
  services/quant-api/tests/reference_trading \
  services/quant-api/tests/alembic/test_reference_trading_migration.py
git diff --check
```

PG必须用 `TESTING.md` 的专用空白可销毁实例与 `GUIYI_ISOLATED_MIGRATION_DATABASE_URL` guard；禁止生产/共享库，
禁止输出凭据。没有现成隔离实例时在允许资源内建立专用临时实例，不为省事连接生产；无法建立则如实报告隔离PG未验，继续其余开发。
测试未配置导致skip不等于完成；进程/端口/目录明确归本任务才能清理。

最终P3完成标准：六表与migration、真实策略checkpoint恢复、幂等原子仓储、稳定快照与revision切换均有真实隔离PG证据和独立Review；
不包含P4构建扫描、P5接口页面或P6盘中运行。用户可据此单独继续P4，无需再重做存储合同。
