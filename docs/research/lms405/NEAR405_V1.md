# lms-near405-v1 完整近似研究策略

自审修正（尚未回放）：区域接触采用半区而非必须碰最外边界，否则严格ibar位于W内部将被结构性排除。此修改来自逻辑可达性，不来自回放结果。

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

无服务、无后台任务、无新交互HTML。静态报告完整回看明确标识，不冒充当时已知未来。以前宿主拒绝file://并明确禁止替代路径/浏览器绕过，本轮未重试、不启动HTTP规避；UI实际点击仍未验。该限制不阻塞本次用户指定的核心/CLI交付终点。OOS、成本与收益、Paper/实盘、UI均是独立后续，不把缺少原版公式继续列为本候选完成阻断。

**结论：近似策略核心完成。** 完整确定性决策与人工确认研究状态周期已实现；不是作者原版恢复、模拟成交账户或实盘可执行策略。
