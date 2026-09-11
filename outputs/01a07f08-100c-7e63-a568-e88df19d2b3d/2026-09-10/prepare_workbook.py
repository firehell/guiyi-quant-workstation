from pathlib import Path
import json
p=Path(__file__).resolve().parent;a=json.loads((p/'analysis.json').read_text());m=json.loads((p/'market.json').read_text())
s=(p.parent/'2026-09-09'/'build_workbook.mjs').read_text()
s=s.replace("推送准确度收盘复盘`","推送复盘（PARTIAL）`")
s=s.replace("行情截至当日日盘收盘。","预警仅截至10:15；分钟行情仅到13:33，全天覆盖不完整。")
s=s.replace("有利比例=方向变化为正的条数÷已满窗口条数。保持发送尝试时间后首个1m收盘价基准，休市不计时。","本周当前只有111条可重算60m，79条数据不足；不据此判断整体周表现。此前已核验结果保留在明细右侧。")
s=s.replace("空白终点价表示观察窗未满，不能计为 0。","空白终点价需看状态：数据不足或未满，均不计作0。右侧AL:AN保留前次已核验结果。")
s=s.replace("'60m待观察','15m不利'","'60m缺数据','15m不利'").replace("'30m均变','60m数据不足'","'30m均变','60m待观察'")
s=s.replace("`=COUNTIFS(${cond},${range('AK')},\"待观察\")`", "`=C${row}-K${row}-COUNTIFS(${cond},${range('AK')},\"待观察\")`")
s=s.replace('s.avg60,s.pending60,s.loss15','s.avg60,s.missing60,s.loss15').replace('s.avg15,s.avg30,s.missing60','s.avg15,s.avg30,s.pending60')
s=s.replace("'当日策略表现'","'当日已存49条预警表现（不代表全天信号覆盖）'").replace("'本周累计策略表现（按交易日，包含周初夜盘）'","'本周当前可重算子集（缺数据单列，不与昨日全样本直接比较）'").replace("'本周品种表现'","'本周品种：当前可重算子集'").replace("'新增、此前已有与周初夜盘补入'","'当日新增与此前已有'")
old_start=s.index('const notes=[');old_end=s.index('for(const note of notes)',old_start)
notes=[
 '来源、数据缺口与限制',
 f"本次{a['status']}。截止{a['cutoff']}。交易日Calendar五交易所已核实；同版本实际loaded roots匹配。",
 '当日已存49条的15/30/60分钟观察路径完整，可计算价格方向表现。最后一条预警为10:15，不代表其后无信号。',
 '已读54个合约的当日分钟快照均只到13:33；13:34—15:00共87个应有分钟缺失。没有跳过缺口计时。',
 '涉及昨日历史的50个合约，9月9日经MDS查询均返回DATASET_OR_PARTITION_MISSING；没有回填或另选分区。',
 f"本周190条当前60m可重算111条，79条数据不足。15m缺74条，30m缺76条。缺失不计作失败或持平。",
 '前次24条待观察中，Event165/166/167的窗口已补齐：60m一有利、二不利；剩余21条缺少昨日基准或路径数据。',
 '其余此前已成熟记录中，58条60m结果今天不能重算；在明细AL:AN保留前次15/30/60m结果，不用旧结果伪装本次验证。',
 '旧141条事件身份全部一致。能重新算出的既有窗口与前次结果一致；当前读取失败单列，不当作价格修订。',
 '本次49条新预警未能完成完整公式复算；不能把它们的未来价格方向表现当作公式正确性验证。',
 f"公式结果分布：{json.dumps(a['formula_counts'],ensure_ascii=False)}。旧结论不等于当前重新验证。",
 'Alert状态最后处理/评估为10:15，苏冰记录evaluation_failed；本次不诊断根因、不自动修复或切换Runtime。',
 'Event206集运欧线09:15记录transport_failed；Event216不锈钢10:15记录provider_accepted；未补发。',
 'provider接受、发送尝试和微信收到分开记录；Event146的owner确认沿用STATUS已有记录，仅限该条和该owner。',
 '方向变化=方向系数×（终点收盘价÷基准价−1）；基准为记录的发送尝试时间后首个completed 1m收盘价。',
 '该时间与识别时点同时赋值，是发送时点代理，不是HTTP开始或微信收到时间。休市不计时，物理合约固定。',
 '每个有效窗口必须所有应有分钟均存在；未满、数据不足和方向反向分别统计。禁止填零或缩短窗口。',
 '正负持平与均值在汇总右侧；明细包含完整时间、参考价格、MFE/MAE及前次结果。',
 '均值按Event等权，不是账户收益；连续信号不独立，未计费用、滑点、保证金和执行约束。',
 '来源文件：source.json、market.json、formula.json；历史结果来源2026-09-09/analysis.json，原文件未覆盖。',
 '下一步：只读定位预警10:15停止推进与行情13:33停止推进的原因；本任务不授权恢复、重启或生产写入。'
]
s=s[:old_start]+'const notes='+json.dumps(notes,ensure_ascii=False)+';\n'+s[old_end:]
needle="nativeTable(detail,`A6:AK${end}`,'PushPerformance');header(detail,'A6:AK6');"
replacement="detail.getRange('AL6:AN6').values=[['前次快照15m','前次快照30m','前次快照60m']];detail.getRange(`AL7:AN${end}`).values=a.records.map(r=>[numeric(r.previous_return_15),numeric(r.previous_return_30),numeric(r.previous_return_60)]);pctColor(detail,`AL7:AN${end}`);detail.getRange(`AL6:AN${end}`).format.columnWidth=18;nativeTable(detail,`A6:AN${end}`,'PushPerformance');header(detail,'A6:AN6');"
assert needle in s;s=s.replace(needle,replacement)
s=s.replace("['复盘汇总','A1:N17'","['复盘汇总','A1:N18'").replace("`M${end-5}:AK${end}`","'M132:AN138'")
(p/'build_workbook.mjs').write_text(s)
deps=Path('/Users/zhangzhao/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules')
if not (p/'node_modules').exists():(p/'node_modules').symlink_to(deps,target_is_directory=True)
print('BUILDER_READY')
