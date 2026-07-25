from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "services/quant-api/alembic/versions/20260725_0026_htdy_observation_alerts.py"


def test_htdy_observation_migration_is_additive_and_bound_to_current_head() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    assert 'revision = "20260725_0026"' in source
    assert 'down_revision = "20260721_0025"' in source
    assert 'op.create_table(\n        "htdy_observation_alerts"' in source
    assert 'op.add_column(\n        "signal_notifications"' in source
    assert '"observation_alert_id"' in source
    assert '"source_kind"' in source
    assert "UPDATE " not in source.upper()
    assert "DELETE " not in source.upper()
