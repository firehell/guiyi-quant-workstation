# SH 四周期历史候选处理

2026-09-28启动，2026-09-29收尾，P7-05 SH **12/12 CANDIDATE_CLOSED**。数据、保存资产、API、实际Chrome与日周兼容验证完成，独立Review通过；允许集成develop。会话 `01a0e895-159e-70b0-aa88-df1d96fad51a`。

## 范围与冻结身份

冻结维护/候选源码 `397dd8deeb9ea07b533c27f32bc665e338a1972b`，包含已集成v27 singleton与较早窗口/顶价、completed-week能力；本项无产品源码、公式或收益口径修改。
管理工作区 `/Volumes/扩展盘/worktree/sh-minute-closeout/guiyi-quant-workstation`，分支 `codex/sh-minute-closeout`。
只处理SH 5m/15m/30m/60m × trend/oscillation/dual：4输入、8基础、4融合、12页面；1m只作可信聚合来源，原21品种分母保留。

历史 `2023-09-15..2026-09-24`，as_of `2026-09-24T07:00:00.000001+00:00`；实际terminal completed为 `2026-09-24T07:00:00+00:00`。
Catalog 46个SH物理合约最早上市日2023-09-15；与[郑商所上市资料](https://www.czce.com.cn/cn/rootfiles/2023/10/18/1697226838884489-1697226838904727.pdf)一致。
`product_window_starts.csv`中的SH起点同日，结合2023-01-01 floor得出本项默认窗口；原上市前映射扫描失败保留，没有据此补数、缩窗或追新。
11段rank1 owner、10次换月、无owner重入；完整计算prefix使用各自物理合约生命周期。

| 物理合约 | 权威上市日 | owner起日 | owner止日 |
| --- | --- | --- | --- |
| SH2405 | 2023-09-15 | 2023-09-15 | 2024-04-29 |
| SH2409 | 2023-09-15 | 2024-04-30 | 2024-08-28 |
| SH2501 | 2024-01-16 | 2024-08-29 | 2024-12-17 |
| SH2505 | 2024-05-20 | 2024-12-18 | 2025-04-22 |
| SH2509 | 2024-09-18 | 2025-04-23 | 2025-08-18 |
| SH2601 | 2025-01-16 | 2025-08-19 | 2025-12-10 |
| SH2603 | 2025-03-17 | 2025-12-11 | 2026-02-24 |
| SH2605 | 2025-05-20 | 2026-02-25 | 2026-04-15 |
| SH2607 | 2025-07-15 | 2026-04-16 | 2026-06-16 |
| SH2609 | 2025-09-15 | 2026-06-17 | 2026-08-13 |
| SH2611 | 2025-11-17 | 2026-08-14 | 2026-09-24 |

原始证据只保留于本机 `/Volumes/扩展盘/guiyi-quant-workstation/outputs/sh-minute-closeout-20260928/`，不提交行情、DB、浏览器raw、配置或凭据。
`candidate.json`、`source-assets-final-v5.json`固定code/schema/stream/revision/seq/source hash；Catalog精确URI及SHA由inventory、campaign各单元和读回保存。
候选schema为 `newow_intraday_pilot_20260927`，API/Web为8012/5178。正式8000/5173及其他任务端口不在操作范围。

## 精确数据维护与独立读回

初始44四频物理prefix为7 DATA_READY，12保存流不存在。44份原生contract-warmup dry-run去重80源月、330派生月，
519720源Bar×1024保守预算532193280 bytes。执行前preflight supplier额度1018381254 bytes、磁盘空闲780357447680 bytes、维护锁0；
不是借TA余额或把预算当实际消费。

执行前SH2405 2023-09已有3330根真实1m Bar在本项outputs同盘scratch原子发布/逐值读回通过，
源/scratch SHA `02dacf18729c3f6c39f45eac7e4e7acf1305f9868c91005fc368170fa7bf8f54`。
Canonical schema SHA `679ce5bb0b71aad3cb60bd7dc3c60539b0e08bf6d00e667fd16c6767cb41434a`。
独立preflight Review允许执行精确bundle `campaign-plan-v2.json` SHA
`b2ffd41b3ef74a21020f8bdd9f5a85439f659f2f5c11b10a6a431cd28eaad74e`。

一次维护完成37 READBACK_VERIFIED、7 NO_GAP，80逻辑provider源请求、330派生月，无失败或重试。
原生维护锁、锁内hash/前像校验、O_EXCL/fsync一次性attempt、单位原子提交和独立读回持续生效。
维护后quota实际只读剩余1010732489 bytes；SDK网络次数/字节归因不由逻辑请求数推断。
FU2309原UNKNOWN、attempt和禁重试边界未触碰；SH成功不解释FU根因。

最终44/44 DATA_READY，五频每频127分区共635。初始523七频旧不可变文件全保留；
477旧pointer不变、46计划内扩展原Bar逐值不变、364新增pointer，最终七频887文件实际SHA由独立Review核对。
252 D1/W1 pointer、URI、source_quality内容/hash、coverage及有效Bar保持一致。
旧SH2501等8个日线质量分区的严格reader触发 `PARTITION_PRICE_UNAVAILABLE`，原脚本和失败日志保留；
仅前像保留验收改用原生quality reader验证源质量/schema/覆盖，分钟仍严格reader。
独立复核252日周文件、2842有效Bar及8个质量分区逐项通过，不把质量例外称为价格完整，也未修复日周数据。

同物理Canonical1m独立重算四频全部prefix，Decimal逐值核对：5m 161880、15m 53960、30m 28164、60m 16450 Bar。
SH权威Session上海时间09:00–10:15、10:30–11:30、13:30–15:00、21:00–23:00；
`(start,end]`，60/75/90/120分钟，30m短尾15、60m短尾15/30。
夜盘、周末、假日和trading_day由原生reader验证，真实Parquet边界例在`futures-boundaries.json`，未建立第二套resolver。

## 保存资产与覆盖边界

原生串行build_base/build_fusion新增8基础+4融合，复用0；12流全部disabled、activation_generation=0，独立revision/seq/source digest读回通过。
每流输入事件（含10合约边界）：5m 161890、15m 53970、30m 28174、60m 16460。
保存源pre/final hash相同；融合绑定各自两基础流，公式和参考模型身份未变。

12流 `complete_window_proven=false` 全部保留；各频first_computed：
5m `2023-09-20T13:20:00+00:00`、15m `2023-10-10T06:00:00+00:00`、
30m `2023-10-24T07:00:00+00:00`、60m `2023-11-14T14:00:00+00:00`，computed终点9/24 07:00UTC。
固定历史窗口、原生availability和更长first_computed边界是不同事实。

实际参考覆盖：趋势FULL，震荡PARTIAL。5m/15m初始WARMING为9/15单日，
30m/60m为9/15..9/18；四频 `unavailable_days=[]`。
原API helper强制FULL导致四个震荡 `REFERENCE_WINDOW` 失败，原代码/输出保留；
独立只读从保存availability、owner、revision/seq/snapshot复用原生`_coverage`生成`coverage-expected.json`，
修正为逐区间、覆盖状态和generation精确匹配；不放宽窗口、身份、hash、cursor或去重。
仅补验这四个组合，原八项通过证据复用；不缩窗去掉预热、不改为FULL。
负向测试拒绝伪FULL、错合约、遗漏预热、额外缺口和错误generation；独立Review确认适配。

## API与真实Chrome

API最终12/12 READY；最终12行保存152次GET，原四失败的16次另保留，两个主读回初始identity GET单列。
wire长度/SHA与compact观察保留，不宣称保留了每份完整wire。
12较早窗口API严格不重叠/same snapshot通过；错频token真实两次409 `NEWOW_SNAPSHOT_GENERATION_CONFLICT`，正确chart/reference恢复。

被动XHR observer限定SH SHA `b6524b6bd1b85e154a568ec56d70af24c301f1413d1d5645fba2cd4223cffb5d`；
functional helper SHA `2912a23205e975aa68bf2e7777ec142bca855c1e06b35ee3002a1d1ee463dc49`。
12真实功能行77 PASS/7同日分页NOT_APPLICABLE、322实际XHR；
实际同日cursor为15m三模式、5m趋势/dual共5行，无样本有据NA。
base records按实际history_limit=200请求绑定DOM，不借全统计窗或相同ID冒充绑定。
冷请求实测pending取消、AbortError约0.2528秒及5m 200卡片/曲线恢复。

12全部/已完成累计曲线DOM记录ID和polyline逐值匹配原功能观察；fullcapture引用实际functional-matrix-final-v5.json。
12较早主图实点至chart_older_window、视口Marker时间属于真实older Bar，
same token/strict earlier、自动分页active=0且按钮ready、末5次价格稳定与翻页前后相同才截图。
SH日周六组合实际Chrome 30 PASS / 6辅助WARMING：D1 MACD ready、TrendReversal WARMING；
W1两辅助均WARMING，原生reason如实保留；空Bar、陈旧reference反例拒绝。
日周实际全窗参数2023-09-15..2026-09-24另作六组只读补验，旧snapshot过期409保留；
以原Chrome chart实际参数建立新token，chart hash对原chart、reference hash对原全窗reference、截止点不变。
D1/W1 trend与dual FULL，oscillation PARTIAL；D1初始WARMING9/15..9/27、W1初始WARMING9/15..11/17，全部unavailable_days=[]。
这是owner窗口参考availability，不证明生命周期prefix价格完整；8个旧quality分区仍保持原事实。
原helper对phase、chart/reference分层hash及dual chart参数的错误断言/422均保留，最终按实际请求精确绑定，不放宽hash或窗口。

本项原生Calendar/Session/completed_calendar_week证明9/25–27关闭，terminal_completed为9/24 07:00UTC。
周辅助脚本最初沿用TA硬编码ba03d58d SHA；原脚本、JSON和日志保留。
修正后实际在SH冻结worktree397dd8de重新执行原生只读命令，记录实际git HEAD、composition模块路径/SHA，
新证据SHA `17ddb63e3af4b7bd4b1afe1e7a2c9e9ccbe74f32401aebe4afa32b5eec40f47e`，日历/Session/原生端点结果完全相同。
49张实际原图逐张独立终审：12分钟主图、12全曲线、12较早主图、12日周主图/曲线和1取消恢复；
原12张较差曲线视图亦保留，以fullcapture替代其最终视觉验收。

## 实际验证、Review与工程交付

脚本均在本项outputs，使用冻结worktree优先PYTHONPATH和既有安全配置，不输出秘密。实际入口：

```sh
python campaign.py --apply --expected-plan-sha256 b2ffd41b3ef74a21020f8bdd9f5a85439f659f2f5c11b10a6a431cd28eaad74e
python verify_data_assets.py
python verify_data_assets_resume.py
python coverage_expected.py
python api-v5/readback.py --execute
python api-v5/resume_coverage.py
python api-v5/earlier_windows.py
python snapshot_recovery-v5.py
python browser/regression_recovery-v5.py --kind cancel-timeout --execute
python browser/verify_sh12.final-v5.py --execute
python browser/finish_observations.py
python weekly_authority_readback.py
python legacy_quality_readback.py
python -m pytest outputs/sh-minute-closeout-20260928/test_scope.py outputs/sh-minute-closeout-20260928/api-v5/test_coverage.py outputs/sh-minute-closeout-20260928/browser/test_record_binding.py -q -p no:cacheprovider
```

`verify_data_assets.py`在旧日线严格reader处exit1；resume仅从适配后的前像验收继续，不重跑维护或已通过inventory/dependencies。
原API四个覆盖断言失败亦保留；最终定向测试`final-targeted-tests.txt`为18 passed in 1.06s；提交前复跑18 passed in 1.17s。
没有产品源码变化，不机械重跑前品种、全量Web build或全仓库测试。
独立preflight、helper、数据、资产、API覆盖纠正、49实际原图、日周与周端点终审完成；最终结论见本项 `independent-review.md`，REVIEW_COMPLETE / 允许集成develop。

页面参考零费用/零滑点、executable=false，不能作为因果/OOS、Paper或账户收益。
完整策略窗口coverage未证明、深窗口MACD整段覆盖未证明、密集Marker文字可能重叠、持有过程曲线不可用、
日周较早窗口未额外验；稳态顶价测试不保证所有pending瞬时均无过渡提示。

不包含main/tag/release、Runtime promotion、正式分钟入口/worker/Scope、通知、Broker或订单；auto_order=false保持。
已核对8012/5178进程PID、命令、cwd与监听地址，仅对本项API/Web发SIGTERM，端口unbound读回通过；
任务Chrome会话关闭。`resources-release.json`与`browser/session-close.txt`保存证据。
源码、disabled资产与全部原始证据保留；UR及正式进程未触碰。工程交付只提交本记录、STATUS及P7-05 roadmap行，普通push/集成develop后做remote exact SHA读回，原始输出不提交。

恢复：旧不可变文件与精确前像保留，计划内扩展旧Bar不变；
不得盲目反指Catalog、覆盖或重跑attempt。未来数据恢复须冻结精确计划并验证原子性、幂等与依赖。
文档可精确forward revert；disabled候选无生产active切换可回退。
唯一最小下一步：由总控安排P7-06 V，本chat不创建下一chat或主动发送跨chat消息。
