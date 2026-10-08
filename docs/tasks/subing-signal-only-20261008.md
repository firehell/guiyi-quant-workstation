# 苏冰仅产生信号（2026-10-08）

COMPLETED / TEST_COMPLETE / REVIEW_COMPLETE。用户交办暂停全部苏冰推送、保留信号。
补丁从 exact v1.12.0 创建，PR #411 合并 main，annotated v1.12.1 peeled
`412ec4bece20aca5f55439edc9057ebd9c8aee4c`，GitHub Release 非 draft/非 prerelease。
正式 root `.worktrees/release-v1.12.1` detached/clean，七个既有应用 label installed/loaded 均新 root/commit。

## 修改与实际验证

- registry 的苏冰 notification_enabled=false；共享 Event helper 仍保存 Event，静默分支不准备消息。
  新静默 Event notification_attempted_at=null，不记通知失败；HTDY=True，去重和历史 Event 不变。
  ORM 字段已有 nullable，无 migration、生产 Scope 或行情修改；正式分钟仍59品种，PP未发布。
- 实测命令：`PYTHONPATH=services/quant-api:packages/quant-core python -m pytest -q`
  后接 test_alert_runtime.py、test_alert_service.py、test_alert_registry.py、test_alert_notification.py、
  test_subing_ths_kernel.py、test_alert_notification_config.py、test_runtime_health.py；实际203 passed。
  首新增测试真实 RED（苏冰仍准备消息）后 GREEN。helper与完整Live trigger各覆盖两rule、SQLite持久化和重复Bar。
- `uv lock --check --offline --project services/quant-api`、定向Ruff、`git diff --check`通过；
  `npm run build`通过typecheck/build/bundle topology，保留既有dynamic import警告；
  `openspec validate --specs --strict --no-interactive` 10 passed。独立实现/补审/部署Review均无Confirmed Issue。
- base、alert、market、existing weekly安装exit0。Market首次在mutation前因旧root未初始化after-market.lock停止，
  authority loaded/recheck通过且确证FileNotFoundError；使用既有after_market_recovery_guard精确初始化协调锁，
  不运行自然job、不写status。随后原安装器重新锁定/preflight snapshot_ready、60/60通过并保留历史。
- 60产品API Scope前后逐条相同，苏冰60×15m仍enabled。API/Web HTTP200，实际API版本1.12.1。
  本次service总体health仍degraded，原因是baseline已有Alert coverage evaluation_failed及历史transport失败；
  processing_state=ok，原失败/attempt时间未增长，未清除或伪造健康证据。
- 自然苏冰Event #1181：PS2611、15m sell、bar_end=2026-10-08T02:45:00Z，
  detected_at=02:45:08.924157Z（北京时间10:45:08），notification_attempted_at=null。
  新Event保存且transport最后尝试仍02:00:32基线，独立Review确认自然静默闭环通过；未人工trigger或发送测试通知。
- 旧v1.12.0树clean、installed/loaded引用迁出、lsof最终0；13份运行状态/plist/marker逐SHA保存后non-force退休。
  首lsof仅瞬时git读目录引用，退出后只读重核0。依赖复制与editable/bin路径重绑定，新Web产物真实构建。

证据：`outputs/subing-signal-only-20261008/`；关键 all-scopes-before/after、readback、subing-natural-events、
services-after、四类安装日志（原停止记录保留）、retirement-preflight 与 old-runtime-state。
允许 Runtime promotion，本次实际完成；不宣称所有品种覆盖、盘后或weekly自然验收完成。
恢复苏冰发送需用户明确交办；不得补发静默期历史Event。唯一最小下一步：按既有Runtime继续自然记录信号。
