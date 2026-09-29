# P7-10 NI 四周期历史候选处理

状态：**PARTIAL / DEFERRED_DATA_BLOCKED，0/12 页面闭环**。首个维护单元原子发布失败后已停批；没有重试、续接或构建候选。仅 NI，固定 4 输入、8 基础、4 融合、12 页面，固定 21 品种分母及其余队列不变。1m 仅为四派生周期的 Canonical 来源。

冻结 develop/源码 `eb3dddb837e5c1b71208d273d1a6775d323e0dfd`，分支 `codex/ni-minute-closeout`，隔离工作区 `.worktrees/ni-minute-closeout`。native managed worktree 返回 `Not a git repository`，按不可用回退使用 Git 隔离副本。无产品源码、公式或正式配置变化。原始证据和 helper 保留于主工作区 `outputs/ni-minute-closeout-20260929/`；本项只提交本记录、STATUS 入口和 P7-10 行，不提交行情、响应、配置或秘密。

## 身份、范围及前置校验

页面窗口 2023-01-01..2026-09-24，as_of `2026-09-24T07:00:00.000001+00:00`。仓库 NI 产品窗口起点为 2015-03-27（`rq_or_listing_start`），Instrument 没有产品上市日期字段；不把 NI2302 的物理上市日冒充产品上市日。41 个实际 rank1 owner 均由 NI 自身 Map/MDS 解析，41 合约唯一，无 owner 重入。完整物理生命周期 warm-up 从各合约自身 listed_date 到 owner-through；首单 NI2302 为 2022-02-16..2023-01-19，未缩成页面窗口。

初始及停批后均为 **7/164 DATA_READY、157/164 缺前缀**，12 项资产查询均无保存流。四个完整输入0/4、基础0/8、融合0/4、页面0/12；新增及复用 Reference 资产均0。源 readiness 失败保持原生 `NEWOW_DATA_UNAVAILABLE / DATASET_OR_PARTITION_MISSING`，不使用连续合约、Live 或其他周期替代。

164 份原生 contract_warmup dry-run 去重为最多 **414 源请求、1710 派生月**，同1m key跨四频的目标字段独立逐值核对一致。源预期3,666,390 Bar、派生1,236,402 Bar。初始账户余量1,004,748,197 bytes；全包1024 bytes/Bar项目估算3,754,383,360 bytes超过该余量，记录 `overall_theoretical_budget_pass=false / completion_guaranteed=false`。采用执行前冻结的逐原生单元及锁内 fresh quota gate，最大单元估算102,097,920 bytes；不把估算称为供应商上限、不保证整包可完成，不放宽源次数、累计预算、窗口或数据标准。

NI 自身 Calendar/Session 只读证据覆盖物理前缀：夜盘21:00..01:00，与 AG 时长不同；日盘09:00..10:15、10:30..11:30、13:30..15:00。历史前缀内未观察到时间对变化；24个节后交易日的 NI Session 无夜盘，沿用原生品种事实，不从交易所共享 Calendar 标记伪补夜盘。30m合法15分钟尾、60m合法15/30分钟尾保持原生合同。完整周端点、换月页面与日周兼容未验收。

既有 NI2302 真正1m样本5805 Bar在本项outputs同盘 scratch 原生发布及严格读回通过，SHA与原文件相同。空间约775GB、共享锁0；scratch只证明该样本，不能证明后来失败响应可发布。独立范围 Review、14项scope测试通过后才运行真实维护。

## 实际发布与失败边界

campaign 文件 SHA `6a39f68f50657861a69ef7e5299a03ab5926bc0d7609f845bda91c02515cb219`；NI2302/5m原生计划 hash `a216f8855468633d53b513075423d198c9d509207ba363a948efc90637747f4a`。原campaign与原单元attempt均保留 `PENDING / retry_allowed=false`，没有native result或campaign-complete。`completed=[] / provider_requests_known=0`只计完整返回成功单元，不能据此声称零写入或零下载。

首单已实测发起 **8个逻辑1m源请求**（BoundedProvider计数，非SDK内部网络次数），随后 `StorageError / ATOMIC_PUBLISH_FAILED`，底层 `ArrowInvalid`。立即停止全部后续 mutation，不重试、改hash、缩窗、造数或改变schema标准。

新独立只读事务确认已发布 **NI2302 2022-02..08 的7个1m及7个5m分区，共14新增pointer**，1m共62,055 Bar、5m共12,411 Bar。全NI五频初始525分区变为539，原525分区hash/row_count不变；其他40 owner无新增/变化。NI2302原29个七频文件/旧Bar及24个D1/W1 pointer完全保留，零替换。14新immutable文件SHA、Parquet行数和原生 strict reader通过。

最早剩余源目标为 **NI2302 / 1m / 2022-09**，9,525预期端点，`2022-08-31T13:01:00+00:00..2022-09-30T07:00:00+00:00`。该1m及5m目录为空；剩余同单元目标8（4源、4派生），共享维护锁0。由串行源请求/发布路径和实际前缀推断第8请求在该目标发布失败；未保存失败响应或异常正文，不能将这项推断冒充记录了完整失败Bar的根因证据。

底层具体原因仍 **UNKNOWN**：只知道 ArrowInvalid，不能据此宣称 NI 专属来源质量问题、共享存储损坏或已修复。生产提交边界已核清，已发布14分区保持，不批量“回滚”；失败单元不重跑，其他40 owner未启动。FU旧失败也未触碰。恢复必须先取得可验证失败原因、来源和恢复合同，不能靠再次授权或改hash替代安全证明。

停批后quota读回上限1,073,741,824、已用72,164,028、余量 **1,001,577,796 bytes**。账户delta不等于本项消费，失败响应实际字节和供应商内部网络次数未知。`quota-final.json`复制的limitation错误写“未开始NI attempt”；原样本保留，`quota-final-interpretation.json`绑定原SHA纠正为已发起8个逻辑请求，不改写数值或伪造消费归属。

## 实际验证、限制及安全隔离

所有helper绑定冻结 worktree，显式 `PYTHONPATH=<frozen>/services/quant-api:<frozen>/packages/quant-core:<frozen>`，使用现有quant-api venv；私有配置只由既有程序加载。sandbox第一次依赖查询OperationalError保留，宿主read-only事务成功，不将sandbox连接限制归类为NI数据缺陷。

- `inventory.py`、`dependencies.py`、`plan.py`：41owner/164依赖/12空资产及全部原生dry-run；零provider/生产写入。
- `quota_current.py`、`preflight.py`：账户quota只读及scratch发布/读回PASS；精确scope/budget/Session独立审查通过。
- `campaign.py --apply --expected-plan-sha256 6a39f68f50657861a69ef7e5299a03ab5926bc0d7609f845bda91c02515cb219`：**exit1 / ATOMIC_PUBLISH_FAILED**，不表述为维护通过。
- `failed_readback.py`：修正只读helper误用不存在的`get_partition`接口为`all_partitions`后PASS；首次AttributeError日志保留。该修正只重新读取，不重新执行维护。
- `inventory_final.py`、`dependencies_final.py`、quota最终样本：525旧五频保留、14实际新增、7/164ready、零资产、锁0；原生七频/目标目录/剩余plan读回PASS。
- 独立离线旧bytes/新SHA/行数审查：`independent-stopped-bytes-check.json` PASS；范围Review见`independent-scope-review.md`。`review_added_aggregation.py`实际exit0/PASS：7月62,055根源与12,411根5m逐字段一致，Decimal precision 200，夜盘previous trading day由NI Calendar证明；`complete_lifecycle_prefix_proven=false`。停止审核见`independent-safe-deferral-review.md`，允许仅安全暂缓记录集成。
- `python -m pytest --confcutdir=<NI-output> <NI-output>/test_scope.py -q`：**14 passed in 0.76s**，拒绝范围、生命周期和预算漂移、provider越界及attempt覆盖。
- 冻结worktree中`python -m pytest services/quant-api/tests/data_foundation/test_aggregation.py services/quant-api/tests/data_foundation/test_historical_session_window.py services/quant-api/tests/newow/test_reference_interruptions.py -q -p no:cacheprovider`：**58 passed in 1.19s**。

`matrix.json`固定12项 `DEFERRED_DATA_BLOCKED`，API/Chrome、主图/适用副图、完整曲线/记录、较早分页、切换/取消/超时恢复、NI自身D1/W1均 `NOT_RUN_DATA_PREREQUISITE_BLOCKED`。没有NI截图或页面成功证据，不拿AG/AU结果代替。未启动API/Web/Chrome；正式分钟、main/tag/release、Runtime/worker/消费者/Scope/audience/通知/Broker/账户未切换，`auto_order=false`保持。

本项交付为失败证据、安全隔离与暂缓记录的develop集成；**没有完成NI历史候选闭环**。剩余产品不自启，固定21分母保持。验收结论：独立停止审核已通过，**允许集成 develop（仅安全暂缓记录）**。唯一最小下一步：取得NI2302/2022-09原子发布失败的可验证原因与安全恢复证据。
