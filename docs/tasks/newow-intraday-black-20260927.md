# P7 首批黑色产业链历史产品闭环

## 当前范围补充（2026-09-28，逐品种闭环）

当前分钟产品验收范围为 **5m/15m/30m/60m**；1m 仅可信聚合输入，Newow 1m 显示与策略留后续独立版本。
RB、HC、I、J、JM 已分别完成十二组合历史候选验收，以 `STATUS.md` 及对应逐品种任务记录为准；SF、SM 待推进，SS 继续暂缓。
下文 1m/15m/30m/60m、84/96 分母及旧候选进度保留为当时批次历史证据，不代表当前范围完成状态。
本地 outputs 原始证据保留并按精确目录忽略，不提交为源码资产。

## 当前执行摘要（2026-09-28，七品种验收进行中，SS暂缓）

- owner 最新范围：先完成 RB、HC、I、J、JM、SF、SM 七品种84页面组合；SS数据暂缓，原96分母保留SS12 `DEFERRED_DATA_BLOCKED`，不称其通过。第一版本接受1m慢加载，性能优化不作为本轮收尾条件；数据身份、公式、记录配对、分页、切换和最终错误状态验证不降低。
- develop/origin develop 已推进至 `00cea970e7e87295ddcc89f7937a34430fb64b11`；数据/资产/API原证据身份仍为c576，新页面候选9dd与该develop提交同树；正式 main/tag/Runtime 未变。下文较早的“执行中”内容是各阶段历史快照，以本节及后续实际读回为准。
- 旧805阶段文件已按原相对路径归档至 `outputs/newow-intraday-black-20260927/archive/final-805ef/`，205个文件字节SHA逐一核验；本文历史805 source/asset/API/matrix/freeze记录应从该归档读取，不与当前新phase文件互用。
- 最终32输入读回：28 READY、SS4 BLOCKED；七品种84个隔离资产独立读回通过，RB12复用。64基础中56 READY/8未构建；32融合中28 READY/4未构建。资产可读不等于页面验收完成。
- exact805 的完整96 API实测于 `2026-09-27T20:33:04.088728+00:00` 自然结束：82 READY、14 BLOCKED。SS12缺历史资产；SF/SM各1m双策略完整参考查询超时。历史证据 `archive/final-805ef/final-api/summary.json`，前两次审计合同漂移的原始结果独立保留。
- 617次、5秒间隔串行API96资源采样观察到最大RSS 1,111,228,416 bytes。此为已暖候选进程采样值，不能称为构建容量、进程冷读或精确进程峰值。
- 历史805诊断：SF只读分阶段诊断确认完整历史 `query_historical_trades` 在30秒DB上限中失败（SQLSTATE57014）；近一年记录及presentation facts通过。无ANALYZE EXPLAIN显示Nested Loop内侧WindowAgg/Incremental Sort且估算偏小，只证明当时计划结构风险，不证明实际loops或generic-plan原因。后续已在隔离task checkout修复版本选择查询，没有增加超时、重建资产或改变数据/公式。
- 历史中间诊断：两个未提交查询候选（group MAX及correlated latest）虽然各自语义回归通过，但SF/SM同资产真实complete读取都仍57014；均未集成，原始结果分别保存 `audit/fusion-winner-readback.json` / `audit/fusion-correlated-readback.json`。repository查询还包含动作明细水合，因此当时继续按SQL实际分段定位，未将EXPLAIN结构改善或离线测试表述为性能修复。
- 历史中间诊断：唯一instrumented SF诊断已将当时失败定位到 `query._interruption_details` 的第二条trade SELECT（30.003559s、params21）；主winner trade SELECT实际0.172125s，动作水合各批0.006..0.025s均通过。因此没有把完整调用超时归因于主winner或动作水合；后续已修复中断详情的版本查询。证据 `audit/sf-fusion-correlated-statement-diagnostic.json`，仅安全结构标签/计时，不包含SQL与参数值。
- 后续SM唯一诊断定位到中断的latest mark窗口回连；最终修复主trade、中断trade与mark三条读取路径。完整实际PG复核SF 4.608090s、SM 5.083995s，两者同snapshot记录分页与旧资产计数/Decimal统计一致；不称为HTTP或浏览器验收。reference模块300 passed/47 skipped，主代理七组定向49 passed/1 skipped，secret scan零发现，独立Review无ConfirmedIssue并允许集成develop，提交及推送 `8d1689060edda494fb3abc635126750ed367dc0d` 已完成。旧失败证据保留，新phase输入/资产/API/页面读回继续。
- 真实浏览器第一轮定位器因现有新增持有过程曲线匹配两个section而停止，未计通过；原失败记录保留。96页面、最终D1/W1、冷/热读及取消恢复仍待完整实际验收。
- 本轮真实维护已知请求781 + SS2302未知保留11 = charged792/1500。SS2303部分提交、SS2302未知结果及禁重试合同保持；151 NEW单元没有被执行，不能写成失败或已完成。
- c576 phase 已重新顺序独立读回 source32 与七品种 asset84：32项来源哈希、84个保存流记录与8d阶段逐项一致；SS仅source身份可读，四输入完整prefix仍BLOCKED。真实96项串行 API 于 `2026-09-27T23:39:51.914655+00:00` 完成：84 READY、SS12 BLOCKED；`final-api/summary.json` 字节 SHA256 `1e1e077acfcd3c7e6afcfd696678e31136b3bab18064a4dd6842b699012c1b05`。这不代替浏览器验收。候选仅8011/5175；首个产品请求前身份证据 `audit/finalc576-service-identity.json`。完整96页仍待验收。
- c576 串行 API96 的候选 PID23859 资源采样共634次，观察最大RSS1,315,045,376 bytes，范围 `2026-09-27T22:46:48.054930+00:00..2026-09-27T23:39:53.380768+00:00`；原始证据 `audit/finalc576-api-observed-resources.jsonl`，SHA256 `cc91a71f0725945184ad388ce81a078627ac14f09f0c744d5406e48595b4b5cb`。这是已暖进程采样，不是构建容量或精确进程峰值。
- 8d API 中断证据已归档：RB 1m 趋势第二个完整参考页响应约39 MB，返回 nullable snapshot token，Web 同快照分页不能接受。c576 仅在有效旧 token 的已保存 proof 完整覆盖本次重新验证依赖时复用它；初次超限、新增 proof、过期、冲突与禁用仍拒绝绑定，不提高32 MiB单条/128 MiB总缓存预算。根代理137项产品/API回归通过，独立114项缓存/导航回归通过；真实 c576 RB 趋势参考页和下一页已同 token 通过。全部96终态仍以当前 `final-api/summary.json` 为准。
- 实际浏览器的大响应证据曾因 `Request content was evicted from inspector cache` 不可读取，旧错误保留。候选取证现旁路读取本次原生 XHR 的原 responseText，保留请求对象/URL/HTTP/事件次序和完整身份，额外解析耗时显式记录；curve仅采摘要，不能冒充完整数组逐值验收。完整数组由独立API读回检查，浏览器仍需原图、曲线和真实控制交互。新空白页初始化失败在首产品请求前发生并独立归档，没有下载或维护重试。
- c576 RB 1m 双策略首次产品进程冷读89.159s、早期同进程热读24.218s；两源与完整窗口可验证且已看主图/曲线，但早期热读有一个未终结请求，不能作为完整热读验收。该进程最大RSS1,032,503,296 bytes，仅覆盖RB阶段。修正动态终结等待后，SM 新进程 cold73.428s / hot18.161s，两次6/6请求已终结、3次稳定poll、零错误；SM主图和完整参考曲线已逐图审查。均仅指候选API进程冷/热，不宣称OS或PostgreSQL冷缓存。 后续RB新进程PID31249重验 cold90.645s / hot26.778s，两轮均6/6终结、3稳定poll、0待处理/0错误，根代理逐图审查主图与完整参考曲线；早期RB证据归档于 `browser/attempt-c576b-rb-coldhot-before-dynamic-settlement/bytes-index.json`，不改写其热读未收敛事实。


## 范围与基线

RB、HC、SS、I、J、JM、SF、SM × 1m、15m、30m、60m × 趋势、震荡、双策略。
现有 black + steel 联合批次，不修改板块分类。分母：32 输入、64 基础、32 融合、96 页面组合。
起点 develop/origin develop `b045fdfc1bff429f4e57765ea502382a6938b86c`；无关未跟踪 outputs 保留。
现役 v1.10.39 不改。P0–P6 依首轮交接复用，冻结截点 `2026-09-24T07:00:00.000001+00:00`。
维护窗口 2023-01-01..2026-09-24；物理合约完整预热按 MDS lifecycle 权威范围，不能以维护窗口截短。
完整资产计算及页面默认全历史统计/曲线窗口为 2023-01-01..2026-09-24。记录范围冻结：既有单策略页面按 accepted anchor 的日历近一年请求 2025-09-24..2026-09-24（history_limit=200）；分钟 persisted reader 实际 entry 下界为 max(request_since, through-364天)，融合后端同样按含首尾365天返回记录，因此本截点两者实际记录下界均为 2025-09-25。页面请求的统计窗口与后端记录筛选范围须分别记录，不能混称。API 显式指定近一年 performance_since/through 时，统计与曲线仅覆盖该请求窗口，独立验收；history_limit=200 不改变默认全历史统计/曲线范围。主图窗口与完整物理预热范围另按实际 response/prefix 记录。

## 执行与证据

已完成全集合轻量目录/coverage盘点、本批初盘、多品种候选入口和首轮测试合同修正；HC40单元及随后I/J/JM/SF/SM310单元精确维护已完成，SS后续部分提交已停止。七品种84个资产及最终独立读回完成，API96终态已记录，真实浏览器验收进行中。
原始证据目录 `outputs/newow-intraday-black-20260927/`。已有 RB 隔离资产先读回，未确认前不重建。
候选默认关闭，生产数据操作仅限本批精确缺口及不可缺少依赖；共享维护串行。
不发布、不切 Runtime、不启用正式分钟入口、观察、worker、通知、订单或策略晋升，不开展新因果/OOS研究。

## 验收状态

当前尚未验收本批；不声明 P7 完成。数据/资产/API原证据代码冻结为 `c576b3614ff79c26ee5a192cb3b0fb1449710240`，source32、asset84、API96 已实际独立读回；新的七品种84页面候选为9dd，D1/W1与取消恢复仍须完成。旧8d证据见 `archive/final-8d168/bytes-index.json`，旧805及原构建/维护aef3证据分别保留，旧浏览器观察不改写为当前 phase 验收。

## 维护与恢复现场（初轮历史快照，后续终态见下文）

- RB：四输入身份及十二隔离资产已独立读回，未重建。
- HC：十个缺失 owner 的四周期共 40 个维护单元完成；77 次实际 provider 请求，逐单元独立 fresh plan 无剩余 target。四周期共 48 个 owner×frequency 完整前缀复核 DATA_READY。15m/30m/60m 共 9 项基础与融合资产完成；1m 两项基础完成（866936 inputs/strategy），1m 融合待构建。
- SS：SS2302 1m 首次维护发生 ATOMIC_PUBLISH_FAILED；2022-02..07 六个月实际提交并独立校验，2022-08 无 Catalog 提交，原 2023-01 完整。实际请求次数无法证明，按原预算保留 11 次；不得重发该单元。SS 全部保持 BLOCKED，未伪造闭环。
- I/J/JM/SF/SM：独立复核限定 310 个精确单元，续跑须验证冻结 reconciliation，源响应持久化及未知结果全局停止。总请求上限 1500，已知 HC 77 + SS 未知保留 11。
- 恢复验证：SS 同卷隔离 scratch publication 与二次幂等通过，零 provider/Canonical/Catalog mutation；只证明已验证源在现有 schema 可发布，不证明 SS 失败源已恢复。
- 资源：宿主 16 GiB；HC 60m/30m/15m 基础构建实际峰值 276086784/336707584/471515136 bytes。采用单任务构建，维护与持有 source lease 的构建串行。

证据：`audit/initial-source-readback.json`、`rb-existing-readback.json`、`final-audit/hc-prefix-readback.json`、`audit/ss2302-failure-readback.json`、`audit/scratch-publish-check.json`、`audit/independent-reconciliation.json`。

## 代码与回归（执行中）

候选白名单代码 `b0cce874bb6a5237c6251248b17d729f52a15a64`；fixture 合同修正 `02558d41ed132e982d2fa552556293a5fe29fb55`。随后并发任务提交 `0d1f558a9d10ef452fe5bf06de22b6e0c58fb4d4`，保留并重新核对，非本批修改。
Python 定向 106 passed；Web capability 23 passed；产品 fixture E2E 41 passed。数据定向 268 passed；Web 720 passed / 1 skipped，typecheck/build 通过。后端全模块原运行 2491 passed / 46 skipped / 5 failed：三项在并发 AU 修改期间合同漂移、两项 sandbox 禁止 socket；冻结当前代码的相关 elevated 复跑 63 passed，原全模块运行不标为全通过。
真实 RB API 88 请求及 payload 身份/重复一致性验证已执行；首次审计读不等于空缓存冷读。真实浏览器逐组合验收继续进行，API HTTP 200 和 fixture 不替代页面证据。

### 真实容量发现与修正

RB 1m 双策略首访在 HC1m 构建同时运行时出现 reference 429（50.023s）和客户端 TIMEOUT（60.002s）；一次显式只读重新计算恢复，不覆盖首次失败。根因之一为双策略隐藏单策略近一年记录面板仍自动请求，争用同一受限参考队列。`253a8e420` 仅将该隐藏资源输入置空，既有取消机制停止旧读，返回单策略恢复；未增加超时、队列预算或改变参考公式。TDD old=1/new=0，8 unit PASS、4 fixture browser PASS；该时点真实冷访待复核，随后aef3实际冷访结果见下文。

HC1m 基础实测 plan 262.625s、build 878.164s、peak RSS 3199287296 bytes。真实只读运行中取消8 batches / 0.163s，前后保存generation完全一致，零provider/写入（`hc/running-cancel-readback.json`）。新 driver 的 zero-commit 隔离保护已在执行前完成修正与独立复核：仅实际提交为严格整数 0、完整源响应持久化且 fresh plan hash 未变时允许隔离数字质量阻断；部分提交或未知结果停止后续 mutation。见 `audit/maintenance-review.md`。当时 I/J/JM/SF/SM 精确续跑启动，原310单元批次将SS整体排除。后续SS仅永久排除SS2302；其他38个未尝试owner的精确152单元见后述新计划，旧失败单元禁重试不变。

## 轻量证据汇总快照

截至 `2026-09-27T15:28:22.878524+00:00`，独立精确维护终态 `COMPLETED`，310 唯一单元全部 SUCCESS；I/J/JM/SF/SM 本轮698次已知实际 provider请求，加 HC77次共775次已知，SS未知保留11次，预算 charged786/1500。原执行中 SUCCESS220/NEW90/charged579 快照已被本终态替代，旧批次预算停止与SS失败历史仍保留。

| 品种 | 单元 | 终态计数 | 子批次 charged |
|---|---:|---|---:|
| I | 44 | SUCCESS=44 | 86 |
| J | 44 | SUCCESS=44 | 88 |
| JM | 42 | SUCCESS=42 | 79 |
| SF | 108 | SUCCESS=108 | 277 |
| SM | 72 | SUCCESS=72 | 168 |

终态来源字节 SHA256 `c698f727f7f562e068922aa180e9f0659354af9bd360c66c3789f618d974c75b`，policy `p7_intraday_source_precision_zero_commit_v1`，冻结 reconciliation `235ca001be161570b31b1c4a2fb5a51b2144b0cb00797cb42658527e48177203`。该维护终态时点完整32输入 source独立身份均 SOURCE_IDENTITY_READY，当时证据字节SHA256 `79bd1e5a67246e8e858af8170b229ca6153c2a108384926657d14b36521d834b`（SS后续部分提交后的新读回见后述，旧SHA保留为历史）；精确逐输入source SHA与依赖身份保存 `maintenance-doc-snapshot.json` / `final-audit/initial-source-readback.json`。source身份可读不等于完整预热prefix证明，尤其SS仍需按缺失历史保持BLOCKED，不因SOURCE_IDENTITY_READY解除禁重试。

串行资产 driver 已由主代理完成 preflight 并启动 `--apply`，当前执行中。冻结 `audit/build-phase-freeze.json`（创建 `2026-09-27T15:25:51.491851+00:00`，code `aef3ca93e4e988e7f55b65410f0beb2bacb53339`）的五脚本仅离线核对SHA全部一致，未改动。没有独立资产读回结果的组合继续等待；不由启动、plan或capacity report推READY。`matrix.json` / `matrix.md` 固定32输入、64基础、32融合、96页面组合，最终API/浏览器仍按逐组合真实证据独立验收。

原 `maintenance-progress.json` 为旧批次history，不覆盖独立子批次真实终态；SS六个已提交月份、未知请求预留及禁重试保持。维护完成只描述I/J/JM/SF/SM精确310单元，不代表本批8品种历史产品闭环或整个P7完成。

## 冻结候选与大批读取修复（执行中）

`6192d342e235cba7a86e4eb853cc08a1971246cb` 修复完整参考身份分块查询第11次起退化为 generic plan 的实际问题；仅 PostgreSQL 多分块读取在既有只读事务内 SET LOCAL force_custom_plan，事务 rollback 恢复，不改全局配置、资产或公式。定向17 passed / 2 skipped；独立真实 PG 33,175身份完整hash保持一致，93.536s降至8.960s，同backend正常/异常rollback后均恢复auto，corrupt仍失败。见 `audit/public-ids-fixed-readback.json` 与 `audit/maintenance-review.md`。

并发任务随后修改根工作区的D1/W1和曲线代码。为保留其修改并保证代码冻结，本批候选迁至干净隔离worktree `/Volumes/扩展盘/worktree/newow-black-p7/guiyi-quant-workstation` exact6192；候选API/Web端口和白名单不变，只读同一Canonical与隔离reference schema，正式Runtime未切换。API/Web identity一致，未预热策略缓存（`audit/candidate-worktree.json`、`api/cold6192-process-identity.json`）。旧共享工作区浏览器结果仅INITIAL_OBSERVATION，不能代替冻结验收。

I的44个精确维护单元完成后独立复核四周期48个owner前缀全部INPUT_PREFIX_VERIFIED；最终source身份与资产尚待构建/读回，不声明12组合验收完成。宿主物理内存17179869184 bytes与当前卷容量实测已保存 `audit/host-capacity.json`；仍采用单构建worker，维护与source lease构建串行。

## aef3 性能修正与周期组合（执行中，尚未验收）

隔离候选推进至 `aef3ca93e4e988e7f55b65410f0beb2bacb53339`；共享 develop 并发任务 `d80afc23c` 的 D1/W1 与持仓参考曲线修改保留，不混入本批冻结候选。aef3 复用 MDS 权威 completed_trading_days 批量计算参考窗口，保留完整请求 Session 范围证明、严格日期类型、排序/唯一/范围校验与最终 Session cutoff 校验，不改窗口、预热、公式或超时。128 定向测试 PASS；独立 Review 无 Confirmed Issue。最终源码 hash `88b373cb3d0989bbb5c151f394f79a3a270c885ccdd56595fb476394e96e5491` 的真实只读同一 REPEATABLE READ snapshot 对比，RB 六周期 × 六窗口边界 36/36 字段完全一致（含节假日早晨、未来 through、收盘前1µs与 W1 pending），见 `audit/window-batch-final-parity.json` 与 `audit/window-batch-review.md`。

此前并发 ASGI 实验使用加入最终类型保护前的源码，保留 source_stable=false；虽 trend window resolver 21.849s→0.150s、SQL3097→388，总 reference 40.710s→40.435s，仍不能证明严格冷访或完整双策略容量通过。原真实 60s 超时及429事实不覆盖；重启后 aef3 冷访由独立验收继续记录。

候选 task launcher 显式按周期组合：四分钟周期使用隔离 persisted reader；D1/W1 使用既有 legacy application 路径，仅每请求新 service 实例临时组合并在 finally 恢复，缺失分钟资产不 fallback、不重试。此为候选进程配置，不是正式 Runtime/config 变更，不证明 persisted D1/W1 ready。launcher SHA256 `b647a6b3131621725932118097db952812cb6d55f3ffe11db421180a85078d36`；离线 AST 检查18/18 PASS（六周期正常/异常恢复、分钟缺失无回退、实例并行隔离及工厂参数），零 provider/DB/API/生产写入，独立 Review 无 Confirmed Issue。真实日周及分钟验收必须记录该 launcher 身份与实际 per-period 模式，见 `audit/period-scoped-composition-test.json`、`audit/period-scoped-composition-review.md`。

后续已保存的 aef3 RB1m 双策略严格冷访：82.249s 页面主图可见、50 条参考记录、曲线37,262点、隐藏 trend 近一年请求0、无记录错误（`browser/rb-1m-dual-coldaef3.json`）。这是一项真实组合与容量观察，不扩大为96组合验收；此前429/60s失败保持记录。aef3 性能修正已由主代理集成 develop `8f540c0e498c1b321f5334e8e82591c76ed26005`，集成 reader 定向128 PASS/0.72s；正式 Runtime/main/tag不变。

最终边界只读索引 `audit/boundary-final-readback-index.json` 保存 I12、SF12、SS近期4共28条代表性 Session/逐值 Canonical 聚合 PASS，零provider/数据写入。范围仅代表性已存在日期；尤其 SS 近期4条不能证明其缺失历史或解除禁重试。JM四周期各12 owner共48前缀已保存 INPUT_PREFIX_VERIFIED（`final-audit/jm-prefix-readback.json`）；该时点资产尚待读回，随后原aef3十二资产独立读回已完成，最终805再次读回及API/页面仍待验，不宣称产品验收。

## 后续资产与SS独立缺口计划（执行中）

`remaining-build-progress.json` 已保存 HC、I、JM 三品种各12资产 INDEPENDENT_READBACK_PASS（原aef3构建证据）；RB既有12资产依最终四周期source SHA一致证明复用，未重建。J30m基础 capacity report已completed，尚未据此声明J全部资产或独立读回ready。资产driver继续串行，不以单品种完成停止；最终API和浏览器96组合仍未完成冻结逐项验收。

SS新只读精确计划已完成：38个此前未尝试owner ×四周期=152单元，直接1m计划预算413次；114个派生计划使用同owner权威1m，提交并独立读回后必须fresh replan证明provider_request_count=0。已有charged786/1500尚余714，若按413执行剩余301，不提高上限。SS2302永久排除本轮维护与重试（四周期），已有未知11次预留保持。证据 `audit/ss-remaining-plan-conclusion.md`、`audit/ss-remaining-fresh-plans/index.json`。该节记录只读计划时点，并不表示152单元已执行；随后仅首单元SS2303 1m发生部分提交和全局停止，实际执行与读回如下，SS完整历史仍BLOCKED。

该新维护已启动并以已知部分提交终态BLOCKED停止。`ss-independent-maintenance-progress.json` 终态与独立receipt须绑定；旧310单元COMPLETED不能替代。最终32source及SS四周期完整prefix须在其完成之后独立读回，保存mtime和字节SHA；source可读、mtime新或维护COMPLETED都不能单独使SS READY。矩阵与最终API预检已加入此时序保护，尚未发起HTTP；该时点源与prefix只能保留旧事实；后续真实aef3 fresh读回已完成，见下节。最终805 phase仍需新source及资产generation/formula读回。

## SS实际部分提交、精度阻断与维护后读回

SS新批次实际仅尝试SS2303 1m，provider6次、成功提交2022-03..07五个月，2022-08失败，原2023-01/02两分区独立读回保持。失败原因 SOURCE_NUMERIC_REPRESENTATION_UNAVAILABLE：turnover存在不能由现合同decimal128(38,18)无损表示的小数值，源响应保留；不能舍入、插值、改变精度合同或重发来伪造闭环。152单元真实状态为1 GLOBAL_STOP（NUMERIC_FAILURE_PARTIAL_COMMIT）+151 NEW，整体BLOCKED；已尝试、结果未知或部分提交单元禁止重试，151 NEW尚未请求且原入口仍GLOBAL_STOP，不能泛化为永久禁执行。SS2302原失败结果与未知11次预留完全保留，未重发。新6次使旧775已知+11预留=786历史基准推进至781已知+11预留=charged792/1500，而非执行完整413次计划。

独立真实reconciliation `audit/ss2303-partial-independent-reconciliation.json` 字节SHA256 `e5da24beba5e48e9b820f0cb665662c3d7d652c7c2f9ae94815cbd673b764a0d`，progress字节SHA256 `60478ea797a6ece1a2b8b0b5440566099f7f35b5d15f3cd96026c6cbdc397394`；确认6个持久源响应、5已提交月份、2既有分区、剩余6 targets及禁重试，不授权恢复mutation。receipt已固定到只读guard，未知或改写receipt仍拒绝；保持BLOCKED，未改成PARTIAL。

维护结束及receipt之后新完整32source与SS四周期prefix已真实只读完成（`audit/post-ss-final-source-readback.json` PASS）。final32source字节SHA256 `ae1610ed5c37a5c1d215a43c79db0e543532e56e99d00b3dbb86e22483b00297`，28个非SS输入hash逐项稳定，仅SS4 source hash随部分提交变化；SS4 prefix全部BLOCKED，prefix字节SHA256 `3b05ddfa40e87e436f93941bd46fbcfec5d962fe193183b6b74cc8de55af5668`。可读source不代表完整prefix，SS12组合本轮保持BLOCKED。仅本地时序/身份guard通过，完整API前检因七品种资产driver尚未全部终态继续拒绝；本次未执行HTTP/PG/browser/mutation，检查见 `final-api/post-ss-freshness-readback.json`。其他七品种资产安全调度继续，96最终API/浏览器验收未由此完成。


## J历史动作读取根因修复与真实只读验证

窄修复 `ea98d0f23a10529d346962e199c6aef1391253d1` 已集成 develop，仅新增历史 action 增量读入口及 SavedFusionSources 消费，保留 Web 200,000 点限制、公式、收益、cursor和原候选构建脚本。历史读取绑定完整 saved revision/seq/snapshot/cutoff 与严格整数 manifest input_count，动作逻辑上限为输入数的两倍；不把此逻辑预算表述为实际融合构建RSS保证。集成定向70 PASS/4.09s（`audit/action-budget-develop-regression.json`）；独立 Review 无 Confirmed Issue（`audit/action-budget-independent-review.md`）。

真实 J source 只读验证 PASS（`audit/j-actual-historical-actions-readback.json`）：trend完整91,989动作，新扫描7.346s，wire hash与旧读取和 saved envelope逐值一致；oscillation完整223,664动作，新扫描10.468s，与 saved envelope wire hash一致，旧页面collector实际报 PRESENTATION_BUDGET_EXCEEDED。两策略正常结束、提前close和扫描中取消均释放连接并恢复只读设置，前后generation完全不变，零provider/写入/build。整个验证进程峰值731,496,448 bytes包含多轮对照，并非融合构建RSS。

原 J1m fusion 失败发生在 planner 读取 source 阶段，未创建 saved fusion stream；其11个既有资产前像保留复用。上述代码和source读取验证不能证明 J fusion 已恢复，需后续安全构建与独立资产读回；原 driver J行仍为 BUILD_CHILD_FAILED_NO_RETRY/BLOCKED，不改写旧失败。

JM1m fusion实际构建 completed，335.946s、peak RSS2,360,836,096 bytes（`jm/fusion-1m-build-capacity.json`）。当前 `remaining-build-progress.json` 的JM新行已为 INDEPENDENT_READBACK_PASS，四周期八个base/fusion构建事件全部COMPLETED，对应12资产独立读回；此状态由新progress读回证明，不由capacity推导。最终96组合 API/浏览器冻结验收仍未完成，未据此宣称板块闭环或整个P7完成。


## 历史805准备快照与当时阻断

原资产driver当前保存HC/I/JM读回通过，SS/J/SF为BLOCKED，SM现已落BLOCKED终态（1m基础完成，融合触发与J相同历史动作读取预算问题）；原J与SF失败记录不清除。SF1m旧基础planner因两策略合计输入超既有预算失败，未创建stream；新方案为trend/oscillation/fusion三个独立stage，沿用4M输入/16GB预算、不缩窗，其他三频九资产待精确复用。J/SF/SM forward目前尚无completed capacity；主代理确认J preflight通过、串行apply已启动，不能称恢复或允许下游READY。

最终候选使用 `run_final_preview.py` / `final_asset_readback.py` 和最终805源码（forward构建仍ea98）；原aef3五个构建脚本、310维护progress、SS固定receipt锚与charged792账保持原身份。aef3→ea98实际包含既有D1/W1/holding集成差异；只有8f540c0→ea98为query/newow_fusion窄修复。分钟saved identity、版本常量和实际advance_fusion_step等AST一致可支持旧资产复用调查，但最终source/hash/gen/formula及96页面仍须实际新代码验证。新phase脚本正在独立Review，尚未启动最终服务、HTTP/浏览器96审计。Review发现矩阵存在无效forward build被独立proof误提升READY的状态覆盖问题；已修正为有效完整构建/复用证据先行，错误代码、失败aggregate和hash漂移均拒绝，独立复核完成前该工具不用于最终验收结论。

剩余最小顺序：原串行构建自然结束与终态核对 → 修正Review确认问题 → J/SF精确forward preflight及串行构建 → 805完整32source与可读资产逐12独立读回 → 最终API96、真实浏览器96及D1/W1回归。SS12组合保持本轮BLOCKED/no-retry；局部阻断不得伪装通过，也不外推整个P7完成。

最终分钟Web读取修复已提交 develop `805ef4ddc2ce0a49f833c04316258de10fcb41a7`，ROOT相关46 PASS/4.21s；独立Review无ConfirmedIssue，追加真实SQLite验证后23 PASS/4.29s（`audit/web-hint-action-independent-review.md`）。仅分钟路径的同Bar hint动作读取改变，不提高Web200k预算、不改公式或D1/W1 collector。最终launcher/API/source/asset/matrix/browser准备identity统一805，forward容量ea98、旧driver/SSreceipt aef3分别绑定，不能全局改写旧证据。最终checkout仍newow-action-budget，由于SF/SM构建未完成暂不更新Git；尚无实际最终source/asset/API/浏览器验收。


## 历史805现场读回与验收推进

原串行构建已自然结束，原失败记录保留。J1m fusion、SF1m trend/oscillation/fusion、SM1m fusion分别按已审查的forward方案完成，未提高输入预算、未缩窗；各stage的plan/capacity/resume保存在对应forward目录。构建仍绑定ea98，完成后最终候选checkout fast-forward到805，tracked clean。develop exact805已正常push origin；未发布main/tag或切换正式Runtime。

最终805实际完整32source读取已完成：initial-source-readback字节SHA256 `43d6ac7b4e89799050d7340cf0d0a7343e2c60ead59e1edaa718f438708d09a3`，source-execution-binding SHA256 `919168c3fd5fa369b08368038d15bc56b2f23dd211de67ac169dd9ae34c40bb7`。读取前后实际源码路径/hash、clean checkout、冻结reader一致，所有32 source身份与SS维护后baseline一致。SS四周期prefix仍BLOCKED；不能以source读取PASS提升。

最终805七个非SS品种各12资产真实独立读回PASS，共84份：56基础和28融合；generation/revision/seq/formula/profile/source逐项绑定，disabled保持true，RB原资产复用未重建。最终输入28READY/4BLOCKED，基础56READY/8NOT_RUN，融合28READY/4NOT_RUN。API与Web候选端口8011/5175实际身份805、共同as_of `2026-09-24T07:00:00.000001+00:00`、local_candidate_readonly、realtime=false、固定八品种白名单。

首次最终API审计在RB12行发现审计器合同漂移，停止只读审计进程并保存于archive/final-805ef/final-api/attempt1-cup-handle-contract-drift；旧请求使用近一年统计窗口，不能改称完整2023窗口。分钟cup-handle精确NOT_APPLICABLE允许null snapshot；partner需策略自己的snapshot；include_fusion不能与history_before组合。审计器窄修后，root独立复核及七模块离线92 PASS/2.20s。新完整96 GET审计已启动，统计/曲线固定2023-01-01..2026-09-24，记录近一年，基础history_before与融合fusion_before分别验证。实际API终态、浏览器96、最新D1/W1和运行中的取消/超时恢复仍待验；离线测试及84资产读回不代替这些验收。

第二次API审计保留于archive/final-805ef/final-api/attempt2-partner-strategy-hash-contract-drift：10完成行中7READY、3dual被审计器错误的跨策略哈希等式阻断。exact805 `_fingerprint`明确包含strategy/formula/profile；真实RB1m两侧500条公开bars完整wire digest及图表窗口相同，metadata hash不同合法。root窄修后逐字段比较14个ProductBarOut字段和chart_from/through，保留每策略自身snapshot/hash/profile守卫；TDD先15失败，修复后七模块107 PASS/2.24s，risk独立复核66 PASS/0.07s。第三次完整96 GET已按审查后脚本SHA256 `37ef30b51dc3797937028c3150c7d46ff0a1f62e3ca2eee112a00d14bcacb427`启动，仍60s且无自动重试；旧两次结果不改写。

## c576 浏览器先行验收与取证修正（进行中）

第一次 RB60m 三模式先行验收发现任务脚本两处竞态：away只等待chart响应头便返回，晚发reference/MACD被取消；真实策略切换后立即bootstrap，取消尚待异步发出的目标请求。三行真实失败与原图已按SHA归档 `browser/attempt-c576b-rb60m-dispatch-away-not-settled/bytes-index.json`，不能改写通过。只修任务runner：显式按周期匹配真实terminal/记录DOM，动态请求与正文三稳定poll后离开away；真实UI动作在既有110s预算内等待自然dispatch。65s阶段预算与目标错误分类不变，不按URL豁免目标abort。根代理四组离线153 passed/3.43s；实际浏览器重验仍须终态，离线结果不代替验收。

当前 c576 API96 实际请求摘要（仅既有结果离线统计）：产品读取923次，其中911次HTTP200、SS12错误响应；成功请求中位1.195409s、最大34.325966s，最大响应80,121,306 bytes，41行实际观察到同日参考游标。API逐行仍须按各自checks判断，无cursor的合法状态不伪造同日跨页；这些数值不代替浏览器读回或构建容量。

浏览器后续先行尝试仍保留未通过原证据：`browser/attempt-c576b-rb60m-shared-loading-away-dom/bytes-index.json` 与 `browser/attempt-c576b-rb60m-waiting-card-navigation/bytes-index.json`。真实 lastSettle 已定位震荡30m DOM108卡中首个为列表外空仓等待状态，其余107条有序交易ID与实际107 items完全一致；不能把状态卡当缺身份交易。初始频率/模式连续控制动作还取消了中间目标chart请求，严格错误规则保留NOT_RUN，不自动豁免。只修任务导航收敛与真实记录容器定位，最终仍需实际重验。


## owner 七品种收尾：reference 快照恢复修正（2026-09-28）

真实 c576 页面试跑16行有12行机器检查满足、4行未满足；原始62文件保留于
`browser/attempt-c576b-full84-reference-recovery-gap/bytes-index.json`，这些不是最终页面验收。
RB60m震荡实际出现 chart200 → reference409 → reference200 后主图未恢复；已修复首次 reference
冲突先恢复原主图/证明再读页首，保留当前/历史窗口语义、单次重建、无token停止及切换取消。
已自审及独立 Review，97项定向测试通过，`pnpm build` 与 strict OpenSpec通过；
集成并推送 develop `00cea970e7e87295ddcc89f7937a34430fb64b11`。

新隔离候选 worktree `newow-fusion-read` 为 `9dd3714e596c1f5aebd6579b3f583fc2def93fe7`，
Git tree 与 develop 上述提交一致；候选前端与API都运行该精确提交以满足既有身份一致合同。
`5175/api/preview/identity` 是API代理身份，实际Web编译身份另由
`audit/web9dd-compiled-runtime-identity.json`记录，不将两个API路径冒充两个独立实例。
旧 c576 数据、资产、API证据保留原身份；完整后端依赖Git对象一致、仅Web恢复/测试/相关canonical变化，
复用条件及12个原证据SHA固定于 `audit/web-api-compatible-evidence-reuse.json`。
不重建资产或补数，不将旧API证据改写为9dd执行结果；新84页面须逐项真实重验并绑定9dd。
`audit/web-api-component-freeze.json`为已被取代的历史准备方案，其c576/PID31249不代表当前实例；
兼容收据`reuse_boundary`中旧API尾句只说明原证据身份。当前运行身份以实际编译/进程证明为准，API与Web均9dd，
原证据和收据字节不改写。独立离线收尾审计见`audit/final-handoff-independent-offline-review.md`：
12份原证据、后端Git对象和13份新phase helper/test哈希一致，无新生产Confirmed Issue；未终结的页面与回归仍待验。
SS12仍为owner明确暂缓，1m慢加载是第一版限制，正确性验收未放宽。当前新84页面尚未终验。

旧候选API PID31249已正常停止：4598.45s进程跨度，最大RSS1,269,104,640B，
涵盖RB冷热读、pilot及中断的页面试跑，不是纯84组合性能测量。
正式Runtime、8000/5186实例及main/tag均未变。

新9dd页面实测中的RB1m双策略保留未完成：`browser/rb-1m-dual-verify-9dd.json`原始错误为
`TARGET_REQUESTS_OR_RECORD_DOM_NOT_SETTLED`，不能由HTTP200提升通过。返回1m时主图20.199s完成，
趋势参考累计59.587s、震荡参考60.704s完成，后发的融合请求id32在65s观察截止时仍pending；
31份已返回响应无请求失败、页面或正文读取错误。派生`REFERENCE_DOM_FIRST_PAGE_MISSING`来自异常返回
未携带分页DOM字段，不证明初始首屏缺失，也不证明pending融合最后成功。按owner允许慢加载，
仅准备独立`browser/verify_return150.py`将1m返回后的统一观察期限改为150s，保持产品超时、provider、
缓存、其他阶段和七项正确性检查不变；原84批次和旧失败不改写。新复核仍须实际执行、逐图审查后才能验收。
该最初仅调整等待期限的wrapper SHA `8197731a14883120cd7bf624828834900b7a61531e28daa8e1ee13fefc8d0bdd`；
作者137项相关离线测试通过，独审初稿144项、最终payload释放窄修15项通过，
`audit/browser-return150-independent-review.md`无剩余Confirmed Issue。root默认准备命令实际返回
`PREPARED_NOT_RUN/browser_calls=0`，不将准备和测试表述为实际复核通过。


### 1m返回补验：单次reference恢复取证合同（已Review，尚未实际补验）

原9dd主轮中的HC1m双策略在return#26主图200后，reference#28返回
`NEWOW_SNAPSHOT_GENERATION_CONFLICT`；产品已发出#31新主图并得到同输入hash的200，
但原观察器看到旧409即终止，新参考/融合尚未终结，不能认定恢复成功。I、J的1m双策略与RB相同，
return65s截止时只有后发fusion #32在途、零HTTP错误/请求失败/页面错误；各原失败保留。

仅在新独立补验工具中支持既有一次reference恢复取证：限定return/1m/目标主策略页首409，
新主图必须新token、完整meta/input及每根14字段bars与旧主图一致；新primary与partner参考各自绑定
新chart身份及2023-01-01..2026-09-24完整统计窗口，新fusion绑定两来源profile/公式、窗口及revision。
cutoff严格按微秒验证。旧abort只允许唯一request_id、事件时钟及同参数成功新counterpart证明的
既有失效取消；其它HTTP错误、第二409、新请求失败或身份/窗口漂移拒绝，pending不提升通过。
raw失败保持，满足网络证明、最终DOM/曲线、零inflight及稳定终结后才调用原七项检查；视觉仍须root逐图审查。

最终独审冻结：wrapper `f98da440cf8bfc1c330d33bed6def37ee3aab3db347154e10190f5cfe213965a`，
pure contract `fa98b06a52b66aeb88687978fc597730e6f9a3a03c82bc81ba14e57ab10974f7`。
作者204项离线测试8.38s通过；独审204项9.09s及完整生成JS编译通过，4个取证证明缺口已窄修闭合。
独审报告 `audit/browser-return-recovery-independent-review.md`，SHA
`67cd589e28f53279ab55593c1737ac1e986393c1de1fa0a9ab71feae21b6f7a1`。
原13个phase helper/test pins与旧wrapper/test归档字节保持，未修改产品超时、数据、API或旧观察。
补验须待原84主轮自然终态后依据实际失败名单冻结并显式执行一次；目前仍为准备完成，不写实际通过。
