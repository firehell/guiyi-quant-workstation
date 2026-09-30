# TA 四周期历史候选处理

2026-09-28，P7-04 TA **12/12 CANDIDATE_CLOSED**。数据、保存资产、API、实际Chrome及日周兼容完成，独立Review通过；允许集成develop。会话 `01a0e854-76a8-7b12-b6ba-4ce7dc562341`。

## 范围与冻结身份

冻结维护/候选源码 `ba03d58d7012cc0557af80d2d9f75664f934d948`，已包含b5d12e2a1 completed-week/MDS修复；不借用UR d990的页面结论。管理工作区 `/Volumes/扩展盘/worktree/ta-minute-closeout/guiyi-quant-workstation`。只处理TA 5m/15m/30m/60m × trend/oscillation/dual，4输入、8基础、4融合、12页面；保留原21品种分母。1m仅可信聚合来源。

历史max(2023-01-01,权威上市日)..2026-09-24；as_of `2026-09-24T07:00:00.000001+00:00`，terminal completed `2026-09-24T07:00:00+00:00`。TA2305上市2022-05-19证明品种在2023年前存在，不冒充品种精确上市日。完整计算prefix按各物理合约生命周期；12个rank1 owner、11次边界，无owner重入。

| 物理合约 | 权威上市日 | rank1 owner起日 | owner止日 |
| --- | --- | --- | --- |
| TA2305 | 2022-05-19 | 2023-01-03 | 2023-04-10 |
| TA2309 | 2022-09-16 | 2023-04-11 | 2023-08-14 |
| TA2401 | 2023-01-17 | 2023-08-15 | 2023-12-08 |
| TA2405 | 2023-05-18 | 2023-12-11 | 2024-04-09 |
| TA2409 | 2023-09-15 | 2024-04-10 | 2024-08-13 |
| TA2501 | 2024-01-16 | 2024-08-14 | 2024-12-16 |
| TA2505 | 2024-05-20 | 2024-12-17 | 2025-04-14 |
| TA2509 | 2024-09-18 | 2025-04-15 | 2025-08-14 |
| TA2601 | 2025-01-16 | 2025-08-15 | 2025-12-15 |
| TA2605 | 2025-05-20 | 2025-12-16 | 2026-04-16 |
| TA2609 | 2025-09-15 | 2026-04-17 | 2026-08-19 |
| TA2701 | 2026-01-19 | 2026-08-20 | 2026-09-24 |


原始证据仅在本机 `/Volumes/扩展盘/guiyi-quant-workstation/outputs/ta-minute-closeout-20260928/`，不提交原始行情、数据库、浏览器日志或凭据。候选身份和schema/stream/revision/seq/source hashes见`candidate.json`、`source-assets-final-v5.json`；各实际URI及SHA由inventory/maintenance/readback固定。

## 数据执行及逐值验收

初始48物理四频prefix为3 DATA_READY、45不完整，五频308分区，12保存流不存在。48份原生contract-warmup dry-run去重88源月、360派生月，570435源Bar×1024保守预算584125440 bytes。TA2305 2023-01真实5280 Bar仅先在outputs同盘scratch发布/逐值读回；source/scratch SHA `d7ec48b74eb99bc750377edd2f62b7551d59a668800fa4b5a6416fcbf9abd68e`，Canonical schema SHA `679ce5bb0b71aad3cb60bd7dc3c60539b0e08bf6d00e667fd16c6767cb41434a`。

精确bundle `campaign-plan-v2.json` SHA `49d7e03b661895f2e14120037b438d22c54a1260541ee83ccef6748213271b7e`。首次apply在CreateProcess前被宿主自动审批拒绝，生产调用/attempt/mutation均为零；原拒绝与308分区零漂移证据保留。owner随后直接回复“授权了，你继续”，刷新代码/脚本/plan/quota/锁/前像后，同exact命令经正常宿主审批放行；没有绕过控制。执行前quota剩余1029308480 bytes、磁盘空闲781650579456 bytes、维护锁0。额度估计不是实际网络消费。

原生维护锁、hash/前像检查、O_EXCL/fsync durable attempt、单位原子发布与读回持续生效。一次执行45 READBACK_VERIFIED、3 NO_GAP；88逻辑provider请求、360派生月，零失败、零重试。旧591七频不可变文件全部保留；540旧pointer不变，51计划内扩展的原Bar逐值不变，新增397 pointer；其中283 D1/W1 pointer不变。FU2309原UNKNOWN及attempt未触碰/重试。

最终48/48 DATA_READY，四输入通过；五频各141分区共705。四频原生`aggregate_full_prefix`逐物理合约用同一Canonical1m、Decimal逐值核对，不从其他派生频率递推：5m 176964、15m 58988、30m 30788、60m 17982 Bar。源SHA在资产构建前后相同。

TA权威Session本地09:00–10:15、10:30–11:30、13:30–15:00、21:00–23:00；固定`(start,end]`，时长60/75/90/120分钟，30m短尾15、60m短尾15/30。原生reader验证夜盘、周末、假日及trading_day；真实2023-01-03 21:01归1/4、周五1/6 21:01归周一1/9，18个原始Parquet边界例见`futures-boundaries.json`。没有建立第二套Session/resolver。

## 保存资产与页面验收

原生串行build_base/build_fusion：8基础+4融合全部新增、复用0；schema `newow_intraday_pilot_20260927`，12流均disabled、activation_generation=0。输入事件含11合约边界：5m 176975、15m 58999、30m 30799、60m 17993。stream identity/formula/profile/revision/seq/source digest按12流逐项验证，融合逐项绑定两个基础流。

所有流`complete_window_proven=false`，不能以原始数据完整替代策略完整窗口证明。首次computed：5m/15m `2023-01-04T14:15:00+00:00`，30m `2023-02-01T15:00:00+00:00`，60m `2023-02-17T15:00:00+00:00`；终点均9/24 07:00 UTC。

真实API：12/12 READY，153次GET（152组合请求及1初始身份），六辅助逐项核验，杯柄12明确NOT_APPLICABLE。37次GET核验12较早窗口，strict nonoverlap/same snapshot；两次错误频率token真实409 `NEWOW_SNAPSHOT_GENERATION_CONFLICT`，正确token chart/reference恢复。HTTP wire长度/SHA和compact观察保留，不宣称重新验证未保存的完整wire。

真实Chrome串行，未mock网络/响应。被动XHR observer SHA `c1f731246f76cfa43de7f5ab18a31f496b9f4ce0821960be12c9103cd9077134`；最终functional helper SHA `13f0dd6c5ff9e9ca69aaa016fe39a8a6bbb548cf9a79496d11e4eed071b011c8`，实际history_limit=200记录绑定采用修正版。12功能行共76 PASS/8同日分页NOT_APPLICABLE、322实际XHR；实际同日cursor仅15m dual及5m三个模式共4行，不能把没有cursor记PASS。

冷API后的取消/短超时/恢复：实际pending、AbortError约0.2512秒、恢复5m200卡片/1曲线、chart/reference真实HTTP200。完整累计曲线12行的DOM记录ID和polyline逐值匹配原功能观察，全部/已完成明确选中。补拍初次仅因旧functional文件名缺失，在浏览器动作前失败；保留原脚本/日志，只修指向实际final-v5文件，无产品/断言修改。

较早主图逐行实点`加载更早`至真实`chart_older_window`，视口可见Marker时间属于实际older Bar；strict earlier/same token，缩放自动分页归零、末5次价格稳定且前后相同才截图。TA日周六组合实际33 PASS/3辅助WARMING（TrendReversal 35<120），无空Bar或过时reference反例通过。实际W1参考截点2026-09-24T07:00:00Z；`weekly-authority-readback.json`冻结当周七日权威Calendar和有效Session，9/25–27休市，原生completed_calendar_week精确返回9/24 07:00:00.000001UTC，与实际API/Bar绑定。不是UR旧截点。

## 实际命令、Review与剩余边界

所有命令使用冻结worktree优先的PYTHONPATH、安全配置既有加载，不输出秘密。实际执行入口均位于上述outputs，关键命令：

```sh
python campaign.py --apply --expected-plan-sha256 49d7e03b661895f2e14120037b438d22c54a1260541ee83ccef6748213271b7e
python build_assets.py
python api-v5/readback.py --execute
python api-v5/earlier_windows.py
python snapshot_recovery-v5.py
python browser/regression_recovery-v5.py --kind cancel-timeout --execute
python browser/verify_ta12.final-v5.py --execute
python browser/capture_full_curves-v5.py --execute
python browser/earlier_windows-v8.py
python browser/legacy_regression.py --execute
python browser/legacy_evaluate_final.py
python weekly_authority_readback.py
python -m pytest outputs/ta-minute-closeout-20260928/test_scope.py outputs/ta-minute-closeout-20260928/browser/test_record_binding.py -q -p no:cacheprovider
```

最后定向测试日志`final-targeted-tests.txt`：12 passed in 0.95s；scope拒绝越界和durable attempt覆盖、记录实际绑定/缺记录/ambiguous反例通过。无产品源码、公式或收益口径改动，不机械运行全仓/Web build。独立Review按原生plans/48维护结果/943旧URI SHA/51扩展旧Bar/705新身份，8资产计划和12流、API合同、原始DOM/XHR及截图分别验收；最终结论保存在`independent-review.md`：49张原图逐张审查、保存raw逐项重算、真实短周权威绑定通过；无Confirmed Issue，允许集成develop。最终12行闭环见`browser/matrix.json`。

保留完整策略窗口coverage未证明、深窗口MACD整段覆盖未证明、密集Marker文字可能重叠、持有过程曲线不可用、日周较早分页未额外验。稳定状态价不变不证明所有pending瞬时均无“未开放”。页面参考零费用/零滑点、不可执行，不能冒充因果/OOS、Paper或账户收益。

正式8000/5173及UR8011/5175未停止/修改。TA8012/5178启动前无listener，按实际command/cwd证明自身进程，验收后仅对自有API/Web发送SIGTERM并关闭任务专用Chrome、释放端口；task-only D1/W1入口和fixed as_of用于本次兼容验证。未启用Runtime、Scope、worker，未发送通知/创建订单；auto_order=false保持。工程交付至develop，不包含main/tag/release或正式消费者切换。

恢复：原不可变文件和完整URI/SHA前像保留，计划内扩展原Bar不变；不得盲目反指Catalog/重跑或删除。未来任何数据恢复应独立冻结精确计划并验证原子性、幂等和依赖。文档可精确forward revert；disabled候选不需生产停机或active切换。

唯一最小下一步：由总控安排P7-05 SH；本会话不创建下一chat、不主动发跨会话消息。
