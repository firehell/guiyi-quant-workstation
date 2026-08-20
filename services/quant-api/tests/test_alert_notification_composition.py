from __future__ import annotations

import json
from pathlib import Path

from app.alerts.notification_composition import (
    build_notification_sender_from_env,
    notification_transport_status_from_env,
)
from app.alerts.notification_config import NOTIFICATION_CONFIG_ENV


MESSAGE_TOKEN = "0123456789abcdef0123456789abcdef"
SHORT_CODE = "fedcba9876543210fedcba9876543210"


class AcceptingClient:
    def __init__(self) -> None:
        self.requests: list[object] = []

    def send(self, request: object) -> str:
        self.requests.append(request)
        return SHORT_CODE


def _write_config(tmp_path: Path) -> Path:
    parent = tmp_path / "private"
    parent.mkdir(mode=0o700)
    parent.chmod(0o700)
    path = parent / "notification.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "transport": "pushplus",
                "transport_config": {
                    "message_token": MESSAGE_TOKEN,
                    "htdy_topic": "fixture-private-topic",
                },
            }
        ),
        encoding="utf-8",
    )
    path.chmod(0o600)
    return path


def test_factory_builds_dispatcher_from_one_frozen_config(
    monkeypatch,
    tmp_path: Path,
) -> None:
    path = _write_config(tmp_path)
    monkeypatch.setenv(NOTIFICATION_CONFIG_ENV, str(path))
    client = AcceptingClient()

    accepted = build_notification_sender_from_env(client=client).send_canary("owner")

    assert accepted.reference == SHORT_CODE
    assert len(client.requests) == 1
    assert client.requests[0].topic is None


def test_structural_status_reads_config_without_constructing_client(
    monkeypatch,
    tmp_path: Path,
) -> None:
    path = _write_config(tmp_path)
    monkeypatch.setenv(NOTIFICATION_CONFIG_ENV, str(path))

    assert notification_transport_status_from_env() == {
        "transport": "pushplus",
        "configured": True,
        "audience_count": 2,
        "would_send": False,
    }


def test_structural_status_is_missing_or_invalid_without_private_details(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv(NOTIFICATION_CONFIG_ENV, raising=False)
    assert notification_transport_status_from_env() == {
        "transport": "pushplus",
        "configured": False,
        "audience_count": 2,
        "would_send": False,
    }
    monkeypatch.setenv(NOTIFICATION_CONFIG_ENV, str(tmp_path / "private-value"))
    assert notification_transport_status_from_env()["configured"] is False
