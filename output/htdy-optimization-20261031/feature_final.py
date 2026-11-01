"""Final feature-source provenance, exact numeric equivalence to consumed TA capture."""
import json,hashlib
from pathlib import Path
import features
root=Path(__file__).resolve().parent;attempt=root/'feature-final';attempt.mkdir(exist_ok=True);features.R=attempt
features.main('TA')
old=json.loads((root/'TA-features.json').read_text());new=json.loads((attempt/'TA-features.json').read_text());assert old['rows']==new['rows'];assert old['proofs']==new['proofs']
(root/'TA-feature-equivalence.json').write_text(json.dumps({'status':'PASS','rows':len(old['rows']),'proofs':len(old['proofs']),'old_capture_sha256':hashlib.sha256((root/'TA-features.json').read_bytes()).hexdigest(),'final_capture_sha256':hashlib.sha256((attempt/'TA-features.json').read_bytes()).hexdigest(),'final_capture_source_sha256':new['source_sha256'],'note':'Actual runs consumed old immutable capture; final source reproduces exact rows and owner proofs'},indent=2))
