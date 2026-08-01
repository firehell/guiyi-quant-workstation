# 当前状态

更新时间：2026-08-01

本文件是项目当前状态的仪表盘：只列当前工作、未关闭 Gate、必要事实锚点与防过度宣称的红线。历史过程由 Git 提交和 final receipt 追溯。

## 当前在做什么

当前 active 执行合同为 `docs/tasks/GY-DATA-CORE-V2.md`。任务 00 已完成 canonical、
迁移顺序与治理边界冻结，并通过 PR #76 以 merge commit
`2266d7f7d285b137a2375aeb78f2c4305684b8e0` 合入 `develop`；post-merge
`engineering-test` 成功。任务 01 数据合同与 golden vectors 已通过 PR #78 以 exact task
HEAD `997d978f40245c8967530471aff0c2471c3478d5`、merge commit
`12f5dbc5447f2bc7ed35ffb3fcf18daabb145bee` 合入 `develop`。任务 02 已统一七字段
`DatasetKey`，追加 schema-only revision `20260730_0027`，并以非破坏性只读 view 收窄
canonical MainContractMap；PR #80 以 task HEAD
`9614710c2e70e7c544642d7688146231df49853c`、merge commit
`59c14ffd7e97c39814576f16dc2c413c8fafb5db` 合入 `develop`。任务 03 staging、quality 与
canonical writer 已由 PR #82 以 task HEAD
`8a892a5a55d7b29b1ca036c89d8d3972bd7ed32a`、merge commit
`3ceb57bd0661d1fd3c35401a68f2b4345eca3ae1` 合入 `develop`；其 CI module detector 修复由
PR #83 以 task HEAD `882bd64b6b4ee7f31d115c350f13e4cd95df5278`、merge commit
`b03d5e98f50d9ada4364a524ca78c92d1e0bbb42` 先行合入。任务 03 的本地测试与独立 Review
已通过；PR #82 两次 Linux run 虽因 CI 竞态跳过 Backend verification，合入后的 exact
commit `3ceb57bd0661d1fd3c35401a68f2b4345eca3ae1` 已在 official Swift Ubuntu
`linux/amd64` 容器中以 GitHub runner 目录形态、clean detached checkout、真实 `plutil` 与
uv-managed Python 3.13 完成等价补验：Ruff 通过，后端全量 `2186 passed, 36 skipped,
0 failed`，独立 Review 批准。因此任务 03 已完成验收。压缩后的新任务 04（原 04～08）
已在 exact code head `f67958c9695a6dbff3dcbd24cb788f0fe65e1f5b` 完成历史同步、统一读取、
JM dry-run/Shadow 与普通消费者切换，并进入 `develop`；该 exact SHA 的 GitHub
`engineering-test` run `30641513830` 成功。Final Review round 5 确认没有剩余
Critical/Important 阻塞项，Spec PASS、Quality APPROVED。exact-head 本地验证为 Ruff 全量通过、
Data Core `394 passed`、后端全量 `2279 passed / 36 skipped / 0 failed`、隔离 PostgreSQL
migration `35 passed`（临时库随后删除）、Web unit `169 passed / 1 skipped / 0 failed`、
Web build 通过、canonical 开关下 Playwright `18 passed`。随后在真实 0025 环境生成 approval
packet 时发现并修复两个 Gate 自锁：0025 现在以与 0027 canonical view 相同的过滤和 resolver
绑定底层 `main_contract_map` 既有 rank1 rows，0026 中间态拒绝，`apply` 仍在任何 inventory、
receipt、root、RQData/writer 前要求 0027；标准 pretty packet 的预解析有界上限为 8 MiB。
reviewed Gate-fix head `54ee8e00` 通过独立 Review，Spec PASS、Quality APPROVED，无
Critical/Important。更新后 Data Core `403 passed`、后端全量 `2288 passed / 36 skipped / 0 failed`。
功能仍默认关闭。
hash-bound 写入执行器已实现并用 fake provider、临时 SQLite/Parquet 验证；首个真实 apply
只运行到 current-facts Gate 即 fail-closed，尚未构造真实 provider/writer 或产生数据副作用。
它现在绑定 exact rank=1 mapping acquisition plan，actual-dominant 仅按 mapping-valid
session 分段写入；正式 `data migrate shadow` 会从当前 DB/session 的 canonical
MainContractMap view 取得每个 actual-dominant bar 交易日的 rank=1 证据，缺失或歧义
fail-closed，且 concrete JM contract 必须精确匹配。partial resume 不再信任可编辑
receipt；它仅是可修复缓存。可 skip 进度必须由 approved initial state、exact plan 与
当前 Catalog/mapping 重建；已验证 mapping 子集只覆盖其精确 approved days，执行器仅
将缺失日按已验证日切分为 approved-index 连续 run，每个 run 的请求起止和
expected days 均精确绑定，并在合并后强制精确全集。当前 partition 状态序列化同时包含
`file_uri/manifest_uri`，并重验 manifest digest 与物理 checksum；仅部分覆盖不得借缓存
write plan 声称完成。
生产 PostgreSQL 已在用户精确批准下完成 schema-only `20260721_0025 -> 20260730_0027`，
并核验三张新 metadata 表为空、`data_core_main_contract_map` view 可读。exact
`develop@5ba8f7c4` 的首个真实 apply 尝试在构造 RQData/CanonicalStore 和创建数据根之前
以 `approval_facts_changed` fail-closed；根因是进度验证器把 actual-dominant `1d` 的日频窗口
错误地按 1m session 重算。该 D1 Gate 自锁已用 TDD 修复并集成至 `develop@da2233b0`；同一
exact SHA 的 GitHub `engineering-test` run `30675343564` 成功。

使用绑定 `da2233b0`、从 `07:00Z` 起始的第二个用户批准 packet 执行真实 apply 时，执行器再次
fail-closed：DCE 夜盘窗口的 UTC 自然日仍为前一日，但其权威 `trading_day` 已是下一交易日，
旧校验错误地要求最后交易日不得晚于 `prepared.end.date()`，触发
`historical_apply_trading_days_invalid`。现场复核确认三张 metadata 表、mapping 增量、Parquet
文件与 receipt 均为零；apply 初始化了空的 canonical/staging、journal 与 quarantine 管理目录，
未执行 historical Shadow。夜盘修复已由 PR #86 以 task HEAD
`c163feb039fd23d16ffe6571044a135bdd698b8b`、merge commit
`e29c2940b8a4c4f0a63c88b80b6a8a4a3b7cbbb5` 合入 `develop`；post-merge
`engineering-test` run `30678204745` 成功。

使用绑定 `e29c2940` 的第三个用户批准 packet 执行真实 apply 后，rank=1 mapping 与
continuous `JM.MAIN` 的 `1m/1d` 已写入并由 receipt/DB/manifest/checksum 对账：任务窗口
mapping `3245` rows，生产 view 当前 JM rank=1 共 `3395` rows；Catalog 为 `2 datasets / 2
partitions / 0 gaps`，1m `830820` rows、1d `3244` rows。随后 continuous direct `1w` 在写入前
以 `CANONICAL_QUALITY_COVERAGE_MISMATCH` fail-closed：RQData 需要 `2013-03-22` 作为查询锚点，
但不会为该上市残周输出 direct 1w bar，首根为 `2013-03-29`。receipt 保持 `in_progress`，
historical Shadow 未执行，现场未删除或回滚已验证的部分进度。

当前 task 分支已用 TDD 将 packet-bound 首交易日残周保留为 provider query anchor，同时从
expected weekly endpoints 排除；通用 quality Gate、M1/D1、actual-dominant 与 resume
reconciliation 未放宽。真实 RQData 只读验证为 `684 expected = 684 actual`；Data Core
`408 passed`、后端全量 `2293 passed / 36 skipped / 0 failed`、Ruff 与 diff check 通过，独立
Review 为 `Spec PASS / Quality APPROVED`，无 Critical/Important。该修复改变 source HEAD，
尚待 clean commit、PR/merge、同一 exact merge SHA 的 CI、新 packet/hash 与用户重新批准，
因此任务状态仍只能是 `BLOCKED_AT_JM_REAL_DATA_GATE`。approval packet/hash 是提交后生成的
仓库外 Gate 证据，不得反写本文件造成 self-drift；旧 `5ba8f7c4`、`da2233b0`、`e29c2940`
packet/approval 均不得复用。完整真实 JM apply 与 historical Shadow 尚未完成；删除、release、
Runtime、通知与交易均未授权。

后续 resume Gate 修复已由 PR #88 合入 `develop@e3e03a9d685aa04f305eda410f219cd44571e0e3`。
在再次执行真实写入前的综合复盘又发现：同一 HEAD 的不同 initial state 会碰撞旧 receipt 路径、
actual-dominant D1 曾错误复用 M1 session、apply 没有严格终态 receipt、真实 provider 没有独立
85-DatasetKey 只读预检，以及 Shadow 的双空输入会被误判通过。当前独立 task branch 已收口
这些 Gate：receipt v2 绑定 approval basis + packet hash 并自校验 digest，passed 终态不可变；
current-state 中冻结并复验 85 个非空 execution runs；`migrate preflight` 只调用 RQData 读取和
内存 quality/Arrow representability 校验，精确 85/85 passed receipt 才允许 apply；Shadow 任一侧
为空、共同遗漏 expected bar、缺月块、矩阵不精确或声明 exception 未被消费均 blocked；
生产 Shadow 改为 approval-plan-frozen legacy exact IDs/evidence/path/SHA256 + Catalog/manifest
canonical 的按月分块读取，不再接受 caller-supplied 整包 JSON；读取前和 receipt 前复验 legacy，
结束时重建 current state 并逐 partition 复验 canonical 物理证据，绑定 apply receipt/state、
source/chunk/exception digests。生产只读复核为
`41 contracts / 3245 mapping rows / 85 dataset plans / 85 nonempty execution runs`，没有调用
RQData，也没有写 PostgreSQL、Parquet 或 receipt。聚焦测试 106 项、Data Core 436 项、后端
2322 项（另 36 skipped）及 engineering 192 项均通过；独立 reviewer 最终为
`Spec PASS / Quality APPROVED`，无 Critical/Important。上述 hardening 已由 PR #89 以 task
HEAD `d892e916`、merge commit `ca7125a2` 合入 `develop`，同一 merge SHA 的 post-merge
`engineering-test` run `30694755868` 成功。随后生成的新 packet 在用户批准后启动真实 preflight，
但在构造 RQData adapter 或产生 PostgreSQL/Parquet/receipt 写入前以 `approval_facts_changed`
fail-closed。根因是 progress Gate 以单值字典重算 actual-dominant 1m execution run，同一 trading day
的夜盘、上午和下午多段 session 被最后一段覆盖；生产 JM1307 冻结 run 为 `01:00-07:00Z`，
旧重算只保留 `05:30-07:00Z`。当前最小 TDD 修复改为聚合同一 run 的全部 session，生产只读
current-state 重算已通过；该修复改变 source HEAD，旧 packet/hash/approval 已失效，仍须新的
exact merge SHA、CI、packet/hash 和用户批准。Task 04 保持 `BLOCKED_AT_JM_REAL_DATA_GATE`。

用户已将旧 S6-10 标记为
`S6-10_PAUSED_BY_OWNER_FOR_CORE_CONVERGENCE`：schema-v4～v7 合同、packet、receipt 与
失败/通过 evidence 全部冻结为历史，不再生成 fresh C2、Approval D、daily child，不执行
旧合同的 mapping、部署、Runtime、通知或真实验收。

旧 `GY-CORE-04～08` 路线已 `superseded / paused`，不得继续执行。`GY-CORE-02` 的 JM
兼容 Facade 与 `GY-CORE-03` 的只读 CLI 壳可在新路线中复用，但旧 Profile/Binding active
selector 不再扩展；已合入的 `GY-CORE-04` ObservationPlan/Adapter 代码保留为 legacy
compatibility，不构成新路线的 Shadow、Runtime 或通知入口。

新路线按任务 00～19 串行执行：先冻结合同，再完成数据合同、Catalog/Manifest/Gap、
canonical writer、统一读取、JM 迁移与消费者切换，之后才处理 live/SignalDecision/EOD、
其他已有品种、legacy 删除和新版单交易日 Runtime Gate。未来 Shadow 与新版 S6-10 仍只验收
一个完整 DCE 交易日；该设计不表示 Runtime Ready。

任务 02 代码已通过独立 Codex Review、35 项隔离 PostgreSQL 16 migration 测试和 exact-head
CI 后进入 `develop`。生产 schema 已在 Task 04 专用 Gate 下升级到 `20260730_0027`；这只证明
schema migration 完成，Catalog 数据写入和真实数据迁移仍需新的 exact-head 专用 Gate。

## 未关闭 Gate

| 项 | 状态 | 说明 |
|---|---|---|
| HTDY XMA 语义 | blocked | 保持 `HTDY_FORMULA_OR_XMA_SEMANTICS_UNRESOLVED`，不重开公式审计 |
| Audit V2 residual triage | pending | 解释 calendar/session/physical/quality residual 后再决定受控任务 |
| 全历史 residual triage | pending | 不得将消费者 Ready 扩写为所有历史资产零 residual |
| GY-DATA-CORE-V2 task 00 | completed on develop | PR #76；task HEAD `67cb7f3427329aa5df29bf63686bc762556752f7`；merge commit `2266d7f7d285b137a2375aeb78f2c4305684b8e0`；未授权真实副作用 |
| GY-DATA-CORE-V2 task 01 | completed on develop | PR #78；task HEAD `997d978f40245c8967530471aff0c2471c3478d5`；merge commit `12f5dbc5447f2bc7ed35ffb3fcf18daabb145bee`；116 项合同/Schema/聚合测试通过；无真实写入 |
| GY-DATA-CORE-V2 task 02 | code and isolated migration validation completed on develop | PR #80；task HEAD `9614710c2e70e7c544642d7688146231df49853c`；merge `59c14ffd7e97c39814576f16dc2c413c8fafb5db`；35 项隔离 PG16 migration tests；生产 apply 未授权 |
| GY-DATA-CORE-V2 task 03 | completed on develop | PR #82；task HEAD `8a892a5a55d7b29b1ca036c89d8d3972bd7ed32a`；merge `3ceb57bd0661d1fd3c35401a68f2b4345eca3ae1`；本地 142 targeted、319 data_core、191 engineering tests；post-merge exact Linux backend `2186 passed, 36 skipped, 0 failed`；Ruff 与独立 Review 通过；无真实写入 |
| GY-DATA-CORE-V2 task 04（原 04～08） | BLOCKED_AT_JM_REAL_DATA_GATE | receipt/preflight/Shadow hardening 已由 PR #89 合入 `develop@ca7125a2` 且 post-merge CI 成功；生产 schema 为 `0027`，partial canonical 为 continuous 1m/1d。首次真实 preflight 暴露多 session execution-run Gate 自锁并在 RQData 初始化/生产写入前 fail-closed；当前最小修复待合并、exact-SHA CI、new packet/hash 与批准，真实完整 apply/Shadow 未完成 |
| GY-CORE-02 Facade / GY-CORE-03 CLI | legacy compatibility / reusable shell | 可复用，但不得继续扩展旧 Profile/Binding selector |
| GY-CORE-04～08 | superseded / paused | 04 代码保留；05～08 禁止按旧路线继续 |
| 旧 S6-10 | paused / frozen historical | 不再执行；恢复入口仅为 `GY-S6-10-R2` 单交易日合同 |
| JM Runtime 验收 | pending redesign | 单日自然运行 + 同一 exact release 独立恢复证据 + 独立 Review + 用户最终批准 |
| 真实公网安全 smoke | pending | TLS、Basic Auth、端口不可达与 FRP/Nginx 重启恢复 |
| V1 最终验收 | pending | 仅在各独立 receipt 与新版 JM Runtime Gate 完成后进行 |

task 自动集成只适用于通过验收、CI、独立 Review 且 exact head 匹配的可逆开发变更。
生产 migration、真实数据/DB 写入、删除、`main`/release/tag、Runtime/live enable 和真实通知
仍是人工 Gate；代码进入 `develop` 不构成这些操作的批准。

## 必要事实锚点

| 事实 | 当前值 | 证据 |
|---|---|---|
| PostgreSQL revision | `20260730_0027` | Task 04 用户批准 migration + Alembic/SQL 现场核验 |
| HTDY S6-08 | 已完成限定自然事件与幂等验证；autosend=false | `docs/tasks/JM-LIVE-SIGNAL-EVENT-S6-08.md` 与 final receipt |
| S6-09 单条企业微信 | event 4 only；notification 2；attempt=1 | `data/reports/jm_live_wecom_single_s6_09/` final receipt |
| 旧 S6-10 | owner-paused；schema-v4～v7 frozen historical | `docs/tasks/JM-LIVE-STABILITY-S6-10.md` |
| 新数据核心 active target | design frozen / tasks 00～03 accepted；task 04 code accepted on develop，blocked at real-data Gate | `docs/tasks/GY-DATA-CORE-V2.md`、`docs/ARCHITECTURE.md`、`docs/DATA_CENTER.md` |
| legacy compatibility | GY-CORE-02/03 可复用；GY-CORE-04 代码保留；04～08 旧路线不再执行 | `docs/tasks/GY-CORE-CONVERGENCE.md` |

## 不可宣称

- 不可把数据、消费者或 archive Gate 写成所有历史资产零 residual、Runtime Ready、长稳 Ready、通知 Ready 或自动交易 Ready。
- 不可把 active target、任务 02 已合入代码或任务 00 文档冻结写成数据迁移、生产 migration、
  Profile/Binding 删除、消费者切换或新 `MarketDataService` 已完成。
- `LONG_RUNNING_READY=false` 仅为 `deprecated / not_applicable` 兼容字段；任何单日 Gate
  不得将其设为 true。`JM_RUNTIME_READY` 只能在单日自然运行、同一 exact release 独立恢复
  证据、独立 Review 全部通过且用户最终批准后发布。
- 不可把 `report_id=14` trust audit、任何 backtest 或单次 smoke 写成策略盈利或实盘准入。
- 不可把 HTDY realtime exception 写成历史回测、OOS、收益或交易资格；`REJECTED_RESEARCH_CANDIDATE` 不得被翻转。
- 不可宣称 `HTDY_XMA_SEMANTICS_AUDITED`；原始 XMA 仅保留精确 observation-only policy。

相关业务定义见 `docs/ARCHITECTURE.md`、`docs/DATA_CENTER.md`、`docs/BACKTEST_ENGINE.md`、`docs/SIGNAL_EVENTS.md` 与 `docs/INDICATOR_KERNEL.md`。
