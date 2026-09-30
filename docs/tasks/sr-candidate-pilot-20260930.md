# P7-21 SR 白糖四周期历史候选闭环

状态：**COMPLETED / CANDIDATE_CLOSED，12/12 页面组合；允许集成 develop**。冻结产品/API/Web 源码 `d4ccfbd6799c183de9b2112878768898ae217649`，窗口 `2023-01-01..2026-09-24`，`as_of=2026-09-24T07:00:00.000001+00:00`。1m 仅为可信聚合来源；验收范围是 `5m/15m/30m/60m × trend/oscillation/dual`。页面参考收益为零费零滑点 `page_parity`、`executable=false`，不代表因果、Paper 或真实交易收益。

数据、维护、保存资产及 API 原始证据在 `outputs/sr-candidate-pilot-20260930/`；浏览器、49 张原图和独立审查在 `outputs/sr-candidate-prepared-20260930/`。原始输出不入 Git，保留在 SR 隔离 worktree。

## 数据、资产与 API

SR 自身 rank1 Map 冻结 14 个物理 owner、56 个 owner×周期单元。原生 dry-run 列出 110 个去重 1m 源月请求、448 个派生月目标；精确维护计划 SHA `450bae2f72ad5c1e31a56dc44a695661cd7f0ee3836b61f87c932ca91912ca43`。额度、磁盘、同盘 scratch 原子发布读回及维护锁 preflight 通过。一次串行真实维护完成 56/56：53 READBACK_VERIFIED、3 NO_GAP；110 次 RQData price 请求、448 个派生目标，未重试。

七频前后独立核对 PASS：105 个旧 dataset、957 个旧不可变文件保持；61 个扩展分区中 79,171 根旧 Bar 逐值保持，497 个新增分区仅在冻结目标内，D1/W1 分区不变。按照同物理合约 Canonical 1m 和 Session `(start,end]`，原生与独立 Parquet-only Decimal 对完整前缀逐值复核：5m 202,644、15m 67,548、30m 35,256、60m 20,592，共 **326,040 根**；每周期 14 个 owner、163 个物理合约月，全部 PASS。依赖读回 56/56 DATA_READY。

隔离 schema `newow_intraday_pilot_20260927` 一次顺序构建 8 基础 + 4 融合保存流，无重试。`source-assets-final-v5.json` 与 `independent-asset-final-v4.json` 分别原生读回、独立复核 12 流和四组融合依赖，以及 plan/manifest/source token/revision/seq/checkpoint：均 READY、`enabled=false`、`activation_generation=0`；`complete_window_proven=false` 是保存资产字段，不能冒充页面验收。API 12/12 READY；旧 token 409、UTC/null 和 fresh 恢复通过。

## 浏览器与独立 Review

SR 专属 Chrome 会话一次完成 19 场（12 分钟、6 日周、1 取消/短超时恢复），无重采。`evidence-index.json` 绑定 19 场、49 张原图和 646 项证据哈希；`offline-audit.json` 19 场数值 PASS，视觉状态由单独的 `visual-review.json` 结案。独立 Decimal/SVG 核算 18 个图表场景的 **22,142 笔 CLOSED 价格收益**及 **22,178 个 SVG 点**，全部 PASS；SR2303 正例及 M2501/PK2304/SR9999/错误 segment 负例验证物理身份 Gate。第 19 场实际客户端短超时为 `AbortError`、约 0.254 秒；取消后返回 5m trend、旧 snapshot token 409 与 fresh 恢复均有原始证据。

49 张原图逐张打开检查并在 `visual-review.json` 按 SHA/字节绑定，未见空白或错误页；分钟主图、Marker、完整参考曲线、较早窗口、日周记录与恢复后主图可见。较早窗口密集标签局部重叠；日周和取消场景的 hover tooltip 遮挡少量图表区域；W1 辅助状态显示原生 warm-up。截图只证明可见区域；完整数值和来源另由 API、Parquet 与独立数值证据核对。浏览器响应未暴露全部历史融合候选动作，独立审查无法完整重放融合选择状态机，不据此声称因果价值。

`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:services/quant-api:packages/quant-core .../.venv/bin/python -m pytest tests/newow_candidate_tools -q -p no:cacheprovider`：**159 passed**；HistoricalDataManager、ProductReader、CandidatePreview、snapshot cache、fusion reference 定向套件：**457 passed**。SR 专属 API/Web/Chrome PID 经命令及工作目录核实后 SIGTERM；8012/5178 无监听，最终只读维护锁 granted=0/waiting=0。无产品源码、公式或策略版本变更。正式分钟开放、main/tag/release、Runtime、Scope、通知和账户均未触碰；固定 21 品种分母保持。

唯一最小下一步：总控核实 SR 集成 SHA，结束本轮 21 品种历史候选队列的状态核对；暂缓品种仍按各自证据处理。
