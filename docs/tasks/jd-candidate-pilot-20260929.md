# P7-14 JD 鸡蛋历史候选及新工具首次实测

状态：**COMPLETED，12/12 页面候选闭环**。仅 JD；固定 21 品种分母不变，AP 未由本任务启动。源码和真实预览冻结于 `a8d0d1910af710617c84f982f26954eaabc86eb6`；历史窗口 `2023-01-01..2026-09-24`，`as_of=2026-09-24T07:00:00.000001+00:00`。四个正式分钟周期为 5m/15m/30m/60m；1m 只作合格 Canonical 聚合来源。结果属于 `page_parity=true, executable=false, auto_order=false` 的页面参考，不是因果收益、OOS、账户成交或正式 Runtime。

本次恪守原验收：同物理合约完整生命周期 1m 来源、Session `(start,end]` 聚合、旧七频事实保护、12 条 disabled 候选资产、12 组合真实 API/Chrome、日周六组、取消/超时/快照恢复、完整交易和曲线数值及逐图独立 Review。实操只启动一次真实维护 campaign、一次 12 流资产首建 campaign、一次 19 场 Chrome 采集；每个 native 维护单元与资产流至多执行一次，失败不续跑。原始计划、attempt、readback、响应和截图在本机 `outputs/jd-candidate-pilot-20260929/`，不提交。

## JD 数据与资产

自身 rank1 映射有 31 个唯一 owner，无重入；产品级上市日期仍为 UNKNOWN，物理合约按自身 `listed_date` 计算全前缀，首个 JD2305 从 2022-05-27 开始。冻结实际维护 `campaign_v3.py` SHA `3e5c72f23bb5ce2c71ece3ecc62470e35f7113af92bd61815796b4f0a24908a7`、精确计划 SHA `c2ba3cee8ae34cd83e560b663e2af44ed5715fa27ee835b4d02821734bd6688b`。124 个 native 单元中 118 READBACK_VERIFIED、6 NO_GAP；实际 303 个 1m 行情 fetch 请求、1234 个派生月发布；最终 124/124 数据依赖 DATA_READY。请求数是 native source 目标，不含 quota 状态查询，不把预算估算当实际下载字节。生产维护没有失败单元、未知提交或重试。

独立七频读回确认 224 个旧 dataset、1496 个旧文件继续保留；137 个扩展分区里的 95563 根旧 Bar 逐值保持，821 个 D1/W1 分区保持，新增目标边界仅为本次精确计划。四周期 31 owner 的完整物理前缀合计 481654 根 Bar（5m 296910、15m 98970、30m 52784、60m 32990），经原生 reader 和独立 Decimal 实现逐值核对 OHLCV、成交额、持仓量、端点与 Session。见 `seven-frequency-difference.json`、`review-offline-aggregation-*.json`、`independent-data-assets-review.json`。

12 条流均为首次原生构建：8 基础、4 融合；fresh reader 复核 manifest/source token/input count/checkpoint/revision/seq 和四组融合依赖均通过。所有流 `READY`、`enabled=false / generation=0`；`complete_window_proven=false` 原值保留。8 个基础 coverage 为 FULL/31 owner，这不改变资产字段的原始布尔值。数据与资产独立终审绑定 945 份实际证据 SHA，没有把 build 过程缓存当成最终读回。

## API、真实页面与独立验收

任务专属 preview API/Web 绑定冻结源码、JD singleton、固定时点及隔离 schema；仅此 preview 的 D1/W1 使用既有 legacy reader。12/12 API READY，独立 coverage/历史窗口核对通过；UTC `Z` 与 `+00:00` 同时点一致、相差一微秒旧 token 返回 409、未请求 section 为原生 null，均有真实 GET 记录。Chrome 一次采集 19/19 场：12 个分钟组合均在同一页面连续取得功能、完整收益数组/记录及较早主图，另有 6 个原生日周组合与 1 个真实取消恢复场景。49 张原图逐张实际 Review；索引及离线审计核对原始 XHR、即时 GET、DOM、全部交易身份、Decimal 累计收益与全部 SVG 点。独立第二实现对 18 个交易曲线场景、14798 笔 CLOSED、14832 个 SVG 顶点通过；W1 震荡零 CLOSED 为真实空曲线、零笔和 null/破折号统计，不能写成 0% 收益。取消场景观察到真实 pending，250ms 限时读在 0.2516s 客户端超时；错频 token 的 chart/reference 409 后用新 token 恢复。

独立逐图结果为 `PASS_WITH_RETAINED_VISUAL_LIMITATIONS`，无新增阻塞，但不得宣称全部副图同步覆盖：12 张分钟较早窗口的趋势转折副图短于累积主图，60m 的 2026 年主体范围大部留白；密集 BUILD/CLEAR/切换标签局部遮 K 线、边缘和换月文字局部裁切。W1 趋势转折仍显示当前合约 43/120 Bar、30 历史段 WARMING；任务预览顶部报价 403 未被页面参考价格替代。见 `api-v5/summary.json`、`api-v5/independent-utc-null-v1.json`、`evidence-index.json`、`offline-audit.json`、`independent-browser-numeric-review-v2.json`、`independent-browser-visual-review.json`。

## 一次性实测的耗时与返工

实际进程 walltime：维护 1056.100s（17m36.1s），12 流资产首建 752.774s（12m32.8s），原 API 验收 231.987s（3m52.0s），唯一 Chrome 采集 1369.784s（22m49.8s）。各阶段之间还有独立审计、准备和人工 Review，部分只读检查重叠，故这些数不能加成端到端总耗时。资产 native plan/build 字段合计 172.246s/564.205s，合计 736.451s，与整阶段 walltime 不混用。

旧 CJ/SM 需要分钟功能、完整曲线和较早窗口各 12 次场景；新工具在本次真实 JD 把 36 次分钟场景变为 12 次，少 24 次（66.7% 的场景结构减少），同时保留日周 6 场与取消 1 场，总场景从 43 变 19；本次保存 49 张原图并通过逐图验收。旧证据仅有 CJ/SM 功能 12 场完整耗时 350.366s/410.032s，旧完整曲线、较早窗口和日周场景缺完整 walltime，无法计算采集、全流程或工具导致的提速百分比。JD 31 owner/481654 全前缀 Bar 与 CJ 12 owner/183668 Bar 不同；JD 12 流分别计划用于首失败即停，CJ 是 8 个资产 stage，原生计划/构建字段分别 79.104s/255.201s，亦不可直接作提速比较。逐项来源与缺口见 `comparison-baseline.json`、`comparison-pilot.json`。

返工如实计 9 项：执行前审查/准备修正 5、测试临时目录误触静态路径断言 1、独立数值审查脚本把 `history_before` 写成 `reference_before` 而离线修正 1、专属进程清理守卫在发信号前拦住错误路径和 `lsof` fd 行判断各 1。首次失败记录全部保留；修正测试在同一冻结代码上为 **231 passed、3 skipped**，首次为 **230 passed、3 skipped、1 failed**。独立数值初版 15/18、修正后 18/18；两次清理守卫均未发信号。真实维护重试 **0**、资产重建/重试 **0**、Chrome 重采 **0**；这些 9 项不能称为 9 次生产返工。旧 CJ/SM 仅保存已知故障类别而非完整返工登记和逐项耗时，也不能证明本次比旧流程返工更少。见 `preexecution-rework.json`、`verification-rework.json`、`independent-browser-numeric-review.json`、`final-rework-accounting.json`。

冻结代码相关回归：`pytest tests/newow_candidate_tools` 加原生聚合/Session/Reference 定向模块，共 **231 passed、3 skipped**（使用 `/private/tmp` 测试临时目录）。首次仅因把临时目录放入 `outputs/` 命中禁止引用旧输出的静态断言而失败，未改测试或产品代码。独立数据/资产 Review PASS，API/Chrome/数值/视觉 Review 均已通过。任务专属 Chrome 关闭；PID30490/30543 经命令、cwd、端口守卫后 SIGTERM，均已终止且 8012/5178 端口释放；维护锁 granted/waiting 皆 0。没有改正式分钟启用、Runtime、Scope、通知、账户、main/tag/release，也未启动 AP。

验收结论：**允许集成 develop**，仅集成本记录、P7-14 状态和工具首次实测说明。唯一下一步：总控核实本次集成 SHA 后，按既有串行队列启动 AP。
