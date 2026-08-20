from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from app.alerts.clawbot_owner import write_clawbot_owner_atomic
from app.alerts.recipients import (
    ClawbotRecipient,
    ClawbotRecipientError,
    RecipientDirectory,
    initialize_recipients_from_owner,
    load_recipient_directory,
)


ACCOUNT_ID = "fixture-account"
OWNER_TARGET = "fixture-owner@im.wechat"
ALICE_TARGET = "fixture-alice@im.wechat"


def _private_parent(tmp_path: Path) -> Path:
    parent = tmp_path / "private"
    parent.mkdir(mode=0o700)
    parent.chmod(0o700)
    return parent


def _payload(*, recipients: list[dict[str, str]] | None = None, retired: list[str] | None = None) -> dict[str, object]:
    return {
        "schema_version": 2,
        "channel": "openclaw-weixin",
        "account_id": ACCOUNT_ID,
        "active_recipients": recipients if recipients is not None else [{"alias": "owner", "target_user_id": OWNER_TARGET}],
        "retired_aliases": retired if retired is not None else [],
    }


def _write_directory(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")
    path.chmod(0o600)


def test_loads_frozen_directory_and_routes_deterministically(tmp_path: Path) -> None:
    path = _private_parent(tmp_path) / "recipients.json"
    _write_directory(
        path,
        _payload(
            recipients=[
                {"alias": "owner", "target_user_id": OWNER_TARGET},
                {"alias": "alice", "target_user_id": ALICE_TARGET},
            ],
            retired=["former_friend"],
        ),
    )

    directory = load_recipient_directory(path)

    assert directory == RecipientDirectory(
        2,
        "openclaw-weixin",
        ACCOUNT_ID,
        (
            ClawbotRecipient("owner", ACCOUNT_ID, OWNER_TARGET),
            ClawbotRecipient("alice", ACCOUNT_ID, ALICE_TARGET),
        ),
        ("former_friend",),
    )
    assert directory.aliases == ("owner", "alice")
    assert directory.recipients_for("htdy_original_15m") == directory.recipients
    assert directory.recipients_for("subing_entry_signal_v1") == (directory.recipients[0],)
    with pytest.raises(ClawbotRecipientError, match="^CLAWBOT_RECIPIENT_RULE_INVALID$"):
        directory.recipients_for("unknown-rule")
    with pytest.raises(AttributeError):
        directory.account_id = "changed"  # type: ignore[misc]


def test_recipient_repr_keeps_alias_but_hides_private_identifiers() -> None:
    recipient = ClawbotRecipient("owner", ACCOUNT_ID, OWNER_TARGET)

    value = repr(recipient)

    assert "owner" in value
    assert ACCOUNT_ID not in value
    assert OWNER_TARGET not in value


def test_directory_repr_keeps_public_aliases_and_count_but_hides_private_identifiers() -> None:
    directory = RecipientDirectory(
        2,
        "openclaw-weixin",
        ACCOUNT_ID,
        (ClawbotRecipient("owner", ACCOUNT_ID, OWNER_TARGET),),
        (),
    )

    value = repr(directory)

    assert "owner" in value
    assert "recipient_count=1" in value
    assert ACCOUNT_ID not in value
    assert OWNER_TARGET not in value


@pytest.mark.parametrize(
    "payload",
    [
        {"schema_version": 2},
        _payload(recipients=[]),
        _payload(
            recipients=[
                {"alias": "owner", "target_user_id": OWNER_TARGET},
                {"alias": "alice", "target_user_id": ALICE_TARGET},
                {"alias": "bob", "target_user_id": "fixture-bob@im.wechat"},
                {"alias": "carol", "target_user_id": "fixture-carol@im.wechat"},
                {"alias": "dave", "target_user_id": "fixture-dave@im.wechat"},
            ]
        ),
        _payload(recipients=[{"alias": "alice", "target_user_id": ALICE_TARGET}]),
        _payload(
            recipients=[
                {"alias": "alice", "target_user_id": ALICE_TARGET},
                {"alias": "owner", "target_user_id": OWNER_TARGET},
            ]
        ),
        _payload(
            recipients=[
                {"alias": "owner", "target_user_id": OWNER_TARGET},
                {"alias": "alice", "target_user_id": OWNER_TARGET},
            ]
        ),
        _payload(retired=["owner"]),
        _payload(retired=["zeta", "alpha"]),
        _payload(recipients=[{"alias": "Owner", "target_user_id": OWNER_TARGET}]),
        _payload(recipients=[{"alias": "owner", "target_user_id": "not-direct"}]),
    ],
)
def test_rejects_invalid_directory_contract_without_private_values(
    tmp_path: Path,
    payload: dict[str, object],
) -> None:
    path = _private_parent(tmp_path) / "recipients.json"
    _write_directory(path, payload)

    with pytest.raises(ClawbotRecipientError, match="^CLAWBOT_RECIPIENT_INVALID$") as captured:
        load_recipient_directory(path)

    assert ACCOUNT_ID not in str(captured.value)
    assert OWNER_TARGET not in str(captured.value)
    assert str(path) not in str(captured.value)


@pytest.mark.parametrize("problem", ["mode", "symlink", "inode_changed"])
def test_safe_loader_rejects_unsafe_or_replaced_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    problem: str,
) -> None:
    path = _private_parent(tmp_path) / "recipients.json"
    _write_directory(path, _payload())
    if problem == "mode":
        path.chmod(0o644)
    elif problem == "symlink":
        outside = tmp_path / "outside.json"
        _write_directory(outside, _payload())
        path.unlink()
        path.symlink_to(outside)
    else:
        original_open = os.open

        def replacing_open(candidate: str | bytes | os.PathLike[str] | os.PathLike[bytes], flags: int, *args: int) -> int:
            if Path(candidate) == path:
                replacement = path.with_name("replacement.json")
                _write_directory(replacement, _payload())
                replacement.replace(path)
            return original_open(candidate, flags, *args)

        monkeypatch.setattr(os, "open", replacing_open)

    with pytest.raises(ClawbotRecipientError, match="^CLAWBOT_RECIPIENT_INVALID$"):
        load_recipient_directory(path)


def test_initializes_owner_only_v2_without_changing_v1(tmp_path: Path) -> None:
    parent = _private_parent(tmp_path)
    owner_path = parent / "owner.json"
    recipients_path = parent / "recipients.json"
    write_clawbot_owner_atomic(owner_path, account_id=ACCOUNT_ID, target_user_id=OWNER_TARGET)
    original_owner = owner_path.read_bytes()

    directory = initialize_recipients_from_owner(owner_path, recipients_path)

    assert directory.aliases == ("owner",)
    assert directory.recipients[0] == ClawbotRecipient("owner", ACCOUNT_ID, OWNER_TARGET)
    assert json.loads(recipients_path.read_text(encoding="utf-8")) == _payload()
    assert recipients_path.stat().st_mode & 0o777 == 0o600
    assert owner_path.read_bytes() == original_owner


def test_initializer_refuses_existing_v2_without_overwriting_it(tmp_path: Path) -> None:
    parent = _private_parent(tmp_path)
    owner_path = parent / "owner.json"
    recipients_path = parent / "recipients.json"
    write_clawbot_owner_atomic(owner_path, account_id=ACCOUNT_ID, target_user_id=OWNER_TARGET)
    _write_directory(recipients_path, _payload())
    original = recipients_path.read_bytes()

    with pytest.raises(ClawbotRecipientError, match="^CLAWBOT_RECIPIENT_INVALID$"):
        initialize_recipients_from_owner(owner_path, recipients_path)

    assert recipients_path.read_bytes() == original
