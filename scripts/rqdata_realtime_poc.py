from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
from datetime import date
import importlib
import json
import os
from pathlib import Path
import sys
from typing import Any

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = PROJECT_ROOT / "services" / "quant-api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

SENSITIVE_ENV_NAMES = (
    "RQDATAC2_CONF",
    "RQDATAC_CONF",
    "RQDATA_LICENSE_KEY",
    "RQDATA_USERNAME",
    "RQDATA_PASSWORD",
    "RQDATA_ADDR",
)

PRODUCT = "JM"
CONTRACT = "JM2609"
START_DATE = date(2026, 1, 5)
END_DATE = date(2026, 1, 6)


def credential_presence(environ: Mapping[str, str] | None = None) -> dict[str, str]:
    source = environ if environ is not None else os.environ
    return {name: "present" if source.get(name) else "missing" for name in SENSITIVE_ENV_NAMES}


def redact_message(message: Any, environ: Mapping[str, str] | None = None) -> str:
    text = "" if message is None else str(message)
    source = environ if environ is not None else os.environ
    for name in SENSITIVE_ENV_NAMES:
        value = source.get(name)
        if value:
            text = text.replace(value, "[REDACTED]")
    return text


def result(
    *,
    capability: str,
    status: str,
    api_name: str | None = None,
    wrapper_name: str | None = None,
    error_type: str | None = None,
    redacted_message: str | None = None,
    sample_columns: list[str] | None = None,
    sample_row_count: int = 0,
    notes: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "capability": capability,
        "status": status,
        "api_name": api_name,
        "wrapper_name": wrapper_name,
        "error_type": error_type,
        "redacted_message": redacted_message,
        "sample_columns": sample_columns or [],
        "sample_row_count": sample_row_count,
        "notes": notes or [],
    }


def frame_summary(value: Any) -> tuple[list[str], int]:
    if isinstance(value, pd.DataFrame):
        return [str(column) for column in value.columns], min(len(value), 5)
    if isinstance(value, pd.Series):
        return [str(value.name or "value")], min(len(value), 5)
    if isinstance(value, list | tuple):
        if value and isinstance(value[0], dict):
            keys: set[str] = set()
            for item in value[:5]:
                keys.update(str(key) for key in item)
            return sorted(keys), min(len(value), 5)
        return ["value"], min(len(value), 5)
    if isinstance(value, dict):
        return sorted(str(key) for key in value), 1
    if value is None:
        return [], 0
    return ["value"], 1


def checked(
    *,
    capability: str,
    api_name: str,
    wrapper_name: str,
    call: Callable[[], Any],
    environ: Mapping[str, str] | None = None,
    notes: list[str] | None = None,
) -> dict[str, Any]:
    try:
        value = call()
    except Exception as exc:  # noqa: BLE001 - PoC must keep collecting capability results.
        return result(
            capability=capability,
            status="fail",
            api_name=api_name,
            wrapper_name=wrapper_name,
            error_type=type(exc).__name__,
            redacted_message=redact_message(exc, environ),
            notes=notes,
        )
    columns, row_count = frame_summary(value)
    return result(
        capability=capability,
        status="pass",
        api_name=api_name,
        wrapper_name=wrapper_name,
        sample_columns=columns,
        sample_row_count=row_count,
        notes=notes,
    )


def dry_run_results() -> list[dict[str, Any]]:
    capabilities = [
        "rqdatac_import",
        "rqdata_auth_init",
        "jm_contract_catalog",
        "dce_jm_contract_list",
        "historical_1d_sample",
        "historical_1m_sample",
        "frequency_5m_direct",
        "frequency_15m_direct",
        "frequency_30m_direct",
        "frequency_1h_direct",
        "trading_calendar",
        "trading_sessions",
        "dominant_mapping",
        "continuous_contracts",
        "ex_factor",
        "contract_multiplier",
        "margin",
        "commission",
        "realtime_snapshot_or_bar",
        "invalid_symbol_error",
        "unsupported_frequency_error",
    ]
    return [
        result(
            capability=capability,
            status="skipped",
            notes=["dry-run only; no RQData client constructed and no RQData API called"],
        )
        for capability in capabilities
    ]


def _import_result(environ: Mapping[str, str] | None = None) -> tuple[dict[str, Any], Any | None]:
    try:
        rqdatac = importlib.import_module("rqdatac")
    except Exception as exc:  # noqa: BLE001
        return (
            result(
                capability="rqdatac_import",
                status="fail",
                api_name="import rqdatac",
                error_type=type(exc).__name__,
                redacted_message=redact_message(exc, environ),
            ),
            None,
        )
    version = getattr(rqdatac, "__version__", None)
    return (
        result(
            capability="rqdatac_import",
            status="pass",
            api_name="import rqdatac",
            sample_columns=["__version__"] if version else [],
            sample_row_count=1 if version else 0,
            notes=[f"version={version}" if version else "version unavailable"],
        ),
        rqdatac,
    )


def _client_factory():
    from app.services.rqdata_ingest.client import RqDataClient

    return RqDataClient(load_env_file=True)


def readonly_results(
    *,
    client_factory: Callable[[], Any] | None = None,
    environ: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    package_result, _rqdatac = _import_result(environ)
    results.append(package_result)
    if package_result["status"] != "pass":
        results.extend(
            result(capability=item["capability"], status="skipped", notes=["rqdatac import failed; readonly checks skipped"])
            for item in dry_run_results()[1:]
        )
        return results

    factory = client_factory or _client_factory
    try:
        client = factory()
    except Exception as exc:  # noqa: BLE001
        results.append(
            result(
                capability="rqdata_auth_init",
                status="fail",
                wrapper_name="RqDataClient",
                error_type=type(exc).__name__,
                redacted_message=redact_message(exc, environ),
            )
        )
        results.extend(
            result(capability=item["capability"], status="skipped", notes=["RQData client init failed; readonly checks skipped"])
            for item in dry_run_results()[2:]
        )
        return results

    results.append(result(capability="rqdata_auth_init", status="pass", wrapper_name="RqDataClient"))
    results.extend(
        [
            checked(
                capability="jm_contract_catalog",
                api_name="all_instruments(type='Future')",
                wrapper_name="RqDataClient.all_future_instruments",
                call=lambda: client.all_future_instruments(),
                environ=environ,
                notes=["inspect returned fields for JM/DCE support; script does not persist rows"],
            ),
            checked(
                capability="dce_jm_contract_list",
                api_name="futures.get_contracts",
                wrapper_name="RqDataClient.listed_contracts",
                call=lambda: client.listed_contracts(PRODUCT, START_DATE),
                environ=environ,
            ),
            checked(
                capability="historical_1d_sample",
                api_name="futures.get_exchange_daily or get_price(frequency='1d')",
                wrapper_name="RqDataClient.exchange_daily",
                call=lambda: client.exchange_daily(CONTRACT, START_DATE, END_DATE),
                environ=environ,
            ),
            checked(
                capability="historical_1m_sample",
                api_name="get_price(frequency='1m')",
                wrapper_name="RqDataClient.contract_bars",
                call=lambda: client.contract_bars(CONTRACT, START_DATE, END_DATE, "1m"),
                environ=environ,
            ),
        ]
    )
    for frequency in ("5m", "15m", "30m", "60m"):
        results.append(
            checked(
                capability=f"frequency_{frequency.replace('60m', '1h')}_direct",
                api_name=f"get_price(frequency='{frequency}')",
                wrapper_name="RqDataClient.contract_bars",
                call=lambda frequency=frequency: client.contract_bars(CONTRACT, START_DATE, END_DATE, frequency),
                environ=environ,
                notes=["pass means direct API shape is available; row quality is not certified by this PoC"],
            )
        )
    results.extend(
        [
            checked(
                capability="trading_calendar",
                api_name="get_trading_dates",
                wrapper_name="RqDataClient.trading_dates",
                call=lambda: client.trading_dates(START_DATE, END_DATE),
                environ=environ,
            ),
            checked(
                capability="trading_sessions",
                api_name="get_trading_hours/get_trading_periods",
                wrapper_name="RqDataClient.trading_periods",
                call=lambda: client.trading_periods([PRODUCT]),
                environ=environ,
            ),
            checked(
                capability="dominant_mapping",
                api_name="futures.get_dominant",
                wrapper_name="RqDataClient.dominant_contracts",
                call=lambda: client.dominant_contracts(PRODUCT, START_DATE, END_DATE, rank=1),
                environ=environ,
            ),
            checked(
                capability="continuous_contracts",
                api_name="futures.get_continuous_contracts",
                wrapper_name="RqDataClient.continuous_contracts",
                call=lambda: client.continuous_contracts(PRODUCT, START_DATE, END_DATE),
                environ=environ,
            ),
            checked(
                capability="ex_factor",
                api_name="futures.get_ex_factor",
                wrapper_name="RqDataClient.ex_factor",
                call=lambda: client.ex_factor(PRODUCT, START_DATE, END_DATE),
                environ=environ,
            ),
            checked(
                capability="contract_multiplier",
                api_name="futures.get_contract_multiplier/all_instruments",
                wrapper_name="RqDataClient.contract_multiplier",
                call=lambda: client.contract_multiplier(CONTRACT),
                environ=environ,
            ),
            checked(
                capability="margin",
                api_name="futures.get_trading_parameters",
                wrapper_name="RqDataClient.trading_parameters",
                call=lambda: client.trading_parameters(CONTRACT, START_DATE, END_DATE),
                environ=environ,
                notes=["check long_margin_ratio/short_margin_ratio columns"],
            ),
            checked(
                capability="commission",
                api_name="futures.get_trading_parameters",
                wrapper_name="RqDataClient.trading_parameters",
                call=lambda: client.trading_parameters(CONTRACT, START_DATE, END_DATE),
                environ=environ,
                notes=["check open_commission/close_commission columns"],
            ),
            result(
                capability="realtime_snapshot_or_bar",
                status="skipped",
                notes=["no existing safe realtime wrapper found; validate manually in a later dedicated task if needed"],
            ),
            checked(
                capability="invalid_symbol_error",
                api_name="get_price(frequency='1m')",
                wrapper_name="RqDataClient.contract_bars",
                call=lambda: client.contract_bars("INVALID9999", START_DATE, END_DATE, "1m"),
                environ=environ,
                notes=["pass means API returned a structured empty/non-empty response; fail records redacted exception type"],
            ),
            result(
                capability="unsupported_frequency_error",
                status="skipped",
                notes=["skipped to avoid unsafe probing beyond documented tiny readonly checks"],
            ),
        ]
    )
    return results


def payload_for(
    *,
    mode: str,
    results: list[dict[str, Any]],
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "mode": mode,
        "safety": {
            "writes_data": False,
            "writes_database": False,
            "writes_parquet": False,
            "prints_secret_values": False,
        },
        "credential_sources": credential_presence(environ),
        "sample_policy": {
            "product": PRODUCT,
            "contract": CONTRACT,
            "start_date": START_DATE.isoformat(),
            "end_date": END_DATE.isoformat(),
            "max_rows_reported_per_check": 5,
        },
        "results": results,
    }


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# RQData Readonly PoC Result",
        "",
        f"- mode: `{payload['mode']}`",
        f"- writes_data: `{payload['safety']['writes_data']}`",
        f"- writes_database: `{payload['safety']['writes_database']}`",
        f"- writes_parquet: `{payload['safety']['writes_parquet']}`",
        "",
        "## Credential Sources",
        "",
    ]
    for name, state in payload["credential_sources"].items():
        lines.append(f"- `{name}`: `{state}`")
    lines.extend(
        [
            "",
            "## Capability Matrix",
            "",
            "| capability | status | api_name | wrapper_name | error_type | sample_row_count | sample_columns | notes |",
            "|---|---|---|---|---|---:|---|---|",
        ]
    )
    for item in payload["results"]:
        lines.append(
            "| {capability} | {status} | {api_name} | {wrapper_name} | {error_type} | {sample_row_count} | {sample_columns} | {notes} |".format(
                capability=item["capability"],
                status=item["status"],
                api_name=item.get("api_name") or "",
                wrapper_name=item.get("wrapper_name") or "",
                error_type=item.get("error_type") or "",
                sample_row_count=item.get("sample_row_count", 0),
                sample_columns=", ".join(item.get("sample_columns") or []),
                notes="; ".join(item.get("notes") or []),
            )
        )
    return "\n".join(lines) + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="RQData readonly PoC. Defaults to dry-run and writes nothing.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Do not import or call RQData; print skipped capability matrix.")
    mode.add_argument("--run-readonly", action="store_true", help="Run tiny readonly RQData checks; requires explicit user authorization.")
    parser.add_argument("--format", choices=["json", "markdown"], default="json")
    return parser.parse_args(argv)


def main(
    argv: list[str] | None = None,
    *,
    client_factory: Callable[[], Any] | None = None,
    environ: Mapping[str, str] | None = None,
) -> int:
    args = parse_args(argv)
    source_env = environ if environ is not None else os.environ
    readonly = bool(args.run_readonly)
    results = readonly_results(client_factory=client_factory, environ=source_env) if readonly else dry_run_results()
    payload = payload_for(mode="readonly" if readonly else "dry-run", results=results, environ=source_env)
    rendered = render_markdown(payload) if args.format == "markdown" else json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
