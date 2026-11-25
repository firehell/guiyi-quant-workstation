"""Compare two completed-price paths for a separate short-term M permission."""

import argparse
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from guiyi_quant.lms405 import Bar
from lms405_counter_m_study import beyond
from lms405_locked_exit_audit import verify_aggregation
from lms405_oi_m_band_study import market_digest
from lms405_protection_timeframes import geometry_events
from lms405_replay import ohlc, read_session_series
from lms405_right_side_study import FIVE, ONE, US, at
from lms405_volatility_context import bars_sha
from lms_near405_replay import encoded, sha

REFERENCES = {
    "jm": ("lms-fg-sa-oct-20261125/jm-m-difficulty-final.json",
           "dfa88fa6f5aa8bece55854e7be47be9e08de55a8ba63e0f3d58ac99d76d043dd"),
    "oi": ("lms-oi2609-june-20261124/m-band-study.json",
           "14853b64b17f8dbbd1f2fc624cd701fdd06d42258b5b7b0da5b7e0338ba387ca"),
    "ru": ("lms405-counter-m-ru-20261125/report.json",
           "a8c97015d4184caa35ec160c424245192518448f7e1ce3075627a20b83e1ef2d"),
}
PVC_INPUTS = {
    "1m": "5ae5ae342f164bf9fd3caf79f1a59ce8181d606ee85b9b8f52e5dfa47cd84654",
    "5m": "9e8fada6d7c8f155e5f83447ec4c8c8d7b80b324ab434887f510af56d998faa8",
}


def completed_paths(minutes, level, side):
    """Track the first break and the currently unbroken run at each minute close."""
    first, active, previous_end = None, None, None
    states = {}
    for bar in minutes:
        directional_close = beyond(bar.close, level, side)
        if bar.start != previous_end or not directional_close:
            active = None
        if active is None and directional_close:
            active = bar.end
        if first is None:
            first = active
        states[bar.end] = (first, active)
        previous_end = bar.end
    return states


def compare_paths(series, *, start, cutoff, side, level, band=None):
    minutes = [b for b in series[1] if b.start >= start and b.end + US < cutoff]
    if not minutes:
        raise ValueError("M_PERMISSION_WINDOW_EMPTY")
    paths = completed_paths(minutes, level, side)
    results = {}
    for confirm in (1, 5):
        events = geometry_events(series, 5, confirm, start=start, as_of=cutoff, side=side)
        classified = []
        for row in events:
            first, active = paths[row["confirmed_at"]]
            shape_start = row["shape_end"] - FIVE
            after_first = first is not None and first + US < shape_start
            after_active = active is not None and active + US < shape_start
            classified.append(row | dict(
                first_break_at=first, current_unbroken_run_at=active,
                after_first_break=after_first, after_current_unbroken_run=after_active,
                confirmation_still_beyond=beyond(row["close"], level, side),
                confirmation_inside_m_band=band[0] <= row["close"] <= band[1] if band else None,
            ))
        results[f"5m_to_{confirm}m"] = classified
    return dict(side=side, start=start, cutoff_exclusive=cutoff, level=level, m_band=band,
                minute_count=len(minutes), first_break_at=paths[minutes[-1].end][0], events=results)


def evidence_inputs(root):
    result = {}
    for key, (name, digest) in REFERENCES.items():
        payload = (root / name).read_bytes()
        if sha(payload) != digest:
            raise ValueError("M_PERMISSION_REFERENCE_CHANGED")
        result[key] = json.loads(payload)
    return result


def read_pair(session, market, contract, days):
    raw = {period: read_session_series(session, market, contract[:-4].lower(), contract, f"{period}m", step, days)
           for period, step in ((1, ONE), (5, FIVE))}
    bars = {period: [Bar(contract, b.bar_end, *ohlc(b), start=b.bar_end - step) for b in raw[period]]
            for period, step in ((1, ONE), (5, FIVE))}
    verify_aggregation(bars[5], raw[1])
    return raw, bars


def window(bars, start, cutoff, side, levels, band=None):
    return {name: compare_paths(bars, start=at(start), cutoff=at(cutoff), side=side,
                                level=Decimal(level), band=band) for name, level in levels.items()}


def study(session, market, references):
    cases, inputs = {}, {}
    for key, day, role in (
        ("jm_skip", "2026-09-09", "SKIP_REPORTED"),
        ("jm_trial", "2026-10-23", "TRIAL_REPORTED"),
    ):
        raw, bars = read_pair(session, market, "JM2701", (date.fromisoformat(day),))
        ref = references["jm"]["cases"][day]
        digest = bars_sha(raw[1])
        if digest != ref["minute_sha256"]:
            raise ValueError("M_PERMISSION_JM_MARKET_CHANGED")
        inputs[key] = dict(minute_sha256=digest, five_sha256=bars_sha(raw[5]), minute_count=len(raw[1]),
                           five_count=len(raw[5]))
        side = ref["retrospective_bands"]["side"]
        band = tuple(map(Decimal, ref["retrospective_bands"]["m"]))
        levels = {"m_near": band[0] if side == "LONG" else band[1]}
        if key == "jm_trial":
            levels["interruption_far"] = "1397.5"
        cases[key] = dict(
            contract="JM2701", source_ids=[references["jm"]["author_case_scope"][day]["source"]],
            public_opportunity=role, author_signal_at=None,
            band_scope="RETROSPECTIVE_ONLY" if key == "jm_skip" else "OLDER_CURRENT_TEXT_EDIT_HISTORY_UNKNOWN",
            diagnostic=window(bars, f"{day}T09:00", f"{day}T15:01", side, levels, band),
        )

    from lms405_oi_m_band_study import DAYS, PRIOR_LOW, PROTECTION, WINDOWS

    raw, bars = read_pair(session, market, "OI2609", DAYS)
    inputs["oi"] = {f"{period}m": market_digest(values) for period, values in raw.items()}
    if inputs["oi"] != references["oi"]["input_ohlc_sha256"]:
        raise ValueError("M_PERMISSION_OI_MARKET_CHANGED")
    for tag, _, start, cutoff in WINDOWS[:3]:
        scope = "BEFORE_CURRENT_PROTECTION_PUBLICATION" if tag == "june4_day" else "KNOWN_PRICE_PROXY_NOT_AUTHOR_M"
        levels = {"protection_lower": PROTECTION[0]}
        if tag != "june4_day":
            levels["prior_trading_day_low"] = PRIOR_LOW
        cases[tag] = dict(
            contract="OI2609", source_ids=list(references["oi"]["source_evidence"]),
            public_opportunity={"june4_day": "LOCK_REPORTED_AFTER_SESSION",
                                "june5_night": "AUTHOR_M_PARTICIPATION_UNKNOWN",
                                "june5_before_morning_post": "COUNTER_M_REPORTED_LATER_EXACT_TIME_UNKNOWN"}[tag],
            band_scope=scope, author_signal_at=None,
            diagnostic=window(bars, start.isoformat(), cutoff.isoformat(), "SHORT", levels),
        )

    ref = references["ru"]["cases"]["ru2701_day"]
    raw, bars = read_pair(session, market, "RU2701", (date(2026, 10, 28),))
    inputs["ru"] = {f"{period}m": dict(count=len(rows), ohlc_sha256=bars_sha(rows)) for period, rows in raw.items()}
    if inputs["ru"] != ref["series"]:
        raise ValueError("M_PERMISSION_RU_MARKET_CHANGED")
    cases["ru_optional"] = dict(
        contract="RU2701", source_ids=ref["source_ids"], author_signal_at=None,
        public_opportunity="M_CONTEXT_REPORTED_PARTICIPATION_UNKNOWN", band_scope="OLDER_CURRENT_TEXT_EDIT_HISTORY_UNKNOWN",
        diagnostic=window(bars, *ref["window"], "LONG", {"m_near": "19515", "m_far": "19610"},
                          (Decimal("19515"), Decimal("19610"))),
    )
    raw, bars = read_pair(session, market, "V2609", (date(2026, 6, 17),))
    inputs["v"] = {f"{period}m": bars_sha(rows) for period, rows in raw.items()}
    if inputs["v"] != PVC_INPUTS:
        raise ValueError("M_PERMISSION_PVC_MARKET_CHANGED")
    band = (Decimal("4686"), Decimal("4704"))
    high = max(bar.high for bar in bars[1])
    cases["v_weak_side_incomplete"] = dict(
        contract="V2609", source_ids=["S5310836013794895"], author_signal_at=None,
        public_opportunity="TARGET_NOT_COMPLETED_SHORT_RECOVERY_OR_REENTRY_DISCUSSION",
        band_scope="RETROSPECTIVE_ONLY", author_reported_high=Decimal("4690"), market_high=high,
        comparison_weak_side_band=band,
        first_bar_at_high=next(bar.end for bar in bars[1] if bar.high == high),
        diagnostic=window(bars, "2026-06-16T21:00", "2026-06-17T15:01", "LONG",
                          {"weak_side_near": band[0], "weak_side_far": band[1]}),
    )
    return dict(version="lms405-m-permission-study-v1", inputs=inputs, cases=cases,
                reference_sha256={key: digest for key, (_, digest) in REFERENCES.items()},
                author_config=None, author_permission=None, admitted_author_samples=0,
                author_matches=None, executable=False, fills=None, pnl=None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--reference-root", type=Path, required=True)
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
        references = evidence_inputs(args.reference_root)
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=60):
            result = study(session, build_market_data_service(session), references)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(result))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (OSError, KeyError, ValueError):
        parser.exit(2, "M_PERMISSION_REFERENCE_OR_MARKET_UNVERIFIED\n")


if __name__ == "__main__":
    main()
