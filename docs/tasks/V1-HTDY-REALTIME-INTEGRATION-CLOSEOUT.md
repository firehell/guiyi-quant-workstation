# V1 HTDY Realtime Integration Closeout

日期：2026-07-26

## 结论

```text
CODE_COMPLETE_EXTERNAL_GATE_PENDING
HTDY_REALTIME_15M_SNAPSHOT_READY
HTDY_FIRST_SEEN_EVENT_WRITER_READY
HTDY_SIGNAL_REVIEW_LINEAGE_V2_READY
HTDY_S6_08_SCHEMA_V3_GATE_READY
WEB_HTDY_FIRST_SEEN_PRESENTATION_READY
WEB_HTDY_LINEAGE_V2_COMPATIBLE
HTDY_OBSERVATION_ONLY_PRESENTATION_PRESERVED
WEB_HTDY_INTEGRATED_ACCEPTANCE_PASSED
NO_WEB_OR_HTDY_SEMANTIC_REGRESSION
NO_RUNTIME_WRITE_AUTHORIZATION_ACTIVE
```

唯一后续开发入口：

```text
worktree=/Volumes/扩展盘/GuiyiWorktrees/guiyi-v1-htdy-realtime-integration
branch=codex/v1-htdy-realtime-integration
```

## Worktree 收敛

以下四个旧 worktree 已移除：

- `/Volumes/扩展盘/GuiyiWorktrees/guiyi-s6-08-live-signal-event-acceptance`
- `/Volumes/扩展盘/GuiyiWorktrees/guiyi-v1-htdy-realtime-closure`
- `/Volumes/扩展盘/GuiyiWorktrees/guiyi-v1-htdy-realtime-snapshot`
- `/private/tmp/guiyi-htdy-original-realtime-alert`

分支引用保留，未删除历史 commit。旧 S6-08 已进入 main；closure 是 snapshot 的祖先；旧 alert
commit 仅作为审计参考，未整体合并。alert 中的独立 `htdy_observation_alerts` migration、平行
notification/WeCom 链和旧 scheduler evaluator 均未进入集成分支。

收敛过程中 snapshot worktree 出现 6 个并行未提交加固修改；使用 stash 可恢复迁移到新分支，
补丁 SHA-256 一致，120 个 Step 2 测试通过后提交为 `9cbac58c`。随后另一会话生成的
`3c6cd723` 与新分支该 checkpoint 文件树完全一致、无独有内容，因此再次安全移除旧 snapshot
worktree。stash 继续保留为迁移备份。

最新 `main@bf767c0b` 已通过 merge commit `91cd88d7` 合入；冲突仅涉及 canonical 文档，
合并结果同时保留 WEB-V1-14 当前事实和 HTDY Step 0～4 进度。

## 实现 checkpoint

- `9cbac58c`：加固 Step 2 public snapshot ingress、previous DCE trading day、as-of frontier
  与 hash/provenance 校验。
- `99e8cf58`：新增未接 Runtime 的 immutable first-seen writer 与
  `signal_review_lineage_v2`。
- `223b92e4`：新增 schema-v3 bounded parent、exact daily child 和纯执行结果 verifier。
- `068785fc`：补充 forged result、同批重复 candidate、既有冻结 Signal/Event 漂移拒绝。
- `91cd88d7`：同步最新 main / WEB-V1-14。
- `cba1ca87`：完成 HTDY first-seen 的 Signal、Dashboard、Market marker 与 Review Web
  observation-only 兼容，并保持 Review 外层 `review_source_lineage_v1`、来源快照
  `signal_review_lineage_v2`。
- `8428856e`：封堵 destructive migration test 误用 Runtime DB，并记录 S6-07 业务事实恢复阻塞。
- 当前收口分支保留现有 Web 集成，同时加入 Step 3 完整 ledger/Stage 9 例外和 Step 4
  schema-v3 Runtime handler、唯一一次幂等探测、create-only 授权消费及三包生成器。

没有新增 migration、表、依赖锁文件、通知投递、订单或交易路径。新增的 Runtime wiring 受
schema-v3 Gate、自然事件和唯一一次幂等探测合同约束，尚未部署或取得写入授权。

## Web HTDY 兼容收口

精确候选身份：

```text
source_main=bf767c0bfbc4d9152d879b73362ee7ad8cc4ab89
integration_base=c3702e00c979da9516f2670a82292ab5f80bc17a
acceptance_code_head=cba1ca87f8214294d2ebe93f058e199f184d6b18
runtime_commit=1805af2e
runtime_deployed=false
five_day_gate_started=false
```

Web 固定以下语义：

- `live_realtime_repainting` 只映射为“HTDY 实时重绘观察”与 `observation-only`；
- exact identity 为 `htdy_original_realtime_first_seen / v1.0`，只接受实际主力、15m、
  first-seen 时间、冻结桶和 `signal_review_lineage_v2` 完整一致的记录；
- Dashboard 只提示“新的 HTDY 观察事件”，不包装为普通 live signal 或交易机会；
- HTDY Market marker 只选择首次 `signal_created`，忽略后续 `signal_changed`；
- Review API 外层继续为 `review_source_lineage_v1`，Web 只读显示
  `source_snapshot_schema_version=signal_review_lineage_v2`；
- `future-looking=true`、`repainting=true`、first-seen no-retraction、
  `notification=false`、`auto-order=false` 持续可见；
- 未新增通知按钮、ReviewNote 自动写入、API、migration 或依赖。

## 验证

```text
Step 2 snapshot/evaluator: 120 passed
Step 3 first-seen writer: 11 passed
Step 4 schema-v3 Gate: 12 passed
HTDY/Signal/Review targeted regression: 446 passed, 1015 deselected
backend full suite on integration candidate: 1459 passed, 3 skipped
engineering: 161 passed
Web unit: 161 passed, 1 optional golden skipped
Web build: passed; production bundle graph acyclic
Playwright mock: 18 passed
Playwright local real-backend read-only: passed; GET/HEAD/OPTIONS only
Ruff quant-core/API/tests: passed
docs profile: passed
secret scan: 9241 files, no high-confidence secret
git diff --check: passed
```

Playwright 第一次执行时未启动 5174 Vite 服务，18 项均以
`ERR_CONNECTION_REFUSED` 失败；按 runner 的实际前置启动临时服务后复跑 18/18，通过后服务已停止。

本次最终收口复验：

- backend full：`1494 passed, 3 skipped`；
- HTDY/相关 backend：`510 passed, 987 deselected`；
- engineering：`163 passed`，deployment Gate：`118 passed`；
- Web unit：`161 passed, 1 skipped`，build 通过；
- Web E2E：临时 Vite 服务下 `18 passed`；
- ruff、secret scan 与 `git diff --check` 通过。

`npm ci` 报告依赖树中 2 个 high severity audit 项；本任务未修改 lockfile，也未自动执行
`npm audit fix`。preflight 在验收改动未提交时报告 dirty worktree，并继续报告隔离 worktree
缺少 `data/parquet`；后者未自动创建。

## 外部 Gate

本任务没有生成真实 deployment、S6-07 rebind 或 HTDY service packet/hash，没有修改 Runtime、
PostgreSQL、Redis、launchd 或环境变量，也没有执行真实 S6-08、企业微信或五交易日长稳。
当前 PostgreSQL schema 已为 `0025`，但 S6-07 checkpoint、7 条历史 binding 和 HTDY trusted
backtest lineage 的逐字段原样恢复证据不完整；不得用 schema 健康或 code-only receipt 替代业务
事实恢复。

下一步必须先完成独立 S6-07 数据恢复合同/Approval R；恢复 receipt 验证通过后，才可从当前候选
commit 独立采集真实 binding，生成 create-only 三包并审查 drift。只有取得精确 Approval A，
才能进入单日真实 S6-08 SignalEvent Gate。
