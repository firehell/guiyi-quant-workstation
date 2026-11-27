"""Persist a Canonical subscriber's accepted results and cursor in one atomic file."""

from dataclasses import asdict, fields
from datetime import date, datetime
from hashlib import sha256
import json
from pathlib import Path

from guiyi_quant.compute import REGISTRY, FeatureIdentity, FeaturePoint, SeriesIdentity, Status

from app.market_data.after_market_history import _bytes
from app.market_data.live_recovery_guard import _file_guard
from app.runtime_handover import _write

from .contracts import ComputeCheckpoint, FeatureUpdate


MAX_PROGRESS_BYTES = 4 * 1024 * 1024


class PublicationProgress:
    def __init__(self, root: Path, windows):
        # The scope includes resolved requests and their current formula/backend.
        # A changed subscription must be enrolled explicitly as a new identity.
        key = []
        for window in windows:
            scope = window.scope
            requests = []
            for request in scope.features:
                definition = REGISTRY.definition(request.feature_id)
                requests.append([request.feature_id, definition.formula_version,
                                 definition.backend_version, dict(definition.resolve(request))])
            key.append([scope.consumer, scope.product, scope.physical_contract, scope.segment_id,
                        scope.frequency, window.since.isoformat(), window.through.isoformat(), requests])
        self._fingerprint = _digest(key)
        self._root = root
        self._path = root / "canonical-compute-progress.json"

    def guard(self):
        return _file_guard("canonical-compute.lock", root=self._root / "live-recovery-guards",
                           wait=False, legacy_root=True)

    def load(self, make_state):
        try:
            payload = json.loads(_bytes(self._path, max_bytes=MAX_PROGRESS_BYTES))
        except FileNotFoundError:
            return {}
        if (not isinstance(payload, dict) or payload.get("schema") != 1 or payload.get("scope") != self._fingerprint
                or _digest(payload.get("rows")) != payload.get("sha256")):
            raise ValueError("COMPUTE_CANONICAL_PROGRESS_INVALID")
        try:
            return {
                int(index): make_state(
                    row["identity"], (date.fromisoformat(row["day"]), datetime.fromisoformat(row["finished"])),
                    row["revision"], date.fromisoformat(row["through"]), row["digest"],
                    tuple(_decode_update(item) for item in row["updates"]),
                )
                for index, row in payload["rows"].items()
            }
        except (KeyError, TypeError, ValueError):
            raise ValueError("COMPUTE_CANONICAL_PROGRESS_INVALID") from None

    def store(self, states):
        rows = {
            str(index): {
                "identity": state.identity, "day": state.order[0].isoformat(),
                "finished": state.order[1].isoformat(), "revision": state.product_revision,
                "through": state.through.isoformat(), "digest": state.input_digest,
                "updates": [_encode_update(update) for update in state.updates],
            }
            for index, state in states.items()
        }
        payload = {"schema": 1, "scope": self._fingerprint, "rows": rows, "sha256": _digest(rows)}
        if len(_json(payload)) > MAX_PROGRESS_BYTES:
            raise ValueError("COMPUTE_CANONICAL_PROGRESS_TOO_LARGE")
        _write(self._path, payload)


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _digest(value):
    return sha256(_json(value)).hexdigest()


def _encode_update(update):
    checkpoint = asdict(update.checkpoint)
    for key in ("as_of", "first_bar_end", "last_bar_end"):
        stamp = checkpoint["identity"][key]
        checkpoint["identity"][key] = None if stamp is None else stamp.isoformat()
    value = {field.name: getattr(update, field.name) for field in fields(FeatureUpdate)}
    value["checkpoint"] = checkpoint
    point = update.point
    if point is not None:
        value["point"] = {
            "bar_end": point.bar_end.isoformat(), "available_at": point.available_at.isoformat(),
            "status": point.status.value, "values": None if point.values is None else dict(point.values),
            "diagnostic": point.diagnostic,
        }
    return value


def _decode_update(value):
    checkpoint = value.pop("checkpoint")
    identity = checkpoint.pop("identity")
    identity["source"] = SeriesIdentity(**identity["source"])
    for key in ("as_of", "first_bar_end", "last_bar_end"):
        if identity[key] is not None:
            identity[key] = datetime.fromisoformat(identity[key])
    point = value.pop("point")
    if point is not None:
        point["status"] = Status(point["status"])
        for key in ("bar_end", "available_at"):
            point[key] = datetime.fromisoformat(point[key])
        point = FeaturePoint(**point)
    return FeatureUpdate(ComputeCheckpoint(FeatureIdentity(**identity), **checkpoint), point, **value)
