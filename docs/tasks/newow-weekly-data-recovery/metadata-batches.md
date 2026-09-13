# 247 目标：有界元数据缺键计划与分阶段审批批次

## 当前终态（23:40:49 CST）

batch-03 的 6,065 行 Session 已单次提交并读回；剩余 04/02/01 本轮也已完成全部 23,537 个元数据
响应下载，形成 27,159 行 Session 快照（7,012 日期），原生离线校验与逐条 journal 对照通过，尚未入库。
四批均不重下载。当前下一步与精确 snapshot hash 以[实施计划 R1–R6](implementation-plan.md)为准。
owner 最新已取消流量估算、额度探测及旧 900 MB 预测门槛；下文为历史计划及审批过程，不覆盖当前意图。

## 初始计划时的结论与授权边界（历史）

2026-09-13 22:41:44–22:42:26 CST，在固定源码 `5b31cf7c1ceb5350d4a5ea0a3d9328635d0ea62d`
上完成四批原生 metadata plan。247 个目标全部覆盖，共 8,708 个唯一 Session 日期键、29,325 个唯一
规划请求；Calendar 缺键为 0。**这不是下载或写入结果。** 实际 provider 请求和生产写入均为 0。

本轮 owner 授权生成计划并提交批次，不授权执行 fetch/apply。四批是当前 Catalog 快照上的候选，
不是可无条件连续执行的队列。优先提交请求数最少的 batch-03；执行前仍须核实当日共享配额和预算、
取得该批精确单次 fetch 意图，并通过原生 recheck。不能证明预算安全时应缩批重新规划，不执行整批。
当前没有 snapshot，因此**尚不能提交可执行的精确 DB apply 批次**；先提交下述写入边界，取得真实
响应后再补齐 snapshot hash、实际行清单和行数，单独申请 apply。不得用计划 hash 代替 snapshot hash。

## 权威文件与来源

原生文件根目录（主仓库内、独立于本 task worktree）：
`/Volumes/扩展盘/guiyi-quant-workstation/outputs/newow-weekly-data-recovery-20260913/metadata-plans-247/`。

- `batch-01-targets.json` 至 `batch-04-targets.json`：分批输入。
- `batch-01-plan.json` 至 `batch-04-plan.json`：精确 resolved_targets、missing_sessions、requests 和原生 hash；
  是执行范围权威。本文只是这些文件的摘要，不能用于重新拼装或扩大请求。
- `invocation.json`、`execution.json`：固定源码身份、输入范围及终态；exit 0、stderr 0、来源与配置元数据未变。

输入为同级 `isolated-5b31cf7c/recovery-index.json` 关联到原始报告的 494 行提案、247 个唯一
symbol/contract/through 目标。原始报告 SHA-256：
`787393d159b0bde955b7258e1251ad24730d45cd18b5a6dfc073db6f33879ff8`。
固定源文件清单摘要：`cb0eb0aacf38442a54c43496e251301586cd1c62daf65110201fd2461eb8e1fe`。

四批在同一 PostgreSQL repeatable-read、read-only 事务内串行规划；原生 validator 逐批通过。
maintenance advisory lock 预检无占用，这不是持有维护锁，也不保证之后执行时无并发维护。

## 精确下载候选批次

| 批次 | 目标数 | Calendar 缺键 | Session 日期键 | 元数据请求数 | 缺失 Session 日期范围 | plan 文件 bytes |
| --- | ---: | ---: | ---: | ---: | --- | ---: |
| batch-01 | 64 | 0 | 1,547 | 10,135 | 2020-03-02–2022-12-30 | 3,053,307 |
| batch-02 | 64 | 0 | 1,458 | 7,366 | 2021-06-16–2022-12-30 | 2,197,910 |
| batch-03 | 63 | 0 | 1,696 | 5,788 | 2022-02-16–2022-12-30 | 1,584,587 |
| batch-04 | 56 | 0 | 4,007 | 6,036 | 2022-03-15–2022-12-30 | 2,667,013 |
| 合计 | 247 | 0 | 8,708 | 29,325 | 非连续缺键集合，以原生文件为准 | — |

各批完整 plan_sha256：

- batch-01：`3a2b4df0a3cafc420bcc56b64d4a46394e499927e5404666ab6d68ac8862739f`
- batch-02：`1ebae39934ed0d096585efebdb8223c6a17099921a03383a8db49543bb0ca3d7`
- batch-03：`5d8073346f7f5ff96edaccc00d8b75706e397ffed2cacb1fb43b9626025a6e5a`
- batch-04：`a8178e215b376b054d1dafcbe8f5b60bd7706cb62dae8315b80017d5fb3459d1`

品种分组：

- batch-01：al、b、cu、eb、sc。
- batch-02：bu、ni、pb、sn、ss、zn。
- batch-03：ag、c、fu、jd、lh、pf、pg、sf、si、sm。
- batch-04：ap、cf、cj、eg、fg、hc、i、j、jm、l、m、ma、oi、p、pk、pp、rb、rm、rs、ru、sa、sr、ta、ur、v、y。

所有请求均为 `get_trading_periods`，每条 start_date=end_date，frequency=1m 是交易时段元数据参数，
**不是 1m OHLCV 下载**。没有 get_trading_dates 请求。每个缺键必须核对计划中的全部 source_contracts；
同日多合约来源不是重复请求，不得静默裁掉。最大同日来源数分别为 20、11、10、4。
RS2311 两个不同 through 保留在目标中；重叠请求由原生 planner 去重。

表中日期只是缺键最早/最晚日期，不是批准连续全区间抓取；请求列表限定精确合约和日期，生命周期
和 effective_through 以 resolved_targets 为准。现有 Session 日期保留计数分别为 1,548、1,512、
2,009、3,972；保留不等于证明那些日期的 Session 完整。

## 下载与写入 Gate

### Fetch：每批单次、只下载元数据

审批对象为该批原生 plan 文件及完整 hash、其中固定 requests。复核固定源码及导入来源、Catalog
基线、维护窗口和共享当日用量；原生 recheck 必须发生在 provider 构造前。执行仅保存该次源响应
snapshot，不写 production DB 或 Canonical，不自动追加分类请求、扩大目标、重试或重放。

首批候选输入为上述根目录下 `batch-03-plan.json`，完整 hash 见表下清单；拟新增响应文件为同目录
`batch-03-snapshot.json`，拟新增后续 apply 结果为 `batch-03-apply.json`。两个输出均尚不存在、尚未授权
生成；执行前检查路径及不存在，不覆盖已有结果。其余批次同样按实际批次单独提交输入和新输出路径。

900,000,000 bytes/日约束不是当前 fetch 实现的硬上限。29,325 次请求或 plan 文件 bytes 均不能推出
RQData 消耗；当前没有真实 quota 前后值，不能声称预算已验收。必要时按整品种细化成新原生小批计划，
保留所有关联物理来源，重新提交 hash，不切片 JSON 冒充原生计划。现有 batch-03 中 SI 为 5 目标、
7 个缺键、35 请求，仅可作为后续小批规划候选，**没有可执行的 SI 独立 plan**。

CLI 对每个输入文件有 16 MiB 限额。当前四个 plan 均低于该限额，但将来 snapshot 包含 plan、
全部响应和归一化数据，大小仍未知，不能承诺全部可直接 apply。超限时保留响应，停止 apply，评估
新的缩批方案并重新取得必要意图；不截断响应、不放宽校验。任何失败/漂移/源冲突均停止该受影响批，
已经消耗的配额如实记录，不自动重试。

### Apply：真实响应到齐后才能精确审批

每批未来允许写入的业务范围仅为该 plan 的 missing_sessions 日期，Calendar 行数应为 0；
实际 Session 行数目前为 null，因为一个日期可能对应多个交易时段。写入只补整日缺键，不覆盖或
拼接已存在的日期，不变更 contracts、instruments、exchanges、MainContractMap 或 Canonical 行情。

提交 apply 前必须提供实际 snapshot 路径、snapshot_sha256、匹配 plan_sha256、blockers=[]、
响应完整性/合约来源一致性/夜盘证据检查、实际 Session 行清单及行数、文件大小和消耗证据。
未知、矛盾、缺响应或夜盘证据不足均不得进入写入。

原生 apply 使用 READ COMMITTED，lock_timeout=5s，对 exchanges、instruments、contracts、
trading_calendars、trading_sessions 五表取得 SHARE ROW EXCLUSIVE 锁，再重做原生 plan 并要求完全相等，
一次 insert-only commit。**不是以 maintenance advisory lock 代替表锁。** 表锁可能与其他维护竞争，
不通过停服务、抢锁或自动重试继续执行。

提交前失败回滚；commit 结果不明先对精确键和行做只读对账，停止后续 apply。已提交事实保留，
不自动删除。重复执行旧 plan 会因基线漂移阻断；通过重规划确认已填键不再出现，不把重放旧批准当幂等。
四批 Session 键和品种无交集，且本轮没有 Calendar 写入，避免了相互 Session 写入重叠；仍需每批
重新核查共享 Catalog 事实，不把同一快照的四份 hash 当长期有效许可。

## 异常隔离与验收

本批 PF 是 2023 年相关旧合约，不含 PF2611；RS 仅 RS2309 和 RS2311 的历史元数据目标，不含
RS2407、RS2409、RS2411、RS2507、RS2509、RS2511、RS2607、RS2608、RS2609 九个专项对象。
元数据补齐不表示非正 OHLC 价格或分区完整性已修复；896 个普通补数候选和 PF/RS 专项均未执行。

已验证：目标并集精确等于 247 个源目标、跨批 target/Session key/request 无重复、47 品种不跨批、
原生 plan validator 通过、provider_requests=0、production_writes=0、执行 exit 0。
固定副本 test_bounded_metadata.py + test_cli.py：168 passed。实际命令入口见 TESTING.md 的 metadata
和 repository hygiene 章节；本任务无生产代码、策略、STATUS、Runtime 或发布变更。

另一次可选 SI 小批只读规划进程 exit 1，未生成 plan，provider fetch/apply 均未进入；未将该失败当成
有效批次，也未重试。它不影响已成功保存的四批，首批仍以本表和现有原生文件为准。

计划状态：完成；整体数据修复：未执行。最终验收仍需获准 fetch、精确 apply、缺键只读归零检查和
MDS/readiness 读回，不能把本次计划完成表述为数据恢复完成。

独立只读 Review：REVIEW_COMPLETE — NO_BLOCKING_FINDINGS。审查者重新核对目标并集、键/请求去重、
四个原生语义 hash、validator、预算及 fetch/apply 边界，允许提交计划，不授权执行。保留风险：
大批下载可能已消耗配额，但生成的 snapshot 超过 16 MiB 而不能直接 apply；批准前应缩批，或明确
接受这一风险。规划树 hygiene/canonical consistency 22 passed、OpenSpec 9 passed、secret scan
0 findings；新增文档空白检查无问题。结论：允许继续实现；受控下载和写入保持 EXTERNAL_GATE_PENDING。

后续真实配额核实记录于持久 evidence 根的 `metadata-plans-247/batch-03-fetch-*` 原始 JSON：22:57:48 CST，
账户当日已用 5,600,535 bytes，按项目 900 MB 停止线剩余 894,399,465 bytes。余额不证明整批成本；
原生 fetch 没有项目硬限额，整批预算 Gate 尚未闭合，不能将先前“优先 batch-03”解读为允许立即下载。

其后 owner 明确批准直接下载 batch-03 并接受超额风险。23:07:35 CST 一次 fetch 成功：5,788/5,788
响应、账户用量增量 4,065,221 bytes；snapshot 3,694,308 bytes、prepared、blockers=[]，没有超额。
精确 snapshot hash、6,065 行 Session 的 apply 终态与独立离线验收见[本任务执行就绪记录](execution-readiness-20260913.md)
及持久 evidence 根的 `metadata-plans-247/batch-03-apply-*` 原始 JSON。
仅 batch-03 下载完成，生产写入仍为 0；其他三批、普通补数及 PF/RS 专项未执行。

后续 owner 单次批准 batch-03 apply，23:14:47 CST 已成功新增 6,065 行 Session、Calendar 0。
新事务逐行核对 6,065 行、共享 Session 读取入口解析 1,696 日期通过；原 63 目标重规划缺键/请求均为 0。
本批元数据闭环完成，但其余 184 目标未执行；终态见[本任务执行就绪记录](execution-readiness-20260913.md)
及持久 evidence 根的 `metadata-plans-247/batch-03-*` 原始 JSON，不据此宣布全体恢复。
