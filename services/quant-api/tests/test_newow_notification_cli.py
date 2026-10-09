import pytest

from app.notifications.cli import require_scope


def test_preflight_accepts_exact_four_strategy_three_period_matrix():
    from app.notifications.newow import STRATEGIES, FREQUENCIES
    rows = [(s, f, p) for s in STRATEGIES for f in FREQUENCIES for p in ("j", "rb")]
    require_scope(rows, ("j", "rb"))


def test_preflight_rejects_missing_or_duplicate_route():
    from app.notifications.newow import STRATEGIES, FREQUENCIES
    rows = [(s, f, "j") for s in STRATEGIES for f in FREQUENCIES]
    with pytest.raises(ValueError, match="SCOPE_NOT_READY"):
        require_scope(rows[:-1], ("j",))
    with pytest.raises(ValueError, match="SCOPE_NOT_READY"):
        require_scope(rows + [rows[0]], ("j",))
