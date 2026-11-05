"""Pair learned fold predictions with seen human development labels, without backdating models."""

from collections import Counter
from datetime import datetime
import json
from pathlib import Path
import numpy as np
from hashlib import sha256
from scripts.research.regime_ml_core import fold_masks


def validate_training_protocol(manifest, training):
    protocol = json.loads((training / "protocol.json").read_text())
    if (
        manifest.get("role") != "DEVELOPMENT_ONLY"
        or manifest.get("sealed_test_evaluated") is not False
        or protocol.get("source") != manifest["source_dataset_id"]
        or protocol.get("test_evaluated") is not False
    ):
        raise ValueError("MANUAL_TRAINING_IDENTITY_INVALID")
    return protocol


def validate_fold_prediction(data, fold, indices, prediction):
    _, mask = fold_masks(data, fold)
    if (
        not np.array_equal(indices, np.flatnonzero(mask))
        or prediction.shape != indices.shape
        or not np.isin(prediction, (0, 1, 2)).all()
    ):
        raise ValueError("MANUAL_PREDICTION_FOLD_INVALID")


def run(root, training, output):
    cache = root / "regime-model-development-20261102/data"
    manifest = json.loads((cache / "manifest.json").read_text())
    validate_training_protocol(manifest, training)
    queries = []
    rounds = [
        (
            "static90",
            root / "regime-learning-20261102-final",
            root / "regime-owner-review-20261102-81d9376e/owner-answers.json",
        ),
        (
            "static24_ema",
            root / "regime-calibration-20261102-final",
            root / "regime-owner-calibration-20261102-2f72105c/owner-answers.json",
        ),
    ]
    labels = {"RANGE": 0, "TREND_UP": 1, "TREND_DOWN": 2, "UNCERTAIN": -1}
    for name, folder, answer in rounds:
        public = json.loads(
            (folder / "index.html")
            .read_text()
            .split("const DATA=", 1)[1]
            .split(";\nconst $=", 1)[0]
        )
        a = json.loads(answer.read_text())
        if public["dataset_id"] != a["dataset_id"]:
            raise ValueError("MANUAL_IDENTITY_CHANGED")
        for s in public["samples"]:
            queries.append(
                dict(
                    round=name,
                    id=s["id"],
                    symbol=s["symbol"],
                    frequency=s["frequency"],
                    time=s["bars"][-1]["time"],
                    answer=labels[a["answers"][s["id"]]["answer"]],
                )
            )
    folder = root / "regime-boundary-review-20261102-final"
    public = json.loads((folder / "boundary.json").read_text())
    a = json.loads(
        (
            root / "regime-boundary-owner-20261102-82be4cab/owner-answers.json"
        ).read_text()
    )
    if public["dataset_id"] != a["dataset_id"]:
        raise ValueError("MANUAL_IDENTITY_CHANGED")
    for s in public["samples"]:
        for e in a["answers"][s["id"]]:
            queries.append(
                dict(
                    round="sequential100_binary",
                    id=s["id"] + f"-{e['cut']}",
                    symbol=s["symbol"],
                    frequency=s["frequency"],
                    time=s["bars"][e["cut"] - 1]["time"],
                    answer=0
                    if e["choice"] == "range"
                    else 1
                    if e["choice"] == "not_yet"
                    else -1,
                )
            )
    results = []
    for entry in manifest["files"]:
        if sha256((cache / entry["file"]).read_bytes()).hexdigest() != entry["sha256"]:
            raise ValueError("MANUAL_CACHE_CHANGED")
        with np.load(cache / entry["file"], allow_pickle=False) as f:
            data = {k: f[k] for k in f.files}
        lookup = {
            (manifest["products"][int(data["product"][i])], int(data["time"][i])): i
            for i in np.flatnonzero(data["owned"])
        }
        mappings = {}
        for number in range(3):
            for model in ("logistic", "tree", "tcn"):
                file = (
                    training
                    / entry["frequency"]
                    / str(number)
                    / f"{model}-predictions.npz"
                )
                if not file.exists():
                    continue
                with np.load(file, allow_pickle=False) as p:
                    validate_fold_prediction(
                        data,
                        manifest["splits"]["folds"][number],
                        p["indices"],
                        p["prediction"],
                    )
                    mappings[(number, model)] = {
                        int(i): int(v) for i, v in zip(p["indices"], p["prediction"])
                    }
        for q in queries:
            if q["frequency"] != entry["frequency"]:
                continue
            i = lookup.get(
                (q["symbol"], int(datetime.fromisoformat(q["time"]).timestamp()))
            )
            predictions = {model: None for model in ("logistic", "tree", "tcn")}
            fold = None
            for (number, model), mapping in mappings.items():
                if i in mapping:
                    if fold is not None and fold != number:
                        raise ValueError("MULTIPLE_CAUSAL_FOLDS")
                    fold = number
                    predictions[model] = mapping[i]
            baseline = int(data["baseline"][i]) if i is not None else None
            if q["round"] == "sequential100_binary":
                baseline = 0 if baseline == 0 else 1 if baseline in (1, 2) else None
                predictions = {
                    k: (0 if v == 0 else 1 if v in (1, 2) else None)
                    for k, v in predictions.items()
                }
            results.append(
                dict(q, fold=fold, baseline=baseline, predictions=predictions)
            )
    summary = {}
    for round_name in ("static90", "static24_ema", "sequential100_binary"):
        summary[round_name] = {}
        for model in ("logistic", "tree", "tcn"):
            c = Counter(
                available=0,
                unavailable=0,
                uncertain=0,
                baseline_agreement=0,
                candidate_agreement=0,
                baseline_conflict=0,
                candidate_conflict=0,
            )
            for r in results:
                if r["round"] != round_name:
                    continue
                if r["answer"] == -1:
                    c["uncertain"] += 1
                    continue
                pred = r["predictions"][model]
                if pred is None or r["baseline"] is None:
                    c["unavailable"] += 1
                    continue
                c["available"] += 1
                c[
                    "baseline_agreement"
                    if r["baseline"] == r["answer"]
                    else "baseline_conflict"
                ] += 1
                c[
                    "candidate_agreement"
                    if pred == r["answer"]
                    else "candidate_conflict"
                ] += 1
            summary[round_name][model] = dict(c)
    report = dict(
        role="SEEN_HUMAN_DEVELOPMENT_DIAGNOSTIC_NOT_OOS",
        unavailable="No causal fold model at that date, or 64-bar validation boundary purge; never use later-trained model",
        summary=summary,
        rows=results,
    )
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(summary))


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, default=Path("output"))
    p.add_argument("--training", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    run(a.root, a.training, a.output)
