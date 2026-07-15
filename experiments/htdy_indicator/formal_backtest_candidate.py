"""Read-only HTDY strict formal backtest candidate dry-run.

The helper reads existing primary/passed JM 15m parquet, runs
``huotian_dayou_strict / v0.1.0-backtest-candidate``, and exports a normalized
payload that can be reviewed before any independent BacktestReport is created.
It does not create tasks, write reports, mutate data assets, send notifications,
or touch report_id=14.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

import pyarrow.parquet as pq


REPO_ROOT = Path(__file__).resolve().parents[2]
QUANT_CORE_ROOT = REPO_ROOT / "packages" / "quant-core"
if str(QUANT_CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(QUANT_CORE_ROOT))

from guiyi_quant.strategies.huotian_dayou_strict import (  # noqa: E402
    CANDIDATE_POLICY,
    EXECUTION_SCOPE,
    FILL_POLICY,
    STRATEGY_CLASS_PATH,
    STRATEGY_CODE,
    STRATEGY_VERSION,
    HuoTianDaYouStrictStrategy,
    build_normalized_result,
)


DEFAULT_MANIFEST_PATH = Path(__file__).with_name("golden_sample_manifest.json")
SOURCE_ENV = "GUIYI_HTDY_FORMAL_SOURCE"
DATA_ROOT_ENV = "GUIYI_DATA_ROOT"
INPUT_COLUMNS = ("datetime", "open", "high", "low", "close", "volume")
LINEAGE_COLUMNS = ("provider", "source", "data_role", "quality_status", "data_version", "symbol", "contract", "period")
ALLOWED_SOURCES = {"rqdata", "local_parquet"}


@dataclass
class CandidateBar:
    datetime: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    price_tick: float
    contract_multiplier: int
    commission_rate: float | None
    commission_per_contract: float | None
    margin_rate: float
    symbol: str
    exchange: str
    contract: str


@dataclass(frozen=True)
class CandidateInput:
    source_path: Path
    bars: list[CandidateBar]
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
    checked = "\n".join(f"- {candidate}" for candidate in candidates)
    raise FileNotFoundError(f"HTDY formal candidate source not found. Checked:\n{checked}")


def read_candidate_input(
    source_path: Path,
    manifest: Mapping[str, Any],
    *,
    start: datetime | None = None,
    end: datetime | None = None,
    price_tick: float,
    contract_multiplier: int,
    commission_rate: float | None,
    commission_per_contract: float | None,
    margin_rate: float,
) -> CandidateInput:
    expected_lineage = {key: str(value) for key, value in manifest["source"]["lineage"].items()}
    table = pq.ParquetFile(source_path).read(columns=[*INPUT_COLUMNS, *LINEAGE_COLUMNS])
    rows = _window_rows(table.to_pylist(), start=start, end=end)
    if not rows:
        raise ValueError("formal candidate input window is empty")
    rows.sort(key=lambda row: _as_naive_datetime(row["datetime"]))
    if len({_as_naive_datetime(row["datetime"]) for row in rows}) != len(rows):
        raise ValueError("formal candidate input contains duplicate datetimes")
    _validate_lineage(rows, expected_lineage)
    _validate_ohlcv(rows)
    bars = [
        CandidateBar(
            datetime=_as_naive_datetime(row["datetime"]),
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=float(row["volume"]),
            price_tick=price_tick,
            contract_multiplier=contract_multiplier,
            commission_rate=commission_rate,
            commission_per_contract=commission_per_contract,
            margin_rate=margin_rate,
            symbol=str(row["symbol"]),
            exchange="DCE",
            contract=str(row["contract"]).upper().replace(".", ""),
        )
        for row in rows
    ]
    return CandidateInput(
        source_path=source_path,
        bars=bars,
        input_sha256=stable_sha256([_bar_payload(bar) for bar in bars]),
        file_sha256=file_sha256(source_path),
        lineage=expected_lineage,
    )


def evaluate_candidate(candidate_input: CandidateInput) -> dict[str, Any]:
    setting = {
        "price_tick": candidate_input.bars[0].price_tick,
        "contract_multiplier": candidate_input.bars[0].contract_multiplier,
        "commission_rate": candidate_input.bars[0].commission_rate,
        "commission_per_contract": candidate_input.bars[0].commission_per_contract,
        "margin_rate": candidate_input.bars[0].margin_rate,
        "submit_vnpy_orders": False,
    }
    strategy = HuoTianDaYouStrictStrategy(None, "htdy-formal-candidate-dry-run", "jm_MAIN.DCE", setting)
    for bar in candidate_input.bars:
        strategy.on_bar(bar)
    strategy.finalize_sample_end()
    normalized = build_normalized_result(strategy)
    normalized["summary"]["formal_candidate_gate"] = {
        "readonly": True,
        "would_write_db": False,
        "would_create_backtest_report": False,
        "report_id_14_touched": False,
        "requires_user_confirmation_before_report_write": True,
    }
    return {
        "status": "formal_backtest_candidate_dry_run",
        "stage_id": "HTDY-FORMAL-BACKTEST-CANDIDATE",
        "strategy_class_path": STRATEGY_CLASS_PATH,
        "strategy_code": STRATEGY_CODE,
        "strategy_version": STRATEGY_VERSION,
        "candidate_policy": CANDIDATE_POLICY,
        "execution_scope": EXECUTION_SCOPE,
        "fill_policy": FILL_POLICY,
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
            "source_path": str(candidate_input.source_path),
            "source_file_sha256": candidate_input.file_sha256,
            "input_sha256": candidate_input.input_sha256,
            "row_count": len(candidate_input.bars),
            "start_datetime": candidate_input.bars[0].datetime.isoformat(timespec="seconds"),
            "end_datetime": candidate_input.bars[-1].datetime.isoformat(timespec="seconds"),
            "lineage": candidate_input.lineage,
        },
        "event_counts": {
            "trade_count": len(normalized["trades"]),
            "order_count": len(normalized["orders"]),
            "execution_event_count": len(normalized["strategy_execution_events"]),
            "rejected_signal_count": len(normalized["warnings"]),
        },
        "normalized_result": normalized,
    }


def write_markdown_report(payload: Mapping[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    data = payload["data"]
    counts = payload["event_counts"]
    lines = [
        "# HTDY Strict Formal Backtest Candidate Dry Run",
        "",
        f"- status: `{payload['status']}`",
        f"- strategy: `{payload['strategy_code']} / {payload['strategy_version']}`",
        f"- candidate_policy: `{payload['candidate_policy']}`",
        f"- execution_scope: `{payload['execution_scope']}`",
        f"- fill_policy: `{payload['fill_policy']}`",
        f"- data: `{data['lineage']['provider']} / {data['lineage']['data_role']} / {data['lineage']['quality_status']}`",
        f"- window: `{data['start_datetime']}` -> `{data['end_datetime']}`",
        f"- row_count: `{data['row_count']}`",
        f"- input_sha256: `{data['input_sha256']}`",
        "",
        "## Dry Run Counts",
        "",
        f"- trade_count: `{counts['trade_count']}`",
        f"- order_count: `{counts['order_count']}`",
        f"- execution_event_count: `{counts['execution_event_count']}`",
        f"- rejected_signal_count: `{counts['rejected_signal_count']}`",
        "",
        "## Boundary",
        "",
        "- Read-only dry-run only; no BacktestReport, strategy_signals, signal_events, live path, or notification path is created.",
        "- `report_id=14` is not read for mutation and is not reused as the HTDY candidate target.",
    ]
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _validate_lineage(rows: Sequence[Mapping[str, Any]], expected_lineage: Mapping[str, str]) -> None:
    for field, expected in expected_lineage.items():
        actual_values = {str(row[field]) for row in rows}
        if actual_values != {expected}:
            raise ValueError(f"source lineage mismatch for {field}: expected={expected!r} actual={sorted(actual_values)!r}")
    provider = expected_lineage["provider"]
    source = expected_lineage["source"]
    if provider not in ALLOWED_SOURCES or source not in ALLOWED_SOURCES:
        raise ValueError(f"provider/source must be rqdata/local_parquet, got provider={provider} source={source}")
    if expected_lineage["data_role"] != "primary":
        raise ValueError(f"data_role must be primary, got {expected_lineage['data_role']}")
    if expected_lineage["quality_status"] != "passed":
        raise ValueError(f"quality_status must be passed, got {expected_lineage['quality_status']}")


def _validate_ohlcv(rows: Sequence[Mapping[str, Any]]) -> None:
    for index, row in enumerate(rows):
        values = [float(row[field]) for field in ("open", "high", "low", "close", "volume")]
        open_, high, low, close, volume = values
        if high < max(open_, close) or low > min(open_, close) or high < low or volume < 0:
            raise ValueError(f"formal candidate input has invalid OHLCV at index {index}")


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


def _bar_payload(bar: CandidateBar) -> dict[str, Any]:
    return {
        "datetime": bar.datetime.isoformat(timespec="seconds"),
        "open": bar.open,
        "high": bar.high,
        "low": bar.low,
        "close": bar.close,
        "volume": bar.volume,
        "price_tick": bar.price_tick,
        "contract_multiplier": bar.contract_multiplier,
        "commission_rate": bar.commission_rate,
        "commission_per_contract": bar.commission_per_contract,
        "margin_rate": bar.margin_rate,
        "symbol": bar.symbol,
        "contract": bar.contract,
    }


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_sha256(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _as_naive_datetime(value: Any) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    return parsed.replace(tzinfo=None)


def _parse_datetime(value: str | None) -> datetime | None:
    return None if value is None else datetime.fromisoformat(value).replace(tzinfo=None)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run HTDY formal backtest candidate as a read-only dry-run.")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH)
    parser.add_argument("--source", type=Path, help=f"Canonical parquet path; alternatively set {SOURCE_ENV}.")
    parser.add_argument("--start", help="Optional inclusive datetime window start.")
    parser.add_argument("--end", help="Optional inclusive datetime window end.")
    parser.add_argument("--price-tick", type=float, default=0.5)
    parser.add_argument("--contract-multiplier", type=int, default=60)
    parser.add_argument("--commission-rate", type=float, default=0.0001)
    parser.add_argument("--commission-per-contract", type=float)
    parser.add_argument("--margin-rate", type=float, default=0.12)
    parser.add_argument("--output-json", type=Path, help="Optional output JSON path.")
    parser.add_argument("--output-markdown", type=Path, help="Optional output Markdown path.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest = load_manifest(args.manifest)
    source_path = resolve_source_path(manifest, args.source)
    candidate_input = read_candidate_input(
        source_path,
        manifest,
        start=_parse_datetime(args.start),
        end=_parse_datetime(args.end),
        price_tick=args.price_tick,
        contract_multiplier=args.contract_multiplier,
        commission_rate=args.commission_rate,
        commission_per_contract=args.commission_per_contract,
        margin_rate=args.margin_rate,
    )
    payload = evaluate_candidate(candidate_input)
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
