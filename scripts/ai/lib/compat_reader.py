#!/usr/bin/env python3
"""
compat_reader.py — Backward-compatible task reader for legacy markdown tasks.

Reads legacy tasks (no YAML frontmatter) and converts them to V2 TaskMeta-compatible
dicts by extracting fields from `## 0. 元信息` markdown table and/or the markdown body.

Decision tree (Plan §5.2):
    1. Has YAML frontmatter with schema_version "2.0" or "3.0" → parse directly
    2. Has YAML frontmatter with unknown version → raise error (fail-closed)
    3. No YAML frontmatter → legacy compat: extract from table, infer missing fields

Usage:
    from compat_reader import parse_task_file, LegacyTaskDict

    task_dict = parse_task_file("docs/tasks/archive/workstation-legacy/GUIYI-DEMO-001.md")
    print(task_dict["task_id"], task_dict["status"])
"""

import re
import sys
from pathlib import Path
from typing import Optional, Dict, Any, List

from risk_resolver import RiskLevel, resolve_risk_level
from status_machine import Status, map_legacy_status

# Regex patterns for extracting metadata from legacy task markdown
TABLE_ROW_RE = re.compile(r"^\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|", re.MULTILINE)
SECTION_RE = re.compile(r"^##\s+(\d+)\.",
    re.MULTILINE)
YAML_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


# Field name mapping: legacy table header → V2 key
LEGACY_FIELD_MAP: Dict[str, str] = {
    "task id": "task_id",
    "task_id": "task_id",
    "github issue": "github_issue",
    "github_issue": "github_issue",
    "branch": "branch",
    "status": "status",
    "risk level": "risk_level",
    "risk_level": "risk_level",
    "work level": "work_level",
    "work_level": "work_level",
    "approval scope": "approval_scope",
    "approval_scope": "approval_scope",
    "critical": "critical",
    "production write requested": "production_write_requested",
    "production_write_requested": "production_write_requested",
    "production write approved": "production_write_approved",
    "production_write_approved": "production_write_approved",
    "owner": "owner",
    "depends on": "depends_on",
    "depends_on": "depends_on",
    "allowed paths": "allowed_paths",
    "allowed_paths": "allowed_paths",
    "forbidden paths": "forbidden_paths",
    "forbidden_paths": "forbidden_paths",
    "required tests": "required_tests",
    "required_tests": "required_tests",
}


def extract_table_section(content: str, section_header: str = "0. 元信息") -> Optional[Dict[str, str]]:
    """Extract key-value pairs from a markdown table section."""
    # Find the section
    section_pattern = re.compile(rf"##\s+{re.escape(section_header)}\s*\n(.+?)(?=\n##\s|\Z)", re.DOTALL)
    match = section_pattern.search(content)
    if not match:
        return None

    section_text = match.group(1)
    result = {}

    for row_match in TABLE_ROW_RE.finditer(section_text):
        key = row_match.group(1).strip().lower()
        value = row_match.group(2).strip()
        if key in ("---", "----", ":---"):
            continue  # Skip separator rows
        if "---" in key and "---" in value:
            continue  # Skip separator
        result[key] = value

    return result


def extract_task_id_from_filename(filepath: str) -> Optional[str]:
    """Extract task ID from filename like 'TASK-2026-07-11-002-lean-v1-demo.md' or 'GUIYI-DEMO-001.md'."""
    name = Path(filepath).stem
    # Try patterns
    patterns = [
        r"^(TASK-\d{4}-\d{2}-\d{2}-\d{3}.+)",
        r"^([A-Z]+-\w+-\d{3})",
        r"^(WS-V2-\d{3})",
    ]
    for pattern in patterns:
        m = re.match(pattern, name)
        if m:
            return m.group(1)
    return name


def parse_legacy_task(content: str, filepath: str, body_text: str) -> Dict[str, Any]:
    """
    Parse a legacy task markdown file (no YAML frontmatter) into a V2-compatible dict.
    Missing V2 fields are inferred.
    """
    table = extract_table_section(content) or {}

    task_id = table.get("task id") or extract_task_id_from_filename(filepath)

    # Map legacy fields to V2
    result: Dict[str, Any] = {
        "kind": "Task",
        "schema_version": "2.0",
        "task_id": task_id,
    }

    for legacy_key, v2_key in LEGACY_FIELD_MAP.items():
        if v2_key in result:
            continue
        if legacy_key in table:
            value = table[legacy_key].strip()
            if value and value != "N/A" and value != "-":
                result[v2_key] = value

    # Map status
    if "status" in result:
        try:
            result["status"] = map_legacy_status(result["status"]).value
        except ValueError:
            pass  # Keep as-is if unmappable
    else:
        result["status"] = Status.DRAFT.value

    # Parse boolean fields
    for bool_field in ("critical", "production_write_requested", "production_write_approved"):
        if bool_field in result:
            val = str(result[bool_field]).lower()
            result[bool_field] = val in ("true", "yes", "是", "1")

    # Parse list fields
    for list_field in ("depends_on", "allowed_paths", "forbidden_paths", "required_tests", "resource_locks", "approval_scope"):
        if list_field in result:
            val = result[list_field]
            if isinstance(val, str):
                # Split by comma or newline
                if "," in val:
                    result[list_field] = [x.strip() for x in val.split(",") if x.strip()]
                elif "\n" in val:
                    result[list_field] = [x.strip() for x in val.split("\n") if x.strip()]
                else:
                    result[list_field] = [val] if val else []

    # Parse work_level from table (might be "L0" / "L1" / "L2")
    if "work_level" not in result:
        result["work_level"] = "L2"  # Default

    # Parse github_issue
    if "github_issue" in result:
        val = str(result["github_issue"])
        if not val.startswith("#"):
            result["github_issue"] = f"#{val}" if val.isdigit() else val

    # Risk level: if explicit, use it; otherwise infer
    if "risk_level" not in result:
        allowed_paths = result.get("allowed_paths", [])
        forbidden_paths = result.get("forbidden_paths", [])
        resolution = resolve_risk_level(
            task_id=task_id,
            explicit_risk=None,
            allowed_paths=allowed_paths if allowed_paths else None,
            forbidden_paths=forbidden_paths if forbidden_paths else None,
            body_text=body_text,
        )
        result["risk_level"] = resolution.resolved_level.value

    # Default approval_scope
    if "approval_scope" not in result or not result["approval_scope"]:
        result["approval_scope"] = ["plan", "code"]

    # Defaults for optional fields
    result.setdefault("critical", False)
    result.setdefault("production_write_requested", False)
    result.setdefault("production_write_approved", False)
    result.setdefault("owner", "WorkBuddy")
    result.setdefault("depends_on", [])
    result.setdefault("allowed_paths", [])
    result.setdefault("forbidden_paths", [])
    result.setdefault("resource_locks", [])
    result.setdefault("required_tests", [])
    result.setdefault("model_profile", "standard")
    result.setdefault("github_issue", "")
    result.setdefault("branch", "")
    result.setdefault("worktree", "")

    return result


def parse_task_file(filepath: str) -> Dict[str, Any]:
    """
    Parse a task file (V2 YAML frontmatter or legacy markdown) into a V2 dict.

    Returns a dict with all V2 Task fields.
    Raises ValueError on unsupported schema_version.
    """
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"Task file not found: {filepath}")

    content = path.read_text(encoding="utf-8")

    # Try YAML frontmatter first
    fm_match = YAML_FRONTMATTER_RE.match(content)
    if fm_match:
        try:
            import yaml
            data = yaml.safe_load(fm_match.group(1)) or {}
        except ImportError:
            # Fallback to minimal parser in schema_validator
            from schema_validator import parse_yaml_frontmatter
            data = parse_yaml_frontmatter(fm_match.group(1))

        if not isinstance(data, dict):
            raise ValueError(f"YAML frontmatter in {filepath} did not produce a dict")

        schema_ver = data.get("schema_version", "")
        if schema_ver in {"2.0", "3.0"}:
            # V2/V3 task — use as-is but ensure required fields
            result = dict(data)
            result.setdefault("kind", "Task" if "task_id" in data else "Epic")
            result.setdefault("depends_on", [])
            result.setdefault("allowed_paths", [])
            result.setdefault("forbidden_paths", [])
            result.setdefault("resource_locks", [])
            result.setdefault("required_tests", [])
            result.setdefault("model_profile", "standard")
            result.setdefault("critical", False)
            result.setdefault("production_write_requested", False)
            result.setdefault("production_write_approved", False)
            result.setdefault("owner", "WorkBuddy")
            result.setdefault("github_issue", "")
            result.setdefault("github_pr", "")
            result.setdefault("branch", "")
            result.setdefault("worktree", "")
            return result
        else:
            raise ValueError(
                f"Unsupported schema_version '{schema_ver}' in {filepath}. "
                f"Only '2.0' and '3.0' are supported (fail-closed)."
            )

    # No YAML frontmatter — legacy parse
    body_text = YAML_FRONTMATTER_RE.sub("", content) if YAML_FRONTMATTER_RE.match(content) else content
    return parse_legacy_task(content, filepath, body_text)


def parse_task_files_batch(filepaths: List[str]) -> List[Dict[str, Any]]:
    """Parse multiple task files. Errors are collected and reported but don't stop the batch."""
    results = []
    errors = []

    for fp in filepaths:
        try:
            results.append(parse_task_file(fp))
        except Exception as e:
            errors.append({"file": fp, "error": str(e)})
            print(f"WARNING: Failed to parse {fp}: {e}", file=sys.stderr)

    return results, errors


# ---- CLI ----
def main():
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Parse task file (V2 YAML or legacy markdown)")
    parser.add_argument("file", help="Path to task .md file")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        data = parse_task_file(args.file)
        if args.json:
            print(json.dumps(data, indent=2, ensure_ascii=False, default=str))
        else:
            print(f"task_id:       {data.get('task_id', 'N/A')}")
            print(f"status:        {data.get('status', 'N/A')}")
            print(f"risk_level:    {data.get('risk_level', 'N/A')}")
            print(f"work_level:    {data.get('work_level', 'N/A')}")
            print(f"approval_scope: {data.get('approval_scope', [])}")
            print(f"depends_on:    {data.get('depends_on', [])}")
            print(f"schema_version: {data.get('schema_version', 'legacy')}")
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
