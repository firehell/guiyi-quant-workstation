from pathlib import Path
import json,shutil
p=Path(__file__).resolve().parent
prior=p.parent/'2026-09-10'
text=(prior/'analyze.py').read_text().replace("OLD=P.parent/'2026-09-09'/'analysis.json'","OLD=P.parent/'2026-09-10'/'analysis.json'").replace("(P/'market.json').read_text()","(P/'market_history.json').read_text()")
text=text.replace("elif anchor_i+h>=len(times):st='待观察'","elif anchor_i+h>=len(times):st='数据不足' if m.get('current_day_endpoints_unavailable') else '待观察'")
text=text.replace("a['status']='PARTIAL' if any(m['errors'] or m.get('missing_count',0) for m in market.values()) else 'COMPLETED'","a['status']='PARTIAL' if any(m['errors'] or m.get('missing_count',0) or m.get('current_day_endpoints_unavailable') for m in market.values()) else 'COMPLETED'")
text=text.replace("['source.json','market.json']","['source.json','market.json','market_history.json','metadata.json']")
(p/'analyze.py').write_text(text)
old=json.loads((prior/'analysis.json').read_text())
formula={str(r['id']):{'status':'本次未复算；前次：'+r['formula_status']} for r in old['records']}
(p/'formula.json').write_text(json.dumps(formula,ensure_ascii=False,indent=2))
shutil.copyfile(prior/'delivery_evidence.json',p/'delivery_evidence.json')
