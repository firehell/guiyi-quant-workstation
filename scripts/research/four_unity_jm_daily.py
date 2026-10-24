"""Frozen-input four-unity JM daily offline study; read-only MDS and local output."""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
import json
import math
from pathlib import Path
import subprocess
from types import SimpleNamespace

from app.market_data.domain import BarFrequency
from app.market_data.new_subing_research import (
    load_execution_facts,
    payload_hash,
    safe_diagnostic,
)
from scripts.research.four_unity_execution import VERSION, run_segment, summarize
from scripts.research.four_unity_signals import CANDIDATES, compute_signals
from scripts.research.newow_futures_execution_facts import read_json, safe_path
from scripts.research.subing_jm_daily_preflight import audit_series


def wire(x):
    if isinstance(x, dict):
        return {k: wire(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [wire(v) for v in x]
    if isinstance(x, (date, datetime)):
        return x.isoformat()
    if isinstance(x, Decimal):
        return str(x)
    if isinstance(x, float) and not math.isfinite(x):
        return None
    return x


def dated_facts(raw, contract, day):
    body = raw["contracts"].get(contract)
    if body is None:
        raise ValueError("EXECUTION_FACTS_MISSING")
    subset = {
        **raw,
        "contracts": {
            contract: {
                **body,
                "parameters": [r for r in body["parameters"] if r["date"] == str(day)],
                "daily": [r for r in body["daily"] if r["date"] == str(day)],
            }
        },
    }
    probe = SimpleNamespace(frequency="1m", physical_contract=contract, trading_day=day)
    return load_execution_facts(subset, product="jm", bars=(probe,))[0][0].facts


def contiguous_groups(day_rows):
    """A failed day ends an interval; never silently bridge missing facts."""
    groups, current = [], []
    for row in day_rows:
        if row["status"] == "INPUTS_VERIFIED":
            current.append(row["day"])
        elif current:
            groups.append(current)
            current = []
    if current:
        groups.append(current)
    return groups


def maximum_drawdown(equity):
    peak = maximum = Decimal("0")
    for row in equity:
        peak = max(peak, row["pnl"])
        maximum = max(maximum, peak - row["pnl"])
    return maximum


def run(market, audit, snapshots):
    result = {
        "strategy_code": "four_unity_jm_daily_research_v1",
        "execution_version": VERSION,
        "kind": "OFFLINE_PER_LOT_RESEARCH_NOT_ACCOUNT",
        "requested_since": audit["since"],
        "requested_through": audit["through"],
        "input_status_counts": audit["status_counts"],
        "excluded_windows": audit["windows"],
        "retrospective_execution_facts": True,
        "independent_oos": False,
        "original_software_parity": "NOT_PROVEN",
        "provider_calls": 0,
        "data_mutations": 0,
        "segments": [],
        "cells": {},
        "formula_metadata": None,
    }
    aggregations = {(c, t): [] for c in CANDIDATES for t in (0, 1, 2)}
    for si, seg in enumerate(audit["segments"]):
        contract = seg["contract"]
        start, end = (
            date.fromisoformat(seg["since"]),
            date.fromisoformat(seg["through"]),
        )
        cutoff = max(
            s.end for s in market.session_windows(symbol="jm", trading_day=end)
        )
        print(json.dumps({"stage": "research_owner", "contract": contract}), flush=True)
        prefix_report, daily = audit_series(
            market, contract, BarFrequency.D1, None, end, cutoff
        )
        minute_report, minutes = audit_series(
            market, contract, BarFrequency.M1, start, end, cutoff
        )
        expected_minute = next(s for s in seg["scans"] if s["frequency"] == "1m")
        for actual, frozen in (
            (prefix_report, seg["daily_warmup"]),
            (minute_report, expected_minute),
        ):
            if (
                actual["status"] != "PASS"
                or actual["input_hash"] != frozen.get("input_hash")
                or actual["source_hash"] != frozen.get("source_hash")
            ):
                raise ValueError("INPUT_CHANGED_SINCE_AUDIT")
        raw_bars = [
            {
                "date": str(b.trading_day),
                **{
                    k: float(getattr(b, k))
                    for k in ("open", "high", "low", "close", "volume")
                },
            }
            for b in daily
        ]
        computed = compute_signals(raw_bars)
        result["formula_metadata"] = computed["metadata"]
        realtime = {s["date"]: s for s in computed["realtime"]}
        chart = {s["date"]: s for s in computed["final_chart"]}
        day_rows = [
            r
            for r in audit["days"]
            if r["contract"] == contract and seg["since"] <= r["day"] <= seg["through"]
        ]
        groups = contiguous_groups(day_rows)
        daily_by_day = {str(b.trading_day): b for b in daily}
        owned_signals = []
        for row in day_rows:
            s = realtime.get(row["day"])
            if s is None:
                raise ValueError("SIGNAL_DAY_MISSING")
            owned_signals.append(
                {
                    **s,
                    "execution_input_status": row["status"],
                    "final_chart": chart[row["day"]],
                }
            )
        info = {
            "contract": contract,
            "since": start,
            "through": end,
            "daily_prefix_count": len(daily),
            "source_hash": prefix_report["source_hash"],
            "minute_input_hash": minute_report["input_hash"],
            "signals": owned_signals,
            "execution_intervals": [],
        }
        result["segments"].append(info)
        facts_by_day = {}
        for row in day_rows:
            if row["status"] != "INPUTS_VERIFIED":
                continue
            candidates = []
            for snap in snapshots:
                # Only use the exact provider snapshots individually proven by the fresh audit.
                if not any(
                    f["snapshot_hash"] == snap["hash"] and f["status"] == "PASS"
                    for f in row["facts"]
                ):
                    continue
                fact = dated_facts(
                    snap["raw"], contract, date.fromisoformat(row["day"])
                )
                candidates.append(fact)
            if not candidates:
                raise ValueError("EXECUTION_FACTS_MISSING")
            normalized = []
            for f in candidates:
                data = asdict(f)
                data.pop("source_id")
                data["fees"].pop("source_id")
                normalized.append(payload_hash(data))
            if len(set(normalized)) != 1:
                raise ValueError("EXECUTION_FACTS_CONFLICT")
            facts_by_day[row["day"]] = candidates[-1]
        sessions = {
            r["day"]: market.session_windows(
                symbol="jm", trading_day=date.fromisoformat(r["day"])
            )
            for r in day_rows
        }
        for group in groups:
            group_set = set(group)
            execution = []
            for b in minutes:
                ds = str(b.trading_day)
                if ds not in group_set:
                    continue
                windows = sessions[ds]
                if not any(
                    w.start <= b.bar_end - timedelta(minutes=1) and b.bar_end <= w.end
                    for w in windows
                ):
                    raise ValueError("EXECUTION_SESSION_UNPROVEN")
                execution.append(
                    SimpleNamespace(
                        bar=SimpleNamespace(**asdict(b), physical_contract=contract),
                        facts=facts_by_day[ds],
                    )
                )
            signals = []
            for ds in group:
                s = realtime[ds]
                # A daily Bar becomes available after the last authoritative session.
                at = max(w.end for w in sessions[ds])
                signals.append({**s, "at": at, "low": daily_by_day[ds].low})
            terminal = (
                "DATA_INTERRUPTED"
                if group[-1] != seg["through"]
                else "ROLLOVER_INTERRUPTED"
                if si < len(audit["segments"]) - 1
                else "OPEN"
            )
            info["execution_intervals"].append(
                {
                    "since": group[0],
                    "through": group[-1],
                    "terminal": terminal,
                    "minute_count": len(execution),
                }
            )
            for candidate in CANDIDATES:
                for ticks in (0, 1, 2):
                    simulation_signals = signals
                    if candidate == "pullback":
                        # Convention-only diagnostic, never a source-parity acceptance result.
                        simulation_signals = [
                            {
                                **s,
                                "ready": {**s["ready"], "pullback": s["ready_inputs"]},
                                "block_reasons": {
                                    **s["block_reasons"],
                                    "pullback": [] if s["ready_inputs"] else ["WARMUP"],
                                },
                            }
                            for s in signals
                        ]
                    cell = run_segment(
                        simulation_signals,
                        execution,
                        candidate,
                        ticks,
                        terminal=terminal,
                    )
                    cell["mtm_max_drawdown_per_lot"] = maximum_drawdown(cell["equity"])
                    # Preserve exact minute-close drawdown, export daily marks rather than
                    # repeating the identical minute clock in nine large JSON arrays.
                    daily_marks = {}
                    for mark, ex in zip(cell["equity"], execution):
                        daily_marks[str(ex.bar.trading_day)] = mark
                    cell["equity"] = list(daily_marks.values())
                    cell.update(
                        {
                            "contract": contract,
                            "since": group[0],
                            "through": group[-1],
                            "terminal": terminal,
                        }
                    )
                    aggregations[(candidate, ticks)].append(cell)
    # Final physical-source check catches changes after an earlier owner was computed.
    for seg in audit["segments"]:
        end = date.fromisoformat(seg["through"])
        cutoff = max(
            s.end for s in market.session_windows(symbol="jm", trading_day=end)
        )
        for scan in (
            seg["daily_warmup"],
            next(s for s in seg["scans"] if s["frequency"] == "1m"),
        ):
            final = market.contract_source_evidence(
                symbol="jm",
                contract=seg["contract"],
                frequency=BarFrequency(scan["frequency"]),
                before=cutoff,
            )
            if payload_hash(final) != scan["source_hash"]:
                raise ValueError("SOURCE_CHANGED_DURING_RESEARCH")
    for (candidate, ticks), parts in aggregations.items():
        trades = [r for p in parts for r in p["trades"]]
        unclosed = [r for p in parts for r in p["unclosed"]]
        summary = summarize(trades, unclosed)
        summary["maximum_verified_interval_mtm_drawdown_per_lot"] = max(
            (p["mtm_max_drawdown_per_lot"] for p in parts), default=Decimal("0")
        )
        summary["whole_history_mtm_drawdown"] = None
        years = [
            str(y)
            for y in range(int(audit["since"][:4]), int(audit["through"][:4]) + 1)
        ]
        annual = {
            y: summarize([t for t in trades if t["exit_at"].startswith(y)], [])
            for y in years
        }
        counts = Counter()
        for p in parts:
            counts.update(p["rejections"])
        result["cells"][f"{candidate}-slip{ticks}"] = {
            "candidate": candidate,
            "slippage_ticks": ticks,
            "status": "CONVENTION_ONLY_XMA6_UNVERIFIED"
            if candidate == "pullback"
            else "PARTIAL_INPUT_HISTORY",
            "summary": summary,
            "annual": annual,
            "trades": trades,
            "unclosed": unclosed,
            "rejections": dict(counts),
            "intervals": parts,
        }
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--source-docx", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    audit_path, target = safe_path(args.audit), safe_path(args.out)
    if not target.is_relative_to(root / "output") or target.exists():
        raise ValueError("OUTPUT_INVALID_OR_EXISTS")
    audit = read_json(audit_path)
    audit_hash = sha256(audit_path.read_bytes()).hexdigest()
    source_docx = safe_path(args.source_docx)
    source_hash = sha256(source_docx.read_bytes()).hexdigest()
    code_paths = [
        root / "scripts/research" / name
        for name in (
            "four_unity_jm_daily.py",
            "four_unity_signals.py",
            "four_unity_execution.py",
        )
    ]
    code_paths.extend(
        root / name
        for name in (
            "packages/quant-core/guiyi_quant/indicators/htdy_original.py",
            "packages/quant-core/guiyi_quant/paper/__init__.py",
            "services/quant-api/app/market_data/new_subing_research.py",
            "scripts/research/subing_jm_daily_preflight.py",
        )
    )
    code_revision = subprocess.run(
        ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()
    code_hashes = {
        str(p.relative_to(root)): sha256(p.read_bytes()).hexdigest() for p in code_paths
    }
    snapshots = []
    for snap in audit["snapshots"]:
        path = safe_path(Path(snap["path"]))
        if sha256(path.read_bytes()).hexdigest() != snap["hash"]:
            raise ValueError("FACTS_CHANGED_SINCE_AUDIT")
        snapshots.append({**snap, "raw": read_json(path)})
    from dotenv import load_dotenv

    load_dotenv(root / ".env", override=False)
    from app.db.session import SessionLocal
    from app.db.readonly import readonly_transaction
    from app.market_data.composition import build_market_data_service
    from app.models.market_tables import MainContractMap
    from sqlalchemy import select

    with SessionLocal() as session, readonly_transaction(session, timeout_seconds=900):
        mappings = (
            session.execute(
                select(MainContractMap)
                .where(MainContractMap.symbol == "jm", MainContractMap.rank == 1)
                .order_by(MainContractMap.trade_date)
            )
            .scalars()
            .all()
        )
        if (
            payload_hash([(m.trade_date, m.contract_code) for m in mappings])
            != audit["mapping_hash"]
        ):
            raise ValueError("MAPPING_CHANGED_SINCE_AUDIT")
        result = run(build_market_data_service(session), audit, snapshots)
    if sha256(audit_path.read_bytes()).hexdigest() != audit_hash or any(
        sha256(Path(s["path"]).read_bytes()).hexdigest() != s["hash"] for s in snapshots
    ):
        raise ValueError("FROZEN_INPUT_CHANGED_DURING_RESEARCH")
    if (
        any(
            sha256((root / p).read_bytes()).hexdigest() != h
            for p, h in code_hashes.items()
        )
        or sha256(source_docx.read_bytes()).hexdigest() != source_hash
    ):
        raise ValueError("SOURCE_CODE_OR_DOCUMENT_CHANGED_DURING_RESEARCH")
    result["audit_sha256"] = audit_hash
    result["code_revision"] = code_revision
    result["code_hashes"] = code_hashes
    result["source_document_sha256"] = source_hash
    result["calculated_at"] = datetime.now(UTC).isoformat()
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x") as stream:
        json.dump(
            wire(result),
            stream,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )
        stream.write("\n")
    print(
        json.dumps(
            wire({k: v["summary"] for k, v in result["cells"].items()}),
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Error text can contain SQL, credentials or paths; return only public typed codes.
        code = (
            str(exc)
            if isinstance(exc, ValueError)
            and str(exc).isupper()
            and str(exc).replace("_", "").isalnum()
            else "RESEARCH_FAILED"
        )
        print(
            json.dumps(
                {
                    "status": "BLOCKED",
                    "code": code,
                    "diagnostic": safe_diagnostic(exc, product="jm", stage="research"),
                }
            )
        )
        raise SystemExit(2) from None
