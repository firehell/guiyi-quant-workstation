"""Versioned ordered leaf comparisons without expanding packed proof vectors.

Legacy arrays retain their original representation and manifest hashes. Reading
one against freshly computed packed leaves compares facts, never upgrades it.
"""
from collections.abc import Sequence

from app.reference_trading.packed_fingerprints import PackedFingerprints

SEMANTIC_READERS = ('newow_product_reader_prefix_v4', 'newow_product_reader_prefix_v5')
FUSION_READERS = frozenset({'newow_fusion_saved_sources_v1', 'newow_fusion_saved_sources_v2',
                          'newow_fusion_saved_sources_v3'})


def fingerprint_sequence(value: object) -> Sequence[str]:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return PackedFingerprints(value)
    raise ValueError('REFERENCE_FINGERPRINT_PROOF_INVALID')


def fingerprint_count(value: object) -> int:
    return len(fingerprint_sequence(value))


def fingerprints_prefix(prior: object, current: object) -> bool:
    try:
        old, new = fingerprint_sequence(prior), fingerprint_sequence(current)
        if len(old) > len(new):
            return False
        if isinstance(old, PackedFingerprints) and isinstance(new, PackedFingerprints):
            return old.is_prefix_of(new)
        return all(left == right for left, right in zip(old, new))
    except (TypeError, ValueError):
        return False


def fingerprints_equal(left: object, right: object) -> bool:
    try:
        return fingerprint_count(left) == fingerprint_count(right) and fingerprints_prefix(left, right)
    except (TypeError, ValueError):
        return False
