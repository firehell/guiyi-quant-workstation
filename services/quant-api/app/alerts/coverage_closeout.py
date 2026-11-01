"""Close only calendar-proven not-due diagnostics; never evaluate or deliver signals."""

from datetime import datetime, date, timedelta
from hashlib import sha256
import json
import re
from zoneinfo import ZoneInfo

from app.alerts.registry import SUBING_THS_ALERT_RULE_CODE
from app.market_data.domain import SeriesPageQuery
from app.market_data.market_read_service import (
    MarketReadWindowNotDue,
    MarketReadWindowError,
)
from app.market_data.market_data_service import MarketDataError
from app.market_data.errors import InfrastructureError

POLICY = "alert_week_not_due_closeout_v1"


def digest(value):
    return sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def validate_resolution(item):
    try:
        if set(item) != {
            "policy",
            "route",
            "original",
            "reason",
            "checked_at",
            "runtime_identity",
            "input_evidence",
            "input_evidence_sha256",
        }:
            raise ValueError
        rule, symbol, frequency = item["route"].split(":")
        original, proof, identity = (
            item["original"],
            item["input_evidence"],
            item["runtime_identity"],
        )
        day = date.fromisoformat(original["trading_day"])
        checked = datetime.fromisoformat(item["checked_at"])
        monday = day - timedelta(days=day.weekday())
        calendar = proof["calendar"]
        if (
            rule != SUBING_THS_ALERT_RULE_CODE
            or frequency != "1w"
            or item["policy"] != POLICY
            or item["reason"] != "MARKET_READ_WEEK_NOT_COMPLETED"
            or item["input_evidence_sha256"] != digest(proof)
            or proof["symbol"] != symbol
            or proof["trading_day"] != day.isoformat()
            or not re.fullmatch(
                re.escape(symbol.upper()) + r"[0-9]{4}", proof["owner_contract"]
            )
            or checked.tzinfo is None
            or day >= checked.astimezone(ZoneInfo("Asia/Shanghai")).date()
            or original.get("state") != "evaluation_failed"
            or original.get("error_type") != "evaluation_failed"
            or set(original)
            != {
                "state",
                "contract",
                "trading_day",
                "last_evaluated_bar_at",
                "last_success_at",
                "error_type",
                "input_error_code",
                "previous_unresolved",
                "last_warming_bar_at",
                "warming_observation_id",
                "warming_runtime_generation",
                "warming_attempts",
            }
            or original.get("warming_attempts") != []
            or any(
                original.get(k) is not None
                for k in (
                    "contract",
                    "last_evaluated_bar_at",
                    "last_success_at",
                    "input_error_code",
                    "previous_unresolved",
                    "last_warming_bar_at",
                    "warming_observation_id",
                    "warming_runtime_generation",
                )
            )
            or type(identity.get("runtime_generation")) is not int
            or identity["runtime_generation"] <= 0
            or not re.fullmatch(r"[a-f0-9]{40}", identity.get("runtime_commit", ""))
            or not identity.get("runtime_root", "").startswith("/")
            or len(calendar) != 7
            or any(
                row[0] != (monday + timedelta(days=i)).isoformat()
                or type(row[1]) is not bool
                for i, row in enumerate(calendar)
            )
            or not any(row == [day.isoformat(), True] for row in calendar)
            or not any(row[1] and row[0] > day.isoformat() for row in calendar)
        ):
            raise ValueError
        sessions = [
            (datetime.fromisoformat(a), datetime.fromisoformat(b))
            for a, b in proof["sessions"]
        ]
        cutoff = datetime.fromisoformat(proof["cutoff"])
        if (
            not sessions
            or cutoff.tzinfo is None
            or cutoff > checked
            or cutoff.astimezone(ZoneInfo("Asia/Shanghai")).date() != day
            or any(a.tzinfo is None or b.tzinfo is None or a >= b for a, b in sessions)
            or max(b for a, b in sessions) != cutoff
        ):
            raise ValueError
    except (KeyError, TypeError, ValueError, AttributeError, IndexError):
        raise RuntimeError("ALERT_COVERAGE_CLOSEOUT_INVALID") from None


def propose_closeout(records, reader, *, now: datetime, identity: dict):
    """Build evidence without changing projections, Events, journals or notifications."""
    if (
        now.tzinfo is None
        or type(identity.get("runtime_generation")) is not int
        or identity["runtime_generation"] <= 0
    ):
        raise RuntimeError("ALERT_COVERAGE_CLOSEOUT_INVALID")
    resolutions = {}
    for route, original in records.items():
        rule, symbol, frequency = route.split(":")
        if (
            rule != SUBING_THS_ALERT_RULE_CODE
            or frequency != "1w"
            or original.get("state") != "evaluation_failed"
            or original.get("error_type") != "evaluation_failed"
            or any(
                original.get(key) is not None
                for key in (
                    "contract",
                    "last_evaluated_bar_at",
                    "last_success_at",
                    "input_error_code",
                    "previous_unresolved",
                )
            )
        ):
            continue
        day = date.fromisoformat(original["trading_day"])
        if day >= now.astimezone(ZoneInfo("Asia/Shanghai")).date():
            continue
        try:
            reader.latest_subing_quality_window(
                SeriesPageQuery("actual_dominant", symbol, "1w"),
                trading_day=day,
            )
        except MarketReadWindowNotDue as exc:
            if (
                not isinstance(exc.evidence, dict)
                or exc.evidence.get("symbol") != symbol
                or exc.evidence.get("trading_day") != day.isoformat()
            ):
                continue
            resolutions[route] = {
                "policy": POLICY,
                "route": route,
                "original": dict(original),
                "reason": "MARKET_READ_WEEK_NOT_COMPLETED",
                "checked_at": now.isoformat(),
                "runtime_identity": dict(identity),
                "input_evidence": exc.evidence,
                "input_evidence_sha256": digest(exc.evidence),
            }
        except (MarketReadWindowError, MarketDataError, InfrastructureError):
            # Unknown/missing/conflicting input is not proof that the old error was false.
            continue
    return resolutions


def merge_closeout(expected, resolutions, archive, *, replacements=None):
    """Validate and preserve the first immutable proof for each exact original record."""
    if (
        not isinstance(archive, dict)
        or set(archive) != {"schema_version", "resolutions"}
        or archive["schema_version"] != 1
        or not isinstance(archive["resolutions"], dict)
    ):
        raise RuntimeError("ALERT_COVERAGE_CLOSEOUT_INVALID")
    saved = dict(archive["resolutions"])
    for identifier, item in saved.items():
        validate_resolution(item)
        if not isinstance(item, dict) or identifier != digest(
            {"route": item.get("route"), "original": item.get("original")}
        ):
            raise RuntimeError("ALERT_COVERAGE_CLOSEOUT_INVALID")
    remaining = dict(expected)
    for route, item in resolutions.items():
        validate_resolution(item)
        if (
            route not in expected
            or item.get("route") != route
            or item.get("original") != expected[route]
            or item.get("policy") != POLICY
            or item.get("reason") != "MARKET_READ_WEEK_NOT_COMPLETED"
        ):
            raise RuntimeError("ALERT_COVERAGE_CLOSEOUT_STALE")
        identifier = digest({"route": route, "original": item["original"]})
        saved.setdefault(identifier, item)
        remaining.pop(route)
    for route, replacement in (replacements or {}).items():
        if (
            route not in resolutions
            or replacement == expected[route]
            or replacement.get("state") != "evaluation_failed"
            or replacement.get("error_type")
            not in {"evaluation_failed", "evaluation_input_invalid"}
            or replacement["trading_day"] < expected[route]["trading_day"]
        ):
            raise RuntimeError("ALERT_COVERAGE_CLOSEOUT_INVALID")
        remaining[route] = dict(replacement)
    return remaining, {"schema_version": 1, "resolutions": saved}
