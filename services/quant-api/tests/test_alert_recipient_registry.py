from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.alerts.recipient_registry import (
    NotificationRecipient,
    RecipientRegistryDocument,
    RecipientRegistryError,
    add_recipient,
    load_recipient_registry,
    write_recipient_registry,
)


def _write_registry(
    tmp_path: Path,
    *,
    version: object = 1,
    channel: object = "openclaw-weixin",
    account_id: object = "account-fixture",
    recipients: object | None = None,
) -> Path:
    tmp_path.chmod(0o700)
    path = tmp_path / "recipients.json"
    payload = {
        "version": version,
        "channel": channel,
        "account_id": account_id,
        "recipients": (
            recipients
            if recipients is not None
            else [{"alias": "owner", "target": "u1@im.wechat", "enabled": True}]
        ),
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    path.chmod(0o600)
    return path


def test_load_valid_registry_and_project_enabled_recipients(tmp_path: Path) -> None:
    path = _write_registry(
        tmp_path,
        recipients=[
            {"alias": "owner", "target": "u1@im.wechat", "enabled": True},
            {"alias": "paused", "target": "u2@im.wechat", "enabled": False},
        ],
    )

    document = load_recipient_registry(path)

    assert document == RecipientRegistryDocument(
        version=1,
        channel="openclaw-weixin",
        account_id="account-fixture",
        recipients=(
            NotificationRecipient("owner", "u1@im.wechat", True),
            NotificationRecipient("paused", "u2@im.wechat", False),
        ),
    )
    assert document.enabled_recipients == (
        NotificationRecipient("owner", "u1@im.wechat", True),
    )


def test_disabled_recipient_survives_round_trip(tmp_path: Path) -> None:
    path = _write_registry(
        tmp_path,
        recipients=[
            {"alias": "owner", "target": "u1@im.wechat", "enabled": True},
            {"alias": "paused", "target": "u2@im.wechat", "enabled": False},
        ],
    )
    document = load_recipient_registry(path)

    write_recipient_registry(path, document)
    reloaded = load_recipient_registry(path)

    assert [item.alias for item in reloaded.recipients] == ["owner", "paused"]
    assert [item.alias for item in reloaded.enabled_recipients] == ["owner"]
    assert path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("kind", ("missing", "directory", "symlink", "wrong_mode"))
def test_load_rejects_unsafe_file_identity(tmp_path: Path, kind: str) -> None:
    tmp_path.chmod(0o700)
    path = tmp_path / "recipients.json"
    if kind == "directory":
        path.mkdir()
    elif kind == "symlink":
        target = _write_registry(tmp_path)
        path = tmp_path / "linked.json"
        path.symlink_to(target)
    elif kind == "wrong_mode":
        path = _write_registry(tmp_path)
        path.chmod(0o640)

    with pytest.raises(RecipientRegistryError):
        load_recipient_registry(path)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("version", 2),
        ("version", True),
        ("channel", "wecom"),
        ("account_id", " "),
        ("account_id", 7),
    ),
)
def test_load_rejects_invalid_document_fields(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    kwargs = {field: value}
    path = _write_registry(tmp_path, **kwargs)

    with pytest.raises(RecipientRegistryError):
        load_recipient_registry(path)


def test_load_rejects_malformed_json_and_extra_schema_fields(tmp_path: Path) -> None:
    tmp_path.chmod(0o700)
    malformed = tmp_path / "malformed.json"
    malformed.write_text("{", encoding="utf-8")
    malformed.chmod(0o600)
    extra = _write_registry(tmp_path)
    payload = json.loads(extra.read_text(encoding="utf-8"))
    payload["unexpected"] = True
    extra.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(RecipientRegistryError):
        load_recipient_registry(malformed)
    with pytest.raises(RecipientRegistryError):
        load_recipient_registry(extra)


@pytest.mark.parametrize(
    "recipients",
    (
        [],
        [{"alias": "owner", "target": "u1@im.wechat", "enabled": False}],
        [{"alias": " ", "target": "u1@im.wechat", "enabled": True}],
        [{"alias": "owner", "target": "not-direct", "enabled": True}],
        [{"alias": "owner", "target": "u1@im.wechat", "enabled": 1}],
        [{"alias": "owner", "target": "u1@im.wechat", "enabled": True, "x": 1}],
        [
            {"alias": "owner", "target": "u1@im.wechat", "enabled": True},
            {"alias": "owner", "target": "u2@im.wechat", "enabled": False},
        ],
        [
            {"alias": "owner", "target": "u1@im.wechat", "enabled": True},
            {"alias": "other", "target": "u1@im.wechat", "enabled": False},
        ],
    ),
)
def test_load_rejects_invalid_recipient_records(
    tmp_path: Path,
    recipients: list[dict[str, object]],
) -> None:
    path = _write_registry(tmp_path, recipients=recipients)

    with pytest.raises(RecipientRegistryError):
        load_recipient_registry(path)


def test_load_rejects_more_than_sixteen_total_records(tmp_path: Path) -> None:
    path = _write_registry(
        tmp_path,
        recipients=[
            {
                "alias": f"member_{index}",
                "target": f"u{index}@im.wechat",
                "enabled": index == 0,
            }
            for index in range(17)
        ],
    )

    with pytest.raises(RecipientRegistryError):
        load_recipient_registry(path)


def test_atomic_write_requires_existing_private_parent(tmp_path: Path) -> None:
    document = RecipientRegistryDocument(
        1,
        "openclaw-weixin",
        "account-fixture",
        (NotificationRecipient("owner", "u1@im.wechat", True),),
    )
    missing_parent = tmp_path / "missing" / "recipients.json"

    with pytest.raises(RecipientRegistryError):
        write_recipient_registry(missing_parent, document)
    assert not missing_parent.parent.exists()

    tmp_path.chmod(0o755)
    with pytest.raises(RecipientRegistryError):
        write_recipient_registry(tmp_path / "recipients.json", document)


def test_add_recipient_preserves_document_and_rejects_duplicates() -> None:
    document = RecipientRegistryDocument(
        1,
        "openclaw-weixin",
        "account-fixture",
        (
            NotificationRecipient("owner", "u1@im.wechat", True),
            NotificationRecipient("paused", "u2@im.wechat", False),
        ),
    )

    updated = add_recipient(
        document,
        NotificationRecipient("member_2", "u3@im.wechat", True),
    )

    assert [item.alias for item in updated.recipients] == ["owner", "paused", "member_2"]
    with pytest.raises(RecipientRegistryError):
        add_recipient(document, NotificationRecipient("owner", "u3@im.wechat", True))
    with pytest.raises(RecipientRegistryError):
        add_recipient(document, NotificationRecipient("other", "u1@im.wechat", True))
