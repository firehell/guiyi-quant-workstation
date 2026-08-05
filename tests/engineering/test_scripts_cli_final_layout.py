"""Regression coverage for the post-consolidation scripts layout."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]


def _load_disposition():
    path = ROOT / "scripts" / "engineering" / "script_disposition.py"
    spec = importlib.util.spec_from_file_location("script_disposition", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_post_consolidation_tracked_scripts_match_final_layout() -> None:
    disposition = _load_disposition()

    report = disposition.validate_final_layout(disposition.list_tracked_scripts(ROOT))

    assert report.ok, report.errors
