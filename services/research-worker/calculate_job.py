"""Run registered research calculations with serialized inputs."""

from importlib.metadata import version
import json
import os
from pathlib import Path
import platform
from statistics import mean
import sys
from threading import Thread
from time import sleep
import tomllib



def backtest(payload):
    from performance import calculate, daily_returns

    if payload["coverage"]["reason"]:
        return {"performance": None, "unavailable": {"performance": payload["coverage"]["reason"]}}
    policy = payload["policy"]
    rows = [row for row in payload["samples"] if row["record_type"] == "settlement"]
    levels = {row["trading_day"]: row["equity"] for row in rows}
    values = daily_returns(list(levels), levels, policy["initial_equity"],
                           external_cash_flow=policy["external_cash_flow"])
    result = calculate(values, periods=policy["annual_periods"])
    return {"performance": result, "unavailable": {
        name: "SAMPLE_INSUFFICIENT_OR_ZERO_DENOMINATOR"
        for name in ("sharpe", "sortino", "calmar") if result[name] is None
    }}


def factor(payload):
    import pandas as pd
    from scipy.stats import spearmanr

    rows = payload["samples"]
    if len(rows) < 3 or len({row["feature"] for row in rows}) < 2 or len({row["label"] for row in rows}) < 2:
        return {"factor": None, "unavailable": {"factor": "SAMPLE_INSUFFICIENT_OR_CONSTANT"}}
    x = [row["feature"] for row in rows]
    y = [float(row["label"]) for row in rows]
    ranks = pd.qcut(pd.Series(x), q=4, labels=False, duplicates="drop") + 1
    groups = {
        str(int(group)): {"n": len(part), "mean_label": float(part.mean())}
        for group, part in pd.Series(y).groupby(ranks)
    }
    return {"factor": {"n": len(rows), "spearman": float(spearmanr(x, y).statistic), "mean_label": mean(y)},
            "factor_groups": groups, "unavailable": {}}


def event(payload):
    rows = payload["samples"]
    groups = {key: [float(row["label"]) for row in rows if row["confirmed"] == seen]
              for key, seen in (("confirmed", True), ("control", False))}
    return {"event": {name: {"n": len(values), "mean_label": mean(values) if values else None}
                      for name, values in groups.items()},
            "unavailable": {name: "SAMPLE_INSUFFICIENT" for name, values in groups.items() if not values}}


ANALYSES = {"backtest": backtest, "factor": factor, "event": event}


def watch_parent(parent):
    while os.getppid() == parent and parent != 1:
        sleep(0.25)
    os._exit(1)


def environment(kind):
    dependencies = {"backtest": ("quantstats", "pandas", "numpy"), "factor": ("scipy", "pandas", "numpy"),
                    "event": ()}
    lock = tomllib.loads(Path(__file__).with_name("uv.lock").read_text())
    locked = {row["name"]: row["version"] for row in lock["package"]}
    actual = {package: version(package) for package in dependencies[kind]}
    if sys.version_info[:2] != (3, 13) or any(locked[name] != value for name, value in actual.items()):
        raise ValueError("RESEARCH_ENVIRONMENT_LOCK_MISMATCH")
    return {"python": platform.python_version(), "architecture": platform.machine(), "packages": actual}


def main():
    Thread(target=watch_parent, args=(os.getppid(),), daemon=True).start()
    payload = json.load(sys.stdin)
    kind = payload["source"]["kind"]
    runtime = environment(kind)
    result = ANALYSES[kind](payload)
    print(json.dumps({**result, "worker_environment": runtime}, allow_nan=False))


if __name__ == "__main__":
    main()
