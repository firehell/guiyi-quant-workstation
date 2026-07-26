# V1 HTDY Realtime Integration Closeout

日期：2026-07-26

## 结论

```text
CODE_COMPLETE_EXTERNAL_GATE_PENDING
HTDY_REALTIME_15M_SNAPSHOT_READY
HTDY_FIRST_SEEN_EVENT_WRITER_READY
HTDY_SIGNAL_REVIEW_LINEAGE_V2_READY
HTDY_S6_08_SCHEMA_V3_GATE_READY
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

没有新增 migration、表、依赖锁文件、Runtime wiring、通知路径、订单或交易路径。

## 验证

```text
Step 2 snapshot/evaluator: 120 passed
Step 3 first-seen writer: 11 passed
Step 4 schema-v3 Gate: 12 passed
HTDY/Signal/Review targeted regression: 446 passed, 1015 deselected
backend full suite after final main merge: 1458 passed, 3 skipped
engineering: 161 passed
Web unit: 155 passed, 1 optional golden skipped
Web build: passed; production bundle graph acyclic
Playwright mock: 17 passed
Ruff quant-core/API/tests: passed
docs profile: passed
secret scan: 9240 files, no high-confidence secret
git diff --check: passed
```

Playwright 第一次执行时未启动 5174 Vite 服务，17 项均以
`ERR_CONNECTION_REFUSED` 失败；按 runner 的实际前置启动临时服务后复跑 17/17，通过后服务已停止。

`npm ci` 报告依赖树中 2 个 high severity audit 项；本任务未修改 lockfile，也未自动执行
`npm audit fix`。preflight 唯一 warning 为隔离 worktree 缺少 `data/parquet`，未自动创建。

## 外部 Gate

本任务没有生成真实 deployment、S6-07 rebind 或 HTDY service packet/hash，没有修改 Runtime、
PostgreSQL、Redis、launchd 或环境变量，也没有执行真实 S6-08、企业微信或五交易日长稳。

下一步必须从当前候选 commit 独立采集真实 binding，生成 create-only 三包并审查 drift；只有取得
精确 hash 批准后，才能进入单日真实 S6-08 SignalEvent Gate。
