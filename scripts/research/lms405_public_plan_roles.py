"""Replay public commodity plans while preserving their distinct price-area roles."""

import argparse
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from lms405_portfolio_replay import ARCHIVE, input_sources
from lms405_recovery_confirmation_audit import examine, strict_runs
from lms405_protection_timeframes import VARIANTS, geometry_events, read_window, summarize
from lms405_replay import display
from lms405_right_side_study import ONE, US, at
from lms405_sh_lock_lifecycle import completed, digest
from lms405_v_zone_progress import observations
from lms_near405_replay import encoded, sha

TA_TARGET_COMMENT_AT = "2025-09-25T14:57"
CASES = {
    "G63272-537": ("RU2601", "2025-08-26", "11:30", (
        ("morning_recovery_reference", "09:00", "published", "LONG", "15885 15960"),
        ("morning_strong_target", "09:00", "published", "LONG", "16095 16200"),
        ("later_recovery_reference", "after_publication", "close", "LONG", "15885 15960"),
    )),
    "G63272-538": ("SH2601", "2025-08-28", "17:02", (
        ("first_resistance", "session_start", "close", "SHORT", "2689 2708"),
        ("second_resistance", "session_start", "close", "SHORT", "2671 2682"),
    )),
    "G63272-549": ("TA2601", "2025-09-25", "11:18", (
        ("initial_target", "09:00", "published", "LONG", "4648 4660"),
        ("expanded_target_by_comment_cutoff", "after_publication", "author_comment", "LONG", "4674 4684"),
        ("new_extreme_target", "after_publication", "close", "LONG", "4692 4696"),
        ("reused_protection_reference", "after_publication", "close", "SHORT", "4648 4660"),
        ("separate_m_reference", "after_publication", "close", "SHORT", "4640 4648"),
    )),
}
UNALIGNED_SOURCE = "S5215089620682840"
MANAGEMENT_CASES = {
    "S5290904148773752": ("V2609", "2026-04-23", "16:35", (
        ("strong_target_on_gap_day", "session_start", "close", "LONG", "5226 5262"),
    )),
    "S5292358960155373": ("V2609", "2026-04-27", "16:56", (
        ("uncompleted_long_unlock_reference", "session_start", "close", "LONG", "5226 5262"),
    )),
    "S5292720017903146": ("V2609", "2026-04-28", "16:50", (
        ("first_strong_target", "session_start", "close", "LONG", "5226 5262"),
        ("second_strong_target", "session_start", "close", "LONG", "5285 5297"),
    )),
    "S5301418816702075": ("V2609", "2026-05-22", "16:56", (
        ("uncompleted_short_target", "session_start", "close", "SHORT", "4802 4830"),
    )),
    "S5311207311147936": ("TA2609", "2026-06-18", "17:12", (
        ("short_protection_reference", "session_start", "close", "LONG", "5800 5820"),
        ("counter_m_reference", "session_start", "close", "LONG", "5868 5888"),
    )),
    "S5315919112832178": ("TA2609", "2026-07-01", "17:15", (
        ("short_reentry_reference", "session_start", "close", "SHORT", "5432 5494"),
    )),
}
PROTECTION_AND_M_CASES = {
    "S5246699477926773": ("OI2605", "2025-12-22", "17:01", (
        ("optional_counter_m_after_reported_lock", "session_start", "close", "LONG", "8738 8814"),
    )),
    "S5310836013794895": ("V2609", "2026-06-17", "16:37", (
        ("incomplete_weak_side_m", "session_start", "close", "LONG", "4686 4704"),
    )),
    "S5319173366613171": ("SA2609", "2026-07-10", "16:46", (
        ("short_protection_reference", "session_start", "close", "LONG", "1079 1087"),
        ("m_reference", "session_start", "close", "LONG", "1087 1094"),
    )),
    "S5323519697094213": ("FG2609", "2026-07-22", "16:37", (
        ("trend_reference", "session_start", "close", "LONG", "882 897"),
        ("short_protection_reference", "session_start", "close", "LONG", "893 899"),
    )),
}
EARLIER_PROTECTION_CONTEXT = {"S5323519697094213": "2026-07-21"}
COTTON_CASES = {
    "S5290450810569076": ("2026-04-22", "10:33", None, (
        ("new_extension_target", "LONG", 16085, 16335),
        ("extreme_target", "LONG", 16460, 16460),
        ("protection_reference", "SHORT", 16175, 16225),
        ("possible_m_transition", "SHORT", 16140, 16175),
    )),
    "S5295515541443911": ("2026-05-06", "09:59", "4.0.5_METHOD_ONLY", (
        ("new_extension_target", "LONG", 16900, 17060),
        ("weakness_onset_or_optional_earlier_protection", "SHORT", 16855, 16930),
        ("protection_reference", "SHORT", 16755, 16855),
    )),
}
SILVER_SOURCE = "S5325950005019835"
SILVER_BANDS = ((Decimal(13910), Decimal(14005)), (Decimal(14041), Decimal(14069)))
SILVER_M = Decimal(14440)
BATCHES = {
    "published-updates": CASES,
    "management": MANAGEMENT_CASES,
    "protection-and-m": PROTECTION_AND_M_CASES,
    "cotton-intraday": COTTON_CASES,
    "silver-ordered-bands": (SILVER_SOURCE,),
}


def load_source(index, key):
    source = index[key]
    path = ARCHIVE.parent / source["archive_path"]
    return source | dict(archive_sha256=sha(path.read_bytes()))


def cotton_protection_clocks(minutes, signals, band):
    lower, upper = band
    overlap = next((bar for bar in minutes if bar.low <= upper and bar.high >= lower), None)
    overlap_known = overlap.end + US if overlap is not None else None
    clocks = {}
    for clock, rows in signals.items():
        inside = [row for row in rows if lower <= row["close"] <= upper]
        clocks[clock] = dict(
            in_band=next(iter(inside), None),
            fresh_after_completed_overlap=next((row for row in inside if overlap_known is not None
                                                and overlap_known < row["shape_start"]), None),
        )
    return dict(overlap_known_at=overlap_known, clocks=clocks)


def cotton_intraday(session, market):
    from lms405_jm_oct_recovery_clock import window_signals

    index = input_sources()
    cases = {}
    for key, (day, time, version_scope, roles) in COTTON_CASES.items():
        source = load_source(index, key)
        published = datetime.fromisoformat(source["published_at"])
        series = read_window(session, market, "CF2609", date.fromisoformat(day))
        start = published + ONE
        close = at(f"{day}T15:00")
        if (published != at(f"{day}T{time}") or not series[1][0].start < published < start < close
                or series[1][-1].end != close):
            raise ValueError("COTTON_PUBLICATION_WINDOW_UNVERIFIED")
        cutoff = close + 2 * US
        after = completed(series[1], start, cutoff)
        before = completed(series[1], series[1][0].start, published)
        signals, checks = window_signals(series, start, cutoff, "SHORT")
        windows = {}
        for role, side, lower, upper in roles:
            band = (Decimal(lower), Decimal(upper))
            windows[role] = dict(
                side=side, band=band, before_publication_retrospective=observations(before, band, side),
                after_publication=observations(after, band, side),
                in_band_short_geometry=cotton_protection_clocks(after, signals, band) if side == "SHORT" else None,
            )
        cases[key] = dict(
            source=source, author_version_scope=version_scope, source_current_text_only=True,
            after_publication_start=start, cutoff_exclusive=cutoff, before_count=len(before),
            after_count=len(after), after_extremes=dict(low=min(b.low for b in after), high=max(b.high for b in after)),
            market={f"{p}m": dict(count=len(rows), sha256=digest(rows)) for p, rows in series.items()},
            geometry_prefix_checks=checks, role_windows=windows,
            author_signal_at=None, author_action_at=None, held_position=None,
        )
    return dict(version="lms405-cotton-intraday-roles-v1", contract="CF2609", cases=cases,
                article_revision_history_verified=False, admitted_author_action_samples=0, author_match_rate=None,
                executable=False, fills=None, pnl=None)


def ordered_stand(minutes, edges, side, *, fresh_first, m_level=None):
    """Fixed candidate: two adjacent closes per edge and distinct release bars."""
    first_runs, second_runs = (strict_runs(minutes, edge, side) for edge in edges)
    previous = first_at = second_at = None
    milestones = dict(first_band=None, second_band=None, m_boundary=None)
    for bar in minutes:
        if bar.start != previous:
            first_at = second_at = None
        previous = bar.end
        visible_at = bar.end + US
        first = first_runs.get(bar.end)
        if (first is None or first["close_count"] < 2
                or (fresh_first and first["fresh_crossing_known_at"] is None)):
            first_at = second_at = None
            continue
        if first_at is None:
            first_at = visible_at
            milestones["first_band"] = milestones["first_band"] or dict(known_at=first_at)
            continue
        second = second_runs.get(bar.end)
        if second is None or second["close_count"] < 2:
            second_at = None
        elif second_at is None:
            second_at = visible_at
            milestones["second_band"] = milestones["second_band"] or dict(known_at=second_at, first_band_known_at=first_at)
        elif m_level is not None and bar.close > m_level and milestones["m_boundary"] is None:
            milestones["m_boundary"] = dict(known_at=visible_at, first_band_known_at=first_at, second_band_known_at=second_at)
    return milestones


def silver_ordered_bands(session, market):
    from lms405_jm_oct_recovery_clock import window_signals

    source = load_source(input_sources(), SILVER_SOURCE)
    published = datetime.fromisoformat(source["published_at"])
    if published != at("2026-07-29T09:34"):
        raise ValueError("SILVER_PUBLICATION_TIME_UNVERIFIED")
    windows = {}
    for day, start, scope in (
        ("2026-07-29", published + ONE, "CURRENT_TEXT_POST_PUBLICATION"),
        ("2026-07-30", at("2026-07-29T21:00"), "PLAN_CARRY_SENSITIVITY"),
    ):
        series = read_window(session, market, "AG2610", date.fromisoformat(day))
        close = at(f"{day}T15:00")
        cutoff = close + 2 * US
        minutes = completed(series[1], start, cutoff)
        if not minutes or minutes[-1].end != close or not published < start:
            raise ValueError("SILVER_WINDOW_UNVERIFIED")
        signals, geometry_checks = window_signals(series, start, cutoff, "LONG")
        counts = 0
        routes = {}
        for side, edges, m_level in (
            ("LONG", tuple(band[1] for band in SILVER_BANDS), SILVER_M),
            ("SHORT", tuple(band[0] for band in reversed(SILVER_BANDS)), None),
        ):
            candidates = {}
            for label, fresh_first in (("allow_starts_beyond", False), ("require_fresh_first_cross", True)):
                options = dict(fresh_first=fresh_first, m_level=m_level)
                full = ordered_stand(minutes, edges, side, **options)
                checks = {event["known_at"] + step for event in full.values() if event is not None for step in (0 * US, US)}
                for cut in checks:
                    prefix = [bar for bar in minutes if bar.end + US < cut]
                    expected = {key: event if event is not None and event["known_at"] < cut else None
                                for key, event in full.items()}
                    if ordered_stand(prefix, edges, side, **options) != expected:
                        raise ValueError("SILVER_PRICE_PREFIX_DIVERGED")
                counts += len(checks)
                candidates[label] = full
            routes[side] = dict(ordered_edges=edges, candidates=candidates)
        windows[day] = dict(
            scope=scope, start=start, cutoff_exclusive=cutoff, open=minutes[0].open,
            low=min(bar.low for bar in minutes), high=max(bar.high for bar in minutes),
            market={f"{p}m": dict(count=len(rows), sha256=digest(rows)) for p, rows in series.items()},
            bands=[observations(minutes, band, "LONG") for band in SILVER_BANDS],
            first_protection_geometry_by_band=[{
                clock: next((row for row in rows if lower <= row["close"] <= upper), None)
                for clock, rows in signals.items()
            } for lower, upper in SILVER_BANDS],
            routes=routes, price_prefix_checks=counts, geometry_prefix_checks=geometry_checks,
        )
    return dict(version="lms405-silver-ordered-bands-v1", contract="AG2610", source=source,
                author_version_scope="4.0.5_PUBLIC_PLAN", windows=windows, author_signal_at=None,
                author_action_at=None, author_held_position=None, historical_plan_revision_verified=False,
                reversal_pressure_confirmation=None, admitted_author_action_samples=0, author_match_rate=None,
                executable=False, fills=None, pnl=None)


def study(session, market, *, batch="published-updates"):
    if batch == "cotton-intraday":
        return cotton_intraday(session, market)
    if batch == "silver-ordered-bands":
        return silver_ordered_bands(session, market)
    index = input_sources()
    use_management = batch == "management"
    compare_protection = batch == "protection-and-m"
    cases = BATCHES[batch]
    records = {}
    for source_id, (contract, day, published_minute, roles) in cases.items():
        source = load_source(index, source_id)
        published = datetime.fromisoformat(source["published_at"])
        if published != at(f"{day}T{published_minute}"):
            raise ValueError("PUBLIC_PLAN_SOURCE_TIME_CHANGED")
        series = read_window(session, market, contract, date.fromisoformat(day))
        session_close = at(f"{day}T15:00")
        close = session_close + 2 * US
        if compare_protection and (series[1][-1].end != session_close or published <= close):
            raise ValueError("PUBLIC_PROTECTION_REPORT_WINDOW_MISMATCH")
        boundaries = dict(published=published, after_publication=published + ONE,
                          session_start=series[1][0].start, close=close)
        if source_id == "G63272-549":
            boundaries["author_comment"] = at(TA_TARGET_COMMENT_AT)
        results = {}
        for role, start, cut, side, levels in roles:
            start_at = boundaries.get(start) or at(f"{day}T{start}")
            cut_at = boundaries.get(cut) or at(f"{day}T{cut}")
            band = tuple(map(Decimal, levels.split()))
            results[role] = examine(series, start=start_at, cut=cut_at, side=side, band=band)
            if compare_protection:
                results[role]["in_band_geometry"] = {
                    f"{shape}m_to_{confirmation}m": summarize(
                        geometry_events(series, shape, confirmation, start=start_at, as_of=cut_at, side=side),
                        band=band, milestones=(),
                    ) for shape, confirmation in VARIANTS
                }
        record = dict(contract=contract, source=source, trading_day=day, role_windows=results)
        if use_management or compare_protection:
            minutes = series[1]
            record["market_extrema"] = dict(
                first_minute_end=display(minutes[0].end), open=minutes[0].open, close=minutes[-1].close,
                high_at=display(max(minutes, key=lambda bar: bar.high).end),
                low_at=display(min(minutes, key=lambda bar: bar.low).end),
            )
        if compare_protection:
            record["market_extrema"].update(low=min(bar.low for bar in minutes), high=max(bar.high for bar in minutes))
            record["market_bar_counts"] = {f"{period}m": len(bars) for period, bars in series.items()}
            prior_day = EARLIER_PROTECTION_CONTEXT.get(source_id)
            if prior_day:
                prior = read_window(session, market, contract, date.fromisoformat(prior_day))[1]
                if prior[-1].end != at(f"{prior_day}T15:00") or prior[-1].end >= minutes[0].start:
                    raise ValueError("PUBLIC_PROTECTION_PRIOR_WINDOW_MISMATCH")
                record["earlier_price_context"] = dict(
                    trading_day=prior_day, reference_from_later_publication=True,
                    close=prior[-1].close, open_change=minutes[0].open - prior[-1].close,
                    bands={role: observations(prior, tuple(map(Decimal, prices.split())), side)
                           for role, _, _, side, prices in roles},
                )
        records[source_id] = record

    report = dict(cases=records, originals_before_current_archives=None, admitted_author_action_samples=0,
                  executable=False, fills=None, pnl=None)
    if use_management:
        return report | dict(version="lms405-public-management-roles-v1", price_roles_retrospective_only=True)
    if compare_protection:
        return report | dict(version="lms405-public-protection-and-m-roles-v1", price_roles_retrospective_only=True)
    return report | dict(version="lms405-public-plan-roles-v1",
                         author_comment=dict(source_id="G63272-549", published_at=at(TA_TARGET_COMMENT_AT),
                                             role="REPORTED_TARGET_REACHED"),
                         reported_unlock_without_contract=load_source(index, UNALIGNED_SOURCE))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--batch", choices=BATCHES, default="published-updates")
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
            result = study(session, build_market_data_service(session), batch=args.batch)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(result))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (OSError, KeyError, ValueError):
        parser.exit(2, "PUBLIC_PLAN_SOURCE_OR_MARKET_UNVERIFIED\n")


if __name__ == "__main__":
    main()
