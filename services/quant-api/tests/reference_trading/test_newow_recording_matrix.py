from app.reference_trading.recording_matrix import newow_recording_matrix


def test_matrix_includes_missing_combinations_without_inventing_flat_state():
    report = newow_recording_matrix(("rb", "cu"), {"streams": []})
    assert report["expected_count"] == 24
    assert report["enabled_count"] == report["observed_count"] == 0
    assert len(report["items"]) == 24
    assert all(item["status"] == "NOT_CONFIGURED" for item in report["items"])
    assert all(item["latest_state"] is None for item in report["items"])


def test_matrix_does_not_count_historical_or_unrecognized_strategies():
    report = newow_recording_matrix(("rb",), {"streams": [
        {"strategy_code": "htdy", "product": "rb", "frequency": "60m"},
        {"strategy_code": "newow_trend", "product": "cu", "frequency": "60m"},
    ]})
    assert report["expected_count"] == 12 and report["configured_count"] == 0


def test_matrix_preserves_missing_period_and_actual_observation():
    state = {"version": "newow_bar_state_v1", "main_state": "HOLD"}
    report = newow_recording_matrix(("rb",), {"streams": [{
        "strategy_code": "newow_trend", "product": "rb", "frequency": "60m",
        "stream_id": "a", "enabled": True, "status": "READY",
        "latest_state": state, "computed_through": "2026-10-08T07:00:00+00:00",
        "observed_through": "2026-10-08T07:00:00+00:00",
    }]})
    assert report["configured_count"] == report["enabled_count"] == report["observed_count"] == 1
    item = next(item for item in report["items"] if item["stream_id"] == "a")
    assert item["latest_state"] == state


def test_historical_seed_state_is_not_counted_as_natural_observation():
    report = newow_recording_matrix(('rb',), {'streams': [{
        'strategy_code': 'newow_trend', 'product': 'rb', 'frequency': '60m',
        'stream_id': 'seeded', 'enabled': True, 'status': 'READY',
        'latest_state': {'version': 'newow_bar_state_v1', 'main_state': 'HOLD'},
        'computed_through': '2026-10-08T07:00:00+00:00',
        'historical_computed_through': '2026-10-08T07:00:00+00:00',
        'observed_through': None,
    }], 'source_endpoints': [{
        'product': 'rb', 'frequency': '60m', 'expected_through': '2026-10-08T07:00:00+00:00',
        'expected_source': 'canonical_completed', 'endpoint_status': 'READY',
    }]})
    assert report['version'] == 'newow_recording_matrix_v3'
    assert report['observed_count'] == 0
    assert report['seeded_count'] == 1
    assert report['configured_count'] == 1
    hourly = [item for item in report['items'] if item['frequency'] == '60m']
    assert all(item['expected_through'] == '2026-10-08T07:00:00+00:00' for item in hourly)
