"""Bounded immutable plan files; logical plan content and hashes stay unchanged."""

from contextlib import contextmanager
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import stat
from uuid import uuid4
import zlib

CODEC = "reference_plan_chunks_v1"
INLINE_BYTES = 16 * 1024 * 1024
MAX_HEADER_BYTES = 16 * 1024 * 1024
MAX_DECODED_BYTES = 256 * 1024 * 1024
CHUNK_BYTES = 4 * 1024 * 1024
MAX_CHUNKS = 64


class PlanBundleError(ValueError):
    def __init__(self):
        super().__init__("REFERENCE_PLAN_BUNDLE_INVALID")


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise PlanBundleError()
        result[key] = value
    return result


def _loads(raw):
    try:
        value = json.loads(
            raw,
            object_pairs_hook=_pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(PlanBundleError()),
        )
    except (ValueError, UnicodeError, RecursionError) as error:
        raise PlanBundleError() from error
    if not isinstance(value, dict):
        raise PlanBundleError()
    return value


def canonical_bytes(value):
    try:
        raw = json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    except (ValueError, TypeError, RecursionError) as error:
        raise PlanBundleError() from error
    if not isinstance(value, dict) or not 0 < len(raw) <= MAX_DECODED_BYTES:
        raise PlanBundleError()
    return raw


@contextmanager
def _parent(path, trusted_root=None):
    """Open the resolved trusted parent with no-follow at every directory hop."""
    path = Path(path).absolute()
    if path.name in {"", ".", ".."} or path.is_symlink():
        raise PlanBundleError()
    fd = None
    try:
        if trusted_root is None:
            parent = path.parent.resolve(strict=True)
            suffix = ()
        else:
            trusted = Path(trusted_root).absolute()
            suffix = path.parent.relative_to(trusted).parts
            if any(part in {".", ".."} for part in suffix):
                raise PlanBundleError()
            parent = trusted.resolve(strict=True)
        fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
        for part in (*parent.parts[1:], *suffix):
            child = os.open(
                part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd
            )
            os.close(fd)
            fd = child
        yield fd, path.name
    except OSError as error:
        raise PlanBundleError() from error
    finally:
        if fd is not None:
            os.close(fd)


def _read(fd, name, limit, expected=None):
    opened = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    with os.fdopen(opened, "rb") as file:
        before = os.fstat(file.fileno())
        if (
            not stat.S_ISREG(before.st_mode)
            or not 0 < before.st_size <= limit
            or expected is not None
            and before.st_size != expected
        ):
            raise PlanBundleError()
        data = file.read(limit + 1)
        after = os.fstat(file.fileno())
    if (
        len(data) != before.st_size
        or before.st_size != after.st_size
        or before.st_mtime_ns != after.st_mtime_ns
    ):
        raise PlanBundleError()
    return data


def _new_file(fd, name, data):
    opened = os.open(
        name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd
    )
    with os.fdopen(opened, "wb") as file:
        file.write(data)
        file.flush()
        os.fsync(file.fileno())


def _publish(fd, name, data):
    temporary = "." + uuid4().hex + ".plan-tmp"
    _new_file(fd, temporary, data)
    try:
        os.link(temporary, name, src_dir_fd=fd, dst_dir_fd=fd, follow_symlinks=False)
        os.fsync(fd)
    finally:
        os.unlink(temporary, dir_fd=fd)


def write_plan(path, value, *, force_bundle=False, trusted_root=None):
    raw = canonical_bytes(value)
    with _parent(path, trusted_root) as (fd, name):
        # No replacement, even for a prior partial write. A new exact filename
        # is required after inspection of an incomplete attempt.
        try:
            os.stat(name, dir_fd=fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise PlanBundleError()
        if len(raw) <= INLINE_BYTES and not force_bundle:
            _publish(fd, name, raw)
            return
        compressed = zlib.compress(raw)
        if (
            len(compressed) > MAX_DECODED_BYTES
            or (len(compressed) + CHUNK_BYTES - 1) // CHUNK_BYTES > MAX_CHUNKS
        ):
            raise PlanBundleError()
        os.mkdir(name + ".parts", mode=0o700, dir_fd=fd)
        parts = os.open(
            name + ".parts", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd
        )
        chunks = []
        try:
            for index, offset in enumerate(range(0, len(compressed), CHUNK_BYTES)):
                data = compressed[offset : offset + CHUNK_BYTES]
                digest = sha256(data).hexdigest()
                chunk_name = f"{index:04d}-{digest}.bin"
                _new_file(parts, chunk_name, data)
                chunks.append(
                    {"name": chunk_name, "bytes": len(data), "sha256": digest}
                )
            os.fsync(parts)
        finally:
            os.close(parts)
        head = dict(
            codec=CODEC,
            decoded_bytes=len(raw),
            decoded_sha256=sha256(raw).hexdigest(),
            compressed_bytes=len(compressed),
            compressed_sha256=sha256(compressed).hexdigest(),
            chunks=chunks,
        )
        _publish(fd, name, canonical_bytes(head))


def read_plan(path, *, trusted_root=None):
    with _parent(path, trusted_root) as (fd, name):
        head = _loads(_read(fd, name, MAX_HEADER_BYTES))
        if "codec" not in head:
            return head
        if (
            set(head)
            != {
                "codec",
                "decoded_bytes",
                "decoded_sha256",
                "compressed_bytes",
                "compressed_sha256",
                "chunks",
            }
            or head["codec"] != CODEC
            or type(head["decoded_bytes"]) is not int
            or not 0 < head["decoded_bytes"] <= MAX_DECODED_BYTES
            or type(head["compressed_bytes"]) is not int
            or not 0 < head["compressed_bytes"] <= MAX_DECODED_BYTES
            or any(
                not isinstance(head[key], str)
                or re.fullmatch("[a-f0-9]{64}", head[key]) is None
                for key in ("decoded_sha256", "compressed_sha256")
            )
            or not isinstance(head["chunks"], list)
            or not 0 < len(head["chunks"]) <= MAX_CHUNKS
        ):
            raise PlanBundleError()
        parts = os.open(
            name + ".parts", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd
        )
        decoder = zlib.decompressobj()
        compressed_hash = sha256()
        decoded_hash = sha256()
        decoded_size = compressed_size = 0
        output = []
        try:
            for index, chunk in enumerate(head["chunks"]):
                if (
                    not isinstance(chunk, dict)
                    or set(chunk) != {"name", "bytes", "sha256"}
                    or not isinstance(chunk["sha256"], str)
                    or re.fullmatch("[a-f0-9]{64}", chunk["sha256"]) is None
                    or chunk["name"] != f"{index:04d}-{chunk['sha256']}.bin"
                    or type(chunk["bytes"]) is not int
                    or not 0 < chunk["bytes"] <= CHUNK_BYTES
                ):
                    raise PlanBundleError()
                data = _read(parts, chunk["name"], CHUNK_BYTES, chunk["bytes"])
                if sha256(data).hexdigest() != chunk["sha256"]:
                    raise PlanBundleError()
                compressed_hash.update(data)
                compressed_size += len(data)
                if compressed_size > head["compressed_bytes"]:
                    raise PlanBundleError()
                raw = decoder.decompress(data, head["decoded_bytes"] - decoded_size + 1)
                decoded_size += len(raw)
                if (
                    decoded_size > head["decoded_bytes"]
                    or decoder.unused_data
                    or decoder.unconsumed_tail
                ):
                    raise PlanBundleError()
                decoded_hash.update(raw)
                output.append(raw)
        except zlib.error as error:
            raise PlanBundleError() from error
        finally:
            os.close(parts)
        if (
            not decoder.eof
            or decoded_size != head["decoded_bytes"]
            or compressed_size != head["compressed_bytes"]
            or decoded_hash.hexdigest() != head["decoded_sha256"]
            or compressed_hash.hexdigest() != head["compressed_sha256"]
        ):
            raise PlanBundleError()
        return _loads(b"".join(output))
