from fastapi.testclient import TestClient

from app.main import app


def test_web_macd_legacy_policy_vectors_and_prefix_invariance() -> None:
    from guiyi_quant.indicators import macd_series

    closes = _jm_closes(42)
    result = macd_series(
        closes,
        12,
        26,
        9,
        ema_seed_policy="sma_window",
        histogram_scale=2,
        round_digits=6,
    )
    expected = _web_macd_style(closes)

    assert result.indicator_version == "v1-draft"
    assert result.parameters["ema_seed_policy"] == "sma_window"
    assert result.parameters["histogram_scale"] == 2
    assert result.calculation_basis["warmup_bars"] == 33
    assert _values(result.dea.points) == expected["dea"]
    assert _values(result.histogram.points) == expected["histogram"]
    for index, expected_dif in enumerate(expected["dif"]):
        if expected_dif is not None:
            assert result.dif.points[index].value == expected_dif

    prefix = macd_series(
        closes[:36],
        12,
        26,
        9,
        ema_seed_policy="sma_window",
        histogram_scale=2,
        round_digits=6,
    )
    extended = macd_series(
        closes[:36] + [1500.0, 1490.0],
        12,
        26,
        9,
        ema_seed_policy="sma_window",
        histogram_scale=2,
        round_digits=6,
    )
    assert _values(prefix.dif.points) == _values(extended.dif.points[:36])
    assert _values(prefix.dea.points) == _values(extended.dea.points[:36])
    assert _values(prefix.histogram.points) == _values(
        extended.histogram.points[:36]
    )

    short = macd_series(
        closes[:20],
        12,
        26,
        9,
        ema_seed_policy="sma_window",
        histogram_scale=2,
        round_digits=6,
    )
    assert all(point.value is None for point in short.histogram.points)

    invalid = macd_series(
        closes[:20] + [None] + closes[21:42],
        12,
        26,
        9,
        ema_seed_policy="sma_window",
        histogram_scale=2,
    )
    assert invalid.dif.points[20].valid is False
    assert invalid.histogram.points[20].reason == "input_invalid"


def test_public_macd_alias_has_only_canonical_selection_parameters() -> None:
    operation = TestClient(app).get("/openapi.json").json()["paths"][
        "/api/v1/market/indicators/macd"
    ]["get"]
    names = {item["name"] for item in operation["parameters"]}

    assert {"dataset_kind", "symbol", "frequency", "start", "end"} <= names
    assert {
        "profile_id",
        "market_data_file_id",
        "expected_market_data_file_id",
        "expected_lineage_token",
        "access_mode",
        "provider",
        "data_role",
    }.isdisjoint(names)


def _jm_closes(count: int) -> list[float]:
    return [1680.0 + index * 1.7 + (index % 5 - 2) * 4.0 for index in range(count)]


def _values(points: list[object]) -> list[float | None]:
    return [getattr(point, "value") for point in points]


def _web_macd_style(closes: list[float]) -> dict[str, list[float | None]]:
    fast = _ema_sma_seeded(closes, 12)
    slow = _ema_sma_seeded(closes, 26)
    dif = [
        None if fast_value is None or slow_value is None else fast_value - slow_value
        for fast_value, slow_value in zip(fast, slow, strict=True)
    ]
    dea = _ema_nullable(dif, 9)
    histogram = [
        None
        if dif_value is None or dea_value is None
        else round((dif_value - dea_value) * 2, 6)
        for dif_value, dea_value in zip(dif, dea, strict=True)
    ]
    return {
        "dif": [None if value is None else round(value, 6) for value in dif],
        "dea": [None if value is None else round(value, 6) for value in dea],
        "histogram": histogram,
    }


def _ema_sma_seeded(values: list[float], period: int) -> list[float | None]:
    output: list[float | None] = [None] * len(values)
    if len(values) < period:
        return output
    seed = sum(values[:period]) / period
    output[period - 1] = seed
    alpha = 2 / (period + 1)
    previous = seed
    for index in range(period, len(values)):
        previous = alpha * values[index] + (1 - alpha) * previous
        output[index] = previous
    return output


def _ema_nullable(values: list[float | None], period: int) -> list[float | None]:
    output: list[float | None] = [None] * len(values)
    valid = [(index, value) for index, value in enumerate(values) if value is not None]
    if len(valid) < period:
        return output
    seed_items = valid[:period]
    seed = sum(float(value) for _, value in seed_items) / period
    seed_index = seed_items[-1][0]
    output[seed_index] = seed
    alpha = 2 / (period + 1)
    previous = seed
    for index in range(seed_index + 1, len(values)):
        value = values[index]
        if value is None:
            continue
        previous = alpha * value + (1 - alpha) * previous
        output[index] = previous
    return output
