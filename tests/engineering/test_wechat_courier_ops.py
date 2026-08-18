from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
from uuid import uuid4


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts/ops/macos/install-wechat-courier.sh"
PINNED_COMMIT = "981bd14e238302b2a0e206cb5f28e8e2505bb874"


def test_check_reports_missing_without_private_values(tmp_path: Path) -> None:
    result = _run("--check", tmp_path / "missing")

    assert result.returncode == 0
    assert result.stdout == "status=not_installed\n"
    assert "group" not in result.stdout.lower()


def test_check_accepts_only_complete_clean_pinned_fixture(tmp_path: Path) -> None:
    root = _installed_fixture(tmp_path)
    fake_git = _fake_check_git(tmp_path)

    result = _run("--check", root, git_bin=fake_git)

    assert result.returncode == 0
    assert result.stdout == f"commit={PINNED_COMMIT}\nstatus=ready\n"
    assert "fixture-group-title" not in result.stdout


def test_check_accepts_standard_venv_python_symlink(tmp_path: Path) -> None:
    root = _installed_fixture(tmp_path)
    python = root / "venv/bin/python"
    python.unlink()
    (root / "venv/bin/python3").symlink_to("/usr/bin/python3")
    python.symlink_to("python3")
    fake_git = _fake_check_git(tmp_path)

    result = _run("--check", root, git_bin=fake_git)

    assert result.returncode == 0
    assert result.stdout == f"commit={PINNED_COMMIT}\nstatus=ready\n"


def test_confirm_install_uses_only_exact_fake_commands_and_never_runs_upstream(
    tmp_path: Path,
) -> None:
    root = REPO_ROOT / ".run" / f"test-courier-{uuid4().hex}"
    fake_git, fake_python, calls = _fake_install_commands(tmp_path)
    try:
        result = _run(
            "--confirm-install",
            root,
            git_bin=fake_git,
            python_bin=fake_python,
        )

        assert result.returncode == 0, result.stderr
        lines = calls.read_text(encoding="utf-8").splitlines()
        assert lines == [
            f"git clone https://github.com/bladydora/WeChat-Courier-macOS.git {root}/source",
            f"git -C {root}/source fetch origin {PINNED_COMMIT}",
            f"git -C {root}/source checkout --detach {PINNED_COMMIT}",
            f"python -m venv {root}/venv",
            "venv-python -m pip install --disable-pip-version-check Pillow==11.3.0",
            f"git -C {root}/source rev-parse HEAD",
            f"git -C {root}/source status --porcelain",
        ]
        assert "main" not in "\n".join(lines)
        assert "watch" not in "\n".join(lines)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_confirm_install_rejects_non_volume_root_before_any_command(
    tmp_path: Path,
) -> None:
    fake_git, fake_python, calls = _fake_install_commands(tmp_path)

    result = _run(
        "--confirm-install",
        tmp_path / "courier",
        git_bin=fake_git,
        python_bin=fake_python,
    )

    assert result.returncode == 2
    assert not calls.exists()


def test_confirm_install_rejects_symlink_root_before_any_command(
    tmp_path: Path,
) -> None:
    root = REPO_ROOT / ".run" / f"test-courier-link-{uuid4().hex}"
    fake_git, fake_python, calls = _fake_install_commands(tmp_path)
    root.symlink_to(tmp_path / "outside", target_is_directory=True)
    try:
        result = _run(
            "--confirm-install",
            root,
            git_bin=fake_git,
            python_bin=fake_python,
        )

        assert result.returncode == 2
        assert not calls.exists()
    finally:
        root.unlink(missing_ok=True)


def _run(
    mode: str,
    root: Path,
    *,
    git_bin: Path | None = None,
    python_bin: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "GUIYI_WECHAT_COURIER_ROOT": str(root),
    }
    script = SCRIPT
    if git_bin is not None or python_bin is not None:
        fixture_root = git_bin.parent if git_bin is not None else python_bin.parent
        fixture_script = fixture_root / "install-wechat-courier-fixture.sh"
        source = SCRIPT.read_text(encoding="utf-8")
        if git_bin is not None:
            source = source.replace(
                'GIT_BIN="/usr/bin/git"', f'GIT_BIN="{git_bin}"'
            )
        if python_bin is not None:
            source = source.replace(
                'PYTHON_BIN="/usr/bin/python3"', f'PYTHON_BIN="{python_bin}"'
            )
        fixture_script.write_text(source, encoding="utf-8")
        fixture_script.chmod(0o700)
        script = fixture_script
    return subprocess.run(
        [str(script), mode],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _installed_fixture(tmp_path: Path) -> Path:
    root = tmp_path / "courier"
    for directory in (
        root / "source/.git",
        root / "runtime",
        root / "tmp",
        root / "cache/clang",
        root / "venv/bin",
    ):
        directory.mkdir(parents=True)
    for private_directory in (root, root / "runtime", root / "tmp", root / "cache/clang"):
        private_directory.chmod(0o700)
    (root / "source/.git/HEAD").write_text(f"{PINNED_COMMIT}\n", encoding="utf-8")
    for private_directory in (root, root / "runtime", root / "tmp", root / "cache/clang"):
        private_directory.chmod(0o700)
    (root / "source/.git/HEAD").write_text(f"{PINNED_COMMIT}\n", encoding="utf-8")
    (root / "source/wechat_courier.py").write_text("# fixture\n", encoding="utf-8")
    python = root / "venv/bin/python"
    python.write_text("#!/bin/sh\n", encoding="utf-8")
    python.chmod(0o700)
    return root


def _fake_check_git(tmp_path: Path) -> Path:
    git = tmp_path / "git-check"
    git.write_text(
        "#!/bin/sh\n"
        'case "$*" in\n'
        f"  *'rev-parse HEAD') printf '{PINNED_COMMIT}\\n' ;;\n"
        "  *'status --porcelain') : ;;\n"
        "  *) exit 2 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    git.chmod(0o700)
    return git


def _fake_install_commands(tmp_path: Path) -> tuple[Path, Path, Path]:
    calls = tmp_path / "calls.log"
    git = tmp_path / "git-install"
    git.write_text(
        "#!/bin/sh\n"
        f"printf 'git %s\\n' \"$*\" >> {str(calls)!r}\n"
        'if [ "${1:-}" = "clone" ]; then\n'
        '  mkdir -p "$3/.git"\n'
        f'  printf "{PINNED_COMMIT}\\n" > "$3/.git/HEAD"\n'
        '  printf "# fake upstream\\n" > "$3/wechat_courier.py"\n'
        "fi\n"
        f'case "$*" in *"rev-parse HEAD") printf "{PINNED_COMMIT}\\n" ;; esac\n',
        encoding="utf-8",
    )
    git.chmod(0o700)
    python = tmp_path / "python-install"
    python.write_text(
        "#!/bin/sh\n"
        f"printf 'python %s\\n' \"$*\" >> {str(calls)!r}\n"
        'if [ "${1:-}" = "-m" ] && [ "${2:-}" = "venv" ]; then\n'
        '  mkdir -p "$3/bin"\n'
        "  cat > \"$3/bin/python\" <<'EOF'\n"
        "#!/bin/sh\n"
        f"printf 'venv-python %s\\n' \"$*\" >> {str(calls)!r}\n"
        "EOF\n"
        '  chmod 700 "$3/bin/python"\n'
        "fi\n",
        encoding="utf-8",
    )
    python.chmod(0o700)
    return git, python, calls
