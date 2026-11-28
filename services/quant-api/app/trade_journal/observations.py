"""Frozen chart records. A capture and its exact PNG are written in one transaction."""

import base64
import binascii
from datetime import date, timedelta
from hashlib import sha256
import json
import math
import struct
from typing import Annotated, Literal
from uuid import UUID
import zlib

from pydantic import AwareDatetime, Field, JsonValue, ValidationError, model_validator

from .contracts import Contract, Identity, Input, Note, Product
from .store import JournalError, JournalStore, encode

PNG_LIMIT = 6 * 1024 * 1024
METADATA_LIMIT = 1024 * 1024
BODY_LIMIT = 4 * ((PNG_LIMIT + 2) // 3) + METADATA_LIMIT
Frequency = Literal["1m", "5m", "15m", "30m", "60m", "1d", "1w"]
Details = dict[Identity, JsonValue]


class Window(Input):
    start: AwareDatetime = Field(alias="from")
    end: AwareDatetime = Field(alias="to")

    @model_validator(mode="after")
    def valid_order(self):
        if self.start > self.end:
            raise ValueError("window")
        return self


class Indicator(Input):
    id: Identity
    version: Identity | None
    cutoff: AwareDatetime | None
    parameters: Details
    source: Details


class Pane(Input):
    id: Identity
    frequency: Frequency
    series_kind: Literal["contract", "actual_dominant"]
    physical_contract: Contract
    window: Window
    source: Annotated[Details, Field(min_length=1)]
    indicators: list[Indicator] = Field(max_length=64)
    drawings: list[Details] = Field(max_length=256)
    ranges: Details


class Snapshot(Input):
    schema_version: Literal[1]
    captured_at: AwareDatetime
    product: Product
    physical_contract: Contract
    panes: list[Pane] = Field(min_length=1, max_length=12)
    active_pane: Identity
    layout: Identity

    @model_validator(mode="after")
    def validate_panes(self):
        panes = {pane.id: pane for pane in self.panes}
        if len(panes) != len(self.panes) or self.active_pane not in panes:
            raise ValueError("active pane")
        if self.physical_contract != panes[self.active_pane].physical_contract:
            raise ValueError("active contract")
        if any(p.physical_contract.rstrip("0123456789") != self.product for p in self.panes):
            raise ValueError("product")
        return self


class Observation(Input):
    note: Annotated[Note, Field(min_length=1)]
    trading_day: date
    snapshot: Snapshot


def valid_json_tree(value, depth=0):
    if depth > 16:
        return False
    if isinstance(value, dict):
        return len(value) <= 512 and all(
            0 < len(k) <= 256 and "\x00" not in k and valid_json_tree(v, depth + 1) for k, v in value.items()
        )
    if isinstance(value, list):
        return len(value) <= 8192 and all(valid_json_tree(v, depth + 1) for v in value)
    if isinstance(value, str):
        return len(value) <= 16000 and "\x00" not in value
    if isinstance(value, float):
        return math.isfinite(value)
    return True


def decode_capture(raw: bytes) -> tuple[Observation, bytes]:
    try:
        content = json.loads(raw)
        image = content.pop("image")
        if not isinstance(image, str) or len(image) > 4 * ((PNG_LIMIT + 2) // 3):
            raise ValueError
        if not valid_json_tree(content) or len(json.dumps(content, ensure_ascii=False).encode()) > METADATA_LIMIT:
            raise ValueError
        capture = Observation.model_validate(content)
        png = base64.b64decode(image, validate=True)
        validate_canvas_png(png)
        return capture, png
    except (AttributeError, ValueError, KeyError, TypeError, ValidationError, RecursionError, zlib.error, struct.error):
        raise JournalError("JOURNAL_OBSERVATION_INVALID", 422) from None


def validate_canvas_png(png: bytes):
    """Accept complete, bounded 8-bit non-interlaced canvas PNGs."""
    if len(png) > PNG_LIMIT or not png.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("png")
    offset = 8
    pixels = bytearray()
    width = height = channels = 0
    ended = False
    while offset + 12 <= len(png):
        size, kind = struct.unpack_from(">I4s", png, offset)
        end = offset + 12 + size
        if end > len(png):
            raise ValueError("chunk length")
        header_and_data = memoryview(png)[offset + 4:end - 4]
        if binascii.crc32(header_and_data) != struct.unpack_from(">I", png, end - 4)[0]:
            raise ValueError("chunk checksum")
        data = header_and_data[4:]
        if offset == 8 and kind != b"IHDR":
            raise ValueError("header")
        if kind == b"IHDR":
            if offset != 8 or size != 13:
                raise ValueError("header")
            width, height, depth, color, compression, filter_method, interlace = struct.unpack(">IIBBBBB", data)
            channels = {0: 1, 2: 3, 4: 2, 6: 4}.get(color, 0)
            if not (0 < width <= 8192 and 0 < height <= 8192 and width * height <= 16_777_216
                    and channels and depth == 8 and compression == filter_method == interlace == 0):
                raise ValueError("image dimensions or encoding")
        elif kind == b"IDAT":
            pixels.extend(data)
        elif kind == b"IEND":
            if size or end != len(png):
                raise ValueError("end")
            ended = True
            break
        elif kind[:1].isupper() and kind != b"PLTE":
            raise ValueError("unknown critical chunk")
        offset = end
    if not ended or not pixels:
        raise ValueError("incomplete")
    stride = width * channels + 1
    expected = stride * height
    decoder = zlib.decompressobj()
    raw = decoder.decompress(pixels, expected + 1)
    if not decoder.eof or decoder.unused_data or len(raw) != expected or any(f > 4 for f in raw[::stride]):
        raise ValueError("pixel stream")


def write_observation(store: JournalStore, observation_id: UUID, key: UUID, capture: Observation, png: bytes):
    body = capture.model_dump(mode="json", by_alias=True)
    fingerprint_data = {**body, "png_sha256": sha256(png).hexdigest()}

    def write():
        row = store.one("""
            INSERT INTO trade_journal_observations (id, trading_day, note, snapshot, png)
            VALUES (:id, :day, :note, CAST(:snapshot AS jsonb), :png)
            ON CONFLICT DO NOTHING RETURNING id
        """, id=observation_id, day=capture.trading_day, note=capture.note, snapshot=encode(body["snapshot"]), png=png)
        if not row:
            raise JournalError("JOURNAL_OBSERVATION_EXISTS")
        return row
    return store.mutate(key, f"observation:{observation_id}", fingerprint_data, write)


def list_observations(store: JournalStore, period: str, anchor: date, offset: int):
    end = anchor + timedelta(days=6) if period == "week" else anchor
    rows = store.many("""
        SELECT id, trading_day, left(note,180) AS note, recorded_at, snapshot->>'product' AS product,
            snapshot->>'physical_contract' AS physical_contract, snapshot->>'captured_at' AS captured_at,
            (SELECT p->>'frequency' FROM jsonb_array_elements(snapshot->'panes') p
             WHERE p->>'id'=snapshot->>'active_pane') AS frequency
        FROM trade_journal_observations WHERE trading_day BETWEEN :start AND :end
        ORDER BY trading_day DESC, recorded_at DESC, id LIMIT 31 OFFSET :offset
    """, start=anchor, end=end, offset=offset)
    return {"items": rows[:30], "next_offset": offset + 30 if len(rows) > 30 else None}


def get_observation(store: JournalStore, observation_id: UUID, image=False):
    sql = ("SELECT png FROM trade_journal_observations WHERE id=:id" if image else
           "SELECT id, trading_day, note, recorded_at, snapshot FROM trade_journal_observations WHERE id=:id")
    row = store.one(sql, id=observation_id)
    if row is None:
        raise JournalError("JOURNAL_OBSERVATION_NOT_FOUND", 404)
    return row
