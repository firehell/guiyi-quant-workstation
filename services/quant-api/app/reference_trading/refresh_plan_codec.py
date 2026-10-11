"""Lossless bounded storage for frozen refresh plans, decoded only when selected.

This codec changes storage representation, never the historical plan contract.
The control file and one decoded plan each retain the existing 64 MB ceiling.
"""
from __future__ import annotations

import base64
from hashlib import sha256
import json
import zlib

CODEC = 'newow_refresh_plan_zlib_v1'
MAX_BYTES = 64_000_000
_KEYS = {'codec', 'decoded_bytes', 'decoded_sha256', 'compressed_sha256', 'payload'}


class RefreshPlanCodecError(ValueError):
    def __init__(self):
        super().__init__('REFRESH_PLAN_CODEC_INVALID')


def _digest(value):
    return isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def validate_encoded_plan(value: object) -> bytes:
    """Check the small envelope and compressed content without expanding the plan."""
    if (not isinstance(value, dict) or set(value) != _KEYS or value['codec'] != CODEC
            or type(value['decoded_bytes']) is not int or not 0 < value['decoded_bytes'] <= MAX_BYTES
            or not _digest(value['decoded_sha256']) or not _digest(value['compressed_sha256'])
            or not isinstance(value['payload'], str) or len(value['payload']) > ((MAX_BYTES + 2) // 3) * 4):
        raise RefreshPlanCodecError()
    try:
        compressed = base64.b64decode(value['payload'], validate=True)
    except (ValueError, TypeError) as error:
        raise RefreshPlanCodecError() from error
    if (base64.b64encode(compressed).decode('ascii') != value['payload']
            or len(compressed) > MAX_BYTES or sha256(compressed).hexdigest() != value['compressed_sha256']):
        raise RefreshPlanCodecError()
    return compressed


def encode_plan(value: object) -> dict:
    if not isinstance(value, dict):
        raise RefreshPlanCodecError()
    if 'codec' in value:
        validate_encoded_plan(value)
        return value
    try:
        raw = json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
    except (TypeError, ValueError) as error:
        raise RefreshPlanCodecError() from error
    if not 0 < len(raw) <= MAX_BYTES:
        raise RefreshPlanCodecError()
    compressed = zlib.compress(raw)
    return {'codec': CODEC, 'decoded_bytes': len(raw), 'decoded_sha256': sha256(raw).hexdigest(),
        'compressed_sha256': sha256(compressed).hexdigest(),
        'payload': base64.b64encode(compressed).decode('ascii')}


def decode_plan(value: object) -> dict:
    if not isinstance(value, dict):
        raise RefreshPlanCodecError()
    if 'codec' not in value:
        return value  # Legacy plans remain subject to plan_from_dict's full contract.
    compressed = validate_encoded_plan(value)
    decoder = zlib.decompressobj()
    try:
        raw = decoder.decompress(compressed, value['decoded_bytes'] + 1)
    except zlib.error as error:
        raise RefreshPlanCodecError() from error
    if (not decoder.eof or decoder.unused_data or decoder.unconsumed_tail
            or len(raw) != value['decoded_bytes'] or sha256(raw).hexdigest() != value['decoded_sha256']):
        raise RefreshPlanCodecError()
    try:
        plan = json.loads(raw)
    except (ValueError, UnicodeError, RecursionError) as error:
        raise RefreshPlanCodecError() from error
    if not isinstance(plan, dict):
        raise RefreshPlanCodecError()
    return plan
