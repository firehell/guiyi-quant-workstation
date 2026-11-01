import sys,subprocess,json,hashlib
from pathlib import Path
R=Path(__file__).resolve().parent;OLD=R.parent/'htdy-ta-60m-70pct-20261031'
symbol=sys.argv[1];data_root=sys.argv[2] if len(sys.argv)>2 else str(OLD)
for policy in ['original','atr_matched','atr2','atr3','trend_filter','osc_exit','long_flat','newow_trend','newow_oscillation','newow_dual']:
 for slip in [1,2]:
  out=R/'runs'/f'{symbol}_{policy}_slip{slip}'
  if out.exists():
   receipt=json.loads((out/'complete.json').read_text())
   for name,sha in receipt['files'].items():assert hashlib.sha256((out/name).read_bytes()).hexdigest()==sha,'EXISTING_RESULT_HASH_MISMATCH'
   assert json.loads((out/'summary.json').read_text())['input_hash']==receipt['input_hash'],'EXISTING_RESULT_IDENTITY_MISMATCH'
   continue
  cmd=[sys.executable,str(OLD/'supervise.py'),'--name',f'optim-{symbol}-{policy}-{slip}',sys.executable,str(R/'experiment.py'),'--symbol',symbol,'--policy',policy,'--slip',str(slip),'--data-root',data_root]
  result=subprocess.run(cmd)
  if result.returncode:raise SystemExit(result.returncode)
