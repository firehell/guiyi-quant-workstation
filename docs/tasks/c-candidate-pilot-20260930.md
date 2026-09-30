# P7-16 C 玉米历史候选暂缓

状态：**PARTIAL / DEFERRED_BROWSER_BLOCKED，0/12 页面闭环**。仅处理 C；固定 21 品种分母不变，未启动 LH。冻结源码 `1207514b48c5bacbf86b3a8d0bb026e38ec150c0`；窗口 `2023-01-01..2026-09-24`，`as_of=2026-09-24T07:00:00.000001+00:00`。1m 仅作为 5m/15m/30m/60m Canonical 聚合来源。12 条资产已建成但页面证据不完整，`page_parity` 不宣称验收通过；不代表因果收益、OOS、模拟成交或正式分钟启用。

原始证据位于本机 `/Volumes/扩展盘/guiyi-quant-workstation/outputs/c-candidate-pilot-20260930/` 及四个不可覆盖的 `outputs/c-candidate-prepared-20260930*` 目录，未提交。Chrome 失败现场、原始 CLI、截图、崩溃诊断与已完成场景 SHA 均保留，不把单场恢复写成一次无中断采集。

## 数据和候选资产

C 有 21 个 rank1 唯一物理 owner、无重入，84 个四周期依赖单元。产品级上市日期 UNKNOWN，2023-01-01 只是存储窗口；首个 C2303 物理 listed_date 为 2022-03-15。C 的 Session 有夜盘 21:00–23:00；依据真实 Session `(start,end]` 聚合，不缩窗。冻结维护 plan hash `35be863f5b07ca184f2073c28ca4a15af8f6f9863751fdc750c16dc7f072a68e`。

一次真实维护完成 84/84：81 个 `READBACK_VERIFIED`、3 个 `NO_GAP`。195 次 RQData 行情价格请求补足 1m，790 个派生目标，合计 985 个精确月分区目标；无失败 attempt、未知提交或数据重试。最终 84/84 依赖 DATA_READY。七频旧数据保护独立读回：1174 个旧文件 SHA 保持，96 个扩展分区的 95887 根旧 Bar 逐值保持，588 个 D1/W1 分区未变，889 个新分区；见 `campaign-complete.json`、`seven-frequency-difference.json`。

原生及独立 Parquet-only Decimal 200 全物理前缀重聚合通过：5m 315531、15m 105177、30m 54896、60m 32063，合计 **507667 根 Bar**；逐根 OHLCV、持仓量、成交额、物理身份、端点与 Session 一致。独立报告为 `review-offline-aggregation-*.json`。

候选 schema `newow_intraday_pilot_20260927` 原 C stream 为 0；一次首建 4 输入、8 基础、4 融合，共 12 流。fresh reader 和独立 manifest/source token/revision/seq/checkpoint、四组融合依赖核对通过。最终 12 流 READY、`enabled=false`、`activation_generation=0`、`complete_window_proven=false`；8 基础 coverage FULL/21 owner 不改变最后一项。见 `source-assets-final-v5.json`、`independent-asset-final-v4.json`。

## API 与 Chrome 停止边界

本地 C singleton preview 的 prepare、live preflight 通过；capability 为 v27、`single_product_intraday_candidate`，Newow 页面仅四分钟周期加 D1/W1，没有 1m 页面。真实 API 12/12 READY，152 次组合 GET 及 5 个 UTC/null 检查通过，Z/+00:00 等价、旧 token 409 与未请求 section null 均按原生合同读回。API 成功不替代浏览器页面验收；见 `api-v5/summary.json`、`api-v5/independent-utc-null-v1.json`。

浏览器采集按失败即停，保留三段现场：

1. 首次 CLI 在浏览器尚未 open 时退出，零场景执行；`chrome-start-failure-forensics.json` 保留。
2. 打开浏览器后 5m trend 完成，5m oscillation 的主图与较早窗口均完成，但回切 60m 时旧 token 短暂 409 被采集器误判为终态。页面后续自然恢复；原始失败与 DOM 均保留。只在切换期容忍特定 409、仍要求新 chart/reference READY 的任务内 helper 四例测试通过。
3. 明确续接后 5m oscillation 完成；5m dual 三图已生成，但 Playwright Node 会话 PID 58586 在 02:56:48 因 V8 `FatalProcessOutOfMemory`、JSON 序列化时 SIGABRT。CLI 无结构化输出，三图不算通过。macOS 崩溃报告 SHA、CLI、三图 SHA 与两个成功场景 SHA 见 `browser-oom-forensics.json`。
4. 对第三场使用独立浏览器会话及 6144 MB V8 上限的诊断性续接。CLI 完整退出 0、主图与曲线图保存，但“加载更早”请求收到 `NEWOW_SNAPSHOT_GENERATION_CONFLICT` 409；随后的 200 是**当前窗口** chart，不是较早窗口成功响应。collector 正确阻断，较早图缺失。此续接不能算 5m dual 完成，也不证明 19 场或 12 页面。原始 `collection-observations.json` 与 CLI 全量响应保留在 `outputs/c-candidate-prepared-20260930-isolated-browser/`。该次提高堆上限仅诊断资源边界，未解决页面较早窗口问题，不作为正式采集通过证据。

最终只有 5m trend、5m oscillation 两场具有完整采集输出；尚无全 19 场 index/audit、49 原图逐张审查或 12 页独立数值 Review。候选完成分子保持 **0/12**。两类 409 不混同：切换期旧 token 可被新 token 完整恢复；较早窗口 409 后没有对应较早页的成功读回，必须 fail-closed。第三场的真实页面请求已经发生，不能仅凭更大内存或再次点击推断相同 snapshot/cursor 会成功；继续需要先定位并修正该页的 token/分页身份，再重新冻结并验收，不能盲目换目录重采。

## 验证、风险与下一步

工具定向回归：`python -m pytest tests/newow_candidate_tools -q -p no:cacheprovider --basetemp=/private/tmp/c-candidate-tool-tests-20260930`，**149 passed**。任务内 409 判定测试：`node --check outputs/c-candidate-pilot-20260930/recovery-browser/minute.js` 与 `node outputs/c-candidate-pilot-20260930/recovery-target-terminal.test.mjs`，四种 transient/hard-failure 情形通过。针对 helper 的源码 diff Review：仅在 bootstrap/away/return 切换阶段容忍特定旧 token 409，且必须重新收到新 chart/reference READY；较早窗口 409 继续阻断。本轮**不提交该 helper**，因为它不修复较早窗口失败，也不改变产品行为。独立数据、资产、API readback 通过；浏览器页面独立 Review 未完成。本轮未变更产品公式、收益、Runtime 或正式消费者。

C 专属 API PID 58041、Web PID 58066 停止前核实了 cwd/端口/命令，SIGTERM 后 8012/5178 均释放；只读 PostgreSQL advisory lock 读回 granted=0、waiting=0。见 `final-maintenance-lock-readback.json`。没有清理其他任务工作区或候选生产事实。

验收结论：**阻塞 C 页面闭环，允许集成 develop 的仅为本暂缓记录**。Canonical 与候选资产是已提交的生产事实，不通过 Git 回滚，也不重放已完成维护/构建 attempt。正式分钟、Runtime、Scope、通知、账户、main/tag/release 均未改变。

唯一最小下一步：在 C 专属隔离现场定位并修复 5m dual “加载更早”旧 token 409 与高数据量采集资源边界，保留当前失败证据，再从冻结身份重新做完整页面验收；不得以旧两场或截图补成 12/12，也不自动推进 LH。
