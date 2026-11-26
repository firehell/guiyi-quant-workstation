"""Bound V2701 position replacement from observed quantities and price envelopes."""

import argparse
from datetime import date, datetime
from decimal import Decimal
import json
from math import ceil
from pathlib import Path

from lms405_exit_position_scope import EARLY, MIDDAY
from lms405_fg_exit_study import minute_context
from lms405_jm_divider_study import price_envelope
from lms405_m_permission_study import read_pair
from lms405_opening_clock_comparison import boundary_clocks
from lms405_portfolio_replay import ARCHIVE, input_sources
from lms405_protection_handoff_study import complete_window, price_window
from lms405_protection_lot_timing import displayed_tick_totals, earlier_lot_counts, tick_bounds, verified_json
from lms405_protection_timeframes import VARIANTS, geometry_events, read_window
from lms405_right_side_study import ONE, US, at
from lms405_sh_lock_lifecycle import completed, signals, digest as bar_digest
from lms405_visible_lock_handoff import stamp
from lms405_volatility_context import bars_sha
from lms_near405_replay import encoded, sha

CONTRACT = "V2701"
DATES = ("2026-10-26", "2026-10-27")
MINUTE_HASHES = {
    "2026-10-26": "0c582bd87acb6cda8d6625dee81ee3fe75383321aa6b3af14cba7253e6061501",
    "2026-10-27": "ec8489b5bbcf6b765a542cd66e2083f417c83a96551204c61da67339640c299d",
}
SOURCE_IDS = (
    "WRo2KQ43iX", "WRoql30FdC", "WRot6yvHyS", "A5358325549629506", "WRoCxx1ooa", "WRov1j6e10", "WRov2ceWt6",
    "WRovrUdwHi", "WRozNMci2y", "WRoAkcEppg", "U03", "WRoEvasxQR",
)
REPORT_ATTACHMENTS = {
    "WRov2ceWt6": ("2026-10-26/Rov2ceWt6-image3-screen.png",
                  "b70b8170ecf217a033f29caa5530cc35537fa9d02bc95b2c6963194f8040010a"),
    "WRovrUdwHi": ("2026-10-26/WRovrUdwHi-image4-screen.png",
                  "f5afb7da82441bcea7e0b2e96b67b038fb421e9cc51de753fe149e8fc81f0165"),
    "WRozNMci2y": ("2026-10-27/RozNMci2y-report-screen.png",
                  "b4350eaace0b6aeb5b92b3ab9ca37580f0467e1cd5d2040cb8f7c49116910692"),
    "WRoAkcEppg": ("2026-10-27/WRoAkcEppg-orders4-screen.png",
                  "5f6f64336c5a267e1654ad15fd951424c71161be1b0dcad609c417ee12dd72ff"),
    "U03": ("2026-10-27/U03-orders5-screen.png",
            "2ae117882abaf8cf38ec50e99ea662d85a3fcfdfc1a7ab4733a892ace3e2db25"),
}
POSITION_ATTACHMENTS = {
    "WRo2KQ43iX": ("2026-10-23/Ro2KQ43iX-position-screen.png",
                   "c98d0864d8120f9c4b7276e72d570da113e846952d504f67c877892a6a2a18a6"),
    "WRoql30FdC": ("2026-10-26/Roql30FdC-position-screen.png",
                  "a04a15ffe26365621b062208cfc8cd808c56e624ee2bdaae5444c0641eada52c"),
    "WRov1j6e10": ("2026-10-26/Rov1j6e10-position-screen.png",
                  "35106f37378f2410b5235773a58c3e9c44581fe3eb84a2af66bf2402405cc9cb"),
    "WRoAkcEppg": ("2026-10-27/WRoAkcEppg-pos2-screen.png",
                  "482969294bdf44a7d4f6bd8b7527708f3d94719b26648befcc00cf72d8b788f8"),
    "U03": ("2026-10-27/U03-pos3-screen.png",
            "7bacf30d3be4cce2de4268c91e01defc1310fc4897a5bc98329f31d29f838c23"),
    "WRoEvasxQR": ("2026-10-27/RoEvasxQR-position-screen.png",
                  "67854d29d606b65cd88efe9af1fa939e86e20b713325732929b8a5a5aa6f9b0a"),
}
TICK = Decimal("1")
SPEC = Path("output/htdy-60m-full-replay-20261025/evidence-002/provider/V2701-instrument.json")
SPEC_SHA = "35dca47e26d67546bbe51b8e67a1acca100aee077e6028a4174215581f8e1cde"
DISPLAY_STEP = Decimal("0.1")
QUANTITY = 40
OLD_AVERAGE = Decimal("5117.0")
LUNCH_AVERAGE = Decimal("5078.4")

PRIOR_PLAN, POST_EXIT, NEW_PLAN = "A5357264059367516", "WRot6yvHyS", "A5358325549629506"
EXIT_SCOPE = Path("output/lms405-exit-position-scope-20261125/final.json")
EXIT_SCOPE_SHA = "9ba998d56d83f28cc6b2f0b7a4a4365b315a1dcbe076ee01b9cdc035f12a6801"
DAY_PLAN = {
    "target_1": ("LONG", "5088", "5118"), "target_2": ("LONG", "5121", "5151"),
    "target_3": ("LONG", "5155", "5180"), "resistance": ("SHORT", "5091", "5115"),
    "protection": ("SHORT", "5045", "5054"), "m": ("SHORT", "4994", "5012"),
    "extreme_m": ("SHORT", "4956", "4983"),
}
TARGET_REFERENCES = ("first_range_reaches_direction", "first_range_contains_level", "first_close_strict_beyond")
NIGHT_EXIT = (Path("output/lms405-v-exit-20261125/verified.json"),
              "b6082e514c80036c0907d39bb2690f6c9416ba1e852beab2a7ad087f64939e58")
SALE = at("2026-10-26T21:09:59")
SALE_MINUTE = at("2026-10-26T21:09")
NIGHT_PHOTO = "WRov1j6e10"
NIGHT_CLOSE = "WRovrUdwHi"


def quote_pair_counts(known, before, after):
    """Compare possible minute placement with strict separation from both quote minutes."""
    return dict(possible=sum(left - ONE < known < right for left in before for right in after),
                strictly_between=sum(left < known < right - ONE for left in before for right in after))


def directional_band_clocks(minutes):
    return {role: {edge: boundary_clocks(minutes, Decimal(level), side)
                   for edge, level in zip(("lower", "upper"), (lo, hi), strict=True)}
            for role, (side, lo, hi) in DAY_PLAN.items()}


def compute_daytime_clocks(session, market):
    reference = verified_json(EXIT_SCOPE, EXIT_SCOPE_SHA)
    scope = reference["cases"]["pvc_daytime"]
    index = input_sources()
    sources = {key: index[key] | {"archive_sha256": sha((ARCHIVE.parent / index[key]["archive_path"]).read_bytes())}
               for key in (PRIOR_PLAN, POST_EXIT, NEW_PLAN, EARLY, MIDDAY)}
    before = tuple(map(datetime.fromisoformat, reference["pvc_row_price_anchors"][EARLY]))
    after = tuple(map(datetime.fromisoformat, reference["quote_anchors"][MIDDAY]))
    start = at("2026-10-26T09:00")
    series = read_window(session, market, CONTRACT, start.date())
    market_digests = {f"{p}m": dict(count=len(rows), sha256=bar_digest(rows)) for p, rows in series.items()}
    if (market_digests["1m"]["sha256"] != MINUTE_HASHES[start.date().isoformat()]
            or market_digests["1m"]["sha256"] != reference["market"]["V2701:2026-10-26"]["sha256"]):
        raise ValueError("V_DAY_EXIT_FROZEN_BAR_DRIFT")
    activation = stamp(sources[PRIOR_PLAN]) + ONE
    day_end = series[1][-1].end + 2 * US
    night_open = series[1][0].start
    if (scope["before_source"] != EARLY or scope["gap_source"] != MIDDAY or not before or not after
            or scope["observed_before"]["quantity"] != QUANTITY or scope["observed_gap"] is not None
            or not activation < night_open < start < min(before) <= max(before) < min(after) <= max(after) < day_end
            or not day_end < stamp(sources[POST_EXIT]) < stamp(sources[NEW_PLAN])):
        raise ValueError("V_DAY_EXIT_SOURCE_ORDER_DRIFT")
    minute_index = {bar.end: bar for bar in series[1]}
    old_mark = Decimal(reference["day_quote_alignment"][EARLY]["per_symbol"][CONTRACT]["mark"])
    if any(not minute_index[end].low <= old_mark <= minute_index[end].high for end in before):
        raise ValueError("V_DAY_EXIT_SINGLE_ROW_QUOTE_DRIFT")
    night = completed(series[1], night_open, start)
    day = completed(series[1], start, day_end)
    nearest_lunch = {str(quote): directional_band_clocks(completed(day, start, quote)) for quote in after}
    night_price_clocks = directional_band_clocks(night)
    day_price_clocks = directional_band_clocks(day)
    resistance_price = Decimal(DAY_PLAN["resistance"][2])
    cutoff = max(after) + 2 * US
    clock_results = {}
    for shape, confirm in VARIANTS:
        candidates = signals(series, shape, confirm, side="SHORT", start=start, cut=cutoff)
        for quote in (*after, *(event["available_at"] for event in candidates)):
            prefix = {key: [bar for bar in rows if bar.end + US < quote] for key, rows in series.items()}
            if signals(prefix, shape, confirm, side="SHORT", start=start, cut=quote) != [
                event for event in candidates if event["available_at"] < quote
            ]:
                raise ValueError("V_DAY_EXIT_PREFIX_DRIFT")
        rows = []
        for event in candidates:
            known = event["available_at"]
            check = quote_pair_counts(known, before, after)
            visible = completed(day, start, known + US)
            high = max(bar.high for bar in visible)
            shape_start = event["shape_end"] - shape * ONE
            target_upper = Decimal(DAY_PLAN["target_3"][2])
            day_through_shape = completed(day, start, shape_start)
            clocks_before_shape = {
                "prior_night": night_price_clocks["target_3"]["upper"],
                "day_session": boundary_clocks(day_through_shape, target_upper, "LONG") if day_through_shape else {},
            }
            target_timing = {role: {metric: clocks.get(metric) is not None for metric in TARGET_REFERENCES}
                             for role, clocks in clocks_before_shape.items()}
            rows.append(event | dict(shape_start=shape_start, high_known_through_confirmation=high,
                                     first_high_at=next(bar.end for bar in visible if bar.high == high),
                                     close_drawdown_points=high - event["close"], quote_pairs=check,
                                     resistance_touch_available_before_shape=any(
                                         bar.low <= resistance_price <= bar.high for bar in day_through_shape),
                                     last_target_available_before_shape=target_timing))
        clock_results[f"{shape}m_to_{confirm}m"] = rows
    resistance = day_price_clocks["resistance"]["upper"]
    return dict(version="lms405-pvc-daytime-exit-clocks-v1", contract=CONTRACT, sources=sources,
                market=market_digests, prior_plan_published_before_night=True, prior_plan_revision_verified=False,
                prior_plan_applicable_to_visible_4_0_5_leg=None, later_plan_used_for_prior_windows=False,
                scope_report_sha256=EXIT_SCOPE_SHA, opening_quotes=list(before), gap_quotes=list(after),
                quote_pair_count=len(before) * len(after), comparison_levels=DAY_PLAN, night_clocks=night_price_clocks,
                full_day_lookup_only=day_price_clocks, before_lunch_quotes=nearest_lunch,
                resistance_near_touch_pairs=quote_pair_counts(resistance["first_range_contains_level"] + US, before, after)
                if resistance["first_range_contains_level"] else None,
                opposing_geometry=clock_results, author_action=None, author_signal=None,
                action_amount=None, admitted_author_samples=0, executable=False, fills=None, pnl=None)


def displayed_sum(average, quantity):
    """Tick-sum interval for a positive average displayed to one decimal, half-up."""
    half = DISPLAY_STEP / 2
    return (ceil((average - half) * quantity / TICK),
            ceil((average + half) * quantity / TICK) - 1)


def replacement_bounds(old_prices, available_new_prices, *, quantity=QUANTITY,
                       old_average=OLD_AVERAGE, new_average=LUNCH_AVERAGE):
    """Return lot replacement counts compatible with both average intervals and envelopes."""
    old_min, old_max = (price / TICK for price in old_prices)
    add_min, add_max = (price / TICK for price in available_new_prices)
    old_sum_min, old_sum_max = displayed_sum(old_average, quantity)
    new_sum_min, new_sum_max = displayed_sum(new_average, quantity)
    counts = []
    for replaced in range(quantity + 1):
        keep = quantity - replaced
        keep_min = max(keep * old_min, old_sum_min - replaced * old_max)
        keep_max = min(keep * old_max, old_sum_max - replaced * old_min)
        if keep_min <= keep_max and max(keep_min + replaced * add_min, new_sum_min) <= min(
            keep_max + replaced * add_max, new_sum_max
        ):
            counts.append(replaced)
    return dict(old_prices=old_prices, available_new_prices=available_new_prices,
                old_total_tick_sum=(old_sum_min, old_sum_max), new_total_tick_sum=(new_sum_min, new_sum_max),
                possible_replaced_lots_within_envelopes=counts,
                minimum_replaced_lots=min(counts, default=None), maximum_replaced_lots=max(counts, default=None))


def placement_window(series, first_seen, cutoff):
    minutes = series[1]
    night_open = at("2026-10-26T21:00")
    old = price_envelope(complete_window(minutes, night_open, first_seen))
    additions = price_envelope(complete_window(minutes, night_open, cutoff))
    day_additions = price_envelope(complete_window(minutes, at("2026-10-27T09:00"), cutoff))
    if old is None or additions is None or day_additions is None:
        raise ValueError("V_EXIT_PRICE_PREFIX_MISSING")
    active = {}
    for period in (1, 5):
        signals = geometry_events(series, 5, period, start=at("2026-10-27T09:00"), as_of=cutoff, side="LONG")
        if not signals:
            active[f"5m_to_{period}m"] = None
            continue
        first = signals[0]
        later = price_envelope(complete_window(minutes, first["available_at"], cutoff))
        active[f"5m_to_{period}m"] = dict(
            first_signal=first,
            after_confirmation=replacement_bounds(old, later) if later is not None else None,
        )
    return dict(
        aggregate_price_envelopes=replacement_bounds(old, additions),
        only_add_during_day_session=replacement_bounds(old, day_additions),
        only_add_after_first_completed_long_geometry=active,
    )


def verified_images(attachments):
    images = {}
    for key, (path, digest) in attachments.items():
        file = ARCHIVE.parent / "02-持仓记录" / path
        if sha(file.read_bytes()) != digest:
            raise ValueError("V_EXIT_IMAGE_CHANGED")
        images[key] = dict(path=str(file), sha256=digest)
    return images


def compute(session, market):
    raw_spec = SPEC.read_bytes()
    spec = json.loads(raw_spec)
    if (sha(raw_spec) != SPEC_SHA or spec["order_book_id"] != CONTRACT
            or Decimal(str(spec["tick_size"])) != TICK):
        raise ValueError("V_EXIT_CONTRACT_TICK_UNVERIFIED")
    index = input_sources()
    sources = {key: index[key] | {"archive_sha256": sha((ARCHIVE.parent / index[key]["archive_path"]).read_bytes())}
               for key in SOURCE_IDS}
    images = verified_images(REPORT_ATTACHMENTS)
    positions = verified_images(POSITION_ATTACHMENTS)
    series, coverage = {}, {}
    for day in DATES:
        raw, series[day] = read_pair(session, market, CONTRACT, (date.fromisoformat(day),))
        coverage[day] = {f"{period}m": dict(count=len(rows), sha256=bars_sha(rows)) for period, rows in raw.items()}
        if coverage[day]["1m"]["sha256"] != MINUTE_HASHES[day]:
            raise ValueError("V_EXIT_FROZEN_MARKET_CHANGED")
    dated_report = at("2026-10-26T21:09:59")
    current = series[DATES[1]]
    first_seen = datetime.fromisoformat(sources["WRov1j6e10"]["published_at"]).replace(second=0, microsecond=0) + ONE
    quote_anchor = at("2026-10-27T11:30")
    if not any(b.end == quote_anchor and b.close == 5100 for b in current[1]):
        raise ValueError("V_EXIT_LUNCH_QUOTE_ANCHOR_CHANGED")
    return dict(
        version="lms405-v-exit-study-v1", contract=CONTRACT, sources=sources, report_images=images, market=coverage,
        position_images=positions, window_reference=dict(first_post_minute_complete=first_seen,
                                                         later_quote_anchor=quote_anchor),
        instrument=dict(source=str(SPEC), sha256=SPEC_SHA, tick_size=TICK),
        daytime_report=dict(source="WRot6yvHyS", system="4.0.5", side=None, quantity=None, time=None, price=None,
                            window=price_window(series[DATES[0]][1], "2026-10-26T09:00", "2026-10-26T15:01",
                                                "LONG", {"earlier_target": "5155 5180"})),
        software_row=dict(displayed_time="21:09:59", direction_closed="LONG", status="FILLED",
                          time_directly_readable_in=sorted(set(images) - {"U03"}),
                          contemporaneous_5_0_context=["WRov2ceWt6", "WRozNMci2y"],
                          repeated_in=sorted(images), account=None, version=None, date=None, quantity=None, price=None,
                          comparison=minute_context(current[1], "2026-10-26T21:09", ("4918", "5045", "5117"))),
        assumed_report_minute_after_daytime_statement=(
            dated_report > datetime.fromisoformat(sources["WRot6yvHyS"]["published_at"])
        ),
        observations=dict(
            prior=dict(source="WRo2KQ43iX", total=40, today=0, opening_average="5045.0"),
            before_daytime_report=dict(source="WRoql30FdC", total=40, today=0, opening_average="5045.0"),
            first_night=dict(source="WRov1j6e10", total=40, today=40, opening_average=str(OLD_AVERAGE)),
            lunch=dict(source="WRoAkcEppg", total=40, today=40, opening_average=str(LUNCH_AVERAGE)),
            day_close=dict(source="U03", total=40, today=40, opening_average=str(LUNCH_AVERAGE)),
            next_night=dict(source="WRoEvasxQR", total=40, today=0, opening_average=str(LUNCH_AVERAGE)),
        ),
        conditional_older_lots_remaining_at_first_night_if_same_account=0,
        conditional_lot_analysis=placement_window(current, first_seen + 2 * US, quote_anchor + 2 * US),
        same_account=None, actual_turnover=None, actual_exit_reason=None, full_exit_observed=None,
        admitted_author_samples=0, author_matches=None, executable=False, fills=None, pnl=None,
    )


def lot_partition(left, right, *, quantity, totals):
    limits = tick_bounds(left, TICK), tick_bounds(right, TICK)
    counts = earlier_lot_counts(*limits, quantity, totals)
    return dict(before_after_ticks=limits, allowed_earlier_lot_counts=counts,
                minimum_earlier_lots=min(counts, default=None), all_new_after_possible=0 in counts)


def sale_price_cohorts(minutes, quote, *, quantity, totals):
    """Separate full minutes on either side of the report and leave its minute ambiguous."""
    cutoff = quote - ONE
    eligible = [bar for bar in minutes if bar.end + US < cutoff]
    prior = [bar for bar in eligible if bar.end <= SALE_MINUTE]
    overlap = [bar for bar in eligible if bar.start == SALE_MINUTE]
    later = [bar for bar in eligible if SALE < bar.start]

    return dict(
        quote_starts_at=cutoff,
        relationship=("SAME_MINUTE_ORDER_UNRESOLVED" if cutoff <= SALE < quote else "REPORT_BEFORE_QUOTE_MINUTE"),
        exclude_report_minute=lot_partition(prior, later, quantity=quantity, totals=totals),
        allow_report_minute_as_prior=lot_partition(prior + overlap, later, quantity=quantity, totals=totals),
        allow_report_minute_as_later=lot_partition(prior, overlap + later, quantity=quantity, totals=totals),
    )


def long_shapes_after_sale(series, shape, confirm, start, cutoff):
    return [event for event in signals(series, shape, confirm, side="LONG", start=start, cut=cutoff)
            if SALE < event["shape_end"] - shape * ONE]


def compute_night_sale(session, market):
    reference = verified_json(*NIGHT_EXIT)
    scope = verified_json(EXIT_SCOPE, EXIT_SCOPE_SHA)
    report = reference["software_row"]
    if (report["displayed_time"] != "21:09:59" or report["direction_closed"] != "LONG"
            or report["status"] != "FILLED" or set(report["repeated_in"]) != set(REPORT_ATTACHMENTS)
            or any(report[key] is not None for key in ("account", "version", "date", "quantity", "price"))):
        raise ValueError("V_NIGHT_REPORT_SCOPE_CHANGED")
    images = verified_images(REPORT_ATTACHMENTS)
    holdings = verified_images({key: POSITION_ATTACHMENTS[key] for key in (EARLY, NIGHT_PHOTO, "WRoAkcEppg")})
    index = input_sources()
    sources = {key: index[key] | {"archive_sha256": sha((ARCHIVE.parent / index[key]["archive_path"]).read_bytes())}
               for key in (*REPORT_ATTACHMENTS, EARLY, MIDDAY, POST_EXIT, NEW_PLAN, NIGHT_PHOTO)}
    first_public = min(datetime.fromisoformat(sources[key]["published_at"]) for key in images)
    old = scope["observed_rows"][EARLY][f"{CONTRACT}/long"]
    current = scope["observed_rows"][NIGHT_PHOTO][f"{CONTRACT}/long"]
    later = scope["observed_rows"]["WRoAkcEppg"][f"{CONTRACT}/long"]
    empty = (MIDDAY, NIGHT_CLOSE)
    if (any(row["quantity"] != QUANTITY for row in (old, current, later)) or old["today_quantity"] != 0
            or Decimal(old["opening_average"]) != Decimal(5045)
            or current["today_quantity"] != QUANTITY or Decimal(current["opening_average"]) != OLD_AVERAGE
            or later["today_quantity"] != QUANTITY or Decimal(later["opening_average"]) != LUNCH_AVERAGE
            or any(any(key.startswith(CONTRACT + "/") for key in scope["observed_rows"][src]) for src in empty)
            or f"{CONTRACT}/short" in scope["observed_rows"][NIGHT_PHOTO]
            or not stamp(sources[POST_EXIT]) < stamp(sources[NEW_PLAN]) < SALE < stamp(sources[NIGHT_PHOTO]) < first_public):
        raise ValueError("V_NIGHT_POSITION_SCOPE_CHANGED")

    day = DATES[1]
    series = read_window(session, market, CONTRACT, date.fromisoformat(day))
    if bar_digest(series[1]) != MINUTE_HASHES[day]:
        raise ValueError("V_NIGHT_MARKET_CHANGED")
    start, first_seen = at("2026-10-26T21:00"), stamp(sources[NIGHT_PHOTO])
    minutes = completed(series[1], start, first_seen)
    anchors = tuple(map(datetime.fromisoformat, scope["pvc_row_price_anchors"][NIGHT_PHOTO]))
    if anchors != tuple(b.end for b in minutes if b.low <= Decimal(5111) <= b.high):
        raise ValueError("V_NIGHT_QUOTE_SCOPE_CHANGED")
    totals = displayed_tick_totals(OLD_AVERAGE, QUANTITY, TICK)
    windows = {display_quote.isoformat(): sale_price_cohorts(minutes, display_quote, quantity=QUANTITY, totals=totals)
               for display_quote in anchors}
    for quote in anchors:
        cut = quote - ONE
        prefix = [b for b in minutes if b.end + US < cut]
        if sale_price_cohorts(prefix, quote, quantity=QUANTITY, totals=totals) != windows[quote.isoformat()]:
            raise ValueError("V_NIGHT_QUOTE_PREFIX_CHANGED")
    before_sale = {}
    after_sale = {}
    price_after_confirm = {}
    for shape, confirm in VARIANTS:
        name = f"{shape}m_to_{confirm}m"
        available = {p: [b for b in bars if b.end + US < SALE] for p, bars in series.items()}
        opposed = signals(series, shape, confirm, side="SHORT", start=start, cut=SALE)
        if signals(available, shape, confirm, side="SHORT", start=start, cut=SALE) != opposed:
            raise ValueError("V_NIGHT_REPORTED_EVENT_PREFIX_CHANGED")
        before_sale[name] = opposed
        after_sale[name] = long_shapes_after_sale(series, shape, confirm, start, first_seen)
        for quote in anchors:
            cut = quote - ONE
            prefix = {p: [b for b in bars if b.end + US < cut] for p, bars in series.items()}
            if (long_shapes_after_sale(prefix, shape, confirm, start, cut)
                    != [row for row in after_sale[name] if row["available_at"] < cut]):
                raise ValueError("V_NIGHT_REOPEN_PREFIX_CHANGED")
        price_after_confirm[name] = []
        for event in after_sale[name]:
            known = event["available_at"]
            quote_checks = {}
            for quote in anchors:
                eligible = [b for b in minutes if b.end + US < quote - ONE]
                early = [b for b in eligible if b.start <= known]
                late = [b for b in eligible if known < b.start]
                quote_checks[quote.isoformat()] = lot_partition(early, late, quantity=QUANTITY, totals=totals)
            price_after_confirm[name].append(dict(event=event, quote_checks=quote_checks))
    sale_window = minute_context(series[1], "2026-10-26T21:09", ("4918", "5045", "5117"))
    current_plan_geometry = dict(
        checked_archive_revision=NEW_PLAN, historic_revision_verified=False,
        full_night_prefix_bounds=price_envelope(minutes),
        left_long_band_touched=any(b.low <= 5074 and 5045 <= b.high for b in minutes),
        right_long_first_close_above_5195=next((b.end for b in minutes if b.close > 5195), None),
        short_reference_band_touched=any(b.low <= 5074 and 5055 <= b.high for b in minutes),
    )
    return dict(
        version="lms405-pvc-night-sale-role-v1", contract=CONTRACT, sources=sources,
        report=report | dict(assumed_report_at=SALE, first_public_post=first_public,
                             assumed_public_availability_boundary=first_public + ONE, report_order_id="102694086"),
        report_minute_price=sale_window, report_images=images, holdings_images=holdings,
        observed_before_day_gap=old, observed_night=current, observed_lunch=later, observed_night_short=None,
        no_displayed_pvc_in_sources=empty, strict_quote_windows=windows, opening_tick_sums=list(totals),
        if_same_complete_account=dict(
            observation_requirements=["SAME_ACCOUNT", "COMPLETE_CONTRACT_DISPLAY", "SYNCHRONIZED_AND_ORDERED_CAPTURES"],
            old_morning_long_left_before_night_report_if_dates_hold=True,
            covering_entire_first_night_long_after_sale_requires_all_new_after_price_support=True,
            if_sale_removed_protection_long_and_original_short_unmodified="SHORT_SURVIVES_SELL_CLOSE",
            if_short_survived_sale_but_complete_night_only_long="ADDITIONAL_SHORT_EXIT_REQUIRED",
            if_no_longs_remained_after_sale_but_night_long_visible="NEW_LONG_ENTRY_REQUIRED",
            independent_accounts_or_transient_positions_remain_possible=True,
        ),
        opposing_geometry_before_assumed_sale=before_sale, fresh_long_geometry_after_assumed_sale=after_sale,
        long_price_when_waiting_for_confirmation=price_after_confirm, current_plan_geometry=current_plan_geometry,
        market={f"{p}m": dict(count=len(rows), sha256=bar_digest(rows)) for p, rows in series.items()},
        account_scope_verified=None, author_decision=None, admitted_author_samples=0, author_matches=None,
        executable=False, fills=None, pnl=None,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--daytime-clocks", action="store_true")
    group.add_argument("--night-sale", action="store_true")
    args = parser.parse_args()
    if not args.env_file.is_file() or args.output.exists():
        parser.error("ENV_FILE_MISSING_OR_OUTPUT_EXISTS")
    from dotenv import load_dotenv
    load_dotenv(args.env_file, override=False)
    from app.db.readonly import readonly_transaction
    from app.db.session import SessionLocal
    from app.market_data.composition import build_market_data_service
    from app.market_data.market_data_service import MarketDataError
    from sqlalchemy.exc import OperationalError

    try:
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=60):
            run = compute_night_sale if args.night_sale else compute_daytime_clocks if args.daytime_clocks else compute
            result = run(session, build_market_data_service(session))
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(result))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (OSError, KeyError, ValueError):
        parser.exit(2, "V_EXIT_SOURCE_OR_MARKET_UNVERIFIED\n")


if __name__ == "__main__":
    main()
