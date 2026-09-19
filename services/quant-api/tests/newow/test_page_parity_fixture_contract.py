"""Contract checks for frozen, source-derived Newow page-parity witnesses."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "page-parity-20260919"
REQUIRED_FIELDS = {
    "case_id",
    "source_url",
    "source_sha256",
    "function_names",
    "surface",
    "clock_as_of",
    "input_sha256",
    "input",
    "expected",
    "allowed_adaptations",
}


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _cases() -> list[dict[str, object]]:
    return [json.loads(path.read_text()) for path in sorted(FIXTURE_ROOT.glob("*.json"))]


def test_fixture_provenance_expected_and_input_identity_are_present() -> None:
    cases = _cases()
    assert cases, "No frozen parity witnesses"
    assert not (missing := REQUIRED_FIELDS - set().union(*(case.keys() for case in cases)))
    assert not (duplicates := [case_id for case_id, count in Counter(case["case_id"] for case in cases).items() if count > 1]), duplicates
    for case in cases:
        assert len(case["source_sha256"]) == 64
        assert len(case["input_sha256"]) == 64
        assert case["function_names"] and case["surface"]
        assert case["expected"], f"{case['case_id']} has no source-derived expected output"
        assert case["expected"].get("status") != "PASS", f"{case['case_id']} cannot turn missing data into parity PASS"
        assert case["input_sha256"] == _canonical_sha256(case["input"])
