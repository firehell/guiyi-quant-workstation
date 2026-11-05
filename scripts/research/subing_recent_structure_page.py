"""Show current candidate boundaries only from their known-at timestamp."""
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import json
from subing_box_lifecycle_cases import chart
ROOT=Path(__file__).resolve().parents[2]

def main():
    out=ROOT/'output/subing-recent-structure-20261104'
    result=json.loads((out/'result.json').read_text());by_id={c['id']:c for c in result['cases']}
    parts=['<!doctype html><meta charset="utf-8"><title>苏冰 · 近期结构边界</title><style>body{font:16px system-ui;max-width:1200px;margin:30px auto;padding:20px;background:#f4f6fa;color:#233047}section{background:white;padding:24px;border-radius:12px;margin:24px 0}svg{width:100%}p{line-height:1.8}.badge{background:#eef3ff;padding:6px 12px;border-radius:6px}</style><h1>近期结构：边界与突破确认分开看</h1><p>蓝色虚线是本时刻自动提取的参考边界，从本组边界实际可知时刻开始画；它不是历史全程的箱体轨迹，也不代表已经判定震荡。每例上图128根、下图32根，不展示未来。算法参数是研究假设，不是正式交易规则。</p>']
    for name in ('C04','L2','L1','C03'):
        c=by_id[name];p=c['point'];lower=float(p['lower']);upper=float(p['upper']);stamp=datetime.fromisoformat(c['at']).astimezone(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d %H:%M')
        status=('尚未突破当前边界' if p['count']==0 else f"向{'下' if p['break_side']=='DOWN' else '上'}破位：突破当根＋后续{p['count']-1}根，尚需{4-p['count']}根收盘确认")
        parts.append(f'<section><h2>{name} · {c["contract"]} · {stamp} 北京时间</h2><p><span class="badge">{lower:g}～{upper:g}</span>　{status}</p>')
        for n in (128,32):
            bs=c['bars'][-n:];base=chart(bs)
            lo=min(b['low'] for b in bs);hi=max(b['high'] for b in bs);span=max(hi-lo,1);lo-=span*.06;hi+=span*.06
            y=lambda v:270-(v-lo)/(hi-lo)*240
            start=next((i for i,b in enumerate(bs) if datetime.fromisoformat(b['time'])>=datetime.fromisoformat(p['boundary_at'])),len(bs)-1)
            x=70+start*880/len(bs)
            overlays=''
            for value in (lower,upper):
                if lo<=value<=hi:
                    overlays+=f'<path d="M{x} {y(value)}H960" stroke="#3267ce" stroke-dasharray="6 4" stroke-width="2"/><text x="870" y="{y(value)-5}" fill="#3267ce" font-size="13">{value:g}</text>'
                else:overlays+=f'<text x="650" y="{20 if value>hi else 285}" fill="#3267ce" font-size="12">另一边界 {value:g} 在当前缩放范围外</text>'
            parts.append(base.replace('</svg>',overlays+'</svg>'))
        parts.append('</section>')
    parts.append('<section><h2>本次只需核对两项</h2><p>1．L2蓝色边界1095～1159.5，是否对应你认可的近期整理区？若不对应，请指出偏宽、偏窄或起点不对。</p><p>2．L1/C03已经向下破位，但三根确认尚未完成。建议显示“向下破位，待确认”：已有持仓继续按原保护规则处理，不能仅凭破位就新增仓位；等三根确认后仍需苏冰位置、信号和风险条件。是否符合你的意思？</p><p>这些是已见开发案例，不能据此计算模型准确率。本页仅用于语义核对，没有改变v2或交易规则。</p></section>')
    (out/'index.html').write_text('\n'.join(parts))
    print('Rendered C04/L2/L1/C03 with then-known boundaries; 8 charts.')
if __name__=='__main__':main()
