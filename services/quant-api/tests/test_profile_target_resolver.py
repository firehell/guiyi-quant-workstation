from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path

from app.services.profile_target_resolver import ProfileEvidencePaths, resolve_profile_targets


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def test_resolve_intraday_targets_uses_audit_v2_and_marks_lineage() -> None:
    root = Path("/tmp/profile-target-resolver-intraday")
    expected = root / "expected.csv"
    _write_csv(
        expected,
        [
            {
                "product": "a",
                "contract_role": "dominant_main",
                "period": "1m",
                "source_role": "direct",
                "target_start": "2010-01-04",
                "target_end": "2026-07-10",
                "boundary_status": "start_boundary_supported",
            },
            {
                "product": "a",
                "contract_role": "dominant_main",
                "period": "5m",
                "source_role": "derived_from_1m",
                "target_start": "2010-01-04",
                "target_end": "2026-07-10",
                "boundary_status": "start_boundary_supported",
            },
        ],
    )
    config = {
        "target_policy": {
            "rules": [
                {
                    "source": "audit_v2_expected_windows",
                    "contract_role": "dominant_main",
                    "periods": ["1m"],
                    "source_role": "direct",
                },
                {
                    "source": "audit_v2_expected_windows",
                    "contract_role": "dominant_main",
                    "periods": ["5m"],
                    "source_role": "derived_from_1m",
                    "lineage_required": True,
                },
            ]
        }
    }

    result = resolve_profile_targets(
        profile_id="intraday_research_v1",
        config=config,
        evidence_paths=ProfileEvidencePaths(expected_windows=expected),
        products={"a"},
    )

    assert result.issues == ()
    one_minute = result.windows[("a", "a.MAIN", "1m")]
    five_minute = result.windows[("a", "a.MAIN", "5m")]
    assert one_minute.target_start == date(2010, 1, 4)
    assert five_minute.lineage_required is True


def test_resolve_actual_targets_keeps_disjoint_rank1_ranges() -> None:
    root = Path("/tmp/profile-target-resolver-actual")
    actual = root / "actual.csv"
    _write_csv(
        actual,
        [
            {
                "product": "jm",
                "contract": "JM2501",
                "period": "1d",
                "start_date": "2024-08-16",
                "end_date": "2024-12-01",
                "status": "covered",
            },
            {
                "product": "jm",
                "contract": "JM2501",
                "period": "1d",
                "start_date": "2025-01-02",
                "end_date": "2025-01-10",
                "status": "covered",
            },
        ],
    )
    config = {
        "target_policy": {
            "rules": [
                {
                    "source": "actual_target_coverage",
                    "contract_role": "actual_contract",
                    "periods": ["1d"],
                    "required_status": "covered",
                }
            ]
        }
    }

    result = resolve_profile_targets(
        profile_id="long_horizon_daily_v1",
        config=config,
        evidence_paths=ProfileEvidencePaths(actual_target_coverage=actual),
        products={"jm"},
    )

    window = result.windows[("jm", "JM2501", "1d")]
    assert [(item.start, item.end) for item in window.ranges] == [
        (date(2024, 8, 16), date(2024, 12, 1)),
        (date(2025, 1, 2), date(2025, 1, 10)),
    ]


def test_missing_target_boundary_is_reported_fail_closed() -> None:
    root = Path("/tmp/profile-target-resolver-missing")
    expected = root / "expected.csv"
    _write_csv(
        expected,
        [
            {
                "product": "jm",
                "contract_role": "dominant_main",
                "period": "1m",
                "source_role": "direct",
                "target_start": "",
                "target_end": "2026-07-10",
                "boundary_status": "start_boundary_unverified",
            }
        ],
    )
    config = {
        "target_policy": {
            "rules": [
                {
                    "source": "audit_v2_expected_windows",
                    "contract_role": "dominant_main",
                    "periods": ["1m"],
                    "source_role": "direct",
                }
            ]
        }
    }

    result = resolve_profile_targets(
        profile_id="intraday_research_v1",
        config=config,
        evidence_paths=ProfileEvidencePaths(expected_windows=expected),
        products={"jm"},
    )

    assert result.windows == {}
    assert result.issues[0].reason == "missing_target_boundary"


def test_profile_configs_freeze_full_history_and_live_semantics() -> None:
    configs = {
        path.stem: json.loads(path.read_text(encoding="utf-8"))
        for path in (PROJECT_ROOT / "configs" / "data_profiles").glob("*.json")
    }
    intraday = configs["intraday_research_v1"]
    long_horizon = configs["long_horizon_daily_v1"]
    live = configs["live_observation_v1"]

    assert intraday["semantic_version"] == "full_history_target_aware_v1"
    assert intraday["pilots"] == []
    assert intraday["frozen_baselines"]["report_14_reference"]["selection_eligible"] is False
    intraday_actual = next(
        rule for rule in intraday["target_policy"]["rules"] if rule["contract_role"] == "actual_contract"
    )
    live_actual = next(
        rule for rule in live["target_policy"]["rules"] if rule["contract_role"] == "actual_contract"
    )
    assert intraday_actual["periods"] == ["1m", "5m", "15m"]
    assert live_actual["periods"] == ["1m", "5m", "15m"]
    assert "2020+" not in long_horizon["description"]
    assert any(
        rule["source"] == "actual_target_coverage"
        for rule in long_horizon["target_policy"]["rules"]
    )
    assert live["trusted_backtest"] is False
    assert live["live_historical_separated"] is True
    assert live["live_tables_only_periods"] == ["30m", "60m", "1d", "1w"]
