"""Two targeted failure examples, not blind samples or accuracy evaluation."""
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import gzip,json
ROOT=Path(__file__).resolve().parents[2]

def chart(bars):
    lo=min(b['low'] for b in bars);hi=max(b['high'] for b in bars);span=max(hi-lo,1);lo-=span*.06;hi+=span*.06
    y=lambda v:270-(v-lo)/(hi-lo)*240
    dx=880/len(bars);out=['<svg viewBox="0 0 1000 310" aria-label="截至案例时刻的30m价格">']
    for j in range(5):
        v=lo+(hi-lo)*j/4;out.append(f'<path d="M60 {y(v)}H960" stroke="#e4e9f1"/><text x="2" y="{y(v)}" font-size="12">{v:.1f}</text>')
    for i,b in enumerate(bars):
        x=70+i*dx;c='#d54b53' if b['close']>=b['open'] else '#21887a'
        out.append(f'<path d="M{x} {y(b["high"])}V{y(b["low"])}" stroke="{c}"/><rect x="{x-dx*.28}" y="{min(y(b["open"]),y(b["close"]))}" width="{dx*.56}" height="{max(1,abs(y(b["open"])-y(b["close"])))}" fill="{c}"/>')
    out.append(f'<text x="65" y="303" font-size="13">当前收盘 {bars[-1]["close"]} · 最右侧为判断时刻</text></svg>')
    return ''.join(out)

def main():
    trace=[json.loads(l) for l in (ROOT/'output/subing-box-reentry-new-seed-20261104/trace.jsonl').read_text().splitlines()]
    # Diagnostic selection based on candidate expansion/age; explicitly NOT random or OOS.
    from decimal import Decimal
    picks=[max((r for r in trace if r['contract']=='JM2605'),key=lambda r:Decimal(r['width_multiple'] or '0')),
           max((r for r in trace if r['contract']=='JM2601'),key=lambda r:r['age_bars'] or 0)]
    data=[]
    with gzip.open(ROOT/'output/regime-learning-20261102-final/jm-30m.jsonl.gz','rt') as f:
        for line in f:
            r=json.loads(line)
            if r['contract'] in {p['contract'] for p in picks}:data.append(r)
    parts=['<!doctype html><meta charset="utf-8"><title>苏冰 · 区间何时重建</title><style>body{font:16px system-ui;max-width:1200px;margin:30px auto;padding:20px;background:#f4f6fa;color:#233047}section{background:white;padding:24px;border-radius:12px;margin:24px 0}svg{width:100%}p{line-height:1.8}</style><h1>两例复核：旧区间何时失去参考意义？</h1><p>按候选异常定向抽取的已见开发行情；不是盲测或随机样本。每例只展示截至当时的K线，上图128根，下图32根。候选范围仅供核对，不是标准答案。</p>']
    saved=[]
    for i,p in enumerate(picks,1):
        bars=[r for r in data if r['contract']==p['contract'] and datetime.fromisoformat(r['time'])<=datetime.fromisoformat(p['time'])][-128:]
        assert bars[-1]['time']==p['time']
        stamp=datetime.fromisoformat(p['time']).astimezone(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d %H:%M')
        parts.append(f'<section><h2>L{i} · {p["contract"]} · {stamp} 北京时间</h2><p>候选仍参考 {p["lower"]}～{p["upper"]}；已沿用 {p["age_bars"]} 根，宽度为最初的 {float(p["width_multiple"]):.2f} 倍。</p>')
        parts.extend([chart(bars),chart(bars[-32:]),'<p>请判断当前应参考：A．这个较大区间；B．最近新整理区间（请给大致上下沿或指出起始位置）；C．当前是趋势，旧区间已无参考意义；D．不确定。</p></section>'])
        saved.append(dict(id='L'+str(i),selection=p,bars=[{k:b[k] for k in ('time','open','high','low','close')} for b in bars]))
    out=ROOT/'output/subing-box-lifecycle-cases-20261104';out.mkdir(exist_ok=True)
    (out/'index.html').write_text('\n'.join(parts));(out/'cases.json').write_text(json.dumps(saved,ensure_ascii=False,indent=2)+'\n')
    print([(x['id'],x['selection']['time'],x['selection']['lower'],x['selection']['upper']) for x in saved])
if __name__=='__main__':main()
