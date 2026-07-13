#!/usr/bin/env python3
"""
schema_validator.py — JSON Schema validation for V2 Task/Epic YAML frontmatter.

Usage:
    python schema_validator.py <task_file.md>
    python schema_validator.py --epic <epic_file.md>

Exit codes:
    0 = valid
    1 = parse error (no YAML, bad YAML, unknown version)
    2 = schema validation error
    3 = usage error
"""

import json
import re
import sys
import os
from pathlib import Path
from typing import Optional, Dict, Any, Tuple, List

try:
    import jsonschema
    from jsonschema import validate, ValidationError
except ImportError:
    jsonschema = None


# __file__ = scripts/ai/lib/schema_validator.py
# parent = lib, parent.parent = ai, parent.parent.parent = scripts, parent.parent.parent.parent = repo root
SCHEMA_DIR = Path(__file__).resolve().parent.parent.parent.parent / "configs" / "ai" / "schemas"
TASK_SCHEMA_PATH = SCHEMA_DIR / "task-v2.0.schema.json"
EPIC_SCHEMA_PATH = SCHEMA_DIR / "epic-v2.0.schema.json"

YAML_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _ensure_jsonschema():
    if jsonschema is None:
        print("ERROR: jsonschema library not installed. Run: pip install jsonschema", file=sys.stderr)
        sys.exit(3)


def load_schema(schema_path: Path) -> dict:
    """Load a JSON Schema file."""
    with open(schema_path, "r", encoding="utf-8") as f:
        return json.load(f)


def extract_yaml_frontmatter(content: str) -> Optional[str]:
    """Extract the YAML frontmatter block from a markdown file."""
    match = YAML_FRONTMATTER_RE.match(content)
    if not match:
        return None
    return match.group(1)


def parse_yaml_frontmatter(yaml_text: str) -> dict:
    """Parse YAML frontmatter text into a Python dict."""
    try:
        import yaml
        return yaml.safe_load(yaml_text) or {}
    except ImportError:
        # Fallback: minimal YAML parser for our known subset
        return _minimal_yaml_parse(yaml_text)


def _minimal_yaml_parse(yaml_text: str) -> dict:
    """Minimal YAML parser for flat key: value and list items. Raises on complex structures."""
    result = {}
    current_key = None
    current_list = None

    for line in yaml_text.split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        # End current list if indentation decreases
        if current_list is not None and not line.startswith("  -") and not line.startswith("  "):
            result[current_key] = current_list
            current_list = None
            current_key = None

        # Key: value
        if ":" in stripped and not stripped.startswith("-"):
            # Check if it's a key: value line (not nested in list)
            if current_list is not None:
                continue
            key, _, value = stripped.partition(":")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if value == "":
                continue
            # Try type coercion
            if value in ("true", "True"):
                result[key] = True
            elif value in ("false", "False"):
                result[key] = False
            elif value.isdigit():
                result[key] = int(value)
            else:
                result[key] = value
            current_key = None
            current_list = None

        # List item
        elif stripped.startswith("- "):
            item = stripped[2:].strip().strip('"').strip("'")
            if current_list is None:
                # New list — find the key from previous line is difficult with minimal parser
                # We need to find the key. Let's look backwards.
                current_list = [item]
                # Try to infer key from context
                for prev_line in reversed(yaml_text.split("\n")[:yaml_text.split("\n").index(line)]):
                    p = prev_line.strip()
                    if ":" in p and not p.startswith("-"):
                        pk = p.split(":")[0].strip()
                        if pk not in result or not isinstance(result.get(pk), list):
                            current_key = pk
                        break
            else:
                current_list.append(item)

    # Flush last list
    if current_list is not None and current_key is not None:
        result[current_key] = current_list

    return result


def validate_task(data: dict) -> Tuple[bool, List[str]]:
    """Validate a Task dict against the V2.0 schema. Returns (valid, errors)."""
    return _validate_against_schema(data, TASK_SCHEMA_PATH, "Task")


def validate_epic(data: dict) -> Tuple[bool, List[str]]:
    """Validate an Epic dict against the V2.0 schema. Returns (valid, errors)."""
    return _validate_against_schema(data, EPIC_SCHEMA_PATH, "Epic")


def _validate_against_schema(data: dict, schema_path: Path, kind_label: str) -> Tuple[bool, List[str]]:
    """Validate data against a JSON Schema file."""
    _ensure_jsonschema()

    if not schema_path.exists():
        return False, [f"Schema file not found: {schema_path}"]

    try:
        schema = load_schema(schema_path)
    except json.JSONDecodeError as e:
        return False, [f"Invalid JSON Schema: {e}"]

    # Enforce kind
    if data.get("kind") != kind_label:
        return False, [f"Expected kind='{kind_label}', got '{data.get('kind')}'"]

    errors = []
    try:
        validate(instance=data, schema=schema)
    except ValidationError as e:
        # Collect all validation errors
        err = e
        while err is not None:
            path = ".".join(str(p) for p in err.absolute_path) if err.absolute_path else "(root)"
            errors.append(f"{path}: {err.message}")
            err = err.context[0] if err.context else None

    return len(errors) == 0, errors


def validate_file(filepath: str, epic_mode: bool = False) -> Tuple[bool, List[str]]:
    """
    Full validate pipeline for a task/epic markdown file:
    1. Read file
    2. Extract YAML frontmatter
    3. Parse YAML → dict
    4. Validate against schema

    Returns (valid, error_messages).
    """
    path = Path(filepath)
    if not path.exists():
        return False, [f"File not found: {filepath}"]

    content = path.read_text(encoding="utf-8")

    yaml_text = extract_yaml_frontmatter(content)
    if yaml_text is None:
        return False, ["No YAML frontmatter found. File must start with '---' block."]

    try:
        data = parse_yaml_frontmatter(yaml_text)
    except Exception as e:
        return False, [f"YAML parse error: {e}"]

    if not isinstance(data, dict):
        return False, ["YAML frontmatter did not produce a dict/mapping"]

    # Detect kind if not explicitly provided (fallback to schema_version presence)
    if "kind" not in data:
        if "epic_id" in data and "task_id" not in data:
            data["kind"] = "Epic"
        else:
            data["kind"] = "Task"

    if epic_mode or data.get("kind") == "Epic":
        return validate_epic(data)
    else:
        return validate_task(data)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Validate V2 Task/Epic YAML frontmatter")
    parser.add_argument("file", nargs="?", help="Path to task/epic .md file")
    parser.add_argument("--epic", action="store_true", help="Validate as Epic instead of Task")
    parser.add_argument("--schema-dir", help="Custom schema directory path")
    args = parser.parse_args()

    global SCHEMA_DIR
    if args.schema_dir:
        SCHEMA_DIR = Path(args.schema_dir)
        global TASK_SCHEMA_PATH, EPIC_SCHEMA_PATH
        TASK_SCHEMA_PATH = SCHEMA_DIR / "task-v2.0.schema.json"
        EPIC_SCHEMA_PATH = SCHEMA_DIR / "epic-v2.0.schema.json"

    if not args.file:
        parser.print_help()
        sys.exit(3)

    valid, errors = validate_file(args.file, epic_mode=args.epic)

    if valid:
        print(f"✓ Valid: {args.file}")
        sys.exit(0)
    else:
        print(f"✗ Invalid: {args.file}")
        for err in errors:
            print(f"  - {err}")
        sys.exit(2)


if __name__ == "__main__":
    main()
