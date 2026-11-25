"""Exercise the scoped near-edge recovery path on frozen author research cases."""

import argparse
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from guiyi_quant.lms405 import Position, Zone
from guiyi_quant.lms405.handoff import Handoff, HandoffConfirmation
from guiyi_quant.lms405.near_recovery import EXPLICIT_NEAR, MINUTE, US, NearRecoveryCase, assess_near_recovery
from guiyi_quant.lms405.public_conditions import Condition
from lms405_protection_lot_timing import verified_json
from lms405_protection_timeframes import read_window
from lms405_right_side_study import at
from lms405_sh_lock_lifecycle import digest
from lms_near405_replay import encoded, sha

REFERENCES = {
    "jm": ("lms405-jm1072-clock-20261126/final.json", "a213015e8f18111dfc2dbc140945855fc9f1c5f047d242107bdad8f08e4b900b"),
    "pvc": ("lms405-pvc-recovery-carry-20261126/reviewed.json", "ec0692372f241cd7a58cd57425954da32beb7ac3771ecbde3ab109ece6d22a2b"),
    "portfolio": ("lms405-portfolio-recovery-progress-20261126/reviewed.json",
                  "6fac4799b05119d385265eb47e043f5513133025db63f471de9be43a1fe31ed7"),
}


def market_for(session, market, contract, day, reference, *, end_only=False):
    series = read_window(session, market, contract, day)
    if end_only:
        hashes = {f"{p}m": dict(count=len(bars), sha256=digest(bars)) for p, bars in series.items()}
    else:
        hashes = {f"{p}m": dict(count=len(bars), sha256=sha(encoded([
            (b.start, b.end, b.open, b.high, b.low, b.close) for b in bars
        ]).encode())) for p, bars in series.items()}
    if hashes != reference:
        raise ValueError("EXPLICIT_NEAR_MARKET_CHANGED")
    return series


def bars_for(series, event, variant, *, start, band, side):
    shape_period, confirm_period = variant
    shape_end, confirm_end = (datetime.fromisoformat(event[key]) for key in ("shape_end", "confirmed_at"))
    shape = next(b for b in series[shape_period] if b.end == shape_end)
    confirm = next(b for b in series[confirm_period] if b.end == confirm_end)
    near = band[0] if side == "LONG" else band[1]
    broke = next((bar for bar in series[1] if bar.start >= start and bar.end + US < shape.start
                  and (bar.close > near if side == "LONG" else bar.close < near)), None)
    if confirm.close != Decimal(event["close"]):
        raise ValueError("EXPLICIT_NEAR_CONFIRMATION_CHANGED")
    return broke, shape, confirm


def make_case(contract, side, band, role, *, source, plan_at, seed_at, bars, version=None):
    plan_id = f"{contract}:near:{source}"
    seed = Handoff("RESUME_ORIGINAL", Position(contract, Decimal(1), Decimal(1)), side,
                   plan_id, f"{contract}:hypothetical-cycle", None, seed_at, seed_at)
    return NearRecoveryCase(seed, Zone(plan_id, contract, *band, plan_at, source), role, *bars, version)


def fixture(case):
    seed = case.request

    def fact(name, observed, known):
        return Condition(name, seed.scope, seed.before.contract, True, observed, known, "TEST_FIXTURE", "EVENT_TIME")

    signal_at = case.confirmation.end
    known = signal_at + US
    terms = (fact("POSITION_PATH_CONFIRMED", seed.position_since, seed.position_known_at),
             fact("ORIGINAL_PLAN_VALID", seed.position_since, seed.position_known_at), fact("SIGNAL", signal_at, known))
    decide = known + US
    approval = HandoffConfirmation(case.approval_scope, f"{case.policy_source}:TEST_FIXTURE", True, decide, decide,
                                   "TEST_FIXTURE")
    params = dict(approval=approval, allow_test_fixture=True)
    return dict(approval=approval.id, with_approval=assess_near_recovery(case, terms, as_of=decide + US, **params),
                at_approval_clock=assess_near_recovery(case, terms, as_of=decide, **params),
                without_approval=assess_near_recovery(case, terms, as_of=decide + US),
                without_external_facts=assess_near_recovery(case, (), as_of=decide + US, **params))


def jm_case(session, market, ref):
    contract, day = ref["contract"], date.fromisoformat(ref["trading_day"])
    series = market_for(session, market, contract, day, ref["market"], end_only=True)
    morning = ref["windows"]["morning"]["edges"]["near_1072"]["context"]
    event = next(row for row in morning if row["variant"] == "5m_to_1m")
    if datetime.fromisoformat(event["confirmed_at"]) != at("2025-11-27T09:16"):
        raise ValueError("EXPLICIT_NEAR_JM_CASE_CHANGED")
    band = (Decimal(1061), Decimal(1072))
    bars = bars_for(series, event, (5, 1), start=at("2025-11-27T09:00"), band=band, side="SHORT")
    seed_at = at("2025-11-27T08:58")  # Unit fixture. It is not an author position observation.
    known = datetime.fromisoformat(ref["later_article_entry"]) + MINUTE
    public = make_case(contract, "SHORT", band, EXPLICIT_NEAR, source="N03_ARCHIVED_ARTICLE_ENTRY",
                       plan_at=known, seed_at=seed_at, bars=bars)
    reproduced = make_case(contract, "SHORT", band, EXPLICIT_NEAR, source="TEST_FIXTURE_JM_NEAR_PLAN",
                           plan_at=at("2025-11-27T08:57"), seed_at=seed_at, bars=bars, version=True)
    return dict(position_preimage="HYPOTHETICAL_UNIT_LOCK_NOT_AUTHOR_OBSERVATION",
                public_at_noon=assess_near_recovery(public, (), as_of=at("2025-11-27T11:34")),
                public_after_late_article=assess_near_recovery(public, (), as_of=known + US),
                hypothetical_unit_case=fixture(reproduced), shape_at=event["shape_end"],
                confirmed_at=event["confirmed_at"], quoted_article_entry=ref["later_article_entry"], author_action_at=None)


def reject_wrong_roles(session, market, contract, day, band, side, events, source, market_hashes,
                       *, start, plan_at, role):
    if not events:
        return []
    series = market_for(session, market, contract, day, market_hashes)
    results = []
    for event in events:
        pair = (event["shape_minutes"], event["confirm_minutes"])
        bars = bars_for(series, event, pair, start=start, band=band, side=side)
        case = make_case(contract, side, band, role, source=source, plan_at=plan_at, seed_at=start - US, bars=bars)
        as_of = max(case.evidence_known_at, case.confirmation.end + US) + US
        report = assess_near_recovery(case, (), as_of=as_of)
        if report["after"] is not None or report["checks"]["explicit_near_role"] is not False:
            raise ValueError("EXPLICIT_NEAR_WRONG_ROLE_ADMITTED")
        results.append(dict(confirmed_at=event["confirmed_at"], result=report))
    return results


def study(session, market):
    refs = {key: verified_json(Path("output") / path, fingerprint) for key, (path, fingerprint) in REFERENCES.items()}
    jm = jm_case(session, market, refs["jm"])
    if (jm["public_at_noon"]["after"] is not None or jm["public_after_late_article"]["after"] is not None
            or any(value is not None for value in jm["public_at_noon"]["checks"].values())
            or jm["hypothetical_unit_case"]["with_approval"]["after"] != {"long": "0", "short": "1"}
            or jm["hypothetical_unit_case"]["at_approval_clock"]["after"] is not None
            or jm["hypothetical_unit_case"]["without_approval"]["after"] is not None
            or jm["hypothetical_unit_case"]["without_external_facts"]["after"] is not None):
        raise ValueError("EXPLICIT_NEAR_JM_SCOPE_CHANGED")
    pvc = refs["pvc"]["days"]["2026-04-27"]
    pvc_report = reject_wrong_roles(session, market, "V2609", date(2026, 4, 27),
                                    (Decimal(5226), Decimal(5262)), "LONG", pvc["candidates"], "PVC_STRONG_TARGET",
                                    pvc["market"], start=at("2026-04-27T09:00"),
                                    plan_at=at("2026-04-27T16:57"), role="STRONG_TARGET")
    portfolio = {}
    for contract, row in refs["portfolio"]["portfolio"].items():
        diagnostic = row["price_diagnostic"]
        if diagnostic is None:
            portfolio[contract] = dict(status="NO_EVALUABLE_BAND", assessed=[])
            continue
        events = [event for event in diagnostic["events"] if event["conditions"]["near_geometry"]]
        plan_at = datetime.fromisoformat(row["source_minute_end"])
        start = at("2026-10-27T11:35") if contract == "SH2701" else at("2026-10-26T21:00")
        assessed = reject_wrong_roles(session, market, contract, date(2026, 10, 27),
                                      tuple(map(Decimal, row["band"])), row["side_scenario"], events,
                                      row["sources"][0]["source_url"], row["market"], start=start,
                                      plan_at=plan_at, role=row["role"])
        portfolio[contract] = dict(status="CHECKED_PRICE_CONTEXT_ONLY", assessed=assessed)
    return dict(version="lms405-explicit-near-recovery-study-v1", jm=jm, pvc_known_unreleased=pvc_report,
                portfolio=portfolio, reference_hashes={key: sha for key, (_, sha) in REFERENCES.items()},
                author_action_samples=0, author_match_rate=None, executable=False, fills=None, pnl=None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
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
            result = study(session, build_market_data_service(session))
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(result))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (KeyError, ValueError, OSError, StopIteration) as exc:
        code = str(exc)
        parser.exit(2, (code if code.isidentifier() and code.startswith("EXPLICIT_NEAR_")
                        else "EXPLICIT_NEAR_EVIDENCE_UNVERIFIED") + "\n")


if __name__ == "__main__":
    main()
