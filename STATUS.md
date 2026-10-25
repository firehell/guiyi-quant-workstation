# 当前状态

本页保留最新已记录的交付、运行身份与未关闭事项；**本次精简没有重新探测生产现场**。
历史发布、失败 attempt、数据修复和候选验收原件继续保留于 `docs/releases/`、`docs/tasks/`、
`docs/research/` 与原 output/outputs。旧版状态正文可从 Git `3bc2db867:STATUS.md` 追溯，
不将旧检查点的“未发布”“下一品种”或旧 PID 当作当前状态。
产品与能力见 [PROJECT_SOURCE](PROJECT_SOURCE.md)，合同和验证见 [架构](docs/ARCHITECTURE.md)、
[TESTING](TESTING.md)。开发完成、发布、Runtime 切换与自然业务验收分别成立。

## 10/25 第六步首页模拟交易监控工程完成，真实账户数据待验

CODE_COMPLETE / TEST_COMPLETE / REVIEW_COMPLETE：首页第三Tab“模拟交易”及详情共用返回、
原生权益与可证明净收益曲线、持仓/执行链/待核、筛选分页、手机全屏明细完成。
可见时5秒读取，隐藏/卸载暂停；翻页或明细期间仅提示新快照，迟到请求不得污染新筛选/账户。
复用现有财务/预留口径，跨日现金流无法证明时净收益断开；异常持仓保留实际数量并撤下完整预算声明。

单一显式根及私有原子索引绑定账户/来源/运行阶段，API仅SQLite只读，不构造执行Store、
不连接Broker、不恢复或创建账本；WAL在连接前拒绝以避免只读SQLite创建sidecar。
宿主监控发布异常已注入实测，不影响受控执行且监控状态明确unavailable；账户未知不当零资金或空仓。
GUIYI_SIMNOW_MONITOR_ROOT仅为API选取既有宿主固定根，不改变宿主输出位置。

实际验证：后端/账户/执行199 passed；Web单测1231 passed/3 skipped（含新9项）；
原生SDK结构无网络smoke8 passed；类型检查/构建、Ruff、secret scan0、独立高风险Review通过。
新增监控4项和相关首页导航/视觉31项浏览器回归合计35 passed，覆盖桌面/375手机及共享首页1280/1440/1920/2560/390。
扩展40项首轮10失败：5张导航截图随第三Tab更新后通过；另5个旧选择器失败在未修改HEAD归档同样复现
（旧micro图标、已移除刷新按钮、已移除快照summary），未修改其无关行为，不宣称整套旧E2E全绿。

本地开发页面5176/API8003独立启动，真实GET读回not_connected及全部金额null，浏览器已核验空态。
未修改既有5175/8002或正式服务；主develop工作区其他消息任务修改保留，不覆盖同步。
本次仅开发集成，不发布/切Runtime、不启用持续交易、不新增后台采集/推送；第一套原生资金10万元
20261027生效、自然输入与真实受控订单仍待独立现场验收。监控截图fixture不是真实账户绩效。

## 10/25 SimNow前五步工程闭环完成，真实账户与订单仍待现场验收

按owner要求完成：原生账户对账、实际费用与账户收益、真实执行输入、一次性受控入口、故障验证及独立Review。
`inventory/finance/evidence/host`复用既有两轮只读协议，核验资金/今昨仓/委托/成交并映射Readback；对锁、超一手、外部未知事实、有保证金无仓或冻结无挂单明确阻断。
实际费用仅在同日稳定非重叠快照间唯一一笔新成交、原生Commission差额及订单身份可证明时归属；多笔/跨日不猜。收益以原生权益和实际现金流调整，跨日连续性不足时净收益保持待核。

新增一次性 `scripts/broker/simnow_controlled.py` 与原生gateway：默认只读preflight，显式execute才限定一品种、每单一手、10..3600秒及1..3次submit。
首次initialize须实际第一套10万元空账户、无委托/冻结且交易日>=20261027；重开接管不覆写旧账本。结算确认仅execute且先通过前置检查后发生。
owner明确批准SimNow盘口仅供执行，Calendar/Session/主力及策略行情仍共用RQData链；自然新完成60m原件、startup/恢复隔离、不补历史信号。

修复实际接线暴露的边界：源回读完成与激活时间分离但必须仍在有效期；正常FILLED等待核验不丢反手目标；已知迟到成交即使缺费用也先重新锁定预留；从未领取发送claim的本地提案可在账户writer内记LOCAL_ABORTED，已领取或未知禁止该路径。
退出先注销/释放原生回调、消费尾部事实再关闭journal；报告逐单、预留、成交、持仓完整性和平仓义务，未知/缺费/未核清非0退出，不能将空列表当空账户。

完整定向212 passed，隔离真实Mac SDK gateway8项、原只读32项通过（共252）；SDK请求结构smoke、同ABI隔离SDK/API依赖实际导入均无网络通过。
Ruff/secret scan0/diff通过；独立高风险Review已关闭退出分类等问题并完成最终聚焦复核，允许集成develop。
CODE_COMPLETE / TEST_COMPLETE / REVIEW_COMPLETE；真实第一套、10万元生效、自然输入和原生报撤单分别EXTERNAL_GATE_PENDING。
本次未读取实际凭据、未创建原生交易API实例、未真实报撤单、未发布/切Runtime，auto_order=false保持；没有持续自动交易或监控UI。
唯一下一步是在实际服务时段运行默认只读preflight并读回结果，再按真实事实推进有界柜台验收。合同见[SIMNOW_EXECUTION](docs/SIMNOW_EXECUTION.md)。


## 10/25 Web参考交易面板按周期显示（develop，未发布）

按owner要求，HTDY仅60m显示参考交易，苏冰仅15m/30m/60m/1d显示；其余周期不渲染参考面板、说明或不支持占位，也不查询参考流。图表与独立Event审计保留，不改Scope、信号、推送或参考交易后端能力。共同显示规则由单一Web策略函数管理。

最新develop集成后Web单测1222 passed/3 skipped、浏览器21 passed（含苏冰各周期及15→5→30切换）、显示矩阵3 passed，typecheck/build/topology、OpenSpec12/12、secret0、diff及自审通过。CODE_COMPLETE / TEST_COMPLETE；尚未发布或切Runtime，正式API/Web仍按下节记录的v1.16.2。

## 10/25 HTDY实时信号统一60分钟，v1.16.2已发布并切换API/Web

按owner批准计划，通过既有Scope API关闭JM5m/15m并开启60m，逐次及最终独立读回：operational60品种均且仅60m（60组合）。JM旧5m/15m Event及发送字段前后相等，无补发、回填或周期转换。

HTDY仅60m查询/显示实时Event及已有参考交易流；其他周期保留历史研究图表并提示统一60m。未新增参考交易流，不将Event冒充开平仓成交。develop已集成3bc2db867；正式v1.16.1最小回移经PR475发布annotated v1.16.2，peeled/main d143143099f1dbc4b153eae4a2dcea927fb85f4c。原生release plan共享合同全相等、仅API+Web，单次apply两项switched；独立正式HTTP/API和十项身份读回通过，API/Web为v1.16.2，其余八项仍exact v1.16.1，未切Alert/Feed/Live/Reference。

候选Web1222 passed/3 skipped、alerts定向25 passed、浏览器9 passed（非60m六旧链接、空流/失败、SPA切换和迟到响应）、健康接口6 passed；build/typecheck/topology、offline lock、OpenSpec12/12、secret0、diff和独立Review通过。develop另一套页面亦经13项浏览器及补充SPA集9项验证。初次浏览器fixture及回移模板适配失败保留，修正后才冻结。

正式Chrome只读实测：JM15m零实时查询，原地切60m仅两项60m实时读取、缺流状态明确、pageerror0；截图留证。现场历史动作读取仍有失败提示，本任务未修改其后端或用实时Event替代历史事实。

独立配置/版本读回在本地 `output/htdy-60m-unification-20261025/`；旧发布树仍被八项服务引用，保留。全局health仍degraded；JM60m新的自然completed评估、Event、provider accepted与手机送达分别待验，不声明整体RUNTIME_READY，不新增监控或制造信号。

## 10/25 48路闭市收尾完成：历史44已验，L4恢复，Runtime v1.16.1/gen25

本节为 gen25 全量切换检查点；随后 API/Web 已单独升级 v1.16.2，当前组合以上节为准。

Owner交办当前能处理部分并明确批准发布/正式切换。33基础+11融合Canonical历史原生重建44/44完成，新进程逐项来源manifest/checkpoint/正式HTTP44/44验收通过；16组旧事实全行摘要及4组journal/index/cursor保持，Reference原PID正常恢复。33项已知纯前置刷新失败精确解决，其余74控制项保留。L四路真实观察端点已齐，修正只读健康投影，不改持久旧health或原件。

PR469/main/annotated tag/Release v1.16.1 exact bc2c43dab2a8ce67038ca3998e74ac6b4a16b3c9已发布；十项身份已统一gen25。cold001在CAS后因新树缺Vite依赖导致Web启动验收超时，旧失败保留；仅离线frozen补依赖（0下载），由既有KeepAlive启动，未重复stop/install/CAS。独立final-readback-003验收全部binding/loaded/六owner/四calendar及旧Scope配置、选定forward字段和原journal一致，Web实际index=dist；60秒PID稳定、Reference cycle ready、日志FD匹配。当前Feed6228/Live6197/Alert6203/Reference6210/API6216/Web10198；旧v1.16.0已确认零引用，保留5个.run原件/SHA后按精确计划非force清理，tag/Release及其他任务树保留。

正式Reference **676 READY/44 OBSERVATION_LAGGING**，L4 READY、44独立Canonical历史CURRENT；pending Capture/消费积压/PG维护占用均0，文件锁空闲。全局仍degraded，剩余44为真实观察缺失，不能靠历史计算消除；下一Session采集/H1/Event/Push及18:05增量另验，七路暖机和后置苏冰全量资产保留。1153关联回归/81明确跳过、183维护回归、exact候选339及独立Review通过。详见[48路收尾记录](docs/tasks/reference-lag-closeout-20261025.md)。

## 10/25 D1历史75条修复完成：全部逐项验收，历史720端点CURRENT

Owner交办前次审计的75条D1历史修复。18基础（AL/PG/PS/PX/SI/ZN各三策略）先、57融合后，使用正式exact v1.16.1/gen25原生fresh rebuild；75/75由独立进程逐条来源manifest/checkpoint/正式HTTP核验到10/23 15:00 CST，旧18个503入口恢复、57个滞后追齐。旧18个partial candidate/94已提交批次结果已独立核清，依赖改变后不复用旧plan/resume；ZN旧advance明确首写前REBUILD_REQUIRED。全部旧候选与经济事实保留。

单次attempt001完成，18组旧事实全行摘要及所有journal/index/cursor前后保持；成功后精确解决74旧控制，原文保留，当前控制队列0。15:19独立最终Review通过，75新revision及旧候选/批次/App事实一致。正式启用历史720/720 CURRENT（D1由165/240至240/240）；非目标645的CURRENT仅端点级，本次75另有完整来源验收。

Reference同PID6210/gen25已恢复，六常驻原PID均active、十binding仍exact v1.16.1；pending Capture/积压/PG维护占用0，文件锁空闲。Forward仍676 READY/44真实观察滞后，global degraded、旧2565+611原件限制、暖机及苏冰全量后置保留；下一自然采集/计算/Event及18:05增量另验。首轮定向144 passed/2 skipped、补强维护30 passed（含重叠）、独立代码和实际结果Review通过；provider/Canonical/forward/通知写入0，无版本切换。详见[D1历史修复记录](docs/tasks/d1-history-repair-20261025.md)。

## 10/25 SimNow受控订单适配代码及离线端到端完成，真实柜台待验

新增 `simnow_ctp_controlled_v1`：固定第一套会话/账户/交易日绑定、最多60秒精确单次Permit、
持久发送领取与OrderRef/RequestID、平今/平昨、撤单、原生回报stage/drain、未知结果不重发。
账户writer guard覆盖SDK请求受理；回调先到独立journal，避免同步回调嵌套账户事务。
CTP秒级回报用独立NativeFill保留精度、dispatch因果及SystemID；缺实际手续费或SystemID不一致保留待核，
未知成交quarantine，前日已知单迟到回报保留，unresolved状态在全部事实分支保持BLOCKED。

155项适配/账户/HTDY回归通过；隔离SDK环境32项只读回归通过；Mac ARM64 openctp-ctp6.7.7.1真实结构与SPI mixin无网络smoke通过。
Ruff、secret scan0及diff通过；独立高风险Review所指秒精度、恢复顺序、SystemID和跨日关联问题均已失败回归复现并修复，聚焦复审允许集成develop。
CODE_COMPLETE / TEST_COMPLETE / REVIEW_COMPLETE；真实端到端EXTERNAL_GATE_PENDING，SDK结构成功不等于柜台实测。

未创建原生交易API实例、未读凭据、未真实报撤单、未发布或切Runtime，auto_order=false保持。
第一套及10万元20261027生效仍待原生读回；完整原生Readback/实际费用投影与受控交易宿主尚未接线，无交易启动CLI。
后续须在这些事实与可交易Session具备后验收精确一手报撤单，不能将测试副本/离线fixture当自然实测。
合同见[SIMNOW_EXECUTION](docs/SIMNOW_EXECUTION.md)，验证见[TESTING](TESTING.md#simnow-受控订单适配)。

## 10/25 HTDY账户风控、预留与订单状态机离线实现完成

`htdy_60m_account_execution_v2` 已实现70%权益保证金准入、冻结去重与本地资金/费用预留、资金拒绝永久消费信号、
信号先后处理、对手价、原生受理后自然180秒撤后核对再跟进、收盘前60秒放弃开仓但保留平仓义务。
SQLite命令/状态/惰性提案原子提交、幂等、未知提交只读核对、重启恢复和真实迟到成交保留均有回归。
原v1政策、公式、Alert与参考收益保持；新入口不连接Broker transport或持续Runtime，没有真实报单/撤单。

定向完整命令见[TESTING](TESTING.md#htdy-60分钟离线执行规则)：124 passed；Ruff通过、secret scan 0、diff check通过。
独立高风险Review发现的离线成交恢复、错误合约恢复方向及连续未知成交问题均已由回归复现并修复，聚焦复核允许集成。
CODE_COMPLETE / TEST_COMPLETE / REVIEW_COMPLETE；不是发布、Runtime或账户自动交易Ready。
真实第一套环境及10万元资金生效仍待下节原生读回；下一步为Broker订单适配及端到端受控验收，不能直接循环发送effects。
合同见[HTDY_SIMNOW_V1](docs/HTDY_SIMNOW_V1.md#账户风控与报单决策2026-10-25确认)。

## 10/25 SimNow测试环境只读已实测；10万元重置申请受理，20261027生效待验

按owner交办完成固定测试环境的资金/持仓/委托/成交两轮串行只读CLI；复用已实测的Mac CTP登录ABI，
不接入持续服务或执行政策。查询必须完整收尾、身份和交易日一致；保留今昨多空/冻结/订单原生事实，
两轮变化或未完成不报空仓，资金仍有保证金占用/冻结时也不能报空账户。

24项离线测试、原生四查询无网络参数核对、Ruff/secret0/diff及独立Review完成；Review所指保证金空账户
判断已由失败回归复现并修复。CODE_COMPLETE / TEST_COMPLETE / REVIEW_COMPLETE。16:56用户本机隐藏输入后实际四类查询均两轮完整，
独立读回确认两轮逐值/摘要一致、测试环境空仓无未完成委托，交易日20261023；原始结果仅本地私有output保留。
这不是第一套环境验收或账本对账；前序失败及登录记录不改写。

后续按owner交办准备显式 `--environment first`，固定官网30001，不自动fallback，新增4项离线回归先失败后通过，
总28项通过。17:05第一套匿名连接12秒未返回成功回调，未认证/登录/查询；第一套仍按官网实际交易服务时段待验。
Owner随后完成官网登录并明确接受清除全部模拟持仓。agent单次提交被官网验证码拒绝，未重试；owner自行重新
提交后提供官网成功截图，目标10万元，明确生效交易日 **20261027**。这是申请受理，不是资金已到账；旧失败
及截图保留本地，不推算为20261026、不重提、不修改旧账户快照。first原生读回仍未完成。
新增成对可选资金验收参数，只在first核对两轮目标余额/空仓/无单/无冻结及柜台生效交易日；测试副本、旧日或
查询未完成均不得通过，且始终无执行资格。定向32项测试通过，真实资金生效另验。
未请求订单、撤单或结算确认，未写行情/生产数据库，未发布或切Runtime；官网资金重置由owner自行提交，
不把测试环境副本当作第一套环境或Ledger对账。
合同见 [SIMNOW_READONLY](docs/SIMNOW_READONLY.md)，交付记录见 [任务记录](docs/tasks/simnow-readonly-20261025.md)。

## 10/25 HTDY九品种闭市来源差异：已核验分类，下一交易日自然验收待发生

按owner交办复核AP/CJ/JD/LH/PK/RS/SF/SM/UR；Canonical32根60m预热及底层1m完整，旧原件也完整，
两套各自1m→60m聚合精确一致；逐端点证实123根1m、17根60m数值差异，保留旧原件和历史事实，不反推provider修订原因。
新增只读 `htdy_closed_day_source_difference_v1` 分类，完整交易日闭市、物理来源/质量、旧/新owner与新合约生命周期、
Calendar/Session及旧/新恢复身份均须可证明；不是盘中fallback，不改变原生冲突reader或执行政策。

fresh全60复核：历史60通过，当前计算51通过/9旧冲突阻断、原Live42完整/18阻断均保留；
总体40等待新观察、11历史已补齐但原件缺失、9已核验闭市差异等待新交易日。9项下一日均10/26、首H1日程10:00 CST，
尚无该自然Bar；所有审计eligible_now/first_seen均false。本次零下载/生产写入/Runtime切换/信号重放/通知，18个原件键前后hash一致。
独立Review验证9份证据hash及原件前像，关闭next ContractFact/next recovery两项边界缺口；定向执行/reader回归221通过，
Ruff/OpenSpec12/secret0/diff通过。证据在 `output/htdy-source-conflicts-20261025/`，该审计当时Runtime为exact v1.15.18；现役记录见本页顶部。

## 仍需分别验收的运行与交付事项

- 最新记录为 API/Web v1.16.2、其余八项 v1.16.1；Reference 676 READY/44 OBSERVATION_LAGGING；global degraded、
  7 路短有效历史 warming、原 2,565 + 611 条自然原件缺失保留。历史输入补齐不能补造原观察或消除真实观察滞后。
- 下一自然 Session 的采集、H1/计算、Event、通知和 18:05 增量须分别验收；不由测试、历史端点 CURRENT
  或进程 active 推导整体 RUNTIME_READY。10/25 闭市修复记录见
  [健康恢复](docs/tasks/runtime-data-health-recovery-20261024.md)、[原件缺口历史补齐](docs/tasks/original-gap-history-repair-20261024.md)。
- Newow 正式品种范围已为 60/60；历史 720/720 CURRENT 的非本次目标部分仅为端点级检查，
  不外推所有来源、辅助指标、自然观察或 OOS 完整性。当前产品开放仍由 capability 合同决定。
- 苏冰全量历史资产按 owner 优先级后置。10/24 初次清点 240 身份中 236 缺失、RB4 仅到9/22；
  JM4 已完整验收，A/AG 各4已构建。该数值是旧盘点，不能当作当前新鲜覆盖数。
  AL15m 原生 INTERRUPTED 位置225792/320074与token保留；RB4 exact append已通过前置校验，
  本页尚无随后完整 apply/验收记录，不宣称苏冰全量闭环。
- 苏冰推送关闭、既有 Rule/Scope/受众和 `auto_order=false` 保持；不启用Paper持续运行、Shadow或自动订单。
  最新夜盘通知口径为4批平台accepted、2批failed或unknown，owner未打开微信，实际收件未验。
  历史 AO2701 10/14 23:00 HTDY 的 owner 收件确认只证明该次事件，不外推其他事件或受众。
- 生产 schema、精确配置与当前 PID 应现场只读核对；本次清理不执行 migration、配置变更、重启、
  replay、backfill、补发、发布或 Runtime promotion。

## 10/24 苏冰历史续算/追加：前置连接失败已修复

AL15m续算及RB四周期追加脚本原先先导入应用、后加载私有配置，数据库连接池提前缓存开发配置。已调整初始化顺序，默认离线行为保留；新增只读check-only和安全错误定位。18项定向测试通过、独立Review无Confirmed Issue。正式v18现场只读：AL225792/320074原生续算位置一致、RB四周期exact append/旧事实校验全部PREFLIGHT_PASSED，production_writes=0。旧失败目录不重写，修复版v2目录独占；本步未执行apply，不代表全量历史计算完成。下一步仍须确认旧writer退出、现场锁和来源后精确续算/追加。详见[修复记录](docs/tasks/subing-history-preflight-fix-20261024.md)。

## 期货双向研究：已随v1.15.16发布，未晋升

已推送并集成develop 757c09ae37；数值实现冻结5ad16d06b。保留牛哇默认原版，新增独立futures_bidir_v1内核、参考投影、10万元分层研究账户、冻结结果只读API及详情页开关；八策略名称和六周期入口保持，主图动作/目标保护线、方向、持有周期、参考与账户收益及记录分别切换。
JM/RB/AL/TA × 六周期 × 八策略 × 三成本场景576格全部落盘并独立核验：260完整、225资金不足、73换月中断、6预热不足、12不适用。基线192格中88个完整账户为12正/69负/7零；不证明普遍盈利或OOS。TA另有3格参考路径DATA_INTERRUPTED，保留未知收益。中断不拼成完整年度收益，资金拒绝不吞并参考交易。
全量104411条模拟Fill的费用/现金/层级PnL/整数仓位/tick及strict-later核对通过；首轮332重叠格数值逐字一致，仅59处参考快照原因修正。后端及原版回归445 passed，Web1165 passed/3 skipped，build/type/topology、secret零发现及独立Review通过；实际5183/8004八策略/六周期、往返刷新、旧响应隔离、精确定位/窗外提示及最终真实价格逐项读回通过。
上述为实现验收检查点；其后已随v1.15.16发布并被现役v1.16.1包含，不因此晋升策略或启用持续Paper/通知/Shadow/Broker/订单。冻结主图最近2000根，窗外历史记录明确不可定位；全窗记录和曲线独立保留。实际统计、身份、文件与命令入口见[首轮研究记录](docs/research/newow-futures-bidir-v1-20261021.md)。发布证据见 [期货研究交付记录](docs/tasks/newow-futures-bidir-v1.md)，当前Runtime记录见本页顶部。

## 新苏冰固定参数研究版：工程与历史回放验收完成，未晋升

新增独立 `new_subing_v1`，规则见 [策略合同](docs/NEW_SUBING_STRATEGY.md)，
交付记录见 [任务验收](docs/tasks/new-subing-v1-20261012.md)。独立只读页面 `/research/new-subing`
和 API 读取显式任务结果根；不恢复旧苏冰策略、不改变现役 Alert/JM Paper；此段记录研究验收，发布与Runtime见顶部。

精确计算候选 `2d7069b1be746cb80656f95fd3a576eb6b97ed53`，AL/RB/TA 各自100000元，
2024-10-14..2026-10-09的9个成本场景包与54个独立窗口摘要均完成。基线两年净收益
AL -0.312%（2笔）、RB -0.305%（1笔）、TA 0%（0笔）；双手续费/滑点未改善结论。
后一年及四季度所有场景均无成交，样本不足，**不证明策略有效或独立OOS通过**，不自动晋升。

定向552项、Web1090项（3项既有跳过）、类型/构建/规范/秘密扫描及独立代码审查通过。
真实结果独立哈希、18笔Fill、9轮成本变体交易和117条权益的资金/费用/PnL/回撤复算通过；
54个独立窗口仅核对摘要，未在独立读回中重新逐笔重放。
原 Notion 经典案例截图尚未逐图解析，案例一致性待验；旧失败采集和两次停止回放记录保留。
CODE_COMPLETE / TEST_COMPLETE / REVIEW_COMPLETE，未进入Paper持续运行、Shadow或Broker。
下一最小步骤：原案例逐图对照，核对新策略触发与笔记交易的差异；不得据少量交易扩大运行范围。

## JM 固定 Paper 口径：七策略六周期复核完成，未晋升

2026-10-11按owner要求，沿用前三步的50000元、最多一手LONG、日初权益亏损2%停开清仓规则，
复核趋势、震荡、双策略及测试1–4，覆盖5m/15m/30m/60m/1d/1w。
42组共用2025-10-13..2026-10-09的82305根物理1m执行行情与逐日成本事实。
22组完整年度账户可比，20组因持仓或挂单跨主力换月而中断，不纳入全年排名；
另有168个各自50000元起步的合约段诊断，不拼成全年账户。证据见
[完整矩阵与排名](output/jm-causal-matrix-20261011/report.md)。

完整年度收益最高为周线测试3：+14.30%、3笔已平仓交易，样本过少且集中单一合约。
60m测试2：+9.78%、35笔、最大回撤13.91%，四个独立合约段均盈利，列为未见数据验证优先项。
8个盈利组合完成双手续费与双滑点压力；60m测试2仍为+10.32%/+8.04%，
30m震荡与测试1在双滑点下转为-1.54%/-7.47%。本年已参与选择，不是独立OOS。

定向Paper/研究测试192 passed（含隔离PostgreSQL），工程合同29 passed，Ruff/Mypy通过，
独立审查无阻断问题。新增研究适配复用原公式与Paper事件内核，不写生产数据，不新增正式账户，
不连接SimNow、不启用Shadow/自动订单、不发布或切换Runtime。
下一最小步骤：冻结60m测试2研究身份，在未参与筛选的数据上验证；本次不自动晋升。

## JM 前三步：因果验证与本地 Paper 工程完成，策略不晋升

2026-10-11 owner交办前三步，风险固定50000元、一手long、较交易日初权益亏损2%停开并安排清仓。
新增版本化双策略因果目标、开/平今/平昨费用、纯Paper状态机、独立PostgreSQL不可变账本与历史回放CLI。
合同见 [Paper试点](docs/PAPER_PILOT.md)，证据见 [验收结果](output/jm-paper-first-three-20261011/acceptance.md)。

近一年JM5m双策略1430笔已平仓因果交易，1tick滑点基线复利净回报 **-79.1812%**，
双手续费 **-84.6940%**，双滑点 **-93.4562%**。这是closed-trade研究口径，不是50000元账户收益；
一笔换月中断和一笔期末未平仓单列排除。筛选年与诊断WF重叠，不能称独立未见OOS。
因此页面赢家不满足进入执行阶段的研究证据，不自动换候选或启用策略。

独立本地Paper实例端口15462（未改生产5432），账户`jm-dual-5m-20260928`完成
2026-09-28..2026-10-09真实Canonical历史回放：1551命令/事件、55次模型成交、
期末权益49364.702元、保留JM2701一手及一个未完成平仓意图。9月29日触发2%停机并平仓，当日未再开仓。
相同计划重复执行事件/成交数不变，新进程独立重放一致。这是HISTORICAL_REPLAY，不是实时Paper/Shadow。

Paper/研究116项（含真实隔离PostgreSQL）及工程合同29项通过；独立高风险Review问题已修复。
没有发布、运行切换、Broker接入、通知、真实资金订单或后台自动执行。`auto_order=false`。
该检查点之后已完成上节同口径矩阵复核；当前5m双策略不进入SimNow自动交易。

## 旧P9未知结果与恢复边界（不得据新闭环自动关闭）

P0–P8 工程和隔离验收已经集成；**P9 生产闭环未完成**。Newow 页面参考投影验收不等于持久化统一参考交易验收。

- 460 个 SuBing D1 质量候选已一次性原子发布；生产读回 `already_applied=460/460`、`old_count=0`。
  3,113 个源 Close=0 分类为 `NONPOSITIVE_CLOSE_SOURCE_FACT`，保留 5,175 根有效 Bar 与显式质量事实。
  精确备份及 journal：`outputs/reference-p9-d1-quality-20260925/`。
- 首波 175 单元 warm-up 中前 6 单元已提交、读回 80 个分区，已知 provider 请求 21 次。
  第 7 单元 `al/AL2302/15m` 为 `UNIT_OUTCOME_UNKNOWN`：22 个目标仍未发布、请求次数无法证明，
  **未重试，余 168 单元未启动**。结果不明保持阻断，不用重规划缺失证明请求可安全重试。
- 最近一次 600 流只读审计为 `SOURCE_READY=387 / BLOCKED=213`；之后 15 条 W1 流复核中 SC/SI 六条
  SOURCE_READY，PL/PX/RS 九条仍为 `REFERENCE_BOUNDARY_CONTEXT_MISSING`。这些是对应旧精确提交的审计，
  当前版本完整矩阵、历史构建与持续更新须重新绑定 exact code/input identity，不能沿用旧结论。
- 0048 migration及本轮Newow720历史构建、记录worker启用已完成；全局persisted reader与其他P9范围须按各自证据验收，不能由Newow闭环推定完成。
  2026-10-08历史检查点：v1.14.3 worker恢复85条旧阻塞；该检查点worker为v1.14.5（当前身份见顶部），136条23:00遗漏已恢复，自然验收见顶部。旧P9未知结果与恢复边界保留。
- A2611 旧来源请求已按 `SOURCE_RESPONSE_IDENTITY_INVALID` 停止且禁止重试；后续 D1 修复后重审无新恢复目标，
  不是对旧请求的重试。六个 W1 新批次共 64 个 W1 与 64 个 D1 同源上下文目标通过，来源 journal 64 次请求。

完整 P9 证据与恢复边界见 [rollout](docs/tasks/unified-reference-trading-p9/rollout.md)，
`outputs/reference-p9-warmup-wave1-20260925/`、`outputs/reference-p9-source-inventory-20260925/`。
旧盘后 D/E/F 已关闭，不重跑；旧事故未证明的生产归因继续保持证据不足。

## 已接受的后续交付规划

日周交付 → 关闭已记录页面缺口与自然维护验收 → Web 体验改善与分钟数据准备 → 分钟产品独立验收开放。
当前日周交付已发布；不能再按旧 v1.10.8/v1.10.9 检查点把该阶段重开，或把最新切换认定为自然验收通过。

- Web 正确性随对应版本验收，纯 Web 改善不等待分钟补数；不顺带改变公式、参考收益或数据来源。
- 分钟准备由同物理合约 Canonical 1m 派生，复用 Catalog/MDS、Session、质量校验、维护锁与预算；
  去重窗口、有源先派生，只对明确缺失安排恢复，失败按合同停止。补数完成不自动开放产品。
- 分钟开放分别验预热、Session 聚合、换主力、completed Bar、参考记录、分页与故障状态；
  跨周期解释保留 bar_end/as_of，不用未来完成周线回填历史决策。
- 策略公式、页面参考、因果研究、OOS/Walk-forward、Shadow 和账户事实分别验收；解释评分不自动成为执行 Gate。

## 唯一下一步

按本页顶部最新发布、Runtime 身份及未完成事项推进；本节不另存版本号或复制阶段待办，
避免历史检查点覆盖当前结论。自然 completed Bar、发送及 Live→Canonical 验收分别保留真实证据，
不制造 Bar、不盲目重试，也不扩大现役运行范围。
