# P7-18 M 豆粕四周期历史候选闭环

状态：**COMPLETED / CANDIDATE_CLOSED，12/12 页面组合；允许集成 develop**。只处理 M，未启动 RM。产品/API/Web 冻结源码 `a39ff3f7f8008a6e49e0d7c41b4c0effbe1d4a14`；候选窗口 `2023-01-01..2026-09-24`，`as_of=2026-09-24T07:00:00.000001+00:00`。1m 只作为可信聚合源；验收对象是 `5m/15m/30m/60m × trend/oscillation/dual`。页面参考收益为零费零滑点的 `page_parity`，`executable=false`，不代表因果收益、模拟或真实成交。

原始数据、维护、资产、API 与独立物理读回在 `outputs/m-candidate-pilot-20260930/`；首次缺 `open` 的采集在 `outputs/m-candidate-prepared-20260930/`，原生 CLI OOM 的采集在 `outputs/m-candidate-open-recovery-20260930/`，首次分块续采及会话状态故障在 `outputs/m-candidate-chunked-resume-20260930/`，最终 19 场证据在 `outputs/m-candidate-chunked-resume-v2-20260930/`。这些原始输出不提交 Git；四个目录互不覆盖，失败现场保留。

## 数据与保存资产

12 个物理 owner、48 个 owner×周期维护单元；初始 54 条 section 依赖记录含重复，48 条 UNAVAILABLE、6 条 READY。原生 dry-run 冻结 87 个去重 1m 源月及 356 个派生目标；精确维护计划 SHA `b57c61212583356ba7a86cfaf672146ee64c91203ed1ddcfecd56ff9f9bc0342`。同盘 scratch 原子发布读回、额度、磁盘、维护锁等 preflight 通过。一次串行维护完成 48/48，**45 READBACK_VERIFIED、3 NO_GAP；87 次真实 RQData price 请求、356 个派生目标，失败/重试 0**。attempt 到完成文件的间隔约 555 秒，不作为整个流程 walltime。

独立七频前后核对通过：91 个旧 dataset、902 个旧不可变文件全保留；51 个扩展分区的 71,399 条旧 Bar 逐值保留，392 个新增分区只在冻结目标内，369 个 D1/W1 分区不变。按同物理合约 Canonical 1m、Session `(start,end]` 完整前缀独立 Parquet-only Decimal 重聚合：5m 173,010、15m 57,670、30m 30,100、60m 17,580，共 **278,360 Bar**，四周期各 140 个物理合约月，全部 PASS。

隔离 schema 一次顺序构建 8 基础 + 4 融合流，约 499.756 秒，零重试。`source-assets-final-v5.json` 对 12 流读回 READY、`enabled=false`、`activation_generation=0`；`complete_window_proven=false` 仍是资产字段，不冒充页面验收。`independent-asset-final-v4.json` 独立核查 12 个 plan/manifest/source token/revision/seq/checkpoint 及 4 组融合依赖均 PASS。候选 API 12/12 READY；微秒旧 token 原生 409、UTC/null 与 fresh 恢复通过，API 阶段约 175.797 秒。正式 Scope、Runtime、通知及账户均未切换。

## 浏览器故障、续采与审查

首次 `capture` 未先打开 Playwright session，1.406 秒内按前置条件停止，零成功场景/截图。显式 `open` 后，第二次前两场 5m trend/oscillation 完整；第三场 5m dual 三张图已写但 CLI 返回 `Session closed`，没有完整结果。Node 崩溃报告确认 `V8::FatalProcessOutOfMemory` 位于 CLI 对整场返回值的 `JsonStringify`；本次 M 没有把旧窗口 409 误判为 OOM 原因。

采集器改为在同一 Playwright Page 保留完整场景对象，再按最多 1 Mi UTF-16 字符的块传输。每块校验 nonce、顺序、字节数、SHA-256 与终态；最终全量 JSON 哈希和原始对象一致，缺块、乱序、部分输出与会话丢失均阻塞。没有调大 Node heap、截短数组或删掉 SVG 点。真实 5m dual 以 **180 块、187,774,211 字节** 完整传出，且 42 条响应和三张图读回通过。第一版分块后的第 4 场因旧对象未释放而保护性停止；审查后修复并在新的专用 session 从第 4 场继续。最终目录按 SHA 复用前三场原始 raw/CLI/49 图中的九张及第三场所有 180 块附件；旧失败场景仍在原目录。四段采集文件间隔约 1.406、202.843、454.902、1124.304 秒，含两次工具返工，不声称一次采集成功或提速。

独立高风险代码 Review 发现并促成三项修复：续采必须复制分块清单/数据/全部块；离线索引必须把旧完整 CLI 或新小 ACK、脚本 nonce、完整块与 raw 绑定；失败的第 19 场也必须支持精确身份续接。见 `transport-review.json`。`python -m pytest tests/newow_candidate_tools -q -o cache_dir=/tmp/m-candidate-pytest-cache` 为 **159 passed**。最终 `evidence-index.json` 对 19 场、49 原图和 548 项文件证据逐项核哈希；`offline-audit.json` 为 19 场数值 PASS。另用只读、无应用算法导入的 Decimal/SVG 审计，对 18 个图表场景独立核算 **21,983 笔 CLOSED** 参考收益和 **22,019 个 SVG 点**，全 PASS。取消/短超时/fresh 恢复由第 19 场审计通过。

49 张原图逐张打开并按 SHA 保存于 `visual-review.json`，无空白或错误页；周期、模式、Marker、参考曲线、记录、较早窗口及日周兼容可见。密集双模式 Marker 标签遮挡、D1/W1 截图的光标 tooltip 遮挡和 W1 当前物理合约指标 `35/120` 根预热提示保留，不用视觉结果替代数值与来源审查。独立审计只能从已暴露的融合交易和曲线验证价格/累计，不能从浏览器响应重放所有未暴露的融合候选动作选择。页面乐观收益不作为因果策略价值结论。

M 专用浏览器 session 已关闭，专用 API/Web 进程 78095/78120 已按精确身份停止，8012/5178 不再监听。此处只关闭 **M 历史候选**；C 与 NI/FU 的暂缓边界不变，不开放正式分钟、不做 release/main/tag 或 Runtime promotion。维护 attempt 与失败浏览器证据保留，不盲重试已经完成的正式数据写入。

唯一最小下一步：总控按固定 21 品种队列安排 **P7-19 RM**；本任务不自行启动 RM。
