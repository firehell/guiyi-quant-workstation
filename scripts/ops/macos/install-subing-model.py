"""Explicit install of the owner-authorized independent development observer."""

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
    raise SystemExit("SUBING_INDEPENDENT_MODEL_RETIRED_USE_INSTALL_SUBING_PAPER")

if __name__ == '__main__':
    main()
