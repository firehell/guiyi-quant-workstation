# WEB-V1-13 品牌与个人研究操控台最终验收

更新时间：2026-07-22

```text
WEB_V1_13_PARTIAL
```

> W13-00～W13-06 的代码、单元、构建与 mock 浏览器 Gate 已通过；W13-07 的真实 PostgreSQL read-only API/浏览器 Gate 也已通过。真实库没有 SignalEvent→ReviewNote 关联样本，因此不得发布 `SIGNAL_EVENT_CHART_REVIEW_ROUNDTRIP_READY` 或 `WEB_V1_13_PERSONAL_WORKSPACE_READY`。WEB-V1-12 的 `WEB_V1_BROWSER_ACCEPTANCE_PASSED / WEB_V1_READY` 继续作为历史 Gate 保留。

## 1. 执行身份与边界

| 项 | 值 |
|---|---|
| 基线 | `main@b442ed5a` |
| 分支 | `codex/web-v1-13-personal-workspace` |
| 候选 Web | worktree Vite `127.0.0.1:5177` |
| 候选 API | worktree Uvicorn `127.0.0.1:8010`，单进程、无 reload |
| 数据库保护 | PostgreSQL `default_transaction_read_only=on`，会话 `transaction_read_only=on` |
| 禁止项 | 未运行 Alembic、worker、scheduler、真实通知、数据写入、push、merge 或 deploy |

本轮只增加品牌/工作台前端能力和 Dashboard、Signal、Review、Backtest 的向后兼容只读接口。未修改 Profile binding、数据资产、指标、策略、回测口径、SignalEvent 生成、通知或 Runtime Gate。

## 2. 顺序 Gate 结果

| 步骤 | 结果 | Gate |
|---|---|---|
| W13-00 | PASS | `WEB_V1_13_BASELINE_INVENTORIED / WEB_V1_13_IMPLEMENTATION_PLAN_READY / NO_CODE_CHANGE` |
| W13-01 | PASS | `WEB_BRAND_IDENTITY_READY / WEB_BRAND_ASSET_SINGLE_SOURCE_READY / NO_DUPLICATE_BRAND_ASSETS` |
| W13-02 | PASS | `WEB_PERSONAL_WORKSPACE_SHELL_READY / WEB_NAVIGATION_WORKFLOW_READY / WEB_SYSTEM_PULSE_READONLY_READY` |
| W13-03 | PASS | `WEB_ACTION_DASHBOARD_READY / WEB_PRIMARY_WORKFLOW_READY / WEB_JM_QUICK_ENTRY_READY` |
| W13-04 | PASS | `MARKET_RESEARCH_WORKSPACE_READY / MARKET_CONTEXT_EVIDENCE_SEPARATED / MARKET_RIGHT_RAIL_TABBED_READY / NO_MARKET_SEMANTIC_REGRESSION` |
| W13-05 | PASS（mock/代码） | 两条研究往返、精确 event GET、Review source 查询与手动创建边界通过 |
| W13-06 | PASS | `WEB_SINGLE_USER_STATE_READY / WEB_INTERACTION_PERFORMANCE_READY / WEB_ERROR_REDACTION_READY / WEB_ACCESSIBILITY_BASELINE_READY / NO_SENSITIVE_WEB_EXPOSURE` |
| W13-07 | PARTIAL | 真实只读 Gate 通过；真实 SignalEvent→ReviewNote 样本缺失 |

## 3. 真实数据库事实

只读 preflight 仅输出非敏感标志和 ID：

```text
default_transaction_read_only=on
transaction_read_only=on
reports=[14, 15]
review_9=true
event_review_pairs=[]
```

- report `15`、trade `3199`、review `9` 可用于真实 report→trade→chart→review→report 验收。
- SignalEvent 列表与按 event ID 精确读取可用；但没有任何真实 ReviewNote 与 SignalEvent 关联。
- 事件无复盘页面正确展示真实 SignalEvent 来源、“尚无复盘”和显式“创建复盘”按钮；readonly E2E 没有点击写操作。

## 4. 真实浏览器与网络结果

`npm run test:e2e:readonly` 共 10 项检查通过：

1. health/runtime、coverage、market、report 14、signals/events、reviews 可读；
2. Backtest/Review/Signal 新分页响应与旧数组契约兼容；
3. 11 条主要路由真实打开，console error 为 0；
4. 专业 Logo、折叠侧栏、JM 15m、Historical/Live、actual/continuous、Browser/Research、四个 Market Tab 可见；
5. 严格研究缺 Profile 时 fail-closed；
6. report `15` / trade `3199` / review `9` 的刷新、back、forward、返回来源通过；
7. SignalEvent 的 chart→无复盘→event 降级往返与刷新恢复通过；
8. 1280×720、1440×900 无页面级横向溢出；
9. 页面不回显物理路径或凭据；
10. API 网络方法只有 GET/HEAD/OPTIONS，没有 POST/PUT/PATCH/DELETE。

真实验收中发现服务端分页使深链交易不一定出现在第一页，随后增加兼容式 `trade_id` 精确过滤，并让 Backtest URL 在带 `trade_id` 时恢复该交易；旧分页与导出契约保持不变。

## 5. 最终验证

| 命令 | 结果 |
|---|---|
| `cd apps/quant-web && npm test` | 119 passed / 0 failed / 1 skipped |
| `cd apps/quant-web && npm run build` | PASS |
| `PLAYWRIGHT_BASE_URL=http://127.0.0.1:5177 npm run test:e2e` | 14 passed / 0 failed |
| W13 后端定向 pytest（Backtest/Signal/Review/lineage） | 41 passed / 0 failed |
| changed Python `ruff check` | PASS |
| `PLAYWRIGHT_API_BASE=http://127.0.0.1:8010 PLAYWRIGHT_BASE_URL=http://127.0.0.1:5177 npm run test:e2e:readonly` | 10 checks passed；GET-only；console error=0 |
| `bash scripts/engineering/preflight.sh --json` | failed=0 / warn=2 / passed=6；warning 为当前步骤 dirty diff 与隔离 worktree 无 `data/parquet` |
| `bash scripts/engineering/check-secrets.sh` | PASS；scanned_files=9158 |
| `git diff --check` | PASS |

## 6. Gate 判定

已通过：

```text
REPORT_TRADE_CHART_REVIEW_ROUNDTRIP_READY
WEB_RESEARCH_CONTEXT_RETURN_READY
```

未发布：

```text
SIGNAL_EVENT_CHART_REVIEW_ROUNDTRIP_READY
WEB_V1_13_PERSONAL_WORKSPACE_READY
```

最终发布：

```text
WEB_V1_13_PARTIAL
```

该 Partial 只描述 W13 新增的真实关联样本缺口，不撤销或改写 WEB-V1-12 的历史验收，也不代表 Runtime、策略盈利、通知、实盘或自动交易 Ready。

## 7. 解阻条件

后续只有在真实环境自然存在、或由另一个明确授权的写入任务创建合法 SignalEvent→ReviewNote 关联后，才能重新执行 event→chart→review→event 的 GET-only 验收。不得为了本 Gate 临时写库、迁移数据或用 mock 结果替代。

## 8. 回滚

使用各 W13 checkpoint 的 `git revert` 逐步回滚；不使用 destructive reset，不修改 report 14/15、review 9、数据资产、Stage 6 receipt 或生产 Runtime。
