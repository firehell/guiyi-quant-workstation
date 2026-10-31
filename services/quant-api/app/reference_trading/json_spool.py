"""Private, disposable JSON spool for bounded historical replay inputs.

The spool is a process-local materialization of verified inputs, never a source
of market or trading facts. Its decoder is explicit; no Python object loading
or pickle is involved.
"""

from __future__ import annotations

from array import array
from collections.abc import Callable, Iterator, Sequence
from datetime import date, datetime
from decimal import Decimal
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import tempfile
from typing import Generic, TypeVar, overload


T = TypeVar("T")


class JsonSpoolSequence(Sequence[T], Generic[T]):
    """Append once, seal, then read only bounded slices or individual items."""

    def __init__(
        self, *, encode: Callable[[T], object], decode: Callable[[object], T],
        directory: Path | None = None, max_slice: int = 256,
        max_bytes: int = 2_000_000_000,
        unique_key: Callable[[T], str] | None = None,
        validate: Callable[[T], None] | None = None,
    ) -> None:
        if type(max_slice) is not int or max_slice < 1:
            raise ValueError("REFERENCE_SPOOL_SLICE_INVALID")
        if type(max_bytes) is not int or max_bytes < 1:
            raise ValueError("REFERENCE_SPOOL_BUDGET_INVALID")
        self._encode = encode
        self._decode = decode
        self._unique_key = unique_key
        self._validate = validate
        self._max_slice = max_slice
        self._max_bytes = max_bytes
        self._path = Path(tempfile.mkdtemp(
            prefix="reference-input-", dir=directory,
        ))
        try:
            os.chmod(self._path, 0o700)
            self._file = (self._path / "bars.jsonl").open("w+b")
            self._digests = (self._path / "digests.bin").open("w+b")
            os.chmod(self._path / "bars.jsonl", 0o600)
            os.chmod(self._path / "digests.bin", 0o600)
        except BaseException:
            for name in ("_file", "_digests"):
                opened = getattr(self, name, None)
                if opened is not None:
                    opened.close()
            shutil.rmtree(self._path)
            raise
        self._offsets = array("Q")
        self._sha256 = sha256()
        self._sealed = False
        self._closed = False
        self._read_fd: int | None = None
        self._digest_fd: int | None = None
        self._size = 0
        self._index = None
        if unique_key is not None:
            try:
                self._index = sqlite3.connect(self._path / "unique.sqlite")
                self._index.execute("CREATE TABLE seen (value TEXT PRIMARY KEY) WITHOUT ROWID")
            except BaseException:
                self.close()
                raise

    @property
    def sealed(self) -> bool:
        return self._sealed and not self._closed

    @property
    def digest(self) -> str:
        if not self.sealed:
            raise ValueError("REFERENCE_SPOOL_NOT_SEALED")
        return self._sha256.hexdigest()

    def append(self, item: T) -> None:
        if self._sealed or self._closed:
            raise ValueError("REFERENCE_SPOOL_CLOSED")
        if self._validate is not None:
            self._validate(item)
        line = json.dumps(
            self._encode(item), sort_keys=True, separators=(",", ":"),
            ensure_ascii=True, allow_nan=False,
        ).encode("ascii") + b"\n"
        if len(line) > 1_000_000 or self._size + len(line) > self._max_bytes:
            raise ValueError("REFERENCE_SPOOL_BUDGET_EXCEEDED")
        if self._index is not None:
            key = self._unique_key(item)  # type: ignore[misc]
            try:
                self._index.execute("INSERT INTO seen(value) VALUES (?)", (key,))
            except sqlite3.IntegrityError as error:
                raise ValueError("REFERENCE_SPOOL_DUPLICATE_INPUT") from error
        self._offsets.append(self._file.tell())
        self._file.write(line)
        self._digests.write(sha256(line).digest())
        self._sha256.update(line)
        self._size += len(line)

    def seal(self) -> JsonSpoolSequence[T]:
        if self._closed:
            raise ValueError("REFERENCE_SPOOL_CLOSED")
        if not self._sealed:
            self._file.flush()
            os.fsync(self._file.fileno())
            self._digests.flush()
            os.fsync(self._digests.fileno())
            if self._file.tell() != self._size or self._digests.tell() != 32 * len(self._offsets):
                raise ValueError("REFERENCE_SPOOL_CORRUPT")
            if self._index is not None:
                self._index.close()
                self._index = None
                (self._path / "unique.sqlite").unlink()
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            read_fd = os.open(self._path / "bars.jsonl", flags)
            self._read_fd = read_fd
            digest_fd = os.open(self._path / "digests.bin", flags)
            self._digest_fd = digest_fd
            for original, sealed in ((self._file.fileno(), read_fd),
                                     (self._digests.fileno(), digest_fd)):
                a, b = os.fstat(original), os.fstat(sealed)
                if (a.st_dev, a.st_ino) != (b.st_dev, b.st_ino) or not stat.S_ISREG(b.st_mode):
                    raise ValueError("REFERENCE_SPOOL_CORRUPT")
            os.fchmod(read_fd, 0o400)
            os.fchmod(digest_fd, 0o400)
            self._file.close()
            self._digests.close()
            self._sealed = True
        return self

    def __len__(self) -> int:
        if not self.sealed:
            raise ValueError("REFERENCE_SPOOL_NOT_SEALED")
        return len(self._offsets)

    @overload
    def __getitem__(self, index: int) -> T: ...

    @overload
    def __getitem__(self, index: slice) -> tuple[T, ...]: ...

    def __getitem__(self, index: int | slice) -> T | tuple[T, ...]:
        if not self.sealed:
            raise ValueError("REFERENCE_SPOOL_NOT_SEALED")
        if isinstance(index, slice):
            start, stop, step = index.indices(len(self))
            count = len(range(start, stop, step))
            if count > self._max_slice:
                raise ValueError("REFERENCE_SPOOL_SLICE_EXCEEDED")
            return tuple(self[position] for position in range(start, stop, step))
        if type(index) is not int:
            raise TypeError("spool indices must be integers or slices")
        if index < 0:
            index += len(self)
        if not 0 <= index < len(self):
            raise IndexError(index)
        line = self._line_at(index)
        try:
            return self._decode(json.loads(line))
        except (TypeError, ValueError, KeyError) as error:
            raise ValueError("REFERENCE_SPOOL_CORRUPT") from error

    def __iter__(self) -> Iterator[T]:
        if not self.sealed:
            raise ValueError("REFERENCE_SPOOL_NOT_SEALED")
        for index in range(len(self._offsets)):
            line = self._line_at(index)
            try:
                yield self._decode(json.loads(line))
            except (TypeError, ValueError, KeyError) as error:
                raise ValueError("REFERENCE_SPOOL_CORRUPT") from error

    def _line_at(self, index: int) -> bytes:
        start = self._offsets[index]
        end = self._offsets[index + 1] if index + 1 < len(self._offsets) else self._size
        if not 0 < end - start <= 1_000_000:
            raise ValueError("REFERENCE_SPOOL_CORRUPT")
        read_fd, digest_fd = self._read_fd, self._digest_fd
        if read_fd is None or digest_fd is None:
            raise ValueError("REFERENCE_SPOOL_CORRUPT")
        line = os.pread(read_fd, end - start, start)
        digest = os.pread(digest_fd, 32, index * 32)
        if not line.endswith(b"\n") or len(digest) != 32 or sha256(line).digest() != digest:
            raise ValueError("REFERENCE_SPOOL_CORRUPT")
        return line

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._index is not None:
            self._index.close()
            self._index = None
        if self._read_fd is not None:
            os.close(self._read_fd)
        if self._digest_fd is not None:
            os.close(self._digest_fd)
        if not self._file.closed:
            self._file.close()
        if not self._digests.closed:
            self._digests.close()
        shutil.rmtree(self._path)

    def __del__(self) -> None:
        try:
            self.close()
        except (AttributeError, OSError):
            pass


def encode_product_bar(item: object) -> dict[str, object]:
    """Wire only the known, validated ProductBar contract."""
    from guiyi_quant.newow.product_contracts import ProductBar

    if not isinstance(item, ProductBar):
        raise TypeError("expected ProductBar")
    bar = item.bar
    return {
        "v": 1,
        "product": bar.product,
        "physical_contract": bar.physical_contract,
        "segment_id": bar.segment_id,
        "trading_day": bar.trading_day.isoformat(),
        "bar_end": bar.bar_end.isoformat(),
        "open": str(bar.open),
        "high": str(bar.high),
        "low": str(bar.low),
        "close": str(bar.close),
        "volume": bar.volume,
        "open_interest": bar.open_interest,
        "source_identity": bar.source_identity,
        "observation_eligible": bar.observation_eligible,
        "completed": bar.completed,
        "series_kind": item.series_kind,
        "frequency": item.frequency.value,
        "calculation_segment_id": item.calculation_segment_id,
        "source_bar_sha256": item.source_bar_sha256,
    }


def decode_product_bar(raw: object):
    from guiyi_quant.newow.models import NewowDailyBar
    from guiyi_quant.newow.product_contracts import ProductBar, ProductFrequency

    if not isinstance(raw, dict) or raw.get("v") != 1 or set(raw) != {
        "v", "product", "physical_contract", "segment_id", "trading_day",
        "bar_end", "open", "high", "low", "close", "volume",
        "open_interest", "source_identity", "observation_eligible",
        "completed", "series_kind", "frequency", "calculation_segment_id",
        "source_bar_sha256",
    }:
        raise ValueError("REFERENCE_SPOOL_CODEC_INVALID")
    bar = NewowDailyBar(
        raw["product"], raw["physical_contract"], raw["segment_id"],
        date.fromisoformat(raw["trading_day"]),
        datetime.fromisoformat(raw["bar_end"]),
        Decimal(raw["open"]), Decimal(raw["high"]),
        Decimal(raw["low"]), Decimal(raw["close"]),
        raw["volume"], raw["open_interest"], raw["source_identity"],
        raw["observation_eligible"], raw["completed"],
        frequency="1d",
    )
    return ProductBar(
        bar, ProductFrequency(raw["frequency"]), raw["series_kind"],
        raw["calculation_segment_id"], raw["source_bar_sha256"],
    )
