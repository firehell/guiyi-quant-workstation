"""Compare priority on frozen entry snapshots without generating a new position path."""

import argparse
from collections import Counter
from datetime import datetime
import json
from pathlib import Path

from lms405_portfolio_replay import ARCHIVE, CONTRACTS, LOCAL, input_sources
from lms_near405_replay import encoded, sha

SOURCE = "S5244966513415009"
SOURCE_SHA256 = "2c27c91f6098bab22c9c30e2c9b5f357ece796b469507f6ce7ffc3aa9a419611"
TIMELINE_SHA256 = "c5e98c3850b4b4bbd83b5ceda0303028ed323f4f6bfe17ca3bddd4ef0d04be4a"
PUBLISHED = "2025-12-17T22:15:00+08:00"
PUBLISHED_GROUPS = (("J", "JM", "V", "OI", "FG", "SA"), ("RB", "I", "SH", "RU"), ("TA",))
PRODUCTS = {c[:-4] for c in CONTRACTS}
GROUPS = tuple(tuple(product for product in group if product in PRODUCTS) for group in PUBLISHED_GROUPS)
ENTRY_LEGS = {"ENTER_LONG": ["1", "0"], "ENTER_SHORT": ["0", "1"]}
MANAGEMENT = {"LOCK", "UNLOCK_LONG", "UNLOCK_SHORT", "CLEAR"}


def priority(rows, *, slots, groups=None):
    """Resolve only complete priority groups. A tie that crosses capacity stays unresolved."""
    if slots is not None and (type(slots) is not int or slots < 0):
        raise ValueError("INVALID_HYPOTHETICAL_CAPACITY")
    contracts = {row["contract"] for row in rows}
    if len(contracts) != len(rows) or contracts - set(CONTRACTS):
        raise ValueError("INVALID_ENTRY_IDENTITIES")
    if slots is None or len(contracts) <= slots:
        return dict(status="ENOUGH_SLOTS", proposed=sorted(contracts), unresolved=[], deferred=[])
    if slots == 0:
        return dict(status="NO_SLOTS", proposed=[], unresolved=[], deferred=sorted(contracts))
    if groups is None:
        return dict(status="NO_APPLICABLE_RANK", proposed=[], unresolved=sorted(contracts), deferred=[])
    ranks = {product: rank for rank, group in enumerate(groups) for product in group}
    if set(ranks) != PRODUCTS or sum(map(len, groups)) != len(ranks):
        raise ValueError("INCOMPLETE_OR_DUPLICATE_TEST_RANK")
    proposed = []
    for rank in range(len(groups)):
        current = sorted(c for c in contracts if ranks[c[:-4]] == rank)
        lower = sorted(c for c in contracts if ranks[c[:-4]] > rank)
        if len(current) > slots:
            return dict(status="TIER_TIE", proposed=proposed, unresolved=current, deferred=lower)
        proposed.extend(current)
        slots -= len(current)
        if slots == 0:
            return dict(status="RANKED", proposed=proposed, unresolved=[], deferred=lower)
    raise ValueError("EXPECTED_COMPETITION")


def inspect_timeline(timeline):
    variants = (
        ("ample", None, None),
        ("no_slots", 0, None),
        ("one_slot_no_applicable_rank", 1, None),
        ("one_slot_2025_groups_hypothetical", 1, GROUPS),
        ("one_slot_reversed_groups_control", 1, GROUPS[::-1]),
        ("two_slots_2025_groups_hypothetical", 2, GROUPS),
    )
    retained, snapshots, competitions = [], [], []
    management_counts = Counter()
    opportunities = Counter()
    previous_at = None
    proposals_seen = set()
    for batch in timeline:
        at = datetime.fromisoformat(batch["time"])
        if at.utcoffset() is None or (previous_at is not None and at <= previous_at):
            raise ValueError("INVALID_SNAPSHOT_ORDER")
        if batch["layer"] != "FIXTURE_STATE_BATCH":
            raise ValueError("EXPECTED_FIXTURE_BATCH")
        entries, management = [], []
        seen = set()
        for row in batch["payload"]["actions"]:
            contract, action, proposal_id = (row[key] for key in ("contract", "action", "proposal_id"))
            if contract not in CONTRACTS or contract in seen or not proposal_id or proposal_id in proposals_seen:
                raise ValueError("DUPLICATE_OR_INVALID_FIXTURE_ACTION")
            seen.add(contract)
            proposals_seen.add(proposal_id)
            if action in ENTRY_LEGS and row["before"] == ["0", "0"] and row["after"] == ENTRY_LEGS[action]:
                entries.append(row)
                opportunities[contract] += 1
            elif action in MANAGEMENT:
                management.append(row)
                management_counts[action] += 1
            else:
                raise ValueError("UNCLASSIFIED_FIXTURE_ACTION")
        if management:
            retained.append(dict(time=batch["time"], actions=management))
        if entries:
            snap = dict(time=at.astimezone(LOCAL).isoformat(), opportunities=entries,
                        independent_management=management, comparisons={
                            name: priority(entries, slots=slots, groups=groups)
                            for name, slots, groups in variants
                        })
            snapshots.append(snap)
            if len(entries) > 1:
                competitions.append(snap["time"])
        previous_at = at
    return dict(
        opportunities_by_contract={c: opportunities[c] for c in CONTRACTS},
        management_counts=dict(management_counts), management=retained,
        management_sha256=sha(encoded(retained).encode()),
        entry_snapshots=snapshots, competition_times=competitions,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.output.exists():
            raise ValueError("OUTPUT_EXISTS")
        raw = args.fixture.read_bytes()
        if sha(raw) != TIMELINE_SHA256:
            raise ValueError("FROZEN_FIXTURE_HASH_MISMATCH")
        source = input_sources()[SOURCE]
        if (source["published_at"] != PUBLISHED
                or sha((ARCHIVE.parent / source["archive_path"]).read_bytes()) != SOURCE_SHA256):
            raise ValueError("PRIORITY_SOURCE_CHANGED")
        result = inspect_timeline(json.loads(raw)["actions"]["explicit_sh_fixture"]["timeline"])
        result.update(
            version="lms405-priority-study-v1", timeline_sha256=TIMELINE_SHA256,
            source=dict(id=SOURCE, url=source["source_url"], published_at=PUBLISHED,
                        sha256=SOURCE_SHA256, published_groups=PUBLISHED_GROUPS, projected_groups=GROUPS,
                        version=None,
                        scope="REMAINDER_OF_SOURCE_WEEK_ONLY_EXACT_END_UNKNOWN"),
            research_mode="STATIC_TEST_FIXTURE_SNAPSHOTS_NO_STATE_OR_BUDGET_FEEDBACK",
            historical_rank_applicable=False, capacity_unit="HYPOTHETICAL_CONCURRENT_NEW_OPPORTUNITIES",
            executable=False, admitted_author_samples=0, author_matches=None, fills=None, pnl=None,
        )
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(result))
    except (OSError, ValueError, KeyError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
