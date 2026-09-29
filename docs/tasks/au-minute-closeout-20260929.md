# AU 四周期历史候选闭环

状态：**CANDIDATE_CLOSED，12/12**。数据、候选资产、真实 API/Chrome 与独立 Review 的结论分别记录如下；允许集成 develop。

## 已验证范围

仅 P7-08 AU，固定5m/15m/30m/60m × trend/oscillation/dual，4输入、8基础流、4融合流、12页面；1m仅聚合源。窗口2023-01-01..2026-09-24，as_of=2026-09-24T07:00:00.000001+00:00。冻结源码b2c355f5f0c98c3ade6f00339725d62498efdd86；隔离工作区 /Volumes/扩展盘/worktree/au-minute-closeout/guiyi-quant-workstation，branch codex/au-minute-closeout。原始evidence仅在本机outputs/au-minute-closeout-20260929/，不提交行情、配置、凭据、原始响应或图片。

## 数据

22实际rank1 owner、88份原生contract_warmup计划，初始25/88 DATA_READY。源1m完整，本次get_price/行情下载请求0（仅get_quota只读预算查询）、681去重派生月；计划SHA0bcf5f1642965d069f7cc6110b1f9aa100310c25beaad9521704f0dcd34c8a84。实际63READBACK_VERIFIED+25NO_GAP，88/88 DATA_READY；没有维护重试或未知提交。
1350旧七频不可变文件逐字节保持；1296旧pointer不变，54扩展且保留全部旧Bar，627新增pointer；562日周pointer保持。
四频22owner、各283contract-months全部生命周期前缀独立用同物理合约Canonical1m按Session(start,end]重算，926135Bar全部OHLCV/OI/turnover/time一致：5m577461、15m192487、30m98886、60m57301。独立计算使用Decimal精度200。AU夜盘21:00–02:30及交易日/周末归属、75分钟Session、30m15分钟与60m15/30分钟尾、21换月边界通过。AU自身Calendar证明9/25–27关闭、completed week终点9/24 07UTC。

## 工具失败与恢复边界

5m基础原生execute已完成两条完整577482输入流，辅助脚本之后因RUSAGE_SELF被误改为RUAUGE_SELF在收集RSS时失败。原日志、plan、attempt PENDING和resume保留；未重跑/恢复构建。只读核对与独立复核证明两条active publication READY、disabled/generation0，stored manifest、native plan hash/source token、完整end index、seq2257及computed_through精确匹配。单独保存5m-build-outcome-readback.json，明确原生report和timings不可用，不伪造原生报告。后续只运行未启动动作。修正仅本机任务helper，不修改产品代码、plan hash或失败记录。

早期只读fixture测试在coverage/API/Chrome实际fixtures尚未生成时出现FileNotFoundError，另一次收集时未设置冻结PYTHONPATH触发身份guard；均保留原输出，实际AUfixtures生成后最终重验通过，不宣称此前通过。
日周v2采集提前启动，其60m回切依赖尚未构建，首组实际65秒timeout保存raw/CLI/png；精确SIGINT只停止owned采集runner PID15460，exit130，不停止候选写入。最终日周v3等待全部资产/API完成，并增加精确代码/原生completed guard与既有输出保护，全部fresh重采；v2图片不得计入最终49图。

## 候选资产实际读回

12唯一stream READY/enabled=false/activation_generation=0；7尚未启动的native构建正常completed，5m基础使用独立验证publication且不重跑。全部plan/source manifest/input count/revision/seq/end checkpoint绑定，4融合与各自最终base stream/revision/seq/digest/snapshot匹配；独立资产Review通过。
8基础流native覆盖FULL，各22VALID interval，与AU自身Calendar owner/交易日并集相等；unavailable_days=[]、source no_trade=0。complete_window_proven=false保留；first_computed_through5m/15m2023-01-03T15:45Z、30m2023-01-13T18:30Z、60m2023-02-01T16:00Z。FULL不代替窗口首日策略输出或完整窗口收益证明。

## API 与恢复证据

候选8012/5178固定b2c源码、as_of与AU singleton v27/realtime=false；真实API152保存请求、12/12READY、12older窗口、两次错频409（安全JSON detail保存）与fresh同token chart/reference恢复通过，独立APIReview通过。原错误capabilities路线403记录保留，只有原生product-capabilities正确读回作为范围证据。
真实Chrome pending取消、0.25360000002384187秒AbortError短超时与fresh5m主图/记录/曲线恢复通过。逐Bar持有过程不可用与解释尚未读取不伪称已验收。
资源只读精确核对API PID6767/root cwd及Web PID6834/frozen apps cwd；已按同一command/PID/cwd精确SIGTERM关闭本项两个进程，8012/5178读回UNBOUND；au-minute-closeout Chrome实际close成功，其他服务不触及。

分钟功能12/12实际完成：75PASS/9有据NOT_APPLICABLE，actual history_limit200/DOM IDs、独立chart/ref分页与模式/周期回切身份核对通过。60m无当前窗口后页等N/A均保留native原因；30mtrend、5mtrend/dual实际同日分页PASS。

早窗视觉保留一项非阻断Risk / Needs Verification：主图按兼容窗口累积Bar，而MACD按最后接受的单窗口替换。60m真实network依次07/23–09/24、05/19–07/22、缩放触发03/09–05/18，均同snapshot/200；截图主图显示5–9月，MACD仅最后窗口与可见5月的交集。现有useNewowProduct/Workspace实现与newow-product-reference-trading canonical的exact accepted window合同一致，canonical尚未要求跨窗口累计aux。独立Review判定不阻塞本版earlier price/markers/topprice固定验收，但跨窗口全段副图覆盖未验收，不能声称完整；后续先明确累积aux合同再专测。Canonical前缀独立验证仍通过。

## 完整曲线与日周回归

12/12分钟完整CLOSED曲线使用fresh自身snapshot；全部CLOSED身份集合、Decimal累计值与全部SVG坐标逐值核对，窗口/section/token与当前流revision/seq、源码身份绑定。12/12较早窗口实际price/markers和5次稳定viewport/topprice观察通过，不用导航或HTTP200代替页面验收。

日周六组32 PASS/3原生WARMING/1有据零CLOSED曲线NOT_APPLICABLE。AU自身W1震荡完整窗口0 CLOSED+2 ROLLOVER_INTERRUPTED，近一年0 CLOSED+1 ROLLOVER_INTERRUPTED；原生胜率、均值和sum_return_percentage_points为null，页面显示—/无SVG及真实空曲线说明。空数组算术sum=0仅用于核对，不冒充原生收益，不制造零收益线。其余完整CLOSED数量：D1趋势57、震荡22、融合68；W1趋势7、融合7。六组全部阶段的完整记录身份、Decimal和全部曲线点独立复核通过。

## 实际验证与独立 Review

冻结PYTHONPATH指向隔离源码，以下定向测试均使用本机真实AU fixtures：

- `pytest outputs/au-minute-closeout-20260929/test_scope.py outputs/au-minute-closeout-20260929/test_complete_curve_binding.py -q -p no:cacheprovider`：55 passed，1.55s（final-scope-complete-curve-tests.txt）。
- `pytest outputs/au-minute-closeout-20260929/api-v5/test_coverage.py -q`：6 passed，0.04s（final-coverage-negative-tests.txt）。
- `pytest outputs/au-minute-closeout-20260929/browser/test_record_binding.py -q`：3 passed，0.06s（actual-record-negative-tests.txt）。
- `pytest outputs/au-minute-closeout-20260929/test_legacy_binding.py -q`：3 passed，0.05s（legacy-zero-green.txt），覆盖AU零CLOSED/null及拒绝伪造平线。合计67项定向测试通过。
- 原生aggregation/Session/reference interruption边界回归：58 passed（native-boundary-regression.txt）。
- `verify_remaining.py`九个只读验收阶段全部exit0（verify-remaining-host-run.txt）；最终`final_asset_readback.py` exit0，全部12 descriptors及整个stored state逐值等于构建后读回，仍READY/disabled/generation0（final-asset-readback.json）。

独立Review按数据维护、全生命周期926135 Bar重算、5m基础publication复用、资产、API、Chrome记录/曲线身份及原图分别核对。最终49张原图按SHA绑定逐张审阅，不使用旧v2失败图片。无未解决Confirmed Issue；上述跨窗口副图范围是非阻断Risk / Needs Verification，不扩大本次验收结论。最终审阅证据为review-visual-observations.json、review-final-curves-independent.json及review-final.md；原始证据均保留本机，不纳入Git。

## 交付边界

仅修改本记录、STATUS.md的AU入口及P7-08队列行；固定21分母、其他品种与AG NOT_STARTED保持。产品源码/公式/策略和reference模型版本未改。FULL覆盖但complete_window_proven=false、持有过程、deep MACD因果专测、日周较早窗口仍未验收；未声明OOS、可执行收益、账户交易、正式分钟开放、release或Runtime。

本项候选与临时资源已验收，允许集成develop。未改变main/tag/release、Runtime/worker/Scope/audience/通知或auto_order=false。唯一下一步为P7-09 AG，需由owner交办；本任务未启动AG。
