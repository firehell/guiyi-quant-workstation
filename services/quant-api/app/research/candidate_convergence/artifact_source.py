from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from types import MappingProxyType


_LOWER_SHA256 = re.compile(r"[0-9a-f]{64}", flags=re.ASCII)


class FiveCandidateDossierSourceError(ValueError):
    code = "FIVE_CANDIDATE_DOSSIER_SOURCE_INVALID"

    def __init__(self) -> None:
        super().__init__(self.code)


@dataclass(frozen=True, slots=True)
class SourceArtifactRef:
    artifact_id: str
    path: str
    expected_sha256: str

    def __post_init__(self) -> None:
        if (
            type(self.artifact_id) is not str
            or not self.artifact_id
            or _has_control_character(self.artifact_id)
            or type(self.path) is not str
            or not self.path
            or _has_control_character(self.path)
            or PurePosixPath(self.path).is_absolute()
            or any(part in {"", ".", ".."} for part in self.path.split("/"))
            or type(self.expected_sha256) is not str
            or _LOWER_SHA256.fullmatch(self.expected_sha256) is None
        ):
            raise FiveCandidateDossierSourceError()


@dataclass(frozen=True, slots=True)
class VerifiedJsonArtifact:
    ref: SourceArtifactRef
    verified_sha256: str
    payload: Mapping[str, object]


def verify_json_artifact(
    ref: SourceArtifactRef,
    project_root: Path,
    error_type: type[ValueError] = FiveCandidateDossierSourceError,
) -> VerifiedJsonArtifact:
    root = project_root.resolve()
    relative = PurePosixPath(ref.path)
    if relative.is_absolute() or ".." in relative.parts or "." in relative.parts:
        raise error_type()
    try:
        resolved = (root / Path(*relative.parts)).resolve(strict=True)
        if not resolved.is_relative_to(root) or not resolved.is_file():
            raise error_type()
        raw = resolved.read_bytes()
        if hashlib.sha256(raw).hexdigest() != ref.expected_sha256:
            raise error_type()
        payload = json.loads(raw.decode("utf-8", errors="strict"))
        if type(payload) is not dict:
            raise error_type()
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise error_type() from None
    return VerifiedJsonArtifact(
        ref=ref,
        verified_sha256=ref.expected_sha256,
        payload=MappingProxyType(dict(payload)),
    )


def _has_control_character(value: str) -> bool:
    return any(ord(character) < 32 or ord(character) == 127 for character in value)
