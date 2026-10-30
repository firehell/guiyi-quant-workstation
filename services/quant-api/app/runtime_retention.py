"""Read-only release worktree retention proof; this module never deletes a tree."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import subprocess
import stat
from typing import Any

from app.runtime_bindings import SERVICES, _git, read_bindings, verify_release


class RetentionError(ValueError):
    pass


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _references(value: str, root: Path) -> bool:
    # A conservative prefix match retains descendants and ambiguous shell quoting.
    return str(root) in value


class _SimNowReferences:
    """Only named SimNow configuration anchors; never load settings or Broker code."""
    PATH_FIELDS = frozenset({"project_root", "api_env", "sdk_python", "state_root",
        "state_project_root", "ordinary_takeover_permit", "deployment_connection_permit"})

    def __init__(self, roots, result):
        self.roots, self.result = roots, result
        self.snapshots = {}
        self.limits = {}
        self.absent = set()
        self.service_seen = False
        self.dependencies = {}

    @staticmethod
    def snapshot(path, *, limit):
        from app.runtime_identity import file_snapshot, safe_directory
        if not path.is_absolute() or path != path.resolve(strict=True):
            raise RetentionError("CLEANUP_SIMNOW_PRIVATE_INVALID")
        with safe_directory(path.parent) as directory:
            info = os.fstat(directory)
            parent_identity = (info.st_dev, info.st_ino, info.st_mode, info.st_uid)
        info = path.lstat()
        if stat.S_IMODE(info.st_mode) != 0o600:
            raise RetentionError("CLEANUP_SIMNOW_PRIVATE_INVALID")
        raw, identity = file_snapshot(path, limit=limit)
        if identity != (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns):
            raise RetentionError("CLEANUP_SIMNOW_PRIVATE_DRIFT")
        with safe_directory(path.parent) as directory:
            info = os.fstat(directory)
            if parent_identity != (info.st_dev, info.st_ino, info.st_mode, info.st_uid):
                raise RetentionError("CLEANUP_SIMNOW_PRIVATE_DRIFT")
        return raw, identity, parent_identity

    def read(self, path, *, limit=64 * 1024 * 1024):
        path = Path(path)
        snapshot = self.snapshot(path, limit=limit)
        if path in self.snapshots and self.snapshots[path] != snapshot:
            raise RetentionError("CLEANUP_SIMNOW_PRIVATE_DRIFT")
        self.snapshots[path] = snapshot
        self.limits[path] = min(limit, self.limits.get(path, limit))
        def unique(pairs):
            value = {}
            for key, item in pairs:
                if key in value:
                    raise RetentionError("CLEANUP_SIMNOW_PRIVATE_INVALID")
                value[key] = item
            return value
        value = json.loads(snapshot[0], object_pairs_hook=unique)
        if not isinstance(value, dict):
            raise RetentionError("CLEANUP_SIMNOW_PRIVATE_INVALID")
        return value

    def pin(self, values, reason):
        for root in self.roots:
            if any(_references(value, root) for value in values):
                self.result[str(root)].append(reason)

    @staticmethod
    def dependency_snapshot(path):
        """Follow named aliases, recording link/entry identity but no directory timestamps."""
        def walk():
            current = Path(path.anchor)
            pending = list(reversed(path.parts[1:]))
            entries = []
            links = 0
            while pending:
                part = pending.pop()
                if part == ".":
                    continue
                if part == "..":
                    current = current.parent
                    continue
                entry = current / part
                try:
                    info = entry.lstat()
                except FileNotFoundError:
                    entries.append((str(entry), None))
                    current = entry
                    continue
                identity = (info.st_dev, info.st_ino, info.st_mode, info.st_uid)
                if stat.S_ISLNK(info.st_mode):
                    links += 1
                    if links > 40:
                        raise RetentionError("CLEANUP_SIMNOW_ALIAS_UNPROVEN")
                    target = os.readlink(entry)
                    entries.append((str(entry), (*identity, info.st_size, info.st_mtime_ns, info.st_ctime_ns, target)))
                    destination = Path(target)
                    if destination.is_absolute():
                        current = Path(destination.anchor)
                        pending.extend(reversed(destination.parts[1:]))
                    else:
                        pending.extend(reversed(destination.parts))
                else:
                    # Journals can change contents within state_root during this read-only scan.
                    entries.append((str(entry), identity))
                    current = entry
            return str(current), tuple(entries)
        try:
            before = walk()
            if before != walk() or before[0] != str(path.resolve(strict=False)):
                raise RetentionError("CLEANUP_SIMNOW_ALIAS_DRIFT")
            return before
        except RuntimeError:
            raise RetentionError("CLEANUP_SIMNOW_ALIAS_UNPROVEN") from None

    def config(self, path, reason):
        value = self.read(path, limit=1024 * 1024)
        required = {"schema", "account_id", "state_root", "project_root", "sdk_python", "api_env", "mode", "enabled"}
        schema = value.get("schema")
        if type(schema) is not int or schema not in (1, 2, 3):
            raise RetentionError("CLEANUP_SIMNOW_CONFIG_UNPROVEN")
        if schema in (2, 3):
            required.add("state_project_root")
        optional = {"account_profile", "account_takeover_pending", "ordinary_takeover_permit", "deployment_connection_permit"} if schema == 2 else set()
        if (not required <= value.keys() or value.keys() - (required | optional)
                or not isinstance(value["account_id"], str) or not re.fullmatch(r"[0-9a-f]{64}", value["account_id"])
                or type(value["enabled"]) is not bool
                or value["mode"] not in (("observe", "manage", "trade") if schema == 2 else ("observe", "manage"))
                or schema == 3 and (value["mode"] != "observe" or value["enabled"] is not False)):
            raise RetentionError("CLEANUP_SIMNOW_CONFIG_UNPROVEN")
        paths = []
        for key in self.PATH_FIELDS & value.keys():
            item = value[key]
            if not isinstance(item, str) or not item.startswith("/") or any(ord(c) < 32 for c in item):
                raise RetentionError("CLEANUP_SIMNOW_PRIVATE_INVALID")
            dependency = Path(item)
            observed = self.dependency_snapshot(dependency)
            if dependency in self.dependencies and self.dependencies[dependency] != observed:
                raise RetentionError("CLEANUP_SIMNOW_ALIAS_DRIFT")
            self.dependencies[dependency] = observed
            paths.extend((item, observed[0], *(entry for entry, _identity in observed[1])))
        self.pin([str(path), *paths], reason)

    def arguments(self, arguments, label, source):
        if not re.fullmatch(r"com\.guiyi\.quant-simnow(?:-candidate-[0-9a-f]{32})?", label):
            return
        self.service_seen = True
        switches = [i for i, value in enumerate(arguments) if value.startswith("--config")]
        if (len(switches) != 1 or arguments[switches[0]] != "--config"
                or switches[0] + 1 >= len(arguments) or arguments[switches[0] + 1].startswith("-")):
            raise RetentionError("CLEANUP_SIMNOW_CONFIG_UNPROVEN")
        self.config(Path(arguments[switches[0] + 1]), f"{source}-config:{label}")

    def monitor(self, home):
        path = home / "Library/Application Support/GuiyiQuant/simnow-monitor.private.json"
        if os.path.lexists(path):
            self.config(path, "simnow-monitor")
        else:
            self.absent.add(path)
            # A SimNow service requires its stable monitoring identity anchor.
            if self.service_seen:
                raise RetentionError("CLEANUP_SIMNOW_MONITOR_UNPROVEN")

    def intents(self, repo_root):
        """Inspect only operator SimNow switch artifacts at their documented paths."""
        locations = {repo_root}
        if os.path.lexists(repo_root / ".git"):
            common = Path(_git(repo_root, "rev-parse", "--path-format=absolute", "--git-common-dir"))
            locations.add(common.resolve(strict=True).parent)
        def inventory():
            paths = set()
            for location in locations:
                for leaf in ("switch-intent.private.json", "ordinary-recovery-intent.private.json"):
                    paths.update((location / "output").glob(f"simnow*/{leaf}"))
            if len(paths) > 1024:
                raise RetentionError("CLEANUP_SIMNOW_INTENTS_UNPROVEN")
            return paths
        self.intent_inventory = inventory
        self.intent_paths = inventory()
        for path in sorted(self.intent_paths):
            value = self.read(path)
            if self.closed_intent(path, value):
                continue
            # Preserve every named recovery path, including preimages and permits.
            self.pin([json.dumps(value, sort_keys=True, ensure_ascii=False)], f"simnow-recovery:{path.parent.name}:{path.name}")

    def closed_intent(self, path, value):
        """A terminal word alone is never proof. Unknown recovery schemas stay pinned."""
        if (value.get("schema") != "simnow_trade_switch_plan_v7" or value.get("stage") != "COMPLETE"
                or value.get("result") not in {"HOST_SWITCH_VERIFIED", "HOST_SWITCH_LATE_VERIFIED"}):
            return False
        plan_path = path.parent / "switch-plan.private.json"
        plan = self.read(plan_path)
        if (plan.get("schema") != value["schema"] or plan.get("plan_hash") != value.get("plan_hash")
                or _hash({key: item for key, item in plan.items() if key != "plan_hash"}) != plan.get("plan_hash")):
            raise RetentionError("CLEANUP_SIMNOW_CLOSURE_UNPROVEN")
        snapshot = value.get("snapshot", {})
        original = plan.get("snapshot", {})
        pid, run_id = value.get("pid"), value.get("run_id")
        if (not isinstance(snapshot, dict) or not isinstance(original, dict)
                or not isinstance(snapshot.get("candidate"), dict) or not snapshot["candidate"]
                or snapshot.get("candidate") != original.get("candidate")
                or not isinstance(snapshot.get("host"), dict) or not snapshot["host"]
                or snapshot.get("host") != original.get("host")
                or type(pid) is not int or pid <= 1 or not isinstance(run_id, str) or not run_id
                or pid == snapshot["host"].get("pid") or run_id == snapshot["host"].get("run_id")):
            raise RetentionError("CLEANUP_SIMNOW_CLOSURE_UNPROVEN")
        if value["result"] == "HOST_SWITCH_VERIFIED":
            candidate = snapshot["candidate"]
            identities = candidate.get("identities", {})
            preimage = snapshot.get("preimage")
            release = preimage.get("release") if isinstance(preimage, dict) else None
            if (value.get("error") or value.get("native_recovery_complete") is not False
                    or type(plan.get("created_at")) not in (int, float)
                    or type(plan.get("expires_at")) not in (int, float)
                    or plan["expires_at"] - plan["created_at"] != 60
                    or plan.get("execution_permitted") is not False or plan.get("broker_io") is not False
                    or not isinstance(release, dict)
                    or not isinstance(release.get("root"), str) or not release["root"].startswith("/")
                    or release.get("tag") != candidate.get("tag")
                    or release.get("commit") != candidate.get("commit")
                    or "root" in candidate and candidate["root"] != release["root"]
                    or not isinstance(candidate.get("tag"), str) or not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", candidate["tag"])
                    or not isinstance(candidate.get("commit"), str) or not re.fullmatch(r"[0-9a-f]{40}", candidate["commit"])
                    or any(candidate.get(key) is not True for key in ("annotated_exact", "clean", "sdk_check", "preflight_valid"))
                    or not isinstance(identities, dict)
                    or identities.get("code") != candidate["commit"]
                    or any(not identities.get(key) for key in ("code", "sdk", "config", "plist", "old_config", "old_plist", "monitor"))):
                raise RetentionError("CLEANUP_SIMNOW_CLOSURE_UNPROVEN")
            return True
        receipt_path = path.parent / "late-started-receipt.private.json"
        before_path = path.parent / "late-started-beforeimage.private.json"
        receipt, before = self.read(receipt_path), self.read(before_path)
        def sha(path):
            return hashlib.sha256(self.snapshots[path][0]).hexdigest()
        if (value.get("reconciliation_receipt") != {"path": str(receipt_path), "sha256": sha(receipt_path)}
                or value.get("initial_failure") != {"path": str(before_path), "sha256": sha(before_path)}
                or receipt.get("schema") != "simnow_late_started_reconciliation_v1"
                or receipt.get("original_intent_sha256") != sha(before_path)
                or receipt.get("original_plan_sha256") != sha(plan_path)
                or receipt.get("plan_hash") != plan["plan_hash"]
                or before.get("plan_hash") != plan["plan_hash"]
                or before.get("snapshot") != snapshot or receipt.get("target") != snapshot["candidate"]
                or receipt.get("runtime_restart") is not False):
            raise RetentionError("CLEANUP_SIMNOW_CLOSURE_UNPROVEN")
        proofs = receipt.get("proofs")
        if not isinstance(proofs, list) or len(proofs) != 2:
            raise RetentionError("CLEANUP_SIMNOW_CLOSURE_UNPROVEN")
        for proof in proofs:
            if (not isinstance(proof, dict) or proof.get("pid") != pid or proof.get("run_id") != run_id
                    or proof.get("mode") != "trade" or proof.get("opening_enabled") is not False
                    or any(proof.get(key) is not True for key in ("verified", "dual_locks_held_by_pid",
                        "config_bound", "monitor_bound", "account_takeover_pending"))):
                raise RetentionError("CLEANUP_SIMNOW_CLOSURE_UNPROVEN")
        claim = self.read(path.parent / "late-started-reconciliation-claim.private.json")
        if claim != {"source_sha256": sha(before_path), "receipt_hash": _hash(receipt)}:
            raise RetentionError("CLEANUP_SIMNOW_CLOSURE_UNPROVEN")
        return True

    def verify(self):
        for path, expected in self.dependencies.items():
            if self.dependency_snapshot(path) != expected:
                raise RetentionError("CLEANUP_SIMNOW_ALIAS_DRIFT")
        for path, expected in self.snapshots.items():
            if self.snapshot(path, limit=self.limits[path]) != expected:
                raise RetentionError("CLEANUP_SIMNOW_PRIVATE_DRIFT")
        if hasattr(self, "intent_inventory") and self.intent_inventory() != self.intent_paths:
            raise RetentionError("CLEANUP_SIMNOW_PRIVATE_DRIFT")
        if any(os.path.lexists(path) for path in self.absent):
            raise RetentionError("CLEANUP_SIMNOW_PRIVATE_DRIFT")


def build_cleanup_plan(roots: tuple[Path, ...], *, backend=None) -> dict[str, Any]:
    """Freeze exact deletion candidates, and fail closed on incomplete host evidence."""
    if not roots or len(set(roots)) != len(roots):
        raise RetentionError("CLEANUP_TARGETS_INVALID")
    for root in roots:
        if not isinstance(root, Path) or not root.is_absolute() or root != root.resolve(strict=True):
            raise RetentionError("CLEANUP_TARGETS_INVALID")
    backend = backend or RetentionBackend()
    identities = {}
    invalid = set()
    for root in roots:
        try:
            identities[str(root)] = backend.candidate_identity(root)
        except (OSError, ValueError, subprocess.SubprocessError):
            invalid.add(str(root))
    try:
        references = backend.references_by_root(roots)
        probe_unknown = False
    except (OSError, ValueError, subprocess.SubprocessError):
        references = {}
        probe_unknown = True
    targets = []
    for root in roots:
        key = str(root)
        reasons = sorted(set(references.get(key, [])))
        unknown = probe_unknown or key in invalid or key not in references
        targets.append({"root": key, "identity": identities.get(key),
            "status": "blocked" if unknown else "retained" if reasons else "eligible",
            "references": reasons, "error_code": "CLEANUP_EVIDENCE_UNAVAILABLE" if unknown else None})
    plan = {"schema_version": 1, "readonly": True, "dry_run": True, "targets": targets,
            "eligible_roots": [row["root"] for row in targets if row["status"] == "eligible"],
            "recovery": "git worktree removal only after an unchanged exact plan readback; never force"}
    plan["plan_sha256"] = _hash(plan)
    return plan


class RetentionBackend:
    def __init__(self, *, home: Path | None = None):
        self.home = Path.home() if home is None else home

    def candidate_identity(self, root: Path) -> dict[str, str]:
        # Release cleanup only accepts a registered detached clean annotated-tag worktree.
        if (root / ".git").is_symlink() or not (root / ".git").is_file():
            raise RetentionError("CLEANUP_MANAGED_WORKTREE_REQUIRED")
        from app.core.env import PROJECT_ROOT
        common = _git(root, "rev-parse", "--path-format=absolute", "--git-common-dir")
        authorized_common = _git(PROJECT_ROOT, "rev-parse", "--path-format=absolute", "--git-common-dir")
        if Path(common).resolve(strict=True) != Path(authorized_common).resolve(strict=True):
            raise RetentionError("CLEANUP_REPOSITORY_IDENTITY_INVALID")
        commit = _git(root, "rev-parse", "HEAD")
        tag = _git(root, "describe", "--exact-match", "--tags", "HEAD")
        verify_release(root, tag, commit)
        listed = _git(root, "worktree", "list", "--porcelain")
        blocks = [dict((line.partition(" ")[0], line.partition(" ")[2]) for line in block.splitlines())
                  for block in listed.split("\n\n") if block]
        matching = [item for item in blocks if item.get("worktree") == str(root)]
        if len(matching) != 1 or matching[0].get("HEAD") != commit or "detached" not in matching[0]:
            raise RetentionError("CLEANUP_WORKTREE_IDENTITY_INVALID")
        return {"root": str(root), "commit": commit, "tag": tag}

    def _command(self, arguments: list[str]) -> str:
        try:
            result = subprocess.run(arguments, capture_output=True, text=True, timeout=15, check=True)
            return result.stdout
        except (OSError, subprocess.SubprocessError):
            raise RetentionError("CLEANUP_PROBE_UNAVAILABLE") from None

    def references_by_root(self, roots: tuple[Path, ...]) -> dict[str, list[str]]:
        from app.runtime_identity import launchd_arguments as _arguments, launchd_environments as _environments, file_snapshot as _snapshot
        result: dict[str, list[str]] = {str(root): [] for root in roots}
        simnow = _SimNowReferences(roots, result)
        registry = read_bindings(home=self.home)
        if registry is not None:
            for service, binding in registry.services.items():
                if binding.root in result:
                    result[binding.root].append(f"binding:{service}")
        directory = self.home / "Library/LaunchAgents"
        labels = set()
        if directory.exists():
            if directory != directory.resolve(strict=True):
                raise RetentionError("CLEANUP_PLIST_DIRECTORY_INVALID")
            for path in directory.glob("com.guiyi.quant-*.plist"):
                content, _ = _snapshot(path)
                try:
                    payload = plistlib.loads(content)
                    label = payload["Label"]
                    if label != path.stem:
                        raise ValueError
                    labels.add(label)
                    environment = payload.get("EnvironmentVariables", {})
                    values = [payload.get("WorkingDirectory", ""), *(environment.get(key, "") for key in ("GUIYI_PROJECT_ROOT", "PYTHONPATH", "VIRTUAL_ENV"))]
                    arguments = payload.get("ProgramArguments", [])
                    if not isinstance(arguments, list) or any(not isinstance(value, str) for value in arguments):
                        raise ValueError
                    values.extend(arguments)
                    simnow.arguments(arguments, label, "plist")
                    if any(not isinstance(value, str) for value in values):
                        raise ValueError
                    for root in roots:
                        if any(_references(value, root) for value in values):
                            result[str(root)].append(f"plist:{label}")
                except (KeyError, TypeError, ValueError, plistlib.InvalidFileException):
                    raise RetentionError("CLEANUP_PLIST_UNAVAILABLE") from None
        # Inventory loaded labels as well as installed plists; stale candidate jobs are pins.
        output = self._command(["/bin/launchctl", "list"])
        for line in output.splitlines()[1:]:
            parts = line.split()
            if len(parts) != 3:
                raise RetentionError("CLEANUP_LOADED_INVENTORY_INVALID")
            if parts[2].startswith("com.guiyi.quant-"):
                labels.add(parts[2])
        valid_label = re.compile(r"com\.guiyi\.quant-(?:" + "|".join(re.escape(item) for item in (*SERVICES, "simnow")) + r")(?:-candidate-[0-9a-f]{32})?")
        from app.runtime_identity import read_launchd_service as _read_launchd_service
        for label in labels:
            if not valid_label.fullmatch(label):
                raise RetentionError("CLEANUP_LOADED_LABEL_UNSUPPORTED")
            observed = _read_launchd_service(label, root=roots[0])
            if observed is None:
                continue
            values = list(_arguments(observed))
            simnow.arguments(values, label, "loaded")
            values.extend(environment.get(key, "") for environment in _environments(observed)
                          for key in ("GUIYI_PROJECT_ROOT", "PYTHONPATH", "VIRTUAL_ENV"))
            values.extend(re.findall(r"^\s*working directory = (.*)$", observed, flags=re.M))
            for root in roots:
                if any(_references(value, root) for value in values):
                    result[str(root)].append(f"loaded:{label}")
        simnow.monitor(self.home)
        # Unmanaged foreground commands may still hold code from a retired release.
        commands = self._command(["/bin/ps", "-ww", "-axo", "pid=,command="])
        for line in commands.splitlines():
            fields = line.strip().split(None, 1)
            if len(fields) != 2 or not fields[0].isdigit():
                raise RetentionError("CLEANUP_PROCESS_INVENTORY_INVALID")
            pid = int(fields[0])
            if pid == os.getpid():
                continue
            for root in roots:
                if _references(fields[1], root):
                    result[str(root)].append(f"process:{pid}")
        # A foreground Python process may use relative argv; its cwd is still a pin.
        cwd_inventory = self._command(["/usr/sbin/lsof", "-a", "-d", "cwd", "-F", "pn"])
        cwd_pid: int | None = None
        for line in cwd_inventory.splitlines():
            if line.startswith("p") and line[1:].isdigit():
                cwd_pid = int(line[1:])
            elif line == "fcwd" and cwd_pid is not None:
                continue
            elif line.startswith("n") and cwd_pid is not None:
                for root in roots:
                    if _references(line[1:], root):
                        result[str(root)].append(f"cwd:{cwd_pid}")
            else:
                raise RetentionError("CLEANUP_CWD_INVENTORY_INVALID")
        from app.core.env import PROJECT_ROOT
        from app.runtime_retirement import recovery_references
        simnow.intents(PROJECT_ROOT)
        recovery = recovery_references(self.home / "Library/Application Support/GuiyiQuant", PROJECT_ROOT, roots)
        for root, reasons in recovery.items():
            result[root].extend(reasons)
        simnow.verify()
        if read_bindings(home=self.home) != registry:
            raise RetentionError("CLEANUP_REGISTRY_DRIFT")
        return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only exact release cleanup plan")
    parser.add_argument("command", choices=["cleanup-plan", "closeout-plan", "seal-closed"])
    parser.add_argument("roots", nargs="*", type=Path)
    parser.add_argument("--plan", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command != "seal-closed" and args.plan is not None:
            raise ValueError
        if args.command == "cleanup-plan":
            payload = build_cleanup_plan(tuple(args.roots))
        else:
            from app.runtime_retirement import build_closeout_plan, seal_closed, _json
            if args.command == "closeout-plan":
                payload = build_closeout_plan(tuple(args.roots))
            else:
                if args.roots or args.plan is None:
                    raise ValueError
                payload = seal_closed(_json(args.plan))
    except (OSError, ValueError, KeyError, TypeError, RuntimeError):
        print(json.dumps({"status": "blocked", "readonly": args.command != "seal-closed",
            "error_code": "CLEANUP_TARGETS_INVALID" if args.command == "cleanup-plan" else "RETIREMENT_EVIDENCE_UNPROVEN"}))
        return 1
    print(json.dumps(payload, sort_keys=True))
    return 1 if any(item["status"] == "blocked" for item in payload.get("targets", [])) else 0


if __name__ == "__main__":
    raise SystemExit(main())
