# V1-HTDY-04 S6-08 Schema-v3 Gate

日期：2026-07-26

## 结论

```text
HTDY_S6_08_SCHEMA_V3_CODE_COMPLETE
REAL_T5_NOT_EXECUTED
NO_RUNTIME_WRITE_AUTHORIZATION_ACTIVE
RUNTIME_CHANGESET_DEPLOYED
S6_08_NATURAL_EVENT_GATE_PENDING
```

本步完成 schema-v3 packet builder/verifier、CLI、独立 HTDY Runtime handler 和测试，并已按
最终精确 Approval A 完成 code-only Runtime/Web bundle 部署与 S6-07 code-only rebind；仍未
启用 SignalEvent、创建 daily child、接受自然事件或发送通知。S6-07 semantic recovery 已按
精确 Approval R 完成：
PostgreSQL 保持 `0025`、7 条 superseded binding 与 1 条 scheduler checkpoint 已恢复，receipt
hash=`3d916810629a34f48cbdd488e6ace7ac5954fa16089362284d85db790f07f75d`；
task 23/report 15、report 14、active Profile 与禁止表均零漂移。

## 合同

- bounded parent 最多包含五个唯一、排序后的明确交易日。
- parent 精确绑定 deployment packet、S6-07 rebind、S6-07 final receipt、DB recovery receipt、
  service bundle、Runtime commit、DB revision、indicator source、policy 和 writer hash。
- deployment packet 冻结部署前 Runtime 与批准目标；service parent 的 `runtime` binding
  冻结批准目标 commit/tree 和既有 Runtime root，使部署完成后的 Runtime 重采集能够精确匹配，
  不得把部署前 commit 错当成目标状态。
- parent 的 Profile/actual-contract 基线使用 packet 生成日前最新且唯一的已知 rank=1 mapping；
  不查询或伪造未来窗口首日 mapping。daily child 仍须重新绑定当日 exact mapping。
- exact daily child 绑定 parent hash、一个被允许交易日、实际主力合约、mapping hash 和
  `strategy_signals/signal_events/signal_notifications/signal_scan_tasks/orders/trades` baseline。
- 旧 schema-v2 packet 必须拒绝。
- execution verifier 至少要求一条 `signal_created`，且只允许
  `htdy_original_realtime_first_seen/v1.0 + live_realtime_repainting +
  signal_review_lineage_v2`。
- StrategySignal 与 SignalEvent delta 必须等于事件数；notification、scan、order、trade
  delta 必须全部为零。
- `LiveRuntimeCycleService` 只在 schema-v3 Gate 授权后调用独立 HTDY handler；旧
  `LiveSignalEvaluator` 不进入 active HTDY 路径。
- 首个自然事件后只允许一次同 observation key 幂等探测；验证
  `unchanged > 0, created = 0, changed = 0` 后消费 create-only 授权。
- source worktree 与 Runtime checkout 分别采集 commit/tree/clean facts，禁止用 source
  checkout 身份冒充 Runtime 身份。
- S6-07 code-only rebind 具备独立 `prepare / verify / confirm` Gate。confirm 必须先验证
  同目录 create-only deployment receipt、目标 Runtime commit、`0025` DB 全量状态、after-market
  launchd identity 和 disabled health；成功后只写 `s6_07_rebind_receipt.json`。
- after-market scheduler 未加载时 rebind 必须保持未加载且不得执行 bootstrap/kickstart；已加载时
  只允许重启精确 label，并有界等待 PID 变化。两种路径都不得重跑 archive、修改历史 receipt、
  watermark、asset、Profile 或启用 HTDY/企业微信开关。
- service Runtime collector 在采集 active parent facts 前必须重载验证 deployment receipt 与
  S6-07 rebind receipt；只有 packet 不能证明 rebind 已执行。

## 外部 Gate

- 三包不内嵌到本代码 checkpoint；只在 checkpoint 后基于干净 commit create-only 生成并重载验证；
- 未修改 Runtime env、launchd、PostgreSQL、Redis 或数据资产；
- 未执行真实 S6-08、S6-09、S6-10 Gate。

所有新 deployment/rebind/service packet 都必须重载验证 recovery receipt；旧 packet 不含该
binding，不能取得运行资格。只有取得精确 Approval A 后才能部署或写入。

`20260726-14d4388c237c` 首轮审批目录保留为 superseded 审计证据：其中 service parent 在
完成前复核时发现绑定了部署前 Runtime commit，未取得任何写授权、未生成 receipt、未部署。
后续只接受修复 checkpoint 对应的新 create-only 目录和三包 hash。

`07b786f1` 对应的第二轮三包曾取得 Approval A：

```text
deployment=0537ef763fca7a37a0c07e29a8cd0531e33e91288fe7a66ae62877ed023b9f55
rebind=e65daf50f1e7e63de5486e949ede9818944e6560c954d2cf7038fb9c986f9526
service_parent=9be89b07bda8cde50561371104c890e462986dc73ec678277a961331446c77bf
```

执行前 fresh verification 发现 `origin/main` 从 `bf767c0b` 漂移到 `facd8034`，
`ahead_of_origin` 从 18 漂移到 6；按 literal Gate 该 Approval A 未消费即失效。审计同时发现
旧 rebind packet 只有 prepare/verify，没有 confirm executor 或 create-only receipt，不能据此
声称 S6-07 code rebind 已完成。因此本分支
`codex/v1-htdy-approval-a-rebind` 取代旧 `codex/v1-htdy-step04-final-closure`
作为唯一非 main 新包来源；旧三包和批准只保留为 superseded 证据，不得部署。

`22760122` 对应的第三轮 Approval A 已执行 code-only deployment：Runtime 从
`facd8034` 切换到 `22760122`，deployment receipt 记录 DB `0025 -> 0025`、
`flags_safe=true`、`health_verified=true`、`rollback=false`。随后 rebind 在写 receipt 或操作
after-market scheduler 前 fail-closed。根因有两层：

1. CLI 进程未显式加载本机 project env 时 PostgreSQL 连接失败；
2. 加载正确环境后，checkpoint collector 暴露出查询列与 0025 schema 不一致：
   使用了不存在的 `exchange` / `watermark_trading_day`，真实列为
   `exchange_code` / `last_successful_trading_day` 等。

未生成 `s6_07_rebind_receipt.json`，after-market scheduler 保持 unloaded/disabled，未写
SignalEvent、通知、订单或交易。修复改为复用 `AfterMarketSchedulerCheckpoint` ORM 的完整列
baseline，receipt 必须同时包含完整 checkpoint count/hash、十类受控计数和四类 baseline hash。
由于该修复产生新 commit，第三轮 rebind/service parent hash 不得复用；须从新 checkpoint
重新生成 deployment/rebind/service parent 三包并取得新的精确 Approval A。

`d6fb9a38` 对应的第四轮 Approval A 已完成 code-only deployment 和 S6-07 code-only rebind：
两份 create-only receipt 均通过仓库 verifier，DB revision/受控计数/hash/checkpoint 零漂移，
after-market scheduler 保持 unloaded/disabled，SignalEvent/autosend 保持关闭。部署后首次调用
production `collect_current_bindings()` 时仍 fail-closed，唯一 drift 为 Web bundle hash。根因是
`apps/quant-web/dist` 被 Git ignore，旧 deployment Gate 只切换 target commit，不会把已测试且被
service parent 冻结的 source bundle 同步到 Runtime。修复合同要求 deployment packet 同时绑定
source/runtime bundle path/hash；confirm 仅可原子安装精确批准 bundle，失败时恢复旧 bundle，
success receipt 冻结 before/after/synced。此补丁必须形成新 checkpoint、新三包和新的精确
Approval A；不得直接复制 Runtime bundle 绕过 hash Gate。

`f63b36365394` 对应的最终 Approval A 已于 2026-07-26 执行并闭合上述 bundle drift：

```text
deployment=63745f53a126718b02826ab8ae1d3a29d15bccf88a005563264ceb761ef35d94
rebind=00e604796e93e5fe49c2d0918730b093247b6a03aa747a60fac243aa17bb4360
service_parent=f0316f262d207502b2d176dee680998308ff1158bfd51559437643c889438b8b
```

证据目录为
`data/reports/jm_live_signal_event_s6_08/htdy_schema_v3/20260726-f63b36365394/`。
deployment receipt 记录 Runtime `d6fb9a38 -> f63b3636`、DB `0025 -> 0025`、
`flags_safe=true`、`health_verified=true`、`rollback=false`，并将 Runtime Web bundle 从
`0f668318...` 原子同步到获批的 `be70524d...`。S6-07 rebind receipt 通过独立 verifier：
checkpoint count/hash、十类受控计数和四类 baseline hash 均未漂移，未重跑 archive、未修改
historical receipt/watermark/asset/Profile，after-market scheduler 保持未加载且未重启。

部署与 rebind 后，production `collect_current_bindings()` 重新采集全部 service parent facts，
`verify_parent_authorization()` 对最终 parent hash 验证为零漂移；Runtime tracked state clean，
SignalEvent 与 WeChat autosend flags 均为 false。目录中没有 `daily/accepted_event.json`，因此本步
没有创建 daily child、真实 HTDY SignalEvent、ReviewNote、通知、订单或交易。下一 Gate 仍是
另行授权的单日自然 first-seen event + 同 key 一次幂等探测；在该 Gate 与五交易日长稳完成前，
不得宣称 HTDY Runtime、通知、交易或长稳 Ready。
