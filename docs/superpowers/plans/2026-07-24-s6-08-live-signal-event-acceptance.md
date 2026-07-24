# S6-08 Live-confirmed SignalEvent 最终验收计划

## Summary

当前 `main@f3c077b1` 干净且与 `origin/main` 一致；Runtime 位于其祖先 `19e6ca31`。沙箱外只读探针确认 API、live scheduler、after-market scheduler 均为 `ok`，安全开关为 `true / false / false`。现有基线为后端定向 `191 passed`、Web `120 passed / 1 skipped`、Web build 通过。

需要关闭的阻塞：

- 正式 Gate 名称与任务契约不一致。
- 缺少独立策略资格判定及无资格阻断出口。
- 旧 code-only packets 已因 target/source 漂移失效，且没有 deployment receipt。
- 真实 T5、真实同 bar 幂等、Web/Review 回链及最终 receipt 尚未执行。
- 最终 verifier 未绑定执行期幂等 heartbeat 与 Review lineage 证据。

## Contract and Code Changes

- 在独立 worktree `/Volumes/扩展盘/GuiyiWorktrees/guiyi-s6-08-live-signal-event-acceptance`、分支 `codex/s6-08-live-signal-event-acceptance` 中按 TDD 修改。
- 将正常终态统一为 `LIVE_SIGNAL_EVENT_GATE_PASSED`，无合法策略终态为 `LIVE_SIGNAL_EVENT_BLOCKED_NO_ELIGIBLE_STRATEGY`；删除未发布的 `JM_LIVE_SIGNAL_EVENT_PASSED` 别名，`PENDING_ELIGIBLE_EVENT` 仅表示某交易日没有自然事件。
- 将 service packet/final receipt 升为 schema v2，绑定：
  - `jm_v1b_daily_direction_fast_entry / v1b.0`；
  - frozen legacy policy、源码 hash、`live_observation_v1`；
  - `observation_only=true`、`notification_ready=false`、`trading_ready=false`；
  - S6-07 schema-v2 receipt 全契约与精确 SHA、Runtime 祖先关系。
- 新增只读策略资格检查模式；只允许上述冻结版本。HTDY rejected/original/strict 均保持禁止，不调参、不翻转阶段 5 结论。
- final verifier 同时验证：
  - 执行期 authorized heartbeat 中，真实事件后一次同 bar 周期出现 `unchanged>0` 且 `created=changed=0`；
  - post-disable heartbeat 更新、授权清空、signal flag=false；
  - revision/state key 包含 `live_bar_revision`，revision 改变只产生一个 `signal_changed`；生产环境不人工篡改 bar，仅以 commit-bound 集成测试证明该分支；
  - `resolve_review_source_lineage(signal_event)` 返回 frozen lineage；
  - SignalNotification、scan、backtest/order/trade、Profile、canonical asset、EOD checkpoint 全表 hash/count 零漂移。
- Web 的 SignalEvent 行增加“进入复盘”按钮，跳转到只读 Review deep link；页面只展示待复盘来源和 lineage，不自动创建 `ReviewNote`。
- 不新增 migration，不改变策略参数、指标公式、数据 Profile、EOD scheduler、企业微信或订单路径。

## Implementation and Real Gate Sequence

1. 将本计划保存为本文件，创建隔离 worktree，执行干净基线测试。
2. 依次完成 Gate 命名、资格判断、schema-v2 packet、执行期幂等证据、Review lineage、Web 深链的 RED→GREEN 测试并提交。
3. 完成 diff/安全审查后，将任务分支本地合并到 `main`；不 push、不关闭 Issue。
4. 保留两份旧 packet 作为失效历史；在全新 create-only 目录生成当前 main 的 code-only deployment packet。展示精确 packet hash 后取得一次 hash-specific 批准，再将 Runtime 切换到批准 commit，只重启 `com.guiyi.quant-runtime-scheduler`。
5. 使用 TradingCalendar 选择目标交易日，生成单日 service packet。展示精确 hash 后取得第二次 hash-specific 批准；未知 hash 不能由概括性批准预授权。
6. 设置 `GUIYI_LIVE_RUNTIME_ENABLED=true`、`GUIYI_LIVE_SIGNAL_EVENTS_ENABLED=true`、`GUIYI_WECHAT_AUTOSEND_ENABLED=false`，仅重启 live scheduler，自然等待 confirmed 5m/15m eligible event。
7. 事件出现后继续观察至少一个同 bar scheduler 周期，保存 authorized heartbeat 的 `unchanged` 幂等证据；随后立即 disable、清空 packet/hash、重启 scheduler，并保存 fresh post-disable health。
8. 若当天无事件：disable、生成 `PENDING_ELIGIBLE_EVENT` 证据；下一交易日重新生成 packet 并取得新精确 hash 批准，持续到自然事件出现，不构造信号。
9. 对真实 event 执行只读 API/Web 验收：Event timeline 可见、K 线可打开、Review deep link 显示对应 SignalEvent 和 ready lineage、console 无错误；不点击创建 ReviewNote。
10. 扫描启用时间窗口内日志，只输出敏感模式命中数量，要求为 0；不得打印日志中的潜在秘密值。
11. 运行 final verifier，create-only 发布 `LIVE_SIGNAL_EVENT_GATE_PASSED` receipt。随后在独立 evidence 分支登记 receipt、测试、浏览器和零禁写证据，更新 canonical 文档，再本地合并到 main；Runtime 不因文档合并自动重部署。

## Test and Acceptance Plan

自动测试：

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
services/quant-api/.venv/bin/python -m pytest -q \
  services/quant-api/tests/test_live_signal_event_gate.py \
  services/quant-api/tests/test_live_signal_event_persistence.py \
  services/quant-api/tests/test_signal_review_profile_lineage.py \
  tests/engineering/test_live_signal_event_service_scripts.py \
  tests/engineering/test_jm_live_signal_event_deployment_gate.py

pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web build
services/quant-api/.venv/bin/ruff check services/quant-api/app services/quant-api/tests tests/engineering
bash scripts/engineering/test.sh engineering
bash scripts/engineering/check-secrets.sh
git diff --check
```

最终 PASS 必须同时具备：

- 一个真实 `live_confirmed`、actual-contract、passed/no-warning event。
- partial/rejected/stale mapping/stale context/缺 lineage 全部 fail-closed。
- 同 bar+revision 重复周期零新增。
- revision-change 集成测试产生且仅产生一个 `signal_changed`。
- Review lineage 和 Web deep link 通过，未创建 ReviewNote。
- notification、企业微信、订单、交易及其他禁写表零增量。
- SignalEvent flag 已恢复关闭，Runtime health fresh/ok。
- 日志敏感模式命中 0。
- create-only receipt Gate 精确为 `LIVE_SIGNAL_EVENT_GATE_PASSED`。

## Assumptions

- 采用默认选择：只读 Review 深链、Codex 本地合并、不 push、无事件时逐交易日继续。
- 本轮授权覆盖代码修改、本地合并、限定的 code-only deployment、三键 Runtime 配置和 packet 范围内真实 StrategySignal/SignalEvent 写入；每个未知 packet hash仍需生成后单独确认。
- 不保证首个交易日产生自然信号；在最终 receipt 发布前状态保持 `CODE_COMPLETE_EXTERNAL_GATE_PENDING` 或 `PENDING_ELIGIBLE_EVENT`。
- S6-08 通过不代表通知、自动交易、Runtime 长稳或 S6-09 Ready。
