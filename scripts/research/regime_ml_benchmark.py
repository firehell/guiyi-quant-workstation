"""Bounded synthetic resource benchmark in an isolated environment, not market evidence."""

import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import resource
import time


def run(output):
    os.environ.setdefault("OMP_NUM_THREADS", "2")
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "2")
    import numpy as np
    import torch
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler

    torch.set_num_threads(2)
    torch.manual_seed(17)
    rng = np.random.default_rng(17)
    x = rng.normal(size=(2048, 9)).astype("float32")
    y = np.arange(len(x)) % 3
    x = StandardScaler().fit_transform(x)
    result = dict(
        role="SYNTHETIC_RESOURCE_ONLY_NOT_MARKET_VALIDATION",
        architecture=platform.machine(),
        python=platform.python_version(),
        cpus=os.cpu_count(),
        threads=2,
        packages={
            n: importlib.metadata.version(n) for n in ("numpy", "scikit-learn", "torch")
        },
        timings={},
    )
    for name, model in [
        ("logistic", LogisticRegression(max_iter=100)),
        (
            "tree",
            HistGradientBoostingClassifier(
                max_iter=20, early_stopping=False, random_state=17
            ),
        ),
    ]:
        start = time.perf_counter()
        model.fit(x, y)
        p = model.predict_proba(x)
        assert p.shape == (2048, 3) and np.isfinite(p).all()
        result["timings"][name] = time.perf_counter() - start
    result["mps_built"] = torch.backends.mps.is_built()
    result["mps_available"] = torch.backends.mps.is_available()
    device = "mps" if result["mps_available"] else "cpu"
    try:
        a = torch.randn(16, 9, 64, device=device)
        net = torch.nn.Sequential(
            torch.nn.Conv1d(9, 16, 3), torch.nn.ReLU(), torch.nn.Conv1d(16, 3, 3)
        ).to(device)
        opt = torch.optim.Adam(net.parameters(), lr=0.001)
        start = time.perf_counter()
        for _ in range(20):
            opt.zero_grad()
            loss = net(a).square().mean()
            loss.backward()
            opt.step()
        if device == "mps":
            torch.mps.synchronize()
        result["timings"]["conv_20_steps"] = time.perf_counter() - start
        result["device_execution"] = device
        result["device_test_passed"] = bool(torch.isfinite(loss).item())
    except Exception as exc:
        result["device_execution"] = device
        result["device_test_passed"] = False
        result["device_error_type"] = type(exc).__name__
    result["peak_rss_native_units"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    output.write_text(json.dumps(result, indent=2))
    print(json.dumps(result))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    run(p.parse_args().output)
