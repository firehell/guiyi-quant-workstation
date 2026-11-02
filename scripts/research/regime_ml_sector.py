"""Three predeclared sector holdouts on the last DEVELOPMENT fold; never sealed test."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import numpy as np
from scripts.research.regime_ml_train import fit_predict
from scripts.research.regime_ml_core import fold_masks, metrics, gate

SECTORS = ("agriculture", "chemical", "nonferrous")


def run(cache, output):
    manifest = json.loads((cache / "manifest.json").read_text())
    if manifest["role"] != "DEVELOPMENT_ONLY" or manifest["sealed_test_evaluated"]:
        raise ValueError("SECTOR_SOURCE_INVALID")
    output.mkdir(parents=True, exist_ok=False)
    plan = dict(
        source=manifest["source_dataset_id"],
        sectors=SECTORS,
        frequencies=["30m", "60m"],
        model="tcn",
        seed=17,
        fold=2,
        scope="held-out sector excluded from training and preprocessing; remaining seven sectors not separately tested",
        test_evaluated=False,
    )
    (output / "protocol.json").write_text(json.dumps(plan, indent=2))
    results = []
    for entry in manifest["files"]:
        if entry["frequency"] not in plan["frequencies"]:
            continue
        file = cache / entry["file"]
        if sha256(file.read_bytes()).hexdigest() != entry["sha256"]:
            raise ValueError("CACHE_CHANGED")
        with np.load(file, allow_pickle=False) as f:
            data = {k: f[k] for k in f.files}
        train, val = fold_masks(data, manifest["splits"]["folds"][2])
        for sector in SECTORS:
            sid = manifest["sectors"].index(sector)
            ti = np.flatnonzero(train & (data["label"] >= 0) & (data["sector"] != sid))
            vi = np.flatnonzero(val & (data["sector"] == sid))
            folder = output / entry["frequency"] / sector
            folder.mkdir(parents=True)
            if len(vi) < 30 or any(
                (data["label"][ti] == c).sum() < 30 for c in range(3)
            ):
                results.append(
                    dict(
                        frequency=entry["frequency"],
                        sector=sector,
                        status="DATA_INSUFFICIENT",
                    )
                )
                continue
            if set(data["product"][ti]) & set(data["product"][vi]):
                raise ValueError("SECTOR_PRODUCT_LEAK")
            pred, prob, resource = fit_predict("tcn", data, ti, vi, 17, folder)
            base = metrics(data, vi, data["baseline"][vi])
            measured = metrics(data, vi, pred)
            r = dict(
                frequency=entry["frequency"],
                sector=sector,
                status="DEVELOPMENT_EVALUATED",
                baseline=base,
                metrics=measured,
                gate=gate(base, measured),
                resource=resource,
            )
            np.savez_compressed(
                folder / "predictions.npz",
                indices=vi,
                prediction=pred,
                probability=prob,
            )
            (folder / "report.json").write_text(json.dumps(r, indent=2))
            results.append(r)
            print(
                json.dumps(
                    dict(
                        frequency=entry["frequency"],
                        sector=sector,
                        f1=measured["macro_f1"],
                        baseline_f1=base["macro_f1"],
                        gate=r["gate"],
                    )
                ),
                flush=True,
            )
    (output / "report.json").write_text(json.dumps(results, indent=2))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cache", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    run(a.cache, a.output)
