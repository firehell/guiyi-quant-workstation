"""Bind accepted runs to exact local research inputs, source and Tick artifacts."""
import json,hashlib
from pathlib import Path
R=Path(__file__).resolve().parent;OLD=R.parent/'htdy-ta-60m-70pct-20261031'
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
 return h.hexdigest()
files={}
for p in [OLD/'engine_base.py',OLD/'replay.py',OLD/'bounded.py',OLD/'spool.py']:files[str(p)]=sha(p)
for sym,base in [('TA',OLD),('MA',R/'ma_data')]:
 e=base/sym/'evidence'
 for p in sorted(e.glob('*.json'))+[e/'execution.sqlite',base/'common/public-fees.json',base/'common/margin_snapshot.csv']:
  files[str(p)]=sha(p)
 for x in json.loads((e/'tick-index.json').read_text()).values():
  p=Path(x['path']);files[str(p)]=sha(p)
 capture=R/(sym+'-features.json');files[str(capture)]=sha(capture)
for p in sorted(R.glob('*.py')):files[str(p)]=sha(p)
runs={}
for p in sorted((R/'runs').glob('*/summary.json')):
 if p.parent.name=='TA_original_slip1':p=R/'baseline-final/runs/TA_original_slip1/summary.json'
 s=json.loads(p.read_text());runs[s['scenario']]={'summary_path':str(p),'summary_sha256':sha(p),'input_hash':s['input_hash'],'status':s['status']}
for sym in ['TA','MA']:
 for x in json.loads((R/(sym+'-tick-input-verification.json')).read_text()):assert sha(Path(x['path']))==x['sha256'],'TICK_INPUT_CHANGED_DURING_STUDY'
(R/'study-identity.json').write_text(json.dumps({'files':files,'accepted_runs':runs,'early_TA_original_slip1':'preserved at runs/TA_original_slip1; superseded by baseline-final attempt','TA_feature_equivalence':'TA-feature-equivalence.json'},indent=2))
print('Bound',len(runs),'accepted scenarios;',len(files),'source/input artifacts')
