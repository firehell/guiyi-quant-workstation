# P7-11 SF 四周期历史候选处理

状态：**BLOCKED / HOST_APPROVAL_BLOCKED，0/12 页面闭环**。宿主在真实生产 apply 进程启动前拒绝，未产生维护 attempt、行情下载或生产写入。此状态不是数据失败或安全暂缓；固定21品种分母和其余队列行保持，仅SF，未启动SM。

冻结 develop/源码 `9531a6352d6507269a1adf9d58edd13e10dbe798`，启动时本地与远端develop一致。native managed隔离工作区 `/Volumes/扩展盘/worktree/sf-minute-closeout/guiyi-quant-workstation` 为冻结detached HEAD，无产品源码、公式或正式配置修改；保留供同一计划恢复核对。原始证据/helper只保存在本机 `outputs/sf-minute-closeout-20260929/`，不提交行情、响应、图片、配置或秘密。

## 自身范围与执行前验证

窗口 `max(2023-01-01, SF产品权威起点2014-08-08)..2026-09-24`，as_of `2026-09-24T07:00:00.000001+00:00`。产品起点来自 `data/universe/product_window_starts.csv` 的 `rq_or_listing_start`，不是物理合约上市日；当前Catalog维护起点2023-01-01与产品上市事实分开。SF自身MDS/Map确定28个唯一rank1 owner，无重入；每个计算前缀从自身Contract.listed_date到owner-through，首单SF2303起于2022-03-15，不缩成页面窗口。

仅 `5m/15m/30m/60m × trend/oscillation/dual`，4输入、8基础、4融合、12页面；1m仅Canonical聚合来源。初盘112依赖中84 DATA_READY，28个5m依赖缺前缀；输入3/4完整。既有15m/30m/60m各有3个保存流，5m没有保存流。既有资产是否精确可复用须独立manifest/source/identity读回，不因存在就计为本轮完成。独立离线比对旧plan/report与本项fresh source摘要发现三个周期的source_evidence_sha256均不匹配；旧revision/seq摘要一致不能替代stored manifest和当前source逐字段证明。因此九旧资产本轮不计为exact reuse通过；差异原因仍待只读核实，不据此断言行情数值变化或公式缺陷。

SF自身历史Session只有09:00..10:15、10:30..11:30、13:30..15:00，前缀3306个Session记录未见夜盘或时段变化。夜盘/跨午夜/周末夜盘归属按SF事实N/A，不复制AG或NI；30m合法15分钟尾、60m合法15/30分钟尾遵循原生 `(start,end]`。Calendar/Session原生completed week读回为2026-09-24，9/25..27休市；该元数据结果不代替日周真实页面验收。

完整112份contract_warmup dry-run去重为 **0源请求、287个5m派生月目标、247950根预期派生Bar**，全目标仅SF，其他周期无目标。计划资源估算253900800 bytes，空间约774GB；供应商账户余量1001577411 bytes只作现场quota事实，不冒充实际下载消费或供应商字节上限。

SF2303/1m/2022-03真实2925根Bar经本项同盘scratch原生发布、严格读回，SHA与源文件一致；canonical schema SHA `679ce5bb0b71aad3cb60bd7dc3c60539b0e08bf6d00e667fd16c6767cb41434a`。先前读取尚未完整dry-run的scratch记录保留为 `preflight-partial-dryrun.json`，未用于apply；完整28owner final preflight单独PASS。scratch不保证所有后续派生文件可发布。

任务helper新增仅观察型publisher异常捕获，安全记录exact dataset/year/month及class/code/errno因果链后原样raise，不保留可能泄漏敏感信息的异常正文/traceback，不修改产品存储或事务语义。执行前独立scope Review通过。

## 宿主拒绝与停止边界

冻结campaign计划SHA `a38ec0e8be2692b0f1b2577c3c0aa75f61401f08b781171d21b55786f79d3f2b`。`campaign.py --apply --expected-plan-sha256 <该SHA>` 的宿主审批被拒绝，理由是当前可信用户消息未明确授权此次具体生产写入，代理交接记录不能代替可信授权。未原样重试、换工具绕过、改hash、缩窗或关闭控制；已在本聊天请求明确授权供正常复核。

拒绝发生在进程创建之前：`campaign-attempt.json` 与 `campaign/` 均不存在，真实维护未启动，零本项源行情请求、零Canonical/Catalog写入。独立只读host boundary读取证明28owner初始五频1400个Catalog月份/row_count/旧文件SHA全部保持：1m332、5m72、15m332、30m332、60m332；共享锁0。D1/W1当前332/304指纹已捕获，但初始inventory未含七频，所以不虚称日周前后比对通过。

NI/FU旧失败attempt、数据、工作区和证据未触碰；SF停止不证明它们的根因已解决。未启动API/Web/Chrome，无本项服务资源需要停止。未改正式分钟、main/tag/release、Runtime/worker/消费者/Scope/audience/通知/Broker/账户，`auto_order=false`保持。

## 实际只读验证与未完成项

使用现有quant-api venv，显式 `PYTHONPATH=<冻结树>/services/quant-api:<冻结树>/packages/quant-core:<冻结树>`，import guard防止editable误导入。私有配置只由现有loader加载；初次sandbox连接限制保留，host只读查询成功，不归类为SF数据缺陷。

- `inventory.py`、`dependencies.py`、`plan.py`、`review_metadata_readonly.py`：28owners/112依赖/9旧流、完整dry-run与自身metadata，零provider/生产写入。
- `quota_current.py`、`preflight.py`：final完整scope/quota/空间/锁与SF scratch PASS。
- `python -m pytest --confcutdir=outputs/sf-minute-closeout-20260929 outputs/sf-minute-closeout-20260929/test_scope.py -q -p no:cacheprovider`：**14 passed in 0.61s**（最终helper）。
- 冻结树 `python -m pytest services/quant-api/tests/data_foundation/test_aggregation.py services/quant-api/tests/data_foundation/test_historical_session_window.py services/quant-api/tests/newow/test_reference_interruptions.py -q -p no:cacheprovider`：**58 passed in 1.00s**。
- `aggregation_full_prefix.py` 分周期真实只读运行：15m/30m/60m各28owner、332月，分别90615/48328/30205根Bar从同物理Canonical1m原生逐字段重聚合一致；这项使用原生算法，不冒充独立算法验收。30m首次只读占锁 `SOURCE_BUSY` 保留，既有检查自然结束后fresh只读检查通过，无mutation attempt。
- `weekly_authority_readback.py`：7日Calendar、SF Session及原生completed week PASS。
- `review_host_boundary.py`：独立只读PASS，原五频1400文件/rows/pointers严格保持、attempt不存在、锁0。停止Review见 `independent-host-block-review.md`。

`matrix.json`固定12项HOST_APPROVAL_BLOCKED。287个5m目标发布、5m来源独立重聚合、12READY disabled资产精确完整绑定、API/真实Chrome十二组合、主图/副图/完整曲线/records/分页/切换/错误和pending取消恢复、SF自身日周六组合及逐图独立视觉Review均未完成，不借其他品种结果填补。prepared后续helper不是已执行结果。

本项未完成历史候选闭环；验收结论：**阻塞**。唯一最小下一步：取得本聊天可信明确授权后按宿主流程复核同一冻结计划，并在任何真实执行前fresh校验范围、前像、预算和锁；宿主拒绝解除前不启动mutation，不自启SM。
