# 10月13日盘中故障修复与补丁发布

Owner交办：按影响顺序修复收盘审计问题，全部修复后发布一个版本；授权覆盖必要精确数据恢复、生产读回、发布和运行切换。范围保持60品种、既有规则/收件人，苏冰外部推送关闭、auto_order=false。

基线develop aa3896e0840694fff17ca3abd211d67a060c83a5；现役v1.15.5 dc32c020d328ab81d4d65a959603f4ab66965f52/gen18。

- [ ] Reference：真实冲突保留，明确隔离故障品种/周期；每观察持久终止事实才能ack，未知提交继续阻塞；恢复采用独立明确中断边界，禁止跨旧参考链配对。
- [ ] SA：定位10:12缺口与恢复失败根因，修复稳定诊断及安全恢复；原Source/Completed及首次时间不改写，恢复数据不冒充自然观察，预算与失败attempt不删除。
- [ ] Alert：固定30秒有效期，减少重复权威读取/计算，验证同轮多品种延迟；不补发过期信号、不改变公式。日周coverage基于当前身份/输入证明，质量事实不造正常价。
- [ ] Web：首页价格与策略摘要独立可用，读取有界且可取消；展示真实滞后/冲突/不可用，无第二行情resolver。
- [ ] 运行诊断：总health纳入Reference，稳定公开错误码代替unclassified；日历not_due/休市正常区别实际缺口。
- [ ] 定向回归、相关集成、Web类型/build、lint/type、secret、diff及独立高风险Review。
- [ ] 精确补丁main/tag/Release与正式运行切换，保护原journal/Scope/receipt/发送事实；冷启动独立readback。

修复、发布、身份切换与新版本自然业务验收分别记录。未知提交停止相应mutation并只读核对；不放宽质量、时序、维护锁或幂等校验。必要恢复前冻结精确对象、前像、预算、hash与恢复办法，串行生产操作。

## 当前取证与验证（尚未发布）

SA一次性精确provider诊断已真实完成（1次、SA2701、2026-10-13、1m），捕获345行；
10:12 total_turnover=-916520、volume=588。源码严格拒绝RQDATA_TURNOVER_INVALID，原Source/Completed此分钟不存在。
不改成0、不伪造金额、不删除旧预算；当时提出是否采用字段级不可用合同的决策，后续现场事实已消除该取舍。
证据在主工作区output/runtime-intraday-repair-20261013/sa-provider-{attempt,response,outcome}-001.json。

自然盘后任务2026-10-13 18:05:05→18:07:22第一次执行passed，覆盖原60品种并实际cleanup bars=0/subscription=false。
正式MDS只读读回SA2701 10:12分钟，成交额0、volume588；独立新attempt002仅一次provider查询确认原始
total_turnover已由源自行更新为0（无本地金额填值），与正式Canonical一致。保留严格质量校验，未修改任何金额语义。
盘中原始Live缺口/失败budget仍是历史事实，不补发旧信号。SA数据口径选择已不再需要owner答复。

60品种10:00小时输入纯评估同hash/同策略结果：旧cold16.810785s/warm16.462727s；
候选cold12.089472s/warm11.662910s。此测量未包含完整到达批次、同向分析或Event/transport，不能称实时30秒验收通过；
正在补完整原始顺序批次测量，禁止补发或改变有效期。

完整300条整点producer顺序输入SHA d5b4a32f52aa7c13a88e7e17b373dd3af693acd1060b9a4cc85860745424b41b：
旧cold85.582104s/warm86.337394s；共享window候选cold74.171825s/warm73.372481s；
追加facts缓存cold73.506777s/warm74.329910s。300条两轮outputs与旧实现逐项一致，
但耗时仍超过30秒有效期，延迟修复尚未验收；正在profile真实热点。

Reference发布前输入诊断（2026-10-13 16:55，生产只读）：固定60条D1/W1源读取，
原24条MAPPED_CONTRACT_DATASET_MISSING现全部no_input，正确等待当天Canonical发布。
Reference定向145 passed/5 skipped；隔离、恢复新revision和发布窗口正进行独立Review，未执行生产恢复。
恢复historical源现场扫描发现14条历史OPEN和SF/SM6条已invalid旧revision；不得绕过_source检查。

Root定向命令均使用主工作区services/quant-api/.venv/bin/python及task的PYTHONPATH：
- live_recovery + queue + concurrency：78 passed / 32隔离Redis未配置skip。
- deployment_identity + runtime_scheduled：33 passed；补齐log-rotate合法idle身份校验。
- live_recovery_guard：10 passed；测试显式使用隔离目录，生产共享锁规则不变。
- root修改Ruff、git diff --check、secret_scan均通过。

## 收尾验证补充（20:00 前，生产恢复仍未执行）

候选APP_VERSION=1.15.6；独立Review已通过 Reference/Web/CLOSED_CLEANED及部署准备，
最新增量suffix和真实恢复caller待独审。正式版本仍v1.15.5/gen18，不提前声明已发布或Runtime ready。

- 真实隔离Redis恢复/队列/并发/guard：120 passed；CLOSED_CLEANED独立47 passed。
- 真实隔离PostgreSQL冲突提交/新段恢复：7 passed，独立schema，不写生产。
- 首页定向35 passed，版本一致性1 passed；Web类型/build/topology通过，uv lock --check --offline通过。
- Canonical历史计算测量：240条同输入，baseline 88.196786/84.524775秒；
  候选充分预热后的原读取43.594853/43.719377秒，新suffix29.325923/28.539880秒。
  两轮240条输出逐项相等（只排除耗时），未生成Event/通知、无provider/生产写入。
  这不是自然Live突发批次或收件人30秒验收；原300条Live证据仍保留，盘后Live已清理。
- 两个不可变输入缓存各200000 Bars/128条，合计最坏400000个不同Bars；
  alignment缓存只保留384组输入digest和解释facts，不保留Bars，不缓存错误。

生产恢复限定10品种60m×四策略，历史Source重建30base+10fusion；
旧69次冲突及参考交易完整保留，新forward段空仓、未来21:00开始、不继承旧OPEN。
实际执行必须持真实PG维护锁和既有OS/owner锁、精确park token、
当前CLOSED/自然清理证明、逐副作用持久intent及独立readback；20:55 expiry，未知不重试。

Root最后联合回归实际完成：1613 passed / 3 skipped，480.28秒；命令为主venv
`python -m pytest -q -p no:cacheprovider --tb=short`，task PYTHONPATH，
显式隔离Redis端口16393与隔离PG15463/guiyi_reference_isolated_test，
覆盖Reference全目录、Catalog/Storage/CLOSED_CLEANED/Feed/Live recovery/队列/并发、
Alert Runtime/Evaluator/Readiness/MarketRead/health/identity/guard/alignment、Newow reader/home cards。
3项既有可选隔离项跳过，不把skip计为通过；新增7项真实PG冲突测试已另实际通过。
Web35项及home_cards16项复验、版本一致性1项通过；
Mypy11个Alert/数据Runtime source + 9个API/Reference/identity source通过
（--follow-imports=silent --ignore-missing-imports，不称全仓类型检查）。
Ruff实际生产改动通过、秘密扫描0 findings、OpenSpec 11/11、diff check通过。

独立高风险Review最终：suffix406项复验通过，MDS SHA3fa3a3bea81b；无Confirmed Issue，允许此范围集成。API类型标注/cast复核为纯类型变化。Reference/Web/CLOSED_CLEANED此前已独审通过。实际恢复caller独审仍单独待验，不以工程Review代替真实恢复。

补丁release branch基于精确v1.15.5，工程commit64fdaa024只移植本轮60文件；
全部改动生产代码前像与v1.15.5相同，STATUS按正式基线保留历史并加入本轮证据，不带develop无关研究功能。
精确补丁树543项定向复验通过（含实际隔离Redis/PG），Web35项、type/build/topology、
uv lock离线校验通过；真实恢复caller及发布/切换仍分别待验。
