"""Strict file-based CLI boundary for P4 historical reference replay."""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from datetime import date, datetime
from enum import Enum
import json
from pathlib import Path

from app.reference_trading.planning import (
    plan_from_dict,
    plan_to_dict,
    request_from_dict,
)
from app.reference_trading.service import ResumeToken


_MAX_JSON_BYTES = 1_048_576


def _pairs(values):
    result = {}
    for key, value in values:
        if key in result:
            raise ValueError("REFERENCE_JSON_INVALID")
        result[key] = value
    return result


def strict_json_loads(value: str):
    if not isinstance(value, str) or len(value.encode()) > _MAX_JSON_BYTES:
        raise ValueError("REFERENCE_JSON_INVALID")
    try:
        return json.loads(
            value,
            object_pairs_hook=_pairs,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                ValueError("REFERENCE_JSON_INVALID")
            ),
        )
    except (json.JSONDecodeError, UnicodeError, ValueError) as error:
        raise ValueError("REFERENCE_JSON_INVALID") from error


def _read_json(path_value: str):
    path = Path(path_value)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > _MAX_JSON_BYTES:
        raise ValueError("REFERENCE_PATH_INVALID")
    return strict_json_loads(path.read_text(encoding="utf-8"))


def _jsonable(value):
    if value is None or type(value) in (bool, int, float, str):
        return value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: _jsonable(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    raise TypeError("REFERENCE_OUTPUT_INVALID")


def _resume_token(value: object) -> ResumeToken:
    if not isinstance(value, dict) or set(value) != {
        "plan_hash", "stream_id", "revision_id", "next_input_index",
        "source_token", "last_batch_key",
    }:
        raise ValueError("REFERENCE_RESUME_TOKEN_INVALID")
    return ResumeToken(**value)


def run_reference_command(args, *, planner=None, service=None) -> dict[str, object]:
    if args.reference_command == "plan":
        request = request_from_dict(_read_json(args.request))
        if planner is None:
            from app.reference_trading.composition import open_historical_reference_components

            with open_historical_reference_components() as (active_planner, _service):
                plan = active_planner.plan(request)
        else:
            plan = planner.plan(request)
        output = Path(args.output)
        if output.is_symlink() or output.exists() or not output.parent.is_dir():
            raise ValueError("REFERENCE_OUTPUT_EXISTS")
        output.write_text(
            json.dumps(plan_to_dict(plan), sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        return {
            "schema_version": 1,
            "command": "reference.plan",
            "status": "planned",
            "readonly": True,
            "plan_hash": plan.plan_hash,
            "stream_count": len(plan.streams),
            "output": str(output),
        }

    plan = plan_from_dict(_read_json(args.plan))
    if plan.operation != args.reference_command and not (
        args.reference_command == "resume" and plan.operation in {"build", "rebuild"}
    ):
        raise ValueError("REFERENCE_OPERATION_CONFLICT")
    if plan.plan_hash != args.expected_plan_hash:
        raise ValueError("REFERENCE_PLAN_HASH_CONFLICT")
    if not args.apply:
        return {
            "schema_version": 1,
            "command": f"reference.{args.reference_command}",
            "status": "planned",
            "readonly": True,
            "plan_hash": plan.plan_hash,
            "stream_count": len(plan.streams),
        }

    if service is None:
        from app.reference_trading.composition import open_historical_reference_components

        with open_historical_reference_components() as (_planner, active_service):
            return _run_apply(args, plan, active_service)
    return _run_apply(args, plan, service)


def _run_apply(args, plan, service) -> dict[str, object]:
    if args.reference_command == "resume":
        result = service.resume(
            plan,
            _resume_token(_read_json(args.resume_token)),
            args.expected_plan_hash,
        )
    elif args.reference_command == "build":
        result = service.execute(plan, args.expected_plan_hash)
    else:
        result = getattr(service, args.reference_command)(plan, args.expected_plan_hash)
    payload = _jsonable(result)
    return {
        "schema_version": 1,
        "command": f"reference.{args.reference_command}",
        "status": result.status,
        "readonly": False,
        "report": payload,
    }
