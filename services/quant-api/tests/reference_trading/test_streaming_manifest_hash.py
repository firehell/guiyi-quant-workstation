"""Persisted proofs retain their exact bytes when hashing becomes incremental."""
from dataclasses import asdict
from datetime import UTC, date, datetime
from decimal import Decimal
from hashlib import sha256
import json

import pytest

from app.reference_trading.contracts import manifest_sha256
from app.reference_trading.planning import canonical_sha256, _wire
from guiyi_quant.newow.models import NewowDailyBar
from guiyi_quant.newow.product_contracts import (
    ProductBar, ProductFrequency, lifecycle_input_sha256,
)


def test_manifest_digest_preserves_original_canonical_bytes():
    manifest = {'reader': 'newow_product_reader_prefix_v4', '中文': '焦煤',
                'input_fingerprints': [sha256(str(i).encode()).hexdigest() for i in range(1025)],
                'boundary': [None, False, {'end': '2026-10-30T07:00:00Z'}]}
    expected = sha256(json.dumps(manifest, sort_keys=True, separators=(',', ':'),
                                 ensure_ascii=True, allow_nan=False).encode()).hexdigest()
    assert manifest_sha256(manifest) == expected
    assert canonical_sha256(manifest) == expected


def test_planning_digest_preserves_dates_decimal_and_tuple():
    value = {'cutoff': datetime(2026, 10, 30, 7, tzinfo=UTC),
             'facts': (date(2026, 10, 30), Decimal('1401.00'))}
    expected = sha256(json.dumps(_wire(value), sort_keys=True, separators=(',', ':'),
                                 ensure_ascii=True).encode()).hexdigest()
    assert canonical_sha256(value) == expected


@pytest.mark.parametrize('bad', [float('nan'), float('inf'), object()])
def test_manifest_still_rejects_nonfinite_or_nonjson(bad):
    with pytest.raises(ValueError, match='finite canonical JSON'):
        manifest_sha256({'bad': bad})


def test_lifecycle_one_pass_iterator_matches_original_array_digest():
    bar = ProductBar(NewowDailyBar(
        product='jm', physical_contract='JM2611', segment_id='segment1',
        trading_day=date(2026, 10, 30), bar_end=datetime(2026, 10, 30, 7, tzinfo=UTC),
        open=Decimal('1400'), high=Decimal('1450'), low=Decimal('1390'), close=Decimal('1440'),
        volume=100, open_interest=200, source_identity='canonical',
        observation_eligible=True, completed=True,
    ), ProductFrequency.HOURLY)
    # The old persisted contract includes these exact fields and string prices.
    payload = asdict(bar.bar)
    payload.update(frequency=bar.frequency.value, series_kind=bar.series_kind,
                   trading_day=bar.bar.trading_day.isoformat(), bar_end=bar.bar.bar_end.isoformat())
    for key in ('open', 'high', 'low', 'close'):
        payload[key] = str(payload[key])
    expected = sha256(json.dumps([payload], ensure_ascii=False, sort_keys=True,
                                 separators=(',', ':')).encode()).hexdigest()
    assert lifecycle_input_sha256(iter((bar,))) == expected
    with pytest.raises(ValueError, match='INVALID_LIFECYCLE'):
        lifecycle_input_sha256(iter(()))
