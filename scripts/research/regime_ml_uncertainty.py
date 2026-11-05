"""Paired product/calendar-month block resampling on development folds only."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import numpy as np
from scripts.research.regime_ml_manual import (
    validate_training_protocol,
    validate_fold_prediction,
)


def macro(confusion):
    tp = np.diag(confusion[:, :3])
    fn = confusion.sum(axis=1) - tp
    fp = confusion[:, :3].sum(axis=0) - tp
    den = 2 * tp + fn + fp
    return float(np.divide(2 * tp, den, out=np.zeros(3), where=den > 0).mean())


def paired_blocks(data, indices, prediction, seed=101, repetitions=300):
    keep = data["label"][indices] >= 0
    ix = indices[keep]
    pred = prediction[keep]
    blocks = []
    global_months = np.unique(data["day"][ix] // 100)
    for product in np.unique(data["product"][ix]):
        mask = data["product"][ix] == product
        px = ix[mask]
        pp = pred[mask]
        if len(px) < 30:
            continue
        months = data["day"][px] // 100
        unique = global_months
        base = np.zeros((len(unique), 3, 4))
        trial = base.copy()
        for j, month in enumerate(unique):
            sel = months == month
            y = data["label"][px[sel]]
            b = data["baseline"][px[sel]]
            p = pp[sel]
            np.add.at(base[j], (y, np.where(b >= 0, b, 3)), 1)
            np.add.at(trial[j], (y, np.where(p >= 0, p, 3)), 1)
        blocks.append((base, trial))
    if len(blocks) < 10:
        return dict(status="INSUFFICIENT_PRODUCTS", products=len(blocks))
    rng = np.random.default_rng(seed)
    draws = []
    for _ in range(repetitions):
        deltas = []
        chosen = rng.integers(0, len(global_months), len(global_months))
        for product in rng.integers(0, len(blocks), len(blocks)):
            base, trial = blocks[product]
            if base[chosen].sum() == 0:
                continue
            deltas.append(
                macro(trial[chosen].sum(axis=0)) - macro(base[chosen].sum(axis=0))
            )
        if deltas:
            draws.append(float(np.mean(deltas)))
    point = float(
        np.mean([macro(t.sum(axis=0)) - macro(b.sum(axis=0)) for b, t in blocks])
    )
    return dict(
        status="DEVELOPMENT_ESTIMATE",
        products=len(blocks),
        point_delta=point,
        interval95=np.quantile(draws, [0.025, 0.975]).tolist(),
        repetitions=len(draws),
        seed=seed,
        method="resample products equally and shared calendar-month blocks jointly across all sampled products; not iid bars",
        limitations="exploratory weak-reference development interval; shared month blocks preserve same-month shocks but not dependence beyond months",
    )


def run(cache, training, output):
    manifest = json.loads((cache / "manifest.json").read_text())
    validate_training_protocol(manifest, training)
    report = {}
    for entry in manifest["files"]:
        path = cache / entry["file"]
        if sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
            raise ValueError("CACHE_CHANGED")
        with np.load(path, allow_pickle=False) as f:
            data = {k: f[k] for k in f.files}
        report[entry["frequency"]] = {}
        for model in ("logistic", "tree", "tcn"):
            indices = []
            prediction = []
            for number in range(3):
                path = (
                    training
                    / entry["frequency"]
                    / str(number)
                    / f"{model}-predictions.npz"
                )
                if not path.exists():
                    continue
                with np.load(path, allow_pickle=False) as f:
                    validate_fold_prediction(
                        data,
                        manifest["splits"]["folds"][number],
                        f["indices"],
                        f["prediction"],
                    )
                    indices.extend(f["indices"])
                    prediction.extend(f["prediction"])
            if not indices:
                continue
            if len(set(indices)) != len(indices):
                raise ValueError("DUPLICATE_VALIDATION_ENDPOINT")
            report[entry["frequency"]][model] = paired_blocks(
                data, np.asarray(indices), np.asarray(prediction)
            )
    output.write_text(json.dumps(report, indent=2))
    print(json.dumps(report))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cache", type=Path, required=True)
    p.add_argument("--training", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    run(a.cache, a.training, a.output)
