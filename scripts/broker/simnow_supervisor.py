"""Pinned isolated-SDK entrypoint for one continuous SimNow account host."""

import argparse
from datetime import UTC, datetime
import importlib.util
import os
from pathlib import Path
import signal
import sys

_STARTUP_STAGE = "CONFIG"


def dependency_environment(values):
    """Match run-local-service.sh's shared Redis default; never print values."""
    from urllib.parse import quote

    env = dict(values)
    env["PGOPTIONS"] = "-c default_transaction_read_only=on"
    password = env.get("REDIS_PASSWORD") or env.get("POSTGRES_PASSWORD")
    if password:
        env["REDIS_PASSWORD"] = password
        if env.get("REDIS_URL") in (None, "", "redis://127.0.0.1:6379/0"):
            env["REDIS_URL"] = (
                "redis://:" + quote(password, safe="") + "@127.0.0.1:6379/0"
            )
    return env


def options(argv=None):
    parser = argparse.ArgumentParser(
        description="SimNow持续宿主：默认配置observe，不开放新仓"
    )
    parser.add_argument("--config", type=Path, required=True)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--observe-only", action="store_true")
    modes.add_argument(
        "--trade", action="store_true", help="仅与schema2 trade配置共同开放持续交易能力"
    )
    checks = parser.add_mutually_exclusive_group()
    checks.add_argument(
        "--check", action="store_true", help="仅校验配置/兼容性，不读凭据或连接"
    )
    checks.add_argument(
        "--check-keychain",
        action="store_true",
        help="仅验证本进程Keychain加载，不连接Broker",
    )
    return parser.parse_args(argv)


def main(argv=None):
    global _STARTUP_STAGE
    args = options(argv)
    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root / "packages/quant-core"))
    from guiyi_quant.simnow_execution.settings import load_settings

    settings = load_settings(args.config)
    if settings.project_root != root or (
        args.observe_only
        and settings.mode != "observe"
        or args.trade != (settings.mode == "trade")
    ):
        raise ValueError("CONTINUOUS_SOURCE_OR_MODE_INVALID")
    if args.check_keychain:
        _STARTUP_STAGE = "KEYCHAIN_CHECK"
        from guiyi_quant.simnow_execution.credentials import CredentialStore

        credentials = CredentialStore().load(settings.account_id)
        if credentials.account_id != settings.account_id:
            raise ValueError("CREDENTIAL_IDENTITY_MISMATCH")
        del credentials
        print("CONTINUOUS_KEYCHAIN_LOAD_VERIFIED_NO_BROKER_IO")
        return 0
    spec = importlib.util.spec_from_file_location(
        "guiyi_bounded_composition", root / "scripts/broker/simnow_controlled.py"
    )
    bounded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bounded)
    _STARTUP_STAGE = "SDK_BOOTSTRAP"
    module = bounded.bootstrap(root, settings.api_env)
    if args.check:
        print("CONTINUOUS_CONFIG_SDK_COMPATIBLE_NO_BROKER_IO")
        return 0
    if not settings.enabled:
        print("CONTINUOUS_DISABLED")
        return 0
    # Importing the private loader may initialize API module globals. Re-exec
    # once with validated dependencies before composing the market reader.
    _STARTUP_STAGE = "PRIVATE_DEPENDENCIES"
    from app.private_settings import private_dependency_settings

    env, _ = private_dependency_settings(
        Path.home() / "Library/Application Support/GuiyiQuant/project.env"
    )
    os.environ.update(dependency_environment(env))
    if os.environ.get("GUIYI_SIMNOW_DEPENDENCIES_READY") != "1":
        os.environ["GUIYI_SIMNOW_DEPENDENCIES_READY"] = "1"
        os.execv(
            sys.executable,
            [sys.executable, "-I", str(Path(__file__).resolve()), *sys.argv[1:]],
        )
    _STARTUP_STAGE = "MARKET_IMPORT"
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
    _STARTUP_STAGE = "MARKET_SUBSCRIPTION"
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
    _STARTUP_STAGE = "SUPERVISOR_START"
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
    except Exception as exc:
        # Fixed phase and exception class only; never native error text or values.
        credential_code = (
            str(exc)
            if str(exc)
            in {
                "CREDENTIAL_UNAVAILABLE",
                "CREDENTIAL_CORRUPT",
                "CREDENTIAL_IDENTITY_MISMATCH",
                "MACOS_KEYCHAIN_REQUIRED",
                "MACOS_KEYCHAIN_UNAVAILABLE",
            }
            else "STARTUP_UNAVAILABLE"
        )
        raise SystemExit(
            "CONTINUOUS_START_FAILED_NO_ORDER_PROOF phase="
            + _STARTUP_STAGE
            + " type="
            + type(exc).__name__
            + " code="
            + credential_code
        ) from None
