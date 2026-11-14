"""Real Git provenance: registered trees and exact shared clones share authority."""

import subprocess

import pytest
from app.runtime_repository import repository_common_dir, shared_release_owner
from app.runtime_retention import RetentionBackend
from app import runtime_retirement as retirement


def git(root, *args):
    return subprocess.check_output(
        [
            "/usr/bin/git",
            "-c",
            "core.fsmonitor=false",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "-C",
            str(root),
            *args,
        ],
        stderr=subprocess.DEVNULL,
        text=True,
    ).strip()


@pytest.fixture
def layout(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init")
    git(root, "config", "remote.origin.url", "git@example.invalid:owner/project.git")
    (root / ".gitignore").write_text(".worktrees/\n.run/\n")
    git(root, "add", ".gitignore")
    git(root, "commit", "-m", "fixture")
    git(root, "tag", "-a", "v1.2.3", "-m", "fixture")
    clone = root / ".worktrees/release-v1.2.3"
    clone.parent.mkdir()
    subprocess.run(
        ["/usr/bin/git", "clone", "--shared", "--no-checkout", str(root), str(clone)],
        check=True,
        capture_output=True,
    )
    git(clone, "checkout", "--detach", "v1.2.3")
    monkeypatch.setattr("app.core.env.PROJECT_ROOT", root)
    return root, clone


def test_shared_clone_keeps_exact_tag_and_canonical_repository(layout):
    root, clone = layout
    common = (root / ".git").resolve()
    assert shared_release_owner(root) is None
    assert shared_release_owner(clone) == root
    assert repository_common_dir(clone) == repository_common_dir(root) == common
    identity = RetentionBackend().candidate_identity(clone)
    assert identity == dict(
        root=str(clone), commit=git(root, "rev-parse", "HEAD"), tag="v1.2.3"
    )
    retirement._verify_present_release(root, identity)
    retirement._verify_present_release(clone, identity)
    assert retirement._common(root) == retirement._common(clone)


@pytest.mark.parametrize(
    "change",
    [
        "origin",
        "foreign_objects",
        "multiple_alternates",
        "relative_alternate",
        "alternate_symlink",
        "source_change",
        "branch",
        "rename",
    ],
)
def test_shared_clone_cannot_hide_identity_or_local_changes(layout, tmp_path, change):
    root, clone = layout
    alternate = clone / ".git/objects/info/alternates"
    if change == "origin":
        git(
            clone,
            "remote",
            "set-url",
            "origin",
            "git@example.invalid:foreign/project.git",
        )
    elif change == "foreign_objects":
        other = tmp_path / "foreign"
        other.mkdir()
        git(other, "init")
        alternate.write_text(str(other / ".git/objects") + "\n")
    elif change == "multiple_alternates":
        alternate.write_text(alternate.read_text() + alternate.read_text())
    elif change == "relative_alternate":
        alternate.write_text("../../../../.git/objects\n")
    elif change == "alternate_symlink":
        copy = tmp_path / "alternate"
        copy.write_bytes(alternate.read_bytes())
        alternate.unlink()
        alternate.symlink_to(copy)
    elif change == "source_change":
        (clone / ".gitignore").write_text("changed")
    elif change == "branch":
        git(clone, "switch", "-c", "unapproved")
    elif change == "rename":
        clone = clone.rename(clone.with_name("release-v9.9.9"))
    with pytest.raises(ValueError):
        RetentionBackend().candidate_identity(clone)


def test_shared_clone_can_keep_matching_upstream_origin(layout):
    root, clone = layout
    git(
        clone,
        "remote",
        "set-url",
        "origin",
        git(root, "config", "--get", "remote.origin.url"),
    )
    assert shared_release_owner(clone) == root


@pytest.mark.parametrize("change", ["local_only_release", "reannotated_tag"])
def test_shared_clone_cannot_delete_clone_only_history(layout, change):
    root, clone = layout
    if change == "local_only_release":
        (clone / "new-source").write_text("unmerged work")
        git(clone, "add", "new-source")
        git(clone, "commit", "-m", "local only")
        git(clone, "tag", "-a", "v9.9.9", "-m", "local only")
        clone = clone.rename(clone.with_name("release-v9.9.9"))
    else:
        git(clone, "tag", "-d", "v1.2.3")
        git(clone, "tag", "-a", "v1.2.3", "-m", "foreign annotation")
    with pytest.raises(ValueError):
        RetentionBackend().candidate_identity(clone)
    identity = dict(
        root=str(clone),
        tag="v9.9.9" if change == "local_only_release" else "v1.2.3",
        commit=git(clone, "rev-parse", "HEAD"),
    )
    with pytest.raises(ValueError):
        retirement._verify_present_release(root, identity)


def test_post_delete_reference_check_uses_existing_controller_home(
    tmp_path, monkeypatch
):
    from app.runtime_retention import RetentionBackend

    deleted = tmp_path / "deleted-release"
    backend = RetentionBackend(home=tmp_path)

    def command(args):
        if args[0] == "/bin/launchctl":
            return "PID\tStatus\tLabel\n42\t0\tcom.guiyi.quant-api\n"
        return ""

    calls = []

    def launchd(label, *, root):
        assert root == tmp_path and root.is_dir()
        calls.append(label)
        return None

    monkeypatch.setattr(backend, "_command", command)
    monkeypatch.setattr("app.runtime_identity.read_launchd_service", launchd)
    assert backend.references_by_root((deleted,)) == {str(deleted): []}
    assert calls == ["com.guiyi.quant-api"]
