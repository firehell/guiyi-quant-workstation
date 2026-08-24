from __future__ import annotations

from dataclasses import fields
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path

import app.research.jdj_strategy.service as strategy_service
from app.research.jdj_strategy.engine import JdjAction


_GOLDEN = Path(__file__).with_name("fixtures") / "jdj_jm_1m_v1_reference_golden.json"
_FIXTURE = Path(__file__).with_name("test_jdj_strategy_replay_service.py")


def _normalize(value: object):
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, tuple):
        return [_normalize(item) for item in value]
    raise TypeError(type(value).__name__)


def _project(action: JdjAction) -> dict[str, object]:
    return {
        item.name: _normalize(getattr(action, item.name))
        for item in fields(JdjAction)
    }


def test_jm_reference_projection_matches_pre_active60_golden(monkeypatch):
    spec = spec_from_file_location("_jdj_replay_fixture", _FIXTURE)
    assert spec is not None and spec.loader is not None
    fixture = module_from_spec(spec)
    spec.loader.exec_module(fixture)
    monkeypatch.setattr(
        strategy_service,
        "build_jdj_context_series",
        fixture._contexts,
    )

    actual = fixture._service(fixture._Reader()).history(fixture._request())
    expected = json.loads(_GOLDEN.read_text(encoding="utf-8"))

    expected_fields = [field.name for field in fields(JdjAction)]
    assert all(list(item.keys()) == expected_fields for item in expected)
    assert [_project(action) for action in actual.actions] == expected
