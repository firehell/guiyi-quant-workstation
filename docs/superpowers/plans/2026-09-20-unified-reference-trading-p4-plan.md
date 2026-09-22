# Unified Reference Trading P4：历史构建、增量、修订与 CLI

> 执行者使用 writing-plans / executing-plans 的逐项验证方式；本文件是 P4 实施合同，不授权生产写入。

日期：2026-09-20。调查基线：develop `1a1d8fbbfe1f7e4417cc8bb2e21c7c9592d31082`。
用户要求详细设计 P4 并创建 Sol medium 新任务开发。P0–P3 已集成；本轮开发授权限于代码、隔离测试、Review 和条件满足的 develop 集成。

## 1. 目标与依据

Spec：`openspec/specs/reference-trading/spec.md`。
总设计：[统一参考交易设计](../specs/2026-09-19-unified-reference-trading-design.md)。
总计划：[P0–P9](2026-09-19-unified-reference-trading-plan.md)。

P4 将 P2 的逐 Bar 策略/reducer 和 P3 的六表仓储连接到真实历史读取，提供手动调用的历史 plan/build/advance/resume/rebuild。
完成后能从已验证 Canonical 构建历史参考结果、追加新发布数据、识别历史修订并安全重建；无需浏览器访问。

不开发 P5 HTTP/Web、P6 后台 worker/盘中 Live、P7 HTDY 模型；不修改 Alert、通知、公式、收益、周期开放和现有页面行为。
不执行 RQData、Canonical 写入、生产 DB migration/bootstrap、Redis 写入、Runtime enable、main/tag/release。
输出目录已有其他任务未跟踪文件，不清理、不暂存。实施前重新核对 HEAD、依赖、dirty 和其他任务。

已核定的接口：

- `ReferenceRepository.ensure_stream(identity)` 默认 disabled。
- `create_revision(stream_id, expected_row_version, dependency_digest)` 创建 candidate。
- `stage_seed_chunk` / `seal_seed` 创建严格、分块 seed；seed seal 为 seq=1。
- `load_checkpoint(stream_id, revision_id=None)` 返回 `(CheckpointToken, AdapterCheckpoint)`。
- `commit_batch(expected, prepared)`，不是早期设计稿的单参数方法。
- `read_batch`、`record_diagnostic`、`invalidate_revision`、`publish_revision` 和内部 snapshot 读取。
- `PreparedBatch` 保留完整 transitions、SourceAction、strategy_schema、输入证据和末 checkpoint。
- 策略状态 codec 为 `newow_product_replay_v1` / `subing_replay_v1`，复用严格编解码，不保存不可验证 object/pickle。

`STATUS.md` 记录 P3 的 83 项（含 9 项隔离 PG）和 368 项关联回归通过；这是先前证据，P4 修改后必须重新验证相关范围。

## 2. 本版策略范围

只接受 `recording_mode=historical_replay`、`series_kind=actual_dominant`。
苏冰：15m/30m/60m/1d；牛哇 trend/oscillation/main-rise：1d/1w/60m，以当前 canonical 和能力注册为准。
这是历史构建代码支持范围，不等于所有品种都数据就绪或正式开放。实际请求明确列出 product/strategy/frequency，禁止默认 all。
HTDY、forward、未知策略/版本/周期及未确认 Bar 在 plan 阶段拒绝。
schema 0047 存在不构成生产写权限；缺 schema 时只报告明确错误，不自动 migrate。

## 3. 重要发现：P3 依赖摘要需要支持真正的历史追加

当前 `commit_batch` 要求 `revision.dependency_digest == digest(prepared.dependency_manifest)`。
若把新增分区和新 cutoff 写入 manifest，会被拒绝；若永远使用旧 manifest，又无法证明最新输入来源。
P4 必须补一个最小的、原子且向后兼容的 dependency advance 合同，不能绕过校验或每次增量都全量重建。

建议在应用 DTO 新增 `DependencyAdvance`，包含 expected prior digest、新 manifest，以及经输入层生成的 append-only proof。
`PreparedBatch` 新字段默认 None，旧调用保持原校验行为。proof 至少列明 prior/new prefix digest、追加输入范围和元数据扩展事实。
proof 是内部可信输入层的校验结果，不是接受外部 CLI 自称“无修改”的授权凭证；外部 JSON 必须重新读取权威来源验证。

同一 repository 事务内：核对 checkpoint CAS 和旧 digest -> 核对 manifest 结构/前缀扩展 -> 写批次与新 manifest -> 更新 revision digest -> commit。
batch payload hash 包含 dependency advance；相同 batch_key 已提交时仍优先返回原 receipt，不能因 digest 已更新而错误拒绝幂等重放。
revision 保存当前有效 digest，seed/batch 保存各自当时的完整 manifest，不改写 seed 历史。publish 使用最后已验证 digest。
补最小只读仓储接口读取 stream/候选状态、当前 manifest 和 resume 信息；不得用 `ensure_stream` 做 dry-run 的读取。
原则上不增加第七张表或新 migration；若现 schema 存在不可绕过的实际缺口，先给出证据与最小方案，不擅自扩建。

## 4. 文件职责与应用接口

新增 `app/reference_trading/planning.py`：严格请求/计划 DTO、规范编码、plan hash、预算、resume 身份。
新增 `inputs.py`：组合现有 MDS/research reader，输出有序完成输入、边界、完整依赖和截止证据。
新增 `service.py`：构建/增量/修订状态编排，调用 P2/P3；不直接写 SQL、不下载。
新增 `composition.py`：显式注入连接、reader、时钟/取消与预算；import 时不读取生产配置或创建 engine。
新增 `app/guiyi_cli/reference_commands.py`，在现有 `main.py` 注册 reference 子命令与 readonly 分类。
按需小改应用 `contracts.py/repository.py`，以及共享历史输入读取 seam；不复制 resolver。

拟定应用入口：

```text
HistoricalReferencePlanner.plan(request) -> HistoricalReferencePlan
HistoricalReferenceService.execute(plan, expected_plan_hash) -> BatchReport
HistoricalReferenceService.resume(plan, resume_token, expected_plan_hash) -> BatchReport
```

request：operation(build/advance/rebuild)、显式 streams、since/through、timezone-aware as_of、预算。
plan：schema_version、operation、规范 stream identity、storage_start、目标完成截点、预热/owner/质量依赖、
前置 checkpoint/revision/row_version、输入 manifest/hash、分包参数、缺口、预算、plan_hash。
resume_token：plan hash、stream/revision、已封口位置、最近 batch identity；不是另一个可随意编辑的范围清单。
report：planned/completed/noop/blocked/failed、逐流原因、candidate/active revision、最后 receipt、水位、资源用量。
所有公共输出使用稳定错误码，绝不输出连接 URL、SQL、凭据或原始异常堆栈。

## 5. 历史输入与依赖合同

复用 `ActualDominantResearchSegmentLoader`、NewowProductReader 与苏冰现有 `_inputs/_daily_quality_inputs` 所代表的统一读取逻辑。
可把确需复用的只读输入准备抽成公开 typed helper，由旧服务和 P4 共用；不能让 P4 调用 HTTP query/project 再拆响应。
不得复制 Calendar/Session/rank1/coverage resolver，也不得 glob 自选 Canonical 文件。

每流必须固定：实际可计算 storage_start、物理生命周期预热起点、正式 owner 区间、最后完整交易日及其合法 Bar 截点。
`since` 是本次保存覆盖合同，不能当作随页面变化的筛选窗口。历史起点扩大使用 rebuild，不从缺失状态直接接续。
当前交易日未完成不能混入正式历史；周线须满足完整周；缺数据不静默缩窗。
预热输入可早于正式 owner 水位，新 owner 的预热不得倒退全流正式水位；预热不能产生 owner 外交易。

manifest 至少覆盖：物理 dataset/partition 内容身份、源版本、查询范围、Calendar/Session、rank1 有效区间、
coverage/质量分段、lifecycle warmup、公式与模型版本。只 hash 最后一根 Close 或目录 mtime 不合格。
若权威 catalog revision 不能充分证明旧前缀不变，允许有界逐分区校验旧依赖；不能把读验证误称策略全量重算。
新增尾部与历史修改分开：旧前缀 OHLC/映射/Session/质量不能变化；同分区追加需要证明旧窗口内容相同。
owner 的查询 horizon 扩展与已确认换月是两件事，不得因为 reader 用当前 through 裁剪 owner 就每天误判换月。
苏冰 step fingerprint 含 since/through 等上下文；新增目标日期不能让查询范围变化伪装成源修订或改变既有状态。
允许为此提取稳定计算上下文，但必须用批次/重启/全量 parity 证明公式与旧结果完全不变。

通过既有维护/读取锁或受保护的内容身份快照取得一致输入。锁内只做必要读取/确认，计算和 DB 长操作在锁外。
每个正式 batch commit、最终 publish 前重新验证源身份；必须封闭“验证后源又被改”的时间窗：
使用现有共享读保护覆盖最终复核与短 DB 提交，或证明所消费内容不可变且提交时 active 指针一致。
若现有设施不能提供该保证，做最小共享 seam，不能以两次无锁 hash 宣称已消除竞态。

## 6. 首次 build 与 resume

1. plan/dry-run 只读完成全范围校验；任何生产写入仍需明确外部授权，CLI --apply 不是授权事实。
2. execute 复核 plan hash、代码模型身份、环境和源依赖；ensure disabled stream、create candidate，返回 revision receipt。
3. 分块保存 seed 描述并 seal 初始 checkpoint。初始 reference 必须 FLAT；禁止把已经回放完且 OPEN 的末 checkpoint 当 seed，
   否则没有对应持久交易/动作却声称历史已经构建。indicator warmup 也须遵守 P2 codec 对状态一致性的要求。
4. 使用 P2 逐 Bar 与公共 reducer 推进，保留每个有序 transition，组成 PreparedBatch 原子提交。
   无信号也写 checkpoint/mark；owner/质量 boundary 包含在正式顺序中，同 Bar 必须按 P1 封口规则处理。
5. batch_key 由 revision、前置输入位置、输入身份与终点产生；不含墙钟、随机数或输出 hash。
6. 持久化行数/动作/交易/marks、末 OPEN 和 checkpoint 一致性检查；测试全量对照不能只检查交易数量。
7. 完整完成且当前依赖匹配后 publish。普通追加中的旧 active 可继续读取；已知失效旧结果不能继续标 READY。
8. resume 用已有 candidate，不新建一个相同任务；seed chunk 相同重放 no-op，差异 conflict。
   计划输入身份变化则 SOURCE_CHANGED，停止原 resume，重新 plan，不能悄悄吸收新历史。

分块点不能制造换月/缺价事件，不能把每包末尾当样本末平仓。需测试跨包的 OPEN、反手、同 Bar 和边界。
build 失败只保留不可见候选；单流失败不阻止其他独立流按计划完成，整体结果如实标 PARTIAL。

## 7. 正常 advance

1. 只读加载 active checkpoint、完整策略状态和旧 manifest；advance 不创建不存在的历史基线。
2. 计划固定新的完成截点；没有新输入且依赖未变返回 noop，零业务写入。
3. 校验旧依赖：不变且仅尾部扩展走 DependencyAdvance；旧内容变化转 REBUILD_REQUIRED，不能按追加覆盖。
4. 只评价新增 Bar 与必要新 owner 预热，不再运行旧历史 projector，不重复计算原指标前缀。
5. 原子提交新动作、trade changes、marks、checkpoint 和 manifest；enabled 始终 false，historical apply 不等于启用 worker。
6. 源或 CAS 冲突停止该流，不能吞掉异常自动从最新状态猜测继续。

source read 与策略 step 用 spy/counter 验证：允许为完整性读取旧依赖，但策略 step 数只能对应新增输入与必要预热。

## 8. 修订 rebuild 的本版明确策略

识别最早受影响依赖，报告触发原因（行情/映射/Session/质量/历史起点/版本）。
先将已证明失效的 revision 标 invalid，保留旧事实与诊断；新 candidate 成功后再切换。
旧输入不可证明的情况保持 BLOCKED/待核定，不把“验证失败”伪装成正常零交易。

P3 暂无向新 revision 安全复制前缀动作/交易的接口，单纯装载一个旧 OPEN checkpoint 会丢数据库前缀。
因此 P4 首版对受影响 stream 做完整重建，复用相同逐 Bar 算法与分块恢复；其他 stream 不重建。
正常尾部追加仍必须真正增量。报告明确 `rebuild_scope=stream` 与预计成本；预算不足停止，不静默扩大预算。
精确 checkpoint 前缀拷贝优化不是本版完成条件，不能为声称“局部重算”而漏掉已 CLOSED 交易和跨边界 OPEN。
公式/模型版本变更创建新 stream，不作为原 stream 的源修订覆盖。

## 9. CLI 与预算

新增语法：

```text
guiyi reference plan --request <json-path> --output <plan-path>
guiyi reference build   --plan <plan-path> --expected-plan-hash <sha256> [--apply]
guiyi reference advance --plan <plan-path> --expected-plan-hash <sha256> [--apply]
guiyi reference rebuild --plan <plan-path> --expected-plan-hash <sha256> [--apply]
guiyi reference resume  --plan <plan-path> --resume-token <json-path> --expected-plan-hash <sha256> [--apply]
```

无 --apply 全部只读：不 ensure_stream/create_revision，不写诊断表、不迁移、不自动建 seed。
plan --output 只保存用户指定的任务计划文件，不写业务数据；已存在输出默认拒绝覆盖。
不默认连接可销毁测试库以外的环境执行 mutation；真正执行仍服从用户环境和精确授权范围。
CLI root 的 `_execution_is_readonly` / parse-error 分类必须覆盖新 domain，不能掉入 data_command 属性错误或误判写权限。
JSON 解析拒绝重复键、未知字段、超长内容、非法日期/布尔冒充整数/NaN、重复 streams、非法路径和未来 as_of。
operation 与计划一致，resume 不能改变目标、窗口、manifest 或分包约定。

初始工程默认：单计算 worker、batch 最多 256 个已封口正式 Bar、seed chunk 复用 P3 256 KiB 上限；
request 必填总 max_streams/max_input_bars/max_elapsed_seconds/max_input_bytes，正整数且严格校验。
elapsed 预算用单调时钟，输入数量含 warmup；预算耗尽在批次边界安全停止，保留最后有效 receipt。
取消不提交部分批次；DB 提交结果未知先 read_batch，不盲目自动重试。首版自动重试次数为 0；恢复由明确 resume 驱动。
禁止无界读取整个品种历史到内存；若现 reader 只支持全量物化，增加共享有界读取或在 plan 明确拒绝超预算，不能虚报流式。

## 10. 开发任务与验收

### T1：严格计划与只读输入（先于任何写入）

- [ ] 实现 planning.py、typed historical input seam、composition，复用现有 authority。
- [ ] 测试 identity/日期/预算/manifest、缺数据/预热/完成周、夜盘/owner horizon。
- [ ] spy 证明 dry-run 零 DB mutation、零 provider、零 Redis/通知。

### T2：P3 最小依赖扩展

- [ ] 补 DependencyAdvance 和必需只读状态查询；append proof 只由可信输入层生成。
- [ ] 测试旧调用不变、旧 digest CAS、前缀冲突、同分区合法追加、manifest 与进度同事务、未知提交 readback。
- [ ] 真正隔离 PG 验证并发/事务；复跑 P3 原测试，不以 SQLite 替代。

### T3：首次构建与恢复

- [ ] 实现分块 seed、candidate、PreparedBatch 组装、publish、resume 与逐流 report。
- [ ] 测试 seed 前/中/后、批次提交前/后 crash、候选不可见、重复 resume 和尾段缺失。
- [ ] 验证跨包同 Bar 动作、OPEN、换月、D1质量边界与恢复后的全部输出一致。

### T4：增量与修订

- [ ] 实现 noop/append/rebuild_required 分流；恢复 P2 全状态，正常增量不 replay 原前缀。
- [ ] 实现已失效标记和受影响 stream candidate 重建；依赖复核覆盖提交竞态。
- [ ] 测试 EMA早期修订影响到最新、映射/Session/质量变化、多流部分失败、发布前源漂移、初始起点扩大。

### T5：CLI 与业务回归

- [ ] 注册 plan/build/advance/rebuild/resume，strict parser、JSON输出、只读分类、安全错误。
- [ ] 用真实临时 Canonical/Catalog/MDS fixtures 串到隔离仓储，覆盖苏冰四周期和牛哇三策略已有周期矩阵；
  不以 fake reader 的通过替代真实读取接线验证，不为 fixture 启用真实 RQData。
- [ ] 逐字段比较 legacy/public projection、batch运行与恢复运行：动作、交易 ID/状态/价格/收益、marks、末checkpoint。
- [ ] 基准记录新增 Bar 数、step 数、内存、写入量；修订成本与正常增量分开报告。

### T6：独立 Review 与交付

- [ ] 独立审查时序、manifest演进、seed/OPEN一致性、并发提交、源变动竞态与CLI授权边界。
- [ ] 修复 Confirmed Issue，更新新 canonical 的 P4 能力与 TESTING；不提前描述 P5/P6 为 active。
- [ ] 完成定向/关联回归、diff/secret检查；commit/push及条件满足的develop集成。
- [ ] 列出生产 migration/bootstrap、HTTP/Web、worker 的外部/后续 Gate，不能把 P4 代码完成写成上线。

## 11. 新增测试文件与运行入口

拟新增 `services/quant-api/tests/reference_trading/` 下：
`test_historical_planning.py`、`test_historical_inputs.py`、`test_dependency_advance.py`、
`test_bootstrap.py`、`test_historical_incremental.py`、`test_revision_rebuild.py`、`test_reference_cli.py`、`test_historical_integration.py`。
PG专项放入既有隔离PG测试或新增明确受guard保护的模块；不在普通pytest里自动找生产连接。

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q -p no:cacheprovider --tb=short \
  services/quant-api/tests/reference_trading

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q -p no:cacheprovider --tb=short \
  services/quant-api/tests/test_subing_reference_projection.py \
  services/quant-api/tests/test_subing_reference_service.py \
  services/quant-api/tests/newow/test_reference_trades.py \
  services/quant-api/tests/newow/test_reference_statistics.py \
  services/quant-api/tests/newow/test_product_replay_invariants.py
```

运行前用 rg --files 核对；PG按 TESTING.md 专用可销毁库的guard执行。skip不算PG通过。
本计划创建时未执行上述测试，不引用 P3 旧结果冒充 P4 新证据。
