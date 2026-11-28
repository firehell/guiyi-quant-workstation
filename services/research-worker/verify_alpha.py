"""Check VeighNa Alpha input compatibility with a frozen physical futures feature export."""

import argparse
from collections import Counter
from datetime import UTC, datetime
import gzip
from hashlib import file_digest
import json
from math import isfinite
from pathlib import Path

import polars as pl
from vnpy.alpha.dataset.template import AlphaDataset
from vnpy.alpha.dataset.utility import calculate_by_expression

FEATURES = ("ema_slope_atr", "atr_close", "return_1")
LABEL_CODES = {"TREND_DOWN": -1, "RANGE": 0, "TREND_UP": 1, "DISPUTED": 2}
KEYS = ["datetime", "vt_symbol"]


def alpha_roundtrip(rows, label_column):
    if label_column not in ("regime_label", "forward_label"):
        raise ValueError("RESEARCH_LABEL_UNSUPPORTED")
    if not rows:
        raise ValueError("ALPHA_SAMPLE_EMPTY")
    frame = pl.DataFrame(rows).sort(KEYS)
    if frame.select(KEYS).is_duplicated().any():
        raise ValueError("ALPHA_DUPLICATE_SAMPLE")
    if not frame.select(pl.all_horizontal(pl.col(*FEATURES, label_column).is_finite()).all()).item():
        raise ValueError("ALPHA_INPUT_NONFINITE")
    # Only raw_df is used in this probe. No training split or processor runs.
    window = (frame["datetime"].min().date().isoformat(), frame["datetime"].max().date().isoformat())
    dataset = AlphaDataset(frame.select(*KEYS, label_column), window, window, window)
    for name in FEATURES:
        dataset.add_feature(name, result=frame.select(*KEYS, pl.col(name).alias("data")))
    dataset.set_label(label_column)
    dataset.prepare_data(max_workers=1)
    expected = frame.select(*KEYS, *FEATURES, pl.col(label_column).alias("label"))
    # Tests exact alignment and values without calling any fit, process or tear sheet.
    if not dataset.raw_df.equals(expected):
        raise ValueError("ALPHA_EXTERNAL_INPUT_MISMATCH")
    inference = dataset.raw_df.select(*KEYS, *FEATURES)
    actual_lag = calculate_by_expression(inference, "ts_delay(return_1, 1)")["data"]
    expected_lag = inference.select(pl.col("return_1").shift(1).over("vt_symbol")).to_series()
    if not actual_lag.equals(expected_lag):
        raise ValueError("ALPHA_SEGMENT_LAG_MISMATCH")
    return len(expected)


def verify(path, *, contract, since, through):
    if since > through:
        raise ValueError("RESEARCH_WINDOW_INVALID")
    with gzip.open(path, "rt", encoding="utf-8") as source:
        raw = [row for line in source if (row := json.loads(line))["contract"] == contract
               and row["owned"] and since <= row["day"] <= through]
    segments = {row["segment"] for row in raw}
    if not raw or len(segments) != 1 or {row["frequency"] for row in raw} != {"60m"}:
        raise ValueError("RESEARCH_PHYSICAL_SEGMENT_REQUIRED")
    raw.sort(key=lambda row: row["time"])
    labels = []
    forward = []
    for i, row in enumerate(raw):
        label = row["reference"]["label"]
        if row["features"] is None or label not in LABEL_CODES:
            continue
        point = {
            "datetime": datetime.fromisoformat(row["time"]).astimezone(UTC).replace(tzinfo=None),
            "vt_symbol": f"{contract}:{row['segment']}",
            **{name: row["features"][name] for name in FEATURES},
        }
        labels.append({**point, "regime_label": LABEL_CODES[label]})
        # Compatibility probe only. This is a completed-Bar price label tied to
        # this segment, with the next complete Bar as its starting observation.
        if (i + 3 < len(raw) and row["day"] == raw[i + 3]["day"]
                and all(isfinite(item["close"]) and item["close"] > 0 for item in raw[i + 1:i + 4])):
            label_value = raw[i + 3]["close"] / raw[i + 1]["close"] - 1
            forward.append({**point, "forward_label": label_value})
    with path.open("rb") as handle:
        source_digest = file_digest(handle, "sha256").hexdigest()
    return {
        "contract": contract, "frequency": "60m", "segment": next(iter(segments)),
        "days": [raw[0]["day"], raw[-1]["day"]], "source_sha256": source_digest,
        "source_rows": len(raw), "features": FEATURES,
        "existing_label_counts": dict(Counter(row["regime_label"] for row in labels)),
        "existing_label_rows_verified": alpha_roundtrip(labels, "regime_label"),
        "external_forward_label_rows_verified": alpha_roundtrip(forward, "forward_label"),
        "inference_features": FEATURES,
        "checked_operator": "ts_delay(return_1, 1)",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("feature_export", type=Path)
    parser.add_argument("--contract", required=True)
    parser.add_argument("--since", required=True)
    parser.add_argument("--through", required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.feature_export, contract=args.contract, since=args.since, through=args.through),
                     indent=2, allow_nan=False))
