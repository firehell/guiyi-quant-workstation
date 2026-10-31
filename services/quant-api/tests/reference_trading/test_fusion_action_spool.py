from dataclasses import replace
from datetime import timedelta, timezone
from decimal import Decimal
from hashlib import sha256
import json

import pytest

from app.reference_trading.fusion_action_spool import FusionActionSpool
from app.reference_trading.inputs import _action_wire
from guiyi_quant.newow.product_adapters import build_product_identity
from guiyi_quant.newow.product_contracts import ProductFrequency, ProductStrategy
from newow.product_fixtures import ProductCases


def _actions():
    cases = ProductCases()
    trend = cases.closed(strategy="trend", frequency="1m").entry
    oscillation = cases.closed(strategy="oscillation", frequency="1m").entry
    trend_identity = build_product_identity("rb", ProductStrategy.TREND, ProductFrequency.MINUTE)
    oscillation_identity = build_product_identity(
        "rb", ProductStrategy.OSCILLATION, ProductFrequency.MINUTE
    )
    first = replace(trend, identity=trend_identity)
    second = replace(first, sequence=first.sequence + 1)
    third = replace(
        oscillation, identity=oscillation_identity,
        physical_contract=first.physical_contract, segment_id=first.segment_id,
        calculation_segment_id=first.calculation_segment_id,
        bar_end=first.bar_end, trading_day=first.trading_day,
    )
    key = (
        first.bar_end, first.physical_contract,
        first.segment_id, first.calculation_segment_id,
    )
    return key, (first, second, third)


def test_spool_is_on_disk_preserves_same_bar_strategy_and_source_order():
    key, expected = _actions()
    spool = FusionActionSpool()
    path = spool._path
    try:
        assert path.is_file()
        assert path.stat().st_mode & 0o777 == 0o600
        for action in expected:
            spool.append(action)
        assert spool.get(key) == expected
        assert spool.get((key[0].astimezone(timezone(timedelta(hours=8))), *key[1:])) == expected
        assert list(spool.items()) == [(key, expected)]
        assert spool.get((key[0], "UNKNOWN", *key[2:])) == ()
        spool.append(expected[0])
        assert spool.get(key) == (*expected, expected[0])
    finally:
        spool.close()
    assert not path.exists()
    with pytest.raises(ValueError, match="REFERENCE_FUSION_ACTION_SPOOL_CLOSED"):
        spool.get(key)


def test_spool_rechecks_decoded_action_wire_and_cleans_after_failure():
    key, expected = _actions()
    spool = FusionActionSpool()
    path = spool._path
    try:
        spool.append(expected[0])
        spool._connection.execute(
            "UPDATE actions SET signal_id=? WHERE signal_id=?",
            ("f" * 64, expected[0].signal_id),
        )
        with pytest.raises(ValueError, match="REFERENCE_FUSION_SOURCE_NOT_READY"):
            spool.get(key)
        wire = _action_wire(expected[0])
        wire["reference_price"] = "999"
        spool._connection.execute(
            "UPDATE actions SET signal_id=?, payload=? WHERE signal_id=?",
            (expected[0].signal_id, json.dumps(wire), "f" * 64),
        )
        with pytest.raises(ValueError, match="REFERENCE_FUSION_SOURCE_NOT_READY"):
            spool.get(key)
        spool._connection.execute(
            "UPDATE actions SET payload=?, payload_sha256=? WHERE signal_id=?",
            ("{}", sha256(b"{}").hexdigest(), expected[0].signal_id),
        )
        with pytest.raises(ValueError, match="REFERENCE_SPOOL_CODEC_INVALID"):
            spool.get(key)
    finally:
        spool.close()
    assert not path.exists()


def test_spool_keeps_duplicate_rows_for_the_existing_reference_kernel():
    from guiyi_quant.newow.reference_trades import _dedupe_actions

    key, expected = _actions()
    changed = replace(expected[0], reference_price=expected[0].reference_price + Decimal("1"))
    assert changed.signal_id == expected[0].signal_id
    spool = FusionActionSpool()
    try:
        for action in (expected[0], expected[0], changed):
            spool.append(action)
        saved = spool.get(key)
        assert saved == (expected[0], expected[0], changed)
        with pytest.raises(ValueError, match="NEWOW_REFERENCE_ID_CONTENT_CONFLICT"):
            _dedupe_actions(saved)
        assert _dedupe_actions(saved[:2]) == (expected[0],)
    finally:
        spool.close()
