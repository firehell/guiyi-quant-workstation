#!/usr/bin/env python3
"""
epic_manager.py — Epic lifecycle management with readiness_flags.

Capabilities:
    - Parse Epic YAML frontmatter
    - Read/write readiness_flags
    - Immutable readiness flag history (JSONL log)
    - Check if all flags are true (epic ready to merge)
    - Validate epic schema

Usage:
    from epic_manager import EpicManager, EpicData

    mgr = EpicManager(".ai/results/WORKSTATION-GOVERNANCE-V2")
    mgr.set_flag("ws_v2_001_gate_passed", True)
    all_ready = mgr.all_flags_ready()
"""

import json
import os
import re
from pathlib import Path
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional


YAML_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


@dataclass
class EpicData:
    """In-memory representation of an Epic."""
    epic_id: str
    schema_version: str = "2.0"
    title: str = ""
    status: str = "DRAFT"
    risk_level: str = "R3"
    owner: str = "WorkBuddy"
    tasks: List[str] = field(default_factory=list)
    readiness_flags: Dict[str, bool] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""
    filepath: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": "Epic",
            "schema_version": self.schema_version,
            "epic_id": self.epic_id,
            "title": self.title,
            "status": self.status,
            "risk_level": self.risk_level,
            "owner": self.owner,
            "tasks": self.tasks,
            "readiness_flags": self.readiness_flags,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class EpicManager:
    """
    Manages Epic readiness_flags with immutable history.

    Data storage:
        - .ai/results/<EPIC_ID>/readiness_flags.json  (current state)
        - .ai/results/<EPIC_ID>/readiness_log.jsonl   (immutable history)
    """

    def __init__(self, results_dir: str, epic_file: Optional[str] = None):
        """
        Args:
            results_dir: Path to .ai/results/<EPIC_ID>/ directory
            epic_file: Optional path to the epic .md file for initial parsing
        """
        self.results_dir = Path(results_dir)
        self.epic_id = self.results_dir.name
        self.flags_file = self.results_dir / "readiness_flags.json"
        self.log_file = self.results_dir / "readiness_log.jsonl"
        self.results_dir.mkdir(parents=True, exist_ok=True)

        # Load current state
        self._flags: Dict[str, bool] = {}
        self._load_flags()

        # Load epic metadata if file provided
        self._epic_data: Optional[EpicData] = None
        if epic_file and os.path.exists(epic_file):
            self._epic_data = self.parse_epic_file(epic_file)

    def _load_flags(self):
        """Load current readiness_flags from JSON file."""
        if self.flags_file.exists():
            try:
                with open(self.flags_file, "r", encoding="utf-8") as f:
                    self._flags = json.load(f)
            except (json.JSONDecodeError, IOError):
                self._flags = {}
        else:
            self._flags = {}

    def _save_flags(self):
        """Save current readiness_flags to JSON file (atomic write)."""
        tmp_path = self.flags_file.with_suffix(".tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(self._flags, f, indent=2, ensure_ascii=False)
        tmp_path.replace(self.flags_file)

    def _log_change(self, flag_name: str, old_value: Optional[bool], new_value: bool, source: str = "unknown"):
        """Append an immutable log entry for a flag change."""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "flag": flag_name,
            "old_value": old_value,
            "new_value": new_value,
            "source": source,
            "epic_id": self.epic_id,
        }
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def get_flag(self, flag_name: str) -> Optional[bool]:
        """Get the current value of a readiness flag."""
        return self._flags.get(flag_name)

    def set_flag(self, flag_name: str, value: bool, source: str = "manual") -> bool:
        """
        Set a readiness flag. Records the change in immutable log.
        Returns True if value changed, False if unchanged.
        """
        old_value = self._flags.get(flag_name)
        if old_value == value:
            return False

        self._flags[flag_name] = value
        self._log_change(flag_name, old_value, value, source)
        self._save_flags()
        return True

    def set_flags_batch(self, updates: Dict[str, bool], source: str = "manual") -> int:
        """Set multiple flags at once. Returns count of changed flags."""
        changed = 0
        for name, value in updates.items():
            if self.set_flag(name, value, source):
                changed += 1
        return changed

    def all_flags_ready(self) -> bool:
        """Check if all readiness flags are True. Returns True if no flags defined."""
        if not self._flags:
            return True
        return all(self._flags.values())

    def get_unready_flags(self) -> List[str]:
        """Return list of flag names that are not yet True."""
        return [name for name, value in self._flags.items() if not value]

    def get_flags_summary(self) -> Dict[str, Any]:
        """Return a summary of all flags with status."""
        return {
            "epic_id": self.epic_id,
            "all_ready": self.all_flags_ready(),
            "flags": dict(self._flags),
            "unready": self.get_unready_flags(),
            "total": len(self._flags),
            "ready_count": sum(1 for v in self._flags.values() if v),
        }

    def parse_epic_file(self, epic_file: str) -> EpicData:
        """Parse an Epic .md file and extract metadata."""
        path = Path(epic_file)
        content = path.read_text(encoding="utf-8")

        fm_match = YAML_FRONTMATTER_RE.match(content)
        if fm_match:
            try:
                import yaml
                data = yaml.safe_load(fm_match.group(1)) or {}
            except ImportError:
                from schema_validator import parse_yaml_frontmatter
                data = parse_yaml_frontmatter(fm_match.group(1))
        else:
            data = {}

        epic = EpicData(
            epic_id=data.get("epic_id", path.stem),
            schema_version=data.get("schema_version", "2.0"),
            title=data.get("title", ""),
            status=data.get("status", "DRAFT"),
            risk_level=data.get("risk_level", "R3"),
            owner=data.get("owner", "WorkBuddy"),
            tasks=data.get("tasks", []),
            readiness_flags=data.get("readiness_flags", {}),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
            filepath=str(path),
        )

        # Sync flags from epic file if they don't exist in results dir yet
        if epic.readiness_flags and not self._flags:
            for name, value in epic.readiness_flags.items():
                self._flags[name] = value
            self._save_flags()

        self._epic_data = epic
        return epic

    @property
    def flags(self) -> Dict[str, bool]:
        return dict(self._flags)

    @property
    def epic_data(self) -> Optional[EpicData]:
        return self._epic_data


# ---- CLI ----
def main():
    import argparse

    parser = argparse.ArgumentParser(description="Epic readiness_flags manager")
    parser.add_argument("results_dir", help="Path to .ai/results/<EPIC_ID>/")
    parser.add_argument("--epic-file", help="Path to epic .md file for initial parsing")
    sub = parser.add_subparsers(dest="command")

    # get
    get_parser = sub.add_parser("get", help="Get flag value")
    get_parser.add_argument("flag", help="Flag name")

    # set
    set_parser = sub.add_parser("set", help="Set flag value")
    set_parser.add_argument("flag", help="Flag name")
    set_parser.add_argument("value", choices=["true", "false"], help="Flag value")

    # summary
    sub.add_parser("summary", help="Show flags summary")

    # check
    sub.add_parser("check", help="Check if all flags are ready (exit 0=yes, 1=no)")

    args = parser.parse_args()

    mgr = EpicManager(args.results_dir, epic_file=args.epic_file)

    if args.command == "get":
        val = mgr.get_flag(args.flag)
        if val is None:
            print(f"Flag '{args.flag}' not found")
            sys.exit(1)
        print(f"{args.flag}: {val}")

    elif args.command == "set":
        changed = mgr.set_flag(args.flag, args.value == "true")
        print(f"Set '{args.flag}' = {args.value} (changed: {changed})")

    elif args.command == "summary":
        summary = mgr.get_flags_summary()
        print(json.dumps(summary, indent=2, ensure_ascii=False))

    elif args.command == "check":
        if mgr.all_flags_ready():
            print(f"✓ Epic '{mgr.epic_id}': all flags ready")
            sys.exit(0)
        else:
            unready = mgr.get_unready_flags()
            print(f"✗ Epic '{mgr.epic_id}': {len(unready)} flags not ready")
            for f in unready:
                print(f"  - {f}")
            sys.exit(1)


if __name__ == "__main__":
    import sys
    main()
