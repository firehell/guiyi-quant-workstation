"""Read-only proof for the one Reference legacy-to-durable receiving boundary."""
from __future__ import annotations

import ast
from datetime import date
from hashlib import sha256
import json
from pathlib import Path
import re

from app.reference_trading.inbox import _digest, _envelope, DAILY_LIMIT, UNFINISHED_BYTES_LIMIT

KIND = "reference_backlog_handover_v1"
PATH = "services/quant-api/app/reference_trading/receiving_handover.py"
MAX_DAYS = 32


class ReceivingHandoverError(ValueError):
    pass


def require(value):
    if not value:
        raise ReceivingHandoverError("COHORT_REFERENCE_BACKLOG_UNPROVEN")


def _id(value):
    require(isinstance(value, str) and re.fullmatch(r"(0|[1-9][0-9]*)-(0|[1-9][0-9]*)", value))
    result = tuple(map(int, value.split("-")))
    require(all(part <= 2**64 - 1 for part in result))
    return result


def target_supports_receiving_handover(root):
    from app.runtime_bindings import _tracked, _git
    if PATH not in _tracked(Path(root)):
        return False
    try:
        source = _git(Path(root), "show", "HEAD:" + PATH)
        require(len(source) <= 262144)
        values = [ast.literal_eval(node.value) for node in ast.parse(source).body
                  if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "KIND" for target in node.targets)]
        return values == [KIND]
    except (ValueError, TypeError, SyntaxError):
        return False


def _protocol(protocol):
    value = protocol.read()
    if value is None:
        return None
    require(type(value.get("schema_version")) is int and value["schema_version"] == 1
            and type(value.get("protocol_version")) is int and value["protocol_version"] == 2
            and value.get("status") in {"requested", "active"} and value.get("intake_error") is None
            and value.get("binding") == protocol.binding and re.fullmatch(r"[0-9a-f]{64}", protocol.binding))
    return value


def _progress(journal):
    require(journal.kind == "completed")
    days = journal.days()
    require(0 < len(days) <= MAX_DAYS and len(set(days)) == len(days))
    registered = journal.registered_day("reference").isoformat()
    result = {day.isoformat(): {"cursor": journal.cursor("reference", day), "tail": journal.tail(day)} for day in days}
    require(registered in result)
    for value in result.values():
        require(_id(value["cursor"]) <= _id(value["tail"]))
    return registered, result


def valid_receiving_handover_intent(value, *, target):
    try:
        require(set(value) == {"schema_version", "kind", "target_sha256", "protocol_sha256", "authority_sha256",
                              "binding", "status", "registered_day", "baseline", "intent_sha256"})
        require(type(value["schema_version"]) is int and value["schema_version"] == 1 and value["kind"] == KIND
                and value["target_sha256"] == _digest(target) and value["status"] in {"requested", "active"})
        require(all(isinstance(value[key], str) and re.fullmatch(r"[0-9a-f]{64}", value[key])
                    for key in ("target_sha256", "protocol_sha256", "authority_sha256", "binding", "intent_sha256")))
        require(value["registered_day"] in value["baseline"] and 0 < len(value["baseline"]) <= MAX_DAYS)
        for day, boundary in value["baseline"].items():
            require(date.fromisoformat(day).isoformat() == day and set(boundary) == {"cursor", "tail"}
                    and _id(boundary["cursor"]) <= _id(boundary["tail"]))
        require(value["intent_sha256"] == _digest({key: item for key, item in value.items() if key != "intent_sha256"}))
        return True
    except (KeyError, TypeError, ValueError):
        return False


def freeze_receiving_intent(protocol, journal, *, target, schema_proof):
    try:
        value = _protocol(protocol)
        if value is None:
            return None
        registered, progress = _progress(journal)
        result = {"schema_version": 1, "kind": KIND, "target_sha256": _digest(target),
                  "protocol_sha256": _digest(value), "authority_sha256": _digest(schema_proof),
                  "binding": protocol.binding, "status": value["status"], "registered_day": registered,
                  "baseline": progress}
        result["intent_sha256"] = _digest(result)
        require(valid_receiving_handover_intent(result, target=target))
        return result
    except Exception:
        raise ReceivingHandoverError("COHORT_REFERENCE_BACKLOG_UNPROVEN") from None


def verify_receiving_intent(protocol, journal, intent, *, target, schema_proof):
    require(valid_receiving_handover_intent(intent, target=target))
    current = freeze_receiving_intent(protocol, journal, target=target, schema_proof=schema_proof)
    require(current is not None and all(current[key] == intent[key] for key in intent if key not in {"baseline", "intent_sha256"}))
    require(set(current["baseline"]) == set(intent["baseline"]))
    for day, boundary in current["baseline"].items():
        old = intent["baseline"][day]
        require(_id(boundary["cursor"]) >= _id(old["cursor"]) and _id(boundary["tail"]) >= _id(old["tail"]))
    return current["baseline"]


def _text(value):
    return value.decode() if isinstance(value, bytes) else value


def seal_receiving_backlog(protocol, journal, intent, *, target, schema_proof, progress, capacity, check_budget=lambda: None):
    try:
        check_budget()
        current = verify_receiving_intent(protocol, journal, intent, target=target, schema_proof=schema_proof)
        require(current == progress and set(capacity) == {"unfinished_bytes", "day_inputs"}
                and type(capacity["unfinished_bytes"]) is int and 0 <= capacity["unfinished_bytes"] <= UNFINISHED_BYTES_LIMIT)
        metrics, total, total_bytes = {}, 0, 0
        for day_text, boundary in sorted(progress.items()):
            day = date.fromisoformat(day_text)
            cursor, tail = boundary["cursor"], boundary["tail"]
            frontier, count, size = cursor, 0, 0
            stream_hash = sha256()
            seen = {}
            while _id(frontier) < _id(tail):
                check_budget()
                rows = journal.read("reference", day, count=512, after=frontier, through=tail)
                require(bool(rows))
                for event in rows:
                    require(_id(frontier) < _id(event.stream_id) <= _id(tail))
                    _product, _frequency, _end, canonical, digest, payload_bytes, _order = _envelope(event)
                    require(event.trading_day == day and event.observation_id not in seen)
                    seen[event.observation_id] = (event.stream_id, sha256(canonical.encode()).hexdigest())
                    stream_hash.update(json.dumps([event.stream_id, event.observation_id, digest, payload_bytes],
                                                  separators=(",", ":")).encode() + b"\n")
                    count += 1
                    size += payload_bytes
                    require(count <= DAILY_LIMIT and total_bytes + size + capacity["unfinished_bytes"] <= UNFINISHED_BYTES_LIMIT)
                    frontier = event.stream_id
                check_budget()
            require(frontier == tail)
            existing = capacity["day_inputs"].get(day_text, 0)
            require(type(existing) is int and 0 <= existing <= DAILY_LIMIT and existing + count <= DAILY_LIMIT)
            check_budget()
            require(journal.redis.hlen(journal.identity_key(day)) <= DAILY_LIMIT)
            verified = set()
            for raw_key, raw_value in journal.redis.hscan_iter(journal.identity_key(day), count=512):
                check_budget()
                key = _text(raw_key)
                identity = json.loads(_text(raw_value))
                identifier = identity["id"]
                if _id(cursor) < _id(identifier) <= _id(tail):
                    require(key in seen and seen[key][0] == identifier)
                    content = identity.get("content", identity.get("payload"))
                    require(isinstance(content, str) and sha256(content.encode()).hexdigest() == seen[key][1])
                    if "payload" in identity:
                        require(isinstance(identity["payload"], str) and sha256(identity["payload"].encode()).hexdigest() == seen[key][1])
                    verified.add(key)
            require(verified == set(seen))
            metrics[day_text] = {"count": count, "bytes": size, "sha256": stream_hash.hexdigest()}
            total += count
            total_bytes += size
            check_budget()
        require(verify_receiving_intent(protocol, journal, intent, target=target, schema_proof=schema_proof) == progress)
        check_budget()
        return {"schema_version": 1, "kind": KIND, "intent_sha256": intent["intent_sha256"],
                "progress": progress, "count": total, "bytes": total_bytes, "days": metrics,
                "capacity_sha256": _digest(capacity), "content_sha256": _digest(metrics)}
    except Exception:
        raise ReceivingHandoverError("COHORT_REFERENCE_BACKLOG_UNPROVEN") from None


def verify_receiving_backlog(protocol, journal, intent, proof, **kwargs):
    require(seal_receiving_backlog(protocol, journal, intent, progress=proof["progress"], **kwargs) == proof)
