"""Single-generation, serial native query collection."""

from datetime import datetime
import re

SECTIONS = ("account", "positions", "orders", "fills")
MAX_ROWS = 4096


class ReadbackError(ValueError):
    pass


class Readback:
    def __init__(self):
        self.generation = 0
        self.day = None
        self.watermark = 0
        self.discard()

    def discard(self):
        self.started = None
        self.rows = {}
        self.pending = None

    def login(self, generation: int, day: str):
        if generation <= self.generation:
            raise ReadbackError("GENERATION_REGRESSION")
        if not re.fullmatch(r"[0-9]{8}", day):
            raise ReadbackError("TRADING_DAY_INVALID")
        datetime.strptime(day, "%Y%m%d")
        self.discard()
        self.generation = generation
        self.day = day

    def disconnect(self):
        self.day = None
        self.discard()

    def changed(self):
        self.watermark += 1

    def begin(self, now: datetime):
        if self.day is None:
            raise ReadbackError("NOT_LOGGED_IN")
        self.discard()
        self.started = now
        self.start_watermark = self.watermark

    def request(self, section: str, request_id: int):
        if (self.started is None or self.pending is not None or len(self.rows) == len(SECTIONS)
                or section != SECTIONS[len(self.rows)]):
            raise ReadbackError("QUERY_OUT_OF_SEQUENCE")
        self.rows[section] = []
        self.pending = (section, request_id)

    def _check_watermark(self):
        if self.watermark != self.start_watermark:
            raise ReadbackError("READBACK_CHANGED")

    def reply(self, section: str, request_id: int, data: dict, error: int, last: bool) -> bool:
        if self.pending != (section, request_id):
            return False
        self._check_watermark()
        if error:
            raise ReadbackError("NATIVE_QUERY_FAILED")
        if data:
            rows = self.rows[section]
            if len(rows) >= MAX_ROWS:
                raise ReadbackError("NATIVE_QUERY_ROW_LIMIT")
            rows.append(data)
        if last:
            self.pending = None
        return last

    def complete(self, investor: str, now: datetime) -> dict:
        from app.simulation_center.facts import normalize

        if self.day is None or self.started is None or self.pending or tuple(self.rows) != SECTIONS:
            raise ReadbackError("READBACK_INCOMPLETE")
        self._check_watermark()
        return {
            **normalize(self.rows, investor, self.day),
            "generation": self.generation,
            "watermark": self.watermark,
            "started_at": self.started.isoformat(),
            "observed_at": now.isoformat(),
        }
