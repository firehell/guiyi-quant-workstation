"""Pinned SDK account readback / explicit observe initialization. Never trades."""
import argparse
from contextlib import contextmanager
from dataclasses import asdict
from datetime import UTC, datetime
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
from types import SimpleNamespace


class ReadOnlyTraderAPI:
    ALLOWED = frozenset({'RegisterSpi', 'RegisterFront', 'SubscribePrivateTopic', 'Init', 'Release',
        'ReqAuthenticate', 'ReqUserLogin', 'ReqQryTradingAccount', 'ReqQryInvestorPosition',
        'ReqQryOrder', 'ReqQryTrade'})

    def __init__(self, api):
        self._api = api

    def __getattr__(self, name):
        if name not in self.ALLOWED:
            raise ValueError('BOOTSTRAP_NATIVE_READ_ONLY')
        return getattr(self._api, name)


def options(argv=None):
    parser = argparse.ArgumentParser(description='独立SimNow账户只读核验/仅观察初始化')
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--deadline', type=datetime.fromisoformat, required=True)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--read-only', action='store_true')
    action.add_argument('--initialize-observe', action='store_true')
    return parser.parse_args(argv)


def check_deadline(deadline, *, now=None):
    now = now or datetime.now(UTC)
    if deadline.tzinfo is None or deadline.utcoffset() is None or now >= deadline:
        raise ValueError('BOOTSTRAP_DEADLINE_REACHED')


@contextmanager
def quiet_native():
    """Native libraries must not print credentials, addresses or raw diagnostics."""
    sink = os.open(os.devnull, os.O_WRONLY)
    saved = [os.dup(1), os.dup(2)]
    try:
        os.dup2(sink, 1)
        os.dup2(sink, 2)
        yield
    finally:
        for target, old in zip((1, 2), saved, strict=True):
            os.dup2(old, target)
            os.close(old)
        os.close(sink)


def _module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class NativeReader:
    def __init__(self, settings, module, connector, check):
        self.settings, self.module, self.connector, self.check = settings, module, connector, check
        self.stage = 'NOT_CONNECTED'
        self.broker_io = False
        self.credentials_loaded = False
        self.diagnostics = None

    def __call__(self):
        from guiyi_quant.simnow_execution.credentials import CredentialStore
        self.check()
        self.stage = 'CREDENTIAL_LOAD'
        credentials = CredentialStore().load(self.settings.account_id)
        if credentials.account_id != self.settings.account_id:
            raise ValueError('CREDENTIAL_IDENTITY_MISMATCH')
        self.credentials_loaded = True
        gateway = None
        with quiet_native(), tempfile.TemporaryDirectory(prefix='guiyi-observe-bootstrap-') as flow:
            try:
                gateway = self.module.Gateway(credentials.user, credentials.password, initial_funds_timeout=45)
                del credentials
                create = self.module.tdapi.CThostFtdcTraderApi.CreateFtdcTraderApi
                facade = SimpleNamespace(CThostFtdcTraderApi=SimpleNamespace(
                    CreateFtdcTraderApi=lambda directory: ReadOnlyTraderAPI(create(directory))))
                self.stage = 'NATIVE_LOGIN'
                self.broker_io = True
                self.connector(gateway, facade, flow)
                self.check()
                self.stage = 'ACCOUNT_SNAPSHOT'
                report = gateway.snapshot()
                self.check()
                self.stage = 'READ_COMPLETE'
                return report
            finally:
                if gateway is not None:
                    try:
                        try:
                            self.diagnostics = gateway.inventory_diagnostics()
                        except Exception:
                            self.diagnostics = None
                        if gateway.api is not None:
                            try:
                                gateway.api.RegisterSpi(None)
                            finally:
                                gateway.api.Release()
                    finally:
                        gateway.user = gateway.password = ''


def _private_output(path):
    if (not path.is_absolute() or path.resolve(strict=False) != path or path.is_symlink()
            or not path.parent.is_dir()):
        raise ValueError('BOOTSTRAP_OUTPUT_INVALID')
    parent = path.parent.stat()
    if parent.st_uid != os.getuid() or stat.S_IMODE(parent.st_mode) != 0o700:
        raise ValueError('BOOTSTRAP_OUTPUT_NOT_PRIVATE')
    return os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)


def probe_summary(snapshot):
    from guiyi_quant.simnow_execution.observe_bootstrap import _require_flat
    flat = True
    try:
        _require_flat(snapshot)
    except ValueError:
        flat = False
    return dict(status='READ_ONLY_COMPLETE', account_read_complete=True,
        balance_verified=True, positions_verified=True, flat_verified=flat,
        account_reconciled=False, old_account_state='UNKNOWN', new_account_state='UNINITIALIZED',
        execution_permitted=False, mode='observe', enabled=False)


def main(argv=None):
    args = options(argv)
    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root / 'packages/quant-core'))
    from guiyi_quant.simnow_execution.settings import load_settings
    from guiyi_quant.simnow_execution.observe_bootstrap import probe_account, initialize_observe
    reader = None
    stage = 'CONFIG'
    output = None
    try:
        def check():
            check_deadline(args.deadline)
        check()
        settings = load_settings(args.config)
        if settings.schema != 3 or settings.project_root != root:
            raise ValueError('BOOTSTRAP_PREPARATION_SOURCE_MISMATCH')
        stage = 'SDK_BOOTSTRAP'
        bounded = _module('guiyi_observe_bounded', root / 'scripts/broker/simnow_controlled.py')
        with quiet_native():
            sdk = bounded.bootstrap(root, settings.api_env)
        # The existing dependency loader is the authority; no secret enters output.
        from app.private_settings import private_dependency_settings
        runner = _module('guiyi_observe_environment', root / 'scripts/broker/simnow_supervisor.py')
        env, _ = private_dependency_settings(Path.home() / 'Library/Application Support/GuiyiQuant/project.env')
        os.environ.update(runner.dependency_environment(env))
        os.environ['GUIYI_PROJECT_ROOT'] = str(root)
        os.environ['GUIYI_OBSERVATION_STREAM_ENABLED'] = '1'
        if os.environ.get('GUIYI_OBSERVE_BOOTSTRAP_READY') != '1':
            os.environ['GUIYI_OBSERVE_BOOTSTRAP_READY'] = '1'
            os.execv(sys.executable, [sys.executable, '-I', '-B', str(Path(__file__).resolve()), *sys.argv[1:]])
        check()
        output = _private_output(args.output)
        reader = NativeReader(settings, sdk, bounded.connect, check)
        stage = 'ACCOUNT_READ'
        if args.read_only:
            snapshot = probe_account(args.config, reader, now=lambda: datetime.now(UTC), check=check)
            result = probe_summary(snapshot)
            private = {**result, 'snapshot': asdict(snapshot)}
        else:
            from app.market_data.operational_universe import load_operational_products
            from app.runtime_cohort_host import CohortHost
            def closed():
                window = CohortHost().session_proof()
                return window['mode'] == 'closed_idle' and all(x['phase'] == 'CLOSED' for x in window['phases'].values())
            products = tuple(sorted(p.upper() for p in load_operational_products()))
            result = initialize_observe(args.config, products, reader, now=lambda: datetime.now(UTC),
                assert_closed=closed, check=check)
            result.update(status='OBSERVE_INITIALIZED')
            private = result
        with os.fdopen(output, 'w') as stream:
            output = None
            json.dump({**private, 'credentials_loaded': reader.credentials_loaded,
                'broker_io': reader.broker_io}, stream, sort_keys=True, default=str)
            stream.flush()
            os.fsync(stream.fileno())
        print(json.dumps({**result, 'evidence_path': str(args.output)}))
        return 0
    except Exception as error:
        result = dict(status='BLOCKED', error_type=type(error).__name__, stage=reader.stage if reader else stage,
            credentials_loaded=bool(reader and reader.credentials_loaded), broker_io=bool(reader and reader.broker_io),
            execution_permitted=False)
        if output is not None:
            with os.fdopen(output, 'w') as stream:
                json.dump({**result, 'diagnostics': reader.diagnostics if reader else None}, stream)
                stream.flush()
                os.fsync(stream.fileno())
        print(json.dumps(result))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
