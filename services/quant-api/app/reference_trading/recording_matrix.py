"""Complete Newow observation matrix; missing records remain explicitly unknown."""

from app.reference_trading.query import QueryConflict

STRATEGIES = ("trend", "oscillation", "main_rise", "dual_fusion")
FREQUENCIES = ("1w", "1d", "60m")


def newow_recording_matrix(products, health: dict) -> dict:
    routes = {}
    for item in health["streams"]:
        code = item["strategy_code"].replace("-", "_")
        if not code.startswith("newow_"):
            continue
        strategy = code.removeprefix("newow_")
        key = (item["product"], strategy, item["frequency"])
        if key[0] not in products or strategy not in STRATEGIES or key[2] not in FREQUENCIES:
            continue
        if key in routes:
            raise QueryConflict("NEWOW_RECORDING_IDENTITY_CONFLICT")
        routes[key] = item
    endpoints = {(item["product"], item["frequency"]): item for item in health.get("source_endpoints", [])}
    items = []
    for product in products:
        for frequency in FREQUENCIES:
            for strategy in STRATEGIES:
                item = routes.get((product, strategy, frequency))
                items.append({
                    "product": product, "strategy": strategy, "frequency": frequency,
                    "stream_id": None, "enabled": False, "latest_state": None,
                    "computed_through": None, "status": "NOT_CONFIGURED",
                    "historical_computed_through": None, "observed_through": None,
                    "last_observed_at": None, "latest_state_source": None,
                    "latest_reconciliation_status": None,
                    "expected_through": None, "expected_source": "canonical_completed",
                    "endpoint_status": "UNKNOWN", "endpoint_reason": "ENDPOINT_NOT_VERIFIED",
                    **endpoints.get((product, frequency), {}), **(item or {}),
                })
    return {
        "version": "newow_recording_matrix_v2", "recording_mode": "forward_observation",
        "expected_count": len(items), "configured_count": len(routes),
        "enabled_count": sum(item["enabled"] is True for item in items),
        "observed_count": sum(item["observed_through"] is not None for item in items),
        "seeded_count": sum(item["historical_computed_through"] is not None for item in items),
        "items": items,
    }
