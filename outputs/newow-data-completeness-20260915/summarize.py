from pathlib import Path
from collections import Counter
import csv
import hashlib
import json

ROOT = Path('/Volumes/扩展盘/guiyi-quant-workstation')
OUT = Path('/private/tmp/guiyi-newow-completeness-20260915')
INPUTS = {
    '1w': (ROOT/'outputs/newow-weekly-recovery-attempts/fresh-audit-20260914-002/full-report.json', 'd5ee0c61906cded4ee5e1e20b0ed187f4deb38ac3dfc37921e1670f0aecb211b'),
    '1d': (ROOT/'.worktrees/newow-daily-60/outputs/newow-daily-60-20260914/d1-dependency-audit/full-report.json', '4aba9745f4037dd2c384c75dc99316f8fa519b2f274a7f66f9bf901a89234255'),
}
products = (ROOT/'data/universe/operational_products.txt').read_text().split()
names = {r['product']: r['name'] for r in csv.DictReader((ROOT/'data/universe/product_sectors.csv').open())}
assert len(products) == len(set(products)) == 60
reports = {}
for frequency, (path, expected_hash) in INPUTS.items():
    raw = path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == expected_hash
    d = json.loads(raw)
    assert d['complete'] and not d['budget_exhausted'] and d['readonly']
    assert d['provider_requests'] == d['writes'] == 0 and d['product_count'] == 60
    assert set(e['symbol'] for e in d['enumerations']) == set(products)
    assert all(e['status'] in ('ENUMERATED','UNOPENED') for e in d['enumerations'])
    reports[frequency] = d

result = {'sources': {f:{'path':str(p),'sha256':h,'as_of':reports[f]['as_of']} for f,(p,h) in INPUTS.items()}, 'products':[]}
ready = []
for symbol in products:
    entry = {'symbol':symbol,'name':names[symbol],'frequencies':{},'60m':'NOT_VERIFIED'}
    for frequency,d in reports.items():
        deps = [x for x in d['dependencies'] if x['symbol']==symbol]
        repairs = [x for x in d['repair_targets'] if x['symbol']==symbol]
        failures = [x for x in deps if x['status'] not in ('DATA_READY','NOT_APPLICABLE')]
        missing = Counter()
        seen = set()
        for r in repairs:
            for w in r.get('target_windows',[]):
                k = (tuple(w['dataset']),w['year'],w['month'])
                assert k not in seen, (frequency,symbol,k)
                seen.add(k)
                count = w.get('missing_bar_count')
                if count is not None:
                    assert type(count) is int and count>=0
                    missing[w['dataset'][-1]] += count
        entry['frequencies'][frequency] = {
            'data_ready':bool(deps) and not failures and not repairs,
            'dependency_count':len(deps),
            'affected_contracts': sorted({x['contract'] for x in failures}|{r['contract'] for r in repairs}),
            'known_missing_by_source_frequency':dict(missing),
            'repair_units':len(repairs),
            'review_units':sum(r['status']=='REVIEW_REQUIRED' for r in repairs),
            'failures':failures,
            'repairs':repairs,
        }
    if all(x['data_ready'] for x in entry['frequencies'].values()): ready.append(symbol)
    result['products'].append(entry)
assert ready == ['a','ag','al','ao','ap','au','pd','pt']
result['daily_weekly_ready']=ready
result['incomplete_count']=60-len(ready)
(OUT/'product-details.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))

notes={
 'b':'B2411 另有 O/H/L=0、volume>0 的历史来源异常；原始证据待重新取证。',
 'pf':'另有 PF2611 非正价格来源异常，不包含在普通缺失根数中。',
 'rs':'已知缺失根数仅是可量化部分；另有9个W1专项审查对象、RS2309/RS2311非正价格。',
 'bz':'另有 BZ2610 数据集或月分区缺失。',
 'si':'另有 SI2401 数据集或月分区缺失；日版还识别出尾部端点缺口。',
}
lines=['# 牛哇60品种数据完整性清单','',
'本表基于2026-09-14夜间完成的两份完整原生依赖审计，已在2026-09-15核验文件SHA-256、60品种覆盖与计数。不是本轮重新执行的全60品种实时扫描。',
'',
'- W1：审计于2026-09-14 23:31完成，固定as_of=2026-09-13 14:36:13 CST，最新完整周为2026-09-11。',
'- D1：审计于2026-09-14 23:26完成，固定as_of=2026-09-14 23:10:00 CST，最新完整日为2026-09-14。',
'- 两者覆盖实际主图、副图、独立参考交易历史和物理合约预热；不是全部上市合约、全部历史、三周期综合解释或页面矩阵验收。',
'- 60m：无同等新全域审计，不把UNOPENED认作缺数，也不把日周完整推广到60m完整。',
'- D1与W1的品种统计窗不同；W1缺失数与D1缺失数分别取各自报告，不相加当作下载流量。',
'- 两份报告metadata_proposals均为0；这仅证明所审范围，不证明未来元数据。',
'','## 已确认日周依赖完整的8个品种','',
'、'.join(f'{s.upper()} {names[s]}' for s in ready)+'。',
'',
'当前八品种复核结果见 current-ready-summary.json（如仍执行中则不提前宣称已通过）。数据齐备不证明三策略页面、跨周期评分和因果研究已全部验收。',
'','## 其余52品种逐项汇总','',
'根数取原生计划target_windows.missing_bar_count，已检查同报告内合约/周期/月无重复。它表示缺失Bar，不是预计全部响应行数。RS与PF的数值不含无法量化的来源质量问题。所有这些品种都还缺历史日线及对应周线预热/分区。',
'',
'| 品种 | 日版已知缺D1根数 | 周版已知缺W1根数 | 周版受影响合约数 | 额外问题 |',
'|---|---:|---:|---:|---|']
for e in result['products']:
    if e['symbol'] in ready:continue
    w=e['frequencies']['1w'];d=e['frequencies']['1d']
    nd=d['known_missing_by_source_frequency'].get('1d',0);nw=w['known_missing_by_source_frequency'].get('1w',0)
    prefix='至少 ' if e['symbol']=='rs' else ''
    lines.append(f"| {e['symbol'].upper()} {e['name']} | {prefix}{nd:,} | {prefix}{nw:,} | {len(w['affected_contracts'])} | {notes.get(e['symbol'],'历史前缀不足')} |")
lines += ['','## 各品种具体合约与缺失窗口','',
'下列日期区间是各目标月中缺失Bar的首尾包络，区间内不保证每天都缺；逐月计数、原生目标、consumer和错误上下文完整保存在 product-details.json。\n']
for e in result['products']:
    if e['symbol'] in ready:continue
    lines += [f"### {e['symbol'].upper()} {e['name']}",'']
    for frequency,label in [('1w','周版（D1来源与W1）'),('1d','日版（D1）')]:
        data=e['frequencies'][frequency]
        lines += [f'**{label}**','', '受影响合约：'+ '、'.join(data['affected_contracts'])+'。','',
                  '| 合约 | 原生状态 | 缺D1 | 缺W1 | 已知缺失日期包络 |', '|---|---|---:|---:|---|']
        for r in data['repairs']:
            counts=Counter();starts=[];ends=[]
            for w in r.get('target_windows',[]):
                counts[w['dataset'][-1]] += w.get('missing_bar_count') or 0
                if w.get('missing_start'):starts.append(w['missing_start'][:10])
                if w.get('missing_end'):ends.append(w['missing_end'][:10])
            span=min(starts)+' 至 '+max(ends) if starts and ends else '尚不可量化'
            lines.append(f"| {r['contract']} | {r['status']} | {counts.get('1d',0)} | {counts.get('1w',0)} | {span} |")
        special={}
        for f in data['failures']:
            if f.get('reason') in ['SOURCE_NONPOSITIVE_PRICE','DATASET_OR_PARTITION_MISSING','REPLAY_ENDPOINTS_MISSING']:
                ctx=f.get('error',{}).get('diagnostic',{}).get('context',{})
                k=(f['contract'],f.get('reason'),ctx.get('trading_day'),ctx.get('first_missing_day'))
                special[k]=ctx
        if special:
            lines += ['','额外诊断：']
            for (contract,reason,day,first),ctx in special.items():
                lines.append(f'- {contract}：{reason}；日期 {day or first or "原报告未给精确坏行日期"}。')
        lines.append('')
lines += ['## 证据来源与本轮验证','']
for f,(p,h) in INPUTS.items():lines += [f'- {f}：[原始完整报告]({p})；SHA-256：{h}。']
lines += ['','本轮只生成分析文件与对已报告完整的八品种发起日周只读复核；无RQData下载、Canonical/DB写入、补数、通知、发布或Runtime动作。没有修改已有源码。']
(OUT/'report.md').write_text('\n'.join(lines)+'\n')
print(json.dumps({'ready':ready,'incomplete':result['incomplete_count'],'rows_in_detail':sum(len(e['frequencies'][f]['repairs']) for e in result['products'] for f in ['1w','1d']),'report':str(OUT/'report.md')},ensure_ascii=False))
