import json,csv,hashlib,collections
from pathlib import Path
P=Path('/Volumes/扩展盘/guiyi-quant-workstation/outputs/newow-weekly-remaining12-20260923')
r=json.loads((P/'readiness-full.json').read_text()); identity=json.loads((P/'audit-identity.json').read_text())
cases=[c for c in r['cases'] if c['frequency']=='1w']
assert len(cases)==36 and len({(c['symbol'],c['strategy']) for c in cases})==36
def save(name,x):(P/name).write_text(json.dumps(x,ensure_ascii=False,indent=2,default=str)+'\n')
def csvout(name,rows,fields):
 with (P/name).open('w',newline='') as f:
  w=csv.DictWriter(f,fields,extrasaction='ignore');w.writeheader();w.writerows(rows)
def context(row):return row.get('error',{}).get('diagnostic',{}).get('context',{})
matrix=[]
for c in cases:
 m=c['main'];cx=context(m)
 matrix.append({'product':c['symbol'].upper(),'strategy':c['strategy'],'status':m['status'],'reason':m.get('reason'),'contract':cx.get('contract'),'trading_day':cx.get('trading_day'),'sections':c['sections']})
csvout('strategy-matrix-36.csv',matrix,['product','strategy','status','reason','contract','trading_day'])
save('strategy-matrix-36.json',{'audit_identity':identity,'cases':cases})
deps=r['dependencies'];repairs=r['repair_targets']
anomalies=[d for d in deps if d['status'] not in ('DATA_READY','NOT_APPLICABLE')]
save('dependency-anomalies.json',anomalies)
save('repair-targets.json',repairs)
windows=[]
for t in repairs:
 for w in t.get('target_windows',[]):windows.append({'product':t['symbol'].upper(),'contract':t['contract'],'plan_status':t['status'],'reason':t.get('reason'),'through':t.get('through'),**w,'dataset':json.dumps(w.get('dataset'))})
csvout('repair-windows.csv',windows,['product','contract','plan_status','reason','through','dataset','year','month','expected_start','expected_end','expected_bar_count','missing_start','missing_end','missing_bar_count'])
products=[]
for p in sorted({c['symbol'] for c in cases}):
 cs=[m for m in matrix if m['product']==p.upper()];ds=[d for d in deps if d['symbol']==p];ts=[t for t in repairs if t['symbol']==p]
 products.append({'product':p.upper(),'main_statuses':dict(collections.Counter(c['status'] for c in cs)),'main_reasons':sorted({c['reason'] or '' for c in cs}),'first_blockers':[{'strategy':c['strategy'],'contract':c['contract'],'trading_day':c['trading_day'],'reason':c['reason']} for c in cs],'dependency_statuses':dict(collections.Counter(d['status'] for d in ds)),'blocked_contracts':sorted({d['contract'] for d in ds if d['status'] not in ('DATA_READY','NOT_APPLICABLE')}),'repair_statuses':dict(collections.Counter(t['status'] for t in ts)),'repair_contracts':sorted({t['contract'] for t in ts})})
summary={'audit_identity':identity,'native_status':r['status'],'native_complete':r['complete'],'budget_exhausted':r['budget_exhausted'],'work_used':r['work_used'],'denominator':36,'main_statuses':dict(collections.Counter(m['status'] for m in matrix)),'dependency_count':len(deps),'dependency_statuses':dict(collections.Counter(d['status'] for d in deps)),'repair_count':len(repairs),'repair_statuses':dict(collections.Counter(t['status'] for t in repairs)),'metadata_proposal_count':len(r['metadata_proposals']),'provider_requests':r['provider_requests'],'writes':r['writes'],'products':products}
save('summary.json',summary)
lines=['# 剩余 12 品种 W1 精确缺口审计','',f"- 冻结代码：`{identity['code_sha']}`",f"- 完整周截点：`{r['as_of']}`（北京时间 2026-09-18 15:00:00.000001）",f"- Catalog revision：`{identity['catalog_revision_before']}`",f"- 事务：REPEATABLE READ / READ ONLY；快照内稳定：{identity['catalog_revision_stable']}；独立新事务回读一致：{identity['fresh_revision_unchanged']}。",f"- 原生审计状态：{r['status']}；预算耗尽：{r['budget_exhausted']}；provider={r['provider_requests']}，生产 writes={r['writes']}。",'- 固定分母：12 品种 × 3 策略 = 36；仅审计 W1。完整原生报告含其他周期占位项，未将其计入36格。','', '## 策略矩阵汇总','',str(summary['main_statuses']),'','| 品种 | 三策略主图状态 | 首个阻塞合约/日期 | 阻塞依赖合约数 | 修复提案 |','|---|---|---|---:|---|']
for p in products:
 b=sorted({f"{x['contract'] or '-'} / {x['trading_day'] or '-'}: {x['reason']}" for x in p['first_blockers']})
 lines.append(f"| {p['product']} | {p['main_statuses']} | {'; '.join(b)} | {len(p['blocked_contracts'])} | {p['repair_statuses']} |")
lines+=['','## 逐合约清单','']
for p in products:
 lines +=[f"### {p['product']}",'','阻塞依赖合约：'+(', '.join(p['blocked_contracts']) or '无'), '','待修复提案合约：'+(', '.join(p['repair_contracts']) or '无'),'']
lines+=['## 证据与边界','', '- `strategy-matrix-36.csv/json`：36个组合的当前状态与第一处阻塞。','- `dependency-anomalies.json`：完整依赖阻塞、owner窗口、错误上下文；不能将主图第一处阻塞当成全部缺口。','- `repair-targets.json`、`repair-windows.csv`：各合约的月分区、expected/missing日期边界及条数、scope diagnostics与计划状态。窗口起止并不代表区间内每个交易日都缺失。','- `readiness-full.json`：原生完整枚举、依赖、候选修复与逐section结果。','- REVIEW_REQUIRED不是可执行补数批次，PROPOSED也不是生产授权。真实来源异常不通过造数消除。','- 本次是固定代码/数据截点的API与底层依赖审计，不是浏览器、正式开放、发布或Runtime验收。','- 首次沙箱连接失败未进入审计；`runner-error.json`保留该尝试，成功运行结果以本报告和audit-identity为准。']
(P/'report.md').write_text('\n'.join(lines)+'\n')
save('artifact-hashes.json',{f.name:hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(P.iterdir()) if f.is_file() and f.name!='artifact-hashes.json'})
print(json.dumps({k:v for k,v in summary.items() if k not in ('audit_identity','products')},ensure_ascii=False))
print(json.dumps(products,ensure_ascii=False))
