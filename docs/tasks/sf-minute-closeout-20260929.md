# P7-11 SF 四周期历史候选闭环

状态：**COMPLETED，12/12 页面闭环**。仅 SF（硅铁），4 输入、8 基础、4 融合候选完成数据、资产、API、真实 Chrome 与独立数值及视觉核验。固定 21 品种分母不变，未启动 SM。候选全部 disabled、activation generation=0、`complete_window_proven=false`；本结果是历史页面参考验收，不是因果收益、OOS、账户收益或正式运行晋升。

源码、数据读回与预览冻结于 `9531a6352d6507269a1adf9d58edd13e10dbe798`，未修改产品源码、公式或正式配置。原始行情、helper、响应和图片保留在本机 `outputs/sf-minute-closeout-20260929/`，不提交。原 `matrix.json` 保留宿主阻断历史，最终结果另存 `matrix-final.json`。

## 范围与授权恢复

窗口 `max(2023-01-01, SF 产品权威起点 2014-08-08)..2026-09-24`，as_of `2026-09-24T07:00:00.000001+00:00`。只验收 `5m/15m/30m/60m × trend/oscillation/dual`，1m 仅聚合来源。SF 自身 Map/MDS 确定 28 个唯一 rank1 owner，无重入；计算前缀使用物理合约自身 listed_date，首单 SF2303 从 2022-03-15 开始，不缩成页面窗口。

初次宿主在 apply 进程创建前拒绝，旧 `host-approval-blocked.json` 与停止证据完整保留；用户本聊天明确回复“授权”后，经正常宿主复核执行原冻结计划，没有绕过控制。campaign SHA 始终为 `a38ec0e8be2692b0f1b2577c3c0aa75f61401f08b781171d21b55786f79d3f2b`。

恢复前严格前像检查发现 SF2611 当月新增 9/29 数据，旧文件与旧行均保持。独立只读核验确认 112 份 fresh plan 的范围、窗口、生命周期、零源请求和 287 个目标不变；追加行为的 actor 未归因，不猜测来源。差异及核验保留在 `independent-authorized-drift-review.json` 与 `independent-authorized-drift-review.md`。未复用失败 attempt、修改 plan hash、缩窗或盲重试。

## 数据与候选资产

112 个维护单元实际完成，**0 provider requests，287 个 5m 派生月发布**；其中 27 个旧月份指针扩展、260 个新增月份。计划 247950 根预期派生 Bar 是目标规模，不能表述为新增 Bar 数量。`campaign-complete.json` 与逐单元计划、attempt、结果和读回保留。

独立前后核对：2036 个旧七频文件、1576576 根旧行均保留；2009 个旧指针保持，只有上述 27 个 5m 指针扩展，636 个 D1/W1 指针保持。见 `inventory-difference.json`、`review-offline-maintenance-v2.json`。最终依赖 **112/112 DATA_READY**。

SF 自身 Session 为 09:00–10:15、10:30–11:30、13:30–15:00，前缀含 3306 个 Session 记录。夜盘、跨午夜、周末夜盘按自身事实 N/A；30m 的 15 分钟尾段和 60m 的 15/30 分钟尾段遵循 `(start,end]`。四频各 28 owners、332 月，独立从同物理 Canonical 1m 核验的 required Bars 为：5m 271845、15m 90615、30m 48328、60m 30205。独立 Decimal 重聚合、月份完整性、Calendar/Session 与边界检查全部 PASS，详见 `data-review.md`。

旧 9 个资产 stored source evidence 不再匹配当前月份 source 摘要，不能因输入数值身份未变就宣称 exact reuse。5m 原生新建 3 个流，其余三频原生重建 9 个流；旧 revision 仅 invalid 状态及原因变化，旧 batch/action/trade/mark 全量行数与 SHA 保持。见 `independent-asset-source-review.md`、`old-asset-rows-after-v3.json`。

12 个最终资产的 stored manifest、fresh full reader、checkpoint、snapshot、source 和融合依赖逐字段核验 PASS。四频输入分别为 271872/90642/48355/30232（各含 27 个换月边界），seq 为 1063/356/190/120，终点为 9/24 07:00 UTC。8 个基础 coverage 为 FULL、各含 28 个区间，但不将其改写成 `complete_window_proven=true`。见 `source-assets-final-v5.json`、`independent-asset-final-v4.json`、`independent-final-asset-review.md`。

## API、页面与独立验收

仅任务预览使用 frozen 源码、只读 DB、SF 白名单和固定 as_of。SF 原生能力为 **v26 / black_steel_intraday_candidate**；最初错误套用 AG v27 的断言失败证据保留，修正的是任务核验 helper，没有修改产品能力或正式配置。

- API 12/12 READY、12 个更早窗口、两次错误周期 snapshot 的真实 409 与正确请求恢复全部 PASS；UTC Z/+00 同时点一致，1 微秒变更产生原生冲突；原生 null 字段保持。见 `api-v5/`、`snapshot-recovery-readback-v5.json`。
- Chrome 12/12 主图、参考 records、曲线、5 个副图、切换返回与错误检查通过。同日分页 3 项实际 PASS、9 项原生无 next cursor 为 N/A。更早窗口 12 项通过；主图累积多个窗口，MACD 只显示最后接受的窗口，该原生显示边界保留。
- 12 个完整 CLOSED 曲线按每笔记录身份、Decimal 累计值及全部 SVG 点核验，通过全量 membership 而非首尾抽样。见 `complete-curve-binding-fresh-v8.json`。
- D1/W1 共 6 组合回归完成；D1 副图原生 trend reversal WARMING，W1 副图原生 MACD/trend reversal WARMING。W1 oscillation 实际零 CLOSED，页面显示空曲线及“—”，没有伪造 0% 收益线。自身 Calendar/Session 证明 completed week 为 9/24，9/25..27 非交易日。见 `legacy-complete-binding.json`、`independent-legacy-response-curve-audit.json`。
- 真实 pending cancel、250ms timeout AbortError 和 fresh 恢复均观测通过，未注入 mock 失败。见 `browser/sf-cancel-timeout-observations-v5.json`。
- 独立数值审计 `independent-acceptance-audit.json` PASS；61 张原始 PNG 全部逐张视觉检查并核对 SHA，`independent-visual-review-v1.json` 为 PASS_WITH_NATIVE_AND_VIEWPORT_BOUNDARIES，没有 Confirmed Visual Issue。截图不证明视口外记录或收益算法，全量数值证据分别覆盖。

候选预览原生禁止市场顶部报价所用 `/api/v1/market/research/product`，真实响应为 403 PREVIEW_ROUTE_FORBIDDEN；顶部报价 unavailable 是预览合同边界，不冒称行情缺口，也不将策略目标价/吸筹价当作顶部报价通过。没有开放额外路由或伪造报价。

## 实际验证与收尾

所有 Python 导入由 frozen PYTHONPATH/import guard 固定，秘密仅由现有 loader 使用，不进入输出。实际命令及结果：

- `python -m pytest --confcutdir=outputs/sf-minute-closeout-20260929 outputs/sf-minute-closeout-20260929/test_scope.py -q -p no:cacheprovider`：14 passed in 0.61s。
- `python -m pytest services/quant-api/tests/data_foundation/test_aggregation.py services/quant-api/tests/data_foundation/test_historical_session_window.py services/quant-api/tests/newow/test_reference_interruptions.py -q -p no:cacheprovider`：58 passed in 1.00s（冻结树）。
- 原生 source/fusion/persisted query 定向测试：22 passed in 0.65s，命令输出见 `native-assets-tests.txt`；原生 rebuild：6 passed、3 skipped in 0.81s，见 `native-rebuild-tests.txt`。PG fixture skip 不冒充生产验证，真实构建及全量读回已有独立证据。
- prefix negative selftests：6 passed；`python outputs/sf-minute-closeout-20260929/independent_acceptance_audit.py --saved`：独立保存证据重算 PASS，零 HTTP/DB/provider/writes。

历史 scratch partial preflight、SOURCE_BUSY、旧资产 source conflict、任务 helper 校验失败、sandbox 连接失败与宿主拒绝均保留，不用成功文件覆盖。最终共享维护锁为 0，见 `final-lock-readback.json`。

任务专用 Chrome 会话 `sf-minute-closeout` 已关闭；API PID73971/8012、Web PID74035/5178 已 TERM，两个 exec 会话均退出，两个端口无监听。managed worktree 已经原生归档，list_artifacts 回读为 archived_worktree，保留可恢复 Git 快照；未使用 shell 删除。原始本机证据保留。

NI/FU 旧失败 attempt 和证据未触碰，未声称其根因已修复。未启动 SM；未修改正式分钟 Scope、Runtime/worker/消费者、audience/通知、main/tag/release、Broker 或账户，`auto_order=false` 保持。

验收结论：**允许集成 develop**（仅本项三份收尾文档）。唯一最小下一步：按既有串行队列处理 SM，本任务未启动。
