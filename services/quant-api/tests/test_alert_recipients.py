from __future__ import annotations

from dataclasses import FrozenInstanceError
import json
import os
from pathlib import Path
import stat
from types import SimpleNamespace

import pytest

import app.alerts.recipients as recipients
from app.alerts.clawbot_owner import write_clawbot_owner_atomic
from app.alerts.recipients import (
    ClawbotRecipient,
    ClawbotRecipientError,
    RecipientInitializationResult,
    initialize_recipients_from_owner,
    load_recipient_directory,
)


ACCOUNT_ID = "fixture-account-private"
OWNER_TARGET = "fixture-owner-private@im.wechat"
ALICE_TARGET = "fixture-alice-private@im.wechat"
BOB_TARGET = "fixture-bob-private@im.wechat"


def _private_path(tmp_path: Path, name: str = "recipients.json") -> Path:
    parent = tmp_path / "private"
    parent.mkdir(mode=0o700)
    parent.chmod(0o700)
    return parent / name


def _payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": 2,
        "channel": "openclaw-weixin",
        "account_id": ACCOUNT_ID,
        "active_recipients": [
            {"alias": "owner", "target_user_id": OWNER_TARGET},
            {"alias": "alice", "target_user_id": ALICE_TARGET},
            {"alias": "bob", "target_user_id": BOB_TARGET},
        ],
        "retired_aliases": ["retired_old"],
    }
    payload.update(overrides)
    return payload


def _write(path: Path, payload: object, *, mode: int = 0o600) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    path.chmod(mode)
    return path


def test_loads_frozen_directory_in_owner_first_alias_order(tmp_path: Path) -> None:
    path = _write(
        _private_path(tmp_path),
        _payload(
            active_recipients=[
                {"alias": "bob", "target_user_id": BOB_TARGET},
                {"alias": "owner", "target_user_id": OWNER_TARGET},
                {"alias": "alice", "target_user_id": ALICE_TARGET},
            ]
        ),
    )

    directory = load_recipient_directory(path)

    assert directory.aliases == ("owner", "alice", "bob")
    assert directory.recipients == (
        ClawbotRecipient("owner", ACCOUNT_ID, OWNER_TARGET),
        ClawbotRecipient("alice", ACCOUNT_ID, ALICE_TARGET),
        ClawbotRecipient("bob", ACCOUNT_ID, BOB_TARGET),
    )
    assert directory.owner == ClawbotRecipient("owner", ACCOUNT_ID, OWNER_TARGET)
    assert directory.retired_aliases == ("retired_old",)
    with pytest.raises(FrozenInstanceError):
        directory.retired_aliases = ()  # type: ignore[misc]


def test_routes_only_the_two_frozen_rule_contracts(tmp_path: Path) -> None:
    directory = load_recipient_directory(_write(_private_path(tmp_path), _payload()))

    assert [item.alias for item in directory.recipients_for("htdy_original_15m")] == [
        "owner",
        "alice",
        "bob",
    ]
    assert [item.alias for item in directory.recipients_for("subing_entry_signal_v1")] == [
        "owner"
    ]
    with pytest.raises(ClawbotRecipientError, match="^CLAWBOT_RECIPIENT_RULE_INVALID$"):
        directory.recipients_for("future_rule")


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {"schema_version": 2},
        _payload(extra=True),
        _payload(schema_version=True),
        _payload(schema_version=1),
        _payload(channel="wecom"),
        _payload(account_id=""),
        _payload(account_id=f" {ACCOUNT_ID}"),
        _payload(account_id=f"{ACCOUNT_ID}\x00"),
        _payload(active_recipients="owner"),
        _payload(active_recipients=[]),
        _payload(
            active_recipients=[
                {"alias": "owner", "target_user_id": OWNER_TARGET},
                {"alias": "a", "target_user_id": "a@im.wechat"},
                {"alias": "b", "target_user_id": "b@im.wechat"},
                {"alias": "c", "target_user_id": "c@im.wechat"},
                {"alias": "d", "target_user_id": "d@im.wechat"},
                {"alias": "e", "target_user_id": "e@im.wechat"},
            ]
        ),
        _payload(active_recipients=[{"alias": "owner"}]),
        _payload(
            active_recipients=[
                {"alias": "owner", "target_user_id": OWNER_TARGET, "extra": True}
            ]
        ),
        _payload(active_recipients=[{"alias": "Owner", "target_user_id": OWNER_TARGET}]),
        _payload(active_recipients=[{"alias": "9alice", "target_user_id": OWNER_TARGET}]),
        _payload(active_recipients=[{"alias": "a" * 33, "target_user_id": OWNER_TARGET}]),
        _payload(active_recipients=[{"alias": "alice", "target_user_id": ALICE_TARGET}]),
        _payload(active_recipients=[{"alias": "owner", "target_user_id": "@im.wechat"}]),
        _payload(active_recipients=[{"alias": "owner", "target_user_id": "not-direct"}]),
        _payload(active_recipients=[{"alias": "owner", "target_user_id": f" {OWNER_TARGET}"}]),
        _payload(active_recipients=[{"alias": "owner", "target_user_id": f"{OWNER_TARGET}\n"}]),
        _payload(
            active_recipients=[
                {"alias": "owner", "target_user_id": OWNER_TARGET},
                {"alias": "owner", "target_user_id": ALICE_TARGET},
            ]
        ),
        _payload(
            active_recipients=[
                {"alias": "owner", "target_user_id": OWNER_TARGET},
                {"alias": "alice", "target_user_id": OWNER_TARGET},
            ]
        ),
        _payload(retired_aliases="retired_old"),
        _payload(retired_aliases=["Retired"]),
        _payload(retired_aliases=["retired_old", "retired_old"]),
        _payload(retired_aliases=["alice"]),
        _payload(retired_aliases=["owner"]),
    ],
)
def test_rejects_non_exact_or_unsafe_schema_without_private_values(
    tmp_path: Path, payload: object
) -> None:
    path = _private_path(tmp_path)
    if payload is None:
        path.write_text("not-json", encoding="utf-8")
        path.chmod(0o600)
    else:
        _write(path, payload)

    with pytest.raises(ClawbotRecipientError) as captured:
        load_recipient_directory(path)

    assert str(captured.value) == "CLAWBOT_RECIPIENTS_INVALID"
    assert ACCOUNT_ID not in str(captured.value)
    assert OWNER_TARGET not in str(captured.value)
    assert str(path) not in str(captured.value)


@pytest.mark.parametrize("problem", ["missing", "relative", "symlink", "directory", "fifo"])
def test_rejects_missing_relative_or_non_regular_recipient_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, problem: str
) -> None:
    path = _private_path(tmp_path)
    if problem == "relative":
        monkeypatch.chdir(path.parent)
        path = Path(path.name)
    elif problem == "symlink":
        real = _write(path.parent / "real.json", _payload())
        path.symlink_to(real)
    elif problem == "directory":
        path.mkdir(mode=0o700)
    elif problem == "fifo":
        os.mkfifo(path, mode=0o600)

    with pytest.raises(ClawbotRecipientError, match="^CLAWBOT_RECIPIENTS_INVALID$"):
        load_recipient_directory(path)


def test_rejects_symlink_parent(tmp_path: Path) -> None:
    real_parent = tmp_path / "real-private"
    real_parent.mkdir(mode=0o700)
    real_parent.chmod(0o700)
    linked_parent = tmp_path / "linked-private"
    linked_parent.symlink_to(real_parent, target_is_directory=True)
    path = _write(real_parent / "recipients.json", _payload())

    with pytest.raises(ClawbotRecipientError, match="^CLAWBOT_RECIPIENTS_INVALID$"):
        load_recipient_directory(linked_parent / path.name)


@pytest.mark.parametrize("problem", ["parent_mode", "file_mode", "parent_uid", "file_uid"])
def test_requires_exact_private_modes_and_current_uid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, problem: str
) -> None:
    path = _write(_private_path(tmp_path), _payload())
    if problem == "parent_mode":
        path.parent.chmod(0o755)
    elif problem == "file_mode":
        path.chmod(0o640)
    else:
        selected = path.parent if problem == "parent_uid" else path
        original_lstat = Path.lstat

        def wrong_owner(candidate: Path):
            metadata = original_lstat(candidate)
            if candidate == selected:
                return SimpleNamespace(
                    st_mode=metadata.st_mode,
                    st_uid=os.getuid() + 1,
                    st_dev=metadata.st_dev,
                    st_ino=metadata.st_ino,
                )
            return metadata

        monkeypatch.setattr(Path, "lstat", wrong_owner)

    with pytest.raises(ClawbotRecipientError, match="^CLAWBOT_RECIPIENTS_INVALID$"):
        load_recipient_directory(path)


def test_rejects_file_replaced_between_lstat_and_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _write(_private_path(tmp_path), _payload())
    replacement = _write(path.parent / "replacement.json", _payload())
    original_open = os.open
    replaced = False

    def replacing_open(candidate: object, flags: int, *args: object, **kwargs: object) -> int:
        nonlocal replaced
        if Path(candidate) == path and not replaced:
            replaced = True
            replacement.replace(path)
        return original_open(candidate, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", replacing_open)

    with pytest.raises(ClawbotRecipientError, match="^CLAWBOT_RECIPIENTS_INVALID$"):
        load_recipient_directory(path)


def test_rejects_parent_replaced_after_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _write(_private_path(tmp_path), _payload())
    replacement_parent = tmp_path / "replacement-private"
    replacement_parent.mkdir(mode=0o700)
    replacement_parent.chmod(0o700)
    _write(replacement_parent / path.name, _payload())
    moved_parent = tmp_path / "moved-private"
    original_lstat = Path.lstat
    replaced = False

    def replacing_lstat(candidate: Path):
        nonlocal replaced
        if candidate == path and not replaced:
            replaced = True
            path.parent.rename(moved_parent)
            replacement_parent.rename(path.parent)
        return original_lstat(candidate)

    monkeypatch.setattr(Path, "lstat", replacing_lstat)

    with pytest.raises(ClawbotRecipientError, match="^CLAWBOT_RECIPIENTS_INVALID$"):
        load_recipient_directory(path)


def test_initializes_owner_only_v2_without_modifying_v1(tmp_path: Path) -> None:
    owner_path = _private_path(tmp_path, "owner.json")
    recipients_path = owner_path.parent / "recipients.json"
    write_clawbot_owner_atomic(
        owner_path,
        account_id=ACCOUNT_ID,
        target_user_id=OWNER_TARGET,
    )
    owner_before = owner_path.read_bytes()
    owner_stat_before = owner_path.stat()

    result = initialize_recipients_from_owner(owner_path, recipients_path)

    assert result == RecipientInitializationResult(
        channel="openclaw-weixin",
        recipient_count=1,
        active_aliases=("owner",),
        recipients_written=True,
    )
    assert ACCOUNT_ID not in repr(result)
    assert OWNER_TARGET not in repr(result)
    assert json.loads(recipients_path.read_text(encoding="utf-8")) == {
        "schema_version": 2,
        "channel": "openclaw-weixin",
        "account_id": ACCOUNT_ID,
        "active_recipients": [{"alias": "owner", "target_user_id": OWNER_TARGET}],
        "retired_aliases": [],
    }
    assert recipients_path.stat().st_mode & 0o777 == 0o600
    assert owner_path.read_bytes() == owner_before
    assert owner_path.stat().st_ino == owner_stat_before.st_ino
    assert load_recipient_directory(recipients_path).aliases == ("owner",)
    assert list(owner_path.parent.glob(f".{recipients_path.name}.*")) == []


def test_initializer_fsyncs_file_and_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner_path = _private_path(tmp_path, "owner.json")
    recipients_path = owner_path.parent / "recipients.json"
    write_clawbot_owner_atomic(
        owner_path,
        account_id=ACCOUNT_ID,
        target_user_id=OWNER_TARGET,
    )
    original_fsync = os.fsync
    fsynced_types: list[str] = []

    def recording_fsync(descriptor: int) -> None:
        mode = os.fstat(descriptor).st_mode
        fsynced_types.append("directory" if stat.S_ISDIR(mode) else "file")
        original_fsync(descriptor)

    monkeypatch.setattr(os, "fsync", recording_fsync)

    initialize_recipients_from_owner(owner_path, recipients_path)

    assert "file" in fsynced_types
    assert "directory" in fsynced_types


@pytest.mark.parametrize("existing_kind", ["file", "symlink"])
def test_initializer_refuses_overwrite_and_preserves_existing_target(
    tmp_path: Path, existing_kind: str
) -> None:
    owner_path = _private_path(tmp_path, "owner.json")
    recipients_path = owner_path.parent / "recipients.json"
    write_clawbot_owner_atomic(
        owner_path,
        account_id=ACCOUNT_ID,
        target_user_id=OWNER_TARGET,
    )
    existing = owner_path.parent / "existing"
    existing.write_text("preserve-me", encoding="utf-8")
    if existing_kind == "file":
        recipients_path.write_text("preserve-me", encoding="utf-8")
    else:
        recipients_path.symlink_to(existing)

    with pytest.raises(ClawbotRecipientError) as captured:
        initialize_recipients_from_owner(owner_path, recipients_path)

    assert str(captured.value) == "CLAWBOT_RECIPIENTS_INVALID"
    if existing_kind == "file":
        assert recipients_path.read_text(encoding="utf-8") == "preserve-me"
    else:
        assert recipients_path.is_symlink()
        assert existing.read_text(encoding="utf-8") == "preserve-me"


@pytest.mark.parametrize("problem", ["invalid_owner", "unsafe_parent"])
def test_initializer_fails_closed_without_artifacts(
    tmp_path: Path, problem: str
) -> None:
    owner_path = _private_path(tmp_path, "owner.json")
    recipients_path = owner_path.parent / "recipients.json"
    if problem == "invalid_owner":
        _write(owner_path, {"private": ACCOUNT_ID})
    else:
        write_clawbot_owner_atomic(
            owner_path,
            account_id=ACCOUNT_ID,
            target_user_id=OWNER_TARGET,
        )
        owner_path.parent.chmod(0o755)

    with pytest.raises(ClawbotRecipientError) as captured:
        initialize_recipients_from_owner(owner_path, recipients_path)

    assert str(captured.value) == "CLAWBOT_RECIPIENTS_INVALID"
    assert ACCOUNT_ID not in str(captured.value)
    assert OWNER_TARGET not in str(captured.value)
    assert str(owner_path) not in str(captured.value)
    assert str(recipients_path) not in str(captured.value)
    assert not recipients_path.exists()
    assert list(owner_path.parent.glob(f".{recipients_path.name}.*")) == []


def test_initializer_closes_temporary_descriptor_on_early_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner_path = _private_path(tmp_path, "owner.json")
    recipients_path = owner_path.parent / "recipients.json"
    write_clawbot_owner_atomic(
        owner_path,
        account_id=ACCOUNT_ID,
        target_user_id=OWNER_TARGET,
    )
    opened_descriptors: list[int] = []
    original_mkstemp = recipients.tempfile.mkstemp

    def recording_mkstemp(*args: object, **kwargs: object) -> tuple[int, str]:
        descriptor, raw_path = original_mkstemp(*args, **kwargs)
        opened_descriptors.append(descriptor)
        return descriptor, raw_path

    monkeypatch.setattr(recipients.tempfile, "mkstemp", recording_mkstemp)
    monkeypatch.setattr(
        recipients.os,
        "fchmod",
        lambda *_args: (_ for _ in ()).throw(OSError("fixture failure")),
    )

    with pytest.raises(ClawbotRecipientError, match="^CLAWBOT_RECIPIENTS_INVALID$"):
        initialize_recipients_from_owner(owner_path, recipients_path)

    assert len(opened_descriptors) == 1
    with pytest.raises(OSError):
        os.fstat(opened_descriptors[0])
    assert not recipients_path.exists()
    assert list(owner_path.parent.glob(f".{recipients_path.name}.*")) == []
