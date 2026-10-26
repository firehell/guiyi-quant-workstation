"""One explicit Newow recording scope; capability does not activate streams."""

FREQUENCIES = ("1w", "1d", "60m", "5m", "15m", "30m")
LIVE_FREQUENCIES = ("5m", "15m", "30m", "60m")
STRATEGIES = ("trend", "oscillation", "main_rise", "dual_fusion")
MAX_ROUTES = 60 * len(FREQUENCIES) * len(STRATEGIES)

def strategies_for(frequency):
    return STRATEGIES if frequency in FREQUENCIES else ()

def recording_route_supported(strategy, frequency):
    return strategy.replace("-", "_").removeprefix("newow_") in strategies_for(frequency)
