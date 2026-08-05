from __future__ import annotations

from pathlib import Path
import subprocess

from app.services.product_retirement_runtime_gate import REQUIRED_WRITER_SERVICES
from app.services.product_retirement_runtime_operator import LaunchdRuntimeOperator


def test_launchd_operator_stops_exact_services_and_reports_readonly_states(
    tmp_path: Path,
) -> None:
    calls: list[tuple[str, ...]] = []

    def runner(command: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        if command[1] == "print":
            return subprocess.CompletedProcess(command, 1, stdout="", stderr="")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    plists = {}
    for label in REQUIRED_WRITER_SERVICES:
        plist = tmp_path / f"{label}.plist"
        plist.write_text("<plist/>", encoding="utf-8")
        plists[label] = plist
    operator = LaunchdRuntimeOperator(service_plists=plists, runner=runner)

    states = operator.stop_writer_services()

    assert states == {label: "stopped" for label in REQUIRED_WRITER_SERVICES}
    assert [command[1] for command in calls].count("bootout") == len(
        REQUIRED_WRITER_SERVICES
    )
    assert [command[1] for command in calls].count("print") == len(
        REQUIRED_WRITER_SERVICES
    )
