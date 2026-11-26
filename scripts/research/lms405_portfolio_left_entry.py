"""Source-scoped PVC left-entry geometry for the independent portfolio study."""

from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal

from guiyi_quant.lms_confirmed_replay import fingerprint
from lms405_portfolio_leg_audit import compare_leg
from lms405_public_plan_roles import load_source
from lms405_right_side_study import FIVE, ONE, US, at
from lms405_sh_lock_lifecycle import signals

MODES = ("shape-overlap", "confirmation-inside")
CONTRACT = "V2701"
SOURCE = "A5358325549629506"
PVC_CARRY_PHOTOS = frozenset(("WRoAkcEppg", "U03", "WRoEvasxQR"))


@dataclass(frozen=True)
class LeftScope:
    contract: str
    source: dict
    available: datetime
    start: datetime
    through: datetime
    low: Decimal
    high: Decimal

    def active(self, contract, now):
        return self.contract == contract and self.start <= now < self.through

    @property
    def identity(self):
        return fingerprint(asdict(self))


def scope_for(index, contract):
    if contract != CONTRACT:
        return None
    source = load_source(index, SOURCE)
    available = datetime.fromisoformat(source["published_at"]) + ONE
    return LeftScope(contract, source, available, max(available + US, at("2026-10-26T21:00")),
                     at("2026-10-27T15:01"), Decimal(5045), Decimal(5074))


def left_signals(series, scope, cutoff):
    """Typed zone and completed bars determine market geometry, never authorization."""
    if scope is None:
        return []
    cut = min(scope.through, cutoff)
    if cut <= scope.start:
        return []
    by_end = {period: {bar.end: bar for bar in rows} for period, rows in series.items()}
    events = []
    for shape_period, confirmation_period in ((1, 1), (5, 1), (5, 5)):
        for frame in signals(series, shape_period, confirmation_period, side="LONG", start=scope.start, cut=cut):
            shape = by_end[shape_period][frame["shape_end"]]
            confirmation = by_end[confirmation_period][frame["confirmed_at"]]
            if (shape.contract != scope.contract or confirmation.contract != scope.contract
                    or not scope.available < shape.start
                    or not (shape.end <= confirmation.start < confirmation.end)
                    or frame["close"] != confirmation.close):
                raise ValueError("LEFT_ENTRY_SIGNAL_SCOPE_MISMATCH")
            shape_overlap = shape.low <= scope.high and scope.low <= shape.high
            if not shape_overlap and not scope.low <= confirmation.close <= scope.high:
                continue
            events.append(dict(
                scope=scope.identity, mode=f"{shape_period}m_to_{confirmation_period}m",
                shape_end=shape.end, shape_start=shape.start,
                shape_low=shape.low, shape_high=shape.high,
                signal_at=confirmation.end, signal_known_at=frame["available_at"], close=confirmation.close,
                confirmation_low=confirmation.low, confirmation_high=confirmation.high,
                shape_overlap=shape_overlap, confirmation_inside=scope.low <= confirmation.close <= scope.high,
                confirmation_overlaps=confirmation.low <= scope.high and scope.low <= confirmation.high,
                close_distance=max(scope.low - confirmation.close, confirmation.close - scope.high, Decimal(0)),
            ))
    return sorted(events, key=lambda row: (row["signal_known_at"], row["mode"]))


def assess_left_proposal(scope, events, mode, proposal, as_of):
    """Evaluate this exact legacy 5m signal; faster observations cannot approve it."""
    if mode not in MODES or not scope.active(proposal["contract"], as_of) or proposal["action"] != "ENTER_LONG":
        raise ValueError("LEFT_ENTRY_PROPOSAL_SCOPE_MISMATCH")
    generated = datetime.fromisoformat(proposal["generated_at"])
    shape_end = datetime.fromisoformat(proposal["signal_bar_end"])
    valid = [row for row in events if row["mode"] == "5m_to_5m" and row["shape_end"] == shape_end
             and scope.identity == row["scope"]
             and row["signal_known_at"] == generated and scope.available < row["shape_start"]
             and row["shape_start"] + FIVE == shape_end and shape_end + FIVE == row["signal_at"]
             and row["signal_at"] + US == generated
             and scope.start <= row["shape_start"] and generated < as_of]
    if len(valid) > 1:
        raise ValueError("LEFT_ENTRY_SIGNAL_AMBIGUOUS")
    event = valid[0] if valid else None
    gate = "shape_overlap" if mode == "shape-overlap" else "confirmation_inside"
    permit = event is not None and event[gate] is True
    return dict(mode=mode, contract=scope.contract, evaluated_at=as_of, source=scope.source["source_url"],
                publication_minute_end_proxy=scope.available, zone=[scope.low, scope.high], event=event,
                status="TEST_FIXTURE_GEOMETRY_ACCEPTED" if permit else "RESEARCH_ZONE_CONDITION_NOT_MET",
                author_permission_supplied=False, original_signal_verified=False, can_project_fixture=permit)


def assumed_carry_comparison(events, quotes, minutes, variant):
    """Retrospective price envelope if a candidate formed the whole visible leg and it survived."""
    photos = {row["source"]: row for row in quotes if row["source"] in PVC_CARRY_PHOTOS and row["side"] == "long"}
    if set(photos) != PVC_CARRY_PHOTOS or any(row["status"] != "CHECKED" for row in photos.values()):
        raise ValueError("LEFT_ENTRY_CARRY_PHOTOS_MISMATCH")
    result = []
    for event in events:
        known = event["signal_known_at"] + US
        cells = {}
        for source, row in photos.items():
            visible = row["visible"]
            if visible["quantity"] != 40 or Decimal(visible["opening_average"]) != Decimal("5078.4"):
                raise ValueError("LEFT_ENTRY_CARRY_PHOTO_QUANTITY_CHANGED")
            day = row["assumed_trading_day"]
            cells[source] = {}
            for label in row["by_variant"][variant]:
                cutoff = datetime.fromisoformat(label) - ONE
                if known < cutoff:
                    check = compare_leg(visible, Decimal("5078.4"), day, cutoff, (known, "ENTER_LONG", None),
                                        minutes, Decimal(40), Decimal(1))
                    cells[source][label] = bool(check.get("price_compatible_strict")) and check[
                        "status"
                    ] == "PRICE_COMPATIBLE"
                else:
                    cells[source][label] = False
        result.append(dict(mode=event["mode"], signal_at=event["signal_at"], assumed_price_window_after=known,
                           strict_prices_exclude_quote_minute=cells,
                           author_continuity_verified=False, exits_simulated=False))
    return result
