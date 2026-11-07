"""Explicit install of the owner-authorized independent development observer."""
import argparse
import os
from pathlib import Path
import plistlib
import subprocess

LABEL = 'com.guiyi.quant-subing-development-model'


def render(root, home):
    return dict(Label=LABEL, ProgramArguments=['/bin/bash', str(root / 'scripts/ops/macos/run-subing-model.sh'), str(root)],
        WorkingDirectory=str(home), RunAtLoad=True, KeepAlive=True, ThrottleInterval=60,
        ProcessType='Background', ExitTimeOut=20,
        StandardOutPath=str(home / 'Library/Logs/GuiyiQuant/subing-model.stdout.log'),
        StandardErrorPath=str(home / 'Library/Logs/GuiyiQuant/subing-model.stderr.log'))


def verify_loaded(output, value):
    from app.runtime_identity import launchd_arguments
    if launchd_arguments(output) != tuple(value['ProgramArguments']):
        raise ValueError('MODEL_LOADED_ARGUMENTS_DIFFER')
    fields = {}
    depth = 0
    for raw in output.splitlines():
        line = raw.strip()
        if line.endswith((' = {', ' => {')):
            depth += 1
        elif line == '}':
            depth -= 1
        elif depth == 1:
            for key in ('working directory', 'program'):
                prefix = key + ' = '
                if line.startswith(prefix):
                    if key in fields:
                        raise ValueError('MODEL_LOADED_IDENTITY_AMBIGUOUS')
                    fields[key] = line[len(prefix):]
    if depth != 0 or fields != {'working directory': value['WorkingDirectory'], 'program': '/bin/bash'}:
        raise ValueError('MODEL_LOADED_SOURCE_UNVERIFIED')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--install', action='store_true')
    parser.add_argument('--allow-canonical-conflict-rebaseline', action='store_true')
    args = parser.parse_args()
    root, home = args.root, Path.home()
    if not root.is_absolute() or root.resolve(strict=True) != root:
        raise ValueError('MODEL_SOURCE_ROOT_INVALID')
    # Only use the persistent original development source and original run.
    # This tree must not be a host-managed candidate or a disposable release.
    if str(root) != '/Volumes/扩展盘/guiyi-quant-workstation':
        raise ValueError('MODEL_STABLE_DEVELOPMENT_ROOT_REQUIRED')
    result = subprocess.run([str(root / 'services/quant-api/.venv/bin/python'),
        '-m', 'app.subing_model_service', '--check'], cwd=root,
        env={**os.environ, 'PYTHONPATH': f'{root}:{root}/services/quant-api:{root}/packages/quant-core'},
        capture_output=True, check=False)
    if result.returncode:
        raise ValueError('MODEL_ORIGINAL_REPLAY_CHECK_FAILED')
    value = render(root, home)
    if not args.install:
        print(plistlib.dumps(value).decode())
        return
    directory = home / 'Library/LaunchAgents'
    directory.mkdir(exist_ok=True)
    if directory.resolve(strict=True) != directory:
        raise ValueError('MODEL_LAUNCHAGENTS_PATH_INVALID')
    (home / 'Library/Logs/GuiyiQuant').mkdir(parents=True, exist_ok=True)
    path = directory / (LABEL + '.plist')
    raw = plistlib.dumps(value)
    if path.exists() and path.read_bytes() != raw:
        raise ValueError('MODEL_EXISTING_LAUNCHER_DIFFERS')
    if path.is_symlink():
        raise ValueError('MODEL_LAUNCHER_SYMLINK')
    if not path.exists():
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'wb') as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
    if args.allow_canonical_conflict_rebaseline:
        import json
        from app.subing_model_service import atomic
        from app.subing_model_recovery import CONFLICT_POLICY
        from app.subing_projection_source import registered_source
        model_root = registered_source('model_root')
        if model_root != root / '.run':
            raise ValueError('MODEL_SUPERVISION_SOURCE_DIFFERS')
        active = json.loads((model_root / 'subing-model-active.json').read_text())
        atomic(model_root / 'subing-model-supervision.json', dict(schema_version=1,
            run_id=active['run_id'], conflict_policy=CONFLICT_POLICY))
    domain = f'gui/{os.getuid()}'
    loaded = subprocess.run(['/bin/launchctl', 'print', f'{domain}/{LABEL}'], capture_output=True, text=True)
    exists = loaded.returncode == 0
    if not exists and not any(code in loaded.stderr for code in ('Could not find service', 'Could not find specified service')):
        raise ValueError('MODEL_LAUNCHD_STATE_UNKNOWN')
    if not exists:
        subprocess.run(['/bin/launchctl', 'bootstrap', domain, str(path)], check=True)
    loaded = subprocess.run(['/bin/launchctl', 'print', f'{domain}/{LABEL}'], capture_output=True, text=True, check=True)
    verify_loaded(loaded.stdout, value)
    print('SUBING_DEVELOPMENT_MODEL_INSTALLED_LOADED_IDENTITY_VERIFIED; MODEL_HEARTBEAT_REQUIRES_SEPARATE_READBACK')


if __name__ == '__main__':
    main()
