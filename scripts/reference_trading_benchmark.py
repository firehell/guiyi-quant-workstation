#!/usr/bin/env python3
"""Repeat real isolated ReferenceTrading integration tests with bounded resources.

Each case uses a disposable PostgreSQL schema. Synthetic query rows and
fixture-only forward streams are reported separately from product evidence.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import platform
import resource
import subprocess
import sys
import tempfile
import time

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


ROOT = Path(__file__).resolve().parents[1]
CASES = {
    "historical_13_streams": (
        "services/quant-api/tests/reference_trading/test_historical_integration.py",
        "test_historical_pipeline_persists_thirteen_streams_in_postgresql",
    ),
    "forward_recovery": (
        "services/quant-api/tests/reference_trading/test_newow_worker_recovery.py",
        "test_postgresql_restart_projects_typed_capture_once",
    ),
    **{
        f"query_{count}": (
            "services/quant-api/tests/reference_trading/test_query_capacity_postgresql.py",
            f"test_postgresql_query_capacity_at_fixed_row_count[{count}]",
        )
        for count in (100, 1000, 10000)
    },
    "query_real_rebuild_10000": (
        "services/quant-api/tests/reference_trading/test_revision_rebuild.py",
        "test_postgresql_long_history_price_rebuild_keeps_past_cutoff[10000]",
    ),
    **{
        f"stream_{count}": (
            "services/quant-api/tests/reference_trading/test_forward_capacity_postgresql.py",
            f"test_postgresql_real_kernel_forward_worker_capacity[{count}]",
        )
        for count in (60, 300)
    },
    "stream_300_mds": (
        "services/quant-api/tests/reference_trading/test_forward_capacity_postgresql.py",
        "test_postgresql_300_streams_acquire_from_real_mds",
    ),
}


def validate_target(environment: dict[str, str]) -> tuple[str, str]:
    raw = environment.get("GUIYI_ISOLATED_MIGRATION_DATABASE_URL", "")
    if not raw or environment.get("DATABASE_URL"):
        raise ValueError("dedicated test URL required; DATABASE_URL must be unset")
    if any(key.startswith("PG") for key in environment):
        raise ValueError("libpq environment overrides are forbidden")
    url = make_url(raw)
    if (
        not url.drivername.startswith("postgresql")
        or url.host not in {"127.0.0.1", "localhost"}
        or bool(url.query)
        or url.port is None or url.port == 5432
        or url.database != "guiyi_reference_isolated_test"
    ):
        raise ValueError("target must be the dedicated loopback PostgreSQL test database on a nonproduction port")
    engine = create_engine(raw, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            database, version = connection.execute(text(
                "SELECT current_database(), current_setting('server_version_num')"
            )).one()
    finally:
        engine.dispose()
    if database != url.database:
        raise ValueError("connected database identity differs from requested test database")
    return str(database), str(version)


def _rss_kib(pid: int) -> int | None:
    result = subprocess.run(
        ["ps", "-o", "rss=", "-p", str(pid)],
        capture_output=True, text=True, check=False, timeout=2,
    )
    try:
        return int(result.stdout.strip())
    except ValueError:
        return None


def run_case(case: str, *, timeout_seconds: int, environment: dict[str, str]) -> dict[str, object]:
    path, test_name = CASES[case]
    command = [
        sys.executable, "-m", "pytest", "-q", "-s", "-p", "no:cacheprovider",
        "--tb=short", f"{path}::{test_name}", "-m", "isolated_postgresql",
    ]
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    start = time.monotonic()
    if case == "historical_13_streams" or case.startswith("query_"):
        environment = {**environment, "GUIYI_P8_BENCH_QUERY": "1"}
    if case.startswith("stream_"):
        environment = {**environment, "GUIYI_P8_BENCH_STREAM": "1"}
    if case == "stream_300_mds":
        environment = {**environment, "GUIYI_P8_BENCH_MDS_STREAM": "1"}
    process = subprocess.Popen(
        command, cwd=ROOT, env=environment,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    peak_rss_kib = 0
    while process.poll() is None:
        if time.monotonic() - start >= timeout_seconds:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
            raise TimeoutError(f"{case} exceeded {timeout_seconds}s budget")
        peak_rss_kib = max(peak_rss_kib, _rss_kib(process.pid) or 0)
        time.sleep(0.05)
    output = process.communicate()[0]
    query_metrics = None
    stream_metrics = None
    mds_stream_metrics = None
    for line in output.splitlines():
        if line.startswith("P8_QUERY_METRIC="):
            query_metrics = json.loads(line.removeprefix("P8_QUERY_METRIC="))
        if line.startswith("P8_STREAM_METRIC="):
            stream_metrics = json.loads(line.removeprefix("P8_STREAM_METRIC="))
        if line.startswith("P8_MDS_STREAM_METRIC="):
            mds_stream_metrics = json.loads(line.removeprefix("P8_MDS_STREAM_METRIC="))
    if process.returncode == 0 and (
        case == "historical_13_streams" or case.startswith("query_")
    ) and query_metrics is None:
        raise RuntimeError("query benchmark did not emit query metrics")
    if process.returncode == 0 and case in {"stream_60", "stream_300"} and stream_metrics is None:
        raise RuntimeError("stream benchmark did not emit worker metrics")
    if process.returncode == 0 and case == "stream_300_mds" and mds_stream_metrics is None:
        raise RuntimeError("MDS stream benchmark did not emit metrics")
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    return {
        "case_id": case,
        "exit_code": process.returncode,
        "elapsed_seconds": round(time.monotonic() - start, 3),
        "child_cpu_seconds": round(
            after.ru_utime + after.ru_stime - before.ru_utime - before.ru_stime, 3,
        ),
        "observed_peak_rss_kib": peak_rss_kib,
        "query_metrics": query_metrics,
        "stream_metrics": stream_metrics,
        "mds_stream_metrics": mds_stream_metrics,
        "test_tail": (
            output.strip().splitlines()[-30 if process.returncode else -1:]
            if output else []
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=tuple(CASES), required=True)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--timeout-seconds", type=int, default=120)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    if not 5 <= arguments.repeats <= 10 or not 1 <= arguments.timeout_seconds <= 600:
        parser.error("repeats must be 5..10 and timeout must be 1..600 seconds")
    output = (arguments.output or (
        Path(tempfile.gettempdir()) / f"guiyi-p8-{arguments.case}.json"
    )).resolve()
    if not output.is_relative_to(Path(tempfile.gettempdir()).resolve()):
        parser.error("output must be inside the system temporary directory")
    try:
        database, pg_version = validate_target(dict(os.environ))
    except Exception as error:
        parser.error(str(error))
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONPATH"] = "services/quant-api:packages/quant-core"
    git_sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
    ).strip()
    dirty = bool(subprocess.check_output(
        ["git", "-c", "core.fsmonitor=false", "status", "--porcelain=v1"],
        cwd=ROOT, text=True,
    ).strip())
    plan = {
        "case_id": arguments.case,
        "repeats": arguments.repeats,
        "timeout_seconds_per_repeat": arguments.timeout_seconds,
        "database": database,
        "postgresql_server_version": pg_version,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "code_sha": git_sha,
        "dirty_worktree": dirty,
        "started_at": datetime.now(UTC).isoformat(),
        "results": [],
    }
    print(json.dumps({key: value for key, value in plan.items() if key != "results"}, sort_keys=True))
    for index in range(arguments.repeats):
        try:
            result = run_case(
                arguments.case, timeout_seconds=arguments.timeout_seconds,
                environment=environment,
            )
        except (TimeoutError, RuntimeError) as error:
            result = {"case_id": arguments.case, "exit_code": 1,
                      "failure": str(error)}
        result["repeat"] = index + 1
        plan["results"].append(result)
        print(json.dumps(result, sort_keys=True), flush=True)
        if result["exit_code"] != 0:
            break
    output.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n")
    return 0 if len(plan["results"]) == arguments.repeats and all(
        result["exit_code"] == 0 for result in plan["results"]
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
