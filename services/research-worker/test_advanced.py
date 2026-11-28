from datetime import UTC, datetime, timedelta
from unittest import TestCase

from advanced import events, panel, search


class AdvancedTests(TestCase):
    def test_incomplete_and_constant_cross_sections_are_excluded(self):
        keys = ["a", "b", "c"]
        samples = []

        def clock(n, members, labels):
            start = datetime(2026, 1, 6, hour=n, tzinfo=UTC)
            for i, member in enumerate(members):
                samples.append({"member": member, "available_at": start.isoformat(), "trading_day": "2026-01-06",
                                "feature": i, "label": labels[i],
                                "label_available_at": (start + timedelta(minutes=10)).isoformat()})
        clock(2, keys, [1, 3, 2])
        clock(3, keys[:2], [1, 2])
        clock(4, keys, [0, 0, 0])
        report = panel({"source": {"member_ids": keys}, "samples": samples, "policy": {"hac_lag": 1}})["advanced"]
        self.assertEqual(report["eligible_cross_sections"], 1)
        self.assertEqual(report["missing_member_counts"], {"c": 1})
        self.assertEqual(report["excluded"], {"INCOMPLETE_CROSS_SECTION": 1, "RANK_HAS_NO_VARIATION": 1})
        self.assertIsNone(report["estimate"]["interval"])
        self.assertEqual(report["quantiles"]["1"]["member_observations"], 2)
        self.assertAlmostEqual(report["quantiles"]["1"]["mean_label"], .5)
        self.assertEqual(set(report["quantiles"]), {"1", "3", "4"})

    def test_event_overlap_is_decided_before_reading_outcomes(self):
        rows = []
        for start, end, group, value in ((0, 2, True, .03), (1, 4, False, .88), (3, 5, False, .01)):
            entry = datetime(2026, 1, 6, 1, start, tzinfo=UTC)
            rows.append({"at": entry.isoformat(), "available_at": entry.isoformat(),
                         "label_available_at": entry.replace(minute=end).isoformat(),
                         "trading_day": "2026-01-06", "confirmed": group, "label": value})
        result = events({"samples": rows, "policy": {"hac_lag": 1}})["advanced"]
        self.assertEqual(result["purged_overlapping_events"], 1)
        self.assertAlmostEqual(result["estimate"]["mean"], .02)
        self.assertIsNone(result["estimate"]["p"])

    def test_optuna_fixed_grid_is_distinct_and_reproducible(self):
        plan = {"policy": {"choices": [0, 1, 2, 3], "budget": 3, "seed": 19}}
        original = search(plan)
        self.assertEqual(original, search(plan))
        self.assertEqual(len(set(original["experiment_plan"]["delays"])), 3)
        self.assertFalse(original["experiment_plan"]["scored"])

    def test_calendar_gaps_disable_inference_and_fixed_family_preserves_multiplicity(self):
        from advanced import stability

        january = [f"2026-01-{day:02}" for day in range(1, 11)]
        february = [f"2026-02-{day:02}" for day in range(1, 11)]
        measured = [0.1, .11, .09, .14, .10, .08, .05, .12, .13, .1]
        daily = {**dict(zip(january, measured)), **dict.fromkeys(february, 0.0)}
        output = stability(daily, 1, january + february)
        jan = output["months"]["2026-01"]
        self.assertAlmostEqual(jan["p_bh"], min(jan["p"] * 2, 1))
        self.assertIsNone(output["months"]["2026-02"]["p_bh"])
        daily.pop(january[3])
        gap = stability(daily, 1, january + february)
        self.assertIsNone(gap["months"]["2026-01"]["interval"])
        self.assertEqual(gap["estimate"]["reason"], "TRADING_DAY_GAPS_OR_CALENDAR_UNPROVEN")
