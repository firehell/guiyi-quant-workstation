from __future__ import annotations

from copy import deepcopy
from dataclasses import FrozenInstanceError
from datetime import date
import json
from pathlib import Path
from typing import Any, Iterator

import pytest

from app.research.robustness.multi_candidate_robustness_policy import (
    MultiCandidateRobustnessProtocolError,
    load_multi_candidate_robustness_protocol,
)


PRODUCTS = (
    "a", "ag", "al", "ao", "ap", "au", "b", "bu", "bz", "c",
    "cf", "cj", "cu", "eb", "ec", "eg", "fg", "fu", "hc", "i",
    "j", "jd", "jm", "l", "lc", "lh", "m", "ma", "ni", "oi",
    "p", "pb", "pd", "pf", "pg", "pk", "pl", "pp", "pr", "ps",
    "pt", "px", "rb", "rm", "rs", "ru", "sa", "sc", "sf", "sh",
    "si", "sm", "sn", "sr", "ss", "ta", "ur", "v", "y", "zn",
)


def _payload() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "protocol_id": "multi_candidate_robustness_v1",
        "research_only": True,
        "frozen_at": "2026-08-20T21:33:00+08:00",
        "anchor_symbol": "jm",
        "candidates": [
            {
                "candidate_id": "subing_lifecycle_v2_candidate_v1",
                "source_kind": "subing_lifecycle",
                "policy_id": "subing_lifecycle_v2_research_v1",
                "formula_version": "subing_lifecycle_v2",
                "candidate_protocol_id": "candidate_validation_v1",
                "baseline_request_through": "2026-08-19",
                "source_event_kind": "entry_confirmed",
                "evaluable_unit": "5m_ready_boundary",
                "horizon_semantics": "same_trading_day_only",
            },
            {
                "candidate_id": "n_structure_5m_candidate_v1",
                "source_kind": "n_structure",
                "policy_id": "n_structure_5m_v1",
                "formula_version": "n_structure_v1",
                "candidate_protocol_id": "n_structure_validation_v1",
                "baseline_request_through": "2026-08-20",
                "source_event_kind": "n_completed",
                "evaluable_unit": "5m_canonical_bar",
                "horizon_semantics": "same_rank1_segment",
            },
        ],
        "common_retrospective": {"since": "2023-01-01", "through": "2026-08-18"},
        "cross_symbol_products": list(PRODUCTS),
        "event_proximity_bars": [3, 5, 8],
        "parameter_perturbation": False,
        "automatic_ranking": False,
        "automatic_promotion": False,
    }


def _write(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _dict_paths(value: object, prefix: tuple[object, ...] = ()) -> Iterator[tuple[object, ...]]:
    if isinstance(value, dict):
        for key, child in value.items():
            path = (*prefix, key)
            yield path
            yield from _dict_paths(child, path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _dict_paths(child, (*prefix, index))


def _container(payload: object, path: tuple[object, ...]) -> object:
    target = payload
    for part in path:
        target = target[part]  # type: ignore[index]
    return target


def test_loads_exact_multi_candidate_robustness_protocol() -> None:
    protocol = load_multi_candidate_robustness_protocol()

    assert protocol.protocol_id == "multi_candidate_robustness_v1"
    assert protocol.frozen_at.isoformat() == "2026-08-20T21:33:00+08:00"
    assert protocol.anchor_symbol == "jm"
    assert protocol.common_since == date(2023, 1, 1)
    assert protocol.common_through == date(2026, 8, 18)
    assert protocol.event_proximity_bars == (3, 5, 8)
    assert protocol.cross_symbol_products == PRODUCTS
    assert protocol.cross_symbol_products[22] == "jm"
    assert protocol.parameter_perturbation is False
    assert protocol.automatic_ranking is False
    assert protocol.automatic_promotion is False
    assert tuple(ref.candidate_id for ref in protocol.candidates) == (
        "subing_lifecycle_v2_candidate_v1",
        "n_structure_5m_candidate_v1",
    )
    assert tuple(ref.baseline_request_through for ref in protocol.candidates) == (
        date(2026, 8, 19),
        date(2026, 8, 20),
    )


def test_protocol_is_immutable() -> None:
    protocol = load_multi_candidate_robustness_protocol()

    with pytest.raises(FrozenInstanceError):
        protocol.anchor_symbol = "ag"  # type: ignore[misc]


def test_missing_extra_and_wrong_type_at_every_nested_key_fail_closed(
    tmp_path: Path,
) -> None:
    source_payload = _payload()
    for index, path in enumerate(_dict_paths(source_payload)):
        parent_path, key = path[:-1], path[-1]
        parent = _container(source_payload, parent_path)
        if not isinstance(parent, dict):
            continue

        missing = deepcopy(source_payload)
        del _container(missing, parent_path)[key]  # type: ignore[index]
        missing_path = tmp_path / f"missing-{index}.json"
        _write(missing_path, missing)
        with pytest.raises(
            MultiCandidateRobustnessProtocolError,
            match="MULTI_CANDIDATE_PROTOCOL_INVALID",
        ):
            load_multi_candidate_robustness_protocol(missing_path)

        extra = deepcopy(source_payload)
        _container(extra, parent_path)[f"unexpected_{index}"] = True  # type: ignore[index]
        extra_path = tmp_path / f"extra-{index}.json"
        _write(extra_path, extra)
        with pytest.raises(MultiCandidateRobustnessProtocolError):
            load_multi_candidate_robustness_protocol(extra_path)

        wrong_type = deepcopy(source_payload)
        current = _container(wrong_type, parent_path)[key]  # type: ignore[index]
        replacement: object = [] if not isinstance(current, list) else {}
        _container(wrong_type, parent_path)[key] = replacement  # type: ignore[index]
        wrong_type_path = tmp_path / f"wrong-type-{index}.json"
        _write(wrong_type_path, wrong_type)
        with pytest.raises(MultiCandidateRobustnessProtocolError):
            load_multi_candidate_robustness_protocol(wrong_type_path)


@pytest.mark.parametrize(
    "mutation",
    (
        "candidate_order",
        "product_order",
        "duplicate_product",
        "wrong_common_date",
        "wrong_baseline_date",
        "wrong_proximity",
        "parameter_true",
        "ranking_true",
        "promotion_true",
    ),
)
def test_exact_value_or_order_drift_fails_closed(tmp_path: Path, mutation: str) -> None:
    payload = _payload()
    if mutation == "candidate_order":
        payload["candidates"].reverse()
    elif mutation == "product_order":
        payload["cross_symbol_products"][0:2] = reversed(
            payload["cross_symbol_products"][0:2]
        )
    elif mutation == "duplicate_product":
        payload["cross_symbol_products"][-1] = payload["cross_symbol_products"][0]
    elif mutation == "wrong_common_date":
        payload["common_retrospective"]["through"] = "2026-08-19"
    elif mutation == "wrong_baseline_date":
        payload["candidates"][0]["baseline_request_through"] = "2026-08-20"
    elif mutation == "wrong_proximity":
        payload["event_proximity_bars"] = [3, 5, 13]
    elif mutation == "parameter_true":
        payload["parameter_perturbation"] = True
    elif mutation == "ranking_true":
        payload["automatic_ranking"] = True
    else:
        payload["automatic_promotion"] = True
    source = tmp_path / f"{mutation}.json"
    _write(source, payload)

    with pytest.raises(MultiCandidateRobustnessProtocolError):
        load_multi_candidate_robustness_protocol(source)


@pytest.mark.parametrize("content", (b"{", b"\xff\xfe"))
def test_malformed_or_non_utf8_protocol_fails_closed(
    tmp_path: Path,
    content: bytes,
) -> None:
    source = tmp_path / "protocol.json"
    source.write_bytes(content)

    with pytest.raises(MultiCandidateRobustnessProtocolError):
        load_multi_candidate_robustness_protocol(source)
