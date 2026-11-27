"""Explicit formal assembly for the existing, source-pinned SuBing Paper run."""

from argparse import ArgumentParser
from importlib import import_module
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import os
import subprocess
import sys


CANDIDATE = Path(__file__).resolve().parents[3]
FROZEN_WORKER = "2be7a62af8cd38be67d9d1b671e132673e44f91e"


def load(name, path, *, package=False):
    spec = spec_from_file_location(name, path, submodule_search_locations=[str(path.parent)] if package else None)
    if spec is None or spec.loader is None or name in sys.modules:
        raise ValueError("PORTFOLIO_COMPUTE_MODULE_UNPROVEN")
    module = module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_candidate(paper_root):
    frozen_api = paper_root / "services/quant-api"
    frozen_core = paper_root / "packages/quant-core"
    sys.path[:0] = [str(frozen_api), str(frozen_core), str(paper_root)]
    worker = import_module("app.subing_portfolio_worker")
    if Path(worker.__file__).resolve() != frozen_api / "app/subing_portfolio_worker.py":
        raise ValueError("PORTFOLIO_FROZEN_WORKER_UNPROVEN")

    api = CANDIDATE / "services/quant-api"
    runtime = api / "app/compute_runtime"
    artifacts = load("_paper_compute_artifact", runtime / "artifact.py")
    lock, core = artifacts.locked_core(api / "quant-core-release.toml")
    compute = core / "compute/__init__.py"
    kernel = load("guiyi_quant.compute", compute, package=True)
    if (kernel.RESULT_SCHEMA_VERSION != lock["result_schema_version"]
            or kernel.STATE_SCHEMA_VERSION != lock["state_schema_version"]):
        raise ValueError("PORTFOLIO_COMPUTE_CONTRACT_INCOMPATIBLE")
    market = api / "app/market_data"
    load("app.market_data.market_foundation_scope", market / "market_foundation_scope.py")
    envelope = load("app.market_data.compute_target_observations", market / "observation_stream.py")
    load("app.compute_runtime", runtime / "__init__.py", package=True)
    from app.compute_runtime.paper_consumer import continue_frozen_paper

    return worker, envelope.ObservationStream, continue_frozen_paper


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--paper-root", type=Path, required=True)
    args = parser.parse_args()
    root = args.paper_root.resolve(strict=True)
    if root != args.paper_root:
        raise ValueError("PORTFOLIO_FROZEN_WORKER_UNPROVEN")
    git = ["/usr/bin/git", "-c", "core.fsmonitor=false", "-C", str(root)]
    try:
        commit = subprocess.run(
            [*git, "rev-parse", "--verify", "HEAD"], capture_output=True, text=True, check=True,
        ).stdout.strip()
        dirty = subprocess.run(
            [*git, "status", "--porcelain", "--untracked-files=all", "--",
             "services/quant-api/app", "packages/quant-core/guiyi_quant", "scripts/research"],
            capture_output=True, text=True, check=True,
        ).stdout
    except subprocess.CalledProcessError:
        raise ValueError("PORTFOLIO_FROZEN_WORKER_UNPROVEN") from None
    if commit != FROZEN_WORKER or dirty:
        raise ValueError("PORTFOLIO_FROZEN_WORKER_UNPROVEN")
    worker, stream_class, launch = load_candidate(root)
    os.chdir(root)
    sys.argv[1:] = ["--refresh-facts"]
    launch(worker, stream_class=stream_class,
           private_config=Path.home() / "Library/Application Support/GuiyiQuant/project.env")


if __name__ == "__main__":
    main()
