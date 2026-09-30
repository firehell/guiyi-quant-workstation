# P7-20 PK 花生四周期历史候选闭环

状态：**COMPLETED / CANDIDATE_CLOSED，12/12 页面组合；允许集成 develop**。本项仅处理 PK，未启动 SR。冻结产品/API/Web 源码 `9cc41bdd56ca8576a17aae6c1363576d65cd9837`，窗口 `2023-01-01..2026-09-24`，`as_of=2026-09-24T07:00:00.000001+00:00`。1m 仅为可信聚合来源；验收范围是 `5m/15m/30m/60m × trend/oscillation/dual`。页面参考收益为零费零滑点 `page_parity`、`executable=false`，不代表因果、Paper 或真实交易收益。

数据、维护、保存资产及 API 原始证据在 `outputs/pk-candidate-pilot-20260930/`；浏览器、49 张原图和独立审查在 `outputs/pk-candidate-prepared-20260930/`。原始输出不入 Git；首次 API wrapper 失败文件保留。

## 数据、资产与 API

PK 自身 rank1 Map 冻结 18 个物理 owner、72 个 owner×周期单元；初始 3 个 DATA_READY、69 个依赖缺口。原生 dry-run 列出 152 个去重 1m 源月请求、617 个派生月目标；精确维护计划 SHA `12608bb525ccd8350efd23f6353e099376ad0adaca9defd3f1cb5bc9976e56e0`。源额度、磁盘、同盘 scratch 原子发布读回及维护锁 preflight 通过。一次串行真实维护完成 72/72：69 READBACK_VERIFIED、3 NO_GAP；152 次 RQData price 请求、617 个派生目标，失败和重试为 0。

七频前后独立核对 PASS：133 个旧 dataset、1065 个旧不可变文件保持；81 个扩展分区中 53,539 根旧 Bar 逐值保持，688 个新增分区仅在冻结目标内，498 个 D1/W1 分区不变。按照同物理合约 Canonical 1m 和 Session `(start,end]`，原生与独立 Parquet-only Decimal 对完整前缀逐值复核：5m 170,505、15m 56,835、30m 30,312、60m 18,945，共 **276,597 根**；每周期 18 个 owner、206 个物理合约月，全部 PASS。

隔离 schema 一次顺序构建 8 基础 + 4 融合保存流，无重试。`source-assets-final-v5.json` 与 `independent-asset-final-v4.json` 分别原生读回、独立复核 12 流和四组融合依赖，以及 plan/manifest/source token/revision/seq/checkpoint：均 READY、`enabled=false`、`activation_generation=0`；`complete_window_proven=false` 是保存资产字段，不能冒充页面验收。API 12/12 READY；旧 token 409、UTC/null 和 fresh 恢复通过。API 读回本体约 156 秒，不包括准备与审查。

首次 API wrapper 把已成功生成的 `coverage-expected.json` 再次交给带拒绝覆盖保护的脚本，第一步 `PRESERVE_PREVIOUS_COVERAGE` 失败、零 GET。该失败及原文件均保留；随后仅执行未运行过的原生 API 读回与独立 UTC/null 核对，均 PASS，未重跑维护、资产或浏览器。根因是临时编排脚本重复调用已完成的 coverage 步骤，不是 PK 数据或 API 缺陷。冻结源码和验收身份期间不改共享工具；后续通用工具应在 exact product/code SHA/source evidence 匹配时只读复用已生成 coverage，对错误身份或缺失文件 fail-closed，并用负例验证。

## 浏览器与独立 Review

PK 专属 Chrome 会话一次完成 19 场（12 分钟、6 日周、1 取消/短超时恢复），无重采。`evidence-index.json` 绑定 19 场、49 张原图和 509 项证据哈希；`offline-audit.json` 19 场数值 PASS。独立 Decimal/SVG 核算 18 个图表场景的 **15,109 笔 CLOSED 价格收益**及 **15,145 个 SVG 点**，全部 PASS；PK2304 正例及 M2501/RM2305/PK9999/错误 segment 负例验证身份 Gate。第 19 场实际客户端短超时为 `AbortError`、约 0.252 秒；取消后返回 5m trend、旧 snapshot token 409 与 fresh 恢复均有原始证据。

49 张原图逐张打开检查并在 `visual-review.json` 按 SHA/字节绑定，未见空白或错误页；分钟主图、Marker、完整参考曲线、较早窗口、日周记录与恢复后主图可见。较早窗口密集 BUILD/CLEAR 和双模式标签局部遮挡 K 线；D1/W1 截图的 hover tooltip 有遮挡；W1 趋势转折仍为原生 `39/120 WARMING`。截图只证明可见区域；完整数值和来源另由 API、Parquet 与独立数值证据核对。浏览器响应未暴露全部历史融合候选动作，独立审查无法完整重放融合选择状态机，不据此声称因果价值。

`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:services/quant-api:packages/quant-core .../.venv/bin/python -m pytest tests/newow_candidate_tools -q -p no:cacheprovider`：**159 passed**；HistoricalDataManager、ProductReader、CandidatePreview、snapshot cache、fusion reference 定向套件：**457 passed**。PK 专属 Chrome session 已关闭；API/Web PID 22022/22058 经命令和端口精确核实后 SIGTERM，8012/5178 无监听；最终只读维护锁 granted=0/waiting=0。无产品源码、公式或策略版本变更。正式分钟开放、main/tag/release、Runtime、Scope、通知和账户均未触碰；C/NI/FU 等暂缓行与固定 21 品种分母保持。

唯一最小下一步：总控核实 PK 集成 SHA 后，按固定队列安排 **P7-21 SR**；本任务不自行启动 SR。
