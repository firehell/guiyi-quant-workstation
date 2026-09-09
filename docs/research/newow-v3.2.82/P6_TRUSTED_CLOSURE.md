# Newow P6 可信收口与真实工作站 MDS 证据

本文是2026-09-08的历史证据，只记录当时已发布`v1.10.0`与当时本地服务的只读核对；后续修复、发布与剩余Gate以`STATUS.md`为准。它不含原始Bar、凭据、通知内容或第三方原件，不授权Runtime、Scope、数据、DB、通知或交易写入。

## 1. 身份与运行前提

| 项目 | 只读事实 |
|---|---|
| 采集时间 | `2026-09-08 09:41:48 CST` |
| Release | `v1.10.0`；annotated tag object `d5faa6923011746a497efbca0aa9a7bdea1c8bb6`；peeled commit `f8f7d91765122c33cf5e82ed425b6c44f41ad0b1`；tree `ccb8f27a1a51e09602a4734c032918f063aa4df2` |
| GitHub Release | non-draft、non-prerelease，`2026-09-08T00:50:04Z`发布，target为同一peeled commit |
| 真实请求的API | 已加载`/Volumes/扩展盘/guiyi-quant-runtime-v1.10.0-r1@f8f7d91765122c33cf5e82ed425b6c44f41ad0b1`，clean、detached |
| 五服务身份 | API/Web为`v1.10.0@f8f7d917`；Live/After-market/Alert仍为`v1.9.15@36fef039`；两个Runtime marker在v1.10.0根下均未启用 |
| 只读health | API/Web HTTP 200，Runtime `ok / readonly=true`；五服务一致性`overall=failed, failures=9` |

因此本文的HTTP测量只归属已加载的`v1.10.0` API，不能归纳为五服务同版Runtime验收。

## 2. 真实MDS请求矩阵

所有请求串行访问现役本地`GET /api/v1/market/newow/strategy-detail`，冻结`as_of=2026-09-08T07:00:00+08:00`，`series_kind=actual_dominant`。未并发压测，未对失败项自动重试，未保存响应Bar。P95使用nearest-rank。

### 2.1 首30个operational品种

请求为`trend x 60m x chart_limit=500`，品种按`operational_products.txt`顺序：

```text
a, ag, al, ao, ap, au, b, bu, bz, c, cf, cj, cu, eb, ec,
eg, fg, fu, hc, i, j, jd, jm, l, lc, lh, m, ma, ni, oi
```

| 轮次 | 请求数 | HTTP | p50 | p95 | max | 响应字节 | input hash / owner / segment |
|---|---:|---|---:|---:|---:|---:|---|
| first pass | 30 | `500: 30` | 555.794 ms | 922.937 ms | 1016.008 ms | 每项42 | 全部不可用 |
| immediate same-identity pass | 30 | `500: 30` | 551.479 ms | 914.615 ms | 951.607 ms | 每项42 | 全部不可用 |

两轮每项只返回脱敏`NEWOW_INTERNAL_ERROR`；没有成功payload，故不存在可比较的input hash、owner或segment。第二轮不得解读为热缓存性能。

### 2.2 rb代表矩阵

`rb x {trend, oscillation, main_rise} x {1w, 1d, 60m} x {chart, MACD, reference, explanation, comparator}`共45项：

| 请求数 | HTTP | p50 | p95 | max | input hash / owner / segment |
|---:|---|---:|---:|---:|---|
| 45 | `500: 45` | 729.773 ms | 4119.610 ms | 4201.478 ms | 全部不可用 |

45项同样全部为42字节的脱敏`NEWOW_INTERNAL_ERROR`。reference错误路径约3.45–4.20秒，但这是失败路径耗时，不是成功的真实MDS产品性能。

## 3. 根因与修复边界

在同exact release代码和同一Git外运行配置下进行的一次只读进程内诊断定位到：

```text
NewowProductService
→ NewowProductReader.load
→ ActualDominantResearchSegmentLoader
→ MarketDataService.actual_dominant_segments
→ MarketDataError(MAIN_CONTRACT_MAP_MISSING)
```

这说明请求已进入真实`MarketDataService`，但冻结窗口不具备完整的权威rank-1主力映射。按当前合同必须fail-closed，不得缩短窗口、推测合约、回退continuous或补造映射。

同时发现`v1.10.0` API错误分类缺陷：稳定的`MarketDataError`未被路由显式处理，因此被包装为500。develop候选已以回归测试锁定，最小修复为统一映射到typed Web已知的`NEWOW_DATA_UNAVAILABLE`并返回HTTP 409；既不向Web泄露MDS内部code，也不改MDS或放宽数据Gate。该修复尚未进入`v1.10.0` Runtime。

数据质量结论：

```text
REAL_WORKSTATION_MDS_REQUEST_PATH = MEASURED
REAL_WORKSTATION_MDS_SUCCESS_PERFORMANCE = BLOCKED / INPUT_IDENTITY_UNAVAILABLE
LATENCY_SLA_RESULT = NOT_EVALUATED
```

没有预先批准的真实工作站SLA，因此不从上述时延发明pass/fail门槛。修复HTTP分类也不会使缺失的映射变完整；成功性能仍需在权威输入完整后对已发布exact Runtime重新只读验收。

## 4. 原始来源证据复审

仓库内GitHub-safe证据核对结果：

| 产物 | 结果 |
|---|---|
| `full-local-evidence-manifest.json` | 133项：96 captured、37 derived；SHA-256 `279aa0c3a88b6e6c5413387a57085dfe4c4d23a34befa751d95ced4c03be962f` |
| `source-registry.json` | 96项：86 GET、10 POST；SHA-256 `0b9e841c9d6af50acfc9adb924f90d4eb161e127db641198301b74a45c1e7dab` |
| manifest中的关键路径 | `strategy-calc-v3.2.82.js`、`verify_exact_page_cases.py`、`page-optimizer-oracle.json`、`core-parity-inputs.json`、`collect_exact_page_cases.mjs`均有登记 |
| 逻辑根`newow-strategy-detail-research/v3.2.82-gap-closure` | 已在本机Codex visualization archive中找到；其manifest及registry与仓库GitHub-safe副本逐字节一致 |
| manifest完整性 | `build_evidence_manifest.py --verify`为`OK / 133`，无缺失、额外或内容变化 |
| 来源重放 | 页面响应`27/27`、AI矩阵`16 + 5`、综合决策witness`13/13`、比较器`601 bars / [52,24,20,10,30]`均通过各自离线verifier |
| 当前Core重放 | 原包`verify_core_page_parity.py`依赖已退役的`CompositeAction`导出，对当前仓库返回`ImportError`；因此本轮不生成新的Core `27/27`声明 |

当前状态为：

```text
SOURCE_BUNDLE_PRESENT / INTEGRITY_VERIFIED / CURRENT_CORE_REPLAY_BLOCKED_INTERFACE_DRIFT
```

可用来源包没有关闭AC02/P3原件Gate，逐项结果如下：

- 页面诊断token：包内Core结果明确为`unavailable=27`，只有page prose和clean-room token，无稳定机器合同；
- 六组合输出oracle、评分与排序：包内只有单一交易日六策略完整分页截面，无历史`as_of`或服务端公式，page-exact公式与排名仍为`UNKNOWN / EVIDENCE_REQUIRED`；
- AI copy：27项只冻结输出hash，A-E与16组合只验证输入分支和输出token，不形成逐字copy合同；
- 目标/吸筹：27项HHV10/LLV10及页面展示已冻结，但Core verifier显式以`previous_close=None`运行，未证明权威昨收或期货owner parity；
- 比较器：离线source oracle已通过，但原包自身记录`browser_render_status=UNAVAILABLE_CONTROL_TIMEOUT`，没有browser-final K线/DOM/tie golden。

所以这些缺口继续保持`EVIDENCE_REQUIRED`；来源包可用不等于原件Gate已经通过。

已有18个D1/60m OOS结果和9个W1执行事实不足也不因本轮复审升级为`OOS_PASSED`。

## 5. P6收口结论

```text
P6_ENGINEERING = COMPLETE
P6_PRODUCT_EVIDENCE = PARTIAL_PRODUCT_EVIDENCE_REQUIRED
REAL_WORKSTATION_MDS = MEASURED / SUCCESS_PATH_BLOCKED
RUNTIME_SWITCH = NOT_EXECUTED
```

必须先有权威输入完整性和后续exact release下的成功响应测量，才能判定真实工作站MDS成功路径性能。本轮没有切换、重启、回滚或启用任何服务。

## 6. 五服务切换前只读回执

在clean、detached的`/Volumes/扩展盘/guiyi-quant-runtime-v1.10.0-r1@f8f7d91765122c33cf5e82ed425b6c44f41ad0b1`上执行安装器`--render-only`。五份渲染plist的`GUIYI_PROJECT_ROOT`均为该exact root，`GUIYI_RUNTIME_COMMIT`均为同一40位commit；渲染后Git状态仍为clean。

Market promotion只读preflight返回：

```json
{"schema_version":1,"command":"runtime.market-promotion-preflight","status":"passed","reason":"snapshot_ready","trading_day":"2026-09-08","operational_count":60,"snapshot_count":60}
```

Alert只读结构核对为`ready`：Git外通知配置是当前用户拥有的普通文件，file/parent权限分别为`0600/0700`；installed API与rendered Alert使用同一路径。核对过程未读取或输出配置内容。

最终再次运行`local-services-status.sh`仍为API/Web=`v1.10.0`、Live/After-market/Alert=`v1.9.15`，API/Web HTTP 200、Runtime health=`ok / readonly=true`、`overall=failed, failures=9`。因此只读preflight通过不等于同版Runtime已成立。

以下两个mutation入口明确停留在Gate前，均未执行：

```text
install-local-services.sh --confirm-market-runtime
install-local-services.sh --confirm-alert-runtime
```

另外，`develop@c59a204f986bbab31cb94cba238cd466e70903e4`中的typed 409修复不属于已发布`v1.10.0`；真实MDS成功路径仍被权威MainContractMap输入缺失阻塞。因此本回执只证明exact root的机械切换前条件，不授权或建议立即切换五服务。
