from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from hashlib import sha256

import pytest

from guiyi_quant.newow.escape_d123 import (
    EscapeState,
    calculate_escape_series,
    step_escape_d123,
)
from guiyi_quant.newow.models import NewowDailyBar, NewowMarkerType
from guiyi_quant.newow.profile import NEWOW_TREND_D1_PAGE_V2, NEWOW_TREND_D1_V1


# Browser-observed 399006.SZ prefix (2020-03-02 through 2020-07-15).  The
# source page emits all three escape labels inside these 92 completed D1 bars.
_GOLDEN_HLC = (
    (2153.217, 2082.969, 2135.415),
    (2238.735, 2151.523, 2173.346),
    (2180.425, 2122.454, 2169.443),
    (2216.825, 2176.49, 2209.588),
    (2220.364, 2175.014, 2192.936),
    (2163.728, 2091.855, 2093.063),
    (2151.45, 2052.055, 2148.81),
    (2162.604, 2100.507, 2101.463),
    (2076.009, 2025.906, 2045.926),
    (2055.331, 1937.946, 2030.58),
    (2036.734, 1902.398, 1910.767),
    (1955.624, 1847.51, 1917.702),
    (1980.789, 1887.042, 1887.042),
    (1908.685, 1838.313, 1894.943),
    (1928.879, 1878.849, 1915.046),
    (1884.449, 1819.77, 1827.052),
    (1880.865, 1817.554, 1876.91),
    (1940.075, 1915.528, 1937.855),
    (1948.631, 1914.346, 1927.275),
    (1957.699, 1902.788, 1903.881),
    (1877.501, 1833.009, 1860.484),
    (1886.266, 1862.856, 1871.917),
    (1900.183, 1862.272, 1864.8),
    (1916.951, 1857.323, 1916.951),
    (1928.339, 1898.794, 1906.675),
    (1972.868, 1942.798, 1969.782),
    (1974.723, 1956.902, 1964.757),
    (2001.36, 1975.038, 1997.136),
    (1994.354, 1943.694, 1949.885),
    (1937.327, 1913.955, 1923.081),
    (1985.426, 1934.482, 1985.426),
    (2002.76, 1975.796, 1977.515),
    (2012.463, 1968.253, 2008.388),
    (2048.278, 2015.835, 2020.77),
    (2043.556, 2022.587, 2043.437),
    (2035.77, 1996.962, 2023.942),
    (2043.558, 2002.962, 2043.171),
    (2057.851, 2027.334, 2029.524),
    (2038.236, 1997.121, 2003.748),
    (2035.889, 1995.505, 2018.666),
    (2046.932, 1967.399, 2030.724),
    (2053.378, 2020.983, 2030.477),
    (2077.807, 2043.816, 2069.432),
    (2111.656, 2051.292, 2110.267),
    (2116.227, 2095.742, 2106.842),
    (2137.786, 2112.887, 2125.243),
    (2139.665, 2088.658, 2102.825),
    (2125.323, 2092.578, 2124.15),
    (2145.024, 2116.551, 2140.681),
    (2137.14, 2116.352, 2117.647),
    (2138.968, 2109.546, 2124.311),
    (2137.149, 2096.254, 2114.858),
    (2144.983, 2128.892, 2144.121),
    (2153.244, 2112.086, 2118.119),
    (2138.72, 2092.544, 2099.432),
    (2099.416, 2036.678, 2046.596),
    (2055.186, 2036.004, 2052.302),
    (2113.288, 2067.144, 2112.973),
    (2114.859, 2064.409, 2071.473),
    (2075.868, 2021.98, 2054.964),
    (2090.296, 2043.953, 2086.666),
    (2163.35, 2105.242, 2158.223),
    (2164.989, 2132.399, 2145.286),
    (2165.454, 2139.993, 2143.117),
    (2157.278, 2137.35, 2151.385),
    (2166.375, 2143.28, 2166.375),
    (2186.974, 2147.865, 2153.564),
    (2186.47, 2147.173, 2181.589),
    (2205.268, 2180.353, 2201.988),
    (2236.085, 2181.588, 2195.638),
    (2220.972, 2147.416, 2206.764),
    (2256.649, 2217.286, 2219.55),
    (2261.179, 2239.342, 2260.458),
    (2274.488, 2248.72, 2263.961),
    (2270.112, 2243.631, 2266.032),
    (2328.583, 2271.589, 2319.449),
    (2358.913, 2328.4, 2342.88),
    (2382.329, 2335.219, 2382.047),
    (2397.363, 2367.685, 2382.473),
    (2387.163, 2360.161, 2372.536),
    (2441.9, 2387.593, 2438.197),
    (2450.842, 2381.593, 2419.629),
    (2435.117, 2397.685, 2424.393),
    (2467.497, 2407.998, 2462.563),
    (2535.714, 2460.131, 2529.487),
    (2632.805, 2538.822, 2591.263),
    (2653.071, 2577.485, 2651.969),
    (2771.215, 2646.466, 2757.653),
    (2799.0, 2734.965, 2778.457),
    (2896.309, 2789.976, 2889.427),
    (2892.888, 2789.035, 2858.672),
    (2894.424, 2787.827, 2813.061),
)


def _bar(
    index: int, high: float, low: float, close: float, *, contract: str = "IF2009"
) -> NewowDailyBar:
    day = date(2020, 3, 2) + timedelta(days=index)
    return NewowDailyBar(
        product="if",
        physical_contract=contract,
        segment_id=f"if:{contract}:2020-03-02",
        trading_day=day,
        bar_end=datetime.combine(day, datetime.min.time(), tzinfo=UTC),
        open=Decimal(str(close)),
        high=Decimal(str(high)),
        low=Decimal(str(low)),
        close=Decimal(str(close)),
        volume=1,
        open_interest=None,
        source_identity="browser:399006.SZ:2026-09-03",
        observation_eligible=True,
        completed=True,
    )


def _golden_bars() -> tuple[NewowDailyBar, ...]:
    return tuple(_bar(index, *values) for index, values in enumerate(_GOLDEN_HLC))


def _marker_facts(results):
    return tuple(
        (index, marker.marker_type)
        for index, result in enumerate(results)
        for marker in result.markers
    )


def test_page_v2_profile_changes_escape_identity_without_mutating_v1() -> None:
    assert NEWOW_TREND_D1_V1.escape_formula == "newow_escape_d123_v1"
    assert NEWOW_TREND_D1_PAGE_V2.escape_formula == "newow_escape_d123_page_v2"


def test_browser_golden_reproduces_d1_d2_d3_and_page_numeric_points() -> None:
    results = calculate_escape_series(_golden_bars(), profile=NEWOW_TREND_D1_PAGE_V2)

    assert _marker_facts(results) == (
        (28, NewowMarkerType.ESCAPE_D2),
        (28, NewowMarkerType.ESCAPE_D3),
        (46, NewowMarkerType.ESCAPE_D2),
        (81, NewowMarkerType.ESCAPE_D2),
        (91, NewowMarkerType.ESCAPE_D1),
    )
    expected = {
        28: (1986.256206896552, -0.006, 86.6275),
        46: (2005.423574468086, 0.0555, 88.3157),
        81: (2085.7846585365846, 0.1564, 91.2202),
        91: (2149.90529347826, 0.326, 91.5517),
    }
    for index, (z_value, var3, var4) in expected.items():
        result = results[index]
        assert result.ma120 == pytest.approx(z_value)
        assert result.ma120_slope10 == pytest.approx(var3)
        assert result.var4 == pytest.approx(var4)
        assert all(
            marker.price == _golden_bars()[index].high for marker in result.markers
        )


def test_page_v2_is_partial_window_causal_serializable_and_rollover_safe() -> None:
    bars = _golden_bars()
    full = calculate_escape_series(bars, profile=NEWOW_TREND_D1_PAGE_V2)
    prefix = calculate_escape_series(bars[:47], profile=NEWOW_TREND_D1_PAGE_V2)
    assert prefix == full[:47]
    assert full[0].ma120 == pytest.approx(float(bars[0].close))
    assert full[0].ma120_slope10 is not None

    restored = EscapeState(**asdict(prefix[-1].state))
    resumed = []
    for bar in bars[47:]:
        result = step_escape_d123(restored, bar, profile=NEWOW_TREND_D1_PAGE_V2)
        resumed.append(result)
        restored = result.state
    assert tuple(resumed) == full[47:]

    rollover = _bar(92, 3000.0, 2900.0, 2950.0, contract="IF2012")
    reset = step_escape_d123(full[-1].state, rollover, profile=NEWOW_TREND_D1_PAGE_V2)
    assert reset.markers == ()
    assert reset.state.closes == (2950.0,)
    assert reset.state.previous_var4 == 50.0


def test_page_v2_marker_identity_is_stable_and_separate_from_v1_namespace() -> None:
    bars = _golden_bars()
    page_markers = tuple(
        marker
        for result in calculate_escape_series(
            bars, profile=NEWOW_TREND_D1_PAGE_V2
        )
        for marker in result.markers
    )

    assert page_markers
    assert len({marker.marker_id for marker in page_markers}) == len(page_markers)
    first = page_markers[0]
    first_bar = next(bar for bar in bars if bar.bar_end == first.bar_end)
    expected = "|".join(
        (
            "newow_trend_page_v2",
            "newow_escape_d123_page_v2",
            first_bar.physical_contract,
            first.marker_type.value,
            first_bar.bar_end.isoformat(),
        )
    )
    assert first.marker_id == sha256(expected.encode()).hexdigest()
    assert page_markers == tuple(
        marker
        for result in calculate_escape_series(
            bars, profile=NEWOW_TREND_D1_PAGE_V2
        )
        for marker in result.markers
    )
