"""Serial, exact planned research jobs; no blind retry or parallel worker."""
import json, subprocess, sys
from pathlib import Path
R=Path(__file__).resolve().parent
for job in json.loads((R/'plan.json').read_text())['jobs']:
 c,day=job['contract'],job['day']
 if c=='MA2305':
  status=R/'MA/evidence/exit-quotes-attempt2'/f'{c}-{day}.json'
  if not status.exists() or json.loads(status.read_text())['status']!='VERIFIED_AND_IMPORTED':raise SystemExit('FIRST_JOB_NOT_VERIFIED')
  continue
 code=subprocess.call([sys.executable,str(R/'supervise.py'),'--name',f'supplement-{c}-{day}',sys.executable,str(R/'prepare.py'),'supplement','--contract',c,'--day',day])
 if code:raise SystemExit(code)
subprocess.run([sys.executable,str(R/'prepare.py'),'refresh'],check=True)
