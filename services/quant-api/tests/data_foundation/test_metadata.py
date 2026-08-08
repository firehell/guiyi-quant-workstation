from __future__ import annotations

from app.market_data.metadata import MetadataSnapshot


def test_metadata_snapshot_excludes_contract_specs() -> None:
    snapshot = MetadataSnapshot((), (), (), (), (), (), {})

    assert snapshot.main_contract_starts == {}
    assert not hasattr(snapshot, "contract_specs")
