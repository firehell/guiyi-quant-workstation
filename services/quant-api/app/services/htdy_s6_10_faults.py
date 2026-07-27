"""Approval-C-only fault executor with bounded automatic recovery."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
import ipaddress
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from typing import Any, Mapping, Protocol

from app.services.htdy_s6_10_stability import (
    HtDyS610Error,
    canonical_hash,
    publish_json_create_only,
)


DEPENDENCY_FAULTS = {"redis", "postgres"}
KICKSTART_FAULTS = {
    "live_scheduler",
    "api",
    "web",
    "eod_scheduler",
}
ALL_FAULTS = {
    *DEPENDENCY_FAULTS,
    *KICKSTART_FAULTS,
    "rqdata",
    "mac_reboot",
}


class FaultPlatformAdapter(Protocol):
    def boot_uuid(self) -> str: ...

    def start_watchdog(
        self,
        *,
        fault: str,
        duration_seconds: int,
        target_ip: str | None,
        evidence_root: Path,
        parent_packet_hash: str,
    ) -> Mapping[str, Any]: ...

    def stop(self, fault: str) -> None: ...

    def start(self, fault: str) -> None: ...

    def kickstart(self, fault: str) -> None: ...

    def block_ip(self, target_ip: str) -> None: ...

    def unblock_ip(self, target_ip: str) -> None: ...

    def healthy(self, fault: str) -> bool: ...

    def reboot(self) -> None: ...

    def safety_facts(self) -> Mapping[str, Any]: ...


class HtDyS610FaultExecutor:
    """Execute one frozen fault and publish evidence only after recovery."""

    def __init__(
        self,
        *,
        adapter: FaultPlatformAdapter,
        sleeper: Callable[[float], None],
        evidence_root: Path,
        parent_packet_hash: str,
    ) -> None:
        self.adapter = adapter
        self.sleeper = sleeper
        self.evidence_root = evidence_root.resolve(strict=False)
        self.parent_packet_hash = parent_packet_hash

    def execute(
        self,
        *,
        fault: str,
        duration_seconds: int,
        target_ip: str | None,
    ) -> dict[str, Any]:
        if fault not in ALL_FAULTS:
            raise HtDyS610Error("fault_not_supported")
        if not 1 <= duration_seconds <= 60:
            raise HtDyS610Error("fault_duration_invalid")
        started_at = datetime.now(UTC)
        boot_before = self.adapter.boot_uuid()
        safety_before = dict(self.adapter.safety_facts())
        if fault == "mac_reboot":
            return self._reboot(
                duration_seconds=duration_seconds,
                boot_before=boot_before,
                started_at=started_at,
                safety_before=safety_before,
            )
        watchdog: dict[str, Any] = {"status": "not_required"}
        if fault in DEPENDENCY_FAULTS or fault == "rqdata":
            watchdog = dict(self.adapter.start_watchdog(
                fault=fault,
                duration_seconds=duration_seconds,
                target_ip=target_ip,
                evidence_root=self.evidence_root,
                parent_packet_hash=self.parent_packet_hash,
            ))
            if watchdog.get("status") != "armed":
                raise HtDyS610Error("fault_watchdog_not_armed")
        if fault in DEPENDENCY_FAULTS:
            self.adapter.stop(fault)
            try:
                self.sleeper(duration_seconds)
            finally:
                self.adapter.start(fault)
                if not self.adapter.healthy(fault):
                    raise HtDyS610Error("fault_recovery_failed")
        elif fault in KICKSTART_FAULTS:
            self.adapter.kickstart(fault)
            if not self.adapter.healthy(fault):
                raise HtDyS610Error("fault_recovery_failed")
        else:
            target = _validated_ip(target_ip)
            self.adapter.block_ip(target)
            try:
                self.sleeper(duration_seconds)
            finally:
                self.adapter.unblock_ip(target)
                if not self.adapter.healthy(fault):
                    raise HtDyS610Error("fault_recovery_failed")
        return self._publish_receipt(
            fault=fault,
            duration_seconds=duration_seconds,
            target_ip=target_ip,
            boot_before=boot_before,
            boot_after=self.adapter.boot_uuid(),
            started_at=started_at,
            watchdog=watchdog,
            safety_before=safety_before,
            safety_after=dict(self.adapter.safety_facts()),
        )

    def _reboot(
        self,
        *,
        duration_seconds: int,
        boot_before: str,
        started_at: datetime,
        safety_before: Mapping[str, Any],
    ) -> dict[str, Any]:
        marker_path = self.evidence_root / "faults" / "mac_reboot_marker.json"
        if not marker_path.exists():
            marker = {
                "schema_version": 1,
                "status": "reboot_requested",
                "parent_packet_hash": self.parent_packet_hash,
                "boot_uuid_before": boot_before,
                "requested_at": started_at.isoformat(),
                "safety_before": dict(safety_before),
            }
            marker["marker_hash"] = canonical_hash(marker)
            publish_json_create_only(marker_path, marker)
            self.adapter.reboot()
            return marker
        import json

        marker = json.loads(marker_path.read_text(encoding="utf-8"))
        if marker.get("parent_packet_hash") != self.parent_packet_hash:
            raise HtDyS610Error("reboot_marker_parent_drift")
        if marker.get("boot_uuid_before") == boot_before:
            raise HtDyS610Error("mac_reboot_not_observed")
        return self._publish_receipt(
            fault="mac_reboot",
            duration_seconds=duration_seconds,
            target_ip=None,
            boot_before=str(marker["boot_uuid_before"]),
            boot_after=boot_before,
            started_at=datetime.fromisoformat(str(marker["requested_at"])),
            watchdog={"status": "reboot_two_phase"},
            safety_before=dict(marker.get("safety_before") or {}),
            safety_after=dict(self.adapter.safety_facts()),
        )

    def _publish_receipt(
        self,
        *,
        fault: str,
        duration_seconds: int,
        target_ip: str | None,
        boot_before: str,
        boot_after: str,
        started_at: datetime,
        watchdog: Mapping[str, Any],
        safety_before: Mapping[str, Any],
        safety_after: Mapping[str, Any],
    ) -> dict[str, Any]:
        receipt: dict[str, Any] = {
            "schema_version": 1,
            "task_id": "JM-LIVE-STABILITY-S6-10",
            "status": "recovered",
            "parent_packet_hash": self.parent_packet_hash,
            "fault": fault,
            "duration_seconds": duration_seconds,
            "target_ip": target_ip,
            "started_at": started_at.isoformat(),
            "recovered_at": datetime.now(UTC).isoformat(),
            "boot_uuid_before": boot_before,
            "boot_uuid_after": boot_after,
            "watchdog": dict(watchdog),
            "safety_before": dict(safety_before),
            "safety_after": dict(safety_after),
        }
        if safety_before != safety_after:
            raise HtDyS610Error("fault_safety_facts_drift")
        if (
            safety_after.get("notification_worker_loaded") is not False
            or safety_after.get("signal_notifications") != 2
        ):
            raise HtDyS610Error("fault_notification_boundary_invalid")
        receipt["receipt_hash"] = canonical_hash(receipt)
        path = (
            self.evidence_root
            / "faults"
            / f"{fault}-{receipt['receipt_hash'][:12]}.json"
        )
        publish_json_create_only(path, receipt)
        return receipt


class SubprocessFaultPlatformAdapter:
    """macOS/Docker/PF adapter; used only after exact Approval C verification."""

    LABELS = {
        "live_scheduler": "com.guiyi.quant-runtime-scheduler",
        "api": "com.guiyi.quant-api",
        "web": "com.guiyi.quant-web",
        "eod_scheduler": "com.guiyi.quant-after-market-scheduler",
    }
    CONTAINERS = {
        "redis": "guiyi-redis",
        "postgres": "guiyi-postgres",
    }
    PF_ANCHOR = "com.guiyi.htdy-s610"

    def __init__(
        self,
        *,
        runner: Callable[[list[str]], str] | None = None,
    ) -> None:
        self.runner = runner or self._run
        self._heartbeat_before: dict[str, str | None] = {}

    def boot_uuid(self) -> str:
        value = self.runner(["/usr/sbin/sysctl", "-n", "kern.boottime"])
        import hashlib

        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def start_watchdog(
        self,
        *,
        fault: str,
        duration_seconds: int,
        target_ip: str | None,
        evidence_root: Path,
        parent_packet_hash: str,
    ) -> Mapping[str, Any]:
        script = Path(__file__).resolve().parents[4] / "scripts" / (
            "htdy_s610_fault_watchdog.py"
        )
        command = [
            sys.executable,
            str(script),
            "--fault",
            fault,
            "--delay-seconds",
            str(duration_seconds + 5),
            "--evidence-root",
            str(evidence_root.resolve(strict=False)),
            "--parent-packet-hash",
            parent_packet_hash,
        ]
        if target_ip is not None:
            command.extend(["--target-ip", _validated_ip(target_ip)])
        process = subprocess.Popen(  # noqa: S603 - fixed local script and validated args.
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        ack = evidence_root / "faults" / f"{fault}-watchdog-{process.pid}.armed.json"
        for _ in range(20):
            if ack.is_file():
                return {"status": "armed", "pid": process.pid, "ack_path": str(ack)}
            if process.poll() is not None:
                break
            time.sleep(0.1)
        raise HtDyS610Error("fault_watchdog_not_armed")

    def stop(self, fault: str) -> None:
        self.runner(["docker", "stop", self.CONTAINERS[fault]])

    def start(self, fault: str) -> None:
        self.runner(["docker", "start", self.CONTAINERS[fault]])

    def kickstart(self, fault: str) -> None:
        if fault in {"live_scheduler", "eod_scheduler"}:
            self._heartbeat_before[fault] = self._heartbeat_value(fault)
        label = self.LABELS[fault]
        self.runner(
            [
                "launchctl",
                "kickstart",
                "-k",
                f"gui/{os.getuid()}/{label}",
            ]
        )

    def block_ip(self, target_ip: str) -> None:
        target = _validated_ip(target_ip)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            prefix="guiyi-s610-pf-",
            delete=False,
        ) as stream:
            stream.write(f"block drop quick to {target}\n")
            path = Path(stream.name)
        try:
            self.runner(["sudo", "-n", "pfctl", "-E"])
            self.runner(
                [
                    "sudo",
                    "-n",
                    "pfctl",
                    "-a",
                    self.PF_ANCHOR,
                    "-f",
                    str(path),
                ]
            )
        finally:
            path.unlink(missing_ok=True)

    def unblock_ip(self, target_ip: str) -> None:
        _validated_ip(target_ip)
        self.runner(
            [
                "sudo",
                "-n",
                "pfctl",
                "-a",
                self.PF_ANCHOR,
                "-F",
                "all",
            ]
        )

    def healthy(self, fault: str) -> bool:
        try:
            if fault in self.CONTAINERS:
                value = self.runner(
                    [
                        "docker",
                        "inspect",
                        "--format",
                        "{{.State.Running}}",
                        self.CONTAINERS[fault],
                    ]
                )
                if value.strip() != "true":
                    return False
                if fault == "redis":
                    from app.queue import get_redis_connection

                    return bool(get_redis_connection().ping())
                from sqlalchemy import text

                from app.db.session import SessionLocal

                with SessionLocal() as session:
                    return session.execute(text("SELECT 1")).scalar_one() == 1
            if fault in self.LABELS:
                value = self.runner(
                    [
                        "launchctl",
                        "print",
                        f"gui/{os.getuid()}/{self.LABELS[fault]}",
                    ]
                )
                if "pid =" not in value or "state = running" not in value:
                    return False
                if fault in {"live_scheduler", "eod_scheduler"}:
                    before = self._heartbeat_before.get(fault)
                    for _ in range(20):
                        current = self._heartbeat_value(fault)
                        if current is not None and current != before:
                            return True
                        time.sleep(0.5)
                    return False
                if fault in {"api", "web"}:
                    return self._http_healthy(fault)
                return True
            if fault == "rqdata":
                from datetime import timedelta

                from app.services.rqdata_ingest.client import RqDataClient

                today = datetime.now(UTC).date()
                return bool(
                    RqDataClient(load_env_file=True).trading_dates(
                        today,
                        today + timedelta(days=7),
                    )
                )
            return False
        except HtDyS610Error:
            return False

    def reboot(self) -> None:
        self.runner(["sudo", "-n", "shutdown", "-r", "now"])

    def safety_facts(self) -> Mapping[str, Any]:
        from sqlalchemy import func, select

        from app.db.session import SessionLocal
        from app.models.signal import SignalNotification

        try:
            self.runner(
                [
                    "launchctl",
                    "print",
                    f"gui/{os.getuid()}/com.guiyi.quant-notification-worker",
                ]
            )
            worker_loaded = True
        except HtDyS610Error:
            worker_loaded = False
        with SessionLocal() as session:
            count = int(
                session.scalar(select(func.count(SignalNotification.id))) or 0
            )
            attempts = int(
                session.scalar(
                    select(func.coalesce(func.sum(SignalNotification.attempt_count), 0))
                )
                or 0
            )
            session.rollback()
        return {
            "notification_worker_loaded": worker_loaded,
            "signal_notifications": count,
            "wechat_attempt_total": attempts,
        }

    @staticmethod
    def _heartbeat_value(fault: str) -> str | None:
        from app.after_market_scheduler import (
            HEARTBEAT_KEY as AFTER_MARKET_HEARTBEAT_KEY,
        )
        from app.queue import get_redis_connection
        from app.runtime_scheduler import SCHEDULER_HEARTBEAT_KEY

        key = (
            SCHEDULER_HEARTBEAT_KEY
            if fault == "live_scheduler"
            else AFTER_MARKET_HEARTBEAT_KEY
        )
        raw = get_redis_connection().get(key)
        if raw is None:
            return None
        return (
            raw.decode("utf-8", errors="strict")
            if isinstance(raw, bytes)
            else str(raw)
        )

    @staticmethod
    def _http_healthy(fault: str) -> bool:
        import urllib.request

        url = (
            "http://127.0.0.1:8000/healthz"
            if fault == "api"
            else "http://127.0.0.1:5173/"
        )
        try:
            with urllib.request.urlopen(url, timeout=3) as response:  # noqa: S310
                return response.status == 200
        except OSError:
            return False

    @staticmethod
    def _run(command: list[str]) -> str:
        try:
            result = subprocess.run(  # noqa: S603 - fixed command vectors.
                command,
                check=True,
                capture_output=True,
                text=True,
            )
        except (OSError, subprocess.CalledProcessError) as exc:
            raise HtDyS610Error("fault_platform_command_failed") from exc
        return result.stdout


def _validated_ip(value: str | None) -> str:
    try:
        parsed = ipaddress.ip_address(str(value))
    except ValueError as exc:
        raise HtDyS610Error("rqdata_target_ip_invalid") from exc
    if parsed.is_unspecified or parsed.is_loopback:
        raise HtDyS610Error("rqdata_target_ip_invalid")
    return str(parsed)


def default_fault_executor(
    *,
    evidence_root: Path,
    parent_packet_hash: str,
) -> HtDyS610FaultExecutor:
    return HtDyS610FaultExecutor(
        adapter=SubprocessFaultPlatformAdapter(),
        sleeper=time.sleep,
        evidence_root=evidence_root,
        parent_packet_hash=parent_packet_hash,
    )


def verify_fault_receipts(
    evidence_root: Path,
    *,
    parent_packet_hash: str,
) -> set[str]:
    import json

    seen: set[str] = set()
    for path in sorted((evidence_root / "faults").glob("*-*.json")):
        if path.name == "mac_reboot_marker.json" or "-watchdog-" in path.name:
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise HtDyS610Error("fault_receipt_invalid") from exc
        if not isinstance(payload, dict):
            raise HtDyS610Error("fault_receipt_invalid")
        fault = payload.get("fault")
        safety_before = payload.get("safety_before")
        safety_after = payload.get("safety_after")
        watchdog = payload.get("watchdog")
        if (
            fault not in ALL_FAULTS
            or fault in seen
            or payload.get("status") != "recovered"
            or payload.get("parent_packet_hash") != parent_packet_hash
            or not isinstance(safety_before, dict)
            or safety_before != safety_after
            or safety_before.get("notification_worker_loaded") is not False
            or safety_before.get("signal_notifications") != 2
            or not isinstance(watchdog, dict)
            or payload.get("receipt_hash") != canonical_hash(payload)
        ):
            raise HtDyS610Error("fault_receipt_invalid")
        if fault in DEPENDENCY_FAULTS or fault == "rqdata":
            ack_path = Path(str(watchdog.get("ack_path") or ""))
            fault_root = (evidence_root / "faults").resolve(strict=True)
            try:
                ack_path.resolve(strict=True).relative_to(fault_root)
            except (OSError, ValueError) as exc:
                raise HtDyS610Error("fault_watchdog_path_invalid") from exc
            cleanup_path = Path(
                str(ack_path).replace(".armed.json", ".receipt.json")
            )
            if not ack_path.is_file() or not cleanup_path.is_file():
                raise HtDyS610Error("fault_watchdog_receipt_missing")
            cleanup = json.loads(cleanup_path.read_text(encoding="utf-8"))
            ack = json.loads(ack_path.read_text(encoding="utf-8"))
            pid = watchdog.get("pid")
            if (
                ack.get("status") != "armed"
                or ack.get("fault") != fault
                or ack.get("parent_packet_hash") != parent_packet_hash
                or ack.get("pid") != pid
                or cleanup.get("status") != "cleanup_completed"
                or cleanup.get("parent_packet_hash") != parent_packet_hash
                or cleanup.get("fault") != fault
                or cleanup.get("pid") != pid
                or cleanup.get("ack_sha256") != _file_sha256(ack_path)
                or cleanup.get("receipt_hash")
                != _watchdog_receipt_hash(cleanup)
            ):
                raise HtDyS610Error("fault_watchdog_receipt_invalid")
        seen.add(str(fault))
    if seen != ALL_FAULTS:
        raise HtDyS610Error("fault_receipt_matrix_incomplete")
    return seen


def _file_sha256(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def _watchdog_receipt_hash(payload: Mapping[str, Any]) -> str:
    import hashlib
    import json

    normalized = {
        key: value for key, value in payload.items() if key != "receipt_hash"
    }
    return hashlib.sha256(
        json.dumps(
            normalized,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
