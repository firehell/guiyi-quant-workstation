"""Audit which candidate survives a hypothetical protection-area change and a timed public update."""

import argparse
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from guiyi_quant.lms405.protection_band import ProtectionBandUpdate, active_band, visible_bands
from lms405_plan_driven_replay import MARKET_REQUEST_VERSION, market_request, replay_input
from lms405_portfolio_replay import input_sources
from lms405_protection_lot_timing import verified_json
from lms405_protection_route_comparison import candidate_clocks
from lms405_protection_timeframes import VARIANTS, read_window
from lms405_public_plan_roles import load_source
from lms405_right_side_study import ONE, US, at
from lms405_sh_lock_lifecycle import digest, signals
from lms_near405_replay import encoded

BASE = (Path("output/lms405-protection-external-cases-20261126/final.json"),
        "c1f891277fad085eef5b70d8209ad40204c892d7b38c0d621e79d80bd878a81a")
COAL, OIL = "JM2609", "OI2609"
REPLAY_REFERENCE = (Path("output/lms405-protection-revision-timing-20261126/verified.json"),
                    "37b1429aba6aeb94a321fc073d1cd540e7b974fd4d57dbf9de04e7bc57272e00")
SOY_SOURCE = "S5285902597230444"


def geometry(series, band, *, start, cutoff):
    candidates, contact = candidate_clocks(series, band, start=start, cutoff=cutoff, side="SHORT", compare_wick=True)
    return {k: v for k, v in candidates.items() if k not in ("opening", "contact")}, contact


def scoped_geometry(series, band, *, known_at, cutoff):
    """Exclude contact and shape bars that already started at plan availability."""
    return geometry(series, band, start=known_at + US, cutoff=cutoff)


def active_revision(updates, contract, instant):
    area, reason = active_band(visible_bands(updates, contract, instant), instant, "LONG")
    return dict(revision=area.revision if area else None, status=reason)


def witnesses(series, *, stamp, start, cutoff):
    result = []
    for shape, confirm in VARIANTS:
        by_end = {bar.end: bar for bar in series[shape]}
        for event in signals(series, shape, confirm, side="SHORT", start=start, cut=cutoff):
            if event["available_at"] == stamp:
                bar = by_end[event["shape_end"]]
                result.append(dict(shape_minutes=shape, confirm_minutes=confirm, shape_start=bar.start,
                                   shape_end=bar.end, confirmed_at=event["confirmed_at"], close=event["close"]))
    return result


def switch_scan(series, old, revised, *, cutoff):
    start = series[1][0].start
    historical, contact = geometry(series, old, start=start, cutoff=cutoff)
    revised_day, first_revised_contact = geometry(series, revised, start=start, cutoff=cutoff)
    old_update = ProtectionBandUpdate(COAL, "old", "PROTECTION", start - 2 * US, start - 2 * US,
                                      "TEST_FIXTURE_PRESESSION_OLD", "LONG", *old)
    times = {b.start + offset * US for b in series[1] for offset in (-1, 0)}
    times |= {when + offset * US for when in historical.values() for offset in (-1, 0, 1)}
    rows = []
    for when in sorted(times):
        update = ProtectionBandUpdate(COAL, "revised", "PROTECTION", when, when,
                                      "TEST_FIXTURE_REVISION", "LONG", *revised)
        pending = ProtectionBandUpdate(COAL, "pending", "REVIEW_PENDING", when, when,
                                       "TEST_FIXTURE_AWAITING_REVIEW", "LONG")
        for updates, revision, status in (((old_update, update), "revised", None),
                                          ((old_update, pending), None, "PROTECTION_RANGE_REVIEW_PENDING")):
            if (active_revision(updates, COAL, when) != dict(revision="old", status=None)
                    or active_revision(updates, COAL, when + US) != dict(revision=revision, status=status)):
                raise ValueError("REVISION_SCOPE_CAUSALITY_CHANGED")
        # Historical candidates remain in the log; the revised plan cannot inherit their permission.
        previous = {key: stamp for key, stamp in historical.items() if stamp < when}
        new, first_contact = scoped_geometry(series, revised, known_at=when, cutoff=cutoff)
        rows.append(dict(change_time=when, before_change=previous, after_change=new,
                         new_contact_end=first_contact.end if first_contact else None))
    return dict(
        old_day_candidates=historical, old_day_first_contact=contact.end if contact else None,
        revised_priors_only_sensitivity=revised_day,
        revised_priors_first_contact=first_revised_contact.end if first_revised_contact else None,
        timeline=rows, actual_revision_at=None, actual_band_publication_at=None, actual_action_at=None,
        revision_clock_scope="HYPOTHETICAL_MINUTE_BOUNDARIES_AND_OLD_SIGNAL_CLOCK",
        ordinary_geometry=witnesses(series, stamp=revised_day["ordinary"], start=start, cutoff=cutoff)
        if "ordinary" in revised_day else [],
        old_permission_after_revision="REQUIRES_FRESH_CONFIRMATION_SCOPED_TO_REVISED_BAND",
    )


def public_update_control(series, *, published):
    band = (Decimal(9596), Decimal(9630))
    cutoff = series[1][-1].end + 2 * US
    display_minute = published.replace(second=0, microsecond=0)
    minute_visible = display_minute + ONE
    start = series[1][0].start
    if not start < minute_visible < cutoff:
        raise ValueError("REVISION_PUBLIC_CONTROL_WINDOW_CHANGED")
    before, _ = geometry(series, band, start=start, cutoff=display_minute)
    all_day, _ = geometry(series, band, start=start, cutoff=cutoff)
    after, contact = scoped_geometry(series, band, known_at=minute_visible, cutoff=cutoff)
    return dict(band=band, public_display_minute=display_minute,
                conservative_known_at=minute_visible, retrospective_before_display_minute=before,
                retrospective_all_day=all_day, scoped_after_publication=after,
                scoped_first_contact_end=contact.end if contact else None, author_execution=None)


def study(session, market):
    frozen = verified_json(*BASE)["cases"]
    old, revised = (frozen[key] for key in ("coal_previous_reference", "coal_advanced_reference"))
    sources = input_sources()
    coal_source = load_source(sources, "S5290900347693045")
    if coal_source != old["source"] or old["source"] != revised["source"]:
        raise ValueError("REVISION_COAL_SOURCE_CHANGED")
    series = read_window(session, market, COAL, date(2026, 4, 23))
    if {f"{period}m": dict(count=len(bars), sha256=digest(bars)) for period, bars in series.items()} != old["market"]:
        raise ValueError("REVISION_COAL_MARKET_CHANGED")
    bands = [tuple(map(Decimal, reference["band"])) for reference in (old, revised)]
    scan = switch_scan(series, *bands, cutoff=datetime.fromisoformat(old["observation_cutoff"]))
    if scan["old_day_candidates"].get("precontact") != datetime.fromisoformat(old["geometry"]["advance"]) or (
        scan["revised_priors_only_sensitivity"].get("ordinary") != datetime.fromisoformat(revised["geometry"]["ordinary"])
    ):
        raise ValueError("REVISION_FROZEN_CLOCKS_CHANGED")
    oil_source = load_source(sources, "S5290447639678222")
    oil_series = read_window(session, market, OIL, date(2026, 4, 22))
    control = public_update_control(oil_series, published=datetime.fromisoformat(oil_source["published_at"]))
    return dict(version="lms405-protection-revision-timing-v1", frozen_cross_date_sha256=BASE[1],
                coal=scan | dict(source=coal_source, old_band=bands[0], revised_band=bands[1]),
                oil=control | dict(source=oil_source, market={f"{p}m": digest(b) for p, b in oil_series.items()}),
                earlier_jm_plan=None, earlier_jm_plan_version_verified=False,
                author_action_samples=0, author_match_rate=None, executable=False, fills=None, pnl=None)


def approval_evaluation(compiled):
    """Create one explicitly synthetic approval after the scoped candidate is visible."""
    evaluation, = compiled["tape"]["evaluations"]
    report, = compiled["replay"]["events"]
    scope = report["pending_approval_scope"]
    shown = datetime.fromisoformat(evaluation["at"])
    approval = dict(scope=scope, id=f"TEST_FIXTURE:{scope}", accepted=True, decided_at=shown.isoformat(),
                    known_at=(shown + US).isoformat(), record_kind="TEST_FIXTURE")
    return evaluation | dict(at=(shown + 2 * US).isoformat(), approval=approval)


def compile_coal_revision(session, market, reference):
    source = load_source(input_sources(), "S5290900347693045")
    close = at("2026-04-23T15:00") + 2 * US
    start = at("2026-04-22T21:00")
    if source != reference["source"] or datetime.fromisoformat(source["published_at"]) <= close:
        raise ValueError("REVISION_RETROSPECTIVE_SOURCE_IDENTITY_CHANGED")
    seed = dict(contract=COAL, episode="JM2609:2026-04-23:HYPOTHETICAL_LONG_UNIT", direction="LONG",
                known_at=(start - 2 * US).isoformat(), original="1", protection="0", counter_m="0", attempt=1)
    request_base = dict(session=session, market=market, version=MARKET_REQUEST_VERSION, seed=seed,
                        trading_day="2026-04-23", start=start.isoformat(), cutoff=close.isoformat(),
                        request_expires_at=close.isoformat(), quantity="1", sequence_window=True)

    def revision(identity, clock, operation):
        return dict(contract=COAL, id=identity, source=f"TEST_FIXTURE:JM2609_PROTECTION:{identity}",
                    published_at=clock.isoformat(), known_at=clock.isoformat(), operations=[operation])

    old = market_request(**request_base, shape_period=15, confirmation_period=15, band=reference["old_band"],
                         operation="PROTECT_EARLY", revision=revision("OLD", start - US, "PROTECT_EARLY"))
    if old["candidate"] is None or old["candidate"]["available_at"] != datetime.fromisoformat(
        reference["old_day_candidates"]["precontact"],
    ):
        raise ValueError("REVISION_OLD_FIXTURE_CANDIDATE_CHANGED")
    checked_market = verified_json(*BASE)["cases"]["coal_previous_reference"]["market"]
    if old["market_digests"] != {period: row["sha256"] for period, row in checked_market.items()}:
        raise ValueError("REVISION_COAL_MARKET_CHANGED")
    old_review = approval_evaluation(old)
    approval_clock = datetime.fromisoformat(old_review["at"])
    result = {}
    for offset, name, expected in (
        (-1, "VISIBLE_BEFORE_OLD_APPROVAL_EVALUATION", ("PLAN_SUPERSEDED", "CONDITIONAL_ACTION")),
        (0, "SAME_CLOCK_AS_OLD_APPROVAL_EVALUATION", ("CONDITIONAL_ACTION", "POSITION_UNAVAILABLE_OR_SUPERSEDED")),
        (1, "VISIBLE_AFTER_OLD_APPROVAL_EVALUATION", ("CONDITIONAL_ACTION", "POSITION_UNAVAILABLE_OR_SUPERSEDED")),
    ):
        revision_at = approval_clock + offset * US
        new = market_request(**request_base, shape_period=1, confirmation_period=1,
                             band=reference["revised_band"], operation="PROTECT_REGULAR",
                             revision=revision("ADVANCED", revision_at, "PROTECT_REGULAR"))
        if new["candidate"] is None or new["candidate"]["available_at"] != datetime.fromisoformat(
            reference["revised_priors_only_sensitivity"]["ordinary"],
        ):
            raise ValueError("REVISION_ADVANCED_FIXTURE_CANDIDATE_CHANGED")
        new_review = approval_evaluation(new)
        tape = old["tape"] | dict(revisions=old["tape"]["revisions"] + new["tape"]["revisions"])
        initial = old["tape"]["evaluations"] + new["tape"]["evaluations"]
        unsigned = replay_input(**(tape | dict(evaluations=initial)))
        approved = replay_input(**(tape | dict(evaluations=[*initial, old_review, new_review])), allow_test_fixture=True)
        acted = tuple(row for row in approved["events"] if row["approval"] is not None)
        if (tuple(row["status"] for row in acted) != expected or unsigned["final"]["protection"]
                or approved["final"]["original"] != 1 or approved["final"]["protection"] != 1):
            raise ValueError("REVISION_FIXTURE_LIFECYCLE_CHANGED")
        result[name] = dict(revision_known_at=revision_at, candidate=new["candidate"], unsigned=unsigned, approved=approved)
    return dict(contract=COAL, retrospective_source=source, historical_plan_known_at=None, old_candidate=old["candidate"],
                market_digests=old["market_digests"], handoffs=result)


def soy_public_control(session, market):
    source = load_source(input_sources(), SOY_SOURCE)
    published = datetime.fromisoformat(source["published_at"])
    if published != at("2026-04-09T21:20"):
        raise ValueError("REVISION_SOY_SOURCE_TIME_CHANGED")
    series = read_window(session, market, "A2605", date(2026, 4, 10))
    start = series[1][0].start
    cutoff = series[1][-1].end + 2 * US
    known_at = published + ONE
    band = Decimal(4795), Decimal(4803)
    full, _ = geometry(series, band, start=start, cutoff=cutoff)
    scoped, touch = scoped_geometry(series, band, known_at=known_at, cutoff=cutoff)
    scopes = {name: dict(geometry=result, first=witnesses(
        series, stamp=result["precontact"], start=from_time, cutoff=cutoff,
    ) if "precontact" in result else []) for name, result, from_time in (
        ("whole_session_retrospective", full, start), ("strictly_after_publication", scoped, known_at + US),
    )}
    return dict(contract="A2605", source=source, author_version=None, conservative_known_at=known_at, band=band,
                first_scoped_touch=touch.end if touch else None, market={f"{p}m": digest(b) for p, b in series.items()},
                scopes=scopes, author_signal=None, author_action=None)


def handoff_study(session, market):
    frozen = verified_json(*REPLAY_REFERENCE)
    return dict(version="lms405-protection-revision-handoff-v1", reference_sha256=REPLAY_REFERENCE[1],
                coal=compile_coal_revision(session, market, frozen["coal"]), soy=soy_public_control(session, market),
                author_action_samples=0, author_match_rate=None, executable=False, fills=None, pnl=None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--compile-handoff", action="store_true")
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
            calculate = handoff_study if args.compile_handoff else study
            result = calculate(session, build_market_data_service(session))
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(result))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (KeyError, ValueError, OSError) as exc:
        code = str(exc)
        parser.exit(2, (code if code.isidentifier() and code.startswith("REVISION_")
                        else "REVISION_EVIDENCE_UNVERIFIED") + "\n")


if __name__ == "__main__":
    main()
