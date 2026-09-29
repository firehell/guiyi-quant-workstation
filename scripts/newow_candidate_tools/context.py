"""Immutable task inputs and frozen source identity."""

from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import date, datetime, timezone
from pathlib import Path
import re
import json
import hashlib
import subprocess
from urllib.parse import urlsplit

FREQUENCIES = ("5m", "15m", "30m", "60m")
MODES = ("trend", "oscillation", "dual")


def need(condition: bool, code: str) -> None:
    if not condition:
        raise ValueError(code)


def instant(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    need(
        parsed.tzinfo is not None and parsed.utcoffset() is not None,
        "TIMEZONE_REQUIRED",
    )
    return parsed.astimezone(timezone.utc)


def origin(value: str) -> str:
    parsed = urlsplit(value)
    need(
        parsed.scheme == "http"
        and parsed.hostname in ("127.0.0.1", "localhost", "::1")
        and parsed.username is None
        and parsed.password is None
        and parsed.path == ""
        and not parsed.query
        and not parsed.fragment
        and parsed.port is not None
        and 1024 <= parsed.port <= 65535,
        "LOCAL_ORIGIN_REQUIRED",
    )
    return value


@dataclass(frozen=True)
class Candidate:
    product: str
    code_sha: str
    worktree: str
    since: str
    through: str
    as_of: str
    schema: str
    api_origin: str
    web_origin: str
    frequencies: tuple[str, ...] = FREQUENCIES
    web_code_sha: str | None = None

    @classmethod
    def from_mapping(cls, data: dict) -> Candidate:
        required = (
            "product",
            "code_sha",
            "worktree",
            "since",
            "through",
            "as_of",
            "schema",
            "api_origin",
            "web_origin",
        )
        need(
            isinstance(data, dict)
            and all(isinstance(data.get(k), str) for k in required),
            "CANDIDATE_FIELDS_REQUIRED",
        )
        need(re.fullmatch("[a-z]{1,3}", data["product"]) is not None, "PRODUCT_INVALID")
        need(
            re.fullmatch("[a-f0-9]{40}", data["code_sha"]) is not None,
            "CODE_SHA_INVALID",
        )
        web_code = data.get("web_code_sha")
        need(
            web_code is None
            or isinstance(web_code, str)
            and re.fullmatch("[a-f0-9]{40}", web_code) is not None,
            "WEB_CODE_SHA_INVALID",
        )
        need(
            Path(data["worktree"]).is_absolute() and Path(data["worktree"]).is_dir(),
            "WORKTREE_REQUIRED",
        )
        need(
            date.fromisoformat(data["since"]) <= date.fromisoformat(data["through"]),
            "WINDOW_INVALID",
        )
        instant(data["as_of"])
        need(
            re.fullmatch("newow_intraday_[a-z0-9_]{1,40}", data["schema"]) is not None,
            "CANDIDATE_SCHEMA_REQUIRED",
        )
        origin(data["api_origin"])
        origin(data["web_origin"])
        need(
            data["api_origin"] != data["web_origin"],
            "DISTINCT_PREVIEW_ORIGINS_REQUIRED",
        )
        frequencies = tuple(data.get("frequencies", FREQUENCIES))
        need(frequencies == FREQUENCIES, "EXACT_FOUR_PERIODS_REQUIRED")
        return cls(
            **{k: data[k] for k in required},
            frequencies=frequencies,
            web_code_sha=web_code,
        )

    def to_mapping(self) -> dict:
        result = asdict(self)
        result["frequencies"] = list(self.frequencies)
        return result

    @property
    def task_sha256(self) -> str:
        return hashlib.sha256(
            json.dumps(
                self.to_mapping(),
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode()
        ).hexdigest()

    def proof(self, **fields) -> dict:
        return dict(
            status="PASS",
            product=self.product,
            code_sha=self.code_sha,
            as_of=self.as_of,
            task_sha256=self.task_sha256,
            **fields,
        )

    def frozen_check(self) -> dict:
        root = Path(self.worktree).resolve()
        cmd = ["git", "-c", "core.fsmonitor=false"]
        head = subprocess.check_output(
            [*cmd, "rev-parse", "HEAD"], cwd=root, text=True, timeout=15
        ).strip()
        need(head == self.code_sha, "FROZEN_HEAD_CHANGED")
        dirty = subprocess.check_output(
            [
                *cmd,
                "status",
                "--porcelain",
                "--untracked-files=all",
                "--",
                "services",
                "packages",
            ],
            cwd=root,
            text=True,
            timeout=15,
        )
        need(not dirty.strip(), "FROZEN_PRODUCT_CODE_DIRTY")
        return self.proof()
