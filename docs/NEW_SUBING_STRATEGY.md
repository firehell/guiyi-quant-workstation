# 新苏冰策略 V1

本文件是 owner 已批准的新策略合同。身份 `new_subing_v1`；首版为固定参数顺势波段研究，
不覆盖旧苏冰预警，不放宽 JM Paper，不启用实时、通知、Shadow、Broker 或自动订单。
原文明示 / 归一补充 / 用户选择分别保留来源标签，研究收益不冒充苏冰本人收益。

## 批准的规则

- MA21 为简单移动平均；BOLL=MA21 ± 2×总体标准差（21根）。MACD(12,26,9)，sma_window seed、柱乘2，六位投影。ATR14 Wilder SMA seed。交易金额 Decimal。
- 日线决定方向：多头最新已完成 close>MA21 且 MA21>三根前MA21；空头对称。周线只作上下文，未知不阻止入场。
- 主决策5m、确认15m：两周期close与三根MA21斜率均同方向。仅 completed 同物理合约输入，日周禁止未来。
- 最近10根5m的close−MA21非零符号切换≥3为震荡，禁止开仓/加仓；距离abs(close−MA21)/ATR14≤1，ATR未知/零不可评价。
- 夜盘/日盘首次开盘20交易分钟禁开/加仓；小节休息不重置。时间只来自权威Session。
- 五项至少三项：①5m close与MA21三根斜率同向；②最近3根同向MACD交叉，交叉时max(abs(DIF),abs(DEA))/ATR14≤0.1，最近两根柱同向且绝对值增加；③最近3根同向穿越BOLL中轨且当前保持；④最近3根至少一根volume≥该根之前20根均量×3，均量>0；⑤最近3根收盘突破该根之前20根高/低且当前仍在冻结水平外。
- MA/BOLL保留五项计票，页面提示相关性，不声称信息独立。
- 基础约束+三票且有最近3根的新MA穿越/MACD交叉/区间突破才创建setup。多触发优先区间、MA、MACD，保存全部依据。冻结区间水平，其他冻结触发MA21；随后3根5m收盘均保持水平外，才确认。返回水平内立即失效。确认重查基础约束；MACD反向失效。不得回填。每触发只用一次，等待不叠加setup。
- 每交易日首次实际模型开仓锁方向，当日不反手。清仓后不由持续HOLD自动重建，须新触发。
- 各品种独立初始资金100000元，统一净仓/平均成本，无批次保护，无锁仓。
- 首次/两次加仓预算3:2:1；首次保证金预算=当时权益10%，后两次为首次预算2/3、1/3。首次止损风险=权益0.5%，后两次1/3%、1/6%；总风险≤1%、总保证金≤30%。风险计入往返费用和滑点。
- 整数手数=min(保证金允许手数,风险允许手数)向下取整；两次加仓还受floor(首次实际手数×2/3)、floor(首次实际手数×1/3)约束；不足1手跳过，不凑手数。
- 加仓须净仓盈利、发生回调但未破冻结起涨/跌水平、再次确认同向区间突破、突破Bar三倍量、OI较前根增加≥0.5%。OI缺失/基准0禁止加仓，不阻止首次。最多两次，任意减仓后该轮禁止加仓。
- 首次硬止损：多头min(确认MA21,冻结突破水平)−tick；空头对称；不在入场风险方向拒绝。保护线只收紧。
- completed 1m close检测退出，后续可交易1m执行；不是触价止损模拟。
- 固定优先级：账户停机 > 全清 > 一次减仓 > 加仓 > 首次开仓。
- 当equity≤交易日初equity×0.98：取消开仓、停开并安排全清，同日不可复位；新交易日仅flat且无挂单才复位。
- 全清：硬止损失守；completed5m收盘穿过MA21；日线明确反向；入场后6根completed5m仍无净浮盈；最后Session收盘前2分钟亏损仓。盈利且未触发退出可跨日。
- 减仓：前12根5m内净浮盈≥实际占用保证金30%；净浮盈自本轮正峰回撤≥20%；盈利时1m close穿过此前最新completed5m低/高；确认背离并有最近3根反向MACD交叉。
- 每次减仓ceil(qty×20%)但保留1手。仅1手记录无法分批，不改全清。快速盈利/峰值回撤每轮各一次，高低点每锚点一次，背离每pivot对一次；同刻多条件一次减仓。
- 背离pivot左右各2根，右侧2根完成才可知；多头最近两价格高点抬高、对应DIF降低，空头对称。无回填。
- 净仓达到2×入场ATR盈利距离后，止损收紧到平均成本加预计平仓费用保本线；跳空仍可能亏损。
- 连续两轮已平净亏损，当交易日暂停新开。

## 数据与执行

- MarketDataService/Catalog/MainContractMap/Calendar/Session唯一入口；同合约lifecycle预热，owner有效区间输出。
- 首轮AL/RB/TA，2024-10-14..2026-10-09固定窗口，预热不计收益。缺口精确报DATA_INSUFFICIENT/EXECUTION_FACTS_MISSING，不换品种/缩窗/插值/跨频替代。
- 双向整数手研究账户，模型执行仅bar.start > max(decision_at,effective_after)的后续1m open，1tick基线；开仓/平今/平昨分别收费，多空保证金、乘数、tick、限价事实逐日绑定物理合约。
- 成交前重查资金和风险，只能缩量或拒绝；零量/封板/缺事实不造Fill。持仓或挂单跨owner切换中断，保留旧事实，无自动换月。独立合约段不可拼成年账户。
- 研究内核无I/O；CLI只读行情与事实，写任务结果包，无生产账本。费用/执行约束复用已有实现而非复制。
- baseline/double_commission/double_slippage独立100000元。前一年开发诊断、后一年冻结历史验证、四季度固定参数滚动诊断；未见性未证明不得标独立OOS。

## 对外合同

页面 `/research/new-subing`，只读展示规则来源、三个品种、setup/decisions、净仓/模型交易、权益、拒绝与证据状态。
只读API前缀 `/api/v1/research/new-subing`：`/profiles`、`/runs`、`/runs/{run_id}`，
`/runs/{run_id}/decisions`、`/trades`、`/equity`支持受限分页。GET不启动回测/下载。
`/runs/{run_id}/equity-curve`只读完整冻结窗口，独立于明细分页；返回run_id、结果sha256、
原始权益点、total、sampled、sampling_version及窗口/状态。可传sha256绑定预期结果，不匹配返回409。
max_points默认2000、范围4—2000；超过预算时保留首末点、全局及连续桶内极值、物理合约/segment/status变化
及空值中断两侧原始点，按原顺序返回，不插值，不修改冻结summary。必保边界超预算返回
CURVE_BOUNDARY_BUDGET_EXCEEDED；时间无时区、倒序、非有限权益返回CURVE_FACTS_INVALID，不缩窗掩盖缺口。
页面使用统一收益面板与真实时间轴，显示模型账户权益元值、账户收益和账户回撤；抽样仅用于绘图。
明细“加载更多”追加已核验同run_id/hash记录，筛选明确仅覆盖已加载范围，不影响完整窗口摘要或曲线。
显式配置任务结果根 `GUIYI_NEW_SUBING_RESULTS_ROOT`；只按index.json精确索引run-id及SHA，不glob，不接受任意路径。
结果标识code SHA、formula/profile/risk/execution版本、input/facts hashes，source=historical_replay、auto_order=false。
运行产物schema_version=1：metadata,summary,decisions,trades,equity,diagnostics；未知/中断不得写作零收益或通过。

## 来源与证据

Notion《交易从此开始》：
- 交易系统 https://app.notion.com/p/3705b8452a1a80509c01fd074770af4b
- 不同周期 https://app.notion.com/p/3715b8452a1a8041a21aea76318a18ec
- 周期选择 https://app.notion.com/p/3715b8452a1a8045b1b7c378482ec5bb
- 原则 https://app.notion.com/p/3715b8452a1a806bb63df413405c30e3
- 理念 https://app.notion.com/p/3705b8452a1a8036ac19c54b7d66fd08
- 日志 https://app.notion.com/p/3715b8452a1a80eeac2fff3e8957fb2a
- 经典案例 https://app.notion.com/p/3705b8452a1a80fdb9e4fda13ae6d3c1

截图尚未逐图解析，CASE_PARITY_PENDING。工程构造fixture不得冒充原案例。案例缺口不阻止独立编码，阻止案例一致性声明。
用户明确选择MA21、日线方向、1m完成检测、三票、统一净仓；模糊阈值采用本版固定定义，未来按品种新profile。
所有成交/收益是模型事实；不声明苏冰本人收益、未见OOS、持续Paper或正式Runtime。

## 验收

定向边界、未来函数/prefix/batch/restart、三品种只读数据实跑与成本压力、API/页面、旧苏冰/Newow/JM Paper回归及独立Review。
工程完成与数据/案例证据分别报告；没有盈利门槛，不自动晋升。已批准范围内测试、提交、push、集成develop；不发布或切Runtime。

冻结结果读取：运行摘要返回与同一次已校验结果包一致的 `sha256`。Web 将摘要、当前明细和完整权益绑定到同一 `run_id + sha256`；首次所选明细重新核验，其他 Tab 和分页按该 hash 使用现有有界会话缓存。未选明细不预读；单类明细最多显示1000条，保留真实游标并提示容量上限，不据此改变完整摘要或权益曲线。
