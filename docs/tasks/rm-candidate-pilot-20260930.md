# P7-19 RM 菜粕四周期历史候选闭环

状态：**COMPLETED / CANDIDATE_CLOSED，12/12 页面组合；允许集成 develop**。只处理 RM，未启动 PK。冻结产品/API/Web 源码 `9c59d58e285c52cc975468935fb559e207f01245`；窗口 `2023-01-01..2026-09-24`，`as_of=2026-09-24T07:00:00.000001+00:00`。1m 仅作可信聚合来源；验收范围是 `5m/15m/30m/60m × trend/oscillation/dual`。页面参考收益为零费零滑点的 `page_parity`、`executable=false`，不代表因果、Paper 或真实交易收益。

数据、维护、资产与 API 原始证据在 `outputs/rm-candidate-pilot-20260930/`，浏览器、49 张原图和独立审查在 `outputs/rm-candidate-prepared-20260930/`。原始输出不入 Git，失败报告保留。

## 数据与保存资产

RM 自身 rank1 Map 冻结 13 个物理 owner、52 个 owner×周期单元；初始仅 3 个 DATA_READY、49 个依赖缺口。原生 dry-run 列出 98 个去重 1m 源月和 402 个派生月目标；精确维护计划 SHA `1ea98d18231844729d118420fa3e209617620b0fe91e90aa312bd7eafb9a45de`。源额度、磁盘、同盘 scratch 原子发布与维护锁 preflight 通过。一次串行真实维护完成 52/52：49 READBACK_VERIFIED、3 NO_GAP，98 次 RQData price 请求、402 个派生目标，失败/重试为 0。attempt 与完成文件时间间隔约 622 秒，不等于全流程 walltime。

七频前后独立核对 PASS：98 个旧 dataset、942 个旧不可变文件全部保持；56 个扩展分区中 60,495 根旧 Bar 逐值保持，444 个新增分区仅在冻结目标内，396 个 D1/W1 分区不变。按照同物理合约 Canonical 1m 和 Session `(start,end]`，原生与独立 Parquet-only Decimal 均对完整前缀逐值复核：5m 192,759、15m 64,253、30m 33,536、60m 19,587，共 **310,135 根**，各周期 153 个物理合约月，全部 PASS。

隔离 schema 一次顺序构建 8 基础 + 4 融合流，耗时 541.608 秒，无重试。`source-assets-final-v5.json` 与 `independent-asset-final-v4.json` 分别读回、独立复核 12 流与四组融合依赖、plan/manifest/source token/revision/seq/checkpoint：均 READY、`enabled=false`、`activation_generation=0`；`complete_window_proven=false` 是资产字段，不冒充页面验收。API 12/12 READY；旧 token 409、UTC/null 与 fresh 恢复通过，API 阶段 192.920 秒。

## 浏览器与独立 Review

RM 专属 Playwright 会话在显式 open 后一次完成 19 场（12 分钟、6 日周、1 取消/短超时恢复），采集耗时 1815.990 秒；大场景按有序哈希分块完整传出，未截短响应数组或 SVG 点。`evidence-index.json` 对 19 场、49 张原图与 641 项证据绑定哈希；`offline-audit.json` 19 场数值 PASS。独立 Decimal/SVG 复核对 18 个图表场景验证 **22,057 笔 CLOSED 收益**、**22,093 个 SVG 点**，均 PASS；取消、实际短超时和 fresh/snapshot 恢复另有第 19 场原始证据。

首次独立浏览器数值脚本误沿用 M 合约前缀，错误报告 `independent-browser-numeric-review-v3.json` 原样保留；这属于审查脚本身份错误，不是 RM 采集失败。随后从 RM 自身 Map/依赖读回冻结 13 owner，先以真实 RM 正例及 M/未知 RM/错误 segment 负例验证身份 Gate，再另存修正版脚本及 `independent-browser-numeric-review-v4.json`，全 18 场 PASS。未重新下载、维护、构建或采集。此项返工未单独计时，不声称整个审查一次通过。

49 张原图逐张打开检查并在 `visual-review.json` 按 SHA/字节绑定，未见空白或错误页；分钟主图、Marker、完整参考曲线、较早窗口、日周参考记录与恢复后主图均可见。较早窗口密集 BUILD/CLEAR 和双模式标签局部遮挡 K 线；D1/W1 截图的 hover tooltip 有遮挡；W1 原生趋势转折当前 44/120 根，三个模式的辅助状态保留 WARMING。截图仅证明可见区域，完整数值和来源另以 API/离线/物理读回证明。浏览器审查无法从已暴露响应重放所有未暴露的融合候选动作选择；页面乐观收益不作为因果策略价值结论。

`pytest tests/newow_candidate_tools -q -p no:cacheprovider` 为 **159 passed**；含原生 HistoricalDataManager、ProductReader、CandidatePreview 的定向套件为 **429 passed**。RM 专属 Chrome session 已关闭；API/Web PID 675/757 经命令、cwd、端口精确核实后 SIGTERM，8012/5178 无监听；最终只读维护锁 granted=0/waiting=0。没有改正式分钟开放、Release/main/tag、Runtime、Scope、通知或账户。C、NI、FU 等暂缓状态及固定 21 品种分母均不变。

唯一最小下一步：总控按固定队列安排 **P7-20 PK**；本任务不自行启动 PK。
