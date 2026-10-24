# 两段原件缺口：独立历史补齐与采集恢复

Owner 选择：补齐独立历史行情和计算，保留原件缺失标记，同时修复采集故障；不宣称原件恢复。

## 已核对的边界

- 2026-10-22 21:01–21:57 的 45 品种、2,565 条自然 1m 原件无持久副本。通过统一 MDS 按物理合约和权威端点核对，独立 Canonical 历史 2,565/2,565 条齐全；原件缺失保持。证据：`output/gap-history-repair-20261024/coverage.json`。
- 2026-10-24 00:30 起的 11 品种、611 条 source/completed 原件缺失属于 **10 月 26 日交易日**。原生历史准入的 latest complete day 为 10 月 23 日；11 个精确 warmup 请求均拒绝 `CONTRACT_WARMUP_THROUGH_INCOMPLETE`。10 月 26 日 15:00 是权威最终 Session 边界，不保证该刻 provider 已完整。当前未请求或发布这 611 条历史数据。
- PG 与 Redis 于 10 月 24 日 00:29:21 正常结束（exit 0、无 OOM、RestartCount 0），00:29:32 同期启动，与缺口起点吻合；仅有协调停启证据，不能确证 Docker 引擎、VM 或人为触发。该十分钟无 Sleep/Wake 证据，触发主体仍 UNKNOWN。Feed/Live 故障状态不能解释成正常休市，也不能以当前无交易需求宣称采集故障消失。证据：`gap24-independent-container-restart.json`。

## 独立历史重算：部分执行，必须先读回

使用 v1.15.17 精确发布树和原生历史入口，计划 hash 为 `980ee0b60baec539fdff6fa11919dd7ba0f004021516fde7cb4bdda15bbce0af`，目标为原 240 路 H1 独立历史身份、各自原 since 至 10 月 23 日 15:00。正式 forward 原件、结果、游标和通知不在本次重算修改范围。

`history-gap-final-attempt004` 已完成前 84 路。第 85 路 NI 主升浪在 planner 阶段报 `DATASET_OR_PARTITION_MISSING`；085 目录无 native intent，未开始该路写入，整个调用器已停止。禁止直接复用该失败计划重跑。随后 84 路逐路独立新 lease、全 240 路旧不可变组、余 156 路前像、255 个旧 candidate、forward 和控制文件均核对通过。证据：`history-gap-84-independent-readback-20261024/completed.json`。不能将 84 个局部成功当作全任务完成。

剩余来源扫描发现 NI2612、PG2612、PS2612、SI2612 完整物理 H1 预热前缀缺口，共影响 12 路基础策略。使用原生显式 `60m` warmup（依赖仅 `1m`），从各合约上市日至 10 月 23 日完成 44 次真实 RQData 请求、44 个分钟分区和 44 个派生 H1 分区发布；四次均 passed、failed/blocked 0、后验计划零目标、旧文件哈希不变。执行文件 `history-prefix-h1-apply-20261024.py`、固定计划文件 hash `b089845951f35aab2a603571c6e29ca1b0edf9750a6bc471271a7a1491f1de05`，各自 attempt001 保留。独立 MDS 读取确认完整 H1 前缀 NI/PG/PS/SI 分别 1817/1358/1030/1030 根，12 路来源计划通过。未触及 D1/W1、Live 原件、通知或游标。

剩余 156 路使用新计划 `f18251ba90bae41ccd5364aded372e07d6ef2e0d290ee418dc51190a3a148614` 和 attempt005，排除已成功 84 路，已全部完成。完整旧组扫描覆盖 1,327,446 行、16,561,355,953 字节；旧不可变事实、255 个 candidate、成功 84 路、forward 和控制文件均保持。既有周审计于 10:15 完成，60/60 passed、发现 0。首轮只读验收 180 路后因脚本将 checkpoint 误写为 token 停止；修正、独立合同测试后使用新 -002 目录重新完整读回，240/240 新 lease 来源及融合依赖通过，原失败证据保留。随后精确替代 180 个已满足 H1 控制项，旧 raw control 保存，保留 D1/W1、游标和全部旧失败；journal/DB 写入均 0。证据：`history-gap-all240-independent-readback-20261024-002/completed.json`、`history-control-supersession-attempt001/verified.json`。

## 采集恢复：技术阻塞，未切换

任务内准备了独立的 typed interruption 路径，明确旧缓冲为 UNKNOWN、原件 NOT_RESTORED，普通 Feed 正常排空验证保持不变。最终编排 97 个离线测试通过，控制项替代工具 10 个真实 main 隔离故障用例通过，不代表生产恢复完成。

现网 NAT 不保留可核验的客户端端口映射，故障 PID 的旧服务端连接无法精确归属；稳定快照和 CLOSED 主机 socket 尚不足以证明未知提交终结。不能为此终止无关开发连接。旧草案拒绝执行的记录保留；新草案使用可回退的健康服务准备阶段：只正常排空并停止四个明确的本项目健康服务，故障 Feed/Live 暂不触及；同 Redis 实例全部非维护 client 自然消失才允许暂停故障进程，再复核空集并终结。PG 原生维护 lease 在处置前持有，覆盖 metadata 写事务。若连接仍在，恢复精确 gen22 健康服务，Reference 保留原 token、以新 PID 独立验收；任何 effect 结果未知立即停止，不自动回退。新草案已完成独立审查和故障注入，尚未生成现场计划或停服务、切换 Runtime。

不能用 `SCRIPT FLUSH` 代替屏障：exact v16 source/completed 路径使用携带脚本全文的 `EVAL`，缓存清空无法阻止旧排队命令执行。未执行 flush。详见 `output/data-three-repair-20261023/interrupted-cold-v11517/REVIEW.md`。

后续只在精确源缺口修复、部分结果独立读回及未知提交终结证明通过后继续。保留旧失败和缺口，不造数、缩窗、改游标、重放或补发通知；不新增定时任务。

恢复现场计划首次仅在 immutable_inventory 全表聚合只读统计超时退出，未生成 plan、未创建 apply attempt、未停服务。分批统计修正待独立验证，不能据此宣称采集恢复。

分页版保留整表 180 秒累计预算后，现场只读扫描仍超时；两次均未生成 plan、未发生服务变更。已证明旧规模超过 130 万行/16.5GB，正复核有界 900 秒表级预算、单条 180 秒及 14:00 硬截止的适配，不跳过完整事实保护。

Runtime 新 002 计划 `942bf2a6e04b577cf1da29da97271836c2b2f540cf3a40a506924ff5611d29ed` 经 112 测试/独立审查后执行。完整六表前像已哈希保存（1,496,254 行、98,970,213,267 字节），主表 720 秒；Alert/API/Web 原生 drain 成功，首个 Alert stop 因即时标签读回迟滞报 `FAULT_RECOVERY_LABEL_STILL_LOADED` 停止。独立后验确认 Alert99063 已退出、标签 absent；API52250/Web52258 仍在原 token 下 parked，Reference27877 原 token 未变，Feed54197/Live29804 未处置，正式仍 gen22。旧 attempt 禁重试；正在准备精确恢复本次三个健康服务，不触及 Reference 或故障进程。

002 后续已用独立 `healthy-restore-002` 精确恢复 Alert/API/Web，仅取消本次三个 token；Reference 原 token 保留。003新计划060eb149…执行首轮全部旧事实SHA通过、四健康服务退出、Redis空集与PG屏障通过，fault两PID精确SIGSTOP。随后只读old-PK全列表分页扫描超900秒停止，session62428真实exit1，无kill intent/commit。独立读回 `suspended-no-kill-independent-readback.json` 证明四healthy标签absent、fault原birth/kernel status4、PG锁空、Redis非维护连接0。该attempt禁止重跑，需从SUSPENDED_NO_KILL新状态续接，不能把暂停当作退出或恢复完成。

Owner 10/24 进一步交办：正式历史只用盘后Canonical，来源冲突按已通过质量验证的盘后数据重算；不再双正式历史展示。正在收敛读取及Web入口，旧不可变审计不物理删除；源未就绪/质量/身份错误继续显式阻断。

## 004续接完成（2026-10-24 14:44 CST）

新精确计划59a5c53d48e704522c1eb18b6a8c0d03a249e4fc61de4d47b660dd57085bfb43执行成功，旧四健康服务与两暂停故障服务的已知状态经独立校验后单次续接；两旧故障PID仅一次终止/卸载，全10安装与registry CAS后启动v1.15.18/gen23。六轮逐旧PK/行哈希、长度及完整汇总核对通过（1,496,254行、98,970,213,267源字节）；日志、索引、原游标保留，Reference原生追尾。独立检查发布树/六PID/十binding及loaded配置一致，OS维护锁空闲，PG维护锁持有者0。无原件伪造、游标修改、replay或补发；旧失败全部保留。

120个10/21短期恢复metadata已缺失，按精确清单projection处理，标记EXPECTED_EPHEMERAL_METADATA_ABSENCE_POSSIBLE_TTL；旧DUMP哈希保留，单键到期时间未证明，不能称已证明TTL。保留source/journal/index在15:00:03.266自然过期前完成完整读回；没有延长TTL。

证据：`output/data-three-repair-20261023/suspended-continuation-004/attempt-1/completed.json`及`final-runtime-readback/{identity-001,pg-lock-001}.json`。服务恢复不等于新自然采集/Event/Push验收。旧2565的Canonical替代和240H1已通过；611仍待10/26交易日完成。正式历史API入口已切换，NewowJM60m/D1已返回保存历史，苏冰NOT_BUILT需继续补齐，第一项整体完成仍保留待验。
