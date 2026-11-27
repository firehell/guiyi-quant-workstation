import pytest

from app.services.newow_reference_mode import require_isolated_redis


def test_isolated_redis_cannot_fall_back_to_runtime_port():
    for address in ("", "redis://127.0.0.1:6379/0", "redis://localhost:6379/14",
                    "redis://127.0.0.1:6380/0?host=example.test"):
        with pytest.raises(ValueError, match="BACKTEST_ISOLATED_REDIS_REQUIRED"):
            require_isolated_redis(address)
    require_isolated_redis("redis://127.0.0.1:16379/0")
