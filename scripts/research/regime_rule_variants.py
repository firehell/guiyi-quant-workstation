"""Nine bounded v2 timing profiles, using the shared direction state kernel."""

import argparse
import gzip
from hashlib import sha256
import json
from pathlib import Path
import numpy as np
from guiyi_quant.indicators.subing_range import direction_transition
from scripts.research.regime_ml_core import fold_masks, metrics, gate

PROFILES = [(d, n) for d in (1, 2, 3) for n in (2, 3, 4)]
CLASSES = {"RANGE": 0, "TREND_UP": 1, "TREND_DOWN": 2, "UNKNOWN": -2}


def run(dataset, cache, output):
    snapshot = json.loads((dataset / "snapshot.json").read_text())
    manifest = json.loads((cache / "manifest.json").read_text())
    identity = sha256(
        json.dumps(
            snapshot,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()
    if (
        identity != manifest["source_dataset_id"]
        or manifest["role"] != "DEVELOPMENT_ONLY"
        or manifest["sealed_test_evaluated"]
    ):
        raise ValueError("RULE_SOURCE_IDENTITY_INVALID")
    output.mkdir(parents=True, exist_ok=False)
    report = []
    for item in manifest["files"]:
        path = cache / item["file"]
        if sha256(path.read_bytes()).hexdigest() != item["sha256"]:
            raise ValueError("CACHE_CHANGED")
        with np.load(path, allow_pickle=False) as f:
            data = {k: f[k] for k in f.files}
        lookup = {
            (int(data["product"][i]), int(data["time"][i])): i
            for i in np.flatnonzero(data["owned"])
        }
        if len(lookup) != int(data["owned"].sum()):
            raise ValueError("DUPLICATE_OWNER_ENDPOINT")
        predictions = np.full((9, len(data["day"])), -2, dtype="int8")
        found = set()
        for entry in snapshot["rows"]:
            if entry["frequency"] != item["frequency"]:
                continue
            file = dataset / entry["file"]
            if (
                file.resolve().parent != dataset.resolve()
                or sha256(file.read_bytes()).hexdigest() != entry["sha256"]
            ):
                raise ValueError("SOURCE_CHANGED")
            product = manifest["products"].index(entry["symbol"])
            segment = None
            from datetime import datetime

            with gzip.open(file, "rt") as stream:
                for line in stream:
                    b = json.loads(line)
                    if b["day"] >= manifest["splits"]["test_from"]:
                        continue
                    if b["segment"] != segment:
                        segment = b["segment"]
                        states = [(None, 0, None, 0) for _ in PROFILES]
                    ready = b["baseline"] != "UNKNOWN"
                    if not ready:
                        states = [(None, 0, None, 0) for _ in PROFILES]
                    else:
                        states = [
                            direction_transition(
                                *state,
                                b["trend_direction"],
                                direction_bars=d,
                                neutral_bars=n,
                            )
                            for state, (d, n) in zip(states, PROFILES)
                        ]
                    if not b["owned"]:
                        continue
                    key = (product, int(datetime.fromisoformat(b["time"]).timestamp()))
                    if key not in lookup:
                        raise ValueError("RULE_ENDPOINT_MISSING")
                    i = lookup[key]
                    found.add(i)
                    for j, state in enumerate(states):
                        predictions[j, i] = (
                            -2
                            if not ready
                            else CLASSES["TREND_" + state[2]]
                            if state[2]
                            else 0
                        )
                    if predictions[PROFILES.index((2, 3)), i] != data["baseline"][i]:
                        raise ValueError("FIXED_V2_PARITY_FAILED")
        if len(found) != int(data["owned"].sum()):
            raise ValueError("RULE_COVERAGE_INCOMPLETE")
        for fold_number, fold in enumerate(manifest["splits"]["folds"]):
            _, val = fold_masks(data, fold)
            indices = np.flatnonzero(val)
            base = metrics(data, indices, data["baseline"][indices])
            for j, (d, n) in enumerate(PROFILES):
                measured = metrics(data, indices, predictions[j, indices])
                result = dict(
                    frequency=item["frequency"],
                    fold=fold_number,
                    model=f"v2_{d}_{n}",
                    baseline=base,
                    metrics=measured,
                    gate=gate(base, measured),
                )
                report.append(result)
        np.savez_compressed(output / f"{item['frequency']}.npz", prediction=predictions)
        print(
            json.dumps(
                dict(
                    frequency=item["frequency"], fixed_v2_parity=True, owned=len(found)
                )
            ),
            flush=True,
        )
    (output / "report.json").write_text(json.dumps(report, indent=2))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dataset", type=Path, required=True)
    p.add_argument("--cache", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    run(a.dataset, a.cache, a.output)
