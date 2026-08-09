from __future__ import annotations

import pytest

from app.core.env import PROJECT_ROOT
from app.market_data.operational_universe import (
    OperationalUniverseError,
    load_operational_products,
)


def _write_universe(tmp_path, values: tuple[str, ...]):
    path = tmp_path / "operational_products.txt"
    path.write_text("\n".join(values) + "\n", encoding="utf-8")
    return path


def test_loads_exact_operational_products_in_configured_order() -> None:
    assert load_operational_products() == ("j", "jm", "ap", "ag")


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
