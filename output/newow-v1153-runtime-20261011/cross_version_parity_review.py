import sys,json,dataclasses,enum
from pathlib import Path
root=Path(sys.argv[1]); project=Path('/Volumes/扩展盘/guiyi-quant-workstation')
sys.path[:0]=[str(root/'services/quant-api'),str(root/'packages/quant-core'),str(project/'services/quant-api')]
import importlib.util
spec=importlib.util.spec_from_file_location('review_fixtures',project/'services/quant-api/tests/newow/product_fixtures.py'); f=importlib.util.module_from_spec(spec);sys.modules[spec.name]=f;spec.loader.exec_module(f)
from guiyi_quant.newow.product_adapters import replay_strategy,replay_step,seed_replay_state
from guiyi_quant.newow.subplots import calculate_zhaoyao_mirror

def wire(x):
 if dataclasses.is_dataclass(x):
  value={p.name:wire(getattr(x,p.name)) for p in dataclasses.fields(x) if p.name not in {'ma10_display_v1','confirmed_peak_events'}}
  if 'main_values' in value:value['main_values']=[v for v in value['main_values'] if v[0] not in {'ma10_display_v1','magic11_count'}]
  return value
 if isinstance(x,dict):return {str(k):wire(v) for k,v in x.items()}
 if isinstance(x,(tuple,list)):return [wire(v) for v in x]
 if isinstance(x,enum.Enum):return x.value
 if x is None or isinstance(x,(str,int,float,bool)):return x
 return str(x)
rows={}; cases=f.ProductCases()
for strategy in ('trend','oscillation','main_rise'):
 for freq in ('1d','1w','60m'):
  case=cases.primitive_input(strategy,freq)
  state=seed_replay_state(); frames=[]
  for bar in case.bars:
   state,frame,diag=replay_step(case.identity,state,bar);frames.append(wire((state,frame,diag)))
  rows[strategy+':'+freq]={'batch':wire(replay_strategy(case.identity,case.bars)),'incremental':frames,
   'subplot_prefixes':[wire(calculate_zhaoyao_mirror(tuple(b.bar for b in case.bars[:n]))) for n in range(1,len(case.bars)+1)]}
Path(sys.argv[2]).write_text(json.dumps(rows,sort_keys=True,separators=(',',':')))
print(json.dumps({'root':str(root),'scenarios':len(rows),'incremental_steps':sum(len(x['incremental']) for x in rows.values())}))
