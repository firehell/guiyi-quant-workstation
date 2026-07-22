# WEB-V1 最终验收（WEB-V1-12）

```text
WEB_V1_PARTIAL
```

> 本次复跑：mock browser smoke / unit / build / secrets / preflight / 定向 pytest / diff-check **通过**；  
> 真实后端 readonly smoke **失败**（`127.0.0.1:8000` 监听但请求超时）。  
> 因此不宣称 `WEB_V1_READY` / `WEB_V1_BROWSER_ACCEPTANCE_PASSED`。

---

## 1. 基线 commit

| 项 | 值 |
|---|---|
| 手册审查基线 | `115101e3abac283d26e049d64ff6cf7781fa5d53` |
| 工作分支 | `cursor/web-v1-final` |
| 验收时 tip（WEB-V1-11） | `70ce8ea91bc5f2011d0ce5b2250a622c804167b7` |
| 相对 `origin/main` | ahead 1（本提交之后将含 WEB-V1-12 文档） |

---

## 2. 修改摘要（WEB-V1-00～11）

| Commit | 内容 |
|---|---|
| `41a70663` | web-v1-00 inventory |
| `20cefa39` | web-v1-01 global foundation / error redaction |
| `5db471f5` | web-v1-02 data center bounded loading |
| `6e66a53f` | web-v1-03/04 market state + live observation |
| `3be32636` | web-v1-05 strategy capability boundary |
| `43346b77` | web-v1-06/07 backtest formal + batch research-only |
| `063c302d` | web-v1-08 signal source mode timeline |
| `3536ce87` | web-v1-09/10 review + runtime observability |
| `70ce8ea9` | web-v1-11 browser e2e mock + readonly smoke |

范围约：`apps/quant-web/**` + `docs/tasks/WEB-V1-*.md` + 最小只读 data-center API（02）。未改策略公式、回测撮合、migration、live 写入、企微发送。

---

## 3. 页面状态矩阵

| 页面 | 状态 | 证据 |
|---|---|---|
| Dashboard | 通过（mock） | e2e 主路由 + heading |
| Data | 通过（mock） | Tab lazy + `paged=true`，无 `include_paths` |
| Market List | 通过（mock） | 「查看 K 线」可见 |
| Market Historical | 通过（mock） | 「历史」控件 |
| Market Live | 通过（边界） | 「Live」控件；指标上下文准确显示待服务端只读（04 residual） |
| Strategy | 通过（mock） | Registry≠validated；能力分类 |
| Backtest report 14/15 | 部分 | 只读 deep-link 可开；本轮 readonly report14 因后端超时未复验 |
| Trade / Order | 部分 | 代码闭环在 06/09；本轮无独立只读 API 复验 |
| Signal / Event / Notification | 通过（mock） | source_mode / 非自动下单；readonly 本轮超时 |
| Review | 通过（mock） | deep-link；readonly 本轮超时 |
| Runtime | 通过（mock） | Scheduler + After-Market Archive |
| Settings | 通过（mock） | 「测试连接」无写方法 |
| 1280×720 / 1440×900 | 通过 | mock e2e |
| error / empty / degraded | 通过（基础） | PageShell + RouteErrorFallback（01） |
| no console / path / secret | 通过（mock） | actionable console=0；无 `/Volumes` / secret 模式 |

---

## 4. formal / research / observation / legacy 边界

| 类别 | V1 表达 |
|---|---|
| formal research | JM 固定历史回测快捷任务；报告只读 |
| research-only | 通用回测表单；通用历史扫描；默认策略 Registry |
| observation-only | 前端 EMA 技术观察；HTDY historical/browser；Live Target preview |
| historical replay | Signal `jm_v1b_historical_replay` badge；非 live-confirmed |
| live-confirmed | 与 historical/replay 文案分层（08） |
| rejected | HTDY / Stage5 candidate；无 live enablement |
| legacy | Batch：`BATCH_BACKTEST_RESEARCH_ONLY`，默认禁用启动 |

---

## 5. 测试命令与原始结果（WEB-V1-12 复跑，2026-07-22）

| 命令 | 结果 |
|---|---|
| `git status --short --branch` | clean；`ahead 1` |
| `bash scripts/engineering/preflight.sh --json` | failed=0，warn=1（`data/parquet` missing） |
| `bash scripts/engineering/check-secrets.sh` | OK，scanned_files=9130 |
| `cd apps/quant-web && npm test` | 105 pass / 1 skipped / 0 fail |
| `cd apps/quant-web && npm run build` | 通过 |
| `PLAYWRIGHT_BASE_URL=http://127.0.0.1:5175 PLAYWRIGHT_CHANNEL=chrome npm run test:e2e` | **8 passed** |
| `npm run test:e2e:readonly` | **6 failed**（`127.0.0.1:8000` GET 超时 30s）；suite GET-only ok |
| 定向 pytest `-k "data_center or coverage or profile or strategy_registry or runtime_health"` | **164 passed**, 2 skipped |
| `git diff --check` | clean |

说明：WEB-V1-11 当日同一 readonly suite 曾对可达后端 **全部通过**；本轮失败判定为 **本机 API 进程无响应**（端口监听、curl/health 超时），不是前端回归。

---

## 6. Browser smoke

- Runner：`apps/quant-web/e2e/run-mock-smoke.mjs`（Node 26 下 bypass Playwright CLI hang）
- Mock 仅拦截 pathname `/api/*`，不伤 `/src/api/*`
- Channel：本机 Chrome
- 结果：`WEB_BROWSER_SMOKE_READY`（mock）保持；本轮真实后端 browser matrix **未完整复验**

---

## 7. Performance（既有结论，本轮未扩测）

- Data：首屏无无界 coverage；切「数据文件」才 `paged=true`
- Market：viewport / limit 有界（03）
- Live refresh：20s + hidden 停表 + in-flight 防重叠（04）
- 大表服务端分页（02）

---

## 8. 已知 residual

1. Live 指标完整 `historical_live_context_v1` 只读展示未接（准确显示 pending，不伪装 Ready）
2. Batch 页 ECharts `BarChart` 未注册 console 噪声（已在 e2e 过滤）
3. 本轮真实后端 readonly **阻塞**（API hung）
4. Stage 6 EOD real enable / T5 / T6 / T7 / `LONG_RUNNING_READY` 仍为后端 Gate；Web 只观察

---

## 9. 未完成项

- 后端恢复后重跑 `npm run test:e2e:readonly`，若通过可将 Gate 升为 `WEB_V1_READY`
- 可选：人工补跑 Market Live 指标上下文、report 15、Trade/Order 列表只读核对
- 创建/审查 PR（本步骤不 push）

---

## 10. 回滚方式

```bash
# 回退本分支 tip（含 web-v1-* commits）到合入前 main
git checkout cursor/web-v1-final
git reset --hard origin/main   # 仅在用户明确批准时

# 或按 commit revert：
git revert --no-edit 70ce8ea9..HEAD   # 视 tip 调整
```

不回滚 `data/`、report 14/15、Stage 6 receipt。

---

## 11. 不可宣称事项

- 不宣称 `WEB_V1_READY` / `WEB_V1_BROWSER_ACCEPTANCE_PASSED`（本轮）
- 不宣称 `JM_RUNTIME_READY` / 可实盘 / 策略盈利
- 不宣称 Batch formal / Registry=validated / HTDY live
- 不宣称 historical replay = live-confirmed
- 不修改 Stage 6 T4/T5/T6/T7 状态

---

## 12. 最终 Gate

```text
WEB_V1_PARTIAL
```

阻断原因：本轮 `test:e2e:readonly` 对 `127.0.0.1:8000` 超时。  
恢复条件：API 健康响应后 readonly 全绿，再开一次最小 WEB-V1-12b 文档升 Gate；届时才允许写 `WEB_V1_READY` 并最小更新 `STATUS.md`。
