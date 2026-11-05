"""Explicit read-only bindings to existing development model and replay data."""
import json
from pathlib import Path

from app.new_subing_research.store import _safe_root
from app.private_settings import read_private_settings_content

BINDING = Path.home() / 'Library/Application Support/GuiyiQuant/subing-development-read.json'


def registered_source(key: str) -> Path | None:
    if not BINDING.exists() and not BINDING.is_symlink():
        return None
    _safe_root(BINDING.parent)
    value = json.loads(read_private_settings_content(BINDING))
    if not isinstance(value, dict) or set(value) != {'model_root', 'results_root'}:
        raise ValueError('MODEL_READ_SOURCE_INVALID')
    roots = {}
    for name, raw in value.items():
        if not isinstance(raw, str):
            raise ValueError('MODEL_READ_SOURCE_INVALID')
        root = Path(raw)
        if not root.is_absolute() or '..' in root.parts or not root.is_dir():
            raise ValueError('MODEL_READ_SOURCE_INVALID')
        roots[name] = _safe_root(root)
    return roots[key]
