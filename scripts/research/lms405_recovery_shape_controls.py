"""Apply the frozen recovery clocks to the PVC and caustic soda controls."""

import argparse
from datetime import date, datetime
from pathlib import Path

from lms405_portfolio_recovery_shape_lifetime import compare
from lms405_portfolio_replay import input_sources
from lms405_protection_lot_timing import verified_json
from lms405_protection_timeframes import read_window
from lms405_public_plan_roles import load_source
from lms405_pvc_recovery_carry import BAND
from lms405_right_side_study import US, at
from lms405_sh2609_recovery_context import PRIOR_BAND
from lms405_sh_lock_lifecycle import digest
from lms_near405_replay import encoded, sha

PVC = ("lms405-pvc-recovery-carry-20261126/reviewed.json",
       "ec0692372f241cd7a58cd57425954da32beb7ac3771ecbde3ab109ece6d22a2b")
SH = ("lms405-sh2609-recovery-context-20261126/checked-a.json",
      "db27de0b4ca6f419f4ef8f2fbd197a40b79572bfa12034d6a8c0f38356ce2432")
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


def report(session, market):
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
            edges={role: dict(edge=edge, comparison=compare(series, start, cutoff, side=side, edge=edge))
                   for role, edge in (("near", near), ("far", far))},
            verified_as_of_plan=None, research_permission=None, author_action_at=None, projected_position=None,
        )
    return dict(version="lms405-recovery-shape-controls-v1", cases=cases, retrospective=True,
                source_report_hashes={PVC[0]: PVC[1], SH[0]: SH[1]}, author_action_samples=0,
                author_match_rate=None, executable=False, fills=None, pnl=None)


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
            result = report(session, build_market_data_service(session))
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
