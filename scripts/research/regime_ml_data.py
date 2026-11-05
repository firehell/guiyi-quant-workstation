"""Build causal development-only ML inputs from the verified frozen research export."""

from collections import Counter, deque
from datetime import datetime
import gzip
from hashlib import sha256
import json
from pathlib import Path

import numpy as np
from app.market_data.new_subing_research import payload_hash
from scripts.research.regime_ml_core import fold_masks

FEATURES = (
    "return_1",
    "body_atr",
    "range_atr",
    "close_ema_atr",
    "ema_slope_atr",
    "er",
    "chop",
    "atr_close",
    "volatility_5",
    "volatility_20",
)
CLASSES = {"RANGE": 0, "TREND_UP": 1, "TREND_DOWN": 2, "DISPUTED": -1, "UNKNOWN": -2}


def build(dataset, output):
    snapshot = json.loads((dataset / "snapshot.json").read_text())
    run = json.loads((dataset / "run.json").read_text())
    if (
        run["status"] != "WAIT_LABEL_REVIEW"
        or payload_hash(snapshot) != run["dataset_id"]
    ):
        raise ValueError("ML_SOURCE_IDENTITY_INVALID")
    output.mkdir(parents=True, exist_ok=False)
    code_hash = sha256(Path(__file__).read_bytes()).hexdigest()
    products = sorted({x["symbol"] for x in snapshot["rows"]})
    sectors = []
    manifest = []
    for frequency in ("1d", "30m", "60m"):
        collected = []
        serial = 0
        stats = Counter()
        for entry in snapshot["rows"]:
            if entry["frequency"] != frequency:
                continue
            path = dataset / entry["file"]
            if (
                path.resolve().parent != dataset.resolve()
                or sha256(path.read_bytes()).hexdigest() != entry["sha256"]
            ):
                raise ValueError("ML_SOURCE_CHANGED")
            segment = None
            started = False
            pending = deque(maxlen=63)
            history = deque(maxlen=64)
            with gzip.open(path, "rt") as stream:
                for line in stream:
                    b = json.loads(line)
                    if b["day"] >= snapshot["splits"]["test_from"]:
                        continue
                    if b["segment"] != segment:
                        segment = b["segment"]
                        serial += 1
                        started = False
                        pending = deque(maxlen=63)
                        history = deque(maxlen=64)
                    f = b["features"]
                    xs = [
                        float(f[k]) if f and f.get(k) is not None else float("nan")
                        for k in FEATURES
                    ]
                    valid = all(np.isfinite(xs))
                    history.append((int(b["day"].replace("-", "")), valid))
                    eligible = len(history) == 64 and all(v for _, v in history)
                    if b["sector"] not in sectors:
                        sectors.append(b["sector"])
                    record = (
                        xs,
                        b["owned"],
                        eligible,
                        CLASSES[b["reference"]["label"]],
                        CLASSES[b["baseline"]],
                        products.index(b["symbol"]),
                        sectors.index(b["sector"]),
                        serial,
                        int(datetime.fromisoformat(b["time"]).timestamp()),
                        int(b["day"].replace("-", "")),
                        history[0][0],
                    )
                    if not b["owned"]:
                        if started:
                            raise ValueError("ML_OWNER_NOT_CONTIGUOUS")
                        pending.append(record)
                        continue
                    if b["partition"] != "DEVELOPMENT":
                        # Retain raw features as context; eligibility must remain false for excluded endpoints.
                        record = record[:2] + (False,) + record[3:]
                    if not started:
                        collected.extend(pending)
                        started = True
                    collected.append(record)
                    stats["owned"] += 1
                    stats["eligible"] += bool(record[2])
                    if record[2]:
                        stats[b["reference"]["label"]] += 1
        if not collected:
            raise ValueError("ML_NO_DEVELOPMENT_ROWS")
        fields = (
            "x",
            "owned",
            "eligible",
            "label",
            "baseline",
            "product",
            "sector",
            "segment",
            "time",
            "day",
            "start_day",
        )
        arrays = {}
        for i, name in enumerate(fields):
            dtype = (
                "float32"
                if name == "x"
                else "bool"
                if name in ("owned", "eligible")
                else "int64"
            )
            arrays[name] = np.asarray([r[i] for r in collected], dtype=dtype)
        # Every eligible endpoint has a real complete same-segment input window.
        indices = np.flatnonzero(arrays["owned"] & arrays["eligible"])
        if np.any(indices < 63) or np.any(
            arrays["segment"][indices] != arrays["segment"][indices - 63]
        ):
            raise ValueError("ML_WINDOW_CROSSES_SEGMENT")
        file = output / f"{frequency}.npz"
        np.savez_compressed(file, **arrays)
        fold_counts = []
        for fold in snapshot["splits"]["folds"]:
            train, val = fold_masks(arrays, fold)
            fold_counts.append(
                dict(
                    train=int(train.sum()),
                    validation=int(val.sum()),
                    train_classes=[
                        int((train & (arrays["label"] == c)).sum()) for c in range(3)
                    ],
                    validation_classes=[
                        int((val & (arrays["label"] == c)).sum()) for c in range(3)
                    ],
                )
            )
        manifest.append(
            dict(
                frequency=frequency,
                file=file.name,
                sha256=sha256(file.read_bytes()).hexdigest(),
                stats=dict(stats),
                folds=fold_counts,
            )
        )
        print(json.dumps(manifest[-1]), flush=True)
    if sha256(Path(__file__).read_bytes()).hexdigest() != code_hash:
        raise ValueError("ML_CODE_CHANGED")
    info = dict(
        source_dataset_id=run["dataset_id"],
        features=FEATURES,
        classes=CLASSES,
        products=products,
        sectors=sectors,
        splits=snapshot["splits"],
        files=manifest,
        code_hash=code_hash,
        role="DEVELOPMENT_ONLY",
        label_status="WEAK_PRICE_PATH_REFERENCE_NOT_HUMAN_TRUTH",
        sealed_test_evaluated=False,
    )
    (output / "manifest.json").write_text(json.dumps(info, indent=2))


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dataset", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    build(a.dataset, a.output)
