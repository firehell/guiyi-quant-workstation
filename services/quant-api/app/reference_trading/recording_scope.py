"""One explicit Newow recording scope; capability does not activate streams."""

FREQUENCIES = ("1w", "1d", "60m", "5m", "15m", "30m")
H1_BOUNDARY_POLICY = "newow_h1_from_new_observation_v1"
H1_INTERVAL_POLICY = "newow_h1_retired_interval_v1"
H1_BOUNDARY_POLICIES = frozenset({H1_BOUNDARY_POLICY, H1_INTERVAL_POLICY})

LIVE_FREQUENCIES = ("5m", "15m", "30m", "60m")
STRATEGIES = ("trend", "oscillation", "main_rise", "dual_fusion")
MAX_ROUTES = 60 * len(FREQUENCIES) * len(STRATEGIES)


class ReferenceCalculationRetired(ValueError):
    code = "REFERENCE_STRATEGY_RETIRED"


def require_active_calculation(strategy):
    """Reject new work without changing legacy identity/plan decoding."""
    if strategy.replace("-", "_") in {"htdy", "subing_reference"}:
        raise ReferenceCalculationRetired("REFERENCE_STRATEGY_RETIRED")


def retired_calculation_clause(stream):
    from sqlalchemy import func

    return func.replace(stream.strategy_code, "-", "_").in_(("htdy", "subing_reference"))


def strategies_for(frequency):
    return STRATEGIES if frequency in FREQUENCIES else ()


def recording_route_supported(strategy, frequency):
    return strategy.replace("-", "_").removeprefix("newow_") in strategies_for(frequency)


def calculation_scope_clause(stream):
    """Active calculation scope; legacy streams and journals remain immutable.

    Database activation alone cannot re-enable retired HTDY/SuBing reference
    calculations. Alert evaluation and account execution do not use this scope.
    """
    from sqlalchemy import and_, func

    return and_(
        func.replace(stream.strategy_code, "-", "_").in_(
            tuple(f"newow_{strategy}" for strategy in STRATEGIES)
        ),
        stream.frequency.in_(FREQUENCIES),
    )
