"""Fixed local development comparison. Never opens sealed-test rows or promotes a model."""

import os

os.environ.setdefault("OMP_NUM_THREADS", "2")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "2")
import argparse
from hashlib import sha256
import json
from pathlib import Path
import time

import joblib
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
import torch
from torch import nn
from torch.nn import functional as F
from scripts.research.regime_ml_core import fold_masks, product_weights, metrics, gate


class CausalTCN(nn.Module):
    def __init__(self, features):
        super().__init__()
        self.layers = nn.ModuleList(
            [
                nn.Conv1d(features if i == 0 else 16, 16, 2, dilation=2**i)
                for i in range(6)
            ]
        )
        self.head = nn.Linear(16, 3)

    def sequence(self, x):
        x = x.transpose(1, 2)
        for i, layer in enumerate(self.layers):
            x = F.relu(layer(F.pad(x, (2**i, 0))))
        return self.head(x.transpose(1, 2))

    def forward(self, x):
        return self.sequence(x)[:, -1]


def tabular(x, indices):
    windows = x[indices[:, None] - np.arange(63, -1, -1)[None, :]]
    return np.concatenate(
        [windows[:, -1], windows.mean(axis=1), windows.std(axis=1)], axis=1
    )


def sample_train(indices, products, seed):
    rng = np.random.default_rng(seed)
    chosen = []
    for p in np.unique(products[indices]):
        xs = indices[products[indices] == p]
        chosen.extend(rng.choice(xs, min(len(xs), 2000), replace=False))
    return np.array(sorted(chosen))


def fit_predict(name, data, train, validation, seed, folder):
    torch.set_num_threads(2)
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    chosen = sample_train(train, data["product"], seed)
    weights = product_weights(data["product"][chosen])
    y = data["label"][chosen]
    if set(y) != {0, 1, 2}:
        raise ValueError("TRAIN_CLASSES_INSUFFICIENT")
    x = data["x"]
    start = time.perf_counter()
    if name in ("logistic", "tree"):
        xt = tabular(x, chosen)
        scaler = StandardScaler().fit(xt, sample_weight=weights)
        xt = scaler.transform(xt)
        model = (
            LogisticRegression(C=1.0, max_iter=500)
            if name == "logistic"
            else HistGradientBoostingClassifier(
                max_iter=100,
                max_leaf_nodes=15,
                min_samples_leaf=30,
                l2_regularization=1.0,
                learning_rate=0.05,
                early_stopping=False,
                random_state=seed,
            )
        )
        model.fit(xt, y, sample_weight=weights)
        predictions = []
        probabilities = []
        for offset in range(0, len(validation), 2048):
            xx = scaler.transform(tabular(x, validation[offset : offset + 2048]))
            prob = model.predict_proba(xx)
            predictions.extend(model.classes_[prob.argmax(axis=1)])
            probabilities.extend(prob)
        joblib.dump(dict(model=model, scaler=scaler), folder / f"{name}.joblib")
        restored = joblib.load(folder / f"{name}.joblib")
        probe = tabular(x, validation[:10])
        assert np.array_equal(
            restored["model"].predict(restored["scaler"].transform(probe)),
            np.asarray(predictions)[:10],
        )
    else:
        # Fit normalization only to selected training windows; product equal row weights.
        sample = tabular(x, chosen)[:, : x.shape[1]]
        scaler = StandardScaler().fit(sample, sample_weight=weights)
        mean = torch.tensor(scaler.mean_, dtype=torch.float32)
        scale = torch.tensor(scaler.scale_, dtype=torch.float32)
        model = CausalTCN(x.shape[1])
        optimizer = torch.optim.AdamW(model.parameters(), lr=0.001, weight_decay=0.0001)
        for epoch in range(3):
            epoch_indices = rng.choice(
                len(chosen),
                min(len(chosen), 60000),
                replace=True,
                p=weights / weights.sum(),
            )
            model.train()
            for offset in range(0, len(epoch_indices), 256):
                ix = chosen[epoch_indices[offset : offset + 256]]
                batch = torch.from_numpy(
                    x[ix[:, None] - np.arange(63, -1, -1)[None, :]]
                )
                target = torch.from_numpy(data["label"][ix]).long()
                optimizer.zero_grad()
                loss = F.cross_entropy(model((batch - mean) / scale), target)
                loss.backward()
                optimizer.step()
            print(
                json.dumps(
                    dict(model=name, epoch=epoch + 1, train_samples=len(chosen))
                ),
                flush=True,
            )
        model.eval()
        probabilities = []
        with torch.no_grad():
            for offset in range(0, len(validation), 512):
                ix = validation[offset : offset + 512]
                batch = torch.from_numpy(
                    x[ix[:, None] - np.arange(63, -1, -1)[None, :]]
                )
                probabilities.extend(
                    torch.softmax(model((batch - mean) / scale), dim=1).numpy()
                )
        predictions = np.asarray(probabilities).argmax(axis=1)
        torch.save(
            dict(state=model.state_dict(), mean=mean, scale=scale, features=x.shape[1]),
            folder / "tcn.pt",
        )
        saved = torch.load(folder / "tcn.pt", weights_only=True)
        restored = CausalTCN(saved["features"])
        restored.load_state_dict(saved["state"])
        restored.eval()
        with torch.no_grad():
            ix = validation[:10]
            probe = (
                torch.from_numpy(x[ix[:, None] - np.arange(63, -1, -1)[None, :]]) - mean
            ) / scale
            assert torch.equal(model(probe), restored(probe))
    prob = np.asarray(probabilities, dtype="float32")
    pred = np.asarray(predictions, dtype="int64")
    if not np.isfinite(prob).all() or not np.allclose(prob.sum(axis=1), 1.0, atol=1e-5):
        raise ValueError("PROBABILITY_INVALID")
    return (
        pred,
        prob,
        dict(seconds=time.perf_counter() - start, training_rows=len(chosen), seed=seed),
    )


def run(cache, output, names, seed, frequencies=("1d", "30m", "60m")):
    manifest = json.loads((cache / "manifest.json").read_text())
    if manifest["role"] != "DEVELOPMENT_ONLY" or manifest["sealed_test_evaluated"]:
        raise ValueError("SEALED_FORBIDDEN")
    output.mkdir(parents=True, exist_ok=False)
    protocol = dict(
        source=manifest["source_dataset_id"],
        frequencies=frequencies,
        models=names,
        configs_per_model=1,
        seed=seed,
        training="price_path_20_40_v1 weak reference, DISPUTED excluded",
        input="64 completed bars; 10 dimensionless features; no identity in X",
        tabular="last/mean/std across 64",
        tcn="6 causal conv layers, 16 channels, kernel2 dilations1..32, 3 epochs",
        products="max2000/product deterministic sample; equal product weight",
        threads=2,
        device="cpu",
        code_hash=sha256(Path(__file__).read_bytes()).hexdigest(),
        core_hash=sha256(
            Path(__file__).with_name("regime_ml_core.py").read_bytes()
        ).hexdigest(),
        test_evaluated=False,
    )
    (output / "protocol.json").write_text(json.dumps(protocol, indent=2))
    report = []
    for entry in manifest["files"]:
        if entry["frequency"] not in frequencies:
            continue
        file = cache / entry["file"]
        if sha256(file.read_bytes()).hexdigest() != entry["sha256"]:
            raise ValueError("CACHE_CHANGED")
        with np.load(file, allow_pickle=False) as saved:
            data = {k: saved[k] for k in saved.files}
        for number, fold in enumerate(manifest["splits"]["folds"]):
            trainmask, valmask = fold_masks(data, fold)
            train = np.flatnonzero(trainmask & (data["label"] >= 0))
            validation = np.flatnonzero(valmask)
            folder = output / entry["frequency"] / str(number)
            folder.mkdir(parents=True)
            base = metrics(data, validation, data["baseline"][validation])
            for name in names:
                pred, prob, resource = fit_predict(
                    name, data, train, validation, seed, folder
                )
                measured = metrics(data, validation, pred)
                result = dict(
                    frequency=entry["frequency"],
                    fold=number,
                    model=name,
                    baseline=base,
                    metrics=measured,
                    gate=gate(base, measured),
                    resource=resource,
                )
                np.savez_compressed(
                    folder / f"{name}-predictions.npz",
                    indices=validation,
                    probability=prob,
                    prediction=pred,
                )
                (folder / f"{name}-report.json").write_text(
                    json.dumps(result, indent=2)
                )
                report.append(result)
                print(
                    json.dumps(
                        dict(
                            frequency=entry["frequency"],
                            fold=number,
                            model=name,
                            f1=measured["macro_f1"],
                            baseline_f1=base["macro_f1"],
                            gate=result["gate"],
                        )
                    ),
                    flush=True,
                )
    if (
        sha256(Path(__file__).read_bytes()).hexdigest() != protocol["code_hash"]
        or sha256(
            Path(__file__).with_name("regime_ml_core.py").read_bytes()
        ).hexdigest()
        != protocol["core_hash"]
    ):
        raise ValueError("CODE_CHANGED")
    (output / "report.json").write_text(json.dumps(report, indent=2))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cache", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument(
        "--models",
        nargs="+",
        choices=["logistic", "tree", "tcn"],
        default=["logistic", "tree", "tcn"],
    )
    p.add_argument("--seed", type=int, default=17)
    p.add_argument(
        "--frequencies",
        nargs="+",
        choices=["1d", "30m", "60m"],
        default=["1d", "30m", "60m"],
    )
    a = p.parse_args()
    run(a.cache, a.output, a.models, a.seed, a.frequencies)
