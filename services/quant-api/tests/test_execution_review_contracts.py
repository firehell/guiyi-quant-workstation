from __future__ import annotations

import csv
from datetime import date
from decimal import Decimal
from pathlib import Path
import re
from urllib.parse import urlparse

import pytest

from app.execution_review.contracts import (
    ExecutionReviewContractError,
    load_product_trade_multipliers,
    validate_execution_reasons,
    validate_not_executed,
    validate_review,
)
from app.market_data.operational_universe import load_active_products


def test_not_executed_requires_primary_reason() -> None:
    with pytest.raises(ExecutionReviewContractError, match="PRIMARY_REASON_REQUIRED"):
        validate_not_executed(primary_reason=None, secondary_reasons=(), note=None)


def test_other_reason_requires_note() -> None:
    with pytest.raises(ExecutionReviewContractError, match="OTHER_NOTE_REQUIRED"):
        validate_not_executed(
            primary_reason="OTHER",
            secondary_reasons=(),
            note="  ",
        )


def test_secondary_reasons_are_unique_and_exclude_primary() -> None:
    with pytest.raises(ExecutionReviewContractError, match="SECONDARY_REASON_DUPLICATE"):
        validate_not_executed(
            primary_reason="TOO_LATE",
            secondary_reasons=("POOR_LOCATION", "POOR_LOCATION"),
            note=None,
        )

    with pytest.raises(ExecutionReviewContractError, match="SECONDARY_REASON_PRIMARY"):
        validate_not_executed(
            primary_reason="TOO_LATE",
            secondary_reasons=("TOO_LATE",),
            note=None,
        )


def test_executed_requires_at_least_one_reason() -> None:
    with pytest.raises(ExecutionReviewContractError, match="EXECUTION_REASON_REQUIRED"):
        validate_execution_reasons(())


def test_unknown_reason_or_review_tag_is_rejected() -> None:
    with pytest.raises(ExecutionReviewContractError, match="UNKNOWN_DECISION_REASON"):
        validate_not_executed(
            primary_reason="MADE_UP",
            secondary_reasons=(),
            note=None,
        )


@pytest.mark.parametrize(
    ("validator", "value", "code"),
    [
        ("primary", " TOO_LATE ", "UNKNOWN_DECISION_REASON"),
        ("secondary", " POOR_LOCATION ", "UNKNOWN_DECISION_REASON"),
        ("execution", " LOCATION_ACCEPTABLE ", "UNKNOWN_EXECUTION_REASON"),
        ("review", " REASONABLE ", "UNKNOWN_REVIEW_TAG"),
    ],
)
def test_fixed_vocabularies_reject_non_exact_literals(
    validator: str,
    value: str,
    code: str,
) -> None:
    with pytest.raises(ExecutionReviewContractError, match=code):
        if validator == "primary":
            validate_not_executed(
                primary_reason=value,
                secondary_reasons=(),
                note=None,
            )
        elif validator == "secondary":
            validate_not_executed(
                primary_reason="TOO_LATE",
                secondary_reasons=(value,),
                note=None,
            )
        elif validator == "execution":
            validate_execution_reasons((value,))
        else:
            validate_review(
                signal_execution_adherence="ALIGNED",
                entry_tags=(value,),
                holding_tags=("NORMAL",),
                exit_tags=("NORMAL",),
                market_context_tags=("TREND",),
                psychology_tags=("NONE",),
            )

    with pytest.raises(ExecutionReviewContractError, match="UNKNOWN_EXECUTION_REASON"):
        validate_execution_reasons(("MADE_UP",))

    with pytest.raises(ExecutionReviewContractError, match="UNKNOWN_REVIEW_TAG"):
        validate_review(
            signal_execution_adherence="ALIGNED",
            entry_tags=("MADE_UP",),
            holding_tags=("NORMAL",),
            exit_tags=("NORMAL",),
            market_context_tags=("TREND",),
            psychology_tags=("NONE",),
        )


@pytest.mark.parametrize(
    ("group", "values"),
    [
        ("entry_tags", ("REASONABLE", "TOO_LATE")),
        ("holding_tags", ("NORMAL", "UNPLANNED_ADD")),
        ("exit_tags", ("NORMAL", "STOP_DELAYED")),
        ("psychology_tags", ("NONE", "HESITATION")),
    ],
)
def test_review_normal_tags_are_mutually_exclusive(
    group: str,
    values: tuple[str, ...],
) -> None:
    payload = {
        "entry_tags": ("REASONABLE",),
        "holding_tags": ("NORMAL",),
        "exit_tags": ("NORMAL",),
        "market_context_tags": ("TREND",),
        "psychology_tags": ("NONE",),
    }
    payload[group] = values

    with pytest.raises(ExecutionReviewContractError, match="REVIEW_TAG_CONFLICT"):
        validate_review(signal_execution_adherence="ALIGNED", **payload)


def test_review_requires_every_structured_group() -> None:
    with pytest.raises(ExecutionReviewContractError, match="REVIEW_TAG_REQUIRED"):
        validate_review(
            signal_execution_adherence="ALIGNED",
            entry_tags=("REASONABLE",),
            holding_tags=("NORMAL",),
            exit_tags=("NORMAL",),
            market_context_tags=(),
            psychology_tags=("NONE",),
        )


def test_multiplier_loader_normalizes_and_returns_missing_as_none(
    tmp_path: Path,
) -> None:
    path = tmp_path / "multipliers.csv"
    path.write_text("product,multiplier\n JM ,60\nec,50\n", encoding="utf-8")

    loaded = load_product_trade_multipliers(path)

    assert loaded == {"jm": Decimal("60"), "ec": Decimal("50")}
    assert all(isinstance(value, Decimal) for value in loaded.values())
    assert loaded.get("rb") is None


@pytest.mark.parametrize(
    "content",
    [
        "symbol,multiplier\njm,60\n",
        "product,multiplier\njm,60\nJM,60\n",
        "product,multiplier\njm,0\n",
        "product,multiplier\njm,-1\n",
        "product,multiplier\njm,NaN\n",
        "product,multiplier\njm,not-a-number\n",
        "product,multiplier\n,60\n",
    ],
)
def test_multiplier_loader_fails_closed_for_malformed_reference(
    tmp_path: Path,
    content: str,
) -> None:
    path = tmp_path / "multipliers.csv"
    path.write_text(content, encoding="utf-8")

    with pytest.raises(ExecutionReviewContractError, match="MULTIPLIER_REFERENCE_INVALID"):
        load_product_trade_multipliers(path)


def test_tracked_multiplier_reference_and_official_evidence_cover_active_universe() -> None:
    project_root = Path(__file__).resolve().parents[3]
    reference = load_product_trade_multipliers(
        project_root / "data/reference/product_trade_multipliers.csv"
    )
    evidence_path = (
        project_root / "data/reference/product_trade_multipliers.sources.csv"
    )
    with evidence_path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames == [
            "product",
            "exchange",
            "source_kind",
            "official_source_title",
            "official_source_url",
            "source_effective_date",
            "effective_scope",
            "verified_on",
            "quote_unit",
            "trading_unit_or_contract_multiplier",
            "derived_multiplier",
            "artifact_sha256",
            "derivation_note",
        ]
        evidence_rows = list(reader)

    active = set(load_active_products())
    evidence_products = [row["product"] for row in evidence_rows]

    assert len(active) == 60
    assert len(evidence_products) == len(set(evidence_products))
    assert set(reference) == set(evidence_products)
    assert set(reference) <= active
    assert all(multiplier > 0 for multiplier in reference.values())

    allowed_hosts = {
        "SHFE": {"www.shfe.com.cn", "shfe.com.cn"},
        "INE": {"www.ine.cn", "ine.cn"},
        "DCE": {"www.dce.com.cn", "dce.com.cn"},
        "CZCE": {"www.czce.com.cn", "czce.com.cn"},
        "GFEX": {"www.gfex.com.cn", "gfex.com.cn"},
    }
    allowed_source_kinds = {
        "exchange_html",
        "exchange_attachment",
        "regulator_official_mirror",
    }
    exchange_products = {
        "SHFE": {
            "ag", "al", "ao", "au", "bu", "cu", "fu", "hc", "ni", "pb",
            "rb", "ru", "sn", "ss", "zn",
        },
        "INE": {"ec", "sc"},
        "DCE": {
            "a", "b", "bz", "c", "eb", "eg", "i", "j", "jd", "jm", "l",
            "lh", "m", "p", "pg", "pp", "v", "y",
        },
        "CZCE": {
            "ap", "cf", "cj", "fg", "ma", "oi", "pf", "pk", "pl", "pr",
            "px", "rm", "rs", "sa", "sf", "sh", "sm", "sr", "ta", "ur",
        },
        "GFEX": {"lc", "pd", "ps", "pt", "si"},
    }
    assert set().union(*exchange_products.values()) == active
    for row in evidence_rows:
        assert set(row) == set(reader.fieldnames)
        required_fields = set(reader.fieldnames) - {"artifact_sha256"}
        assert all(row[field].strip() for field in required_fields)
        assert row["exchange"] in allowed_hosts
        assert row["product"] in exchange_products[row["exchange"]]
        assert row["source_kind"] in allowed_source_kinds
        source_url = urlparse(row["official_source_url"])
        assert source_url.scheme == "https"
        if row["source_kind"] == "regulator_official_mirror":
            assert source_url.hostname in {"www.csrc.gov.cn", "csrc.gov.cn"}
        else:
            assert source_url.hostname in allowed_hosts[row["exchange"]]
        if row["source_kind"] == "exchange_attachment":
            assert Path(source_url.path).suffix.lower() in {".doc", ".docx", ".pdf"}
        date.fromisoformat(row["source_effective_date"])
        date.fromisoformat(row["verified_on"])
        assert row["verified_on"] == "2026-08-16"
        if row["artifact_sha256"]:
            assert re.fullmatch(r"[0-9a-f]{64}", row["artifact_sha256"])
        assert Decimal(row["derived_multiplier"]) == reference[row["product"]]
