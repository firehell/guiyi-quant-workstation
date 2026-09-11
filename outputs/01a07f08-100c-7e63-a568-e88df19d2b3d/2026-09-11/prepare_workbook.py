from pathlib import Path
import json
p=Path(__file__).resolve().parent
t=(p.parent/'2026-09-10'/'build_workbook.mjs').read_text()
t=t.replace("s.getRange('A1:AN250')","s.getRange('A1:AP250')")
t=t.replace('右侧AL:AN保留前次已核验结果。','右侧AL:AN保留9月10日快照结果，AO:AP为重叠窗口分组。')
t=t.replace("nativeTable(detail,`A6:AN${end}`,'PushPerformance');header(detail,'A6:AN6');", "detail.getRange('AO6:AP6').values=[['60m窗口组','组首条']];detail.getRange(`AO7:AP${end}`).values=a.records.map(r=>[r.cluster_id,r.cluster_first]);detail.getRange(`AO6:AP${end}`).format.columnWidth=16;nativeTable(detail,`A6:AP${end}`,'PushPerformance');header(detail,'A6:AP6');")
t=t.replace('前次快照15m','9/10快照15m').replace('前次快照30m','9/10快照30m').replace('前次快照60m','9/10快照60m')
t=t.replace("summary.getRange('A4').values=[[`当日 ${a.today_total.count} 条 / ${a.today_products} 品种；本周 ${a.total.count} 条 / ${a.unique_products} 品种。预警仅截至10:15；分钟行情仅到13:33，全天覆盖不完整。`]];", "summary.getRange('A4').values=[[`当日新增 ${a.today_total.count} 条；本周 ${a.total.count} 条。预警仍停在9月10日10:15。今天0条新增不能解释为正常无信号。`]];")
t=t.replace("summary.getRange('A5').values=[['本周当前只有111条可重算60m，79条数据不足；不据此判断整体周表现。此前已核验结果保留在明细右侧。']];", "summary.getRange('A5').values=[[`今日60品种缺有效Session及当日rank1映射；本周当前60m可重算 ${a.total.n60} 条，${a.total.missing60} 条数据不足。`]];")
t=t.replace("function section(name,rows,kind,day){", "function section(name,rows,kind,day){\n if(!rows.length){summary.getRange(`A${row}`).values=[[name+'：今日无新增记录，比例不适用。']];row+=2;return;}")
t=t.replace("section('当日已存49条预警表现（不代表全天信号覆盖）'", "section('当日预警表现'")
t=t.replace("section('当日多空表现',a.today_direction_summary,'direction',a.today);",'')
t=t.replace("section('当日品种表现',a.today_product_summary,'product',a.today);",'')
start=t.index('const notes=[');end=t.index(';\nfor(const note of notes)',start)
t=t[:start]+'const notes=a.notes'+t[end:]
t=t.replace("const original=detail.getRange('N7')", "const original=detail.getRange('N7')")
t=t.replace("detail.getRange('N7').values=[[base*(1+side*.01)]];", "if(!base)throw Error('probe anchor unavailable');detail.getRange('N7').values=[[base*(1+side*.01)]];")
t=t.replace("detail.getRange(`W6:W${end}`).format.columnWidth=33;","detail.getRange(`W6:W${end}`).format.columnWidth=55;")
t=t.replace("['复盘汇总','A1:N18','summary-preview.png']","['复盘汇总','A1:N17','summary-preview.png']")
t=t.replace("['逐条表现','M132:AN138','detail-preview.png']","['逐条表现','R6:X12','detail-preview.png']")
t=t.replace("['推送内容',`A${end-2}:H${end}`,'contents-preview.png']","['推送内容','A6:H9','contents-preview.png']")
(p/'build_workbook.mjs').write_text(t)
link=p/'node_modules'
if not link.exists():link.symlink_to('/Users/zhangzhao/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules',target_is_directory=True)
