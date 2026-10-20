# 10/19 健康接口性能修复与自然链路核验

范围：健康接口超时修复、今天自然行情及Event/提醒只读核验。不重放、不补cursor、不补发、不新增通知受众或任务。

## 已验证的代码修复

原生v11的cProfile共44.3秒，JSON raw_decode约24.9秒；健康汇总加载完整ReferenceBatch，包含健康未用的checkpoint、历史source evidence、manifest和projection载荷。只减少ORM字段仍约39.8秒；最终改用SQL标量投影，calculation仅取presentation_v1，seed仅取pending key存在标志，typed诊断保留完整source_evidence/hash等原校验输入。JSON null仍按key存在处理；不改公式、行情入口、Scope、状态优先级或交易/收益语义。

新增回归先RED（查询checkpoint_text），最终GREEN。develop源码4619db48e；独立Review未发现Confirmed Issue。实际验证：

- pytest -q：test_reference_runtime_health.py、test_original_conflict.py、test_recording_history_audit.py、test_forward_query.py、test_runtime_health.py：161 passed、1 skipped。
- 同一生产REPEATABLE READ READ ONLY快照、同一now、旧新完整dict相等：40.4695秒→6.5252秒，SHA256 7e536a80c98c272ea20987d62ceee6b438ecfb2fe49816c826ec8564ba51d15c。
- 独立单次profile7.009秒、完整返回；临时loopback真实FastAPI路由HTTP200/7.036秒，720 enabled、684 READY/36 OBSERVATION_LAGGING、pending Capture0。临时server已关闭，此证据不是正式8000已修复证明。
- Ruff、secret_scan（finding0）、git diff --check通过。

全部只读实测与原始失败日志保存在output/health-timeout-20261019。前两次candidate profile完成health后，空cProfile Stats报告抛TypeError，原始失败保留；修正脚本后第三次完整成功，不将报告失败误报为生产写入失败。

从main隔离准备v1.15.12候选.worktrees/health-timeout-v11512@4be0a70dc，仅本修复及单一版本源；独立venv/锁检查、候选177 passed/1 skipped、pnpm frozen离线安装、Web build/type/topology通过。后续PR460已合并，v1.15.12正式发布于09:45:02Z，main/tag peeled13c86b7351b8977b8bca96e17feb2399f181a159、annotated object899ad7a2f533e7b21e052e96df9ad02cef35aaac，非draft/prerelease；与已验证候选完整tree相等。exact正式树独立venv/锁定依赖/Web build/type/topology通过。当时尚未切换正式服务；最终切换见下文。合同只读比较：db/live/input/formula/launcher相等，reference指纹改变；现有原生部署合同禁止混合顺序交接，须独立准备冷切换，而不能修改已发布v11源码冒充已上线。

## 自然链路核验结果

17:25–17:30北京时间只读取证：Live60品种闭市、末根15:00、coverage ok，source/Live cursor在tail，Alert今日completed cursor在tail。今天249 Event均有source ID及handover_buffer来源：HTDY21（12 provider accepted且provider reference均非空、1 FAILED_OR_UNKNOWN、8 EXPIRED_NO_SEND）；SuBing228（183静默、45过期）。逐条来源核验另证实249个独立source ID经identity HGET→exact XRANGE→原生ObservationEnvelope/trigger解析，合约/周期/Bar时间/交易日/来源观察时间全部一致（含12 accepted），无失败；只保存摘要hash，不dump原始payload。这些是Event条数，不是通知批次或收件人数。12 provider accepted不证明手机实际收到；无手机ack；失败/未知/过期不补发。

当前运行未通过完整连续性核验：Reference今日cursor有效但落后，旧16日completed journal27040条仍存活、两个旧cursor缺失；Reference owner明确OBSERVATION_CURSOR_MISSING/stream_subscribe。样本PTTL约2424秒，保留原TTL，不重造cursor、不主动重启。Alert与Reference均在更换PID；Alert公开错误type ValueError，原始固定码CLI_INTERNAL_ERROR。421项coverage均无last_evaluated（361lagging/60waiting_canonical）；coverage是进程内状态，重启首项前写空heartbeat，不能把今天持久化处理/Event事实和空coverage混为一谈。随后24秒GET-only采样两轮实证：各PID均完成110评估/10warming，进入get_message读取旧日后退出并换PID；原生cursor只读抛OBSERVATION_CURSOR_MISSING(ValueError)，与运行顺序和日志闭合。Alert与Reference已定位为同一旧日cursor缺失阻断，非coverage更新算法故障。首A日/周纯评估及真实status纯内存记录均通过。

## 18:05后自然读回与切换准备

旧16日journal于18:08:58自然TTL消失，未删除或补cursor；随后Alert/Reference自然恢复为稳定新PID，今日三个消费cursor均真tail。18:05自然盘后主更新18:05:05–18:08:08，60品种passed、720分区发布、Live cleanup通过；后续consumer audit自然结束，18:26四calendar实际idle。没有重跑主任务或制造completed Bar。18:34最新Alert处理状态ok、持久化末根仍15:00/成功15:00:41；进程内421项coverage为108 ok、301 unverified、12 evaluation_failed。因此旧226 lagging/75 pending不能直接宣称已消退：日间持久化处理/Event存在，重启后的分钟coverage须新自然观察验证，不补回放。

自然读回另发现真实未通过项：PR2612 D1历史39根OHLC为0，SF2701 D1历史1根为0，Alert完整窗口拒绝MARKET_READ_WINDOW_INCOMPLETE；保留已有10项物理段warming不足。新Canonical与已捕获历史观察内容核对产生REFERENCE_CANONICAL_MISMATCH，动态health可见DATA_CONFLICT；静态stream.health=READY不能替代完整health。第二次同一只读快照旧/新完整health相等，47.1845秒→7.7206秒，当时644 READY/76 DATA_CONFLICT、pending0，SHA 9bcdd8c8875af33eaa2febc8bba5e7aa1881031671ba74a4fc0f4a1a4cab05d1；不将该动态冲突数量硬编码为以后结果。

两次只读计划前检查均在任何effect前停止，未写plan：001为旧owner瞬时scan，增加同PID真实cycle的90秒只读等待后149测试和独立Review通过；002为运行中自然DB对账写入。双只读全DB摘要实证18:32:33–18:33:17仅active_forward_reference_capture_reconciliations从1374增至1382（+8），其他表相等，与原生8条/60秒预算一致。记录原失败，未盲重试mutation。

独立Review确认冷切换的一致性边界应位于原生合作drain完成、六owner真实park并持有所有writer/部署/盘后/PG维护锁之后；允许原owner在停止领取前正常收尾，不要求运行中全DB静止。当时拟定封存后的完整DB、输入与health保持；后续证据证明启动后须分别核验原生历史进度和reconciliation合法追加，最终边界见下文；保留全部原有DATA_CONFLICT，不以补数据、清冲突、重放或差异白名单便利上线。这是当时准备阶段的检查点；最终实现与切换见下文。手机实际送达无ACK，新v12自然Event尚未发生，不声明RUNTIME_READY。


## 第二轮校验边界与现场执行

第一轮drain仅Feed请求已提交并park，随后reference_streams/revisions摘要差异使流程停止；无stop/install/start，无迁移。独立Review后，用精确token原生cancel恢复原Feed PID46458，新鲜闭市业务心跳、输入与原失败日志保持；不重跑原attempt。

19:00–19:01两次按PK/列只读核对及原生身份分类证实：仅一个disabled historical_replay历史资产的latest_seq/row_version及对应revision的last_seq/checkpoint_batch_id/dependency_digest变化，现役forward变化为0；属于HistoricalRefresh正常checkpoint提交（repository.py809–815）。新attempt002只允许派生历史身份同active revision的这5列单调推进，新增calculation须seq/expected_seq/statehash/through和native dependency append证据连续；所有其他metadata/PK/active_revision_id/公式/Scope/现役forward与通知事实仍保护。旧历史事实校验范围是原生已提交payload身份及选定链字段，不宣称78GB历史大字段逐字审计。

机械停写到首start之前持全部writer/PG锁并严格封存；启动后正常历史推进和reconciliation合法追加分别取证，同一生产RR/READ ONLY快照比较旧/新health完整dict，真实HTTP采用新鲜health与recon前后SHA稳定窗口，最多3次只读重采，不重播effect。旧失败caller的20个Python文件及原plan/日志保持冻结。

新caller与NEW-only最终读回212项测试通过、独立Review通过；NULL seed排序及snapshot终点上界回归已覆盖；旧摘要无损压缩，005真实预算为plan约4.61MB、sealed保守7.48MB，均低于8MiB。新精确plan e73a64955efa00ab7a90c15e0fbb0dd18a902386d11e38acd85aca9d9505d073已生成，执行证据位于output/release-v11512-20261019-attempt002。随后完成正式切换及独立验收，结果见下文。

## 正式切换及独立验收

attempt002 drain六个旧owner合作park后封存，stop十项disable/bootout、install exact v12/gen21配置及绑定、start六常驻/四日历各一次committed；schema仍20261015_0052，无migration。原start最后即时采样DELIVERY_SWITCH_FINAL_OWNER_NOT_FRESH，保留stopped_no_retry，未重跑任何启动effect。

独立verify_new_runtime_readonly.py --read-only实际exit0，new-runtime-acceptance-001/complete.json为RUNTIME_SWITCH_VERIFIED_READBACK。六PID两轮一致：live5519、alert5525、reference-worker5532、api5541、web5548、market-feed5840；四calendar空闲，API/Web版本1.15.12，Runtime identity matched，dist一致。完整旧/新health在同一RR/RO快照相等，43.3975秒→7.7360秒；正式Reference HTTP200/8.5842秒，与独立新鲜health稳定窗口逐字一致。720 enabled、540 READY/180 DATA_CONFLICT、pending0；保留真实degraded。独立Review核对产物与sealed来源通过，未新增生产读写。相对sealed合法reconciliation追加56、5条历史stream各追加一个批次，旧行/受保护事实保持；该证据不表示全部数据库静止，也不表示新v12自然Event或手机送达。

旧目录清理plan在任何归档/删除前因RETENTION_DB_IMPORTED_BEFORE_PRIVATE_SETTINGS停止，retirement-plan-command-001.log原样保留。原因是private_settings模块间接提前导入数据库Session；冻结caller不修改，独立新cleanup caller修正导入顺序并补真实导入回归后继续。此时未删除旧v11目录。

新清理caller在output/release-v11512-retirement-20261019-attempt001，51项测试通过（含真实native传递导入及Engine do_connect禁止连接回归），独立Review通过。先安全加载私有环境，再允许native import，并比对实际Session创建使用的normalized URL；不删除前置拒绝检查。冻结cold2 SHA保持。NEW-only收尾采用v3，同一bootstrap，无OLD运行树导入依赖。清理计划22b3df2a916e4d991ce9a870da09818b15c559d5684434c6d23f718a579611bd已实际生成，唯一eligible root为旧v11，精确运行源manifest9项；归档/删除结果待下文。

新清理attempt001的plan通过后，archive在写归档和删除前因RETENTION_CURRENT_OWNER_NOT_READY停止；单次owner就绪采样不能覆盖周期性scan瞬时状态。原plan/code/日志冻结，后续独立attempt采用固定验收PID/身份、90秒有界等候新鲜ready；换PID或超时仍拒绝。此失败不涉及归档结果未知或删除重试。

最终清理caller为output/release-v11512-retirement-20261019-attempt002，45项定向回归通过（5项覆盖轮询暂态、超时、读前/读后PID变化及Reference同PID健康scan合同），独立Review通过。保留原ready_owner新鲜度/身份/状态规则；新plan 775b4b8cf6fe7c5379ec7f72ed12e67cb03763f3e7791c5dd5a192acf4725116实际通过，唯一目标仍旧v11，当前归档进行中。

## 旧运行目录清理结果

最终精确plan/archive/apply均实际exit0。归档文件0600，SHA256 90909d269fbd71e3e2c2e209024e40fe2155a005b9405cc6c3a9892e2d634729，原生零引用与exact旧identity、源manifest/内容、归档成员、当前DB边界和同PID就绪均复核通过；apply两轮gate后非force移除.worktrees/release-v1.15.11，complete.json为COMPLETE、local_formal_release_trees=1。保留v1.15.12、Git tag/Release历史、Canonical/DB及完整失败证据；没有迁移、通知补发、Scope变化或交易。清理时Reference仍540 READY/180 DATA_CONFLICT/pending0，冲突未被删除或掩盖。源运行证据可由受保护归档恢复，源码可按旧annotated tag重建；恢复运行本身须按exact部署合同，不直接复制历史status冒充自然证据。

最后只读读回采用NEW-only final_new_only_readback_v3.py --read-only，独占输出final-new-only-readback-003.json；不再运行依赖OLD目录的caller。

最终NEW-only只读命令实际exit0，final-new-only-readback-003.json为NEW_ONLY_FINAL_READBACK_VERIFIED（2026-10-19约20:12北京时间）：唯一registered/physical正式发布树v1.15.12，旧v11 absent，六PID与原独立验收双轮一致，四calendar idle。API/Web health均200/version1.15.12，Runtime identity matched，Web index与dist一致；Reference直连200/8.404012秒、Web代理200/8.964748秒，各自与原生新鲜health完整相等并有reconciliation稳定窗口。当前720 enabled、540 READY/180 DATA_CONFLICT、pending0，继续显式degraded，不宣称RUNTIME_READY。两项交办已完成；新v12自然completed Bar/Event、历史零值/预热不足与手机实际送达不由本次接口验收代替。

实际新增验证入口：
- services/quant-api/.venv/bin/python -m pytest -q output/release-v11512-20261019-attempt002 output/health-timeout-20261019/test_final_new_only_readback_v2.py：212 passed。
- 私有配置真实导入与NEW-only v3相关回归：51 passed；最终cleanup002定向回归：45 passed。独立Review均通过。
- retirement002 plan / archive / apply：exit0，精确计划及归档/删除receipt保留于对应output目录。
- .worktrees/release-v1.15.12/services/quant-api/.venv/bin/python output/health-timeout-20261019/final_new_only_readback_v3.py --read-only：exit0，NEW_ONLY_FINAL_READBACK_VERIFIED。
