# L.M.S 4.0.5 近似研究策略使用说明

**当前结论（2026-11-27）。** 两条研究路径均可复算。日常检查优先使用作者计划模式，保留价带用途、修订、分腿及人工判断。独立模式固定为 `lms-near405-v1`，可只用行情产生建议，适合隔离比较。两条路径默认均须显式人工确认才改变研究持仓。关于作者公开实际做单流程及出处，见[作者公开策略说明](AUTHOR_STRATEGY.md)。

## 两种模式的完整决策顺序

| 步骤 | 作者计划模式 | 独立模式 `lms-near405-v1` |
|---|---|---|
| 1. 准备 | 绑定实月、起始仓位、触发周期和决策前已知的最新版计划。区分目标、分水岭、保护、恢复及独立M。计划缺失、到期、冲突或用途不符时，依赖该计划的动作等待。 | 读取这个实月的完成5分钟K。形态K前六根分成两个三根组，后组高低两端同升为UP、同降为DOWN，其余为RANGE。六根K最低至最高为研究区间。 |
| 2. 首次进入 | 空仓须有计划许可及新方向信号。由经审查的输入指定触发、方向和数量。 | 内包或长影线形态由下一根完成K严格收越确认。趋势只顺向，需接触相关半区并收过区间顺向端点。盘整从相关半区确认后，收盘须仍在区间内。接受后开原方向1单位，冻结区间和方向。 |
| 3. 继续持有 | 分别追踪原仓、保护腿、独立M，等下一次有证据的动作。暂停供应公开价带时，相关新动作等待。独立退出仍需自己的条件和许可。 | 无失效、反向信号或恢复信号时持有。已入场计划不移动边界。 |
| 4. 增加保护 | 提前保护要求适用区域与提前触发，可部分保护。常规保护等量建立反向腿，已有部分保护时可按常规条件补足。 | 尚无退出条件时，新反向确认产生等量锁定建议。两腿各记1单位。 |
| 5. 恢复原方向 | 原计划仍成立，且有新原向确认和当次许可，平全部保护腿。独立M另行处理。 | 已锁定且无退出条件时，锁定后新原向确认产生解锁建议，只撤保护腿。仍属同一持仓周期，计划原期限继续计数。 |
| 6. 退出及反向短线 | `CLEAR_TREND` 完结原仓及其保护。独立M有单独开平条件，允许按已知数量部分退出。从锁定组合转为M须同时满足原仓退出及M新入场条件，并明确是否保留旧保护的一部分。 | 同一时点按风险边界、计划满12根评估K、环境反向、盘整到目标的顺序选退出原因。首次失效后持续建议清全部腿，优先于锁定或解锁。独立版没有抓M动作。 |
| 7. 回补或新开 | 已退出且空仓后，须有新触发、适用计划和新的确认。反方向新尝试单独建立方向和仓位起点。 | 只有风险退出可用原计划回补一次。新形态须在退出后，仍在期限内，当前环境不得反向。其他情况要有退出后形成的完整六根新上下文，再按首次条件建立新计划。 |

作者计划模式的行情入口可查**首次进入、恢复原向、区内保护、原空的1→1区前多向保护、原仓退出、独立M退出和回补**。退出要声明目标后反向确认或严格逆向收盘的用途，回补需先有空仓和明确许可。行情入口核对完成Bar，回放核对计划修订、仓位前像、动作和数量。许可必须绑定本次依据并严格晚于所有依据可知时点。文件中的来源输入由研究者核验，盘后文章或持仓展示无法提供事件时点的触发。 [首次进入条件与实月复算](REPLICATION_MANUAL.md#从作者计划和行情生成首次入场候选) · [退出与回补](REPLICATION_MANUAL.md#从作者计划和行情生成退出及回补候选) · [计划文件与复算命令](REPLICATION_MANUAL.md#使用计划信号与许可文件复算)

独立模式只接收明确的接受或拒绝记录。未接受的建议到下一根Bar的研究可知时点过期。`--timely-fixture` 仅用于显式测试确认。独立模式的六根K价区、严格收越确认、12根期限和一次回补上限均为自行补全。作者BBB/VPLUS、环境分类、动态降级、私有价带、账户手数及人工执行条件，分别保留在[规则与缺口记录](evidence/rule-identification.csv)。

## 复算结果与适用范围

| 验证 | 结果 |
|---|---|
| 九品种开发截图 | 70个侧别中29个各有相容报价。同合约双腿在同一候选报价标签相容为3/15。作者动作可评分样本为0。 [组合复算](evidence/PORTFOLIO_REPLAY.md#在九品种入口复算烧碱和焦煤的连续分腿) |
| 烧碱、焦煤连续持仓 | 烧碱在同账户等假设下相容路径保留原空20，撤旧保护多20，再开夜盘保护多20。焦煤旧空退出，日盘多腿可以全换，也可留1–13手、换入7–19手，夜盘今空为独立开仓。决定时点和先后仍有可区分的多条解释。 [两案计划重放](REPLICATION_MANUAL.md#p3计划驱动连续回放) |
| 独立价带 | 12组可比较，8组区间相交或端点相接，0组两端吻合。保留作者保护带的独立用途。 [价带核对](REPLICATION_MANUAL.md#p4独立价带生成更新与作废) |
| 日期外及跨实月 | 九个2701实月在2026年11月16–20日参考毛损益合计−460元，假设每边3元加1跳为−2,460元。另两实月JM2609及SH2611同成本情景分别−624元、−756元。留出阶段未见可评分作者动作，也未覆盖解锁与回补。 [留出结果、复算命令和成本边界](REPLICATION_MANUAL.md#p5留出验证口径) |

研究可复现两种模式的建议和条件持仓。当前用法限于研究与盘后逐项核对，历史手续费、涨跌停和可成交盘口仍缺，独立候选近期留出结果未显示整体优势。

**连续回放。** 给出按时钟排列的计划窗口后，后续候选自动承接已确认的仓位。无许可、计划暂停、换版或仓位不满足时保持原状态。保护补足可用区内确认，独立M进入和旧保护转M可连接显式外部证据及独立许可。焦煤两条条件路径均可连续走到夜盘新空。作者实际动作的可评分样本仍为0。 [连续回放样本和命令](REPLICATION_MANUAL.md#连续行情和仓位回放) · [焦煤混合证据复算](REPLICATION_MANUAL.md#焦煤抓m证据与夜盘行情持续回放)

## 独立候选冻结说明

最初自审将区间接触从最外沿改为相关半区，使严格内包形态也能参与。此口径在后续冻结样本中已复算。

规则冻结于2026-10-29、基线54eaba696之后、本轮回放之前。实现新模块，不改keybar/proposal/confirmed/inspired旧身份。使用brainstorming完成取舍与自审、TDD实现及独立时序Review；用户已授权补全，不再请示阈值。只本地提交，不触及active、生产行情或交易。

## 作者依据与候选补全

作者框架的来源入口为[AUTHOR_STRATEGY](AUTHOR_STRATEGY.md)：价格空间/关键K、强弱路径、趋势与盘整、双腿保护/恢复、试错及回补、人工参与。作者精确环境、区域、入退场与数量公式未知。本文下述所有数值、逻辑组合、时序、期限与回补上限均为**本候选补全**；不是作者原规则或原版准确率。保留单位双腿，Fill/performance/cost/margin均null、executable=false。

取舍：不使用MA/RSI/MACD/ATR；不选需要事后回填的拐点，采用严格历史滚动价格区域。前6根足够暖机，不要求拐点才能交易。未采用ebar/tbar、特殊GAP预知、抓M、跨品种共振、动态降周期、加仓或账户风控，不设置UNKNOWN隐藏Gate。

## 输入、环境、区域、形态

- 一个固定物理合约、completed 5m，显式相邻输入序列；OHLC用Decimal。Session与coverage由冻结MDS快照/provenance保证，核心不自行猜缺口或用时钟造Bar。中断/不完整数据显式失败，不下载、不补值、不主连替代。
- 每个评估用形态K S与紧随确认K C。严格早于S的6根Bar记为W；不足6根为WARMUP，不开仓（至少8根才能首次评估）。W的前3根A、后3根B：若maxHigh(B)>maxHigh(A)且minLow(B)>minLow(A)，环境UP；双双严格降低为DOWN；其余包括相等为RANGE。不用L/M/S包装。
- 区域L=minLow(W)、U=maxHigh(W)，L<U才有效。空仓每次基于新W生成候选区域，已接受入场计划冻结L/U、环境及方向，不漂移止损；生命周期内的新环境仅用于失效判定。无自动回填、锚点替换或重绘。
- 关键K复用`lms-keybar-approx-v1.classify`：ibar为相邻上一根高低区间内严格内包；pinbar实体>0、长影>=3倍实体、另一影<=实体。C收盘严格高于S.high为LONG、严格低于S.low为SHORT；pinbar必须与其方向一致，ibar不受未确认pinbar否决。等价、仅影线越过、无形态均无方向。
- 信息可用时刻为C.end+1微秒（研究离散可用时刻，不是实际行情接收延迟）；S必须严格晚于当前状态since。仅在输入权威Session内已完成Bar评估，日夜均允许；不额外引入钟点交易窗口。

## 首次进入与新计划

显式初始空仓(0,0)、无原方向。当前方向D必须满足：

| 环境 | LONG进入 | SHORT进入 |
|---|---|---|
| UP | S.low<=U 且 S.high>=(L+U)/2，且 C.close>U，且已确认LONG关键K | 不进入 |
| DOWN | 不进入 | S.high>=L 且 S.low<=(L+U)/2，且 C.close<L，且已确认SHORT关键K |
| RANGE | S.low<=(L+U)/2 且 S.high>=L，L<C.close<U，且已确认LONG关键K | S.high>=(L+U)/2 且 S.low<=U，L<C.close<U，且已确认SHORT关键K |

UP/DOWN突破与关键K突破均须满足；RANGE不是任意中区交易。数据退化L=U不形成计划。新入场建议为ENTER_LONG/SHORT，接受后单位1、创建新cycle_id，原方向取本次方向，计划ID绑定规则、合约、6根W、S/C及方向。研究状态生效known_at，不能将其当作确认K成交。风险边界LONG=L、SHORT=U。新计划最后有效评估序号为首次建议生成C序号+11；从+12开始期限失效，12表示12根输入Bar，不是自然时钟12*5分钟。

## 持有、保护、恢复、退出（按顺序）

每根新completed C先检查本周期入场后历次已揭示Bar与环境；以下失效一旦发生，不因价格回归而撤销，持续建议CLEAR至接受：

1. RISK_INVALID：LONG收盘<=冻结L；SHORT收盘>=冻结U（触碰即失效）。
2. PLAN_EXPIRED：当前C序号>=计划首次C序号+12。
3. REGIME_INVALID：LONG出现DOWN、SHORT出现UP（当前评估的W环境）；暖机不足时不会发生已入场状态。
4. RANGE_TARGET：仅原计划RANGE，LONG收盘>=U、SHORT收盘<=L。进入时要求严格区域内，故不在入场同时命中目标。

逐Bar按时间寻找首次失效并冻结其原因；同一Bar同时成立按上述原因顺序取首个。后来的风险事件不把已发生的目标退出改成可回补的风险退出。CLEAR清gross：单向1、锁定2；无自动反手。未获确认的风险退出只是建议，不能冒充已平仓。

没有失效时：单向遇新反向确认关键K→LOCK等量另一腿；同方向保持。锁定遇新原方向确认→UNLOCK_LONG/SHORT，仅平反向腿；反方向保持。保护恢复仍受形态S>state.since约束。锁定也执行上面全部退出条件，期限不因锁/解锁延长。

每Bar最多一个建议：CLEAR > LOCK/UNLOCK > REENTER > ENTER；只在空仓考虑后两者，故不可能同Bar清仓再自动入场。接受动作之后，旧S不能触发下一动作。窗口末不强制平仓；报告OPEN_DIRECTIONAL/OPEN_LOCKED/FLAT与未接受建议。

## 退出、回补与重复失败

- CLEAR接受后保留计划及退出原因，但本周期关闭。只有RISK_INVALID退出可尝试同计划回补：原方向、新S严格晚于退出known_at，沿用冻结区域/环境的进入条件，当前新W环境不得与原方向相反，且未到原计划+12期限。回补必须新确认，不叫解锁。
- 每计划最多2次进入（首次+一次REENTER）。REENTER接受创建新cycle_id、保持plan_id和原期限、attempt=2。再次风险失败则CLEAR，禁止第三次同计划回补。
- 非风险退出、期限到、回补耗尽、或新环境相反时，同计划不再进入。允许新计划，但新计划W的全部6根必须严格晚于最近CLEAR的known_at，且新S/C满足首次条件。新计划可换方向；不强行延续上一周期original_side。六根新行情不是重新使用旧信号的冷却漏洞。
- 同计划回补时，先前已经结束周期的风险失效不延续到新周期；新周期仍从新入场Bar之后独立检查风险。原期限不重置。

## 人工确认、时序与恢复

所有动作都是建议。人工模式默认零确认；决定最小字段decision_id/proposal_id/state_fingerprint/decision(ACCEPT或REJECT)/decided_at/known_at/record_kind，历史情景另存实际recorded_at。规则、cycle、plan、合约显式字段如提供必须精确一致；不得提供任意after/action绕过核心。

建议下一根completed输入Bar的end+1微秒过期；known_at与decided_at均严格晚于建议生成时刻，known_at>=decided_at且严格早于过期。同刻Bar过期优先；同有效时刻冲突决定全部拒绝。无ACCEPT不改变持有状态，REJECT不应用建议；新Bar可对持续风险重新建议，但不可重复应用旧proposal。相同ID同内容幂等，后来同ID篡改只拒后来记录，不撤销历史；前像/cycle/计划/版本/合约错配拒绝。checkpoint绑定规则hash、输入前缀、初始状态、决定内容和当前研究状态，重算验证后只追加新时间后缀；迟到记录不能改写已冻结前缀。

独立演示模式必须显式`--timely-fixture`：对当时新待处理建议在生成+1微秒写TEST_FIXTURE决定。它不是用户操作、作者交易、Paper或收益；人工模式不默认接受。禁止伪造HUMAN记录。

## 例子与代码对应

区域[100,110]、UP，S区间[108,111]且形成合法关键K，C.close=112：建议ENTER_LONG；若接受后新反向关键K出现且仍高于100，建议LOCK；新原方向关键K建议UNLOCK_LONG。任一后续收盘<=100则优先CLEAR，即使同根也有恢复信号。盘整计划[100,110]内低侧关键K确认到103可进入多，收盘>=110建议目标退出。风险退出后新低侧关键K确认回103可一次REENTER；再失败禁止同计划第三次进入。例子仅阐明条件，合成完整OHLC见测试。

实现/验收检查点在下方更新；不以回放收益调参。

## 执行检查点

- [x] 现场develop/54eaba696与干净工作区确认，旧资产hash前像冻结。
- [x] 规则在本轮样本回放前冻结、自审。
- [x] 新核心、CLI、人工与fixture路径。
- [x] 生命周期/时序/重启测试及独立Review。
- [x] A/B/C固定样本、稳定生成、拒覆盖与旧资产hash复核。
- [x] 完整说明与本地交付验证已完成；本地提交身份以Git记录为准。UI不开发，宿主限制单列；OOS/收益/实盘不在本轮。

## 实现入口与合同对应

| 规则 | 代码 |
|---|---|
| 固定参数与规则hash | `packages/quant-core/guiyi_quant/lms_near405.py` 的 `RULES/RULE_HASH` |
| 严格过去6根与3+3环境 | `context` |
| 原ibar/pinbar与收盘方向 | `classify`（旧模块只读复用）、`_direction` |
| 半区接触与趋势/盘整入场 | `_entry_allowed`，半区使用2*price与L+U精确比较，无浮点 |
| 首次失效锁存与退出 | `_invalid`，按Bar时间找第一失效，再按同Bar原因顺序 |
| 单Bar动作优先与回补上限 | `evaluate` |
| 新cycle、双腿/清gross、known_at生效 | `_apply`，复用既有`Action/apply_action` |
| 决定校验、过期、幂等、恢复、fixture | `replay`，初始状态由首Bar.start-1微秒的显式空仓假设产生 |
| 快照/Session校验与静态产物 | `scripts/research/lms_near405_replay.py` |
| 生命周期与边界场景 | `services/quant-api/tests/lms405/test_near405.py` |
| 报告/拒覆盖/转义/缺Bar校验 | `services/quant-api/tests/lms405/test_near405_cli.py` |

规则hash：`ba4a3aa30e499496196bfa36afcd18907e4f4cf5bd50fc6e56cab91d9ef43d07`。它绑定参数与身份；每份报告另绑定完整核心、CLI、keybar源码hash，因此相同规则参数不能冒充相同代码实现。报告中的规则字典复制隔离，不能通过修改输出改变下一次运行的规则。

### 自审与独立Review结论

独立Review已完成，当前无剩余重要Confirmed Issue。发现并已修复：退出原因应锁定**第一次**失效，而非后来风险重写目标退出；同刻逆序冲突与无效记录在重启后的报告顺序不同，现统一按已知时间及内容hash排序，保留记录内容原样。同刻全部拒绝，不按文件顺序选赢家。自审另外用失败回归修复极端Decimal尺度下半区比较精度、报告可变规则对象影响后续运行；均未因市场回放结果改变参数。

独立定向复核42 passed。本轮全LMS：

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:services/quant-api:packages/quant-core:scripts/research services/quant-api/.venv/bin/python -m pytest -q -p no:cacheprovider services/quant-api/tests/lms405
```

实际200 passed、1 skipped（API环境缺matplotlib，既有渲染测试另用系统Python补跑）。相关四文件ruff通过、secret scan 0、diff检查与文档本地引用检查通过；系统Python既有真实渲染5 passed。双向空→进入→保护→恢复→退出、入场风险失败、一次回补再失败、锁定清gross、目标/环境/期限退出、无确认/拒绝/过期/等价/错配/迟到、前缀/批量/重启与非法数据均有确定性验证。

## 固定样本结果

本轮直接读既有冻结CSV，未下载、未补暖机、未缩窗、未换合约。各前7根显式WARMUP，整个窗口保留；A沿用原冻结hash，不重新声称权威Session现场查询。B/C精确CSV hash与既有MDS provenance绑定，并核对权威Session全部预期5m Bar集合完全相同；核心不以5分钟墙钟间隔猜夜盘/午休缺口。任意无provenance快照仅标`FROZEN_SNAPSHOT_HASH_ONLY_NO_NEW_SESSION_CLAIM`，不能宣称通过Session完整性验收。

最终本地报告根`output/lms-near405-v1-20261029/`，`summary.json`列全部分母，六份静态HTML/JSON/CSV报告分开人工与fixture。`synthetic-fixture-paths.json`单列合成完整生命周期，绝不计市场匹配。

| 样本/交易日 | Bar | ibar/pinbar | UP/RANGE/DOWN/暖机 | 人工模式建议/确认/转换 | 及时TEST_FIXTURE转换 | fixture末端 |
|---|---:|---:|---|---|---:|---|
| A JM2509 2025-07-21至22 |138|21/7|69/45/17/7|6/0/0|6（3进入、3退出）|FLAT|
| B JM2701 2026-09-21至10-09 |573|61/55|182/223/161/7|10/0/0|20（10进入、10退出）|FLAT|
| C SH2701 2026-10-26至27 |138|10/10|24/45/62/7|3/0/0|6（3进入、3退出）|FLAT|

人工模式所有建议因下一输入Bar过期；不是无信号。fixture全部record_kind=TEST_FIXTURE、用户操作数0，不叫真实交易笔数。退出原因：A环境失效3；B环境失效8、期限1、盘整目标1；C环境失效1、期限1、风险1。真实三样本没有触发LOCK/UNLOCK/REENTER，完整路径由独立合成测试覆盖；不能据此声称完整市场行为匹配。全部为已见开发样本，无盲测/OOS/收益结论。

A原hash `71c668cc3874cfdcb1c52b47c26615a89ed455977bfb5c80883a9e18b3cb91b3`；B新CSV `9d9d2af223effe39e3f89be2c952a5a621a0d13fe16b927d7389d11fa4131352`；C新CSV `4583c1d84f5739e9a750b286c59ecdd4d2a6925f9e5acc03904f64496f84bdb4`。B/C provenance在`output/lms-confirmed-samples-provenance-20261029/`，与原JSON使用不同序列化/hash，不混用。

两独立A fixture CLI进程全部输出逐字节相等；拒覆盖返回2，原文件逐字节未变。旧keybar/proposal/confirmed核心及两组冻结报告共12文件hash一致；旧inspired及其他原版研究文件未改。最终源码与参数均绑定在新报告，不覆盖旧报告。

## 可运行命令与使用方式

人工模式默认零确认（新目录必须不存在）：

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=packages/quant-core:scripts/research services/quant-api/.venv/bin/python scripts/research/lms_near405_replay.py --input output/lms405-jm2509-july22-20261017/market-read-authorized/JM2509_2025-07-21_2025-07-22_5m.csv --input-sha256 71c668cc3874cfdcb1c52b47c26615a89ed455977bfb5c80883a9e18b3cb91b3 --output /tmp/lms-near405-human-new
```

独立及时确认演示用同命令增加`--timely-fixture`并更换output。提供实际研究确认文件则使用`--decisions /精确路径/decisions.json`，不可与fixture模式混用；历史假设决定应另存实际recorded_at。恢复增加`--checkpoint /原报告/checkpoint.json`，提供同样完整Bar前缀及新后缀；人工作业只接受known_at晚于checkpoint的新记录，不能补造历史接受。B/C改用相应CSV与上述hash，并增加`--provenance output/lms-confirmed-samples-provenance-20261029/对应合约-provenance.json`。

静态报告包含评估、建议、决定、转换时间线及恢复检查点。浏览器实际交互未验。日期外与跨实月已完成参考成本检验，使用边界见上文。
