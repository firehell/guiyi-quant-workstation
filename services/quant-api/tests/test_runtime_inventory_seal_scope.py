"""A stopped inventory may share seal reads only within its own verification."""

from types import SimpleNamespace
import subprocess

import pytest

from app import runtime_retirement as retirement
from app import runtime_stopped_recovery as stopped
from app.runtime_handover import _write


@pytest.fixture
def inventory(tmp_path, monkeypatch):
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o700)
    for name in ("release-retirements", "cohort-attempts", "cohort-forward-recoveries"):
        (runtime / name).mkdir(mode=0o700)
    prior = runtime / "cohort-attempts" / ("b" * 64)
    prior.mkdir(mode=0o700)
    external = tmp_path / "public-plan.json"
    _write(external, {"revision": 1})
    folder = runtime / "release-retirements" / ("a" * 64)
    folder.mkdir(mode=0o700)
    plan = {
        "plan_sha256": folder.name, "directory": str(runtime), "markers": {},
        "repository_common_dir": str(tmp_path), "releases": [],
        "originals": {str(external): retirement.sha(external.read_bytes())},
    }
    index = {"plan": plan}
    _write(folder / "index.json", {**index, "index_sha256": retirement._digest(index)})
    # Narrow the historical scenario to one external file. The real loader
    # still checks the index, private folder, expected leaves and original SHA.
    monkeypatch.setattr(retirement, "_valid_plan", lambda value: None)
    monkeypatch.setattr(retirement, "_common", lambda root: str(root))
    monkeypatch.setattr(retirement, "_closed_history", lambda *args: set())
    load = retirement._load_index
    reads = []

    def count_load(folder, repo):
        reads.append(folder)
        return load(folder, repo)

    monkeypatch.setattr(retirement, "_load_index", count_load)

    def run(change=lambda: None):
        def close(host, entries):
            for _ in range(4):  # Several historical bindings refer to one seal.
                assert retirement._seals(host.directory, tmp_path)[0][1] == plan
            change()
            return set()

        monkeypatch.setattr(stopped.recovery, "_closed_predecessors", close)
        stopped._inventory(SimpleNamespace(directory=runtime), set())

    return run, reads, runtime, prior, external


def test_history_is_read_before_and_after_each_inventory(inventory):
    run, reads, *_ = inventory
    run()
    assert len(reads) == 2
    run()
    assert len(reads) == 4


def test_external_original_drift_is_rejected_on_scope_exit(inventory):
    run, _, _, _, external = inventory
    with pytest.raises(ValueError):
        run(lambda: _write(external, {"revision": 2}))


@pytest.mark.parametrize("change", ["empty_attempt", "new_leaf"])
def test_inventory_membership_drift_is_rejected_on_scope_exit(inventory, change):
    run, _, runtime, prior, _ = inventory
    def mutate():
        if change == "empty_attempt":
            (runtime / "cohort-forward-recoveries" / ("d" * 64)).mkdir(mode=0o700)
        else:
            _write(prior / "receipt.json", {"phase": "changed"})
    with pytest.raises(ValueError):
        run(mutate)


@pytest.fixture
def historical_release(tmp_path):
    repo = (tmp_path / "source").resolve()
    repo.mkdir()

    def git(*args):
        return subprocess.run(
            ["/usr/bin/git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
             "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false", *args],
            cwd=repo, text=True, capture_output=True, check=True,
        ).stdout.strip()

    git("init", "-q")
    (repo / "source.py").write_text("revision = 1\n")
    git("add", "source.py")
    git("commit", "-qm", "source")
    tag = "v1.2.3"
    git("tag", "-a", tag, "-m", "release")
    git("checkout", "--detach", "-q")
    return repo, {"root": str(repo), "commit": git("rev-parse", "HEAD"), "tag": tag}, git


def test_git_and_checkout_are_fresh_at_both_ends_of_each_scope(
    tmp_path, monkeypatch, historical_release
):
    from app import runtime_bindings

    repo, identity, _ = historical_release
    git_probe, checkout_probe = retirement._git, runtime_bindings.verify_release
    git_reads, checkout_reads = [], []

    def git(root, *args):
        if args[:2] == ("cat-file", "-t"):
            git_reads.append(root)
        return git_probe(root, *args)

    def checkout(root, tag, commit):
        checkout_reads.append(root)
        return checkout_probe(root, tag, commit)

    monkeypatch.setattr(retirement, "_git", git)
    monkeypatch.setattr(runtime_bindings, "verify_release", checkout)
    for count in (2, 4):
        with retirement.inventory_history_reads(tmp_path):
            for _ in range(3):
                retirement._verify_git(repo, identity)
                retirement._verify_present_release(repo, identity)
        assert len(git_reads) == len(checkout_reads) == count


@pytest.mark.parametrize("drift", ["tag", "source"])
def test_scope_exit_rejects_release_identity_drift(tmp_path, historical_release, drift):
    repo, identity, git = historical_release
    with pytest.raises(ValueError):
        with retirement.inventory_history_reads(tmp_path):
            retirement._verify_git(repo, identity)
            retirement._verify_present_release(repo, identity)
            if drift == "tag":
                git("tag", "-f", identity["tag"], "HEAD")  # Convert to lightweight.
            else:
                (repo / "source.py").write_text("revision = 2\n")
