from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import app.research.robustness.jdj_robustness as robustness
from app.core.env import PROJECT_ROOT
from app.research.robustness.jdj_robustness import (
    JdjActive60RobustnessReport,
    JdjActive60RobustnessProtocolError,
    JdjActive60RobustnessRequest,
    JdjRobustnessHorizonSummary,
    JdjRobustnessSectorHorizonSummary,
    JdjRobustnessSectorSummary,
    JdjRobustnessStatus,
    JdjRobustnessSymbolResult,
    JdjRobustnessYearSummary,
    load_jdj_active60_robustness_protocol,
)


PRODUCTS = (
    "a", "ag", "al", "ao", "ap", "au", "b", "bu", "bz", "c",
    "cf", "cj", "cu", "eb", "ec", "eg", "fg", "fu", "hc", "i",
    "j", "jd", "jm", "l", "lc", "lh", "m", "ma", "ni", "oi",
    "p", "pb", "pd", "pf", "pg", "pk", "pl", "pp", "pr", "ps",
    "pt", "px", "rb", "rm", "rs", "ru", "sa", "sc", "sf", "sh",
    "si", "sm", "sn", "sr", "ss", "ta", "ur", "v", "y", "zn",
)
SECTOR_GROUPS = {
    "agriculture": (
        "a", "ap", "b", "c", "cf", "cj", "jd", "lh", "m", "oi",
        "p", "pk", "rm", "rs", "sr", "y",
    ),
    "precious": ("ag", "au", "pd", "pt"),
    "nonferrous": ("al", "ao", "cu", "ni", "pb", "sn", "zn"),
    "energy": ("bu", "fu", "pg", "sc"),
    "chemical": (
        "bz", "eb", "eg", "l", "ma", "pf", "pl", "pp", "pr", "px",
        "ru", "sh", "ta", "ur", "v",
    ),
    "other": ("ec",),
    "building": ("fg", "sa"),
    "steel": ("hc", "rb", "ss"),
    "black": ("i", "j", "jm", "sf", "sm"),
    "new_energy": ("lc", "ps", "si"),
}
CANDIDATES = (
    "jdj_trend_follow_1m_candidate_v1",
    "jdj_trend_reentry_6_1m_candidate_v1",
    "jdj_key_level_breakout_1m_candidate_v1",
)


def test_phase7_protocol_is_exact_and_does_not_consume_oos() -> None:
    protocol = load_jdj_active60_robustness_protocol()

    assert protocol.protocol_id == "jdj_active60_robustness_v1"
    assert protocol.research_only is True
    assert protocol.readonly is True
    assert protocol.common_since == date(2023, 1, 1)
    assert protocol.common_through == date(2026, 8, 20)
    assert protocol.embargo_trading_days == (date(2026, 8, 21),)
    assert protocol.prospective_first_trading_day == date(2026, 8, 24)
    assert protocol.prospective_consumed is False
    assert protocol.horizons_bars == (3, 5, 8, 20)
    assert protocol.candidate_ids == CANDIDATES
    assert protocol.cross_symbol_products == PRODUCTS
    assert protocol.sector_groups == SECTOR_GROUPS
    assert tuple(
        symbol
        for symbol in protocol.cross_symbol_products
        if symbol in protocol.sector_groups["chemical"]
    ) == protocol.sector_groups["chemical"]


def test_phase7_request_rejects_any_other_protocol() -> None:
    assert JdjActive60RobustnessRequest(
        protocol_id="jdj_active60_robustness_v1"
    ).protocol_id == "jdj_active60_robustness_v1"

    with pytest.raises(
        JdjActive60RobustnessProtocolError,
        match="JDJ_ACTIVE60_ROBUSTNESS_PROTOCOL_INVALID",
    ):
        JdjActive60RobustnessRequest(protocol_id="multi_candidate_robustness_v1")


@pytest.mark.parametrize(
    "mutation",
    (
        "extra_field",
        "candidate_order",
        "product_order",
        "sector_member_order",
        "retrospective_through",
        "prospective_consumed",
    ),
)
def test_phase7_protocol_shape_value_and_order_drift_fail_closed(
    tmp_path: Path,
    mutation: str,
) -> None:
    source = PROJECT_ROOT / "data/research_protocols/jdj_active60_robustness_v1.json"
    payload = json.loads(source.read_text(encoding="utf-8"))
    mutated = deepcopy(payload)
    if mutation == "extra_field":
        mutated["threshold"] = 1
    elif mutation == "candidate_order":
        mutated["candidate_ids"].reverse()
    elif mutation == "product_order":
        mutated["cross_symbol_products"][0:2] = reversed(
            mutated["cross_symbol_products"][0:2]
        )
    elif mutation == "sector_member_order":
        mutated["sector_groups"]["agriculture"][0:2] = reversed(
            mutated["sector_groups"]["agriculture"][0:2]
        )
    elif mutation == "retrospective_through":
        mutated["common_retrospective"]["through"] = "2026-08-21"
    else:
        mutated["prospective_consumed"] = True
    path = tmp_path / f"{mutation}.json"
    path.write_text(json.dumps(mutated), encoding="utf-8")

    with pytest.raises(JdjActive60RobustnessProtocolError):
        load_jdj_active60_robustness_protocol(path)


def test_phase7_protocol_rejects_current_active_or_taxonomy_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        robustness,
        "load_active_products",
        lambda: tuple(reversed(PRODUCTS)),
    )
    with pytest.raises(JdjActive60RobustnessProtocolError):
        load_jdj_active60_robustness_protocol()

    monkeypatch.setattr(robustness, "load_active_products", lambda: PRODUCTS)
    taxonomy = robustness.load_product_taxonomy()
    drifted = dict(taxonomy)
    drifted["a"] = SimpleNamespace(name="豆一", sector="other")
    monkeypatch.setattr(robustness, "load_product_taxonomy", lambda: drifted)
    with pytest.raises(JdjActive60RobustnessProtocolError):
        load_jdj_active60_robustness_protocol()


def test_phase7_protocol_rejects_jdj_validation_protocol_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current = robustness.load_jdj_candidate_validation_protocol()
    monkeypatch.setattr(
        robustness,
        "load_jdj_candidate_validation_protocol",
        lambda: SimpleNamespace(
            retrospective_since=current.retrospective_since,
            retrospective_through=date(2026, 8, 21),
            embargo_trading_days=current.embargo_trading_days,
            prospective_oos_first_trading_day=(
                current.prospective_oos_first_trading_day
            ),
            horizons_bars=current.horizons_bars,
            candidates=current.candidates,
        ),
    )

    with pytest.raises(JdjActive60RobustnessProtocolError):
        load_jdj_active60_robustness_protocol()


def _zero_horizons() -> dict[int, JdjRobustnessHorizonSummary]:
    return {
        horizon: JdjRobustnessHorizonSummary(
            sample_count=0,
            historical_positive_outcome_rate=None,
            median_directional_return_bps=None,
            median_mfe_bps=None,
            median_mae_bps=None,
        )
        for horizon in (3, 5, 8, 20)
    }


def _zero_years() -> dict[int, JdjRobustnessYearSummary]:
    return {
        year: JdjRobustnessYearSummary(
            event_count=0,
            horizon_sample_count={horizon: 0 for horizon in (3, 5, 8, 20)},
            horizon_positive_outcome_rate={
                horizon: None for horizon in (3, 5, 8, 20)
            },
            horizon_median_directional_return_bps={
                horizon: None for horizon in (3, 5, 8, 20)
            },
        )
        for year in (2023, 2024, 2025, 2026)
    }


def _available(candidate_id: str, symbol: str) -> JdjRobustnessSymbolResult:
    sector = next(
        sector for sector, symbols in SECTOR_GROUPS.items() if symbol in symbols
    )
    return JdjRobustnessSymbolResult(
        candidate_id=candidate_id,
        symbol=symbol,
        sector=sector,
        status=JdjRobustnessStatus.AVAILABLE,
        reason_code=None,
        observed_since=date(2023, 1, 1),
        observed_through=date(2026, 8, 20),
        evaluable_bar_count=0,
        event_count=0,
        long_event_count=0,
        short_event_count=0,
        event_rate_per_1000_evaluable=None,
        horizon_summary=_zero_horizons(),
        yearly=_zero_years(),
    )


def _unavailable(candidate_id: str, symbol: str) -> JdjRobustnessSymbolResult:
    sector = next(
        sector for sector, symbols in SECTOR_GROUPS.items() if symbol in symbols
    )
    return JdjRobustnessSymbolResult(
        candidate_id=candidate_id,
        symbol=symbol,
        sector=sector,
        status=JdjRobustnessStatus.UNAVAILABLE,
        reason_code="JDJ_SOURCE_UNAVAILABLE",
        observed_since=None,
        observed_through=None,
        evaluable_bar_count=None,
        event_count=None,
        long_event_count=None,
        short_event_count=None,
        event_rate_per_1000_evaluable=None,
        horizon_summary=None,
        yearly=None,
    )


def _sector_summary(
    candidate_id: str,
    sector: str,
) -> JdjRobustnessSectorSummary:
    symbol_count = len(SECTOR_GROUPS[sector])
    return JdjRobustnessSectorSummary(
        candidate_id=candidate_id,
        sector=sector,
        symbol_count=symbol_count,
        available_symbol_count=symbol_count,
        symbols_with_events=0,
        horizon_summary={
            horizon: JdjRobustnessSectorHorizonSummary(
                symbols_with_samples=0,
                positive_median_symbol_count=0,
                zero_median_symbol_count=0,
                negative_median_symbol_count=0,
                median_of_symbol_median_return_bps=None,
            )
            for horizon in (3, 5, 8, 20)
        },
    )


def _report(
    *,
    rows: tuple[JdjRobustnessSymbolResult, ...] | None = None,
    sectors: tuple[JdjRobustnessSectorSummary, ...] | None = None,
    quality_flags: tuple[str, ...] = (
        "SYMBOL_WITHOUT_EVENT",
        "HORIZON_WITHOUT_SAMPLE",
    ),
) -> JdjActive60RobustnessReport:
    return JdjActive60RobustnessReport(
        schema_version=1,
        command=(
            "guiyi research candidate-robustness "
            "--protocol jdj_active60_robustness_v1"
        ),
        protocol_id="jdj_active60_robustness_v1",
        frozen_at=datetime.fromisoformat("2026-08-21T20:34:00+08:00"),
        research_only=True,
        readonly=True,
        common_since=date(2023, 1, 1),
        common_through=date(2026, 8, 20),
        embargo_trading_days=(date(2026, 8, 21),),
        prospective_first_trading_day=date(2026, 8, 24),
        prospective_consumed=False,
        candidate_ids=CANDIDATES,
        cross_symbol_results=rows
        or tuple(
            _available(candidate_id, symbol)
            for candidate_id in CANDIDATES
            for symbol in PRODUCTS
        ),
        sector_summaries=sectors
        or tuple(
            _sector_summary(candidate_id, sector)
            for candidate_id in CANDIDATES
            for sector in SECTOR_GROUPS
        ),
        quality_flags=quality_flags,
    )


def test_report_requires_exact_180_candidate_major_product_order_rows() -> None:
    report = _report()

    assert len(report.cross_symbol_results) == 180
    assert tuple(
        (row.candidate_id, row.symbol) for row in report.cross_symbol_results
    ) == tuple(
        (candidate_id, symbol)
        for candidate_id in CANDIDATES
        for symbol in PRODUCTS
    )

    with pytest.raises(ValueError, match="JDJ_ACTIVE60_ROBUSTNESS_REPORT_INVALID"):
        _report(rows=report.cross_symbol_results[:-1])
    with pytest.raises(ValueError, match="JDJ_ACTIVE60_ROBUSTNESS_REPORT_INVALID"):
        _report(rows=tuple(reversed(report.cross_symbol_results)))


def test_unavailable_rows_keep_identity_reason_and_nullable_metrics() -> None:
    unavailable = _unavailable(CANDIDATES[0], PRODUCTS[0])
    rows = list(_report().cross_symbol_results)
    rows[0] = unavailable

    report = _report(
        rows=tuple(rows),
        quality_flags=(
            "SOURCE_UNAVAILABLE_PRESENT",
            "SYMBOL_WITHOUT_EVENT",
            "HORIZON_WITHOUT_SAMPLE",
        ),
    )

    assert report.cross_symbol_results[0] == unavailable
    assert report.cross_symbol_results[0].reason_code == "JDJ_SOURCE_UNAVAILABLE"
    assert report.cross_symbol_results[0].event_count is None
    assert report.cross_symbol_results[0].horizon_summary is None
    with pytest.raises(ValueError, match="JDJ_ACTIVE60_ROBUSTNESS_REPORT_INVALID"):
        replace(unavailable, event_count=0)


def test_available_zero_event_is_not_unavailable() -> None:
    row = _available(CANDIDATES[0], PRODUCTS[0])

    assert row.status is JdjRobustnessStatus.AVAILABLE
    assert row.event_count == 0
    assert row.reason_code is None


def test_zero_sample_forces_rate_and_all_medians_null() -> None:
    summary = _zero_horizons()[3]

    assert summary.sample_count == 0
    assert summary.historical_positive_outcome_rate is None
    assert summary.median_directional_return_bps is None
    assert summary.median_mfe_bps is None
    assert summary.median_mae_bps is None
    with pytest.raises(ValueError, match="JDJ_ACTIVE60_ROBUSTNESS_REPORT_INVALID"):
        replace(summary, historical_positive_outcome_rate=Decimal("0"))


def test_sector_sign_counts_must_sum_to_symbols_with_samples() -> None:
    summary = JdjRobustnessSectorHorizonSummary(
        symbols_with_samples=3,
        positive_median_symbol_count=1,
        zero_median_symbol_count=1,
        negative_median_symbol_count=1,
        median_of_symbol_median_return_bps=Decimal("0"),
    )

    assert (
        summary.positive_median_symbol_count
        + summary.zero_median_symbol_count
        + summary.negative_median_symbol_count
        == summary.symbols_with_samples
    )
    with pytest.raises(ValueError, match="JDJ_ACTIVE60_ROBUSTNESS_REPORT_INVALID"):
        replace(summary, negative_median_symbol_count=0)


def test_quality_flags_are_only_the_fixed_ordered_subset() -> None:
    assert _report(
        quality_flags=(
            "SOURCE_UNAVAILABLE_PRESENT",
            "SYMBOL_WITHOUT_EVENT",
            "HORIZON_WITHOUT_SAMPLE",
            "SHORT_HISTORY_PRESENT",
        )
    ).quality_flags == (
        "SOURCE_UNAVAILABLE_PRESENT",
        "SYMBOL_WITHOUT_EVENT",
        "HORIZON_WITHOUT_SAMPLE",
        "SHORT_HISTORY_PRESENT",
    )

    for invalid in (
        ("PASS",),
        ("SHORT_HISTORY_PRESENT", "SYMBOL_WITHOUT_EVENT"),
        ("SYMBOL_WITHOUT_EVENT", "SYMBOL_WITHOUT_EVENT"),
    ):
        with pytest.raises(
            ValueError,
            match="JDJ_ACTIVE60_ROBUSTNESS_REPORT_INVALID",
        ):
            _report(quality_flags=invalid)
