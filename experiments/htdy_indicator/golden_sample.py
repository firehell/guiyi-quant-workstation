"""Read-only HTDY Golden Sample verifier for the fixed JM.MAIN 15m window.

The verifier never downloads or writes market data.  It reads an existing
primary/passed canonical parquet, verifies its lineage, computes the original
observation-only and strict research-candidate outputs, and compares stable
summaries with the tracked manifest.
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
SOURCE_ENV = "GUIYI_HTDY_GOLDEN_SOURCE"
DATA_ROOT_ENV = "GUIYI_DATA_ROOT"
INPUT_COLUMNS = ("datetime", "open", "high", "low", "close", "volume")
LINEAGE_COLUMNS = ("provider", "source", "data_role", "quality_status", "data_version", "symbol", "contract", "period")


@dataclass(frozen=True)
class GoldenSample:
    source_path: Path
    bars: dict[str, list[Any]]
    input_sha256: str


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
        f"HTDY Golden Sample source not found. Set {SOURCE_ENV} or {DATA_ROOT_ENV}. Checked:\n{joined}"
    )


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_golden_sample(source_path: Path, manifest: Mapping[str, Any]) -> GoldenSample:
    expected_file_sha = str(manifest["source"]["file_sha256"])
    actual_file_sha = file_sha256(source_path)
    if actual_file_sha != expected_file_sha:
        raise ValueError(f"source file sha256 mismatch: expected={expected_file_sha} actual={actual_file_sha}")

    table = pq.ParquetFile(source_path).read(columns=[*INPUT_COLUMNS, *LINEAGE_COLUMNS])
    rows = table.to_pylist()
    sample_spec = manifest["sample"]
    start = datetime.fromisoformat(str(sample_spec["start_datetime"]))
    end = datetime.fromisoformat(str(sample_spec["end_datetime"]))
    selected = [row for row in rows if start <= _as_naive_datetime(row["datetime"]) <= end]
    selected.sort(key=lambda row: _as_naive_datetime(row["datetime"]))
    expected_count = int(sample_spec["row_count"])
    if len(selected) != expected_count:
        raise ValueError(f"sample row_count mismatch: expected={expected_count} actual={len(selected)}")
    if _as_naive_datetime(selected[0]["datetime"]) != start or _as_naive_datetime(selected[-1]["datetime"]) != end:
        raise ValueError("sample datetime boundary mismatch")
    if len({_as_naive_datetime(row["datetime"]) for row in selected}) != len(selected):
        raise ValueError("sample contains duplicate datetimes")

    expected_lineage = manifest["source"]["lineage"]
    for field, expected in expected_lineage.items():
        actual_values = {str(row[field]) for row in selected}
        if actual_values != {str(expected)}:
            raise ValueError(f"source lineage mismatch for {field}: expected={expected!r} actual={sorted(actual_values)!r}")
    _validate_ohlcv(selected)

    bars = {column: [row[column] for row in selected] for column in INPUT_COLUMNS}
    input_sha = stable_sha256(_serializable_bars(bars))
    expected_input_sha = str(sample_spec["input_sha256"])
    if expected_input_sha and input_sha != expected_input_sha:
        raise ValueError(f"sample input sha256 mismatch: expected={expected_input_sha} actual={input_sha}")
    return GoldenSample(source_path=source_path, bars=bars, input_sha256=input_sha)


def verify_golden_sample(
    manifest: Mapping[str, Any],
    sample: GoldenSample,
    *,
    export_web_bundle: Path | None = None,
) -> dict[str, Any]:
    original_module = _load_module("htdy_original_core_golden", Path(__file__).with_name("htdy_original_core.py"))
    strict_module = _load_module("htdy_strict_core_golden", Path(__file__).with_name("htdy_strict_core.py"))
    args = [sample.bars[column] for column in INPUT_COLUMNS]
    original_policy = manifest["policies"]["original"]
    strict_policy = manifest["policies"]["strict"]
    original = original_module.compute_htdy_original(
        *args,
        capital=float(original_policy["capital"]),
        from_open=float(original_policy["from_open"]),
        channel_period=int(original_policy["channel_period"]),
        var23_period=int(original_policy["var23_period"]),
    )
    strict = strict_module.compute_htdy_strict(
        *args,
        channel_period=int(strict_policy["channel_period"]),
        var23_period=int(strict_policy["var23_period"]),
    )

    original_summary = result_summary(original, original_module.NUMERIC_FIELDS, original_module.BOOLEAN_FIELDS)
    strict_summary = result_summary(strict, strict_module.NUMERIC_FIELDS, strict_module.BOOLEAN_FIELDS)
    _assert_summary("original", original_summary, manifest["expected"]["original"])
    _assert_summary("strict", strict_summary, manifest["expected"]["strict"])
    _verify_frozen_policies(manifest["policies"], original_module, strict_module, original, strict, strict_summary)
    _verify_strict_real_sample_invariants(strict_module, sample.bars, strict)
    _verify_capability_boundary(original.metadata, strict.metadata)

    if export_web_bundle is not None:
        export_web_bundle.parent.mkdir(parents=True, exist_ok=True)
        export_web_bundle.write_text(
            json.dumps(
                _web_bundle(manifest, sample, original, original_module),
                ensure_ascii=False,
                indent=2,
                allow_nan=False,
            )
            + "\n",
            encoding="utf-8",
        )

    return {
        "status": manifest["acceptance"]["current_status"],
        "source_file_sha256": file_sha256(sample.source_path),
        "input_sha256": sample.input_sha256,
        "row_count": len(sample.bars["datetime"]),
        "start_datetime": _iso(sample.bars["datetime"][0]),
        "end_datetime": _iso(sample.bars["datetime"][-1]),
        "original": original_summary,
        "strict": strict_summary,
        "external_oracle_required": bool(manifest["acceptance"]["external_oracle_required"]),
        "oracle_type": manifest["acceptance"].get("oracle_type"),
        "oracle_numeric_export_provided": bool(manifest["acceptance"].get("oracle_numeric_export_provided", False)),
        "step5_authorized": bool(manifest["acceptance"]["step5_authorized"]),
    }


def result_summary(result: Any, numeric_fields: Sequence[str], boolean_fields: Sequence[str]) -> dict[str, Any]:
    numeric: dict[str, Any] = {}
    for name in numeric_fields:
        values = np.asarray(result.fields[name], dtype=float)
        normalized = [None if not np.isfinite(value) else round(float(value), 10) for value in values]
        finite_indexes = np.flatnonzero(np.isfinite(values))
        numeric[name] = {
            "null_count": int(np.count_nonzero(~np.isfinite(values))),
            "first_finite_index": int(finite_indexes[0]) if len(finite_indexes) else None,
            "values_sha256": stable_sha256(normalized),
        }
    boolean: dict[str, Any] = {}
    for name in boolean_fields:
        values = np.asarray(result.fields[name], dtype=bool)
        indexes = np.flatnonzero(values).astype(int).tolist()
        boolean[name] = {
            "count": len(indexes),
            "values_sha256": stable_sha256(values.tolist()),
        }
    return {"numeric": numeric, "boolean": boolean}


def stable_sha256(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _verify_strict_real_sample_invariants(module: ModuleType, bars: Mapping[str, list[Any]], batch: Any) -> None:
    for end in range(1, len(bars["datetime"]) + 1):
        prefix_args = [bars[column][:end] for column in INPUT_COLUMNS]
        prefix = module.compute_htdy_strict(*prefix_args)
        for name in module.NUMERIC_FIELDS:
            actual = prefix.fields[name][-1]
            expected = batch.fields[name][end - 1]
            if np.isnan(expected):
                if not np.isnan(actual):
                    raise AssertionError(f"strict prefix mismatch for {name} at {end - 1}: expected NaN")
            elif not np.isclose(actual, expected, atol=1e-12, rtol=1e-12):
                raise AssertionError(f"strict prefix mismatch for {name} at {end - 1}")
        for name in module.BOOLEAN_FIELDS:
            if bool(prefix.fields[name][-1]) is not bool(batch.fields[name][end - 1]):
                raise AssertionError(f"strict prefix mismatch for {name} at {end - 1}")

    changed = {name: list(values) for name, values in bars.items()}
    changed_index = len(changed["datetime"]) - 16
    stable_end = changed_index - 8
    changed["high"][changed_index] += 80.0
    changed["low"][changed_index] -= 50.0
    changed["close"][changed_index] += 25.0
    changed_result = module.compute_htdy_strict(*[changed[column] for column in INPUT_COLUMNS])
    for name in module.NUMERIC_FIELDS:
        np.testing.assert_allclose(
            batch.fields[name][:stable_end], changed_result.fields[name][:stable_end], equal_nan=True, atol=1e-12, rtol=1e-12
        )
    for name in module.BOOLEAN_FIELDS:
        np.testing.assert_array_equal(batch.fields[name][:stable_end], changed_result.fields[name][:stable_end])


def _verify_capability_boundary(original: Mapping[str, Any], strict: Mapping[str, Any]) -> None:
    if original["status"] != "observation_only" or original["repainting_risk"] != "known":
        raise AssertionError("original capability boundary changed")
    if strict["status"] != "strict_research_candidate" or strict["closed_bar_only"] is not True:
        raise AssertionError("strict capability boundary changed")
    for metadata in (original, strict):
        for key in ("backtest_capable", "live_capable", "alert_capable", "trading_capable"):
            if metadata[key] is not False:
                raise AssertionError(f"capability boundary changed: {key}")


def _verify_frozen_policies(
    policies: Mapping[str, Any],
    original_module: ModuleType,
    strict_module: ModuleType,
    original: Any,
    strict: Any,
    strict_summary: Mapping[str, Any],
) -> None:
    original_policy = policies["original"]
    strict_policy = policies["strict"]
    if original.metadata["indicator_version"] != original_policy["indicator_version"]:
        raise AssertionError("original indicator version drifted")
    if strict.metadata["indicator_version"] != strict_policy["indicator_version"]:
        raise AssertionError("strict indicator version drifted")
    if strict.metadata["xma_replacement_policy"] != strict_policy["xma_replacement_policy"]:
        raise AssertionError("strict XMA replacement policy drifted")
    if list(original_module.NUMERIC_FIELDS) != original_policy["numeric_fields"]:
        raise AssertionError("original numeric field whitelist drifted")
    if list(original_module.BOOLEAN_FIELDS) != original_policy["boolean_fields"]:
        raise AssertionError("original boolean field whitelist drifted")
    if list(strict_module.NUMERIC_FIELDS) != strict_policy["numeric_fields"]:
        raise AssertionError("strict numeric field whitelist drifted")
    if list(strict_module.BOOLEAN_FIELDS) != strict_policy["boolean_fields"]:
        raise AssertionError("strict boolean field whitelist drifted")
    actual_warmup = {
        name: values["first_finite_index"] for name, values in strict_summary["numeric"].items()
    }
    if actual_warmup != strict_policy["first_finite_index"]:
        raise AssertionError(f"strict warm-up policy drifted: {actual_warmup}")


def _assert_summary(name: str, actual: Mapping[str, Any], expected: Mapping[str, Any]) -> None:
    if actual != expected:
        raise AssertionError(
            f"{name} Golden Sample summary mismatch\nexpected={json.dumps(expected, ensure_ascii=False, sort_keys=True)}"
            f"\nactual={json.dumps(actual, ensure_ascii=False, sort_keys=True)}"
        )


def _web_bundle(manifest: Mapping[str, Any], sample: GoldenSample, original: Any, module: ModuleType) -> dict[str, Any]:
    fields = {}
    for name in ("zk1", "zd1", "zd2", "yellow_candle", "white_candle", "buy_observation", "sell_observation", "xg"):
        values = original.fields[name]
        if name in module.NUMERIC_FIELDS:
            fields[name] = [None if not np.isfinite(value) else float(value) for value in values]
        else:
            fields[name] = np.asarray(values, dtype=bool).tolist()
    return {
        "sample": {
            "input_sha256": sample.input_sha256,
            "row_count": len(sample.bars["datetime"]),
            "bars": _serializable_bars(sample.bars),
        },
        "python_original": fields,
        "comparison": manifest["comparison"],
    }


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


def _validate_ohlcv(rows: Sequence[Mapping[str, Any]]) -> None:
    for index, row in enumerate(rows):
        values = [float(row[field]) for field in ("open", "high", "low", "close", "volume")]
        if not all(np.isfinite(value) for value in values):
            raise ValueError(f"sample has non-finite OHLCV at index {index}")
        open_, high, low, close, volume = values
        if high < max(open_, close) or low > min(open_, close) or high < low or volume < 0:
            raise ValueError(f"sample has invalid OHLCV at index {index}")


def _as_naive_datetime(value: Any) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    return parsed.replace(tzinfo=None)


def _iso(value: Any) -> str:
    return _as_naive_datetime(value).isoformat(timespec="seconds")


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify the fixed read-only HTDY JM Golden Sample.")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH)
    parser.add_argument("--source", type=Path, help=f"Canonical parquet path; alternatively set {SOURCE_ENV}.")
    parser.add_argument("--export-web-bundle", type=Path, help="Optional generated bundle for the Node Web comparison.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest = load_manifest(args.manifest)
    source_path = resolve_source_path(manifest, args.source)
    sample = read_golden_sample(source_path, manifest)
    result = verify_golden_sample(manifest, sample, export_web_bundle=args.export_web_bundle)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
