# WEB-V1-14 研究工作台体验收口最终验收

日期：2026-07-26
任务：`WEB-V1-14-RESEARCH-WORKSPACE-POLISH`
分支：`codex/v1-web-research-workspace-polish`

```text
WEB_V1_RESEARCH_WORKSPACE_POLISHED
WEB_V1_MARKET_QUALITY_EXPLAINED
WEB_V1_CONTROL_CONTRAST_READY
WEB_V1_READONLY_ACCEPTANCE_PASSED
NO_MARKET_SEMANTIC_REGRESSION
```

> 本 Gate 只确认 V1 Web 研究工作台的展示、交互与只读验收完成。它不代表
> V2、AI 研究、策略有效或盈利、JM Runtime、五交易日长稳、通知、实盘或自动交易 Ready。
> `WEB_V1_13_PARTIAL` 因真实库缺少 SignalEvent→ReviewNote 关联样本继续保留。

## 1. Source / Base / Candidate

| 项 | 值 |
|---|---|
| 开发手册 | `/Users/zhangzhao/Downloads/归一量化_V1_Web研究工作台体验收口与交互重构_顺序Codex开发手册.md` |
| Worktree | `/private/tmp/guiyi-v1-web-research-workspace-polish` |
| Base / merge-base | `origin/main@ba775b0db8aed0e211bfa388f40a917591a4fba2` |
| Code + test candidate | `16f9d99e8bf9a3c0c79b7a445c5ec3a900919177` |
| Runtime deployment | NOT RUN |
| Push / merge / PR | NOT RUN |

## 2. 冲突处理

- 基线盘点与碰撞矩阵见 `docs/tasks/WEB-V1-14-00-BASELINE-AND-COLLISION-AUDIT.md`。
- 在 Kline 收口前精确集成 HTDY Step 0/1：
  - `4f2df31f docs: freeze HTDY realtime observation contract`
  - `63bbc9e5 feat: freeze HTDY original observation kernel`
- 未吸收并行 alert 分支的 Signal/API/Runtime 扩展。
- HTDY original 保持 `historical + browser + observation_only + repainting`；不进入
  research、formal backtest、live SignalEvent、通知或交易。

## 3. JM 1D 诊断

只读根因记录见 `docs/tasks/WEB-V1-14-JM-1D-DIAGNOSIS.md`。

- `jm.MAIN / 1d / browser` 的多文件冲突 warning 是真实数据事实，不隐藏。
- `long_horizon_daily_v1 / research` 精确绑定单一 primary/passed 资产后可严格研究。
- Kline 日线 key 唯一，没有前端重复或错位缺陷。
- 修复 research 深链首个 coverage 请求遗漏 `contract/period` 的 route hydration 问题。
- 未执行数据修复、Profile 切换、DB/Parquet 写入或 Alembic。

## 4. 实现范围

### Market / Kline

- 统一 dark control token、selected/focus/disabled 对比度。
- 将研究上下文、资格结论和工程证据分层；raw version/checksum 保留在证据 Drawer。
- warning 显式解释原因、影响、允许、阻断和下一步；HTDY repaint 风险独立展示。
- Kline 保留 actual/continuous、historical/live、browser/research、Profile fail-closed、
  lineage token、viewport、20 秒 live refresh、stale response 与 `MAX_BARS_PER_REQUEST` 语义。
- 右栏显示名由“策略”调整为“盘面”，内部 preference key 不变。

### 跨页面

- Dashboard：状态 strip、时间格式、行动优先级、空态和 JM 入口。
- Signal：中文 source_mode、exact strategy/source identity、生命周期、qualification、
  密度偏好与 Kline/Event/Review 入口。
- Review：来源事实、结果、用户判断、标签、lesson、冻结证据/lineage 与 Kline 往返分层；
  缺失关联不伪造，创建仍需显式点击。
- Backtest：report identity、Profile/data/cost、trust audit、candidate/OOS/hard reject、结果与
  trade/review 分层；明确报告可信不等于策略有效或可盈利。
- Data：有界快照的 latest date、quality、eligibility、version 与处理优先级；证据 Drawer
  不请求或展示物理路径；coverage/tasks/quality 分页保持 12 条有界。
- Runtime：component health、heartbeat、lag、watermark、last success、error、next retry 与
  恢复信息只读展示；没有恢复、重启或任务重试按钮。

## 5. 测试与验收

### Web unit

```text
command: cd apps/quant-web && npm test
exit_code: 0
tests: 156
passed: 155
failed: 0
skipped: 1
result: PASS
```

唯一 skip 是需要外部 `HTDY_GOLDEN_BUNDLE` 的可选旧测试；tracked Step 1 production Golden 已通过。

### Production build

```text
command: cd apps/quant-web && npm run build
exit_code: 0
result: PASS
bundle_topology: acyclic
largest_chunk: charting-vendor 533.82 kB / gzip 180.54 kB
```

### Mock browser

```text
command: cd apps/quant-web && npm run test:e2e
exit_code: 0
passed: 17
failed: 0
console_errors: 0
result: PASS
```

覆盖控制对比度、Market 模式/资格/quality/evidence、Kline/右栏、Dashboard、Signal Drawer
和密度持久化、Review/Backtest 往返、Data evidence、Runtime 只读恢复信息、键盘 Tab/Drawer
关闭、focus、1280 与六页 1024 页面级 overflow。

### PostgreSQL read-only browser

```text
command:
  PLAYWRIGHT_API_BASE=http://127.0.0.1:8010
  PLAYWRIGHT_BASE_URL=http://127.0.0.1:5177
  npm run test:e2e:readonly
exit_code: 0
checks: 10
failed: 0
http_methods: GET / HEAD / OPTIONS only
console_errors: 0
result: PASS
```

候选 API 为单进程、无 reload，并以
`PGOPTIONS='-c default_transaction_read_only=on'` 启动。未运行 Alembic、worker、scheduler、
通知或 Review 写入。真实验收第一次因脚本仍查找旧“策略”Tab 失败；更新为“盘面”后重跑通过。

### 工程与安全

```text
command: bash scripts/engineering/preflight.sh --json
exit_code: 0
passed: 7
warn: 1
failed: 0
note: 临时 worktree 缺 data/parquet，未自动创建

command: bash scripts/engineering/check-secrets.sh
exit_code: 0
scanned_files: 9225
result: PASS

command: bash scripts/engineering/test.sh engineering
exit_code: 0
passed: 161
failed: 0
result: PASS
```

engineering 首次在沙箱内因 8 个本地 HTTPServer/socket 测试无法 bind 而失败；在受控权限下重跑
同一命令后 161/161 通过。

### HTDY regression

```text
command:
  PYTHONPATH=packages/quant-core
  uv run --project services/quant-api pytest -q
  services/quant-api/tests/test_htdy_production_kernel_policy.py
exit_code: 0
passed: 19
failed: 0
result: PASS

command:
  uv run --project services/quant-api ruff check
  <HTDY changed Python files and targeted test>
exit_code: 0
result: PASS
```

首次遗漏 `PYTHONPATH=packages/quant-core` 时 19 项均为 `ModuleNotFoundError`；按项目模块路径重跑后
19/19 通过，不是 kernel 或 policy 回归。

## 6. 截图证据

本地验收截图（不提交、不代表 Runtime 部署）：

```text
/private/tmp/guiyi-web-v1-14-quality-card.png
/private/tmp/guiyi-web-v1-14-kline-1440.png
/private/tmp/guiyi-web-v1-14-kline-1280.png
/private/tmp/guiyi-web-v1-14-kline-1024-fixed.png
/private/tmp/guiyi-web-v1-14-daily-research.png
```

## 7. 已知限制与延后项

- `WEB_V1_13_PARTIAL` 保留：真实库没有 SignalEvent→ReviewNote 关联样本，页面诚实降级。
- JM Browser 1D 的多文件 conflict warning 保留；严格研究需合法 Profile。
- HTDY original 仍是重绘 observation-only；schema-v3 Gate、Runtime、真实事件和通知未实现或授权。
- 可选外部 HTDY Golden bundle 未提供；tracked production Golden 已通过。
- charting vendor 为当前最大 chunk；topology Gate 通过，本任务未引入新依赖或 lockfile。
- AI 概率、历史相似、参数平台、Experiment、持仓、账户、下单与自动交易继续 deferred/out of scope。

## 8. 边界复核

```text
NO_MIGRATION
NO_DB_OR_PARQUET_WRITE
NO_PROFILE_SWITCH
NO_RUNTIME_DEPLOYMENT
NO_WORKER_OR_SCHEDULER_CHANGE
NO_REAL_NOTIFICATION
NO_REVIEW_WRITE_IN_ACCEPTANCE
NO_AUTO_TRADING_UI
NO_NEW_DEPENDENCY
```

Web 分支保持独立。是否合入、形成最终 Runtime commit、部署或影响五交易日 Gate，继续由用户与
V1 发布协议决定。
