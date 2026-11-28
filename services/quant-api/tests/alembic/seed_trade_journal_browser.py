"""Populate the disposable browser database with the Simulation Center's read model."""

import json
import os
from pathlib import Path
import re

import psycopg

DSN = "postgresql://postgres@127.0.0.1:15474/isolated_test_trade_journal"
DAY = "2026-11-30"
FROM_API = Path(__file__).resolve().parents[3]


def main():
    alias = os.getenv("GUIYI_TRADE_JOURNAL_TEST_ACCOUNT", "journal-e2e")
    if re.fullmatch(r"journal-e2e(?:-[a-z0-9]{1,12})?", alias) is None:
        raise ValueError("invalid browser fixture account")
    with psycopg.connect(DSN, autocommit=True) as conn:
        if conn.info.dbname != "isolated_test_trade_journal" or conn.info.port != 15474:
            raise RuntimeError("trade journal browser fixture requires the isolated test database")
        schema = FROM_API / "newow-vnpy/simulation_schema.sql"
        if conn.execute("SELECT to_regclass('guiyi_simulation.accounts')").fetchone()[0] is None:
            conn.execute(schema.read_text())
        with conn.transaction():
            conn.execute("INSERT INTO guiyi_simulation.accounts (alias,native_key) VALUES (%s,%s)", (alias, alias))
            conn.execute("""
                INSERT INTO guiyi_simulation.readbacks VALUES
                (%s,'2026-11-30T15:05:00+08:00','{"trading_day":"2026-11-30"}')
            """, (alias,))
            events = [
                ("open", "LONG", "OPEN", "3100"), ("add", "LONG", "OPEN", "3105"),
                ("reduce", "SHORT", "CLOSETODAY", "3108"), ("close", "SHORT", "CLOSETODAY", "3110"),
            ]
            for index, (name, direction, offset, price) in enumerate(events):
                at = f"2026-11-27T21:{10 + index}:00+08:00"
                fill_id = f"{DAY}:SHFE:journal-{name}"
                fact = {"id": fill_id, "contract": "RB2701", "occurred_at": at, "direction": direction,
                        "offset": offset, "quantity": 1, "price": price, "fee": None}
                conn.execute("""
                    INSERT INTO guiyi_simulation.fills VALUES (%s,%s,%s,%s)
                """, (alias, fill_id, at, json.dumps(fact)))


if __name__ == "__main__":
    main()
