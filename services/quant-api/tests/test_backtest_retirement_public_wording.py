from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def test_active_public_surfaces_do_not_promise_retired_backtesting() -> None:
    active_public_sources = (
        PROJECT_ROOT / "services/quant-api/app/services/strategy_registry.py",
        PROJECT_ROOT / "services/quant-api/app/services/market_dominant_reader.py",
        PROJECT_ROOT / "apps/quant-web/src/utils/marketChartQuery.ts",
        PROJECT_ROOT / "apps/quant-web/src/pages/market/index.vue",
    )

    forbidden_terms = ("回测", "backtest")
    assert all(
        all(term not in path.read_text(encoding="utf-8").lower() for term in forbidden_terms)
        for path in active_public_sources
    )
