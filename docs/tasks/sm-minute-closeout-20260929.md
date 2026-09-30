# P7-12 SM 四周期历史候选闭环

状态：**COMPLETED，12/12 页面闭环**。4 输入、8 基础、4 融合候选完成数据、资产、API、真实 Chrome、独立数值和视觉验收。仅 SM（锰硅），固定 21 品种分母与其他队列行不变，未启动 CJ。候选保持 disabled、activation generation=0、`complete_window_proven=false`。结果属于 `page_parity=true, executable=false` 的历史页面参考，不代表因果收益、OOS、账户收益或正式运行晋升。

源码、数据读回与任务预览冻结于 `01dc71b55d3882a5c7db4a89b943e44f054db369`。未修改产品源码、公式或正式配置。原始计划、helper、响应与 PNG 保留在本机 `outputs/sm-minute-closeout-20260929/`，不提交。用户交办目标覆盖本品种必要数据与 disabled 候选构建；无宿主拒绝或未知提交，未盲重试失败 attempt。

## 范围与自身事实

固定窗口 `2023-01-01..2026-09-24`，as_of `2026-09-24T07:00:00.000001+00:00`；仅 `5m/15m/30m/60m × trend/oscillation/dual`，1m 仅聚合来源。自身 Map/MDS 确定 19 个唯一 rank1 owner、18 个换月边界，无重入。Catalog 无产品级 listed_date，产品精确上市起点保持 UNKNOWN；既有 historical storage start 为 2023-01-01，不冒称产品上市日。计算前缀依各物理合约自身 listed_date，首单 SM2305 从 2022-05-19 开始，不缩成页面窗口。

自身 Session 为 09:00–10:15、10:30–11:30、13:30–15:00，前缀 3180 个 Session 记录、1590 个 Calendar 记录。夜盘、跨午夜、周末夜盘按自身事实 N/A；30m 的 15 分钟尾段、60m 的 15/30 分钟尾段保持 `(start,end]`。

## 数据与资产

campaign plan SHA `3bef47ba7a8e4011ce47283ef4f0d263153d0a573632ea361208b44dcab052be`。76 个维护单元核对完成（19 个 READBACK_VERIFIED 实际执行、57 个 NO_GAP），**0 行情 fetch requests，178 个 5m 派生月发布**：161 个新增月份、17 个既有月份指针扩展。153675 根预期 Bar 是计划目标规模，不是新增 Bar 数。最终 76/76 依赖 DATA_READY，由 `source-assets-final-v5.json` 四频各 19 项 DATA_READY 证明；任务仍通过既有 quota API 核对预算，零行情 fetch 不等于零外部 API 调用。

独立前后读回保留全部 1689 个旧七频文件 bytes/SHA，140 个 dataset 不变；1672 个无关旧 Catalog 分区保持，扩展分区的 10305 根旧 Bar 逐值保留，510 个 D1/W1 分区保持。当前 1850 个文件。见 `seven-frequency-difference.json`、`review-maintenance-results.md`。

四频各 19 owners、223 月；完整 required Bars：5m 184095、15m 61365、30m 32728、60m 20455。原生 full-prefix reader 与独立 Decimal 重聚合分别通过，后者不导入产品聚合函数，逐值比较端点、OHLCV、turnover、OI。见 `aggregation-*-full-prefix-readback-final.json`、`review-offline-aggregation-*.json`、`review-independent-aggregation.md`。

5m 原生新建 3 个流，其余三频原生重建 9 个流，exact reuse=0。旧基础资产仅 source evidence SHA/dependency digest/source token 三字段变化也不能复用；旧融合 reader 原生报 `REFERENCE_FUSION_SOURCE_SNAPSHOT_CONFLICT`。旧 revision 仅 invalid/P4_SOURCE_REVISION_REBUILD 元数据变化，9 个旧 generation 的 1362 batches、10960 actions、5623 trades、38853 marks 全量 SHA 保持。见 `asset-source-diagnostic.json`、`old-asset-rows-after.json`。

12 个最终候选 manifest、fresh full reader、checkpoint、source token/digest、revision/seq、snapshot 与融合依赖逐字段核验 PASS。四频每基础流输入为 184113/61383/32746/20473，各含 18 个换月边界。8 个基础 coverage 均 FULL、各含 19 个 VALID 区间，但 `complete_window_proven=false` 保留。见 `source-assets-final-v5.json`、`independent-asset-final-v4.json`、`review-final-assets.md`。

## API 与页面

仅任务预览使用 frozen 源码、只读 DB、SM singleton 白名单与固定 as_of；SM 自身能力为 v26 / black_steel_intraday_candidate。预览 D1/W1 使用原生 legacy query，不修改正式 resolver 或配置。

API 12/12 READY，12 个更早窗口、错误频率 snapshot 的两次原生 409 与 fresh 正确请求恢复通过。UTC Z/+00 同时点一致，1 微秒变化产生原生冲突，原生未请求 section/value/status/revision 的 null 保持。见 `api-v5/`、`snapshot-recovery-readback-v5.json`。

真实 Chrome 12/12 主图、reference records、曲线、五副图、切换返回和错误检查通过。同日分页 4 项实际 PASS、8 项原生无 next cursor 为 N/A；API 与浏览器各自按实际响应计数。12 个较早窗口完成同 snapshot、strictly earlier、可见旧 Bar/Marker 与五次稳定采样验证。12 个全 CLOSED 曲线在 fresh full raw GET/records GET、前后 DOM 与真实 SVG 每点间绑定，逐笔 ID 和 Decimal 累计核验 PASS，不用首尾抽样代替全量证明。见 `complete-curve-binding-fresh-v8.json`、`browser/earlier-window-observations-v8.json`。

D1/W1 六组合真实回归与全 CLOSED 曲线绑定通过；D1 趋势转折、W1 MACD/趋势转折保留原生 WARMING。六组合实际 CLOSED 数分别为日线 trend/oscillation/dual 56/13/60、周线 7/2/10，均非空，不照搬其他品种零 CLOSED 结论。见 `browser/legacy-regression-final6-v3-observations.json`、`legacy-complete-binding.json`。真实 pending cancel、250ms AbortError 和 fresh 恢复通过，未注入 mock 失败。

`independent_acceptance_audit.py --saved` 与主代理再次独立保存重算均 exit 0；零 HTTP/DB/provider/writes，12 全曲线、12 较早窗口、6 日周和取消恢复 PASS。61 张原始 PNG 全部逐张查看，封口时重新核对集合、SHA 和 1600×1100 尺寸；独立视觉结论 PASS_WITH_DECLARED_LIMITATIONS，无新增 Confirmed Issue。截图只证明可见视口，视口外记录/全量数字、AbortError 与快照均由独立 raw/DOM 证据证明。见 `independent-acceptance-audit.json`、`independent-acceptance-root-readback.json`、`review-visual-final-v1.md/json`。

市场顶部报价请求 `/api/v1/market/research/product?symbol=sm&series_kind=actual_dominant` 原生返回 403 PREVIEW_ROUTE_FORBIDDEN；unavailable 是候选预览入口边界，不用目标价/吸筹价代替行情报价。更早主图可累积窗口，MACD 只显示最后接受窗口的原生边界保持。自身 Calendar/Session 原生 completed week 为 9/24，9/25..27 非交易日。

## 实际验证与收尾

Python 使用 frozen PYTHONPATH/import guard，凭据仅由现有 loader 使用，不进入输出。

- `python -m pytest --confcutdir=outputs/sm-minute-closeout-20260929 outputs/sm-minute-closeout-20260929/test_scope.py -q -p no:cacheprovider`：14 passed in 0.62s。
- 冻结树 `python -m pytest services/quant-api/tests/data_foundation/test_aggregation.py services/quant-api/tests/data_foundation/test_historical_session_window.py services/quant-api/tests/newow/test_reference_interruptions.py -q -p no:cacheprovider`：58 passed in 1.38s。
- 冻结树 `python -m pytest services/quant-api/tests/reference_trading/test_source_identity.py services/quant-api/tests/reference_trading/test_newow_persisted_query.py services/quant-api/tests/reference_trading/test_newow_fusion_historical.py services/quant-api/tests/reference_trading/test_revision_rebuild.py -q -p no:cacheprovider`：24 passed、3 skipped in 0.94s；PG fixture skip 不冒充真实生产验证，构建及 full reader 已有独立证据。命令输出见 `native-assets-rebuild-tests.txt`。

- `python outputs/sm-minute-closeout-20260929/independent_acceptance_audit.py --saved`：PASS；主代理另以 `--output independent-acceptance-root-readback.json` 完整保存重算，exit 0。
- 文档引用与固定 21 行检查 PASS；`git diff --check` exit 0，`python3 scripts/engineering/secret_scan.py --json`：0 findings / passed。

sandbox DB/网络限制、只读诊断及 helper 错误原证据保留，不用成功读回覆盖。日周首次 runner 在 D1 dual 已完成真实采集后，因任务辅助 `legacy-expected-identities.json` 缺失停止；从冻结原生公式纯函数生成身份，D1 dual 仅用原 CLI 做离线校验，未重采 D1。W1 仅继续尚未启动的三项，原失败 log/截图不覆盖，最终六行矩阵独立另存。最终原生维护锁 granted/waiting 均 0，见 `final-maintenance-lock-readback.json`。任务 Chrome `sm-minute-closeout` 已关闭；API PID89210/8012、Web PID89367/5178 经命令/cwd 核对后 TERM，两个 exec 会话均以 143 退出，端口无监听，见 `resource-cleanup-readback.json`。三份收尾文档经 Review 后集成 develop；managed worktree 在集成后使用原生 archive 工具退休，原始本机证据保留，不用 shell 删除。NI/FU 原 ArrowInvalid/UNKNOWN attempt 与证据未触碰，不声称其根因修复。正式分钟/Runtime/Scope/audience/通知、main/tag/release、Broker/账户保持任务外。

验收结论：**允许集成 develop**（仅本项三份收尾文档）。唯一最小下一步：按既有串行队列处理 CJ，本任务未启动。
