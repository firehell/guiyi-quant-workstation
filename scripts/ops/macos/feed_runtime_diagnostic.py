#!/usr/bin/env python3
"""Bounded CPython 3.13 Feed inspection using LLDB memory reads only.

Attach briefly stops the process. This helper never evaluates target expressions,
calls target functions, changes Python objects, or resumes application work itself.
Unknown layouts or missing facts fail closed. Output contains no target addresses,
thread identifiers, credentials, payloads, contract names, or raw memory.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import sysconfig
import tempfile


def _now():
    return datetime.now(timezone.utc).isoformat()


def _snapshot_hash(day, contracts):
    """Canonicalize only allowlisted day and subscription identity fields."""
    if not isinstance(day, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
        raise ValueError("DATE_UNPROVEN")
    pairs = list(contracts)
    if len(pairs) > 256 or len({p[0] for p in pairs}) != len(pairs):
        raise ValueError("CONTRACTS_UNPROVEN")
    for pair in pairs:
        if (len(pair) != 2 or any(not isinstance(v, str) or
                not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", v) for v in pair)):
            raise ValueError("CONTRACTS_UNPROVEN")
    encoded = json.dumps([day, sorted(pairs)], separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _private_write(path, result):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(result, stream, sort_keys=True)
        stream.write("\n")


class _Reader:
    """Read allowlisted CPython storage; no SBValue or target execution APIs."""

    def __init__(self, process, target, layout, lldb):
        self.process, self.target, self.layout, self.lldb = process, target, layout, lldb
        self.total_read = 0
        self.off = {}
        if (process.GetState() != lldb.eStateStopped or target.GetAddressByteSize() != 8
                or target.GetByteOrder() != lldb.eByteOrderLittle
                or layout["pointer_size"] != 8):
            raise ValueError("STOPPED_ABI_UNPROVEN")
        symbols = target.FindSymbols("_PyRuntime")
        runtime = None
        for index in range(min(symbols.GetSize(), 16)):
            address = symbols.GetContextAtIndex(index).GetSymbol().GetStartAddress().GetLoadAddress(target)
            try:
                if self.read(address, 8) == b"xdebugpy":
                    runtime = address
                    break
            except ValueError:
                continue
        if runtime is None:
            raise ValueError("RUNTIME_UNPROVEN")
        version = self.integer(runtime + 8)
        if (version != layout["version"] or version >> 24 != 3 or
                (version >> 16) & 255 != 13 or self.integer(runtime + 16) != 0):
            raise ValueError("VERSION_UNPROVEN")
        offset = 24
        for group, names in layout["debug_groups"]:
            self.off[group] = {name: self.integer(runtime + offset + index * 8)
                               for index, name in enumerate(names)}
            offset += len(names) * 8
        if self.off["pyobject"]["size"] != layout["object_size"]:
            raise ValueError("OBJECT_ABI_UNPROVEN")
        self.runtime = runtime

    def read(self, address, size):
        if (self.process.GetState() != self.lldb.eStateStopped or not isinstance(address, int)
                or address <= 4096 or not 0 <= size <= 65536):
            raise ValueError("READ_BOUND_UNPROVEN")
        self.total_read += size
        if self.total_read > 16 * 1024 * 1024:
            raise ValueError("READ_BUDGET_EXCEEDED")
        error = self.lldb.SBError()
        data = self.process.ReadMemory(address, size, error)
        if not error.Success() or len(data) != size:
            raise ValueError("READ_FAILED")
        return data

    def integer(self, address, size=8, signed=False):
        return int.from_bytes(self.read(address, size), "little", signed=signed)

    def typename(self, obj):
        typ = self.integer(obj + self.off["pyobject"]["ob_type"])
        address = self.integer(typ + self.off["type_object"]["tp_name"])
        # Names alone are allowlisted; never read an arbitrary object's repr.
        data = bytearray()
        for index in range(160):
            char = self.read(address + index, 1)
            if char == b"\0":
                return data.decode("ascii")
            data.extend(char)
        raise ValueError("TYPE_NAME_UNPROVEN")

    def string(self, obj):
        if self.typename(obj) != "str":
            raise ValueError("STRING_TYPE_UNPROVEN")
        state = self.integer(obj + self.off["unicode_object"]["state"], 4)
        length = self.integer(obj + self.off["unicode_object"]["length"])
        kind, compact, ascii_only = (state >> 2) & 7, (state >> 5) & 1, (state >> 6) & 1
        if length > 2048 or not compact or kind not in (1, 2, 4):
            raise ValueError("STRING_LAYOUT_UNPROVEN")
        start = obj + (self.off["unicode_object"]["asciiobject_size"] if ascii_only
                       else self.layout["unicode_compact_size"])
        return self.read(start, length * kind).decode({1: "latin1", 2: "utf-16-le", 4: "utf-32-le"}[kind])

    def number(self, obj):
        if self.typename(obj) not in ("int", "bool"):
            raise ValueError("INTEGER_TYPE_UNPROVEN")
        tag = self.integer(obj + self.off["long_object"]["lv_tag"])
        count = tag >> 3
        if count > 3:
            raise ValueError("INTEGER_BOUND_UNPROVEN")
        value = sum(self.integer(obj + self.off["long_object"]["ob_digit"] + i * 4, 4)
                    << (30 * i) for i in range(count))
        return -value if tag & 3 == 2 else value

    def boolean(self, obj):
        if self.typename(obj) != "bool":
            raise ValueError("BOOLEAN_UNPROVEN")
        value = self.number(obj)
        if value not in (0, 1):
            raise ValueError("BOOLEAN_UNPROVEN")
        return bool(value)

    def pairs(self, keys, values=0):
        count = self.integer(keys + self.layout["dict_nentries"], signed=True)
        kind = self.integer(keys + self.layout["dict_kind"], 1)
        power = self.integer(keys + self.layout["dict_index_bytes"], 1)
        if not 0 <= count <= 2048 or power > 20 or kind not in (0, 1, 2):
            raise ValueError("DICT_LAYOUT_UNPROVEN")
        entries, stride = keys + self.layout["dict_indices"] + (1 << power), 24 if kind == 0 else 16
        for index in range(count):
            key = self.integer(entries + index * stride + (8 if kind == 0 else 0))
            if not key:
                continue
            value = self.integer(values + self.layout["dict_values"] + index * 8) if values else self.integer(
                entries + index * stride + (16 if kind == 0 else 8))
            if value:
                yield self.string(key), value

    def dict_pairs(self, obj):
        if self.typename(obj) != "dict":
            raise ValueError("DICT_TYPE_UNPROVEN")
        return self.pairs(self.integer(obj + self.off["dict_object"]["ma_keys"]),
                          self.integer(obj + self.off["dict_object"]["ma_values"]))

    def attrs(self, obj, allowed):
        typ = self.integer(obj + self.off["pyobject"]["ob_type"])
        flags = self.integer(typ + self.off["type_object"]["tp_flags"])
        if flags & self.layout["managed_dict_flag"]:
            dictionary = self.integer(obj + self.layout["managed_dict_offset"])
            if dictionary:
                items = self.dict_pairs(dictionary)
            else:
                if (not flags & self.layout["inline_values_flag"] or
                        self.integer(typ + self.layout["type_basicsize"]) != self.layout["object_size"]):
                    raise ValueError("INLINE_VALUES_UNPROVEN")
                values = obj + self.layout["object_size"]
                if self.integer(values + 3, 1) != 1:
                    raise ValueError("INLINE_VALUES_INVALID")
                items = self.pairs(self.integer(typ + self.layout["heap_cached_keys"]), values)
            return {name: value for name, value in items if name in allowed}
        position = self.integer(typ + self.layout["type_dictoffset"], signed=True)
        if position > 0:
            return {name: value for name, value in self.dict_pairs(self.integer(obj + position))
                    if name in allowed}
        # Frozen slots dataclasses expose member descriptors, never execute them.
        result = {}
        dictionary = self.integer(typ + self.layout["type_dict"])
        basicsize = self.integer(typ + self.layout["type_basicsize"])
        for name, descriptor in self.dict_pairs(dictionary):
            if name not in allowed:
                continue
            if self.typename(descriptor) != "member_descriptor":
                raise ValueError("SLOT_DESCRIPTOR_UNPROVEN")
            member = self.integer(descriptor + self.layout["member_definition"])
            if self.integer(member + self.layout["member_type"], 4) != self.layout["member_object_ex"]:
                raise ValueError("SLOT_TYPE_UNPROVEN")
            offset = self.integer(member + self.layout["member_offset"], signed=True)
            if not self.layout["object_size"] <= offset <= basicsize - 8 or offset % 8:
                raise ValueError("SLOT_OFFSET_UNPROVEN")
            result[name] = self.integer(obj + offset)
        return result

    def tuple(self, obj, maximum=256):
        if self.typename(obj) != "tuple":
            raise ValueError("TUPLE_TYPE_UNPROVEN")
        count = self.integer(obj + self.off["tuple_object"]["ob_size"], signed=True)
        if not 0 <= count <= maximum:
            raise ValueError("TUPLE_BOUND_UNPROVEN")
        return [self.integer(obj + self.off["tuple_object"]["ob_item"] + index * 8)
                for index in range(count)]

    def day(self, obj):
        if self.typename(obj) != "datetime.date":
            raise ValueError("DAY_TYPE_UNPROVEN")
        data = self.read(obj + self.layout["date_data"], 4)
        from datetime import date
        return date(data[0] * 256 + data[1], data[2], data[3]).isoformat()

    def service(self, runtime_root):
        filename = str(Path(runtime_root) / "services/quant-api/app/market_data/live_market.py")
        interpreter = self.integer(self.runtime + self.off["runtime_state"]["interpreters_head"])
        thread = self.integer(interpreter + self.off["interpreter_state"]["threads_head"])
        found = set()
        for unused in range(128):
            if not thread:
                break
            frame = self.integer(thread + self.off["thread_state"]["current_frame"])
            for ignored in range(128):
                if not frame:
                    break
                code = self.integer(frame + self.off["interpreter_frame"]["executable"])
                if code and self.typename(code) == "code":
                    if (self.string(self.integer(code + self.off["code_object"]["name"])) == "run_forever"
                            and self.string(self.integer(code + self.off["code_object"]["filename"])) == filename):
                        obj = self.integer(frame + self.off["interpreter_frame"]["localsplus"])
                        if self.typename(obj) == "MarketFeedService":
                            found.add(obj)
                frame = self.integer(frame + self.off["interpreter_frame"]["previous"])
            else:
                raise ValueError("FRAME_BOUND_EXCEEDED")
            thread = self.integer(thread + self.off["thread_state"]["next"])
        else:
            raise ValueError("THREAD_BOUND_EXCEEDED")
        if len(found) != 1:
            raise ValueError("SERVICE_IDENTITY_UNPROVEN")
        return found.pop()


def inspect(debugger, runtime_root, layout_path, output_path, process_identity):
    """LLDB host callback; all failures yield safe unknown proof and detach."""
    import lldb
    target = debugger.GetSelectedTarget()
    process = target.GetProcess()
    result = {"status": "UNPROVEN", "target_calls": 0, "target_writes": 0,
              "stopped_at": _now(), "detached": False, "pid": process.GetProcessID()}
    try:
        if not isinstance(process_identity, str) or not re.fullmatch(r"[0-9a-f]{64}", process_identity):
            raise ValueError("PROCESS_IDENTITY_UNPROVEN")
        result["process_identity"] = process_identity
        layout = json.loads(Path(layout_path).read_text())
        reader = _Reader(process, target, layout, lldb)
        obj = reader.service(runtime_root)
        result["runtime_frame_bound"] = True
        fields = reader.attrs(obj, {"_input_failure", "_closed_retirement_failed", "_provider",
                                    "_pending", "_trading_day", "_contracts", "_cleanup_isolation"})
        failure = reader.string(fields["_input_failure"])
        result["input_failure"] = ("LIVE_PROVIDER_CLOSE_UNKNOWN"
                                   if failure == "LIVE_PROVIDER_CLOSE_UNKNOWN" else "UNCLASSIFIED")
        result["retirement_failed"] = reader.boolean(fields["_closed_retirement_failed"])
        pending = fields["_pending"]
        if reader.typename(pending) != "dict":
            raise ValueError("PENDING_TYPE_UNPROVEN")
        result["pending_count"] = reader.integer(pending + layout["dict_used"], signed=True)
        if not 0 <= result["pending_count"] <= 100000:
            raise ValueError("PENDING_COUNT_UNPROVEN")
        provider = fields["_provider"]
        if reader.typename(provider) != "RQDataLiveProvider":
            raise ValueError("PROVIDER_TYPE_UNPROVEN")
        result["provider_type"] = "RQDataLiveProvider"
        result["object_identity"] = hashlib.sha256(
            f"{process_identity}:{process.GetProcessID()}:{obj}:{provider}".encode()).hexdigest()
        attrs = reader.attrs(provider, {"_close_succeeded", "_close_failed", "_closed", "_messages",
                                        "_listener", "_retired_listener"})
        for name in ("close_succeeded", "close_failed", "closed"):
            result[name] = reader.boolean(attrs["_" + name])
        messages = attrs["_messages"]
        if reader.typename(messages) != "collections.deque":
            raise ValueError("BUFFER_TYPE_UNPROVEN")
        result["raw_buffer_count"] = reader.integer(messages + reader.off["tuple_object"]["ob_size"], signed=True)
        if not 0 <= result["raw_buffer_count"] <= 1000000:
            raise ValueError("BUFFER_COUNT_UNPROVEN")
        native_ids = {process.GetThreadAtIndex(i).GetThreadID() for i in range(process.GetNumThreads())}
        listeners = {}
        for key in ("_listener", "_retired_listener"):
            item = attrs[key]
            if reader.typename(item) == "NoneType":
                listeners[key] = {"present": False}
            else:
                if reader.typename(item) not in ("Thread", "LiveListener"):
                    raise ValueError("LISTENER_TYPE_UNPROVEN")
                native = reader.attrs(item, {"_native_id"})["_native_id"]
                nid = reader.number(native)
                if nid <= 0:
                    raise ValueError("LISTENER_ID_UNPROVEN")
                listeners[key] = {"present": True, "native_thread_alive": nid in native_ids}
        result["listeners"] = listeners
        isolation = fields["_cleanup_isolation"]
        if reader.typename(isolation) != "_CleanupIsolation":
            raise ValueError("ISOLATION_TYPE_UNPROVEN")
        isolated = reader.attrs(isolation, {"day", "local_day", "provider", "contracts"})
        result["isolation_provider_matches"] = isolated["provider"] == provider
        result["isolation_day"] = reader.day(isolated["day"])
        current_day = reader.day(fields["_trading_day"])
        result["isolation_local_day_matches"] = reader.day(isolated["local_day"]) == current_day
        frozen_contracts = [tuple(reader.string(value) for value in reader.tuple(pair, 2))
                            for pair in reader.tuple(isolated["contracts"])]
        current_contracts = [(key, reader.string(value)) for key, value in reader.dict_pairs(fields["_contracts"])]
        result["isolation_snapshot_sha256"] = _snapshot_hash(result["isolation_day"], frozen_contracts)
        result["isolation_snapshot_matches"] = (result["isolation_local_day_matches"] and
            result["isolation_snapshot_sha256"] == _snapshot_hash(current_day, current_contracts))
        result["status"] = "READ_ONLY_INSPECTED"
    except Exception as error:
        result["status"] = "UNPROVEN"
        code = str(error) if isinstance(error, ValueError) else ""
        result["error"] = code if re.fullmatch(r"[A-Z_]{1,80}", code) else "INSPECTION_UNPROVEN"
    finally:
        # Detach even on malformed memory, ABI mismatch, or serialization failure.
        try:
            result["detached"] = process.Detach().Success()
        except Exception:
            result["detached"] = False
        if not result["detached"]:
            result["status"] = "UNPROVEN"
        result["proof_at"] = _now()
        _private_write(output_path, result)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    result = {"status": "UNPROVEN", "error": "HOST_INSPECTION_UNPROVEN",
              "target_calls": 0, "target_writes": 0, "detached": False, "proof_at": _now()}
    output = None
    try:
        if (sys.version_info[:2] != (3, 13) or args.pid <= 1 or args.pid == os.getpid()
                or not args.runtime_root.is_absolute() or not args.output.is_absolute()):
            raise ValueError("HOST_ARGUMENTS_UNPROVEN")
        root = args.runtime_root.resolve(strict=True)
        if not (root / "services/quant-api/app/market_data/live_market.py").is_file():
            raise ValueError("RUNTIME_ROOT_UNPROVEN")
        parent = args.output.parent.resolve(strict=True)
        candidate = parent / args.output.name
        if candidate.exists() or candidate.is_symlink() or parent.stat().st_uid != os.getuid():
            raise ValueError("OUTPUT_UNPROVEN")
        output = candidate
        include = Path(sysconfig.get_path("include")).resolve(strict=True)
        header = (include / "internal/pycore_runtime.h").read_text()
        body = header.split("typedef struct _Py_DebugOffsets {", 1)[1].split("} _Py_DebugOffsets;", 1)[0]
        groups = [(name, re.findall(r"uint64_t\s+(\w+)\s*;", fields))
                  for unused, fields, name in re.findall(r"struct _(\w+)\s*\{(.*?)\}\s*(\w+);", body, re.S)]
        if not groups:
            raise ValueError("HEADER_UNPROVEN")
        started = subprocess.run(["/bin/ps", "-p", str(args.pid), "-o", "lstart="],
                                 capture_output=True, text=True, check=True, timeout=5).stdout.strip()
        if not started:
            raise ValueError("PROCESS_IDENTITY_UNPROVEN")
        identity = hashlib.sha256(f"{args.pid}:{started}".encode()).hexdigest()
        with tempfile.TemporaryDirectory(prefix="guiyi-feed-inspect-") as temp:
            temporary = Path(temp)
            binary = temporary / "layout"
            subprocess.run(["/usr/bin/clang", "-I", str(include), str(Path(__file__).with_name("feed_cpython_layout.c")),
                            "-o", str(binary)], capture_output=True, check=True, timeout=20)
            layout = json.loads(subprocess.run([str(binary)], capture_output=True, text=True,
                                              check=True, timeout=5).stdout)
            layout["debug_groups"] = groups
            layout_path = temporary / "layout.json"
            layout_path.write_text(json.dumps(layout))
            internal_output = temporary / "proof.json"
            command = ("script feed_runtime_diagnostic.inspect(lldb.debugger, " +
                       ", ".join(repr(str(v)) for v in (root, layout_path, internal_output, identity)) + ")")
            # Commands execute debugger-host Python only; no target expression commands.
            subprocess.run(["/usr/bin/lldb", "--no-lldbinit", "--batch",
                            "-O", "command script import " + json.dumps(str(Path(__file__).resolve()), ensure_ascii=False),
                            "-p", str(args.pid),
                            "-o", command], capture_output=True, text=True, timeout=30)
            result = json.loads(internal_output.read_text())
            after = subprocess.run(["/bin/ps", "-p", str(args.pid), "-o", "lstart="],
                                   capture_output=True, text=True, check=True, timeout=5).stdout.strip()
            if after != started:
                result["status"], result["error"] = "UNPROVEN", "PROCESS_IDENTITY_CHANGED"
    except subprocess.TimeoutExpired:
        result["status"], result["error"] = "UNPROVEN", "INSPECTION_TIMEOUT_DETACH_UNKNOWN"
    except Exception:
        result["status"], result["error"] = "UNPROVEN", "HOST_INSPECTION_UNPROVEN"
    result["proof_at"] = _now()
    if output is not None:
        try:
            _private_write(output, result)
        except Exception:
            result["status"], result["error"] = "UNPROVEN", "OUTPUT_WRITE_UNPROVEN"
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "READ_ONLY_INSPECTED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
