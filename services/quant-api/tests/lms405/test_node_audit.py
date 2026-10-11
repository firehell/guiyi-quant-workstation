import importlib.util
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace


def test_publication_bar_and_equal_start_are_excluded():
    root = Path(__file__).resolve().parents[4]
    spec = importlib.util.spec_from_file_location(
        "audit", root / "scripts/research/lms405_node_audit.py"
    )
    audit = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(audit)
    published = datetime.fromisoformat("2026-10-09T10:14:00+08:00")
    bars = [
        SimpleNamespace(
            bar_end=published + timedelta(minutes=i),
            low=Decimal("100"),
            high=Decimal("102"),
            close=Decimal("102"),
        )
        for i in range(3)
    ]
    result = audit.geometry(bars, published, Decimal("100"), Decimal("101"))
    assert result["eligible_bars"] == 1
    assert result["first_lower_touch"] == (published + timedelta(minutes=2)).isoformat()
    assert result["condition_satisfied"] is None
    assert result["stand_firm"] == "UNKNOWN"
    assert result["action_match"] is None


def test_no_eligible_bars_does_not_imply_failure_or_trade():
    root = Path(__file__).resolve().parents[4]
    spec = importlib.util.spec_from_file_location(
        "audit", root / "scripts/research/lms405_node_audit.py"
    )
    audit = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(audit)
    result = audit.geometry(
        [],
        datetime.fromisoformat("2026-10-09T10:14:00+08:00"),
        Decimal("1"),
        Decimal("2"),
    )
    assert result["minimum_low"] is None
    assert result["first_lower_touch"] is None
    assert result["condition_satisfied"] is None
