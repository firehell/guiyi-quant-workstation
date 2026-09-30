# UR 四周期历史候选处理

2026-09-28，P7-03 CANDIDATE_CLOSED，12/12。会话 `01a0e81f-3f72-7c11-984a-49d28065be8e`；实际 goal 已创建，无 token budget。

基线 develop `d990fae5b587c581a5aeafca95c81d0143c82fcc`，隔离工作区 `/Volumes/扩展盘/worktree/ur-minute-closeout/guiyi-quant-workstation`。范围 UR 5m/15m/30m/60m × trend/oscillation/dual；4输入、8基础、4融合、12页面。历史固定 max(2023-01-01,权威上市日)..2026-09-24；as_of=2026-09-24T07:00:00.000001+00:00。证据 `/Volumes/扩展盘/guiyi-quant-workstation/outputs/ur-minute-closeout-20260928/`。

1m只作可信聚合来源；正式分钟、Newow1m、worker保持关闭。不含 main/tag/release、Runtime/Scope、通知、Broker或交易。本任务未操作MA候选8012/5178。FU2309失败attempt禁止重试，UR维护须自身preflight、exact plan、预算及恢复证明。

## 数据维护与读回

UR rank1共12个物理owner：UR2305、UR2309、UR2401、UR2405、UR2409、UR2501、UR2505、UR2509、UR2601、UR2605、UR2609、UR2701。UR2305物理上市日2022-05-19证明品种在2023年前已存在；固定展示起点2023-01-01，计算prefix仍按各合约完整生命周期，不把物理合约上市日写成品种上市日。完成端点由Session确定为2026-09-24T07:00:00+00:00。

初始48依赖仅3完整，12保存流为空。原生48份dry-run去重87源月、356派生月；冻结bundle `campaign-plan-v2.json` SHA `a195a7e33f8c4a4287d684cfe2fbdba1575c7c09f700a13a78b46dd98bdedab3`。原生锁内hash/preimage、staging/hard validation、不可变发布、Catalog commit与独立读回执行；O_EXCL attempt不覆盖，失败停批无自动重试。独立Review通过后一次执行，45 READBACK_VERIFIED、3 NO_GAP；实际87 provider逻辑请求、356派生提交，失败/重试0。不将逻辑请求数写成SDK网络重试数。

当前额度于2026-09-28T13:08:52.717578+00:00剩余1,037,579,074 bytes；370,575源Bar×1024的保守预留379,468,800 bytes，不代表实际网络字节。磁盘777,318,592,512 bytes、锁0；UR2305 2023-01真实3600 Bar在outputs同盘scratch原子发布/读回，源与scratch SHA `93aefdc5dcdbe286b61a7872486a1c2af06d7ebe81c698a80bdf49b1df6441b7`。首次preflight导入名机械替换错误，导入即失败、零发布；失败日志保留，修正版才执行。UR维护未复现FU的ATOMIC_PUBLISH_FAILED，不解释FU UNKNOWN根因、不重试FU2309、不从额度反推其失败消费。

`inventory-difference.json`独立只读：583旧七频文件全部bytes/SHA保留；537旧pointer未变，46计划内pointer扩展且旧Bar逐值不变；397新增。源87操作=78新增+9扩展；派生356操作=319新增+37扩展。280 D1/W1 pointer未变。五频分区303→700；不是443个全新增，也不是全部旧pointer不变。

48/48最终依赖DATA_READY。四份aggregation全prefix每频140 contract-month/12 owner，同物理Canonical1m按权威Calendar/Session `(start,end]`重算逐值一致，5m116280、15m38760、30m20672、60m12920 Bar。`futures-boundaries.json`证明实际日盘09:00–10:15/10:30–11:30/13:30–15:00，无夜盘，30m短尾15分钟、60m短尾15/30分钟；owner无重入。无插值/缩窗/跨频替代，换月边界不串合约。

数据Review另实际核对48 plan/attempt/result/readback、931个distinct历次前像文件SHA及46扩充逐Bar不变。已见共享锁/源/Catalog无本次故障污染；下一品种仍须自身现场quota、存储、精确plan和恢复校验。

## 资产和候选身份

原生基础构建8项、融合构建4项全部完成，新增12、复用0；每频event Bar比行情多11个owner边界事件。所有stream保持enabled=false、activation_generation=0，schema为newow_intraday_pilot_20260927。8份原生plan哈希、12项身份、4融合所依赖的2源stream/revision/sequence/digest均经独立Review；源manifest哈希构建前后不变。

4个coverage.complete_window_proven均为false，不能宣称2023-01-01起每根Bar都有策略输出。最早computed端点：5m 2023-01-09T02:05Z、15m 2023-01-31T05:45Z、30m 2023-01-09T07:00Z、60m 2023-03-20T06:30Z；仍按权威完整prefix预热，无缩窗替代。

只读候选API8011/Web5175，实际代码身份d990fae5b587c581a5aeafca95c81d0143c82fcc、UR singleton、固定as_of；capabilities与编译后的前端配置实际回读一致。code/source身份属于该冻结基线；后续Git提交只交付文档，不把新文档SHA冒充验收代码SHA。正式8000/5173与MA8012/5178未切换。

## API与真实Chrome

API先于Chrome串行完成：12项READY、150次GET（149 per-combination + 1 initial identity），主图/伙伴主图、稳定Marker、普通cursor、完整参考统计/曲线/记录、融合和6副图。12项较早窗口API与原窗口同快照且时间不重叠。两次真实错误频率快照返回409 NEWOW_SNAPSHOT_GENERATION_CONFLICT，重新获取后主图/参考恢复至匹配身份。

真实Chrome保留原始XHR/DOM和截图；不注入响应或使用mock。12主图、12完整累计曲线均经逐张独立Review，已完成累计与全部窗口明确选中，列表ID和曲线点列与原始请求相符。同日分页实际3 PASS、9有据N/A；不得以N/A冒充真实点击成功。持有过程不可用仍按实际页面显示；参考收益不是因果收益、模型账户收益或真实账户收益。

60m震荡原任务checker出现REFERENCE_DOM_PAGE_AMBIGUOUS：全统计与近一年records碰巧拥有同43条ID，但input hash随窗口不同。只修离线checker，限定实际history_limit=200 records；不改产品、请求或原始观察。原错误矩阵/脚本保留；原checker RED 2 failed/1 passed，修正版GREEN 3 passed，另验证缺records不能借stats、两个records冲突不能通过。最终功能矩阵75 PASS/9 NOT_APPLICABLE。

真实冷启动取消与短timeout：pending请求ERR_ABORTED、0.2516秒AbortError、返回5m后主图/记录/曲线HTTP200与稳定身份恢复。原helper SHA绑定错误在浏览器动作前失败；原functional缺静态JS seed在页面动作前失败；均保存失败日志，修正任务文件后才执行。没有改写旧失败或将其计作通过。

较早主图12项真实点击/缩放/自动分页完成，检查同快照、严格早于原窗口、可见older Marker与旧Bar匹配、请求归零后5次一致稳态顶价；逐张视觉Review已通过。深窗口MACD全覆盖未证明。日周较早分页未额外测试。

## 定向验证

真实命令（主工作区Python虚拟环境，outputs为本机证据）：

```sh
PYTHONDONTWRITEBYTECODE=1 services/quant-api/.venv/bin/python -m pytest outputs/ur-minute-closeout-20260928/test_scope.py outputs/ur-minute-closeout-20260928/browser/test_record_binding.py -q -p no:cacheprovider
```

12 passed in 1.15s。scope覆盖范围只减不增、错误品种/合约/月/窗口/预算/频率拒绝；record binding使用实际wire。没有产品源码变更，不机械重跑无关全量测试。真实维护、资产、API、Chrome命令与原始日志均在证据目录；raw/Parquet/私有配置不提交Git。

## 最终 Review 与交付边界

日周6组合实际回归33 PASS/3趋势转折WARMING；主图、MACD、完整累计曲线、近一年记录、切换返回及错误检查通过。实际W1全部窗口performance_since=2023-01-01、performance_through/actual_available_through=2026-09-24、reference_cutoff=2026-09-24T07:00:00Z；不沿用其他品种的旧周线端点。负向离线检查拒绝空Bars和过期reference，不把离线负向检查作为浏览器操作。

独立Reviewer已核对全部原始身份/哈希/计划、数据读回、资产、API、功能12、完整曲线12、较早主图12和日周6（共48截图逐张查看），结论12/12 CANDIDATE_CLOSED。最终矩阵browser/matrix.json，Review为independent-review.md。缩放后settling采样12项未开放样本为0，仅证明被采样阶段与完成稳态，不证明所有点击瞬态均无闪动。

验收仅属于冻结源码d990fae5b587c581a5aeafca95c81d0143c82fcc的UR历史候选。4个complete_window_proven=false、深窗MACD整段覆盖未证明、持有过程不可用、日周older未额外测试仍保留；没有公式、成交、成本或收益语义变更。最新develop另有b5d12e2a1盘后/健康检查修复，本次文档集成保留该提交；新develop不是已验UR候选的新代码身份。

维护结果已原子提交并独立读回；恢复保留583旧不可变文件及旧Bar、exact preimage/plan、Catalog提交和attempt记录，不盲目重复已成功provider/write操作。FU UNKNOWN失败不由UR成功解释，不重试FU2309。没有新增正式分钟入口、worker、Scope、Runtime版本、main/tag/release、通知、Broker或订单，auto_order=false保持。

交付采用task commit/push后合入develop并push，精确Git结果另存本机git-integration-readback.json；Git只包含本记录、STATUS及P7-03行，原始数据/截图/配置不纳入。UR候选8011/5175进程仍需要隔离工作区，保留管理worktree及冻结代码，不清理其他任务资源。

唯一最小下一步：由总控安排P7-04 TA；本会话不创建下一项、不发送跨会话消息。
