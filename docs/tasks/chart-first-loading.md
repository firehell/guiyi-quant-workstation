# 看盘价格优先与有界缓存

范围：用户批准的看盘路径优化，仅 develop 与独立5175/8002预览。不发布、不切正式Runtime、不维护行情、不改公式或收益窗口。
基线 `ee6f804e234041291c92d025397952f202e2efd8`，任务分支 `codex/chart-first-loading`。

## 实现与验收映射

| 项目 | 实现 | 验证 |
| --- | --- | --- |
| 价格先可看 | 页面层 `useDetailPricePreview` + 公共 `DetailPricePreview`；能力失败仍恢复价格 | 桌面/390px、API离线、缓存恢复浏览器场景 |
| 一次解析与主图 | 日周 `resolve_with_chart`，`strategy-detail?resolve_current=true` 返回同一结果与typed context | 日周解析、严格API、显式cutoff逐值相同 |
| 身份隔离 | generation、取消、当前重验；pending只保留价格；显式历史独立 | 旧响应、token/游标、修订、合约与窗口既有回归；新增pending和刷新 |
| 加载顺序 | 当前主图→辅助；可见解释、收益；双策略参考同样等待收益区 | IO节点替换、实验切回正式策略、参考延迟场景 |
| 缓存 | 价格常驻8MiB/磁盘32MiB/7天；目录显示24小时；能力共享5分钟及ETag；冻结run/hash | 有界/过期/损坏/磁盘失败/304无body/取消测试 |
| 权威重验 | strategy-detail绕过浏览器TTL body，保留在途合并；后端缓存逐事实验证不变 | session revalidation及service/cache全量定向回归 |
| 资源与传输 | 全局GET 2并发、最后订阅取消、gzip；重型Gate及后端预算不变 | admission/cancel/gzip/缓存与门禁测试 |
| 目录读取 | SQL max-date join每品种只装配最新映射，不把全历史加载入ORM | 100行历史只加载1行，原最新日期/合约不变 |

价格缓存不是质量、映射、策略或收益权威；显示截止时间。磁盘恢复有最多32MiB内容及克隆的短时分配，
操作串行，等写入结束后释放暂存Map；8MiB指常驻价格快缓存，不代表进程总峰值。
当前报价和Live链路保持独立，无全品种预热、新Redis或后台任务。

## 实际验证入口

全部串行，浏览器workers=1；Web unit heap512MiB，类型/build heap768MiB。

```sh
NODE_OPTIONS=--max-old-space-size=512 pnpm -C apps/quant-web test
NODE_OPTIONS=--max-old-space-size=768 pnpm -C apps/quant-web build
NODE_OPTIONS=--max-old-space-size=512 pnpm -C apps/quant-web exec playwright test -c playwright.config.mjs e2e/chart-first-loading.spec.mjs --workers=1
REAL_DEVELOP=1 PLAYWRIGHT_BASE_URL=http://127.0.0.1:5175 PLAYWRIGHT_SKIP_WEBSERVER=1 NODE_OPTIONS=--max-old-space-size=512 pnpm -C apps/quant-web exec playwright test -c playwright.config.mjs e2e/chart-first-readonly.spec.mjs --workers=1
```

受影响后端组合356 passed：日周snapshot、product API/service/snapshot cache/resource gate/inflight、
catalog/service、market home API、capability与仓库卫生。Ruff通过。
最终完整Web1146 passed/3 skipped；浏览器控制场景8 passed，含手动刷新只发一次bootstrap、能力接口离线、实验切回正式策略。
类型/build/topology、Ruff、OpenSpec strict11项、secret scan零发现、diff检查通过。
真实开发验收三个场景均通过：五步瀑布、20次新存储P95、手动刷新。手动刷新只发一次bootstrap；
价格/主图传输body约22,266/44,508字节，能力条件请求body为0字节。瀑布使用完成请求的timing及sizes记录，未重复读取响应大JSON。
独立静态Review的双策略参考懒加载、能力取消和实验切回收益IO三项已修复并关闭，无剩余确认问题。

## 性能证据与边界

固定JM/RB、真实开发API的单次独立样本：价格257/148ms；合并主图720/633ms；gzip主图44,477/43,305字节，
未压缩503,723/509,806字节。同as_of新旧主图及token相同。该对照不修改原公式或冻结研究产物。
真实浏览器矩阵覆盖首次进入、RB切换、JM缓存返回、60m和策略切换；API瀑布及JS堆采样由read-only测试输出。
最终真实浏览器矩阵（ms；价格从navigation计，缓存恢复另列）：

| 场景 | 价格出现 | 正式主图 | JS堆采样 |
| --- | ---: | ---: | ---: |
| JM日线震荡首次 | 475 | 1521 | 30.2MiB |
| RB日线 | 679 | 1420 | 33.2MiB |
| JM缓存返回 | 125（挂载后30） | 1447 | 34.2MiB |
| JM切60m | 237 | 1933 | 46.4MiB |
| JM切趋势日线 | 115（挂载后34） | 3412 | 31.4MiB |
| JM手动刷新 | 保留价格预览 | 1402 | 42.1MiB |

主图在部分解释竞争样本仍需约3.4秒，价格已可操作，不声称所有策略重任务低延迟。

最终代码20次新浏览器存储进入样本P95约877ms、最慢1746ms；已有开发API与Vite服务，不是服务冷启动P95。
IndexedDB断网价格预览约10–12ms（页面区域挂载至价格标签恢复）。
最终浏览器五步矩阵JS堆采样最高约46.4MiB；20次新存储样本最高约33.8MiB。开发API40秒/80次RSS采样峰值约238.5MiB、末值约206.8MiB；这不是整机峰值证明。
首轮typecheck在512MiB堆限制退出，独立改用768MiB后通过；未并行叠加测试/构建/浏览器。

保留所有既有未提交研究产物。没有正式发布、Runtime切换、数据补齐或真实通知操作。

受影响后端实际命令：

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:services/quant-api:packages/quant-core services/quant-api/.venv/bin/python -m pytest services/quant-api/tests/newow/test_daily_snapshot.py services/quant-api/tests/newow/test_weekly_snapshot.py services/quant-api/tests/newow/test_market_newow_product_api.py services/quant-api/tests/newow/test_product_service.py services/quant-api/tests/newow/test_product_snapshot_cache.py services/quant-api/tests/newow/test_product_resource_gate.py services/quant-api/tests/newow/test_product_inflight.py services/quant-api/tests/data_foundation/test_catalog_and_service.py services/quant-api/tests/test_market_home_api.py tests/engineering/test_newow_capability_contract.py tests/engineering/test_repository_hygiene.py -q
openspec validate --specs --strict --no-interactive
python3 scripts/engineering/secret_scan.py --json
git diff --check
```
