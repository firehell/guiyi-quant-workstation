import fs from 'node:fs/promises';
import {Workbook,SpreadsheetFile} from '@oai/artifact-tool';
const dir=decodeURIComponent(new URL('.',import.meta.url).pathname);
const a=JSON.parse(await fs.readFile(`${dir}analysis.json`,'utf8'));
const w=Workbook.create();
const summary=w.worksheets.add('复盘汇总'), detail=w.worksheets.add('逐条表现'), content=w.worksheets.add('推送内容');
const numeric=v=>v===null||v===undefined?null:Number(v);
const dateValue=s=>s?new Date(s.replace(' ','T')+'Z'):null;
const local=s=>s?new Date(new Date(s).getTime()+8*3600000):null;
const bodyColor='#26354A',headerColor='#253B58';
for(const s of [summary,detail,content]) {s.showGridLines=false;s.getRange('A1:AN250').format.font={name:'Arial',size:11,color:bodyColor};s.getRange('A1:AN250').format.verticalAlignment='center';}
summary.tabColor='#253B58';
function title(s,text){s.getRange('A2').values=[[text]];s.getRange('A2').format.font={name:'Arial',size:16,bold:true,color:headerColor};}
function header(s,range){s.getRange(range).format={fill:headerColor,font:{name:'Arial',size:11,bold:true,color:'#FFFFFF'},rowHeight:36,horizontalAlignment:'center',verticalAlignment:'center',wrapText:true};}
function nativeTable(s,range,name){const t=s.tables.add(range,true,name);t.showFilterButton=true;t.style='TableStyleMedium2';return t;}
function pctColor(s,range){s.getRange(range).setNumberFormat('0.00%;[Red]-0.00%;0.00%');s.getRange(range).conditionalFormats.add('cellIs',{operator:'lessThan',formula:0,format:{font:{color:'#B54737'}}});s.getRange(range).conditionalFormats.add('cellIs',{operator:'greaterThan',formula:0,format:{font:{color:'#176B50'}}});}
title(detail,'逐条推送后的价格表现');
detail.getRange('A4').values=[['来源：不可变 AlertEvent；Canonical 经 MarketDataService 读取；completed Live 经 MarketReadService 读取。']];
detail.getRange('A5').values=[['北京时间。基准为记录的发送尝试时间之后首个分钟收盘价；15/30/60m 为随后交易分钟。空白终点价表示观察窗未满，不能计为 0。']];
const headers=['Event ID','发送日期','发送时间','品种','物理合约','策略','信号周期','方向','方向系数','信号 Bar 时间','信号收盘价','观察基准时间','观察基准价','15m终点价','15m方向变化','30m终点价','30m方向变化','60m终点价','60m方向变化','60m判断','60m最大有利幅度','60m最大不利幅度','公式复算','发送证据','15m终点时间','30m终点时间','60m终点时间','识别时间差(秒)','Rule code','信号价基准15m','信号价基准30m','信号价基准60m'];
detail.getRange('A6:AF6').values=[headers];
const vals=a.records.map(r=>[r.id,dateValue(r.send_date+' 00:00:00'),dateValue(r.send_local),r.product_name,r.contract,r.strategy,r.frequency,r.direction,r.side,dateValue(r.signal_local),numeric(r.signal_close),dateValue(r.anchor_local),numeric(r.anchor_close),numeric(r.close_15),null,numeric(r.close_30),null,numeric(r.close_60),null,null,numeric(r.mfe60),numeric(r.mae60),r.formula_status,r.sender_status,local(r.end_15),local(r.end_30),local(r.end_60),r.lag_seconds,r.rule_code,numeric(r.signal_return_15),numeric(r.signal_return_30),numeric(r.signal_return_60)]);
const end=6+vals.length;detail.getRange(`A7:AF${end}`).values=vals;
detail.getRange('AG6').values=[['记录分组']];detail.getRange('AH6').values=[['交易日']];detail.getRange(`AH7:AH${end}`).values=a.records.map(r=>[dateValue(r.trading_day+' 00:00:00')]);detail.getRange(`AH7:AH${end}`).setNumberFormat('yyyy-mm-dd');detail.getRange('AI6:AK6').values=[['15m状态','30m状态','60m状态']];detail.getRange(`AI7:AK${end}`).values=a.records.map(r=>[r.status_15,r.status_30,r.status_60]);detail.getRange(`AG7:AG${end}`).values=a.records.map(r=>[r.cohort]);
for(const [out,price] of [['O','N'],['Q','P'],['S','R']]){detail.getRange(`${out}7`).formulas=[[`=IF(${price}7="","",I7*(${price}7/M7-1))`]];detail.getRange(`${out}7:${out}${end}`).fillDown();pctColor(detail,`${out}7:${out}${end}`);}
detail.getRange('T7').formulas=[['=IF(R7="",AK7,IF(S7>0,"有利",IF(S7<0,"不利","持平")))']];detail.getRange(`T7:T${end}`).fillDown();
nativeTable(detail,`A6:AK${end}`,'PushPerformance');header(detail,'A6:AK6');
detail.getRange(`A7:AF${end}`).format.rowHeight=26;
detail.getRange(`A6:AF${end}`).format.columnWidth=15;
for(const c of ['A','G','H','I'])detail.getRange(`${c}6:${c}${end}`).format.columnWidth=10;
for(const c of ['C','J','L','Y','Z','AA']){detail.getRange(`${c}6:${c}${end}`).format.columnWidth=23;detail.getRange(`${c}7:${c}${end}`).setNumberFormat('mm-dd hh:mm:ss');}
detail.getRange(`B7:B${end}`).setNumberFormat('yyyy-mm-dd');
for(const c of ['K','M','N','P','R'])detail.getRange(`${c}7:${c}${end}`).setNumberFormat('#,##0.00');
for(const c of ['U','V','AD','AE','AF'])pctColor(detail,`${c}7:${c}${end}`);
detail.getRange(`W6:X${end}`).format.columnWidth=25;detail.getRange(`AC6:AC${end}`).format.columnWidth=32;
detail.getRange(`AB7:AB${end}`).setNumberFormat('0.0');
detail.freezePanes.freezeRows(6);detail.freezePanes.freezeColumns(5);

title(content,'推送内容与发送证据');
content.getRange('A4').values=[['内容由冻结 Event 与当前一致模板 复原，未读取 PushPlus 历史原文；不代表逐条微信收件成功。']];
content.getRange('A5').values=[['来源：历史快照及共享Runtime状态精确时间匹配；Event146另有STATUS记录owner确认，仅限该条。其余逐条结果未留存。']];
content.getRange('A6:H6').values=[['Event ID','发送时间(北京时间)','品种','策略','周期','发送证据','推送正文（按模板复原）','公式复核口径']];
content.getRange(`A7:H${end}`).values=a.records.map(r=>[r.id,dateValue(r.send_local),r.product_name,r.strategy,r.frequency,r.sender_status,r.content,r.formula_status+'；原始逐条输入快照未存档']);
nativeTable(content,`A6:H${end}`,'PushContents');header(content,'A6:H6');content.getRange(`A6:H${end}`).format.columnWidth=14;
content.getRange(`B6:B${end}`).format.columnWidth=23;content.getRange(`B7:B${end}`).setNumberFormat('mm-dd hh:mm:ss');
content.getRange(`F6:F${end}`).format.columnWidth=26;content.getRange(`G6:G${end}`).format.columnWidth=100;content.getRange(`H6:H${end}`).format.columnWidth=44;
content.getRange(`A7:H${end}`).format.rowHeight=102;content.getRange(`G7:H${end}`).format.wrapText=true;content.getRange(`G7:H${end}`).format.verticalAlignment='top';
content.freezePanes.freezeRows(6);content.freezePanes.freezeColumns(3);


title(summary,`${a.today} 推送准确度收盘复盘`);
summary.getRange('A4').values=[[`当日 ${a.today_total.count} 条 / ${a.today_products} 品种；本周 ${a.total.count} 条 / ${a.unique_products} 品种。行情截至当日日盘收盘。`]];
summary.getRange('A5').values=[['有利比例=方向变化为正的条数÷已满窗口条数。保持发送尝试时间后首个1m收盘价基准，休市不计时。']];
summary.getRange('A6').values=[['发送尝试时间是识别时点代理，并非微信收件时间；方向表现不是含成本交易胜率。向右可查看正负持平及均值。']];
const sh=['策略/品种','信号周期','总条数','15m有利','15m样本','15m比例','30m有利','30m样本','30m比例','60m有利','60m样本','60m比例','60m均变','60m待观察','15m不利','15m持平','30m不利','30m持平','60m不利','60m持平','15m均变','30m均变','60m数据不足'];
const range=c=>`'逐条表现'!$${c}$7:$${c}$${end}`;
const quote=x=>`"${x.replaceAll('"','""')}"`;
const checks=[];let row=7;const sections=[];
function criteria(info){const pairs=[];for(const [field,c] of [['strategy','F'],['freq','G'],['product','D'],['direction','H'],['cohort','AG']])if(info[field])pairs.push(`${range(c)},${quote(info[field])}`);if(info.day)pairs.push(`${range('AH')},DATE(${info.day.replaceAll('-',',')})`);return pairs.join(',');}
function putRow(row,label,info,s){
 const cond=criteria(info);summary.getRange(`A${row}:B${row}`).values=[[label,info.freq]];
 const fs=[`=COUNTIFS(${cond})`];
 for(const [p,ret,win,n] of [['N','O','D','E'],['P','Q','G','H'],['R','S','J','K']])fs.push(`=COUNTIFS(${cond},${range(p)},">0",${range(ret)},">0")`,`=COUNTIFS(${cond},${range(p)},">0")`,`=IF(${n}${row}=0,"",${win}${row}/${n}${row})`);
 fs.push(`=IF(K${row}=0,"",SUMIFS(${range('S')},${cond})/K${row})`,`=COUNTIFS(${cond},${range('AK')},"待观察")`);
 for(const [p,ret] of [['N','O'],['P','Q'],['R','S']])fs.push(`=COUNTIFS(${cond},${range(p)},">0",${range(ret)},"<0")`,`=COUNTIFS(${cond},${range(p)},">0",${range(ret)},"=0")`);
 fs.push(`=IF(E${row}=0,"",SUMIFS(${range('O')},${cond})/E${row})`,`=IF(H${row}=0,"",SUMIFS(${range('Q')},${cond})/H${row})`,`=C${row}-K${row}-N${row}`);
 summary.getRange(`C${row}:W${row}`).formulas=[fs];summary.getRange(`C${row}:W${row}`).setNumberFormat('0');
 for(const c of ['F','I','L'])summary.getRange(`${c}${row}`).setNumberFormat('0.0%');for(const c of ['M','U','V'])summary.getRange(`${c}${row}`).setNumberFormat('0.00%;[Red]-0.00%;0.00%');
 checks.push({row,expected:[s.count,s.win15,s.n15,s.hit15,s.win30,s.n30,s.hit30,s.win60,s.n60,s.hit60,s.avg60,s.pending60,s.loss15,s.flat15,s.loss30,s.flat30,s.loss60,s.flat60,s.avg15,s.avg30,s.missing60]});
}
function section(name,rows,kind,day){
 summary.getRange(`A${row}`).values=[[name]];summary.getRange(`A${row}`).format.font.bold=true;row++;
 let first=row;summary.getRange(`A${row}:W${row}`).values=[sh];header(summary,`A${row}:W${row}`);row++;
 for(const s of rows){let words=s.key.split(' ');let info={},label;
  if(kind==='day'){const [d,strategy,freq]=words;info={day:d,strategy,freq};label=`${d} ${strategy}`;}
  else if(kind==='cohort'){const [cohort,strategy,freq]=words;info={cohort,strategy,freq};label=`${cohort} ${strategy}`;}
  else {const [strategy,freq,extra]=words;info={strategy,freq,day};label=strategy;if(kind==='direction'){info.direction=extra;label+=` ${extra}`;}if(kind==='product'){info.product=extra;label=`${extra} ${words[3]} ${strategy}`;}}
  putRow(row++,label,info,s);
 }
 nativeTable(summary,`A${first}:W${row-1}`,`Summary${sections.length+1}`);sections.push({name,first,last:row-1});row+=2;
}
section('当日策略表现',a.today_strategy_summary,'strategy',a.today);
section('本周累计策略表现（按交易日，包含周初夜盘）',a.strategy_summary,'strategy');
section('当日多空表现',a.today_direction_summary,'direction',a.today);
section('当日品种表现',a.today_product_summary,'product',a.today);
section('本周品种表现',a.product_summary,'product');
section('按交易日比较',a.day_summary,'day');
section('本周多空表现',a.direction_summary,'direction');
section('新增、此前已有与周初夜盘补入',a.cohort_summary,'cohort');
const notes=[
 '方法、来源及本次变化',
 `截至北京时间 ${new Date(a.cutoff).toLocaleString('sv-SE',{timeZone:'Asia/Shanghai'})}；来源为只读AlertEvent、Catalog与MarketReadService post_close快照。`,
 '方向变化=方向系数×（终点收盘价÷基准收盘价−1）。多头+1，空头−1。持平计入分母，不算有利。',
 '三个窗口均按权威Calendar/Session的1m端点推进；不同窗口样本数可能不同，比较期限时应另取共同成熟样本。',
 '同一物理合约读取，不跨合约，不补缺口。快照连续两次一致，分钟端点和交易日与权威预期相符。',
 `读取${a.minute_count}根1m Bar、${a.unique_products}个物理合约；当天${a.today_total.formula_match}/${a.today_total.count}条公式当前复算一致。`,
 '旧苏冰55条保留前次复算结论，本次未重新计算公式；HTDY历史前缀重算不能恢复当时Live快照。',
 '原有66条事件身份完全一致；8条此前未满60分钟记录现已补齐。当前收盘仍待观察24条。',
 '周累计补入Event27：9月4日21:15发出，归属9月7日交易日；昨天自然日期范围未包含它。',
 '行情修订：Event76菜粕RM2611，9月8日14:16收盘价由旧observation的2372变为当前Canonical的2371。',
 '该条60m方向变化由+0.38087%改为+0.33855%，仍有利；其余此前已成熟窗口的方向变化精确一致。旧文件未覆盖。',
 '修订只确认两种来源数值不同，尚未核实造成差异的上游原因；不把当前Canonical说成原始通知时可知事实。',
 '逐条发送证据沿用旧快照加当前共享Runtime状态的精确时间匹配。provider接受不是微信送达。',
 '当日Event164 PVC在14:45记录发送失败；Event167在15:00记录provider接受。失败未补发。',
 'Event146 PT2610 14:00的owner收件确认来自STATUS已有验收记录；本次未检查微信，不外推其他Event或成员。',
 '平均变化按Event等权；同合约连续信号与跨品种联动不独立，不构成组合收益、成交记录或净胜率。',
 '未经成本、时序、换月及独立样本验证，不据此改变正式策略、Scope或Runtime。'
];
for(const note of notes)summary.getRange(`A${row++}`).values=[[note]];
summary.getRange(`A7:W${row}`).format.rowHeight=27;summary.getRange(`A7:A${row}`).format.columnWidth=34;summary.getRange(`B7:B${row}`).format.columnWidth=11;summary.getRange(`C7:W${row}`).format.columnWidth=11;
for(const sec of sections)summary.getRange(`A${sec.first}:W${sec.first}`).format.rowHeight=38;
summary.freezePanes.freezeRows(8);summary.freezePanes.freezeColumns(2);
detail.getRange(`AG6:AK${end}`).format.columnWidth=18;detail.getRange(`W6:W${end}`).format.columnWidth=33;
w.recalculate();
for(const {row,expected} of checks){const v=summary.getRange(`C${row}:W${row}`).values[0];expected.forEach((e,i)=>{if(e===null){if(v[i]!==null&&v[i]!=='')throw Error(`missing denominator ${row}:${i}`);}else if(Math.abs(Number(v[i])-e)>1e-10)throw Error(`rollup mismatch ${row}:${i}: ${v[i]} vs ${e}`);});}
for(let i=0;i<a.records.length;i++)for(const [c,key] of [['O','return_15'],['Q','return_30'],['S','return_60']]){const v=detail.getRange(`${c}${i+7}`).values[0][0],e=a.records[i][key];if(e===null){if(v!==null&&v!=='')throw Error('missing converted to zero');}else if(Math.abs(Number(v)-Number(e))>1e-10)throw Error('detail mismatch');}
const original=detail.getRange('N7').values[0][0],base=detail.getRange('M7').values[0][0],side=detail.getRange('I7').values[0][0];
detail.getRange('N7').values=[[base*(1+side*.01)]];if(Math.abs(Number(detail.getRange('O7').values[0][0])-.01)>1e-10)throw Error('recalculation failed');detail.getRange('N7').values=[[original]];w.recalculate();
const errors=await w.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!',options:{useRegex:true,maxResults:30},summary:'formula error scan'});console.log(errors.ndjson);
await fs.writeFile(`${dir}workbook_checks.json`,JSON.stringify({records:a.records.length,rollup_rows:checks.length,rollups_match:true,detail_formulas_match:true,recalculation_verified:true,error_scan:errors.ndjson,sections},null,2));
for(const [sheetName,range,file] of [['复盘汇总','A1:N17','summary-preview.png'],['逐条表现',`M${end-5}:AK${end}`,'detail-preview.png'],['推送内容',`A${end-2}:H${end}`,'contents-preview.png']]){const b=await w.render({sheetName,range,scale:1.3,format:'png'});await fs.writeFile(`${dir}${file}`,new Uint8Array(await b.arrayBuffer()));}
const file=await SpreadsheetFile.exportXlsx(w);await file.save(`${dir}推送准确度复盘_${a.today.replaceAll('-','')}.xlsx`);console.log('WORKBOOK_EXPORTED');
