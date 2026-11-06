"""Resolve the owning Git object repository for documented release layouts.

A shared release clone is accepted only through its exact local alternates,
location and origin. A matching remote or commit alone is never authority.
"""

from pathlib import Path
import stat

from app.runtime_bindings import _git


def shared_release_owner(root: Path) -> Path | None:
    root = Path(root)
    if root != root.resolve(strict=True) or root.is_symlink():
        raise ValueError("RELEASE_REPOSITORY_UNPROVEN")
    metadata = root / ".git"
    if metadata.is_symlink():
        raise ValueError("RELEASE_REPOSITORY_UNPROVEN")
    if not metadata.is_dir():
        return None
    alternate = metadata / "objects/info/alternates"
    if not alternate.exists():
        return None
    info = alternate.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 4096:
        raise ValueError("RELEASE_REPOSITORY_UNPROVEN")
    lines = alternate.read_text().splitlines()
    if len(lines) != 1:
        raise ValueError("RELEASE_REPOSITORY_UNPROVEN")
    objects = Path(lines[0])
    if not objects.is_absolute() or objects != objects.resolve(strict=True):
        raise ValueError("RELEASE_REPOSITORY_UNPROVEN")
    common = objects.parent
    owner = common.parent
    if (
        objects.name != "objects"
        or common.name != ".git"
        or root.parent != owner / ".worktrees"
        or not root.name.startswith("release-v")
        or common
        != Path(
            _git(owner, "rev-parse", "--path-format=absolute", "--git-common-dir")
        ).resolve(strict=True)
        or metadata
        != Path(
            _git(root, "rev-parse", "--path-format=absolute", "--git-common-dir")
        ).resolve(strict=True)
    ):
        raise ValueError("RELEASE_REPOSITORY_UNPROVEN")
    origin = _git(root, "config", "--get", "remote.origin.url")
    if origin not in {str(owner), _git(owner, "config", "--get", "remote.origin.url")}:
        raise ValueError("RELEASE_REPOSITORY_UNPROVEN")
    return owner


def repository_common_dir(root: Path) -> Path:
    owner = shared_release_owner(root)
    return Path(
        _git(owner or root, "rev-parse", "--path-format=absolute", "--git-common-dir")
    ).resolve(strict=True)


def verify_shared_release_identity(root: Path, tag: str, commit: str) -> None:
    owner = shared_release_owner(root)
    if owner is None:
        return
    ref = "refs/tags/" + tag
    if (
        _git(owner, "cat-file", "-t", ref) != "tag"
        or _git(owner, "rev-parse", ref + "^{commit}") != commit
        or _git(owner, "rev-parse", ref) != _git(root, "rev-parse", ref)
    ):
        raise ValueError("RELEASE_REPOSITORY_UNPROVEN")
