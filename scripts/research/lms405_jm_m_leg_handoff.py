"""Constrain JM2701's visible protection, M long and next trading-day short."""

import argparse
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from lms405_fg_sa_case import DAYS, identity
from lms405_portfolio_replay import ARCHIVE, input_sources
from lms405_protection_lot_timing import EXPOSURE, displayed_tick_totals, earlier_lot_counts, tick_bounds, verified_json
from lms405_protection_timeframes import read_window
from lms405_replay import display, read_session_series
from lms405_reversal_stage_bounds import PHOTO, PHOTO_SHA, photo_row
from lms405_right_side_study import ONE, US
from lms405_rubber_m_replacements import compare_gate, first_gates, partition
from lms405_sh_lock_lifecycle import completed, digest
from lms405_sizing_audit import EXPOSURE_SHA256, SPECS, load_specs
from lms405_visible_lock_handoff import stamp
from lms405_volatility_context import bars_sha
from lms_near405_replay import encoded, sha

CONTRACT = "JM2701"
OLD_PLAN, NEW_PLAN = "A5356884629782554", "A5357264059367516"
FIRST, LATER, CLOSE, NIGHT = "WRnTlEfj1t", "WRnZKEysLc", "WRo00BFM1E", "WRo2KQ43iX"
RECAP, REPLY = "WRo0OCbeQG", "WRo11kyxDu"
LATER_IMAGE = "d78135497fbc2396a59fdfdf055667ba5626428795ae98a26e6228d732de032c"
SPECS_SHA = "fc430ad455e81d41cdd479f470e26a7a543cac0f427729de150185dfb3e40652"
LONG_BANDS = {"protection": (Decimal("1382.5"), Decimal("1397.5")),
              "m": (Decimal("1410.5"), Decimal(1420)), "extreme_m": (Decimal("1420.5"), Decimal("1427.5"))}
SHORT_BANDS = {"divider": (Decimal(1392), Decimal("1415.5")), "short_target": (Decimal(1375), Decimal(1391))}
BOUNDARIES = ("EVENT_MINUTE_ALLOWED_AFTER", "ONLY_COMPLETE_MINUTES_AFTER")


def quote_anchors(report, source, minutes, cut, *, joint_close=False):
    row = report["photos"][source]
    jm = row["per_symbol"]["jm"]
    frozen = row["joint_equal_close"] if joint_close else jm["contains"]
    price = Decimal(jm["mark"])
    anchors = [datetime.fromisoformat(x) for x in frozen]
    if not anchors:
        raise ValueError("JM_M_PHOTO_ANCHOR_MISSING")
    for at in anchors:
        bar = minutes[at]
        if not (at + US < cut and bar.low <= price <= bar.high and (not joint_close or bar.close == price)):
            raise ValueError("JM_M_PHOTO_ANCHOR_MISMATCH")
    return anchors


def formation(minutes, captures, gate_end, *, boundary, tick, lots, totals):
    result = {}
    for capture in captures:
        key = display(capture)
        if gate_end is None or gate_end > capture:
            result[key] = dict(status="GATE_NOT_OBSERVED_BY_QUOTE")
            continue
        allowed = [bar for bar in minutes if bar.end <= capture]
        later = [bar for bar in allowed if partition(bar, gate_end, boundary)]
        earlier = [bar for bar in allowed if not partition(bar, gate_end, boundary)]
        counts = earlier_lot_counts(tick_bounds(earlier, tick), tick_bounds(later, tick), lots, totals)
        if not counts:
            raise ValueError("JM_M_HOLDING_INCOMPATIBLE_WITH_FULL_PRICE_ENVELOPE")
        result[key] = dict(status="QUOTE_MINUTE_EQUALS_GATE" if gate_end == capture else "GATE_BEFORE_QUOTE_MINUTE",
                           min_outside_later_bucket=min(counts), whole_leg_can_form_after=0 in counts)
    return result


def study(session, market):
    photos = verified_json(PHOTO, PHOTO_SHA)
    exposure = verified_json(EXPOSURE, EXPOSURE_SHA256)
    index = input_sources()
    sources = {key: index[key] | dict(archive_sha256=sha((ARCHIVE.parent / index[key]["archive_path"]).read_bytes()))
               for key in (OLD_PLAN, NEW_PLAN, FIRST, LATER, CLOSE, NIGHT, RECAP, REPLY)}
    tables = {row["source"]: row for row in exposure["tables"]}
    seen = {key: photo_row(tables, key, CONTRACT) for key in (FIRST, CLOSE, NIGHT)}
    # The two futures rows show two places. The shared transcription strips trailing zeros.
    for photo, side, average in ((FIRST, "long", "1400.10"), (FIRST, "short", "1410.50"),
                                 (NIGHT, "short", "1406.50")):
        row = seen[photo]["legs"][side]
        if Decimal(row["opening_average"]) != Decimal(average):
            raise ValueError("JM_M_REREAD_OPENING_AVERAGE_CHANGED")
        row["opening_average"] = average
    later_image = Path(sources[LATER]["archive_path"]).parent / "RnZKEysLc-table2-screen.png"
    if sha((ARCHIVE.parent / later_image).read_bytes()) != LATER_IMAGE:
        raise ValueError("JM_M_LATER_IMAGE_CHANGED")
    seen[LATER] = dict(source=LATER, version_on_post=None, binding="MIXED_POST_TABLE_BINDING_UNKNOWN",
                       published_at=sources[LATER]["published_at"],
                       image=dict(path=later_image.as_posix(), sha256=LATER_IMAGE),
                       legs={"long": dict(quantity=20, today_quantity=20, opening_average="1415.03")})
    if seen[CLOSE]["legs"] != seen[LATER]["legs"]:
        raise ValueError("JM_M_DAYTIME_LONG_FIELDS_DIVERGED")
    long_old, long_later = seen[FIRST]["legs"]["long"], seen[CLOSE]["legs"]["long"]
    short_old, short_next = seen[FIRST]["legs"]["short"], seen[NIGHT]["legs"]["short"]
    lots = long_old["quantity"]
    if {leg["quantity"] for leg in (long_later, short_old, short_next)} != {lots} or (
        [leg["today_quantity"] for leg in (long_old, long_later, short_old, short_next)] != [lots, lots, 0, lots]
    ):
        raise ValueError("JM_M_HOLDING_FIELDS_CHANGED")

    raw = tuple(read_window(session, market, CONTRACT, day) for day in DAYS)
    minute_index = {row.end: row for series in raw for row in series[1]}
    # Check the complete series against both the existing photo identity and the shaped rows.
    raw_one = read_session_series(session, market, "jm", CONTRACT, "1m", ONE, DAYS)
    if identity(raw_one) != photos["market_1m"]["jm"] or digest(minute_index.values()) != bars_sha(raw_one):
        raise ValueError("JM_M_FROZEN_MARKET_CHANGED")
    anchors = {key: quote_anchors(photos, key, minute_index, stamp(sources[key]), joint_close=key == CLOSE)
               for key in (FIRST, LATER, CLOSE, NIGHT)}
    tick = load_specs(verified_json(SPECS, SPECS_SHA))[CONTRACT]["tick"]

    def totals(leg):
        return displayed_tick_totals(Decimal(leg["opening_average"]), lots, tick)

    long_start = max(stamp(sources[OLD_PLAN]), stamp(sources[FIRST])) + ONE
    long_cut = anchors[CLOSE][0] + 2 * US
    long_gates = first_gates(raw[0], long_start, long_cut, bands=LONG_BANDS)
    for row in long_gates.values():
        if row["end"] is not None:
            row["quote_sets"] = {key: {boundary: compare_gate(
                raw[0][1], [(old, new) for old in anchors[FIRST] for new in anchors[key]], row["end"],
                boundary=boundary, tick=tick, lots=lots, old_totals=totals(long_old), new_totals=totals(long_later),
            ) for boundary in BOUNDARIES} for key in (LATER, CLOSE)}
    short_start = max(raw[1][1][0].start, stamp(sources[NEW_PLAN]) + ONE)
    short_cut = stamp(sources[NIGHT])
    short_minutes = completed(raw[1][1], short_start, short_cut)
    short_gates = first_gates(raw[1], short_start, short_cut, bands=SHORT_BANDS, side="SHORT")
    for row in short_gates.values():
        row["quote_sets"] = {boundary: formation(
            short_minutes, anchors[NIGHT], row["end"], boundary=boundary, tick=tick, lots=lots, totals=totals(short_next),
        ) for boundary in BOUNDARIES}
    first_touch = next(b.end for b in raw[0][1] if b.high >= LONG_BANDS["m"][0])
    first_close = next(b.end for b in raw[0][1] if b.close > LONG_BANDS["m"][0])
    initial_checks = {name: dict(end=gate, quote_sets={boundary: formation(
        raw[0][1], anchors[FIRST], gate, boundary=boundary, tick=tick, lots=lots, totals=totals(long_old),
    ) for boundary in BOUNDARIES}) for name, gate in (("first_m_touch", first_touch), ("first_m_strict_close", first_close))}
    return dict(
        version="lms405-jm-m-leg-handoff-v1", contract=CONTRACT, sources=sources, visible=seen, anchors=anchors,
        same_account_is_assumed_for_position_comparisons=True,
        night_price_regions_are_research_proxies=True,
        previous_short_released_at=None, original_long_task_identity=None, account_continuity=None,
        initial_long_formation=initial_checks,
        retained_previous_day_short_lots_if_today_fields_correct=short_next["quantity"] - short_next["today_quantity"],
        first_trading_day_high=max(bar.high for bar in raw[0][1]), first_day_close=raw[0][1][-1].close,
        long_gates=long_gates, short_gates=short_gates,
        markets={day.isoformat(): {f"{p}m": dict(count=len(bars), sha256=digest(bars)) for p, bars in series.items()}
                 for day, series in zip(DAYS, raw, strict=True)},
        long_window=dict(start=long_start, cut=long_cut), short_window=dict(start=short_start, cut=short_cut),
        author_signal_at=None, author_action_at=None, admitted_author_actions=0, author_match_rate=None,
        executable=False, fills=None, pnl=None,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
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
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=45):
            report = study(session, build_market_data_service(session))
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(report))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (KeyError, OSError, ValueError) as exc:
        code = str(exc)
        parser.exit(2, f"{code if code.startswith(('JM_M_', 'RU_M_')) and code.isidentifier() else 'JM_M_INPUT_UNVERIFIED'}\n")


if __name__ == "__main__":
    main()
