"""macOS launchd and detached-Git adapter for product retirement.

The adapter is intentionally narrow: only the fixed writer labels can be
stopped/restarted, and all Git operations are restricted to the Runtime root
provided by the Gate.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
import os
from pathlib import Path
import subprocess

from app.services.product_retirement_runtime_gate import REQUIRED_WRITER_SERVICES


CommandRunner = Callable[[tuple[str, ...]], subprocess.CompletedProcess[str]]


class ProductRetirementRuntimeOperatorError(ValueError):
    pass


class LaunchdRuntimeOperator:
    """The production RuntimeOperator for the fixed launchd writer set."""

    def __init__(
        self,
        *,
        service_plists: Mapping[str, Path],
        runner: CommandRunner | None = None,
        domain: str | None = None,
    ) -> None:
        if set(service_plists) != set(REQUIRED_WRITER_SERVICES):
            raise ProductRetirementRuntimeOperatorError(
                "PRODUCT_RETIREMENT_SERVICE_PLISTS_MISMATCH"
            )
        self._service_plists = dict(service_plists)
        self._runner = runner or _run
        self._domain = domain or f"gui/{os.getuid()}"

    def stop_writer_services(self) -> Mapping[str, str]:
        prior = self.writer_states()
        for label in REQUIRED_WRITER_SERVICES:
            if prior[label] != "running":
                continue
            self._runner(("launchctl", "bootout", f"{self._domain}/{label}"))
        states = self.writer_states()
        if any(value != "stopped" for value in states.values()):
            raise ProductRetirementRuntimeOperatorError(
                "PRODUCT_RETIREMENT_SERVICE_STOP_FAILED"
            )
        return states

    def writer_states(self) -> Mapping[str, str]:
        return {
            label: (
                "running"
                if self._runner(
                    ("launchctl", "print", f"{self._domain}/{label}")
                ).returncode
                == 0
                else "stopped"
            )
            for label in REQUIRED_WRITER_SERVICES
        }

    def runtime_identity(self, root: Path) -> str:
        return self._git(root, "rev-parse", "HEAD")

    def checkout_detached(self, root: Path, ref: str) -> str:
        self._require_annotated_tag(root, ref)
        checkout = self._git_result(root, "checkout", "--detach", ref)
        if checkout.returncode != 0:
            raise ProductRetirementRuntimeOperatorError(
                "PRODUCT_RETIREMENT_RUNTIME_CHECKOUT_FAILED"
            )
        target = self._git(root, "rev-parse", f"{ref}^{{commit}}")
        current = self.runtime_identity(root)
        if current != target:
            raise ProductRetirementRuntimeOperatorError(
                "PRODUCT_RETIREMENT_RUNTIME_CHECKOUT_DRIFT"
            )
        return current

    def restart_services(self, target_states: Mapping[str, str]) -> Mapping[str, str]:
        if set(target_states) != set(REQUIRED_WRITER_SERVICES) or any(
            value not in {"running", "stopped"} for value in target_states.values()
        ):
            raise ProductRetirementRuntimeOperatorError(
                "PRODUCT_RETIREMENT_SERVICE_STATES_INVALID"
            )
        if any(value != "stopped" for value in self.writer_states().values()):
            raise ProductRetirementRuntimeOperatorError(
                "PRODUCT_RETIREMENT_SERVICE_RESTART_REQUIRES_STOPPED"
            )
        for label in REQUIRED_WRITER_SERVICES:
            if target_states[label] != "running":
                continue
            plist = self._service_plists[label]
            if not plist.is_absolute() or plist.is_symlink() or not plist.is_file():
                raise ProductRetirementRuntimeOperatorError(
                    "PRODUCT_RETIREMENT_SERVICE_PLIST_INVALID"
                )
            result = self._runner(("launchctl", "bootstrap", self._domain, str(plist)))
            if result.returncode != 0:
                raise ProductRetirementRuntimeOperatorError(
                    "PRODUCT_RETIREMENT_SERVICE_BOOTSTRAP_FAILED"
                )
        states = self.writer_states()
        if dict(states) != dict(target_states):
            raise ProductRetirementRuntimeOperatorError(
                "PRODUCT_RETIREMENT_SERVICE_RESTORE_MISMATCH"
            )
        return states

    def preflight(
        self, *, root: Path, release_tag: str, rollback_tag: str
    ) -> dict[str, object]:
        """Read-only Runtime checks; it does not stop services or change refs."""

        invalid_plists = [
            label
            for label, plist in self._service_plists.items()
            if not plist.is_absolute() or plist.is_symlink() or not plist.is_file()
        ]
        if invalid_plists:
            raise ProductRetirementRuntimeOperatorError(
                "PRODUCT_RETIREMENT_SERVICE_PLIST_INVALID:"
                + ",".join(sorted(invalid_plists))
            )
        current = self.runtime_identity(root)
        if self._git_result(root, "status", "--porcelain=v1").stdout.strip():
            raise ProductRetirementRuntimeOperatorError(
                "PRODUCT_RETIREMENT_RUNTIME_DIRTY"
            )
        branch = self._git_result(root, "symbolic-ref", "-q", "HEAD")
        if branch.returncode == 0:
            raise ProductRetirementRuntimeOperatorError(
                "PRODUCT_RETIREMENT_RUNTIME_NOT_DETACHED"
            )
        release_sha = self._require_annotated_tag(root, release_tag)
        rollback_sha = self._require_annotated_tag(root, rollback_tag)
        return {
            "runtime_sha": current,
            "release_tag": release_tag,
            "release_sha": release_sha,
            "rollback_tag": rollback_tag,
            "rollback_sha": rollback_sha,
            "writer_states": dict(self.writer_states()),
        }

    def _require_annotated_tag(self, root: Path, ref: str) -> str:
        if not ref.startswith("runtime-"):
            raise ProductRetirementRuntimeOperatorError(
                "PRODUCT_RETIREMENT_RUNTIME_TAG_INVALID"
            )
        kind = self._git(root, "cat-file", "-t", ref)
        if kind != "tag":
            raise ProductRetirementRuntimeOperatorError(
                "PRODUCT_RETIREMENT_RUNTIME_TAG_NOT_ANNOTATED"
            )
        return self._git(root, "rev-parse", f"{ref}^{{commit}}")

    def _git(self, root: Path, *args: str) -> str:
        result = self._git_result(root, *args)
        if result.returncode != 0:
            raise ProductRetirementRuntimeOperatorError(
                "PRODUCT_RETIREMENT_RUNTIME_GIT_COMMAND_FAILED"
            )
        value = result.stdout.strip()
        if not value:
            raise ProductRetirementRuntimeOperatorError(
                "PRODUCT_RETIREMENT_RUNTIME_GIT_OUTPUT_INVALID"
            )
        return value

    def _git_result(self, root: Path, *args: str) -> subprocess.CompletedProcess[str]:
        if not root.is_absolute() or root.is_symlink() or not root.is_dir():
            raise ProductRetirementRuntimeOperatorError(
                "PRODUCT_RETIREMENT_RUNTIME_ROOT_INVALID"
            )
        return self._runner(("git", "-C", str(root), *args))


def _run(command: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=False, text=True, capture_output=True)
