# V 四周期历史候选闭环

2026-09-29，P7-06 V **12/12 CANDIDATE_CLOSED**；数据、资产、API、真实 Chrome 与独立 Review 已完成。仅交付本项历史候选与工程记录，不构成正式分钟开放、发布或 Runtime promotion。
会话 `01a0e8d5-9683-7332-8c80-72ce7a8c9ef0`，task branch `codex/v-minute-closeout`，管理工作区 `/Volumes/扩展盘/worktree/v-minute-closeout/guiyi-quant-workstation`。

## 范围与现场

只处理 V 5m/15m/30m/60m × trend/oscillation/dual，固定4输入、8基础流、4融合流、12页面；1m仅作为聚合源，原21品种分母与其他队列行不变。
Catalog 222合约最早上市日2009-05-25，与 `data/universe/product_window_starts.csv` 一致；固定窗口2023-01-01..2026-09-24，as_of=2026-09-24T07:00:00.000001+00:00。
候选源码冻结 `756a22fe29bb1da86301609ace8506aad5e4ab58`。续接时 develop 为 `729a788322652a9a575d2b0413be33a372bc01ca`，两者只有24个规则/文档文件差异，services/packages/scripts产品实现不变。本项没有产品源码、公式、收益或执行语义改动。
原始命令、计划、读回、图片与独立Review保留在本机 `outputs/v-minute-closeout-20260929/`，不提交行情、配置、凭据或原始运行日志。其他任务未提交输出未覆盖或清理。
正式分钟、Newow1m、main/tag/release、Runtime/worker/Scope、通知、Broker和订单不在范围；auto_order=false保持。

## 真实维护与数据验收

12个rank1 owner，48份原生dry-run；原依赖3/48 DATA_READY，12候选流原不存在。去重88源月、360派生月，保守预算584125440 bytes。
第一次exact apply在进程创建前被宿主自动审批拒绝；`host-approval-blocked.json`保留，不曾从其他入口执行。
owner随后明确交办“续接 V 任务，读取新规则并重新核对现场后推进”。新AGENTS及维护canonical明确完整历史候选闭环覆盖必要真实下载、Canonical/Catalog写入与候选构建。
重新核对48份fresh计划与原报告完全相等、quota1065847616 bytes、同盘scratch逐值/hash不变；共享锁占用时停止相关动作，之后只读确认释放及fresh PASS，未抢占其他任务。
附上新交办、当前规则与精确副作用后，宿主正常复核放行原exact命令。bundle SHA `5b2f0eeb502b9b51bb69cc5456cca33a256d48365e01c1a75d8d9639aa7073c6`。
实际维护完成：88 provider逻辑请求、360派生月，45单元READBACK_VERIFIED、3单元精确NO_GAP，无失败或盲重试；48/48 DATA_READY。

四频分别对全部12合约、141个月完整生命周期前缀独立重算。只使用同物理合约Canonical1m，Session `(start,end]`，存储OHLCV/OI逐值一致；夜盘交易日、周末/节假日、75分钟Session及30m/60m短尾边界通过。
591旧文件逐字节保留，540原指针不变、51按原生计划扩展、397新增；283 D1/W1指针保持不变，扩展保留旧Bar。独立data Review复算1039文件hash及564最终source/target hash绑定通过。
V自身Calendar/Session/completed_calendar_week证明9/25–27关闭，9/21该周终点为9/24 07:00UTC。未借用前品种时间或质量事实。

## disabled 候选资产与覆盖

候选schema `newow_intraday_pilot_20260927`，四频base/fusion原生构建全部completed，8基础+4融合共12唯一流，全部READY、enabled=false、activation_generation=0。
保存manifest与exact build plan、当前source digest、完整input count、revision/seq/checkpoint精确一致；四组fusion依赖绑定自身最终base stream/revision/seq/digest/snapshot。独立asset Review通过。
8基础流native availability覆盖FULL，每行12 VALID intervals、unavailable_days=[]；Calendar交易日/physical-owner集合与保存availability逐日完整相等，no_trade=0，未复制其他品种缺口事实。
**complete_window_proven=false保持**。first_computed_through分别为：5m/15m=2023-01-04T14:15Z，30m=2023-02-01T15:00Z，60m=2023-02-17T15:00Z。FULL不是从窗口首日已有计算输出或完整窗口收益的证明。

## API 与真实 Chrome

只读候选API/Web为8012/5178，固定源码/as_of、V singleton v27、realtime=false。启动helper最初误用RB-only单数环境变量而在app创建阶段退出，原helper/日志保留；改用原生复数白名单单元素v后实际身份及独立Review通过，不改产品代码。
152保存API请求、12/12组合READY；12主图/基础记录游标及4融合游标稳定性、12较早窗口、错频snapshot两节409拒绝/新快照同token恢复通过。五辅助ready，cup_handle按原生合同NOT_APPLICABLE。
真实Chrome12/12分钟功能观察通过；主图、完整closed累计曲线、近一年记录、模式/周期回切、辅助与身份均核对。较早窗口12/12实际旧Bar Marker可见、XHR绑定、同snapshot、严格更早、五稳定样本active=0/ready以及顶价前后一致通过。
真实pending取消、0.252秒AbortError、恢复到5m主图/记录/曲线通过，未注入mock或伪造响应。
49张最终原图逐张独立Review：12分钟主图、12完整曲线、12较早窗口、12日周主图/曲线、1取消恢复。补拍曲线的DOM IDs/逐点坐标与原functional观察精确一致；原12分钟curve截图亦保留。

V D1/W1六组合最终 **32 PASS / 3 WARMING / 1 有据NOT_APPLICABLE**。WARMING均为原生NEWOW_TREND_REVERSAL_WARMING。
W1震荡初次因工具要求非空曲线而DOM_NOT_SETTLED，原失败保留。原生固定窗口真实只有7条ROLLOVER_INTERRUPTED、零CLOSED，UI正确显示“暂无已完成参考交易”。
独立Review后的empty-v2仅重验此组合一次：服务端closed_count=0、完整curve_trades=[]、各阶段自身request/meta/chart token/hash/cutoff、full/before/return空态、近一年两条记录及回切IDs均匹配；曲线记VERIFIED_ZERO_CLOSED_REFERENCE_TRADES，不造收益或曲线。新增两原图终审通过。

## 实际验证与独立 Review

下列入口均实际执行，使用冻结worktree优先PYTHONPATH及既有安全配置，不输出秘密：

```sh
python campaign.py --apply --expected-plan-sha256 5b2f0eeb502b9b51bb69cc5456cca33a256d48365e01c1a75d8d9639aa7073c6
python verify_data_only.py
python build_assets.py
python verify_assets_only.py
python verify_api_only.py
python browser/regression_recovery-v5.py --kind cancel-timeout --execute
python browser/verify_v12.final-v5.py --execute
python browser/finish_observations.py
python browser/legacy_regression.empty-v2.py --execute --frequency 1w --mode oscillation
python -m pytest outputs/v-minute-closeout-20260929/test_scope.py outputs/v-minute-closeout-20260929/api-v5/test_coverage.py outputs/v-minute-closeout-20260929/browser/test_record_binding.py outputs/v-minute-closeout-20260929/browser/test_legacy_binding.py -q -p no:cacheprovider
```

维护、数据复算、8次base/fusion构建、资产/API/分钟观察/完整曲线/较早窗口均exit0；初次legacy工具零曲线失败并不因orchestrator exit0算通过，以corrected-final与新capture替代该一项。最终定向测试29 passed in1.16s，包括scope扩大、覆盖错报、记录绑定、dual profile/hash/partner/坐标、零曲线缺摘要/缺完整集合/错UI/回切借初始响应等负向保护。
preflight、helper、data、asset、preview、API、主图/完整曲线/较早窗口和日周独立Review均通过，无未解决Confirmed Issue；报告文件在本项outputs。CODE_COMPLETE / TEST_COMPLETE / REVIEW_COMPLETE；**允许集成develop**。

## 资源收尾与保留边界

只核对并停止本项API/Web PID、command、cwd，SIGTERM后8012/5178 unbound；专属Chrome `v-minute-closeout`已关闭。候选资产仍disabled，旧数据/原失败/全部实际证据保留；不按宽泛路径删除文件或改其他服务。
持有过程暂不可用、deep MACD未做额外因果验收、D1/W1 older-window未测、complete_window_proven=false、零费零滑点页面参考口径均保留。不宣称OOS/Walk-forward、模型账户收益、正式开放、RELEASED或RUNTIME_READY。
任务goal工具续接仍显示历史blocked且无active恢复API，未新建或改状态文件；实际工作按owner续接完成，终态以本项真实evidence为准。
完成工程集成后，唯一下一步为按固定队列交办SA；本项没有启动或发送下一品种任务。
