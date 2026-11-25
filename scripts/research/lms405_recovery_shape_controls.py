"""Apply frozen recovery clocks to author-reported controls and reference cases."""

import argparse
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from lms405_explicit_near_recovery import REFERENCES, market_for
from lms405_jm_recovery_boundaries import read_sources
from lms405_jm1072_public_clock import EDGE, FAR, NOON_POST, OPEN
from lms405_portfolio_recovery_shape_lifetime import compare
from lms405_portfolio_replay import input_sources
from lms405_protection_lot_timing import verified_json
from lms405_protection_timeframes import read_window
from lms405_public_plan_roles import load_source
from lms405_pvc_recovery_carry import BAND
from lms405_recovery_confirmation_audit import examine
from lms405_right_side_study import ONE, US, at
from lms405_sh2609_recovery_context import PRIOR_BAND
from lms405_sh_lock_lifecycle import digest
from lms_near405_replay import encoded, sha

PVC = ("lms405-pvc-recovery-carry-20261126/reviewed.json",
       "ec0692372f241cd7a58cd57425954da32beb7ac3771ecbde3ab109ece6d22a2b")
SH = ("lms405-sh2609-recovery-context-20261126/checked-a.json",
      "db27de0b4ca6f419f4ef8f2fbd197a40b79572bfa12034d6a8c0f38356ce2432")
RU = ("lms405-public-plan-roles-20261125/verified.json",
      "1d6f21d11b8dc9520f98e157a76f6195b6952c90c0ccad65da1fe603ac575b2c")
CASES = (
    ("V2609", "2026-04-27", "S5292358960155373", "LONG", BAND, "NO_LONG_UNLOCK_REPORTED", True),
    ("V2609", "2026-04-28", "S5292720017903146", "LONG", BAND, "TARGETS_COMPLETE_ACTION_UNKNOWN", None),
    ("SH2609", "2026-07-27", "S5325329692361179", "SHORT", PRIOR_BAND, "ORIGINAL_SHORT_NOT_PERMITTED", None),
    ("SH2609", "2026-07-28", "S5325700674619111", "SHORT", PRIOR_BAND, "PRIOR_BAND_VALIDITY_UNKNOWN", None),
)


def verify_market(series, contract, day, pvc, sh):
    if contract == "V2609":
        actual = {f"{p}m": dict(count=len(rows), sha256=sha(encoded([
            (bar.start, bar.end, bar.open, bar.high, bar.low, bar.close) for bar in rows
        ]).encode())) for p, rows in series.items()}
        expected = pvc["days"][day]["market"]
    else:
        actual = {f"{p}m": digest(rows) for p, rows in series.items()}
        expected = sh["cases"][day]["market"]
    if actual != expected:
        raise ValueError("RECOVERY_CONTROL_MARKET_CHANGED")
    return actual


def price_comparison(series, start, cutoff, side, **levels):
    return {role: dict(edge=edge, comparison=compare(series, start, cutoff, side=side, edge=edge))
            for role, edge in levels.items()}


def reference_cases(session, market, index):
    jm_path, jm_hash = REFERENCES["jm"]
    jm = verified_json(Path("output") / jm_path, jm_hash)
    jm_contract, jm_day = jm["contract"], date.fromisoformat(jm["trading_day"])
    jm_series = market_for(session, market, jm_contract, jm_day, jm["market"], end_only=True)
    jm_sources = read_sources()
    article_at = datetime.fromisoformat(jm["later_article_entry"])
    if (any(jm_sources[key] != source for key, source in jm["sources"].items())
            or not OPEN < NOON_POST < article_at):
        raise ValueError("RECOVERY_CONTROL_JM_SOURCE_CHANGED")

    ru = verified_json(Path("output") / RU[0], RU[1])["cases"]["G63272-537"]
    ru_source = load_source(index, "G63272-537")
    if ru["source"] != ru_source:
        raise ValueError("RECOVERY_CONTROL_RU_SOURCE_CHANGED")
    ru_published = datetime.fromisoformat(ru_source["published_at"])
    ru_day = date.fromisoformat(ru["trading_day"])
    ru_series = read_window(session, market, ru["contract"], ru_day)
    ru_windows = {}
    for name, snapshot in ru["role_windows"].items():
        start, cutoff = (datetime.fromisoformat(snapshot[field]) for field in ("start", "cutoff_exclusive"))
        post_publication = name == "later_recovery_reference"
        if (post_publication and start != ru_published + ONE) or (not post_publication and cutoff != ru_published):
            raise ValueError("RECOVERY_CONTROL_RU_PUBLICATION_CUTOFF_CHANGED")
        progress = snapshot["minute_price_progress"]
        band = (Decimal(progress["near"]), Decimal(progress["far"]))
        market_check = examine(ru_series, start=start, cut=cutoff, side="LONG", band=band)
        if encoded(market_check) != encoded(snapshot):
            raise ValueError("RECOVERY_CONTROL_RU_MARKET_OR_WINDOW_CHANGED")
        ru_windows[name] = dict(
            start=start, cutoff_exclusive=cutoff,
            timeframe="POST_PUBLICATION" if post_publication else "RETROSPECTIVE",
            price_role="STRONG_TARGET" if name == "morning_strong_target" else "RECOVERY_REFERENCE",
            edges=price_comparison(ru_series, start, cutoff, "LONG", near=band[0], far=band[1]),
        )
    return dict(
        coking_coal=dict(contract=jm_contract, trading_day=jm_day, start=OPEN, cutoff_exclusive=NOON_POST,
                         sources=jm["sources"], source_report_sha256=jm_hash, market=jm["market"],
                         later_reference_article_entry_at=article_at, author_statement="NOON_UNLOCK_REPORTED",
                         edges=price_comparison(jm_series, OPEN, NOON_POST, "SHORT", near=EDGE, far=FAR),
                         timeframe="RETROSPECTIVE", author_action_at=None, verified_as_of_plan=None,
                         research_permission=None, version_405=None),
        rubber=dict(contract=ru["contract"], trading_day=ru_day, source=ru_source, source_report_sha256=RU[1],
                    market=ru["role_windows"]["morning_recovery_reference"]["market"], windows=ru_windows,
                    version_405=None, verified_as_of_plan=None, research_permission=None,
                    author_statement="RECOVERY_REFERENCE_DISCLOSED_ACTION_UNKNOWN", author_action_at=None),
    )


def report(session, market, *, include_reference_cases=False):
    pvc, sh = (verified_json(Path("output") / path, digest_) for path, digest_ in (PVC, SH))
    index, cases = input_sources(), {}
    for contract, day, source_id, side, band, statement, version_405 in CASES:
        source = load_source(index, source_id)
        frozen = pvc["sources"][source_id] if contract == "V2609" else sh["cases"][day]["source"]
        series = read_window(session, market, contract, date.fromisoformat(day))
        start, close = series[1][0].start, at(f"{day}T15:00")
        cutoff = close + 2 * US
        if source != frozen or datetime.fromisoformat(source["published_at"]) <= cutoff:
            raise ValueError("RECOVERY_CONTROL_SOURCE_SCOPE_CHANGED")
        if series[1][-1].end != close:
            raise ValueError("RECOVERY_CONTROL_INCOMPLETE_DAY")
        near, far = band if side == "LONG" else band[::-1]
        cases[contract + ":" + day] = dict(
            contract=contract, trading_day=day, side=side, start=start, cutoff_exclusive=cutoff,
            source_id=source_id, source=source, version_405=version_405, author_statement=statement,
            market=verify_market(series, contract, day, pvc, sh),
            price_range=(min(b.low for b in series[1]), max(b.high for b in series[1])),
            edges=price_comparison(series, start, cutoff, side, near=near, far=far),
            verified_as_of_plan=None, research_permission=None, author_action_at=None, projected_position=None,
        )
    result = dict(version="lms405-recovery-shape-controls-v1", cases=cases, retrospective=True,
                  source_report_hashes={PVC[0]: PVC[1], SH[0]: SH[1]}, author_action_samples=0,
                  author_match_rate=None, executable=False, fills=None, pnl=None)
    if include_reference_cases:
        result.update(version="lms405-recovery-shape-controls-v2", references=reference_cases(session, market, index))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--include-reference-cases", action="store_true")
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
            result = report(session, build_market_data_service(session),
                            include_reference_cases=args.include_reference_cases)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(result))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (KeyError, OSError, ValueError) as exc:
        code = str(exc)
        parser.exit(2, (code if code.isidentifier() and code.startswith("RECOVERY_CONTROL_")
                        else "RECOVERY_CONTROL_INPUT_UNVERIFIED") + "\n")


if __name__ == "__main__":
    main()
