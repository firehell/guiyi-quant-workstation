"""Forward publication boundary, distinct from Calendar/Session completion.

Only today's unpublished tail before 18:05 may wait. Missing earlier periods,
physical datasets, ownership or source quality remain failures of the MDS reader.
"""

from datetime import datetime, time
from zoneinfo import ZoneInfo

from app.market_data.domain import BarFrequency, SeriesKind, SeriesPageQuery

SHANGHAI = ZoneInfo("Asia/Shanghai")


class CanonicalPublicationError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def forward_published_through(
    market_data, *, product, frequency, through, as_of, weekly_candidates
):
    """Read the existing MDS endpoint; weekly due periods come from the caller's
    completed Calendar/Session week resolver, never available data files.
    """
    page = market_data.query_page(
        SeriesPageQuery(
            SeriesKind.ACTUAL_DOMINANT,
            product,
            BarFrequency(frequency),
            limit=1,
        )
    )
    if not page.bars or page.bars[-1].bar_end > as_of:
        raise CanonicalPublicationError("CANONICAL_PUBLICATION_ENDPOINT_INVALID")
    published = page.bars[-1].trading_day
    if published >= through:
        return through
    local = as_of.astimezone(SHANGHAI)
    waiting_today = local.time() < time(18, 5)
    if frequency == "1w":
        candidates = weekly_candidates()
        due = tuple(
            day
            for day, _ in candidates
            if day <= through and not (waiting_today and day == local.date())
        )
    else:
        due = market_data.completed_trading_days(
            symbol=product,
            start=datetime.combine(published, time.min, SHANGHAI),
            as_of=as_of,
            latest=through,
        )
        due = tuple(day for day in due if not (waiting_today and day == local.date()))
    if any(day > published for day in due):
        raise CanonicalPublicationError("CANONICAL_PUBLICATION_LAGGING")
    return published
