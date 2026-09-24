"""P9 inventory enumerates identities and never turns them into data readiness."""

from __future__ import annotations

import pytest
from pathlib import Path
import runpy
import os

from app.market_data.newow.product_release import OPEN_WEEKLY_PRODUCTS
from app.market_data.operational_universe import load_active_products, load_operational_products
from guiyi_quant.newow.product_identity import futures_adaptation_version
from app.market_data.newow.product_release import candidate_input_quality_policy

_manifest = runpy.run_path(str(
    Path(__file__).resolve().parents[2] / "scripts/reference_trading_p9_manifest.py"
))
enumerate_scope = _manifest["enumerate_scope"]
write_new_manifest = _manifest["write_new_manifest"]


def test_formal_p9_inventory_has_exact_stream_denominators_and_no_data_claim():
    active, operational = load_active_products(), load_operational_products()
    result = enumerate_scope(active, operational, tuple(OPEN_WEEKLY_PRODUCTS), {})

    assert result["counts"] == {
        "historical_formal": 600,
        "forward_formal": 540,
        "historical_capability_closed": 180,
        "forward_capability_closed": 180,
        "model_not_approved": 60,
        "existing_formal": 0,
        "unmatched_existing": 0,
    }
    rows = result["streams"]
    assert len(rows) == 1560
    assert all(row["data_gate"] == "UNVERIFIED" for row in rows if row["gate"] == "FORMAL_CANDIDATE")
    assert all(row["gate"] == "CAPABILITY_CLOSED" for row in rows if row["strategy_code"].startswith("newow_") and row["frequency"] == "60m")
    assert all(row["gate"] == "MODEL_NOT_APPROVED" for row in rows if row["strategy_code"] == "htdy")
    assert len({row["stream_id"] for row in rows if row["stream_id"] is not None}) == 1500


def test_formal_p9_newow_streams_bind_the_released_quality_policy():
    scope = enumerate_scope(
        load_active_products(), load_operational_products(), tuple(OPEN_WEEKLY_PRODUCTS), {},
    )
    changed = []
    for row in scope["streams"]:
        if row["gate"] != "FORMAL_CANDIDATE" or not row["strategy_code"].startswith("newow_"):
            continue
        policy = candidate_input_quality_policy(
            row["product"], row["frequency"], candidate_weekly=False,
        )
        assert row["futures_adaptation_version"] == futures_adaptation_version(
            row["frequency"], policy,
        )
        if policy.value != "newow_input_quality_v1":
            changed.append(row)
    assert len(changed) == 174


def test_p9_inventory_matches_existing_rb_identity_and_records_disabled_state():
    active, operational = load_active_products(), load_operational_products()
    rb_trend_d1 = "reference-stream:e93bb7f9c720d0ec31a59f83e92438a57ce592aceca8be12dcd236243166aa70"
    stored = {
        rb_trend_d1: {
            "recording_mode": "historical_replay", "enabled": False,
            "health": "READY", "active_revision_id": "revision", "latest_seq": 11,
            "row_version": 1,
        },
    }

    result = enumerate_scope(active, operational, tuple(OPEN_WEEKLY_PRODUCTS), stored)

    assert result["counts"]["existing_formal"] == 1
    row = next(item for item in result["streams"] if item["stream_id"] == rb_trend_d1)
    assert row["existing"] == stored[rb_trend_d1]
    assert row["data_gate"] == "UNVERIFIED"


def test_p9_inventory_exposes_unmatched_database_streams():
    active, operational = load_active_products(), load_operational_products()
    result = enumerate_scope(active, operational, tuple(OPEN_WEEKLY_PRODUCTS), {
        "reference-stream:old-identity": {"enabled": False},
    })
    assert result["counts"]["unmatched_existing"] == 1
    assert result["unmatched_existing_stream_ids"] == ["reference-stream:old-identity"]


def test_p9_inventory_rejects_capability_or_universe_drift():
    active, operational = load_active_products(), load_operational_products()
    with pytest.raises(ValueError, match="P9_SCOPE_UNIVERSE_INVALID"):
        enumerate_scope(active, operational, tuple(OPEN_WEEKLY_PRODUCTS[:-1]), {})
    with pytest.raises(ValueError, match="P9_SCOPE_UNIVERSE_INVALID"):
        enumerate_scope(active[:-1], operational, tuple(OPEN_WEEKLY_PRODUCTS), {})


def test_p9_inventory_output_is_exclusive_and_does_not_follow_symlinks(tmp_path):
    target = tmp_path / "existing.json"
    target.write_text("original")
    link = tmp_path / "manifest.json"
    link.symlink_to(target)
    with pytest.raises(FileExistsError):
        write_new_manifest(link, {"readonly": True})
    assert target.read_text() == "original"
    link.unlink()
    saved = write_new_manifest(link, {"readonly": True})
    assert saved == link
    assert '"readonly": true' in link.read_text()
    assert os.stat(link).st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        write_new_manifest(link, {"readonly": False})
