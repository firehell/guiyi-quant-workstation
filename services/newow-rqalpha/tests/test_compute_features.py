from datetime import timedelta

import pytest

from compute_features import completed_minute_features
from guiyi_quant.compute import FeatureRequest, Status
from test_minute_execution import market


def test_research_input_is_bounded_to_its_frozen_physical_minutes():
    source = market()
    as_of = source.minutes[9].end + timedelta(seconds=1)
    result, = completed_minute_features(
        source, (FeatureRequest("ema10"),), source_sha256="1" * 64, as_of=as_of,
    )
    assert result.identity.source.physical_contract == source.contract
    assert result.identity.source.source_revision == "1" * 64
    assert len(result.points) == 10
    assert result.points[-1].status is Status.READY
    assert result.points[-1].available_at == source.minutes[9].end
    assert result.points[-1].values["value"] == sum(
        float(row.close) for row in source.minutes[:10]
    ) / 10


def test_unidentified_frozen_input_fails_closed():
    source = market()
    with pytest.raises(ValueError, match="RQALPHA_SOURCE_DIGEST_INVALID"):
        completed_minute_features(source, (), source_sha256="unknown", as_of=source.minutes[-1].end)
