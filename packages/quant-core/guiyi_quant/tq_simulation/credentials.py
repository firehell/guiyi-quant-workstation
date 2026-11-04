"""TqKq-only credentials; secrets never enter argv, files, logs or repr."""

from dataclasses import dataclass
from hashlib import sha256
import json
from ..simnow_execution.credentials import _NativeKeychain

SERVICE = "com.guiyi.quant.tqkq.primary.credentials.v1"


def account_id(username):
    if (
        not isinstance(username, str)
        or not username.strip()
        or len(username) > 256
        or "\x00" in username
    ):
        raise ValueError("TQ_USERNAME_INVALID")
    return sha256(
        json.dumps(["TQKQ", "primary", username], separators=(",", ":")).encode()
    ).hexdigest()


@dataclass(frozen=True, repr=False)
class Credentials:
    username: str
    password: str

    def __post_init__(self):
        account_id(self.username)
        if (
            not isinstance(self.password, str)
            or not 1 <= len(self.password.encode()) <= 512
            or "\x00" in self.password
        ):
            raise ValueError("TQ_PASSWORD_INVALID")

    @property
    def account_id(self):
        return account_id(self.username)

    def __repr__(self):
        return "Credentials(<redacted>)"


class CredentialStore:
    def __init__(self, backend=None):
        self.backend = (
            backend if backend is not None else _NativeKeychain(service=SERVICE)
        )

    def save(self, username, password):
        credentials = Credentials(username, password)
        raw = json.dumps({"username": username, "password": password}).encode()
        if len(raw) > 1024:
            raise ValueError("TQ_CREDENTIAL_SIZE_INVALID")
        self.backend.add("primary", raw)
        return credentials.account_id

    def update(self, username, password):
        credentials = Credentials(username, password)
        raw = json.dumps({"username": username, "password": password}).encode()
        if len(raw) > 1024:
            raise ValueError("TQ_CREDENTIAL_SIZE_INVALID")
        self.backend.update("primary", raw)
        return credentials.account_id

    def load(self):
        raw = self.backend.get("primary")
        if raw is None:
            raise ValueError("TQ_CREDENTIAL_UNAVAILABLE")
        try:
            data = json.loads(raw)
            if set(data) != {"username", "password"}:
                raise ValueError
            return Credentials(**data)
        except Exception:
            raise ValueError("TQ_CREDENTIAL_CORRUPT") from None


def setup_dialog(store=None, *, replace=False):
    """Only the native hidden text boxes see input; subprocess output stays in memory."""
    import subprocess

    def prompt(message):
        program = f'text returned of (display dialog "{message}" default answer "" with hidden answer buttons {{"取消", "保存"}} default button "保存" with title "归一量化 · 快期模拟凭据")'
        result = subprocess.run(
            ["/usr/bin/osascript", "-e", program], capture_output=True, text=True
        )
        if result.returncode != 0:
            raise ValueError("TQ_CREDENTIAL_ENTRY_CANCELLED")
        return result.stdout.removesuffix("\n")

    username = prompt("请输入快期账号（手机号、邮箱或用户名），不在聊天中发送。")
    password = prompt("请输入快期密码；仅写入本机Keychain，用于TqKq模拟。")
    target = store or CredentialStore()
    return (target.update if replace else target.save)(username, password)
