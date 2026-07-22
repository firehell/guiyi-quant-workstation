# WEB-V1 最终验收（WEB-V1-12）

```text
WEB_V1_READY
WEB_V1_BROWSER_ACCEPTANCE_PASSED
```

> 验收日期：2026-07-22。Web 源码、mock 浏览器、真实数据库/数据根的 GET-only API 与真实浏览器矩阵全部通过。该 Gate 只代表 Web V1 研究工作台完成，不代表 Runtime、策略盈利、实盘或自动交易 Ready。

## 1. 基线与执行身份

| 项 | 值 |
|---|---|
| 手册审查基线 | `115101e3abac283d26e049d64ff6cf7781fa5d53` |
| 本轮主线基线 | `main@947fc8729ed4a3dd1d85d5a3167ceff46eca2903` |
| 工作分支 | `codex/web-v1-review-fixes` |
| worktree | `/Volumes/扩展盘/GuiyiWorktrees/guiyi-web-v1-review-fixes` |
| 部署身份 | 未部署；验收使用 worktree 代码 + 主数据根 + 当前 PostgreSQL，只读启动临时 API |

当前未提交 diff 是本轮待用户审查的交付，不包含无法解释的旁路修改。

## 2. 修改摘要

WEB-V1-00～11 原有收口保持不变。本轮补齐最终审查发现的缺口：

1. Runtime 页面增加 `after_market_scheduler`，展示 archive lag、retry、heartbeat、lock 和 active binding，并兼容旧响应缺字段空态。
2. coverage `binding_status` 改为 SQL `EXISTS / NOT EXISTS` 精确 count/分页，只接受 `active / unbound`，不再受前 1000 条扫描限制。
3. mock console Gate 删除资源、WebSocket、ECharts、BarChart 等错误白名单。
4. `BaseChart` 注册 `BarChart`，Batch 柱状图不再产生未注册 series error。
5. 新增 Web-safe validation observation endpoint；严格 `/validation-context` 的 409 fail-closed 语义保持不变，Review 在证据漂移时显示 unavailable 且不制造预期 console error。
6. `test:e2e:readonly` 从 API GET smoke 扩展为 API + 11 主路由真实浏览器 GET-only/console-zero Gate。
7. live scheduler 在闭市时先返回 `idle`，不再解析尚未归档的当日 target 或构造 RQData client；checkpoint freshness 仅在交易时段生效，历史 `NoClosedBuckets` 归一为 idle。
8. Vite 8 使用 Rolldown 对 ECharts/ZRender 和日期依赖定向拆包，生产构建最大 JS chunk 从 671.91 kB 降至 211.24 kB。

未新增 migration，未修改策略、回测撮合、历史报告、Profile binding、live 数据、归档或通知。

## 3. 页面状态矩阵

| 页面/能力 | 结果 | 主要证据 |
|---|---|---|
| Dashboard | PASS | 真实摘要、研究/非自动交易边界、入口可见 |
| Data | PASS | Tab lazy、服务端分页、binding、无物理路径 |
| Market List | PASS | 明确“查看 K 线”入口 |
| Market Historical | PASS | JM2609 15m 真实 bars、lineage、EMA/MACD |
| Market Live | PASS（观察边界） | Live 与 Historical 分层；缺失 Runtime 字段显示 unavailable |
| Strategy | PASS | Registry≠validated；默认 research-only |
| Backtest report 14/15 | PASS | report 14 GET；report 15 Review 精确回链 |
| Trade / Order | PASS | report 14 明细与分页；不触发任务创建 |
| Batch | PASS（边界） | `BATCH_BACKTEST_RESEARCH_ONLY`，默认禁用启动 |
| Signal / Event / Notification | PASS | replay / historical scan / live-confirmed 分层；无真实发送 |
| Review | PASS | review #9 / trade #3199 / report #15 精确 bars；validation drift unavailable |
| Runtime | PASS | scheduler/archive/after-market/checkpoint/RQ/notification 全部只读展示 |
| Settings | PASS | 连接配置与 health 测试边界；无凭据显示 |
| 1280×720 / 1440×900 | PASS | deterministic mock matrix |
| error / empty / degraded | PASS | 旧 Runtime 空态、Runtime degraded、validation unavailable |
| console / path / secret | PASS | raw console error=0；无错误白名单；无物理路径/秘密 |

## 4. 能力边界

| 类别 | V1 表达 |
|---|---|
| formal research | Profile / passed quality / lineage 约束下的历史研究与只读报告 |
| research-only | 通用回测表单、历史扫描、默认 Strategy Registry |
| observation-only | EMA 前端技术观察、HTDY Historical/Browser、Live Target preview |
| historical replay | `jm_v1b_historical_replay`，明确不是 live-confirmed |
| live-confirmed | 与 historical/replay 分层，当前仅研究观察 |
| rejected | HTDY Stage 5 candidate；不提供 live enablement |
| legacy | Batch route 保留查询兼容，默认禁用启动 |

## 5. 测试与原始结果

| 命令 | 结果 |
|---|---|
| `bash scripts/engineering/preflight.sh --json` | failed=0，warn=2（本轮 dirty diff；隔离 worktree 无 `data/parquet`） |
| `bash scripts/engineering/check-secrets.sh` | PASS，scanned_files=9131 |
| `cd apps/quant-web && npm test` | 105 passed / 1 skipped / 0 failed |
| `cd apps/quant-web && npm run build` | PASS；最大 JS chunk 211.24 kB；无 chunk size warning |
| `PLAYWRIGHT_BASE_URL=http://127.0.0.1:5177 npm run test:e2e` | 9 passed；raw console error=0 |
| `PLAYWRIGHT_API_BASE=http://127.0.0.1:8010 PLAYWRIGHT_BASE_URL=http://127.0.0.1:5177 npm run test:e2e:readonly` | 8 checks passed；API + 11 路由浏览器矩阵；GET-only；console error=0 |
| Web + Runtime 相关后端矩阵 | 226 passed / 2 skipped / 0 failed |
| `pytest -q services/quant-api/tests` | 1212 passed / 3 skipped / 0 failed |
| validation strict + observation 定向测试 | 2 passed |
| `bash scripts/engineering/test.sh engineering` | 32 passed |
| Ruff changed backend files | PASS |
| `git diff --check` | PASS |

## 6. 浏览器与真实后端证据

- Mock：9 个场景，覆盖所有主路由、Data lazy/page、Market 控件、Runtime 新旧契约、Signal 边界、Settings GET-only、Batch 禁用和 deep-link。
- Real API：health/runtime、coverage、market、report 14、signals/events、reviews 全部只读通过。
- Real browser：Dashboard、Data、Market List/Chart、Strategy、Backtest、Batch、Signal、Review、Runtime、Settings 共 11 条路由全部打开。
- Review 样本：`review_id=9 / trade_id=3199 / report_id=15`；冻结 K 线和交易 marker 可读。
- 当前 validation 证据发生 Profile identity drift 时，严格端点继续返回 409；Web observation 返回 `available=false`，页面 fail-closed，console 不报错。
- 浏览器矩阵记录的 API 方法只有 GET/HEAD/OPTIONS；未创建任务、扫描、SignalEvent、Review，未修改状态，未发送通知。

## 7. 性能与有界性

- Data 首屏只加载摘要和 active Tab；coverage/tasks/quality 使用服务端分页。
- binding count/page 在数据库完成，不进行 1000 条前端/服务层截断。
- Market 初始 bars、viewport 加载和 overlap merge 有界；异值冲突 fail-closed。
- Live refresh 保留 visibility pause 与 in-flight 防重叠。
- Review/Backtest 大表分页；真实 Review source 查询约 3～14 秒，属于后端性能 residual，不影响正确性 Gate。

## 8. 已知 residual

1. Review source 真实查询约 3～14 秒，属于后端性能 residual。
2. 当前部署副本在合并前仍是旧代码；部署后身份与 health 需记录在独立 closeout 证据中。
3. Stage 6 D1/D2、T5/T6/T7、`LONG_RUNNING_READY` 仍是独立业务 Gate。

## 9. 未完成项

- Web V1 本身没有未完成硬 Gate。
- Git 提交、推送、主干合并和部署按用户本轮授权执行；本文件在部署 closeout 前不预写成功结论。
- 部署后可复跑同一 `test:e2e:readonly`，作为部署身份核验，不改变本次源码验收结论。

## 10. 回滚方式

代码回滚使用对应提交的 `git revert`；部署回滚恢复旧 Runtime hash 与旧 Web dist。不要 reset 主工作树，也不要触碰 `data/`、report 14/15 或 Stage 6 receipt。

## 11. 不可宣称事项

- 不宣称 `JM_RUNTIME_READY`、`LONG_RUNNING_READY`、自动归档 Ready、可实盘或自动交易。
- 不宣称策略盈利、Registry=validated、Batch formal 或 HTDY live-ready。
- 不把 historical replay 写成 live-confirmed。
- 不把 `REJECTED_RESEARCH_CANDIDATE` 改写为 validated。
- 不修改 Stage 6 T4/T5/T6/T7 状态。

## 12. 最终 Gate

```text
WEB_V1_READY
WEB_V1_BROWSER_ACCEPTANCE_PASSED
```

推荐 PR 标题：`fix(web): close Web V1 final acceptance gaps`

推荐 PR 说明：补齐 Runtime after-market 观测、coverage binding 精确分页、raw console Gate、BarChart 注册和 Review validation observation；附 mock/real browser、GET-only、后端、工程与 secrets 全绿证据。
