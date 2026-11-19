"""One persistent private Paper owner, independent of release checkout paths."""
from pathlib import Path

STATE_ROOT = Path.home() / "Library/Application Support/GuiyiQuant/subing-paper"
ACTIVE_PORTFOLIO = STATE_ROOT / "subing-portfolio-active.json"
HEARTBEAT = STATE_ROOT / "subing-portfolio-heartbeat.json"
DB_PATH = STATE_ROOT / "subing-model-database.url"
FACTS_REGISTRY = STATE_ROOT / "facts"
# Research registration is intentionally separate from active Paper state.
HISTORY = Path.home() / "Library/Application Support/GuiyiQuant/subing-portfolio-history.json"
