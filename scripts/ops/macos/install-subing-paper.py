"""Render or explicitly install sole shared Paper supervision (no trading broker)."""
import argparse
import importlib.util
import os
from pathlib import Path
import plistlib
import subprocess

LABEL = 'com.guiyi.quant-subing-paper'


def render(root, home):
    return dict(Label=LABEL, ProgramArguments=['/bin/bash', str(root / 'scripts/ops/macos/run-subing-paper.sh'), str(root)],
        WorkingDirectory=str(home), RunAtLoad=True, KeepAlive=True, ThrottleInterval=60,
        ProcessType='Background', ExitTimeOut=20,
        StandardOutPath=str(home / 'Library/Logs/GuiyiQuant/subing-paper.stdout.log'),
        StandardErrorPath=str(home / 'Library/Logs/GuiyiQuant/subing-paper.stderr.log'))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--database-url-file', type=Path)
    parser.add_argument('--install', action='store_true')
    args = parser.parse_args()
    root, home = args.root, Path.home()
    if not root.is_absolute() or root.resolve(strict=True) != root:
        raise ValueError('PAPER_SOURCE_ROOT_INVALID')
    if not (root / 'services/quant-api/.venv/bin/python').is_file():
        raise ValueError('PAPER_PYTHON_MISSING')
    value = render(root, home)
    if not args.install:
        print(plistlib.dumps(value).decode())
        return
    from app.private_settings import read_private_settings_content
    from app.subing_portfolio_paths import STATE_ROOT, DB_PATH
    STATE_ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    if STATE_ROOT.is_symlink() or STATE_ROOT.resolve() != STATE_ROOT or STATE_ROOT.stat().st_mode & 0o077:
        raise ValueError('PAPER_PRIVATE_ROOT_UNSAFE')
    if not DB_PATH.exists():
        if args.database_url_file is None:
            raise ValueError('PAPER_DATABASE_BINDING_REQUIRED')
        content = read_private_settings_content(args.database_url_file)
        fd = os.open(DB_PATH, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'wb') as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    else:
        read_private_settings_content(DB_PATH)
    directory = home / 'Library/LaunchAgents'
    directory.mkdir(exist_ok=True)
    if directory.resolve(strict=True) != directory:
        raise ValueError('PAPER_LAUNCHAGENTS_PATH_INVALID')
    (home / 'Library/Logs/GuiyiQuant').mkdir(parents=True, exist_ok=True)
    path = directory / (LABEL + '.plist')
    if path.is_symlink():
        raise ValueError('PAPER_LAUNCHER_SYMLINK')
    raw = plistlib.dumps(value)
    if path.exists() and path.read_bytes() != raw:
        raise ValueError('PAPER_EXISTING_LAUNCHER_DIFFERS_STOP_OLD_OWNER_FIRST')
    if not path.exists():
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'wb') as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
    domain = f'gui/{os.getuid()}'
    loaded = subprocess.run(['/bin/launchctl', 'print', f'{domain}/{LABEL}'], capture_output=True, text=True)
    if loaded.returncode:
        if not any(code in loaded.stderr for code in ('Could not find service', 'Could not find specified service')):
            raise ValueError('PAPER_LAUNCHD_STATE_UNKNOWN')
        subprocess.run(['/bin/launchctl', 'bootstrap', domain, str(path)], check=True)
    loaded = subprocess.run(['/bin/launchctl', 'print', f'{domain}/{LABEL}'], capture_output=True, text=True, check=True)
    # Reuse the established exact loaded-source verifier without starting old JM.
    spec = importlib.util.spec_from_file_location('legacy_launchd_identity', Path(__file__).with_name('install-subing-model.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.verify_loaded(loaded.stdout, value)
    print('SUBING_SHARED_PAPER_LOADED_IDENTITY_VERIFIED; BUSINESS_STATUS_REQUIRES_SEPARATE_READBACK')


if __name__ == '__main__':
    main()
