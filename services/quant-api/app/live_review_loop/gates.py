from __future__ import annotations

from collections.abc import Mapping


LIVE_FLAG = "GUIYI_DATA_CORE_V2_LIVE_DECISION_ENABLED"
EOD_FLAG = "GUIYI_DATA_CORE_V2_EOD_ENABLED"
RETENTION_FLAG = "GUIYI_DATA_CORE_V2_RETENTION_SCHEDULER_ENABLED"
NOTIFICATION_FLAG = "GUIYI_LIVE_SIGNAL_EVENTS_ENABLED"
REVIEW_FLAG = "GUIYI_DATA_CORE_V2_REVIEW_ENABLED"


class LiveReviewFeatureDisabledError(RuntimeError):
    pass


class LiveReviewExecutionGate:
    def __init__(self, environ: Mapping[str, str]) -> None:
        self.environ = environ

    def require_live(self) -> None:
        self._require(LIVE_FLAG, "LIVE_REVIEW_LIVE_DISABLED")

    def require_eod(self) -> None:
        self._require(EOD_FLAG, "LIVE_REVIEW_EOD_DISABLED")

    def require_retention(self) -> None:
        self._require(RETENTION_FLAG, "LIVE_REVIEW_RETENTION_DISABLED")

    def require_notification(self) -> None:
        self._require(NOTIFICATION_FLAG, "LIVE_REVIEW_SIGNAL_EVENT_DISABLED")

    def require_review(self) -> None:
        self._require(REVIEW_FLAG, "LIVE_REVIEW_REVIEW_DISABLED")

    def _require(self, flag: str, code: str) -> None:
        if not _enabled(self.environ, flag):
            raise LiveReviewFeatureDisabledError(code)


def build_live_review_health(environ: Mapping[str, str]) -> dict[str, object]:
    live = _enabled(environ, LIVE_FLAG)
    eod = _enabled(environ, EOD_FLAG)
    retention = _enabled(environ, RETENTION_FLAG)
    notification = _enabled(environ, NOTIFICATION_FLAG)
    review = _enabled(environ, REVIEW_FLAG)
    return {
        "status": "enabled" if any((live, eod, retention, notification, review)) else "disabled",
        "live_decision_enabled": live,
        "eod_enabled": eod,
        "retention_scheduler_enabled": retention,
        "notification_enabled": notification,
        "review_enabled": review,
        "auto_order": False,
        "observation_only": True,
    }


def _enabled(environ: Mapping[str, str], name: str) -> bool:
    return str(environ.get(name, "")).strip().lower() in {"1", "true", "yes", "on"}
