from __future__ import annotations

from pathlib import Path
import subprocess

from app.services.product_retirement_runtime_gate import REQUIRED_WRITER_SERVICES
from app.services.product_retirement_runtime_operator import LaunchdRuntimeOperator


def test_launchd_operator_stops_exact_services_and_reports_readonly_states(
    tmp_path: Path,
) -> None:
    calls: list[tuple[str, ...]] = []
    running_label = REQUIRED_WRITER_SERVICES[-1]
    service_states = {
        label: ("running" if label == running_label else "stopped")
        for label in REQUIRED_WRITER_SERVICES
    }

    def runner(command: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        if command[1] == "print":
            label = command[-1].rsplit("/", maxsplit=1)[-1]
            return subprocess.CompletedProcess(
                command,
                0 if service_states[label] == "running" else 1,
                stdout="",
                stderr="",
            )
        if command[1] == "bootout":
            label = command[-1].rsplit("/", maxsplit=1)[-1]
            service_states[label] = "stopped"
        if command[1] == "bootstrap":
            plist_name = Path(command[-1]).stem
            service_states[plist_name] = "running"
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    plists = {}
    for label in REQUIRED_WRITER_SERVICES:
        plist = tmp_path / f"{label}.plist"
        plist.write_text("<plist/>", encoding="utf-8")
        plists[label] = plist
    operator = LaunchdRuntimeOperator(service_plists=plists, runner=runner)

    prior_states = operator.writer_states()
    stopped = operator.stop_writer_services()
    restored = operator.restart_services(prior_states)

    assert stopped == {label: "stopped" for label in REQUIRED_WRITER_SERVICES}
    assert restored == prior_states
    assert [command[-1] for command in calls if command[1] == "bootout"] == [
        f"gui/501/{running_label}"
    ]
    assert [
        Path(command[-1]).stem for command in calls if command[1] == "bootstrap"
    ] == [running_label]
