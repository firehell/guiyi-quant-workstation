from __future__ import annotations

import pytest

from app.core.env import PROJECT_ROOT
from app.market_data.operational_universe import (
    ActiveUniverseError,
    OperationalUniverseError,
    load_active_products,
    load_operational_products,
)


def _write_universe(tmp_path, values: tuple[str, ...]):
    path = tmp_path / "operational_products.txt"
    path.write_text("\n".join(values) + "\n", encoding="utf-8")
    return path


def test_loads_exact_active_products_from_the_canonical_file() -> None:
    products = load_active_products()

    assert len(products) == 60
    assert len(set(products)) == 60
    assert products[0] == "a"
    assert products[-1] == "zn"


def test_rejects_an_incomplete_active_universe(tmp_path) -> None:
    path = tmp_path / "active_products.txt"
    path.write_text("j\njm\n", encoding="utf-8")

    with pytest.raises(ActiveUniverseError, match="ACTIVE_UNIVERSE_INVALID"):
        load_active_products(path)


def test_rejects_retired_products_in_the_active_universe(tmp_path) -> None:
    active = list(load_active_products())
    active[-1] = "sp"
    path = tmp_path / "active_products.txt"
    path.write_text("\n".join(active) + "\n", encoding="utf-8")

    with pytest.raises(ActiveUniverseError, match="ACTIVE_UNIVERSE_INVALID"):
        load_active_products(path)


def test_operational_products_are_the_complete_active_universe() -> None:
    active = load_active_products()

    assert len(active) == 60
    assert load_operational_products() == active


def test_rejects_duplicate_operational_code(tmp_path) -> None:
    path = _write_universe(tmp_path, ("j", "jm", "j"))

    with pytest.raises(OperationalUniverseError, match="OPERATIONAL_UNIVERSE_INVALID"):
        load_operational_products(path)


def test_rejects_operational_code_outside_active_universe(tmp_path) -> None:
    path = _write_universe(tmp_path, ("j", "not-active"))

    with pytest.raises(OperationalUniverseError, match="OPERATIONAL_UNIVERSE_INVALID"):
        load_operational_products(path)


def test_rejects_operational_code_overlapping_retired_universe(tmp_path) -> None:
    path = _write_universe(tmp_path, ("j", "cs"))

    with pytest.raises(OperationalUniverseError, match="OPERATIONAL_UNIVERSE_INVALID"):
        load_operational_products(path)


def test_all_active_products_are_an_accepted_operational_subset(tmp_path) -> None:
    active = tuple(
        line.strip()
        for line in (PROJECT_ROOT / "data/universe/active_products.txt").read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip()
    )

    assert load_operational_products(_write_universe(tmp_path, active)) == active
