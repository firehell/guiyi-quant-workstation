"""Sequential final-source baseline, feature equivalence and independent valuations."""
import os,sys,subprocess
from pathlib import Path
R=Path(__file__).resolve().parent;OLD=R.parent/'htdy-ta-60m-70pct-20261031'
def run(name,script,*args):
 env=os.environ.copy();env['PYTHONPATH']='services/quant-api:packages/quant-core'
 subprocess.run([sys.executable,str(OLD/'supervise.py'),'--name',name,sys.executable,str(R/script),*args],env=env,check=True)
run('optim-baseline-final','baseline_final.py')
run('optim-feature-final','feature_final.py')
run('optim-valuation-TA','verify_valuations.py','--symbol','TA')
run('optim-valuation-MA','verify_valuations.py','--symbol','MA')
run('optim-summary','summarize.py')
subprocess.run([sys.executable,str(R/'compare.py')],check=True)
subprocess.run([sys.executable,'-m','pytest','-q',str(R/'test_experiment.py'),str(R/'test_review.py')],check=True)
subprocess.run([sys.executable,str(R/'study_identity.py')],check=True)
