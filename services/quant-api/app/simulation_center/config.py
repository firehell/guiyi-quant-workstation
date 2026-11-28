"""Separate connection secrets from public deployment metadata."""

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
import stat

ACCOUNT_ALIAS = r"^[a-z][a-z0-9-]{0,39}$"
VERSION = r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}$"
INSTRUMENT = r"^(SHFE|INE|DCE|CZCE|CFFEX|GFEX):[A-Z]{1,8}[0-9]{3,4}$"
SIMNOW_FIRST_FRONT = "tcp://182.254.243.31:30001"


@dataclass(frozen=True)
class Deployment:
    strategy_id: str
    formula_version: str
    profile_id: str
    risk_policy_version: str
    instruments: tuple[str, ...]

    @classmethod
    def from_dict(cls, data: dict):
        if (not isinstance(data, dict)
                or set(data) != {"strategy_id", "formula_version", "profile_id", "risk_policy_version", "instruments"}
                or data["strategy_id"] not in ("htdy_60m", "subing_portfolio_16")):
            raise ValueError("SIMULATION_DEPLOYMENT_INVALID")
        instruments = data["instruments"]
        if (not isinstance(instruments, list) or not 1 <= len(instruments) <= 64
                or not all(isinstance(item, str) and re.fullmatch(INSTRUMENT, item) for item in instruments)
                or len(set(instruments)) != len(instruments)):
            raise ValueError("SIMULATION_INSTRUMENTS_INVALID")
        for key in ("formula_version", "profile_id", "risk_policy_version"):
            if not isinstance(data[key], str) or not re.fullmatch(VERSION, data[key]):
                raise ValueError("SIMULATION_VERSION_INVALID")
        return cls(**{**data, "instruments": tuple(instruments)})


@dataclass(frozen=True)
class ObserverConfig:
    alias: str
    front: str
    user: str = field(repr=False)
    password: str = field(repr=False)
    app_id: str = field(repr=False)
    auth_code: str = field(repr=False)
    deployment: Deployment | None = None
    account_id: str | None = field(default=None, repr=False)

    @classmethod
    def from_dict(cls, data: dict):
        keys = {"alias", "environment", "front", "user", "password", "app_id", "auth_code"}
        if (not isinstance(data, dict) or not keys <= data.keys() <= keys | {"deployment"}
                or not all(isinstance(data[key], str) for key in keys)
                or data["environment"] != "SIMNOW_FIRST" or data["front"] != SIMNOW_FIRST_FRONT
                or not re.fullmatch(ACCOUNT_ALIAS, data["alias"]) or not re.fullmatch(VERSION, data["app_id"])):
            raise ValueError("SIMNOW_CONFIGURATION_INVALID")
        for key in ("user", "password", "auth_code"):
            if not re.fullmatch(r"[!-~]{1,128}", data[key]):
                raise ValueError("SIMNOW_CREDENTIAL_INVALID")
        values = {key: data[key] for key in keys - {"environment"}}
        deployment = data.get("deployment")
        return cls(**values, deployment=Deployment.from_dict(deployment) if deployment is not None else None)


def read_config(path: Path) -> ObserverConfig:
    from dataclasses import replace

    from guiyi_quant.simnow_execution.credentials import CredentialStore

    if not path.is_absolute():
        raise ValueError("PRIVATE_CONFIG_REQUIRED")
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as file:
        info = os.fstat(file.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077 or info.st_size > 8192:
            raise ValueError("PRIVATE_CONFIG_REQUIRED")
        raw = file.read(8193)
        if len(raw) > 8192:
            raise ValueError("PRIVATE_CONFIG_REQUIRED")
    data = json.loads(raw)
    keys = {"alias", "environment", "account_id"}
    if (not isinstance(data, dict) or not keys <= data.keys() <= keys | {"deployment"}
            or not all(isinstance(data[key], str) for key in keys)
            or data["environment"] != "SIMNOW_FIRST" or not re.fullmatch(ACCOUNT_ALIAS, data["alias"])
            or not re.fullmatch(r"[0-9a-f]{64}", data["account_id"])):
        raise ValueError("SIMNOW_CONFIGURATION_INVALID")
    credentials = CredentialStore().load(data["account_id"])
    validated = ObserverConfig.from_dict({
        "alias": data["alias"], "environment": data["environment"], "front": SIMNOW_FIRST_FRONT,
        "user": credentials.user, "password": credentials.password, "app_id": "simnow_client_test",
        "auth_code": "0" * 16, "deployment": data.get("deployment"),
    })
    return replace(validated, account_id=credentials.account_id)
