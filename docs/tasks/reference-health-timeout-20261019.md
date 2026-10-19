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

从main隔离准备v1.15.12候选.worktrees/health-timeout-v11512@4be0a70dc，仅本修复及单一版本源；独立venv/锁检查、候选177 passed/1 skipped、pnpm frozen离线安装、Web build/type/topology通过。尚未创建tag/Release或切换正式服务。合同只读比较：db/live/input/formula/launcher相等，reference指纹改变；现有原生部署合同禁止混合顺序交接，须独立准备冷切换，而不能修改已发布v11源码冒充已上线。

## 自然链路核验结果

17:25–17:30北京时间只读取证：Live60品种闭市、末根15:00、coverage ok，source/Live cursor在tail，Alert今日completed cursor在tail。今天249 Event均有source ID及handover_buffer来源：HTDY21（12 provider accepted且provider reference均非空、1 FAILED_OR_UNKNOWN、8 EXPIRED_NO_SEND）；SuBing228（183静默、45过期）。这些是Event条数，不是通知批次或收件人数。12 provider accepted不证明手机实际收到；无手机ack；失败/未知/过期不补发。

当前运行未通过完整连续性核验：Reference今日cursor有效但落后，旧16日completed journal27040条仍存活、两个旧cursor缺失；Reference owner明确OBSERVATION_CURSOR_MISSING/stream_subscribe。样本PTTL约2424秒，保留原TTL，不重造cursor、不主动重启。Alert与Reference均在更换PID；Alert公开错误type ValueError，原始固定码CLI_INTERNAL_ERROR。421项coverage均无last_evaluated（361lagging/60waiting_canonical）；coverage是进程内状态，重启首项前写空heartbeat，不能把今天持久化处理/Event事实和空coverage混为一谈。随后24秒GET-only采样两轮实证：各PID均完成110评估/10warming，进入get_message读取旧日后退出并换PID；原生cursor只读抛OBSERVATION_CURSOR_MISSING(ValueError)，与运行顺序和日志闭合。Alert与Reference已定位为同一旧日cursor缺失阻断，非coverage更新算法故障。首A日/周纯评估及真实status纯内存记录均通过。

## 尚未完成

正式8000的健康修复上线未完成；现役仍v1.15.11。自然首日处理与事件存在已核验，但进程稳定性、Reference追平、coverage恢复、手机送达未通过。保持EXTERNAL_GATE_PENDING，不声明RUNTIME_READY。最小下一步为旧journal原TTL到期及18:05盘后自然结束后的现场读回，若启动仍失败则继续定位真实ValueError；不得为上线跳过原生兼容/运行校验。
