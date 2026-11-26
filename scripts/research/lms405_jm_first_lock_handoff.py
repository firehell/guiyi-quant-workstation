"""Continue the first JM2701 lock through the next day and fresh-short observation."""

import argparse
from datetime import date, datetime
from decimal import Decimal
from itertools import product
from pathlib import Path

from guiyi_quant.lms405.portfolio_tasks import Book
from lms405_iron_first_protection import by_knowledge, support
from lms405_jm_first_lock_chain import FIRST_RUN
from lms405_jm_m_leg_handoff import CLOSE, CONTRACT, FIRST, LATER, LONG_BANDS, NEW_PLAN, NIGHT, OLD_PLAN
from lms405_portfolio_origin_window import observed_average
from lms405_portfolio_replay import ARCHIVE, input_sources
from lms405_portfolio_task_policy import project_fixture
from lms405_protection_lot_timing import EXPOSURE, displayed_tick_totals, tick_bounds, verified_json
from lms405_protection_timeframes import read_window
from lms405_public_plan_roles import load_source
from lms405_replay import display
from lms405_reversal_stage_bounds import photo_row
from lms405_right_side_study import ONE, US, at
from lms405_rubber_m_replacements import count_bounds, first_gates
from lms405_sh_lock_lifecycle import digest
from lms405_sh_protection_replacement import compatible_counts
from lms405_sizing_audit import EXPOSURE_SHA256
from lms_near405_replay import encoded, sha

FOLLOWUP = (Path("output/lms405-jm-m-leg-handoff-20261125/final.json"),
            "3f768f34ccacc10739ef168aa119f3b5d6beb8c2fbf6ebe4d31e5caa787719ae")
DAYS = (date(2026, 10, 23), date(2026, 10, 26))
LONG_WINDOWS = ("m_near_5m_to_1m_same_run", "m_near_5m_to_5m_same_run", "extreme_m_far_strict_close")
SHORT_BANDS = {"divider": (Decimal(1392), Decimal("1415.5"))}
EARLY_SHORT, NEW_SHORT = "divider_near_strict_close", "divider_near_1m_to_1m_same_run"
FAR_SHORT = "divider_far_strict_close"


def counts_from_replay(minutes, *, old_at, old_quote, next_quote, known_at, tick, lots, old_total, new_total):
    # Quote-minute prices are excluded from the old leg and may not be reused at a later observation.
    old_rows = [bar for bar in minutes if old_at < bar.start and bar.end <= old_quote - ONE]
    between = [bar for bar in minutes if old_quote <= bar.start and bar.end <= next_quote - ONE]
    earlier = [bar for bar in between if bar.start <= known_at]
    later = [bar for bar in between if known_at < bar.start]
    old_range = tick_bounds(old_rows, tick)
    if old_range is None:
        raise ValueError("JM_HANDOFF_FIRST_COHORT_EMPTY")
    counts = compatible_counts(lots, old_total, new_total, old_range, tick_bounds(earlier, tick), tick_bounds(later, tick))
    return (count_bounds(counts, lots) if counts else dict(no_compatible_allocations=True)) | dict(
        gate_known_at=known_at, gate_known_before_quote_minute=known_at < next_quote - ONE,
        old_range_ticks=old_range, actual_opening_fills=None,
    )


def close_cohort_continuity(rows, minutes, tick):
    long_rows = {row["source"]: row for row in rows if row["side"] == "long"}
    first, close = long_rows[FIRST], long_rows[CLOSE]
    lots = first["visible"]["quantity"]
    if (first["assumed_trading_day"] != close["assumed_trading_day"]
            or any(row["visible"]["quantity"] != lots or row["visible"]["today_quantity"] != lots
                   for row in (first, close))):
        raise ValueError("JM_HANDOFF_CLOSE_COHORT_SCOPE_CHANGED")
    old_total, new_total = (displayed_tick_totals(observed_average(CONTRACT, row), lots, tick)
                            for row in (first, close))
    first_checks, close_checks = (row["by_variant"]["strict_replay"] for row in (first, close))
    pairs = {}
    for old_label, old in first_checks.items():
        for new_label, new in close_checks.items():
            if old["status"] != "PRICE_COMPATIBLE" or new["status"] != "PRICE_COMPATIBLE":
                continue
            old_at = old["origin_at"]
            new_at = new["origin_at"]
            bounds = counts_from_replay(
                minutes, old_at=old_at, old_quote=datetime.fromisoformat(old_label),
                next_quote=datetime.fromisoformat(new_label), known_at=new_at, tick=tick,
                lots=lots, old_total=old_total, new_total=new_total,
            )
            # The unit replay can carry the entire leg or replace it, without fractional cohorts.
            unchanged_leg = old_at == new_at
            max_retained = bounds.get("max_old_retained")
            pairs[f"{old_label} / {new_label}"] = dict(
                projected_retained=lots if unchanged_leg else 0,
                minimum_replacement=lots - max_retained if max_retained is not None else None,
                price_compatible=max_retained == lots if unchanged_leg
                else bounds.get("all_ending_lots_new_after_possible", False),
            )
    return dict(sources=(FIRST, CLOSE), opening_tick_sums={FIRST: list(old_total), CLOSE: list(new_total)},
                same_account_and_synchronous_observation_assumed=True,
                individually_compatible_quote_pairs=pairs)


def project_roles(old, lots, gates, night_gates, revision):
    def apply(book, operation, quantity, bar_end, source):
        row = project_fixture(book, operation, quantity, bar_end + 5 * US, plan=source)
        return row["fixture"]["after"], row

    # Both old-cycle clearance and the M open require their own hypothetical permissions.
    cleared, clear = apply(old, "CLEAR_TREND", old.original + old.protection, gates["m_far_strict_close"], "old-exit-test")
    trading, enter = apply(cleared, "ENTER_COUNTER_M", lots, gates[LONG_WINDOWS[0]], "m-entry-test")
    flat, exit_m = apply(trading, "EXIT_COUNTER_M", lots, night_gates[EARLY_SHORT], revision + ":m-exit-test")
    new_book = Book(old.contract, "new-2026-10-26-short", "SHORT", flat.known_at)
    current, enter_short = apply(new_book, "ENTER_TREND", lots, night_gates[NEW_SHORT], revision + ":new-short-test")
    if flat.visible.long or flat.visible.short:
        raise ValueError("JM_HANDOFF_NOT_FLAT_FOR_FRESH_CYCLE")
    return dict(
        old_lock_unchanged=old, independent_approvals=[clear, enter, exit_m, enter_short], late_book=current,
        clearance_at_m_far_is_sensitivity=True, author_permissions_supplied=False,
    )


def project_action_clocks(old, gates, *, cutoff, shape_starts=None):
    """Research-only clearance, independent M trade, then a fresh short from flat."""
    book = old
    steps = []
    shape_starts = shape_starts or {}
    for key, operation, qty in (
        ("clear_old", "CLEAR_TREND", old.original + old.protection),
        ("open_m", "ENTER_COUNTER_M", old.protection),
        ("exit_m", "EXIT_COUNTER_M", old.protection),
        ("new_short", "ENTER_TREND", old.original),
    ):
        end = gates[key]
        if end is None or end + 6 * US >= cutoff:
            return steps, dict(stage=key, reason="NO_COMPLETED_GATE_AS_OF")
        if end <= book.known_at or shape_starts.get(key, end) <= book.known_at:
            return steps, dict(stage=key, reason="GATE_NOT_FRESH_FOR_POSITION")
        if key == "new_short":
            if book.visible.long or book.visible.short:
                raise ValueError("JM_HANDOFF_NOT_FLAT_FOR_FRESH_CYCLE")
            book = Book(old.contract, "new-2026-10-26-short", "SHORT", book.known_at)
        row = project_fixture(book, operation, qty, end + 5 * US, plan=f"{key}:{end.isoformat()}")
        steps.append(row)
        book = row["fixture"]["after"]
    return steps, None


def close_m_gate(minutes, entry, cutoff, far):
    """Sensitivity for an M exit at the completed day close after an extreme-M break."""
    close = at("2026-10-23T15:00")
    if entry is None or close + US >= cutoff:
        return None
    window = [bar for bar in minutes if entry < bar.start and bar.end <= close]
    if (window and window[-1].end == close and window[-1].close <= far
            and any(bar.close > far for bar in window[:-1])):
        return close
    return None


def chain_checks(old, steps, quotes, old_minutes, new_minutes, *, tick, totals):
    def at_quote(end):
        return next((row["fixture"]["after"] for row in reversed(steps) if row["at"] < end - ONE), old)

    day_checks, night_checks = {}, {}
    m_open = next((row["at"] for row in steps if row["operation"] == "ENTER_COUNTER_M"), None)
    fresh_short = next((row["at"] for row in steps if row["operation"] == "ENTER_TREND"), None)
    lots = int(old.protection)
    for source in (CLOSE, LATER):
        pairs = {}
        for a, b in product(quotes[FIRST], quotes[source]):
            key = f"{display(a)} / {display(b)}"
            pairs[key] = False
            if (old.known_at < a - ONE and at_quote(a) == old and m_open is not None
                    and at_quote(b).counter_m == old.protection):
                bounds = counts_from_replay(
                    old_minutes, old_at=old.known_at, old_quote=a, next_quote=b, known_at=m_open,
                    tick=tick, lots=lots, old_total=totals(FIRST, "long"), new_total=totals(source, "long"),
                )
                pairs[key] = bounds.get("all_ending_lots_new_after_possible", False)
        day_checks[source] = pairs
    for end in quotes[NIGHT]:
        book = at_quote(end)
        late = by_knowledge(new_minutes, fresh_short, overlapping=False)
        support_row = support(new_minutes, end, late, tick=tick, lots=int(old.original),
                              totals=totals(NIGHT, "short"), include_quote=False)
        night_checks[display(end)] = dict(
            fresh_short_visible=fresh_short is not None and book.episode != old.episode and book.original == old.original,
            whole_leg_price_possible=support_row["entire_leg_allowed"],
            minimum_lots_outside_allowed=support_row["minimum_lots_outside_allowed_minutes"],
        )
    return dict(first_to_close=day_checks[CLOSE], first_to_mixed_post=day_checks[LATER], night=night_checks,
                first_close_and_night_price_possible=any(day_checks[CLOSE].values()) and any(
                    row["fresh_short_visible"] and row["whole_leg_price_possible"] for row in night_checks.values()
                ))


def compare_action_clocks(old, old_day, new_day, quotes, *, old_known, new_known, cutoff, tick, totals):
    day_end = at("2026-10-23T15:00")
    day_cut = day_end + 2 * US
    far = LONG_BANDS["extreme_m"][1]
    long_bands = {name: LONG_BANDS[name] for name in ("m", "extreme_m")}
    clearance = first_gates(old_day, max(old.known_at, old_known), day_cut, bands=long_bands)
    short_start = max(new_day[1][0].start, new_known)
    short = first_gates(new_day, short_start, cutoff, bands=SHORT_BANDS, side="SHORT")
    results = {}
    for clear_key in ("m_far_strict_close", "extreme_m_far_strict_close"):
        clear_at = clearance[clear_key]["end"]
        fresh_long = first_gates(old_day, clear_at + 6 * US, day_cut, bands=long_bands) if clear_at else {}
        for enter_key, exit_key, short_key in product(LONG_WINDOWS, ("day_close", "night_near"),
                                                     (EARLY_SHORT, NEW_SHORT, FAR_SHORT)):
            entry = fresh_long.get(enter_key, {}).get("end")
            exit_at = (close_m_gate(old_day[1], entry, cutoff, far) if exit_key == "day_close"
                       else short[EARLY_SHORT]["end"])
            gates = dict(clear_old=clear_at, open_m=entry, exit_m=exit_at,
                         new_short=short.get(short_key, {}).get("end"))
            shape_starts = {key: row["geometry"]["shape_start"] for key, row in (
                ("open_m", fresh_long.get(enter_key, {})), ("new_short", short.get(short_key, {})),
            ) if "geometry" in row}
            steps, stopped = project_action_clocks(old, gates, cutoff=cutoff, shape_starts=shape_starts)
            cuts = {row["at"] for row in steps} | {q - ONE for source in (FIRST, CLOSE, NIGHT) for q in quotes[source]}
            for cut in cuts:
                prefix, _ = project_action_clocks(old, gates, cutoff=cut, shape_starts=shape_starts)
                if prefix != [row for row in steps if row["at"] < cut]:
                    raise ValueError("JM_HANDOFF_ACTION_CLOCK_PREFIX_CHANGED")
            key = "/".join((clear_key, enter_key, exit_key, short_key))
            results[key] = dict(gates=gates, shape_starts=shape_starts, steps=steps, stopped=stopped,
                                prefix_checks=len(cuts),
                                checks=chain_checks(old, steps, quotes, old_day[1], new_day[1], tick=tick, totals=totals))
    return dict(
        paths=results, public_author_actions=0, author_permissions_supplied=False,
        first_position_direction_and_time_from_replay=True, size_scaled_to_first_snapshot_quantity=True,
        same_account_and_synchronous_observation_assumed=True, author_side_not_displayed_stays_unknown=True,
        price_only_entries_are_sensitivity=True, day_close_exit_is_sensitivity=True,
    )


def study(session, market, *, with_action_clocks=False):
    lead = verified_json(*FIRST_RUN)
    follow = verified_json(*FOLLOWUP)
    selected = lead["modes"]["RETAIN_AND_ADD_15M"]
    opening, lock = tuple(row for row in selected["actions"] if row["action"] in {"ENTER_SHORT", "LOCK"})
    open_at, lock_at = (datetime.fromisoformat(row["at"]) for row in (opening, lock))
    if lock["protection"]["confirmation_period"] != 15 or lock["after"] != ["1", "1"]:
        raise ValueError("JM_HANDOFF_FIRST_STATE_CHANGED")
    tables = {r["source"]: r for r in verified_json(EXPOSURE, EXPOSURE_SHA256)["tables"]}
    for key, snapshot in follow["visible"].items():
        image = snapshot["image"]
        if sha((ARCHIVE.parent / image["path"]).read_bytes()) != image["sha256"]:
            raise ValueError("JM_HANDOFF_SNAPSHOT_CHANGED")
        if key != LATER and photo_row(tables, key, CONTRACT)["image"] != image:
            raise ValueError("JM_HANDOFF_SNAPSHOT_SCOPE_CHANGED")
    visible = follow["visible"]
    for key, direction in ((FIRST, "long"), (LATER, "long"), (CLOSE, "long"), (NIGHT, "short")):
        if visible[key]["legs"][direction]["today_quantity"] != visible[key]["legs"][direction]["quantity"]:
            raise ValueError("JM_HANDOFF_TODAY_SCOPE_CHANGED")
    index = input_sources()
    sources = {key: load_source(index, key) for key in follow["sources"]}
    if any(sources[key]["archive_sha256"] != row["archive_sha256"] for key, row in follow["sources"].items()):
        raise ValueError("JM_HANDOFF_SOURCE_CHANGED")
    data = {}
    for day in DAYS:
        series = read_window(session, market, CONTRACT, day)
        actual = {f"{p}m": dict(count=len(bars), sha256=digest(bars)) for p, bars in series.items()}
        if actual != follow["markets"][day.isoformat()]:
            raise ValueError("JM_HANDOFF_MARKET_CHANGED")
        data[day] = series
    old_day, new_day = (data[d] for d in DAYS)
    end_night = datetime.fromisoformat(sources[NIGHT]["published_at"])
    new_plan = datetime.fromisoformat(sources[NEW_PLAN]["published_at"]) + ONE
    new_start = new_day[1][0].start
    if not new_plan < new_start < end_night or new_start != at("2026-10-23T21:00"):
        raise ValueError("JM_HANDOFF_NEW_PLAN_SCOPE_CHANGED")
    long_start = datetime.fromisoformat(follow["long_window"]["start"])
    raw_gates = first_gates(old_day, long_start,
                           datetime.fromisoformat(follow["long_window"]["cut"]), bands=LONG_BANDS)
    raw_short = first_gates(new_day, new_start, end_night, bands=SHORT_BANDS, side="SHORT")
    gates = {k: raw_gates[k]["end"] for k in (*LONG_WINDOWS, "m_far_strict_close")}
    short_gates = {k: raw_short[k]["end"] for k in (EARLY_SHORT, NEW_SHORT, "divider_far_strict_close")}
    for clocks, frozen in ((gates, follow["long_gates"]), (short_gates, follow["short_gates"])):
        if any(value != (datetime.fromisoformat(frozen[k]["end"]) if frozen[k]["end"] else None)
               for k, value in clocks.items()):
            raise ValueError("JM_HANDOFF_GATE_CHANGED")
    prefix_checks = 0
    for series, start, bands, side, clocks in (
        (old_day, long_start, LONG_BANDS, "LONG", gates),
        (new_day, new_start, SHORT_BANDS, "SHORT", short_gates),
    ):
        for label, end in clocks.items():
            if end is None:
                continue
            cut = end + 2 * US
            prefix = {p: [bar for bar in bars if bar.end + US < cut] for p, bars in series.items()}
            if first_gates(prefix, start, cut, bands=bands, side=side)[label]["end"] != end:
                raise ValueError("JM_HANDOFF_GATE_PREFIX_CHANGED")
            prefix_checks += 1
    anchors = {key: [datetime.fromisoformat(v) for v in times] for key, times in follow["anchors"].items()}
    if not all(known < anchors[NIGHT][-1] for known in (short_gates[EARLY_SHORT], short_gates[NEW_SHORT])):
        raise ValueError("JM_HANDOFF_GATE_AFTER_NIGHT_OBSERVATION")
    lot_count, tick = visible[FIRST]["legs"]["long"]["quantity"], Decimal("0.5")

    def totals(source, side):
        leg = visible[source]["legs"][side]
        if leg["quantity"] != lot_count:
            raise ValueError("JM_HANDOFF_QUANTITY_CHANGED")
        return displayed_tick_totals(Decimal(leg["opening_average"]), lot_count, tick)

    replacement = {}
    for source in (LATER, CLOSE):
        replacement[source] = {gate: {
            f"{display(a)} / {display(b)}": counts_from_replay(
                old_day[1], old_at=lock_at, old_quote=a, next_quote=b, known_at=gates[gate] + US, tick=tick,
                lots=lot_count, old_total=totals(FIRST, "long"), new_total=totals(source, "long"),
            ) for a in anchors[FIRST] for b in anchors[source]
        } for gate in LONG_WINDOWS}
    before_post = [bar for bar in new_day[1] if bar.end + US < end_night]
    short = {}
    for gate, clock in short_gates.items():
        late = by_knowledge(before_post, clock + US if clock is not None else None, overlapping=False)
        short[gate] = {display(end): support(before_post, end, late, tick=tick, lots=lot_count,
                                             totals=totals(NIGHT, "short"), include_quote=False)
                       for end in anchors[NIGHT]}
    amount = Decimal(lot_count)
    old = Book(CONTRACT, "first-original-and-protection", "SHORT", lock_at, amount, amount, attempt=1)
    role_projection = project_roles(old, amount, gates, short_gates, NEW_PLAN)
    action_clocks = {}
    if with_action_clocks:
        old_revision = sources[OLD_PLAN]["published_at"]
        action_clocks["action_clock_comparison"] = compare_action_clocks(
            old, old_day, new_day, anchors, old_known=datetime.fromisoformat(old_revision) + ONE,
            new_known=new_plan, cutoff=end_night, tick=tick, totals=totals,
        )
    return dict(
        study="JM2701_FIRST_LOCK_TO_DAY_AND_NEW_NIGHT_SHORT_RESEARCH", sources=sources, quotes=anchors,
        original_opened_at=open_at, protection_known_at=lock_at, replacement=replacement, fresh_short=short,
        day_and_night_gates=dict(long=gates, short=short_gates), role_projection=role_projection,
        gates_rechecked_at_knowledge_prefix=prefix_checks,
        prior_short_quantity_that_can_be_today=0, earlier_unlisted_side_is_unknown=True,
        same_account_assumed_for_replacement_bounds=True, old_side_absence_never_inferred=True,
        author_action_samples=0, author_match_rate=None, fills=None, executable=False,
        reference_sha256=dict(first=FIRST_RUN[1], followup=FOLLOWUP[1]),
        **action_clocks,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--compare-action-clocks", action="store_true")
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
            report = study(session, build_market_data_service(session), with_action_clocks=args.compare_action_clocks)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(report))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (KeyError, ValueError, OSError) as exc:
        code = str(exc)
        parser.exit(2, (code if code.isidentifier() and code.startswith("JM_HANDOFF_")
                        else "JM_HANDOFF_INPUT_UNVERIFIED") + "\n")


if __name__ == "__main__":
    main()
