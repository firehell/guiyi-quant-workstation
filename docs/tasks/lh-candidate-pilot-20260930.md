# P7-17 LH 生猪四周期历史候选闭环

状态：**COMPLETED / CANDIDATE_CLOSED，12/12 页面组合，允许集成 develop**。仅处理 LH，不启动 M。冻结产品/API/Web 源码 `c57784a64e849e9b8224c3a9629ed0491c394842`；采集工具有本任务的取消请求绑定修正，见下文。隔离分支 `codex/lh-candidate-pilot`，候选窗口 `2023-01-01..2026-09-24`，`as_of=2026-09-24T07:00:00.000001+00:00`。1m 仅为可信聚合源；验收对象为 `5m/15m/30m/60m × trend/oscillation/dual`，共 4 输入、8 基础、4 融合流和 12 页面组合。ReferenceTrade 是零费零滑点的 `page_parity`，`executable=false`，不是因果收益或账户成交。

原始数据与资产证据位于本任务 worktree 的 `outputs/lh-candidate-pilot-20260930/`，准备及失败浏览器证据位于 `outputs/lh-candidate-prepared-20260930/`，续采及最终浏览器证据位于 `outputs/lh-candidate-resumed-20260930/`。它们不纳入 Git；本记录只引用原始只读证据，未以转述替代文件。正式 API/Web、Runtime、Scope、通知、账户和交易均未切换。

## 数据与物理前缀

初始 readiness 有 **91 个 section 依赖记录**，其中 7 个是同 owner×frequency 在不同 section 的重复检查；独立执行分母为 **21 个物理 owner × 4 周期 = 84 单元**。起初 6 条 section 记录 READY、85 UNAVAILABLE；冻结精确维护单元为 81 个需修复、3 个 NO_GAP。LH 权威窗口配置为 `2021-01-08,rq_or_listing_start`；Instrument 自身上市字段未被伪称已知，维护以现有权威 mapping/Session 与实际物理合约前缀执行。

原生 HistoricalDataManager dry-run 冻结 196 个去重 1m 源月及 794 个派生月，所有源请求的保守预算 830,592,000 bytes，运行前额度剩余 1,054,960,822 bytes。冻结计划 SHA `9840615989eb81c25eafdc6132b028cb8b8ad53ad951f25917a20fba55dc738b`，执行脚本 SHA `08931a91e7cfe89d4d92366a7d19e4cc9669e1ecd3f3e14819735f823d5841ce`，旧七频快照 SHA `4e9cc3d1d31824f81167cf76bb372896ee104dad68ab4e0f826d80f6e06a1512`。同盘 scratch 原子发布读回、维护锁、磁盘和额度 preflight 通过。该预算是预留估算，不等于实际网络字节。

一次串行维护完成 84/84：**81 READBACK_VERIFIED、3 NO_GAP；196 次真实 RQData price 请求、794 个派生目标；失败与重试 0**。源月按去重对象计，不把各周期重复引用的 784 次请求表述为真实下载。attempt 至完成证据间隔 674.902 秒，不声称是整个 Python 进程 walltime。见 `campaign-complete.json` 与逐单元 plan/attempt/result/readback。

独立七频前后读回：154 个 dataset、1165→2059 个文件；旧 1165 个不可变文件全部保留，96 个扩展分区的 85,144 条旧 Bar 逐值保留，579 个 D1/W1 分区不变；894 个新增分区全部落在冻结的 990 个计划目标内。四周期同物理合约 Canonical 1m 全前缀重聚合通过，另用 Parquet-only Decimal 脚本逐 Bar 核对 OHLCV/OI/时间/Session `(start,end]`：5m 197,775、15m 65,925、30m 35,160、60m 21,975，共 **320,835 Bar**，每周期 21 owner/251 物理月。LH 实际日盘 09:00–10:15、10:30–11:30、13:30–15:00；60m 短尾单独核对。最终 84/84 DATA_READY。数据差异与重算证据分别见 `seven-frequency-difference.json`、`aggregation-*-full-prefix-readback.json`、独立逐值报告及最终依赖读回。

## 保存资产与 API

隔离 schema `newow_intraday_pilot_20260927` 从空流一次顺序构建 8 基础 + 4 融合，无构建重试，实测构建阶段 506.789 秒。`source-assets-final-v5.json` 对 12 流读回均 READY、`enabled=false`、`activation_generation=0`；`coverage-expected.json` 核对 8 基础流的完整范围。独立 `independent-asset-final-v4.json` 复核 12 个 plan/manifest/source token/revision/seq/checkpoint 与 4 组融合输入依赖均 PASS。没有将候选流晋升为 active；`complete_window_proven=false` 仍是资产状态，不用其冒充页面验收。

`prepare`、真实候选 API/Web preflight 均通过，预览能力仅返回 LH singleton，任务身份 `f9b8ee6c91f91538daee0af82c60ac09da1a1c526450d7472007e0b629662fbd`。API `api-v5/summary.json` 为 12/12 READY，主图、参考记录/曲线、分页、辅助、双策略、快照均按原生边界读回，实测 152.217 秒；`api-v5/independent-utc-null-v1.json` 检查 Z/+00、原生 null、微秒旧 token 409 及 fresh 恢复，通过，实测 6.534 秒。首次 API 总包装器在尝试重复写已存在的 coverage 输出时于 0.935 秒 fail-closed，**零 GET**；原日志保留，随后仅执行此前未开始的 API 审计，没有重建数据或资产。

## 浏览器续采、Review 与限制

真实 Chrome 对候选 Web 5178/API 8012、固定源码/as_of 做页面操作；XHR 只被动观察，没有 mock 或改写响应。首次采集在第 10 场 `60m trend` 导航等待超时，前 9 场 27 张原图完整，失败场没有 `full_capture`、`earlier_capture` 或 `final`，不能计入 12/12。原 `collection-observations.json`、失败 CLI/raw/progress 与诊断截图保留。现场请求记录显示 D1 explanation #4 被取消，同 URL #7 成功；浏览器内 observer 只有 #7 的一条响应，旧绑定器却等待两个 peer，最终 `pending_body_reads=1` 而 DOM 目标已稳定。共享 `browser/minute.js` 只排除明确失败的请求；缺失真正响应、HTTP 不匹配和含错误 observer row 仍 fail-closed。定向 Node 回归覆盖取消后同 URL 成功、缺失响应和 HTTP 错配，随后实际第 10 场通过。

续采脚本只按 SHA 拷贝首 9 场有效证据到新目录，并保存原失败 `collection-observations` 与第 10 场 raw/CLI 的引用；从第 10 场继续采 10 场，原目录未覆盖、未自动重放。最终 `collection-observations.json` 为 19/19 `OBSERVED_NEEDS_VISUAL_REVIEW`；`evidence-index.json` 锁定 94 项证据、49 张原始图片；`offline-audit.json` 为 19 场数值 PASS（12 分钟、6 日周兼容、1 取消/短超时/fresh 恢复）。独立 `independent-browser-numeric-review-v3.json` 对 18 个页面场景全通过，按 Decimal 价格独立核算 **14,578 笔 CLOSED** 参考收益、**14,614 个 SVG 曲线点**，没有用截短数组替代全窗口。49 原图逐张/13 组联系图视觉检查通过，记录在 `visual-review.json`；可见周期/模式、Marker、累计曲线、记录、较早窗口与日周兼容均与审计一致。

首次浏览器失败采集约 581.414 秒，续采约 477.963 秒；效率统计计入第 10 场工具返工，**不声称一次 19 场无重采**，也不把两段约 1059.377 秒解释为不含诊断的整体耗时。密集 Marker 遮挡、较早窗口副图短窗、报价/持有过程的既有显示限制如实保留；页面参考累计曲线不等于因果研究或模拟账户收益。独立审计能够核验已持久化的融合交易价格与累计/SVG 投影，不能从浏览器响应重放未暴露的所有融合候选动作选择；该边界不影响本次 page-parity 候选闭环声明。

## 工程验证与交付边界

- `PYTHONPATH=. pytest -q tests/newow_candidate_tools`：150 passed；其中新增定向绑定回归 1 passed。`git diff --check` 通过。
- 精确证据：84/84 DATA_READY、12/12 disabled 资产 READY、API 12/12 READY、Chrome 12/12 页面通过、日周6/6兼容及取消恢复通过；数据/资产/页面独立数值与视觉读回无 Confirmed Issue。Review 风险只剩上文限定的 UI 展示与无法从页面重放全部融合内部动作。
- 此处只关闭 **LH 历史候选**，不开放正式分钟、不做 release/main/tag、Runtime promotion、Scope/通知、Paper/真实账户或交易。维护 plan/attempt 和旧不可变文件保留；后续问题只能据精确对象 forward 修复，不能盲重试本次已完成维护。

唯一最小下一步：总控按固定 21 品种队列安排 **P7-18 M**；本任务不替它执行或创建会话。
