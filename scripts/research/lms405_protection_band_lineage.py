"""Replay disclosed protection-area lineage under two explicit knowledge clocks."""

import argparse
import csv
from dataclasses import asdict
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from guiyi_quant.lms405.protection_band import ProtectionBandUpdate, active_band, visible_bands
from lms405_m_permission_study import read_pair
from lms405_portfolio_replay import ARCHIVE
from lms405_protection_lot_timing import verified_json
from lms405_right_side_study import ONE, US, at
from lms405_sh_lock_lifecycle import signals
from lms405_volatility_context import bars_sha
from lms_near405_replay import encoded, sha

HANDOFF = (Path("output/lms405-protection-handoff-20261125/final.json"),
           "2c5457ee76981579bafd87971af5b7e163fe8e7d610bea024dfd12573294ba61")
MARKET_SODA = (Path("output/lms405-sh-lock-lifecycle-20261125/report.json"),
               "4bd0e828b6e654decbe6e2e8a5e3c547835c607f658b904b727aad3699368986")
OIL, SODA = "OI2609", "SH2701"
APRIL, MAY_TARGETS, MAY_EXCERPT = "S5290447639678222", "S5303501070534706", "S5303501928533791"
SODA_OLD, SODA_PENDING, SODA_NEW = "A5358325972992140", "WRouYm67Bc", "A5358686695981271"
HISTORIES = {
    "oil_april": (OIL, "LONG", (
        ("completed_strong_target", "TARGET", APRIL, (9643, 9657)),
        ("different_protection_search_area", "PROTECTION", APRIL, (9596, 9630)),
    )),
    "oil_may": (OIL, "LONG", (
        ("first_completed_target", "TARGET", MAY_TARGETS, (9739, 9745)),
        ("later_completed_target", "TARGET", MAY_TARGETS, (9757, 9792)),
        ("reuse_mentioned_in_truncated_excerpt", "REVIEW_PENDING", MAY_EXCERPT, ()),
    )),
    "soda_october": (SODA, "SHORT", (
        ("old_protection", "PROTECTION", SODA_OLD, (1516, 1529)),
        ("old_special_target", "TARGET", SODA_OLD, (1498, 1498)),
        ("review_announced_without_new_price", "REVIEW_PENDING", SODA_PENDING, ()),
        ("new_short_target", "TARGET", SODA_PENDING, (1483, 1485)),
        ("next_night_protection", "PROTECTION", SODA_NEW, (1490, 1501)),
    )),
}


def post_clock(row):
    return datetime.fromisoformat(row["published_at"]).replace(second=0, microsecond=0) + ONE


def build_updates(contract, side, entries, sources):
    updates = []
    for name, role, source, band in entries:
        clock = post_clock(sources[source])
        updates.append(ProtectionBandUpdate(contract, name, role, clock, clock, source, side, *map(Decimal, band)))
    return tuple(updates)


def selected(updates, contract, side, instant, *, observations=None):
    if observations is not None:
        updates = tuple(row for row in updates if observations[row.source] < instant)
    row, status = active_band(visible_bands(updates, contract, instant), instant, side)
    return dict(revision=row.revision if row else None, scope=row.scope if row else None, unresolved=status)


def timeline(updates, contract, side, *, observations=None, checkpoints=None):
    result = []
    clocks = {entry.known_at for entry in updates} if checkpoints is None else set(checkpoints)
    for stamp in sorted(clocks):
        probes = (stamp, stamp + US)
        for instant in probes:
            prefix = tuple(update for update in updates if update.known_at < instant)
            if selected(prefix, contract, side, instant, observations=observations) != selected(
                updates, contract, side, instant, observations=observations,
            ):
                raise ValueError("PROTECTION_LINEAGE_PREFIX_CHANGED")
        result.append(dict(at=stamp, exact=selected(updates, contract, side, probes[0], observations=observations),
                           afterward=selected(updates, contract, side, probes[1], observations=observations)))
    return result


def price_checks(series, band, *, start, cut, signal_side):
    lo, hi = band
    minutes = [bar for bar in series[1] if bar.start > start and bar.end + US < cut]
    first = next((bar.end for bar in minutes if bar.low <= hi and lo <= bar.high), None)
    candidates = {}
    for shape, confirm in ((1, 1), (5, 1), (5, 5)):
        rows = signals(series, shape, confirm, side=signal_side, start=start + US, cut=cut)
        inside = [row for row in rows if lo <= row["close"] <= hi]
        candidates[f"{shape}m_to_{confirm}m"] = dict(total=len(rows), inside=len(inside), inside_candidates=inside)
    return dict(range=band, start_exclusive=start, cutoff_exclusive=cut, minute_count=len(minutes),
                high=max((bar.high for bar in minutes), default=None), low=min((bar.low for bar in minutes), default=None),
                first_overlap=first, geometry=candidates)


def study(session, market):
    handoff = verified_json(*HANDOFF)
    soda_frozen = verified_json(*MARKET_SODA)
    with ARCHIVE.open(newline="", encoding="utf-8") as stream:
        index = {row["source_id"]: row for row in csv.DictReader(stream)}
    source_ids = {entry[2] for _, _, rows in HISTORIES.values() for entry in rows} | {"WRozPmaK10"}
    sources = {key: index[key] | dict(archive_sha256=sha((ARCHIVE.parent / index[key]["path"]).read_bytes()))
               for key in sorted(source_ids)}
    observations = {key: datetime.fromisoformat(row["observed_at"]) for key, row in sources.items()}
    histories = {}
    for name, (contract, side, entries) in HISTORIES.items():
        assumed = build_updates(contract, side, entries, sources)
        histories[name] = dict(post_clock_assumption=timeline(assumed, contract, side),
                               retrospective_updates=[asdict(row) for row in assumed],
                               at_same_clocks_with_archive_guard=timeline(assumed, contract, side, observations=observations),
                               at_archive_observation_clocks=timeline(
                                   assumed, contract, side, observations=observations,
                                   checkpoints=[observations[entry.source] for entry in assumed],
                               ))

    days = {"oil_april": ("2026-04-22", "2026-04-23"), "oil_may": ("2026-05-27", "2026-05-28", "2026-05-29"),
            "soda_october": ("2026-10-27", "2026-10-28")}
    markets, windows = {}, {}
    for key, (contract, _, _) in HISTORIES.items():
        raw, series = read_pair(session, market, contract, tuple(map(date.fromisoformat, days[key])))
        digests = {f"{p}m": bars_sha(items) for p, items in raw.items()}
        if key == "soda_october":
            for p, items in raw.items():
                if any(bars_sha([bar for bar in items if str(bar.trading_day) == day]) != soda_frozen["market"][f"{p}m"][part]
                       for day, part in zip(days[key], ("afternoon", "night"), strict=True)):
                    raise ValueError("PROTECTION_LINEAGE_SODA_MARKET_CHANGED")
        elif any(digests[p] != handoff["input_ohlc"][key][p]["sha256"] for p in digests):
            raise ValueError("PROTECTION_LINEAGE_OIL_MARKET_CHANGED")
        markets[key] = digests
        windows[key] = series

    def check(key, levels, source, end, signal_side):
        return price_checks(windows[key], tuple(map(Decimal, levels)), start=post_clock(sources[source]),
                            cut=at(end), signal_side=signal_side)

    lock = datetime.fromisoformat(sources["WRozPmaK10"]["published_at"])
    soda_specs = HISTORIES["soda_october"]
    soda_revisions = build_updates(*soda_specs, sources)
    return dict(version="lms405-protection-band-lineage-v1", sources=sources, histories=histories, markets=markets,
                post_clock_scope="CURRENT_ARCHIVE_REPLAY_AT_PUBLICATION_CLOCK_HISTORY_UNVERIFIED",
                archive_clock_scope="ARCHIVE_READINESS_AT_HISTORICAL_CHECKPOINTS_NOT_AUTHOR_KNOWLEDGE",
                assumed_review_pending_supersedes_old_protection_in_study_only=True,
                oil_april_price_checks=dict(
                    distinct_protection=check("oil_april", (9596, 9630), APRIL, "2026-04-22T15:01", "SHORT"),
                    auto_reuse_old_target_sensitivity=check("oil_april", (9643, 9657), APRIL, "2026-04-22T15:01", "SHORT"),
                ),
                oil_may_price_checks=dict(
                    candidate_reuse_of_first_target=check("oil_may", (9739, 9745), MAY_EXCERPT, "2026-05-28T15:01", "SHORT"),
                    auto_reuse_last_completed_target_sensitivity=check("oil_may", (9757, 9792), MAY_EXCERPT, "2026-05-28T15:01", "SHORT"),
                    actual_final_protection_band=None,
                ),
                soda_october_price_checks=dict(
                    active_study_protection_at_lock_report=selected(soda_revisions, SODA, "SHORT", lock),
                    archive_guard_at_lock_report=selected(soda_revisions, SODA, "SHORT", lock, observations=observations),
                    initial_old_band=check("soda_october", (1516, 1529), SODA_OLD, "2026-10-26T21:58", "LONG"),
                    carry_old_during_review_sensitivity=check("soda_october", (1516, 1529), SODA_PENDING, "2026-10-27T10:13", "LONG"),
                    explicit_next_night_band=check("soda_october", (1490, 1501), SODA_NEW, "2026-10-27T22:12", "LONG"),
                    author_protection_band_at_report=None,
                ),
                author_action_samples=0, author_actual_execution=None, executable=False, fills=None, pnl=None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if not args.env_file.is_file() or args.output.exists():
        parser.error("ENV_FILE_MISSING_OR_OUTPUT_EXISTS")
    from dotenv import load_dotenv
    from app.db.readonly import readonly_transaction
    from app.db.session import SessionLocal
    from app.market_data.composition import build_market_data_service
    from app.market_data.market_data_service import MarketDataError
    from sqlalchemy.exc import OperationalError

    load_dotenv(args.env_file, override=False)
    try:
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=60):
            report = study(session, build_market_data_service(session))
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(report))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (OSError, KeyError, ValueError):
        parser.exit(2, "PROTECTION_LINEAGE_EVIDENCE_UNVERIFIED\n")


if __name__ == "__main__":
    main()
