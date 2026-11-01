"""Final-source baseline attempt; preserve the initial result verbatim."""
from pathlib import Path
import experiment
root=Path(__file__).resolve().parent;attempt=root/'baseline-final';attempt.mkdir(exist_ok=True)
link=attempt/'TA-features.json'
if not link.exists():link.symlink_to(root/'TA-features.json')
experiment.R=attempt
experiment.run('TA','original',1,experiment.OLD)
