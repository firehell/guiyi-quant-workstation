"""Recompute a fixed Canonical chart and its four panes in one read-only snapshot."""
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from guiyi_quant.newow.product_contracts import ProductFrequency, ProductStrategy

from app.api.newow_presentation import _product_response
from app.market_data.composition import build_database_coverage_source, build_market_data_service
from app.market_data.operational_universe import load_active_products
from app.reference_trading.presentation import newow_state_point

from .composition import NewowComposition
from .product_release import FORMAL_HISTORICAL_REFERENCE_PRICE_POLICY, candidate_input_quality_policy
from .product_service import AuxiliaryComponent, ProductSection, ProductServiceQuery

_SHANGHAI = ZoneInfo("Asia/Shanghai")
_COMPONENTS = (
    AuxiliaryComponent.ZHAOYAO_MIRROR, AuxiliaryComponent.UP_DOWN_ENERGY,
    AuxiliaryComponent.MAIN_FORCE_CONTROL, AuxiliaryComponent.TREND_REVERSAL,
)


def selected_close(reader, product, frequency, requested_day, now, cancelled):
    anchor = now
    if requested_day is not None:
        if requested_day > now.astimezone(_SHANGHAI).date():
            raise ValueError("NEWOW_INVALID_AS_OF")
        anchor = min(now, datetime.combine(requested_day + timedelta(days=1), time.min, _SHANGHAI))
    lookup = (reader.weekly_snapshot_candidates if frequency is ProductFrequency.WEEKLY
              else reader.historical_snapshot_candidates)
    candidates = lookup(product, as_of=anchor, limit=1, cancelled=cancelled)
    if not candidates or requested_day is not None and candidates[0][0] != requested_day:
        raise ValueError("NEWOW_HISTORICAL_SNAPSHOT_UNAVAILABLE")
    return candidates[0]


def historical_chart(session, product: str, strategy: ProductStrategy, frequency: ProductFrequency,
                     trading_day: date | None, *, now, cancelled):
    composition = NewowComposition(
        build_market_data_service(session, check_cancelled=cancelled),
        build_database_coverage_source(session), load_active_products(),
        candidate_input_quality_policy(product, frequency, candidate_weekly=False), now=lambda: now,
        reference_price_policy=FORMAL_HISTORICAL_REFERENCE_PRICE_POLICY,
    )
    day, cutoff = selected_close(composition.reader(cancelled=cancelled), product, frequency,
                                 trading_day, now, cancelled)
    service = composition.service(cancelled=cancelled, reuse_read_inputs=True)
    base = dict(product=product, strategy=strategy, frequency=frequency, as_of=cutoff)
    chart = service.query(ProductServiceQuery(**base))
    value = chart.chart.value
    proof = chart.meta.shared_input_proof
    if (not value or not value.bars or value.bars[-1].bar.trading_day != day
            or chart.meta.as_of != cutoff or not chart.meta.snapshot_token or not proof):
        raise ValueError("NEWOW_HISTORICAL_SNAPSHOT_UNAVAILABLE")
    chart_dto = _product_response(chart).model_dump(mode="json")
    wire = chart_dto["chart"]["value"]
    # The page navigates with the Canonical bars reader, never a process-local continuation.
    wire["next_before"] = wire["next_older_window"] = None
    actions = {row["signal_id"]: row for row in wire["actions"]}
    hints = {row["hint_id"]: row for row in wire["hints"]}
    frames = []
    for frame in value.replay.frames:
        point = newow_state_point(chart.meta.identity, frame)
        frames.append({
            **point["value"], "trading_day": point["trading_day"],
            "formula_versions": point["formula_versions"],
            "actions": [actions[a.signal_id] for a in frame.actions],
            "hints": [hints[h.hint_id] for h in frame.hints],
        })
    auxiliaries = {}
    for component in _COMPONENTS:
        result = service.query(ProductServiceQuery(
            **base, section=ProductSection.AUXILIARY, component=component,
            snapshot_token=chart.meta.snapshot_token,
        ))
        actual = result.meta.shared_input_proof
        if (not actual or actual.market_input_sha256 != proof.market_input_sha256
                or result.meta.as_of != cutoff or result.meta.input_content_sha256 != chart.meta.input_content_sha256):
            raise ValueError("NEWOW_SNAPSHOT_GENERATION_CONFLICT")
        auxiliaries[component.value] = _product_response(result).model_dump(mode="json")
    return {"source": "canonical_recompute", "trading_day": day.isoformat(), "cutoff": chart_dto["meta"]["as_of"],
            "revision": proof.market_input_sha256, "chart": chart_dto, "auxiliaries": auxiliaries, "frames": frames}
