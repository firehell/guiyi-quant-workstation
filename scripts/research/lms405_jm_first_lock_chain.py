"""Recompute separately the original short and the first published-band protection."""

from argparse import ArgumentParser
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from guiyi_quant.lms405.protection_band import active_band, visible_bands
from lms405_divider_short_candidates import DividerShortPlan, divider_short_events
from lms405_first_night_pa import REFERENCE, REFERENCE_HASH
from lms405_m_permission_study import read_pair
from lms405_old_short_entry_retention import attempts, before_first_photo
from lms405_portfolio_left_entry import scope_for
from lms405_portfolio_leg_audit import SIZE, SIZE_SHA, lot_profile, summarize
from lms405_portfolio_origin_window import ALL_DAYS, compare_rows, verify_tape
from lms405_portfolio_protection_gate import plan_rows, price_admission
from lms405_portfolio_replay import ARCHIVE, input_sources
from lms405_portfolio_right_entry import branches
from lms405_portfolio_task_policy import gated_replay, published_protection_events
from lms405_protection_lot_timing import displayed_tick_totals, verified_json
from lms405_protection_timeframes import read_window
from lms405_public_plan_roles import load_source
from lms405_range_exit_portfolio import compatibility_changes
from lms405_right_side_study import ONE, US, at
from lms405_sh_lock_lifecycle import digest, signals
from lms405_v_ta_case import identity
from lms_near405_replay import encoded, sha

CONTRACT, PHOTO = "JM2701", "WRnTlEfj1t"
DIVIDER, PROTECTION = "A5356507058536457", "A5356884629782554"
NIGHT_START, POST = at("2026-10-22T21:00"), at("2026-10-22T22:10")
PROTECT_TRADING_DAY = date(2026, 10, 23)
START = date(2026, 10, 19)
COMBINED = (Path("output/lms405-portfolio-combined-20261126/a.json"),
            "d4f93e04cbf4bb570b5a7791d4bb67693d7ca9a98844983f835ca60099a02fbb")
FIRST_RUN = (Path("output/lms405-jm-first-lock-chain-20261126/final-a.json"),
             "6d3e40d15650cc40475629471ca3411c263f3b7e8d2e0efe3bc5b0a14c0d854f")


def retention_sensitivity(book, _shape, _bar, _evaluated_at):
    scoped = book.contract == CONTRACT and book.direction == "SHORT"
    return dict(admitted=not scoped, reason="ORIGINAL_SHORT_EXIT_NOT_IN_CONTEMPORARY_RECORD"
                if scoped else "OUTSIDE_JM_SHORT_SCOPE")


def protection_events_15m(series, bands, cutoff):
    cutoff = min(cutoff, POST)
    if any(bar.contract != CONTRACT for period in (1, 15) for bar in series[period]):
        raise ValueError("JM_FIRST_PROTECTION_CONTRACT_MISMATCH")
    result = []
    for event in signals(series, 15, 15, side="LONG", start=NIGHT_START, cut=cutoff):
        known = event["available_at"]
        ready = known + 5 * US
        if ready >= cutoff:
            continue
        band, _ = active_band(visible_bands(bands, CONTRACT, known), known, "SHORT")
        latest, _ = active_band(visible_bands(bands, CONTRACT, ready), ready, "SHORT")
        if band is None or band.revision != PROTECTION or latest != band:
            continue
        if price_admission(series[1], band, event, shape_step=15 * ONE)["ordinary_due_at"] is None:
            continue
        result.append(dict(
            at=ready, known_at=known, shape_start=event["shape_end"] - 15 * ONE, band=band,
            period=15, confirmation_period=15, signal=event, operation="PROTECT_REGULAR",
        ))
    return result


def replay_first_lock(series, bands, end, *, retain=False, extend=False, divider=None):
    prefix = {period: [bar for bar in bars if bar.end + US < end] for period, bars in series.items()}
    protections = published_protection_events(prefix, bands, end, advance_at_touch=True)
    if extend:
        protections += protection_events_15m(prefix, bands, end)

    def first_window_retention(book, shape, bar, evaluated_at):
        if evaluated_at >= POST:
            return dict(admitted=True)
        return retention_sensitivity(book, shape, bar, evaluated_at)

    return gated_replay(
        prefix[5], end, protections, minutes=prefix[1], range_exit_requires_confirmation=True,
        original_reversal_evidence=first_window_retention if retain else None,
        divider_events=divider_short_events(prefix, divider, end) if divider is not None else (),
    )


def study(session, market):
    combined = verified_json(*COMBINED)
    first = verified_json(REFERENCE, REFERENCE_HASH)
    reference = first["cases"][CONTRACT]
    index = input_sources()
    sources = {key: load_source(index, key) for key in (DIVIDER, PROTECTION, PHOTO)}
    photo = first["photo"]
    if (sources[PROTECTION] != reference["plan"] or sources[PHOTO] != first["photo_source"]
            or sha((ARCHIVE.parent / photo["path"]).read_bytes()) != photo["sha256"]
            or scope_for(index, CONTRACT) is not None or branches(index, CONTRACT)):
        raise ValueError("JM_FIRST_PUBLIC_SCOPE_CHANGED")
    days = tuple(d for d in ALL_DAYS if d >= START)
    raw, series = read_pair(session, market, CONTRACT, days)
    complete_15 = read_window(session, market, CONTRACT, PROTECT_TRADING_DAY)
    if {f"{period}m": digest(rows) for period, rows in complete_15.items()} != reference["market"]:
        raise ValueError("JM_FIRST_PROTECTION_MARKET_CHANGED")
    series[15] = complete_15[15]
    full_cutoff = datetime.fromisoformat(combined["as_of"])
    control = combined["contracts"][CONTRACT]
    if (identity(raw[1]) != control["market"]["one_minute"]
            or digest([b for b in series[5] if b.end + US <= full_cutoff]) != control["market"]["five_minute"]):
        raise ValueError("JM_FIRST_ORIGINAL_MARKET_CHANGED")
    bands, _, _ = plan_rows(index, CONTRACT)
    known = datetime.fromisoformat(sources[DIVIDER]["published_at"]).replace(second=0, microsecond=0) + ONE
    replacement = datetime.fromisoformat(sources[PROTECTION]["published_at"]).replace(second=0, microsecond=0) + ONE
    next_short = DividerShortPlan(CONTRACT, DIVIDER, known, at("2026-10-21T21:00"), replacement,
                                  Decimal(1401), Decimal(1406), "FIRST_FAR_CLOSE")
    observed = [row for row in combined["runs"]["PENDING:IRON_RETAIN"]["comparisons"][CONTRACT]
                if row["source"] == PHOTO]
    if {row["side"] for row in observed} != {"long", "short"} or any(r["status"] != "CHECKED" for r in observed):
        raise ValueError("JM_FIRST_PHOTO_SCOPE_CHANGED")
    anchors = [datetime.fromisoformat(value) for value in reference["individual_quote_ends"]]
    if any([datetime.fromisoformat(v) for v in r["by_variant"]["strict_replay"]] != anchors for r in observed):
        raise ValueError("JM_FIRST_QUOTE_SCOPE_CHANGED")
    tick, size = Decimal(reference["tick"]), lot_profile(verified_json(SIZE, SIZE_SHA))[CONTRACT]
    short_row, = (r for r in observed if r["side"] == "short")
    short = short_row["visible"]
    lots = short["quantity"]
    if lots != size or short["today_quantity"] != 0:
        raise ValueError("JM_FIRST_ORIGINAL_LOT_SCOPE_CHANGED")

    def replay(end, *, retain=False, extend=False, enter_divider=False):
        return replay_first_lock(series, bands, end, retain=retain, extend=extend,
                                 divider=next_short if enter_divider else None)

    actions, blocked = replay(POST)
    frozen = control["tapes"]["control"]
    verify_tape(actions, blocked, {key: [row for row in rows if datetime.fromisoformat(row["at"]) < POST]
                                   for key, rows in frozen.items()})
    trace = before_first_photo(series[5], actions, POST)
    minutes = [b for b in raw[1] if b.bar_end < POST]
    days = {day: [b for b in minutes if b.trading_day == day] for day in days if day <= PROTECT_TRADING_DAY}
    original_checks = attempts(
        trace, days, first_quote=anchors[0], last_quote=anchors[-1], observed_day=PROTECT_TRADING_DAY,
        tick=tick, lots=lots, totals=displayed_tick_totals(Decimal(short["opening_average"]), lots, tick),
    )
    flows = {}
    for mode, choices in (
        ("CONTROL", {}), ("RETAIN_ORIGINAL", {"retain": True}), ("ADD_15M_ONLY", {"extend": True}),
        ("RETAIN_AND_ADD_15M", {"retain": True, "extend": True}),
        ("PUBLISHED_DIVIDER_AND_ADD_15M", {"enter_divider": True, "extend": True}),
    ):
        tape, pauses = replay(POST, **choices)
        for clock in (at("2026-10-19T21:15"), at("2026-10-21T22:30"), *anchors):
            expected = ([row for row in tape if datetime.fromisoformat(row["at"]) < clock],
                        [row for row in pauses if row["at"] < clock])
            if replay(clock, **choices) != expected:
                raise ValueError("JM_FIRST_PREFIX_DIVERGED")
        rows = compare_rows(CONTRACT, observed, "replay", tape, minutes, size, None, tick)
        flows[mode] = dict(
            actions=tape, blocked=pauses, comparisons=rows, changed_quotes=compatibility_changes(observed, rows),
            strict=summarize({CONTRACT: rows})[CONTRACT]["strict_replay"],
        )
    return dict(
        study="JM2701_FIRST_VISIBLE_LOCK_CHAIN_RESEARCH", sources=sources, photo=photo, original_short=original_checks,
        candidate_divider_events=divider_short_events(series, next_short, POST), modes=flows,
        price_window=reference, control_market=control["market"], reference_sha256=COMBINED[1],
        approvals_are_test_fixtures=True, original_short_retention_is_sensitivity=True,
        protection_15m_is_sensitivity=True, snapshots_used_as_inputs=False,
        author_action_samples=0, author_match_rate=None, fills=None, pnl=None, executable=False,
    )


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
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
            report = study(session, build_market_data_service(session))
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(report))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (KeyError, ValueError, OSError) as exc:
        code = str(exc)
        parser.exit(2, (code if code.isidentifier() and code.startswith("JM_FIRST_")
                        else "JM_FIRST_INPUT_UNVERIFIED") + "\n")


if __name__ == "__main__":
    main()
