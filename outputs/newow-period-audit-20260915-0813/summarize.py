"""Summarize native dependency diagnostics without inventing repair plans."""
from pathlib import Path
from collections import defaultdict, Counter
import json, csv, hashlib

ROOT=Path('/Volumes/扩展盘/guiyi-quant-workstation')
OUT=ROOT/'outputs/newow-period-audit-20260915-0813'
summary=json.loads((OUT/'summary.json').read_text())
products=(ROOT/'data/universe/operational_products.txt').read_text().split()
names={r['product']:r['name'] for r in csv.DictReader((ROOT/'data/universe/product_sectors.csv').open())}
assert len(summary['products'])==len(products)==60
assert {p['symbol'] for p in summary['products']}==set(products)
result={'as_of':summary['as_of'],'finished_at':summary['finished_at'],'provider_requests':0,'production_writes':0,'products':[],'ready':{},'totals':{}}
lines=['# 牛哇60品种：周、日、60m输入完整性只读核查','',
       '固定 as_of：'+summary['as_of']+'；完成时间：'+summary['finished_at']+'。',
       '使用当前 develop 的原生 NewowReadinessAudit、NewowProductReader、Catalog/Canonical/MDS，逐品种 REPEATABLE READ / READ ONLY 事务。覆盖当前主图、副图、独立参考历史及各物理合约生命周期预热。未开放的跨周期综合解释不在本轮输入核查范围；不是三策略页面矩阵、全部上市合约全历史或交易研究验收。',
       '本轮无 provider、无生产写入，未构造补数 planner。60m 表中的数量是60m缺失Bar，未扫描其全部1m来源，因此不提供1m下载量或精确apply计划。',
       '各周期按物理合约去重。同合约多consumer共享生命周期前缀时，取最大已报告missing_count避免重复累计；仅为可量化缺口。遇到来源异常、缺分区或元数据未量化项，另行披露，不能把已知数当总数。日期为第一已知缺失日至最后要求截止的包络，不表示区间内每根都缺。',
       '没有数据写入锁；逐品种读事务在同一业务截止时间检查，文件/身份冲突由原生读取失败明确报告。','',
       '| 品种 | 周线缺失Bar | 日线缺失Bar | 60m缺失Bar | 额外问题 |','|---|---:|---:|---:|---|']
for s in products:
    raw=(OUT/f'{s}.json').read_bytes();d=json.loads(raw)
    sm=next(x for x in summary['products'] if x['symbol']==s)
    e={'symbol':s,'name':names[s],'source_sha256':hashlib.sha256(raw).hexdigest(),'periods':{}}
    extra=set()
    for freq in ['1w','1d','60m']:
        deps=[x for x in d['dependencies'] if x['frequency']==freq]
        by=defaultdict(list)
        for x in deps:
            if x['status'] not in ['DATA_READY','NOT_APPLICABLE']:by[x['contract']].append(x)
        contracts=[]
        for c,ds in sorted(by.items()):
            counts=[];dates=[];cutoffs=[];reasons=set();unknown=[]
            for x in ds:
                reason=x.get('reason') or x['status'];reasons.add(reason)
                ctx=x.get('error',{}).get('diagnostic',{}).get('context',{})
                n=ctx.get('missing_count')
                if type(n) is int and n>=0:counts.append(n)
                else:unknown.append(reason)
                for k in ['first_missing_day','first_missing_at','trading_day']:
                    if ctx.get(k):dates.append(str(ctx[k])[:10]);break
                if x.get('through'):cutoffs.append(x['through'])
                if reason!='REPLAY_PREFIX_MISSING':extra.add(f'{freq} {c}: {reason}')
            contracts.append({'contract':c,'known_missing':max(counts) if counts else None,'unquantified_reasons':sorted(set(unknown)),'reasons':sorted(reasons),'first_known_day':min(dates) if dates else None,'required_through':max(cutoffs) if cutoffs else None,'diagnostics':ds})
        e['periods'][freq]={**sm['periods'][freq],'known_missing':sum(c['known_missing'] or 0 for c in contracts),'unquantified_contracts':sum(bool(c['unquantified_reasons']) for c in contracts),'contracts':contracts}
    result['products'].append(e)
    def cell(f):
        p=e['periods'][f]
        if p['input_complete']:return '完整'
        n=p['known_missing'];tail=' + 未量化项' if p['unquantified_contracts'] else ''
        if p['budget_exhausted'] or not p['enumeration_complete']:tail+='；审计未穷尽'
        return (f'{n:,}' if n else '未量化')+tail
    lines.append(f"| {s.upper()} {names[s]} | {cell('1w')} | {cell('1d')} | {cell('60m')} | {'；'.join(sorted(extra)) or '历史预热前缀缺口' if extra or any(not e['periods'][f]['input_complete'] for f in ['1w','1d','60m']) else '无已发现输入缺口'} |")
for f in ['1w','1d','60m']:
    result['ready'][f]=[e['symbol'] for e in result['products'] if e['periods'][f]['input_complete']]
    result['totals'][f]={'ready_products':len(result['ready'][f]),'known_missing':sum(e['periods'][f]['known_missing'] for e in result['products']),'unquantified_contracts':sum(e['periods'][f]['unquantified_contracts'] for e in result['products'])}
lines += ['','## 每品种/周期的合约与缺口诊断','']
for e in result['products']:
    lines += [f"### {e['symbol'].upper()} {e['name']}",'']
    for f,label in [('1w','周'),('1d','日'),('60m','60m')]:
        p=e['periods'][f]
        if p['input_complete']:lines += [f'**{label}：本轮输入检查完整。**',''];continue
        lines += [f'**{label}**','','| 合约 | 已知缺失Bar | 首个已知缺失/异常日期 | 要求截止 | 原生原因 |','|---|---:|---|---|---|']
        for c in p['contracts']:
            count=str(c['known_missing']) if c['known_missing'] is not None else '未量化'
            if c['known_missing'] is not None and c['unquantified_reasons']:count+=' + 未量化项'
            lines.append(f"| {c['contract']} | {count} | {c['first_known_day'] or '未给出'} | {c['required_through'] or '未给出'} | {', '.join(c['reasons'])} |")
        lines.append('')
lines += ['## 历史来源异常提醒','',
          'B2411 的旧下载失败记录为 RQDATA_ZERO_OHL_INVALID（2023-12-27 O/H/L=0、volume=2、close=3929）；本轮无provider调用，未重新取证。当前缺口诊断不能消除该旧来源阻断。',
          'PF/RS 等 SOURCE_NONPOSITIVE_PRICE 是已存数据数值异常，不等于普通缺Bar；保留原生诊断。',
          '精确D1/W1逐月补数计划可参考既有报告；本轮只是输入依赖核查，不构成新apply计划或授权。']
(OUT/'details.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
(OUT/'report.md').write_text('\n'.join(lines)+'\n')
print(json.dumps({'ready':result['ready'],'totals':result['totals'],'products':len(result['products'])},ensure_ascii=False))
