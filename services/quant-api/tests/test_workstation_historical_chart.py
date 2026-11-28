from datetime import UTC, date, datetime
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from guiyi_quant.newow.product_contracts import ProductFrequency

from app.api.market_newow import workstation_historical_chart
from app.api.reference_trading import _run
from app.market_data.newow.workstation_history import selected_close
from app.runtime_bindings import ServiceBindingRootUnavailable

NOW = datetime(2026, 11, 28, 8, tzinfo=UTC)
DAY = date(2026, 11, 27)
CLOSE = datetime(2026, 11, 27, 7, tzinfo=UTC)


@pytest.mark.parametrize("requested", [None, DAY])
def test_selected_close_uses_completed_trading_day(requested):
    reader = Mock()
    reader.historical_snapshot_candidates.return_value = [(DAY, CLOSE)]
    assert selected_close(reader, "rb", ProductFrequency.DAILY, requested, NOW, lambda: False) == (DAY, CLOSE)
    assert reader.historical_snapshot_candidates.call_args.kwargs["limit"] == 1


def test_weekly_request_cannot_substitute_a_different_trading_day():
    reader = Mock()
    reader.weekly_snapshot_candidates.return_value = [(DAY, CLOSE)]
    with pytest.raises(ValueError, match="NEWOW_HISTORICAL_SNAPSHOT_UNAVAILABLE"):
        selected_close(reader, "rb", ProductFrequency.WEEKLY, NOW.date(), NOW, lambda: False)
    reader.historical_snapshot_candidates.assert_not_called()


def test_future_date_precedes_reader_access():
    reader = Mock()
    with pytest.raises(ValueError, match="NEWOW_INVALID_AS_OF"):
        selected_close(reader, "rb", ProductFrequency.DAILY, date(2026, 12, 1), NOW, lambda: False)
    assert not reader.mock_calls


@pytest.mark.parametrize(("query", "code"), [
    ("product=PD&strategy=trend&frequency=1d", "PRODUCT_RETIRED"),
    ("product=rb&strategy=trend&frequency=1d&product=cu", "NEWOW_INVALID_QUERY"),
    ("product=rb&strategy=trend&frequency=1d&receipt=wrong", "NEWOW_INVALID_QUERY"),
])
def test_invalid_or_retired_queries_do_not_compute(query, code):
    app = FastAPI()
    app.add_api_route("/historical-chart", workstation_historical_chart)
    response = TestClient(app).get("/historical-chart?" + query)
    assert response.status_code in (409, 422)
    assert response.json()["detail"]["code"] == code


def test_missing_archive_binding_has_service_status():
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as error:
        _run(Mock(side_effect=ServiceBindingRootUnavailable("SERVICE_BINDING_ROOT_UNAVAILABLE")))
    assert error.value.status_code == 503
    assert error.value.detail == {"code": "SERVICE_BINDING_ROOT_UNAVAILABLE"}


def test_repeated_weekly_endpoint_is_scoped_to_its_formal_receipt(tmp_path):
    from app.market_data.after_market_history import _digest, publish_history
    from app.market_data.newow.market_reference_sections import _load, _path, _SCHEMA

    reference = {"stream_id": "reference-stream:" + "e" * 64, "revision_id": "r1", "seq": 1, "cutoff": CLOSE}
    data = {**reference, "schema": _SCHEMA, "cutoff": CLOSE.isoformat(), "chart": {}, "sections": {}}
    old, new = "a" * 64, "b" * 64
    for key, receipt in ((reference, old), ({**reference, "receipt": new}, new)):
        content = {**data, "receipt": receipt}
        publish_history(_path(tmp_path, key), {**content, "sha256": _digest(content)})
        assert _load(tmp_path, {**reference, "receipt": receipt})["receipt"] == receipt
        if receipt == old:
            assert _load(tmp_path, {**reference, "receipt": new}) is None
    assert _load(tmp_path, {**reference, "receipt": old})["receipt"] == old
