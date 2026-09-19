from __future__ import annotations

from datetime import UTC

from guiyi_quant.newow.chart_price_reference import project_chart_price_reference
from guiyi_quant.newow.trend_channel_display import build_trend_channel_layer

from tests.newow.test_trend_channel_display import _bars


def test_projection_uses_exact_anchor_not_last_ready_channel_point() -> None:
    bars = _bars()[:3]
    layer = build_trend_channel_layer(bars[:2], bars[:2])

    projected = project_chart_price_reference(
        layer,
        bars[2],
        as_of=bars[2].bar.bar_end.astimezone(UTC),
        input_sha256="a" * 64,
    )

    assert projected.target.raw is None
    assert projected.target.status.reason_code == "NEWOW_CHART_PRICE_ANCHOR_MISSING"
