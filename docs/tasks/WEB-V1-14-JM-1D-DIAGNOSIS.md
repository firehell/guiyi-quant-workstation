# WEB-V1-14 JM 1D 只读根因诊断

日期：2026-07-26
任务：`WEB-V1-14-01-JM-1D-DIAGNOSIS`
基线：`c890b757`（`main@1805af2e` + Step 0 文档）

```text
JM_1D_ISSUE_CLASSIFIED
BROWSER_MULTI_FILE_WARNING_EXPECTED
NO_WARNING_SUPPRESSED
NO_DATA_WRITE
```

## 1. 结论

用户截图中的：

```text
jm / jm.MAIN / 1d / historical / browser / no profile
```

属于：

```text
BROWSER_MULTI_FILE_WARNING_EXPECTED
```

Browser 模式读取 6 个已登记资产，发现 20 个跨文件 OHLCV 冲突并返回 `quality.status=warning`。API 返回给图表的日线 key 已唯一，Kline 的日线 key/merge/render 没有复现重复或错位。

同一上下文切换到合法 `long_horizon_daily_v1` Research Profile 后，只读 API 绑定单一 immutable `MarketDataFile 103949`，质量 `passed`、冲突为 0、`strict_research_ready=true`。因此：

- 不修数据；
- 不隐藏 warning；
- Browser 保持“仅观察”；
- Web 应解释多文件冲突影响并提供 Profile 入口；
- 不能把 Browser 结果写成 strict research 可用。

诊断还发现一个独立 Web 深链初始化缺陷：

```text
access_mode=research + profile_id + contract + period
```

直接刷新时，首个 coverage 请求只发送 `symbol/profile_id/access_mode`，漏传 `contract/period`，所以 API 正确返回：

```text
422 MARKET_RESEARCH_PROFILE_REQUIRED
```

直接 API 对同一完整参数返回 200/passed，说明这是前端 `scopedCoverageParams()` 的 route hydration 参数缺失，不是 Profile 或数据资产失败。该问题在 Step 3 以测试驱动方式修复；本诊断步骤不修改产品代码。

## 2. 只读执行身份

| 项 | 值 |
|---|---|
| Candidate API | `127.0.0.1:8010` |
| Candidate Web | `127.0.0.1:5177` |
| API process | 单进程、无 reload |
| PostgreSQL | `default_transaction_read_only=on` |
| Session | `transaction_read_only=on` |
| HTTP methods | `GET` only |
| Matrix requests | 32 |
| Alembic | NOT RUN |
| Worker/Scheduler | NOT RUN |
| Notification | NOT RUN |
| Runtime checkout/deploy | NOT CHANGED |

只读探针仅输出 on/off 标志，未输出连接串或凭据。

## 3. 对照矩阵

| Case | Coverage | Bars / quality | Conflict | Binding / lineage | 判定 |
|---|---|---|---:|---|---|
| `jm.MAIN 1d` Browser | 6 versions / 17,756 rows | 500 / warning | 20 | 6 file IDs；strict=false | 真实多文件 warning |
| `jm.MAIN 1d` Research | 1 version / 3,237 rows | 500 / passed | 0 | file `103949`；strict=true | 合法严格研究 |
| `JM2609 1d` Browser | 8 versions / 416 rows | 91 / warning | 5 | 8 file IDs；strict=false | actual Browser 也存在多文件 warning |
| `JM2609 1d` Research | 1 version / 34 rows | 34 / passed | 0 | file `103996`；strict=true | 合法严格研究 |
| `jm.MAIN 15m` Browser | 3 versions / 181,204 rows | 500 / passed | 0 | 3 file IDs；strict=false | 问题不属于通用主连/组件 |
| `jm.MAIN 15m` Research | 1 version / 72,871 rows | 500 / passed | 0 | file `103953`；strict=true | 合法严格研究 |
| `a.MAIN 1d` Browser | 2 versions / 7,487 rows | 500 / passed | 0 | 2 file IDs；strict=false | 其他 1D 无同类冲突 |
| `a.MAIN 1d` Research | 1 version / 5,908 rows | 500 / passed | 0 | file `82673`；strict=true | 合法严格研究 |

所有 8 个 bars 响应：

- status 200；
- 返回 key 无重复；
- bars/EMA/MACD lineage token 一致；
- indicators/MACD status 200；
- 无物理路径回显。

## 4. JM Browser 冲突事实

### Continuous 1D

```text
quality.status=warning
warning_reasons=["cross_file_conflicts=20"]
market_data_file_ids=[82699,103930,103937,103949,103956,56482]
data_versions_count=6
source_intervals=["1m"]
strict_research_ready=false
```

前三个冲突 key 为 `2013-03-26`、`2013-03-28`、`2013-04-02`；冲突字段包含 `low` 和 `volume`。这些是历史多文件证据，不是图表产生的重复。

### Actual 1D

```text
quality.status=warning
warning_reasons=["cross_file_conflicts=5"]
market_data_file_ids=[34104,103941,103960,103975,103982,103989,103996,103922]
data_versions_count=8
source_intervals=["1d","1m"]
strict_research_ready=false
```

Research Profile 选择 file `103996` 后为 passed/0 conflict。

## 5. Browser 浏览器复现

入口：

```text
/market/chart?symbol=jm&contract=jm.MAIN&period=1d
```

浏览器结果：

- 主连研究 / 历史 / 浏览；
- `warning (cross_file_conflicts=20)` 可见；
- 质量提示没有被隐藏；
- chart 内存在重复的大型冲突 banner，需要按 Step 4 收敛为紧凑标记；
- console error=0；
- API 网络方法仅 GET；
- bars、EMA、MACD status 200；
- 页面可完整渲染 3,237 根唯一日线。

本地只读截图：

```text
apps/quant-web/.playwright-cli/page-2026-07-26T05-27-14-818Z.png  # 1440x900
apps/quant-web/.playwright-cli/page-2026-07-26T05-27-16-535Z.png  # 1280x720
apps/quant-web/.playwright-cli/page-2026-07-26T05-27-18-006Z.png  # 1024x768
```

截图是候选 Web + readonly API 证据，不是 Runtime 部署证据。

## 6. Research 深链缺陷

直接打开：

```text
/market/chart?symbol=jm&contract=jm.MAIN&period=1d
&contract_view=continuous
&data_mode=historical
&access_mode=research
&profile_id=long_horizon_daily_v1
```

实际首个 coverage 请求：

```text
GET /market/workbench/coverage
  ?symbol=jm
  &profile_id=long_horizon_daily_v1
  &access_mode=research
  &include_paths=false
```

缺少：

```text
contract=jm.MAIN
period=1d
```

根因位置：

```text
apps/quant-web/src/utils/marketChartInit.ts
  scopedCoverageParams()
apps/quant-web/tests/chartInit.test.ts
  现有预期也错误地省略 contract/period
```

Step 3 修复合同：

1. 先把 `chartInit.test.ts` 的 Research coverage 预期改为包含 route contract/period；
2. 确认测试因当前实现漏字段而失败；
3. 最小修改 `scopedCoverageParams()`；
4. Browser 只传 symbol 的列表/初始场景保持兼容；
5. 真实 Research refresh/back/forward 重跑为 200/passed；
6. Profile 缺失仍 fail-closed。

## 7. 不做事项

- 不修改 MarketDataFile、Profile binding 或 active 数据；
- 不改变 Browser 多文件读取优先级；
- 不静默选择“最新”文件；
- 不移除冲突 warning；
- 不修改后端 dedupe/quality；
- 不修改 Kline daily time key；
- 不把 Browser warning 解释为数据整体失败；
- 不把 Research passed 扩写为策略、回测、Runtime 或交易 Ready。

## 8. 后续处理

本分支可继续 Web polish：

```text
Step 2 Design System
→ Step 3 Context/Evidence + Research deep-link fix
→ Step 4 Quality Impact
```

无需创建 data/backend 修复任务；现有冲突证据由 Web 诚实解释即可。全历史 residual 治理仍属于既有 `DATA_LAYER_REAUDIT_REQUIRED`，不在本任务扩围。
