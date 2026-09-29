# P7-15 AP 苹果历史候选闭环

状态：**COMPLETED，12/12 历史候选页面闭环**。仅 AP，固定 21 品种分母不变，未启动 C。源码与实际预览冻结于 `33c874972de5a1bd4545b0048be2ad19f4696828`。历史窗口 `2023-01-01..2026-09-24`，`as_of=2026-09-24T07:00:00.000001+00:00`。范围为 5m/15m/30m/60m × trend/oscillation/dual；1m 只作聚合来源。结果为 `page_parity=true, executable=false, auto_order=false`，不证明因果研究、OOS、账户成交或正式分钟启用。

原始证据保留在本机 `/Volumes/扩展盘/guiyi-quant-workstation/.worktrees/ap-candidate-pilot/outputs/ap-candidate-pilot-20260930/`，不提交。managed worktree 工具未能识别仓库后使用独立 Git worktree；该树保留用于证据追溯。仅提交本记录、STATUS 入口和 P7-15 队列行，无产品源码或工具修改。

## 数据与候选资产

AP 自身 rank1 有 12 个唯一物理 owner，无重入。产品级上市日期为 UNKNOWN；2023-01-01 是存储窗口而非上市事实。物理合约按自身 listed_date 验证完整生命周期前缀，首个 AP2305 为 2022-05-19。冻结 `campaign-plan-v3.json` SHA256 为 `fefe6f85bf5ba6aa7306ae9908618838025f3f32155e73d3bce364d965bf6641`。

一次真实维护覆盖 48 个 native 单元：31 READBACK_VERIFIED、17 NO_GAP，最终 48/48 依赖 READY；实际行情价格请求为 0，247 个派生月目标（219 新分区、28 扩展分区），109007 根目标 Bar。已有合格 Canonical 1m 足够，quota 查询不算价格下载。无维护失败、未知提交、重试或缩窗。

七频保护核对 91 个 dataset，1095 个旧文件 SHA 全部保持；扩展分区内 9674 根旧 Bar 逐值保持，370 个 D1/W1 分区保持。最终分区数 1314。四周期完整物理前缀逐值独立 Decimal 重聚合：5m 115020、15m 38340、30m 20448、60m 12780，合计 186588 根；OHLCV、成交额、持仓量、端点及 Session `(start,end]` 通过。独立元数据审查另核对 30672 个 Session 窗口。证据为 `seven-frequency-difference.json`、`review-offline-aggregation-*.json`、`independent-data-assets-review.json`。

候选 schema `newow_intraday_pilot_20260927` 中 AP 原有 stream/revision 为 0，这不代表 AP 在其他 schema 无资产。一次首建完成 4 输入、8 基础、4 融合。最终 fresh reader 及独立审查核对 manifest、source token、revision、seq、checkpoint、四组融合依赖通过。12 流全部 READY、enabled=false、activation_generation=0、complete_window_proven=false；8 基础 coverage FULL/12 owner 不改变最后一个布尔值。输入序列包含 11 个换月分隔，与物理 Bar 数分别计数。见 `source-assets-final-v5.json` 及独立数据资产报告。

## API 与真实 Chrome

新工具 prepare/preflight/capture/index/audit 在冻结代码上使用；live GET preflight 为 AP singleton / capability v27。API 12/12 READY，149 次组合 GET 加 7 次 UTC/null 检查；Z 与 +00:00 一致、相差一微秒旧 token 返回 409、未请求 section 原生 null，chart/reference 身份独立核对。API 归档压缩了数组中段，完整响应在检查时验证；不能仅用压缩归档重新构造所有中间值。见 `api-v5/summary.json`、`api-v5/independent-utc-null-v1.json`、`independent-api-review.json`。

唯一 Chrome 采集完成 19/19：12 分钟组合、6 日周组合、1 取消恢复场景；49 张原图全部逐张独立查看并比对 SHA。工具索引 PASS、离线工具结果 NUMERICAL_PASS_VISUAL_PENDING；随后独立数值及视觉审查补齐人工 Gate，不改写工具原始状态。独立 v3 对 18 个交易场景完整校验 DOM/分页 ID、history_limit、分钟 GET/XHR 绑定、14772 笔 CLOSED（基础 8407、融合 6365）参考价收益、累计算术和 14808 个 SVG 点；最大坐标误差约 1.35e-13。融合 v1 是全仓 long/flat 零成本模型，未独立重放所有历史事件选择，不能把收益算术验证写成完整状态机独立重演。

AP 原生日周 CLOSED 为 D1 68/27/71、W1 12/1/13（趋势/震荡/融合），六组均非零。日周绑定原始 XHR，没有额外 GET 对照。取消场景有原请求 net::ERR_ABORTED，另有 0.252s 客户端 AbortError；错频 chart/reference 两次 409 后新 token 恢复 200，60m 恢复及返回 5m 有曲线/记录。客户端取消不证明服务端计算取消。

独立报告：`independent-browser-numeric-review-v3.json`、`independent-browser-numeric-review.md`、`ap-independent-visual-review.md`。数值无 Confirmed Issue；视觉保留 P3：earlier 密集 Marker 局部重叠，但主图、Marker、累计曲线均可见，无核心区域整块异常空白。本轮无阻塞候选闭环的问题，以下限制仍保留：

- 较早趋势转折副图随最后接受页替换，主图累计多页。60m trend 主图累计 2025-07-07..2026-09-24，末副图请求仅 2025-07-07..2025-12-01；压缩 points 无法再独立重算渲染端点，不声称全累积窗口副图覆盖。
- 照妖镜、涨跌动能、主力控盘仅有 DOM/API 切换证据；49 图实绘覆盖 MACD/趋势转折，不能声称五副图均逐图通过。部分 main/curve 同构图，甚至同 SHA，不算新增独立视口。
- W1 当前 35/120 Bar、11 历史段 WARMING；分钟/W1 报价不可用，D1 图中报价 7076 可用。截图不能独立证明 HTTP 状态或实时行情正常。
- 分钟逐 Bar 持有过程暂不可用，累计已完成交易曲线不替代持有过程曲线。

## 实测耗时、修正与验证

维护/资产完整进程 walltime 未记录，不补估：维护 attempt 到 complete 文件时间间隔为 237.617276s，仅是证据区间，排除初始化/退出；资产 native plan 合计 75.634s、build 合计 246.859s。API 实际进程 148.679s，唯一 Chrome 826.314s。阶段间审计与准备不在上述数中，不能相加声称端到端总耗时。见 `measured-phase-summary.json`。

新采集结构分钟 36→12、总场景 43→19；旧 CJ/SM 缺完整 walltime，AP 12 owner/186588 Bar 与 JD 31 owner/481654 Bar 不同，不声称工具造成整体提速百分比。准备与独立审查脚本有离线修正，未记录完整准备工时；数值审查 v3 补入参考价/封存/history_limit 检查，取消断言改为绑定唯一失败请求 ID。旧文件/失败记录保留，不把这些修正称作生产重试。模型容量中断发生在构建后，核实原独立资产进程已正常完成，未重跑；维护重试、资产重建和 Chrome 重采均为 0。

冻结代码定向回归实际命令（Python 为主仓库 `services/quant-api/.venv/bin/python`，cwd 为任务树）：

```sh
PYTHONPATH=services/quant-api:packages/quant-core:. /Volumes/扩展盘/guiyi-quant-workstation/services/quant-api/.venv/bin/python -m pytest tests/newow_candidate_tools services/quant-api/tests/data_foundation/test_aggregation.py services/quant-api/tests/data_foundation/test_historical_session_window.py services/quant-api/tests/newow/test_reference_interruptions.py services/quant-api/tests/reference_trading/test_source_identity.py services/quant-api/tests/reference_trading/test_newow_persisted_query.py services/quant-api/tests/reference_trading/test_newow_fusion_historical.py services/quant-api/tests/reference_trading/test_revision_rebuild.py -q -p no:cacheprovider --basetemp=/private/tmp/ap-pilot-regression-20260930
```

结果 **231 passed、3 skipped，2.10s**，exit 0（阶段 walltime 2.555s）。独立数据/资产/API/浏览器数值及原图审查完成。仅 AP Chrome 会话关闭；API PID46133、Web PID46163 按命令/cwd/端口守卫终止，8012/5178 释放；维护锁 granted/waiting=0。见 `preview-cleanup.json`、`final-maintenance-lock-readback.json`。正式 Runtime、Scope、通知、账户、main/tag/release 未变。

验收结论：**允许集成 develop**。集成只包含三份文档，原始生产事实不通过 Git 回滚；不要重新消费已完成 attempt。唯一下一步：总控核对本次 develop 精确提交后继续既有队列；本任务不启动 C。
