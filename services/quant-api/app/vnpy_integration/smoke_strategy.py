from __future__ import annotations

from typing import Any

from vnpy_ctastrategy import CtaTemplate


class VnpySmokeRoundTripStrategy(CtaTemplate):
    """Minimal research-only strategy for adapter smoke tests."""

    author = "guiyi_quant"
    parameters = ["entry_bar", "exit_bar", "volume"]
    variables = ["bar_count", "entry_sent", "exit_sent"]

    entry_bar = 2
    exit_bar = 6
    volume = 1

    def __init__(self, cta_engine: Any, strategy_name: str, vt_symbol: str, setting: dict[str, Any]) -> None:
        super().__init__(cta_engine, strategy_name, vt_symbol, setting)
        self.bar_count = 0
        self.entry_sent = False
        self.exit_sent = False

    def on_init(self) -> None:
        self.write_log("Vnpy smoke round-trip strategy initialized")

    def on_start(self) -> None:
        self.write_log("Vnpy smoke round-trip strategy started")

    def on_stop(self) -> None:
        self.write_log("Vnpy smoke round-trip strategy stopped")

    def on_bar(self, bar: Any) -> None:
        self.bar_count += 1
        if self.bar_count == int(self.entry_bar) and self.pos == 0 and not self.entry_sent:
            self.buy(float(bar.close_price) + 20, int(self.volume))
            self.entry_sent = True
        elif self.bar_count == int(self.exit_bar) and self.pos > 0 and not self.exit_sent:
            self.sell(float(bar.close_price) - 20, abs(int(self.pos)))
            self.exit_sent = True
