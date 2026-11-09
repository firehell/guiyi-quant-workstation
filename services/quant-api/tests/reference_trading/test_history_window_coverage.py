"""A recent, fully warm input must not masquerade as full historical coverage."""
from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest

from app.reference_trading.persisted_newow import _require_history_window
from app.reference_trading.query import QueryConflict

CUTOFF = datetime(2026, 11, 6, 7, tzinfo=UTC)
READER = SimpleNamespace(historical_storage_start=lambda product: date(2023, 1, 1))


def test_current_watermark_and_warmup_do_not_cover_earlier_owners():
    manifest = {"query_since": "2026-11-02", "computed_through": CUTOFF.isoformat()}
    with pytest.raises(QueryConflict, match="NOT_BUILT"):
        _require_history_window(manifest, READER, "fg", date(2023, 1, 1), CUTOFF)


@pytest.mark.parametrize("since", [date(2023, 1, 1), date(2026, 8, 1), date(2020, 1, 1)])
def test_full_saved_prefix_accepts_requested_windows_and_storage_floor(since):
    _require_history_window({"query_since": "2023-01-01"}, READER, "fg", since, CUTOFF)


def test_local_window_can_read_partial_asset_without_claiming_earlier_history():
    _require_history_window({"query_since": "2026-11-02"}, READER,
                            "fg", date(2026, 11, 2), CUTOFF)


def test_missing_saved_start_fails_closed():
    with pytest.raises(QueryConflict, match="SOURCE_IDENTITY_UNVERIFIED"):
        _require_history_window({}, READER, "fg", date(2023, 1, 1), CUTOFF)


def test_missing_middle_owner_cannot_be_complete():
    from app.reference_trading.page_material_query import require_material_owners
    manifest = {'lifecycle_owners': [['FG2301', 'first'], ['FG2305', 'middle'], ['FG2309', 'last']],
                'rank1': [['FG2301', '2023-01-01', '2023-04-01'],
                         ['FG2305', '2023-04-02', '2023-08-01'],
                         ['FG2309', '2023-08-02', '2023-12-31']]}
    envelope = {'material': {'segments': [{'owner': 'FG2301|first'}, {'owner': 'FG2309|last'}]}}
    with pytest.raises(QueryConflict, match='SOURCE_IDENTITY_UNVERIFIED'):
        require_material_owners(envelope, manifest, since=date(2023, 1, 1), through=date(2023, 12, 31))
    envelope['material']['segments'].append({'owner': 'FG2305|middle', 'ordinary': None})
    # An owner with insufficient formula warm-up still exists; it is not deleted.
    require_material_owners(envelope, manifest, since=date(2023, 1, 1), through=date(2023, 12, 31))


def test_fusion_comparison_rejects_short_prefix_before_projecting(monkeypatch):
    from app.reference_trading.newow_fusion import PersistedFusionComparison
    from app.reference_trading.persisted_newow import PersistedNewowReference
    saved = PersistedNewowReference(lambda: None)
    saved._query = SimpleNamespace(streams=lambda **kw: [{'stream_id': 'fusion'}],
        summary=lambda *a, **kw: {'revision_id': 'r', 'seq': 2})
    saved._manifest = lambda *a: (None, {'query_since': '2026-11-02'})
    fusion = PersistedFusionComparison(lambda: None)
    fusion._persisted = saved
    fusion._query = saved._query
    with pytest.raises(QueryConflict, match='NOT_BUILT'):
        fusion.comparison(product='fg', frequency='1d', since=date(2023, 1, 1),
                          through=date(2026, 11, 6), cutoff=CUTOFF, reader=READER)


def test_repeated_rank1_contract_needs_each_owner_segment():
    from app.reference_trading.page_material_query import require_material_owners
    manifest = {'rank1': [['FG2301', '2023-01-01', '2023-02-01'],
                         ['FG2305', '2023-02-02', '2023-03-01'],
                         ['FG2301', '2023-03-02', '2023-04-01']],
                'lifecycle_owners': [['FG2301', 'first'], ['FG2305', 'second'], ['FG2301', 'third']]}
    envelope = {'material': {'segments': [{'owner': 'FG2301|first|quality1'},
                                        {'owner': 'FG2301|first|quality2'},
                                        {'owner': 'FG2305|second|quality1'}]}}
    with pytest.raises(QueryConflict, match='SOURCE_IDENTITY_UNVERIFIED'):
        require_material_owners(envelope, manifest, since=date(2023, 1, 1), through=date(2023, 4, 1))
    envelope['material']['segments'].append({'owner': 'FG2301|third|quality1'})
    require_material_owners(envelope, manifest, since=date(2023, 1, 1), through=date(2023, 4, 1))


def test_gap_owner_is_kept_even_without_lifecycle_replay_evidence():
    from app.reference_trading.page_material_query import require_material_owners
    manifest = {'rank1': [['FG2301', '2023-01-01', '2023-04-01']], 'lifecycle_owners': []}
    envelope = {'material': {'segments': [{'owner': 'FG2301|first|before-gap'},
                                        {'owner': 'FG2301|first|after-gap'}]}}
    require_material_owners(envelope, manifest, since=date(2023, 1, 1), through=date(2023, 4, 1))


def test_weekly_material_requires_exact_owners_with_verified_inputs():
    from app.reference_trading.page_material_query import require_material_owners
    manifest = {
        'rank1': [['PL2604', '2026-02-03', '2026-02-03'],
                  ['PL2605', '2026-02-04', '2026-04-01'],
                  ['PL2605', '2026-04-07', '2026-04-30']],
        'weekly_page_input_owners': [['PL2605', 'first'], ['PL2605', 'second']],
    }
    segments = [{'owner': 'PL2605|first|before-gap'}, {'owner': 'PL2605|second|after-gap'}]
    envelope = {'material': {'segments': segments}}
    window = dict(since=date(2026, 2, 1), through=date(2026, 4, 30), frequency='1w')
    require_material_owners(envelope, manifest, **window)
    with pytest.raises(QueryConflict, match='SOURCE_IDENTITY_UNVERIFIED'):
        require_material_owners(envelope, manifest, **{**window, 'frequency': '1d'})
    segments[1]['owner'] = 'PL2605|first|after-gap'
    with pytest.raises(QueryConflict, match='SOURCE_IDENTITY_UNVERIFIED'):
        require_material_owners(envelope, manifest, **window)
    segments[1]['owner'] = 'PL2605|different|after-gap'
    with pytest.raises(QueryConflict, match='SOURCE_IDENTITY_UNVERIFIED'):
        require_material_owners(envelope, manifest, **window)


@pytest.mark.parametrize('reader_version', ['newow_product_reader_prefix_v5', 'newow_product_reader_intraday_v3'])
def test_cached_short_prefix_is_rejected_for_all_readers(reader_version):
    from app.reference_trading.persisted_newow import PersistedNewowReference
    saved = PersistedNewowReference(lambda: None)
    saved._manifest = lambda *a: (SimpleNamespace(product='fg'),
        {'reader': reader_version, 'query_since': '2026-11-02'})
    delivery = SimpleNamespace(value=SimpleNamespace(saved_generation=('s', 'r', 2),
        payload={'performance_since': '2023-01-01', 'reference_cutoff': CUTOFF.isoformat()}))
    with pytest.raises(QueryConflict, match='NOT_BUILT'):
        saved.validate_cached_generation(delivery, reader=READER)
