"""Read-only HTDY strict v1 offline candidate evaluator.

This runner evaluates ``huotian_dayou_strict_v1`` as candidate events only.
It reads existing primary/passed JM 15m parquet, computes strict fields, and
exports JSON/Markdown evidence without creating backtest tasks, reports,
signals, live events, or notifications.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import ModuleType
from typing import Any, Mapping, Sequence

import numpy as np
import pyarrow.parquet as pq


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST_PATH = Path(__file__).with_name("golden_sample_manifest.json")
SOURCE_ENV = "GUIYI_HTDY_OFFLINE_SOURCE"
DATA_ROOT_ENV = "GUIYI_DATA_ROOT"
INPUT_COLUMNS = ("datetime", "open", "high", "low", "close", "volume")
LINEAGE_COLUMNS = ("provider", "source", "data_role", "quality_status", "data_version", "symbol", "contract", "period")
STRATEGY_CODE = "huotian_dayou_strict"
STRATEGY_VERSION = "v0.1.0-offline"
CANDIDATE_POLICY = "strict_v1_15m_offline_v0"
FILL_POLICY = "signal_on_close_fill_next_bar_open"
EXECUTION_SCOPE = "offline_comparison_only"
STATUS = "offline_backtest_candidate_eval"


@dataclass(frozen=True)
class OfflineBars:
    source_path: Path
    bars: dict[str, list[Any]]
    input_sha256: str
    file_sha256: str
    lineage: dict[str, str]


def load_manifest(path: Path = DEFAULT_MANIFEST_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_source_path(manifest: Mapping[str, Any], explicit_path: Path | None = None) -> Path:
    candidates: list[Path] = []
    if explicit_path is not None:
        candidates.append(explicit_path.expanduser())
    if os.getenv(SOURCE_ENV):
        candidates.append(Path(os.environ[SOURCE_ENV]).expanduser())
    relative_path = Path(str(manifest["source"]["relative_path"]))
    if os.getenv(DATA_ROOT_ENV):
        candidates.append(Path(os.environ[DATA_ROOT_ENV]).expanduser() / relative_path)
    candidates.append(REPO_ROOT.parents[1] / "guiyi-quant-workstation" / relative_path)
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    joined = "\n".join(f"- {candidate}" for candidate in candidates)
    raise FileNotFoundError(
        f"HTDY offline candidate source not found. Set {SOURCE_ENV} or {DATA_ROOT_ENV}. Checked:\n{joined}"
    )


def read_offline_bars(
    source_path: Path,
    manifest: Mapping[str, Any],
    *,
    start: datetime | None = None,
    end: datetime | None = None,
) -> OfflineBars:
    expected_lineage = {key: str(value) for key, value in manifest["source"]["lineage"].items()}
    table = pq.ParquetFile(source_path).read(columns=[*INPUT_COLUMNS, *LINEAGE_COLUMNS])
    rows = table.to_pylist()
    selected = _window_rows(rows, start=start, end=end)
    if not selected:
        raise ValueError("offline candidate input window is empty")
    selected.sort(key=lambda row: _as_naive_datetime(row["datetime"]))
    if len({_as_naive_datetime(row["datetime"]) for row in selected}) != len(selected):
        raise ValueError("offline candidate input contains duplicate datetimes")
    for field, expected in expected_lineage.items():
        actual_values = {str(row[field]) for row in selected}
        if actual_values != {expected}:
            raise ValueError(f"source lineage mismatch for {field}: expected={expected!r} actual={sorted(actual_values)!r}")
    _validate_ohlcv(selected)

    bars = {column: [row[column] for row in selected] for column in INPUT_COLUMNS}
    return OfflineBars(
        source_path=source_path,
        bars=bars,
        input_sha256=stable_sha256(_serializable_bars(bars)),
        file_sha256=file_sha256(source_path),
        lineage=expected_lineage,
    )


def evaluate_offline_candidate(bars: OfflineBars, *, channel_period: int = 25, var23_period: int = 6) -> dict[str, Any]:
    strict_module = _load_module("htdy_strict_core_offline_eval", Path(__file__).with_name("htdy_strict_core.py"))
    result = strict_module.compute_htdy_strict(
        *[bars.bars[column] for column in INPUT_COLUMNS],
        channel_period=channel_period,
        var23_period=var23_period,
    )
    _verify_strict_metadata(result.metadata)
    events = _candidate_events(result, strict_module)
    event_counts = _event_counts(events)
    return {
        "status": STATUS,
        "stage_id": "HTDY-STEP5-OFFLINE-BACKTEST-CANDIDATE-EVAL",
        "execution_scope": EXECUTION_SCOPE,
        "candidate_policy": CANDIDATE_POLICY,
        "strategy_code": STRATEGY_CODE,
        "strategy_version": STRATEGY_VERSION,
        "indicator_version": result.metadata["indicator_version"],
        "source_version": result.metadata["source_version"],
        "fill_policy": FILL_POLICY,
        "event_interpretation": {
            "mode": "candidate_events_only",
            "long_entry_candidates": ["buy_observation", "xg_observation"],
            "short_or_exit_candidates": ["sell_observation"],
            "signal_confirmed_on": "current_bar_close",
            "proposed_fill_time": "next_bar_open",
            "pnl_calculated": False,
            "trusted_backtest_report_created": False,
        },
        "capabilities": {
            "future_looking": False,
            "closed_bar_only": True,
            "backtest_candidate": True,
            "backtest_capable": False,
            "live_capable": False,
            "alert_capable": False,
            "trading_capable": False,
        },
        "data": {
            "source_path": str(bars.source_path),
            "source_file_sha256": bars.file_sha256,
            "input_sha256": bars.input_sha256,
            "row_count": len(bars.bars["datetime"]),
            "start_datetime": _iso(bars.bars["datetime"][0]),
            "end_datetime": _iso(bars.bars["datetime"][-1]),
            "lineage": bars.lineage,
        },
        "strict_summary": _strict_summary(result, strict_module),
        "event_counts": event_counts,
        "events": events,
        "risk_conclusion": {
            "p0": [],
            "p1": [
                "Candidate observations are not executable strategy rules until entry, exit, stop, reverse, and conflict policies are specified.",
                "Offline event distribution is not a trusted backtest report and is not live or alert evidence.",
            ],
            "p2": [
                "A later formal backtest plan must add a strategy implementation, parameter schema, review context, and trust audit.",
            ],
        },
        "forbidden_integrations": [
            "packages/quant-core/guiyi_quant/strategies",
            "BacktestReport",
            "strategy_signals",
            "signal_events",
            "live_signal_evaluator",
            "enterprise_wechat",
        ],
    }


def write_markdown_report(payload: Mapping[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    data = payload["data"]
    counts = payload["event_counts"]
    lines = [
        "# HTDY Strict V1 Offline Candidate Evaluation",
        "",
        f"- status: `{payload['status']}`",
        f"- strategy: `{payload['strategy_code']} / {payload['strategy_version']}`",
        f"- indicator_version: `{payload['indicator_version']}`",
        f"- candidate_policy: `{payload['candidate_policy']}`",
        f"- execution_scope: `{payload['execution_scope']}`",
        f"- fill_policy: `{payload['fill_policy']}`",
        f"- data: `{data['lineage']['provider']} / {data['lineage']['data_role']} / {data['lineage']['quality_status']}`",
        f"- window: `{data['start_datetime']}` -> `{data['end_datetime']}`",
        f"- row_count: `{data['row_count']}`",
        f"- input_sha256: `{data['input_sha256']}`",
        "",
        "## Candidate Events",
        "",
        f"- long_entry_candidate: `{counts['long_entry_candidate']}`",
        f"- short_or_exit_candidate: `{counts['short_or_exit_candidate']}`",
        f"- any_candidate_event: `{counts['any_candidate_event']}`",
        "",
        "## Capability Boundary",
        "",
        "- Candidate events only; no trusted PnL, report, signal event, live path, or notification path is created.",
        "- Signals are considered confirmed on current bar close; proposed comparison fill time is next bar open only.",
        "",
        "## Risk Notes",
        "",
        "- strict v1 is a safety rewrite candidate, not a point-by-point original formula clone.",
        "- Entry, exit, stop, reverse, and conflict handling remain undefined for a formal strategy.",
    ]
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _candidate_events(result: Any, module: ModuleType) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    length = len(result.datetimes)
    for index in range(length):
        long_reasons = [
            name
            for name in ("buy_observation", "xg_observation")
            if bool(result.fields[name][index])
        ]
        short_reasons = ["sell_observation"] if bool(result.fields["sell_observation"][index]) else []
        if not long_reasons and not short_reasons:
            continue
        next_index = index + 1
        event_type = _event_type(long_reasons, short_reasons)
        events.append(
            {
                "index": index,
                "event_type": event_type,
                "signal_bar_datetime": _iso(result.datetimes[index]),
                "signal_confirmed_on": "current_bar_close",
                "proposed_fill_policy": FILL_POLICY,
                "proposed_fill_datetime": _iso(result.datetimes[next_index]) if next_index < length else None,
                "proposed_fill_open": _scalar_or_none(result.open[next_index]) if next_index < length else None,
                "close": _scalar_or_none(result.close[index]),
                "reasons": long_reasons + short_reasons,
                "fields": {
                    name: _scalar_or_none(result.fields[name][index])
                    for name in module.STRICT_OUTPUT_FIELDS
                },
            }
        )
    return events


def _event_type(long_reasons: Sequence[str], short_reasons: Sequence[str]) -> str:
    if long_reasons and short_reasons:
        return "conflict_candidate"
    if long_reasons:
        return "long_entry_candidate"
    return "short_or_exit_candidate"


def _event_counts(events: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    counts = {
        "long_entry_candidate": 0,
        "short_or_exit_candidate": 0,
        "conflict_candidate": 0,
        "any_candidate_event": len(events),
    }
    for event in events:
        event_type = str(event["event_type"])
        counts[event_type] = counts.get(event_type, 0) + 1
    return counts


def _verify_strict_metadata(metadata: Mapping[str, Any]) -> None:
    expected = {
        "indicator_version": "huotian_dayou_strict_v1",
        "source_version": "huotian_dayou_original_v0",
        "status": "strict_research_candidate",
        "closed_bar_only": True,
        "future_looking": False,
        "backtest_capable": False,
        "live_capable": False,
        "alert_capable": False,
        "trading_capable": False,
    }
    for key, value in expected.items():
        if metadata.get(key) != value:
            raise AssertionError(f"strict metadata drifted: {key} expected={value!r} actual={metadata.get(key)!r}")


def _strict_summary(result: Any, module: ModuleType) -> dict[str, Any]:
    return {
        "numeric": {
            name: _numeric_summary(result.fields[name])
            for name in module.NUMERIC_FIELDS
        },
        "boolean": {
            name: _boolean_summary(result.fields[name])
            for name in module.BOOLEAN_FIELDS
        },
    }


def _numeric_summary(values: Sequence[float]) -> dict[str, Any]:
    arr = np.asarray(values, dtype=float)
    finite = np.flatnonzero(np.isfinite(arr))
    return {
        "null_count": int(np.count_nonzero(~np.isfinite(arr))),
        "first_finite_index": int(finite[0]) if len(finite) else None,
        "last_finite_index": int(finite[-1]) if len(finite) else None,
    }


def _boolean_summary(values: Sequence[bool]) -> dict[str, Any]:
    arr = np.asarray(values, dtype=bool)
    indexes = np.flatnonzero(arr).astype(int).tolist()
    return {"count": len(indexes), "indexes": indexes}


def _window_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    start: datetime | None,
    end: datetime | None,
) -> list[Mapping[str, Any]]:
    selected = []
    for row in rows:
        dt = _as_naive_datetime(row["datetime"])
        if start is not None and dt < start:
            continue
        if end is not None and dt > end:
            continue
        selected.append(row)
    return selected


def _validate_ohlcv(rows: Sequence[Mapping[str, Any]]) -> None:
    for index, row in enumerate(rows):
        values = [float(row[field]) for field in ("open", "high", "low", "close", "volume")]
        if not all(np.isfinite(value) for value in values):
            raise ValueError(f"offline candidate input has non-finite OHLCV at index {index}")
        open_, high, low, close, volume = values
        if high < max(open_, close) or low > min(open_, close) or high < low or volume < 0:
            raise ValueError(f"offline candidate input has invalid OHLCV at index {index}")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_sha256(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _serializable_bars(bars: Mapping[str, list[Any]]) -> list[dict[str, Any]]:
    rows = []
    for index in range(len(bars["datetime"])):
        rows.append(
            {
                "datetime": _iso(bars["datetime"][index]),
                "open": float(bars["open"][index]),
                "high": float(bars["high"][index]),
                "low": float(bars["low"][index]),
                "close": float(bars["close"][index]),
                "volume": float(bars["volume"][index]),
            }
        )
    return rows


def _as_naive_datetime(value: Any) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    return parsed.replace(tzinfo=None)


def _iso(value: Any) -> str:
    return _as_naive_datetime(value).isoformat(timespec="seconds")


def _scalar_or_none(value: Any) -> Any:
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, bool):
        return value
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        value = float(value)
    if isinstance(value, float):
        if not np.isfinite(value):
            return None
        return round(value, 6)
    return value


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _parse_datetime(value: str | None) -> datetime | None:
    return None if value is None else datetime.fromisoformat(value).replace(tzinfo=None)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate HTDY strict v1 as a read-only offline candidate.")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH)
    parser.add_argument("--source", type=Path, help=f"Canonical parquet path; alternatively set {SOURCE_ENV}.")
    parser.add_argument("--start", help="Optional inclusive datetime window start.")
    parser.add_argument("--end", help="Optional inclusive datetime window end.")
    parser.add_argument("--output-json", type=Path, help="Optional output JSON path.")
    parser.add_argument("--output-markdown", type=Path, help="Optional output Markdown path.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest = load_manifest(args.manifest)
    source_path = resolve_source_path(manifest, args.source)
    bars = read_offline_bars(source_path, manifest, start=_parse_datetime(args.start), end=_parse_datetime(args.end))
    payload = evaluate_offline_candidate(bars)
    text = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False)
    if args.output_json is not None:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(text + "\n", encoding="utf-8")
    if args.output_markdown is not None:
        write_markdown_report(payload, args.output_markdown)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
