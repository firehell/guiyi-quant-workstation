"""Build a reader-facing report from completed, independently checked results."""
import json
from pathlib import Path
from decimal import Decimal as D
R=Path(__file__).resolve().parent
NAMES={'original':'原火天大有双向','atr2':'固定2倍ATR退出','atr3':'固定3倍ATR退出','trend_filter':'牛哇趋势方向过滤','osc_exit':'牛哇震荡辅助多头退出','long_flat':'火天大有仅多头对照','newow_trend':'牛哇趋势仅多头','newow_oscillation':'牛哇震荡仅多头','newow_dual':'牛哇双策略仅多头'}
def main():
 rows={}
 for p in (R/'runs').glob('*/summary.json'):
  s=json.loads(p.read_text());assert s['status']=='COMPLETED';rows[p.parent.name]=s
 assert len(rows)==40
 for sym in ['TA','MA']:assert (R/f'{sym}-valuation-verification.json').exists()
 lines=['# PTA／甲醇：火天大有与牛哇策略优化研究结果','', '**结论：本轮固定单因素全部未达到进入组合的门槛，不推荐新策略晋升。PTA保留原火天大有作为研究基线；甲醇原双向长期亏损，暂不扩大使用。**','', '研究范围：2023年1月起至北京时间2026年10月30日15:00；两品种各10万元、最多一手、70%新开保证金准入。40组全部完成请求截止。全部为离线执行模型结果，非真实账户收益；1／2 tick仅作用于分钟代理，Tick腿沿用盘口模型。','', '## 1. 同口径结果','', '收益分母是初始10万元，包含期末浮盈亏与已发生费用；不强制平末仓。牛哇仅多头，必须与火天大有仅多头行比较，不能直接把双向收益差异归因为指标优劣。','']
 for sym,name in [('TA','PTA'),('MA','甲醇')]:
  lines += [f'### {name}','', '|方案|1 tick收益|2 ticks收益|闭合笔数 1／2|最大回撤 1／2|','|---|---:|---:|---:|---:|']
  for policy,label in NAMES.items():
   a,b=[rows[f'{sym}_{policy}_slip{i}'] for i in [1,2]]
   fmt=lambda x:f'{D(x):.2f}%'
   lines.append(f"|{label}|{fmt(a['period_return_pct'])}|{fmt(b['period_return_pct'])}|{a['closed_trades']}／{b['closed_trades']}|{fmt(a['max_drawdown_pct'])}／{fmt(b['max_drawdown_pct'])}|")
  lines.append('')
 lines += ['## 2. 每一步带来的实际认识','', '1. **基线复现完成。** PTA两档分别109325／106535元、141笔，费用均4245元；ATR可用样本对照与原版相同。月度原Event净利润6085元、历史重建6075元的旧产物哈希及逐笔金额再次核对通过；本轮没有重新生成实际实时Event。','2. **固定ATR退出未改善净期望。** PTA两档回撤下降，但2倍ATR由盈利转亏，3倍ATR也明显削弱净收益；甲醇两档均比原版更差。不能仅凭回撤降低推荐止损候选，也不能把结果推广为任何止损都无效。','3. **同向趋势过滤过于稀疏。** PTA只剩14笔、甲醇11笔，均低于30笔门槛；两档仍亏损。牛哇YELLOW／BLUE是明确趋势带方向，不是把空仓状态解释成做空。结果提示这套同向硬过滤与原火天大有逆向机会并不互补，暂保留背景解释用途。','4. **震荡辅助退出没有解决主要问题。** 本轮只用CLEAR提前结束多仓，不镜像做空；净期望下降。所有退出仍用后续执行报价，未把页面参考价当成成交价。','5. **甲醇完整验证推翻近期高胜率外推。** 月度仅3笔全胜不能证明长期优势。只做多对照1 tick盈利很少、2 ticks转亏，显示方向归因值得继续研究，但优势不能覆盖成本压力，暂不推荐采用。','6. **牛哇独立与融合均无正收益。** 本次同成本执行下，两品种三套牛哇只多头对照全部亏损，融合交易次数更多，并未带来净收益优势；这些是固定公式／执行模型／样本的结果，不能外推所有周期或未来版本。','7. **组合按门槛不运行。** 两档必须同时降低最大回撤、降低最大单笔亏损且闭合净期望不下降，至少30笔；本轮单因素无一合格。继续叠加将违反预先门槛，故记为NOT_RUN_GATE_NOT_MET。','', 'PTA 1 tick逐笔对齐进一步说明：2倍ATR改善25笔原亏损，但把28笔原盈利变成亏损，闭合净额合计少14190元；3倍ATR改善19笔原亏损、把12笔原盈利变亏，闭合净额少6670元；震荡退出改善22笔原亏损、把11笔原盈利变亏，闭合净额少6770元。这是已实现路径对照，不能直接解释为被删除信号的未来因果效应。详见trade-differences.csv。', '', '## 3. 建议如何使用','', '- **PTA：** 原版继续作为研究和观察基线，不把这次失败改进替换进正式策略。原版的年度波动、大亏损及薄净期望仍存在；一手固定仓位结果不支持放大资金或杠杆。','- **甲醇：** 暂不把近期月度表现用于扩大双向参与。只做多仅是下一项研究线索，不是本轮合格候选。','- **牛哇：** 趋势用于背景解释、震荡用于区间观察；暂不成为火天大有隐藏Gate。双策略并不等于双重确认，本次不建议因融合而增加交易。','- **唯一最小下一步：** 先按逐笔差异复盘PTA原版大亏损与被提前退出的原盈利交易，明确新的失效条件假设；在提出新假设前不继续搜索阈值。','', '## 4. 数据、验证与剩余边界','', '甲醇仅在研究副本补13个旧合约退出日4365根1m，另补MA2611的11日执行参数及MA2701/2026-10-26原空手续费字段。最终零退出报价缺口；原MA SQLite和旧facts未改。共18次业务请求，额外quota/SDK初始化流量另记；保留失败attempt，不重发未知请求。详见[甲醇数据核验](ma_data/report.md)。','', '原公式按当时32根已完成Bar窗口求末端信号，冻结首次发现；历史重建信号不是当年实际Event。原XMA可重绘，不采用事后图形买卖点。两品种特征逐owner匹配原输入hash；策略、输入、费用与执行身份见study-identity.json。','', '全部曲线从原始入场Fill和可信mark独立重建权益、保证金、费用；逐笔导出与结果SHA另经独立核对。精确点数、资源峰值及最终Review以对应JSON／review.md为准，不把cash＋floating自校验冒充独立重放。','', '2023—2026已看过的数据属于开发及历史稳健性证据，不是独立OOS。本轮没有合格唯一候选，因此没有启用新的前向任务。未来如另有合格候选，仍须8个交易周且30笔闭合，两者均满足才能评估；这些自然证据不能一夜补齐。','', '未修改正式公式、Canonical/Catalog、生产DB、Runtime、Broker或通知。其他任务STATUS.md修改不纳入提交。','', '## 可追溯文件','', '- metrics.csv／metrics.json：40组完整指标与方向、退出年归因。','- gate.json：预先门槛结论；trade-differences等文件以compare.py输出为准。','- TA-annual-valuation.csv／MA-annual-valuation.csv：按权威交易年、前次估值衔接，不按闭合日期重复计利。','- runs/：逐组订单、Fill、交易和SQLite曲线；baseline-final/保留最终冻结源码基线复跑，原attempt保留。','- baseline-audit.json、independent-verification.json、TA-valuation-verification.json、MA-valuation-verification.json及review.md：实际验证。','', '复算入口与命令见[README](README.md)。数据worker单线程串行，384MiB警戒、512MiB停止。']
 (R/'report.md').write_text('\n'.join(lines)+'\n')
if __name__=='__main__':main()
