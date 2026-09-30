# P7-13 CJ 四周期历史候选闭环

状态：**COMPLETED，12/12 页面闭环**。数据、候选、真实 API/Chrome、独立数值及视觉验收全部完成。仅 CJ（红枣），固定 21 品种分母与其他队列行不变，未启动 JD。4 输入、8 基础、4 融合候选保持 disabled、activation generation=0、`complete_window_proven=false`。结果属于 `page_parity=true, executable=false, auto_order=false` 的历史页面参考，不代表因果收益、OOS、账户收益或正式运行晋升。

源码、数据读回与任务预览冻结于 `baf4155ca2ae87a06026d08d472b69ec6ad5d7bf`。未修改产品源码、公式或正式配置。原始计划、helper、响应与 PNG 保留在本机 `outputs/cj-minute-closeout-20260929/`，不提交。交办目标覆盖本品种必要数据与 disabled 候选构建；没有宿主拒绝、失败维护单元或未知提交，未重试已执行 attempt。

## 自身事实与精确范围

窗口 `2023-01-01..2026-09-24`，as_of `2026-09-24T07:00:00.000001+00:00`；仅 `5m/15m/30m/60m × trend/oscillation/dual`，1m 仅聚合来源。自身 Map/MDS 确定 12 个唯一 rank1 owner、11 个换月边界，无重入。Catalog 无产品级 listed_date，产品精确上市起点保持 UNKNOWN；historical storage start 2023-01-01 不冒称上市日。完整计算前缀按各物理合约自身 listed_date，首单 CJ2305 从 2022-05-19 开始，不缩成页面窗口。

自身 Session 为 09:00–10:15、10:30–11:30、13:30–15:00；前缀 3180 个 Session 记录、1590 个 Calendar 记录。夜盘、跨午夜与周末夜盘按自身事实 N/A。30m 的 15 分钟尾段、60m 的 15/30 分钟尾段保持 `(start,end]`。自身 Calendar/Session 原生 completed week 为 9/24，9/25..27 非交易日，见 `weekly-authority-readback.json`。

## 数据与候选资产

campaign plan SHA `53326b0745fe7c820fba09a3cc4f5ba4869999353c8ef2322fa6ae440e8a0d53`。48 个维护单元完成：45 READBACK_VERIFIED、3 NO_GAP；实际 **86 行情 fetch requests、352 派生月发布**，合计 438 精确 source/derived 目标。最终 48/48 依赖 DATA_READY。计划 expected source/derived Bars 365400/125302 是目标规模，不是新增 Bar 数；预算采用项目估计，供应商 completion guarantee=false 保留。

独立七频差异读回：91 datasets 保持，899 个旧文件 bytes/SHA 全部保留，最终 1286 文件；新增 387、扩展 51 个分区，精确等于 438 目标。848 个旧分区完全不变，扩展分区 44779 根旧 Bar 逐值保持，366 个 D1/W1 分区的 pointer、文件与质量事实保持。见 `seven-frequency-difference.json`、`review-maintenance-results.md`。

四频各 12 owners、139 合约月；完整物理前缀 Bars：5m 113220、15m 37740、30m 20128、60m 12580，合计 183668。原生 full-prefix reader 与独立 Decimal 重聚合分别通过；独立实现不导入产品聚合函数，逐值比较端点、OHLCV、turnover、OI 和 trading_day。见 `aggregation-*-full-prefix-readback-final.json`、`review-offline-aggregation-*.json`、`review-independent-aggregation.md`。

CJ 原有候选流为零，12 个均首次原生 build，无 reuse/rebuild。schema `newow_intraday_pilot_20260927`。最终 manifest、fresh full reader、checkpoint、source token/digest、revision/seq、snapshot 和四个 fusion 的两个基础依赖逐字段核验 PASS。四频每流输入 113231/37751/20139/12591，各含 11 个换月边界。8 个基础 coverage 均 FULL、各 12 个 VALID 区间；12 个流末端均为 `2026-09-24T07:00:00+00:00`，`complete_window_proven=false`、observation_boundary=null 保留。first_computed_through 是首个 batch 的 checkpoint，不是历史起点。见 `source-assets-final-v5.json`、`independent-asset-final-v4.json`、`coverage-expected.json`、`review-final-assets.md`。

## API 与真实页面

本项预览使用 frozen 源码、只读 DB、CJ singleton 和固定 as_of；自身能力为 v27 / single_product_intraday_candidate。仅任务预览 D1/W1 使用原生 legacy query，不修改正式 resolver 或配置。

API 12/12 READY，12 个更早窗口通过。错误频率 snapshot 的 chart/reference 两次原生 409 后 fresh 正确请求恢复；UTC Z/+00 同时点一致、1 微秒变化原生冲突、未请求 section/value/status/revision 原生 null 保持。见 `api-v5/`、`snapshot-recovery-readback-v5.json`。

真实 Chrome 12/12 主图、reference records、曲线、五副图、切换返回和错误检查通过。同日分页 4 项实际 PASS、8 项原生无 next cursor 为 N/A。12 个较早窗口验证同 snapshot、strictly earlier、可见旧 Bar/Marker 与五次稳定采样。12 个完整 CLOSED 曲线绑定 fresh full raw GET/records GET、前后 DOM 与每个真实 SVG 点，逐笔 ID、完整数组 SHA 和 Decimal 累计核验通过；独立审查另以纯 Python 重建全部 15333 个 SVG 点一致。见 `complete-curve-binding-fresh-v8.json`、`browser/earlier-window-observations-v8.json`。

市场顶部报价请求 `/api/v1/market/research/product?symbol=cj&series_kind=actual_dominant` 原生返回 403 PREVIEW_ROUTE_FORBIDDEN；unavailable 是候选预览边界，不用目标/吸筹价冒充行情报价。更早主图可累积窗口，MACD 仅最后接受窗口的原生边界保持。截图仅证明实际可见视口，完整数字、视口外记录和 snapshot 由各自 raw/DOM 证据证明。

## 实际验证

Python 使用 frozen PYTHONPATH/import guard，凭据仅由现有 loader 使用，不进入输出。

- `python -m pytest --confcutdir=outputs/cj-minute-closeout-20260929 outputs/cj-minute-closeout-20260929/test_scope.py -q -p no:cacheprovider`：14 passed in 0.61s。
- 冻结树 `python -m pytest services/quant-api/tests/data_foundation/test_aggregation.py services/quant-api/tests/data_foundation/test_historical_session_window.py services/quant-api/tests/newow/test_reference_interruptions.py -q -p no:cacheprovider`：58 passed in 1.22s。
- 冻结树 `python -m pytest services/quant-api/tests/reference_trading/test_source_identity.py services/quant-api/tests/reference_trading/test_newow_persisted_query.py services/quant-api/tests/reference_trading/test_newow_fusion_historical.py services/quant-api/tests/reference_trading/test_revision_rebuild.py -q -p no:cacheprovider`：24 passed、3 skipped in 0.87s；PG fixture skip 不冒充生产验证，实际 build/full reader 另有证据。

sandbox DB/网络限制与 helper 错误保留：独立 5m 聚合首次 shell 指向不存在的 root .venv，exit 127，helper 未启动；改用实际 quant-api Python 后首次审计成功，未重跑维护或覆盖错误日志。NI/FU 原失败/UNKNOWN attempt 与资源未触碰，不声称其根因修复。

日周六组合首次真实采集及全 CLOSED 曲线绑定通过，CLOSED 数分别为 D1 trend/oscillation/dual 74/29/80、W1 13/1/14；均非空，不因 helper 文件名 empty-v3 推断空态。周线趋势转折保留原生 WARMING（当前合约 35 Bar 未满 120，12 历史区段预热）。六行原始 observed 不改，另存 final6，不重采。见 `browser/legacy-regression-final6-v3-observations.json`、`legacy-complete-binding.json`。

实际 pending cancel、0.2521 秒 AbortError 与 fresh 返回 5m 恢复通过，无 mock 注入。`python outputs/cj-minute-closeout-20260929/independent_acceptance_audit.py --saved` 实际 exit 0，PASS；仅保存证据重算，new HTTP/browser/provider/writes 均 0。独立核对 12 资产、12 API、12 API earlier、12 浏览器功能、12 earlier、12 全曲线、六日周与恢复；见 `independent-acceptance-audit.json`、`review-final-acceptance.md`。

61 张实际 PNG 逐张 view_image 审查，采集封口后清单、SHA 与实际尺寸 2400×2558 全部保持，无 Confirmed Issue；视口、密集 Marker、报价 403、MACD 窗口和 W1 预热边界保留，不以截图替代全数组数值或取消时序。见 `review-visual-final-v1.md/json`。

最终原生维护锁 granted/waiting 均 0，见 `final-maintenance-lock-readback.json`。专属 Chrome `cj-minute-closeout` 已关闭；API PID6681/8012、Web PID6760/5178 经命令/cwd/监听核对后 TERM，两 exec 会话均 exit 143，端口无监听。见 `browser-close-run.txt`、`resource-cleanup-readback.json`。只释放本项资源，其他任务和正式服务保持。

主代理只读汇总首次因视觉进度记录字段名不同发生 KeyError，原错误另存；按原两种 view_image 字段重新检查 61 张 SHA/尺寸通过，未改原记录或重采。61 个文档本地引用与固定 21 行检查 PASS（仅 P7-13 变化、JD NOT_STARTED）；`git diff --check` exit 0，`python3 scripts/engineering/secret_scan.py --json` 0 findings / passed。见 `final-doc-checks.json`、`final-doc-checks-helper-error.json`。

三份收尾文档经引用、固定 21 行、diff/secret 检查和独立 Review 后集成 develop；managed worktree 在集成后以原生 archive 工具退休，原始本机证据保留。正式分钟/Runtime/Scope/audience/通知、main/tag/release、Broker/账户保持任务外。

验收结论：**允许集成 develop**（仅本项三份收尾文档）。唯一最小下一步：由总控按既有串行队列安排 JD，本任务未启动。
