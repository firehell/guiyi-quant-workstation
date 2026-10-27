"""Pinned isolated-SDK entrypoint for one continuous SimNow account host."""

import argparse
from datetime import UTC, datetime
import importlib.util
import os
from pathlib import Path
import signal
import sys


def options(argv=None):
    parser = argparse.ArgumentParser(
        description="SimNow持续宿主：默认配置observe，不开放新仓"
    )
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--observe-only", action="store_true")
    parser.add_argument(
        "--check", action="store_true", help="仅校验配置/兼容性，不读凭据或连接"
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = options(argv)
    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root / "packages/quant-core"))
    from guiyi_quant.simnow_execution.settings import load_settings

    settings = load_settings(args.config)
    if settings.project_root != root or (
        args.observe_only and settings.mode != "observe"
    ):
        raise ValueError("CONTINUOUS_SOURCE_OR_MODE_INVALID")
    spec = importlib.util.spec_from_file_location(
        "guiyi_bounded_composition", root / "scripts/broker/simnow_controlled.py"
    )
    bounded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bounded)
    module = bounded.bootstrap(root, settings.api_env)
    if args.check:
        print("CONTINUOUS_CONFIG_SDK_COMPATIBLE_NO_BROKER_IO")
        return 0
    if not settings.enabled:
        print("CONTINUOUS_DISABLED")
        return 0
    # Importing the private loader may initialize API module globals. Re-exec
    # once with validated dependencies before composing the market reader.
    from app.private_settings import private_dependency_settings

    env, _ = private_dependency_settings(
        Path.home() / "Library/Application Support/GuiyiQuant/project.env"
    )
    env["PGOPTIONS"] = "-c default_transaction_read_only=on"
    if "REDIS_PASSWORD" not in env and "POSTGRES_PASSWORD" in env:
        env["REDIS_PASSWORD"] = env["POSTGRES_PASSWORD"]
    if "REDIS_URL" not in env and env.get("REDIS_PASSWORD"):
        from urllib.parse import quote

        env["REDIS_URL"] = (
            "redis://:" + quote(env["REDIS_PASSWORD"], safe="") + "@127.0.0.1:6379/0"
        )
    os.environ.update(env)
    if os.environ.get("GUIYI_SIMNOW_DEPENDENCIES_READY") != "1":
        os.environ["GUIYI_SIMNOW_DEPENDENCIES_READY"] = "1"
        os.execv(
            sys.executable,
            [sys.executable, "-I", str(Path(__file__).resolve()), *sys.argv[1:]],
        )
    from app.market_data.operational_universe import load_operational_products
    from app.simnow_portfolio_market import PortfolioMarket
    from guiyi_quant.simnow_execution.native_portfolio import NativePortfolio
    from guiyi_quant.simnow_execution.supervisor import Supervisor

    stopping = [False]

    def stop(_signal, _frame):
        stopping[0] = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    products = tuple(sorted(p.upper() for p in load_operational_products()))
    market = PortfolioMarket(products)

    def factory(config, folder):
        return NativePortfolio(
            config, folder, module, bounded.connect, now=lambda: datetime.now(UTC)
        )

    supervisor = Supervisor(
        settings, products, market, factory, stopped=lambda: stopping[0]
    )
    # Native SDK diagnostics may include account fields. Never route them to launchd logs.
    saved = os.dup(1), os.dup(2)
    try:
        with open(os.devnull, "w") as sink:
            os.dup2(sink.fileno(), 1)
            os.dup2(sink.fileno(), 2)
            result = supervisor.run()
    finally:
        for source, target in zip(saved, (1, 2)):
            os.dup2(source, target)
            os.close(source)
    print("CONTINUOUS_" + result)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        raise SystemExit("CONTINUOUS_START_FAILED_NO_ORDER_PROOF") from None
