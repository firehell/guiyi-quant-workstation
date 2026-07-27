# WEB-V1-12B：审查问题修复

```text
WEB_V1_REMEDIATION_ACCEPTED
```

> 基线：`main@947fc872`。本记录补充 WEB-V1-12 的修复过程；最终 Gate 与完整证据以 `WEB-V1-FINAL-ACCEPTANCE.md` 为准。

## 修复内容

1. Runtime 前端契约新增可选的 `components.after_market_scheduler`，只读展示状态、交易日水位、archive lag、当前任务、retry、heartbeat、lock 和 active binding end；兼容尚未返回该字段的旧 Runtime 响应并显示明确空态。
2. Data coverage 的 `binding_status` 筛选改为 SQL `EXISTS / NOT EXISTS` 精确 count 和分页；当前页仅查询当前页文件的 active bindings，不再扫描前 1000 条后截断；API 仅接受可完整表达的 `active / unbound`。
3. E2E console Gate 不再过滤资源、WebSocket、ECharts 或 BarChart error；任何 console error 都会使 mock smoke 失败。
4. ECharts 公共容器注册 `BarChart`，Batch 柱状图不再产生未注册 series error。
5. live scheduler 闭市先 idle，Runtime health 只在应轮询时判断 checkpoint freshness，并把无闭合桶归一为 idle。
6. Rolldown 对图表与日期依赖做实际拆包，不提高 warning 阈值。

## TDD 证据

修复前新增回归用例并确认失败：

- binding 第 6 页：预期 `total=60`，旧实现返回 `50`；
- 非法 `binding_status=superseded`：预期 `422`，旧实现返回 `200`；
- mock browser：捕获 `[ECharts] Series bar is used but not imported`；
- Runtime browser：找不到 `After-Market Scheduler`；旧响应缺失该字段时也没有兼容空态。

修复后结果：

| 命令 | 结果 |
|---|---|
| `npm test` | 105 passed / 1 skipped / 0 failed |
| `npm run build` | passed；最大 JS chunk 211.24 kB；无 chunk size warning |
| `PLAYWRIGHT_BASE_URL=http://127.0.0.1:5175 PLAYWRIGHT_CHANNEL=chrome npm run test:e2e` | 9 passed；console error 0，无错误白名单 |
| `npm run test:e2e:readonly`（worktree API + 主数据根/DB） | 8 checks passed；真实 API + 11 路由；GET-only；console error 0 |
| Web + Runtime 相关后端矩阵 | 226 passed / 2 skipped / 0 failed |
| 后端全量测试 | 1212 passed / 3 skipped / 0 failed |
| `ruff check <changed backend files>` | passed |
| `bash scripts/engineering/test.sh engineering` | 32 passed |
| `bash scripts/engineering/test.sh docs` | passed |
| `bash scripts/engineering/check-secrets.sh` | passed；scanned_files=9131 |
| `git diff --check` | passed |

## 边界与未完成 Gate

- 未新增 migration，未写真实数据库或 Parquet，未执行 live、归档或企业微信。
- 已对 worktree 代码、当前 PostgreSQL 与主数据根运行真实 `npm run test:e2e:readonly`；API 和浏览器矩阵全绿。
- `WEB_V1_READY / WEB_V1_BROWSER_ACCEPTANCE_PASSED` 已在最终验收文档发布；Stage 6 业务 Gate 保持独立。

## 回滚

按本修复提交整体 revert；不触碰 data、report 14/15、Stage 6 receipt 或 Runtime 部署目录。
