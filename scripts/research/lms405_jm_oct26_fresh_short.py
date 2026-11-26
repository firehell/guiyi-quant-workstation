"""Replay the 26 October JM short with the previous cycle and target clocks separated."""

from argparse import ArgumentParser
from dataclasses import asdict
from datetime import date, datetime
from decimal import Decimal
import json
from pathlib import Path

from guiyi_quant.lms405 import Action, Position, apply_action
from guiyi_quant.lms405.portfolio_tasks import Book
from lms405_iron_first_protection import by_knowledge, support
from lms405_jm_divider_study import IMAGES, LUNCH
from lms405_jm_first_lock_handoff import DAYS, SHORT_BANDS, project_roles
from lms405_portfolio_origin_window import compare_rows
from lms405_portfolio_replay import ARCHIVE, input_sources
from lms405_portfolio_task_policy import project_fixture
from lms405_protection_lot_timing import displayed_tick_totals, verified_json
from lms405_protection_timeframes import read_window
from lms405_public_plan_roles import load_source
from lms405_replay import display, read_session_series
from lms405_right_side_study import ONE, US, at
from lms405_sh_lock_lifecycle import completed, digest, signals
from lms405_volatility_context import bars_sha
from lms_near405_replay import encoded, sha

CONTRACT, PHOTO, PLAN, PRIOR_PLAN = "JM2701", "WRov1j6e10", "A5358325549629506", "A5357264059367516"
RECAP = "WRoCqMClgV"
NIGHT_START, CUTOFF = at("2026-10-26T21:00"), at("2026-10-26T22:04")
CURRENT_TRADING_DAY = date(2026, 10, 27)
PRIOR_TRADING_DAY = DAYS[1]
DAY_START, LUNCH_QUOTE = at("2026-10-27T09:00"), at("2026-10-27T11:30")
TARGET_NEAR, TARGET_FAR, SECOND_NEAR = Decimal(1391), Decimal(1375), Decimal("1372.5")
PHOTO_HASH = "35106f37378f2410b5235773a58c3e9c44581fe3eb84a2af66bf2402405cc9cb"
REREAD_AVERAGE = "1372.00"
COMBINED = (Path("output/lms405-portfolio-combined-20261126/a.json"),
            "d4f93e04cbf4bb570b5a7791d4bb67693d7ca9a98844983f835ca60099a02fbb")
PREVIOUS = (Path("output/lms405-jm-first-lock-handoff-20261126/final-a.json"),
            "477cd10a951d399f3e8bc44641d37a899634ae82c532055f4e3412b0f0594310")
OPENING = (Path("output/lms405-opening-plan-management-20261125/checked.json"),
           "43eec0d91262c22f133b776538bc291b538f988d3f8648a6d28858463ed9362d")


def first_reversal_after(series, observed, cutoff, *, position_known_at):
    """An independently formed one-minute long keybar must follow both clocks."""
    if observed is None:
        return None
    start = max(observed.end + US, position_known_at)
    return next((e for e in signals(series, 1, 1, side="LONG", start=start, cut=cutoff)
                 if start < e["shape_end"] - ONE), None)


def transition(book, operation, event_known_at, source):
    qty = book.original if operation == "CLEAR_TREND" else Decimal(20)
    assessed = project_fixture(book, operation, qty, event_known_at + 4 * US, plan=source)
    return assessed["fixture"]["after"], assessed


def action_row(event, action):
    def units(book):
        return ["1" if amount else "0" for amount in (book.visible.long, book.visible.short)]

    return dict(at=event["at"].isoformat(), action=action, projection_kind="TEST_FIXTURE",
                before=units(event["before"]), after=units(event["fixture"]["after"]))


def position_action(rows, action, known_at):
    """Project unit exposure only, with a distinct assumption for every action."""
    previous = rows[-1]
    if datetime.fromisoformat(previous["at"]) >= known_at:
        raise ValueError("JM_OCT26_POSITION_ORDER_CONFLICT")
    before = Position(CONTRACT, *map(Decimal, previous["after"]))
    after = apply_action(before, Action(action, Decimal(1)))
    return rows + [dict(at=known_at.isoformat(), action=action, projection_kind="CONDITIONAL_ASSUMPTION",
                        before=previous["after"], after=list(map(str, (after.long, after.short))))]


def strict_prefix(series, cut):
    return {period: [bar for bar in bars if bar.end + US < cut] for period, bars in series.items()}


def before_lunch(series, minutes, row, open_short, retouch, tick):
    """Check two action orders against the same long row and the first divider return."""
    strict_quote = LUNCH_QUOTE - ONE
    horizon = completed(series[1], NIGHT_START, LUNCH_QUOTE)
    divider = SHORT_BANDS["divider"]
    return_bar = next(b for b in horizon if CUTOFF < b.start and divider[0] <= b.close <= divider[1])
    night_exit = first_reversal_after(series, retouch, DAY_START,
                                      position_known_at=datetime.fromisoformat(open_short["at"]))
    if night_exit is None:
        raise ValueError("JM_OCT26_LUNCH_PREDECESSOR_SIGNAL_MISSING")
    night_exit_time = night_exit["available_at"] + 5 * US
    modes = {}
    for shape, confirm in ((1, 1), (5, 1), (5, 5)):
        events = signals(series, shape, confirm, side="LONG", start=DAY_START, cut=strict_quote)
        replay = signals(strict_prefix(series, strict_quote), shape, confirm, side="LONG",
                         start=DAY_START, cut=strict_quote)
        if not events or replay != events or night_exit_time >= events[0]["shape_end"] - shape * ONE:
            raise ValueError("JM_OCT26_LUNCH_PREFIX_OR_CLOCK_CHANGED")
        entry = events[0]
        entry_time = entry["available_at"] + 5 * US
        flat_first = position_action([open_short], "CLEAR", night_exit_time)
        protect_first = position_action([open_short], "LOCK", entry_time)
        variants = {
            "night_exit_then_fresh_day_long": position_action(flat_first, "ENTER_LONG", entry_time),
            "day_protection_with_no_short_exit_evidence": protect_first,
            "day_protection_then_exit_short_at_divider_close": position_action(
                protect_first, "EXIT_SHORT", return_bar.end + 6 * US,
            ),
        }
        paths = {}
        for name, actions in variants.items():
            checked, = compare_rows(CONTRACT, [row], "replay", actions, minutes, Decimal(20), None, tick)
            visible_state = next(action["after"] for action in reversed(actions)
                                 if datetime.fromisoformat(action["at"]) < strict_quote)
            checks = checked["by_variant"]["strict_replay"]
            paths[name] = dict(actions=actions, strict_long_check=checks[LUNCH_QUOTE.isoformat()],
                               strict_short_unit=visible_state[1], observed_short="UNLISTED_UNKNOWN")
        modes[f"{shape}m_to_{confirm}m"] = dict(entry=entry, paths=paths)

    totals = displayed_tick_totals(Decimal("1385.25"), 20, tick)
    bounds = {}
    for name, clock in (("after_short_post", CUTOFF), ("day_only", DAY_START - US),
                        ("after_divider_close", return_bar.end + US)):
        allowed = by_knowledge(horizon, clock, overlapping=False)
        bounds[name] = support(horizon, LUNCH_QUOTE, allowed, tick=tick, lots=20,
                               totals=totals, include_quote=False)
    return dict(night_exit_candidate=night_exit, divider_return_close_bar_end=return_bar.end,
                strict_cutoff=strict_quote, modes=modes, exact_opening_tick_sum=list(totals),
                price_bounds=bounds, public_short_exit=None, public_long_permission=None,
                observed_short="UNLISTED_UNKNOWN")


def study(session, market):
    opening = verified_json(*OPENING)["cases"]
    previous = verified_json(*PREVIOUS)
    combined = verified_json(*COMBINED)
    source_index = input_sources()
    sources = {key: load_source(source_index, key) for key in (PHOTO, PLAN, PRIOR_PLAN, RECAP, LUNCH)}
    photo_path = Path(sources[PHOTO]["archive_path"]).with_name("Rov1j6e10-position-screen.png")
    if (sha((ARCHIVE.parent / photo_path).read_bytes()) != PHOTO_HASH
            or datetime.fromisoformat(sources[PHOTO]["published_at"]) != CUTOFF
            or not datetime.fromisoformat(sources[PLAN]["published_at"]) + ONE < NIGHT_START < CUTOFF
            < datetime.fromisoformat(sources[RECAP]["published_at"])):
        raise ValueError("JM_OCT26_PUBLIC_SCOPE_CHANGED")
    prior, current = (read_window(session, market, CONTRACT, day)
                      for day in (PRIOR_TRADING_DAY, CURRENT_TRADING_DAY))
    for series, reference in ((prior, "jm_new_short"), (current, "jm_target_control")):
        if {f"{p}m": digest(bars) for p, bars in series.items()} != opening[reference]["market"]:
            raise ValueError("JM_OCT26_MARKET_CHANGED")
    baseline = combined["runs"]["PENDING:IRON_RETAIN"]["comparisons"][CONTRACT]
    row, = (r for r in baseline if (r["source"], r["side"]) == (PHOTO, "short"))
    leg = row["visible"]
    if (leg["quantity"] != 20 or leg["today_quantity"] != 20
            or Decimal(leg["opening_average"]) != Decimal(REREAD_AVERAGE)):
        raise ValueError("JM_OCT26_POSITION_CHANGED")
    scoring_row = row | dict(visible=leg | dict(opening_average=REREAD_AVERAGE))
    lunch_row, = (r for r in baseline if (r["source"], r["side"]) == (LUNCH, "long"))
    lunch_short, = (r for r in baseline if (r["source"], r["side"]) == (LUNCH, "short"))
    lunch_image, lunch_hash, lunch_post = IMAGES[LUNCH]
    lunch_path = Path(sources[LUNCH]["archive_path"]).with_name(lunch_image)
    if (sha((ARCHIVE.parent / lunch_path).read_bytes()) != lunch_hash
            or datetime.fromisoformat(lunch_post) != datetime.fromisoformat(sources[LUNCH]["published_at"])
            or lunch_short["status"] != "UNLISTED_UNKNOWN" or lunch_short.get("visible") is not None
            or lunch_row["status"] != "CHECKED"
            or lunch_row["visible"] != dict(quantity=20, today_quantity=20, opening_average="1385.25")
            or list(lunch_row["by_variant"]["strict_replay"]) != [LUNCH_QUOTE.isoformat()]
            or lunch_row["quote_scope"] != "ALIGNED"
            or Decimal(lunch_row["reported_quote"]) != Decimal("1392.5")):
        raise ValueError("JM_OCT26_LUNCH_SOURCE_CHANGED")
    anchors = [datetime.fromisoformat(value) for value in row["by_variant"]["strict_replay"]]
    mark = Decimal(row["reported_quote"])
    minutes = completed(current[1], NIGHT_START, CUTOFF)
    if anchors != [bar.end for bar in minutes if bar.low <= mark <= bar.high] or (
        anchors != [datetime.fromisoformat(value) for value in opening["jm_target_control"]["first_visible_quote_candidates"]]
    ):
        raise ValueError("JM_OCT26_QUOTE_SCOPE_CHANGED")

    amount = Decimal(20)
    first_lock = Book(CONTRACT, "first-original-and-protection", "SHORT",
                      datetime.fromisoformat(previous["protection_known_at"]), amount, amount, attempt=1)
    gates = {side: {name: datetime.fromisoformat(value) if value else None for name, value in clocks.items()}
             for side, clocks in previous["day_and_night_gates"].items()}
    predecessor = project_roles(first_lock, amount, gates["long"], gates["short"], PRIOR_PLAN)
    if json.loads(encoded(predecessor)) != previous["role_projection"]:
        raise ValueError("JM_OCT26_PREVIOUS_MODEL_STATE_CHANGED")
    old = predecessor["late_book"]
    near_hit = next(bar for bar in prior[1] if old.known_at < bar.start and bar.low <= TARGET_NEAR)
    far_hit = next((bar for bar in prior[1] if old.known_at < bar.start and bar.low <= TARGET_FAR), None)
    previous_exit = first_reversal_after(prior, near_hit, prior[1][-1].end + 2 * US,
                                         position_known_at=old.known_at)
    if previous_exit is None or far_hit is not None:
        raise ValueError("JM_OCT26_PREVIOUS_EXIT_SCOPE_CHANGED")

    entry, *_ = signals(current, 1, 1, side="SHORT", start=NIGHT_START, cut=CUTOFF)
    first_divider_break = next(bar for bar in minutes if bar.close < SHORT_BANDS["divider"][0])
    first_target_break = next(bar for bar in minutes if bar.close < TARGET_FAR)
    if entry["available_at"] + US != datetime.fromisoformat(opening["jm_target_control"]["reference_entry_known_at"]) or (
        not first_divider_break.end < first_target_break.end < entry["confirmed_at"]
    ):
        raise ValueError("JM_OCT26_ENTRY_CLOCK_CHANGED")
    basis = {"divider_close_price_only": first_divider_break.end + US,
             "first_target_far_close_price_only": first_target_break.end + US,
             "fresh_1m_shape": entry["available_at"]}
    tick, lots = Decimal("0.5"), leg["quantity"]
    exact_total = displayed_tick_totals(Decimal(REREAD_AVERAGE), lots, tick)
    archived_total = displayed_tick_totals(Decimal(leg["opening_average"]), lots, tick)
    price_paths = {}
    for label, known in basis.items():
        for unit in ("exact_display", "archived_display"):
            totals = exact_total if unit == "exact_display" else archived_total
            eligible = by_knowledge(minutes, known, overlapping=False)
            price_paths[f"{label}:{unit}"] = {
                display(anchor): support(minutes, anchor, eligible, tick=tick, lots=lots, totals=totals,
                                         include_quote=False)
                for anchor in anchors
            }

    retired, close_previous = transition(old, "CLEAR_TREND", previous_exit["available_at"], PRIOR_PLAN + ":first-near-test")
    next_book = Book(CONTRACT, "fresh-2026-10-27-short", "SHORT", retired.known_at)
    current_book, open_current = transition(next_book, "ENTER_TREND", entry["available_at"], PLAN + ":entry-test")
    eligible = [bar for bar in minutes if current_book.known_at < bar.start]
    after_entry_progress = next(bar for bar in eligible if bar.low <= TARGET_FAR)
    after_entry_retouch = next(bar for bar in eligible if bar.low <= TARGET_FAR <= bar.high)
    management = {}
    # The old leg still blocks a fresh separate cycle in the far-target interpretation.
    scopes = {"prior_short_still_open": None, "prior_exit_and_new_short": None,
              "exit_on_already_beyond_plus_reversal": after_entry_progress,
              "exit_on_fresh_retouch_plus_reversal": after_entry_retouch}
    native = read_session_series(session, market, "jm", CONTRACT, "1m", ONE, (PRIOR_TRADING_DAY, CURRENT_TRADING_DAY))
    if bars_sha(native) != digest((*prior[1], *current[1])):
        raise ValueError("JM_OCT26_SCORE_SERIES_CHANGED")
    for mode, reached in scopes.items():
        if mode == "prior_short_still_open":
            actions = [dict(at=old.known_at.isoformat(), action="ENTER_SHORT", projection_kind="PROJECTED_CARRY",
                            before=["0", "0"], after=["0", "1"])]
        else:
            actions = [action_row(open_current, "ENTER_SHORT")]
        reversal = first_reversal_after(current, reached, CUTOFF, position_known_at=current_book.known_at)
        projected_clear = None
        if reversal is not None:
            _, projected_clear = transition(current_book, "CLEAR_TREND", reversal["available_at"], PLAN + ":exit-test")
            actions.append(action_row(projected_clear, "CLEAR"))
        checked, = compare_rows(CONTRACT, [scoring_row], "replay", actions, native, Decimal(lots), None, tick)
        management[mode] = dict(
            actions=actions, trigger_bar_end=reached.end if reached else None, reversal=reversal,
            projected_clear=projected_clear, checks=checked["by_variant"]["strict_replay"],
        )

    for anchor in anchors:
        cut = anchor - ONE
        prefix = strict_prefix(current, cut)
        prefix_entry = next(iter(signals(prefix, 1, 1, side="SHORT", start=NIGHT_START, cut=cut)), None)
        if prefix_entry != (entry if entry["available_at"] < cut else None):
            raise ValueError("JM_OCT26_ENTRY_PREFIX_CHANGED")
        for mode, reached in scopes.items():
            event = management[mode]["reversal"]
            reached = reached if reached is not None and reached.end + US < cut else None
            actual = first_reversal_after(prefix, reached, cut, position_known_at=current_book.known_at)
            if actual != (event if event is not None and event["available_at"] < cut else None):
                raise ValueError("JM_OCT26_MANAGEMENT_PREFIX_CHANGED")
    lunch_row = lunch_row | dict(by_variant={"replay": lunch_row["by_variant"]["strict_replay"]})
    noon = before_lunch(current, native, lunch_row, action_row(open_current, "ENTER_SHORT"),
                        after_entry_retouch, tick)

    return dict(
        study="JM2701_OCT26_FRESH_SHORT_AFTER_OLD_CYCLE", sources=sources,
        old_episode=asdict(old), current_episode=asdict(current_book),
        old_target_near_at=near_hit.end, old_target_far_at=None, old_risk_permission=None,
        old_test_exit=close_previous, current_test_entry=open_current, current_keybar=entry,
        current_target_near=SECOND_NEAR, current_first_close_below_first_far=first_target_break.end,
        current_trading_day=CURRENT_TRADING_DAY, strict_price_windows=price_paths, management=management,
        strict_prefix_checks=len(anchors) * (1 + len(scopes)), lunch_handoff=noon,
        photo_reread=dict(image_sha256=PHOTO_HASH, opening_average=REREAD_AVERAGE),
        historical_revision_verified=False, actual_account_continuity=None, author_permissions_supplied=False,
        author_action_samples=0, author_match_rate=None, fills=None, executable=False,
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
    except (KeyError, ValueError, OSError, StopIteration) as exc:
        code = str(exc)
        parser.exit(2, (code if code.isidentifier() and code.startswith("JM_OCT26_")
                        else "JM_OCT26_INPUT_UNVERIFIED") + "\n")


if __name__ == "__main__":
    main()
