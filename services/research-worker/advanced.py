"""Statistics on frozen, time-aligned evidence with a preregistered HAC policy."""

from collections import Counter, defaultdict
from datetime import datetime
from math import isfinite
from statistics import mean


def hac_mean(samples, lag):
    import numpy as np
    from statsmodels.regression.linear_model import OLS

    n = len(samples)
    if n < max(8, lag + 3) or len(set(samples)) < 2:
        return {"n": n, "mean": mean(samples) if n else None, "interval": None, "p": None,
                "reason": "INSUFFICIENT_OR_CONSTANT_DAILY_SAMPLE"}
    model = OLS(samples, np.ones((n, 1))).fit(cov_type="HAC", cov_kwds={"maxlags": lag}, use_t=True)
    estimate = {"n": n, "mean": float(model.params[0]), "interval": model.conf_int()[0].tolist(),
                "p": float(model.pvalues[0]), "reason": None}
    if not all(isfinite(value) for value in [estimate["mean"], estimate["p"], *estimate["interval"]]):
        return {"n": n, "mean": mean(samples), "interval": None, "p": None, "reason": "ESTIMATE_NONFINITE"}
    return estimate


def stable_estimate(daily, lag, calendar):
    days = sorted(daily)
    values = [daily[day] for day in days]
    if not days:
        return hac_mean(values, lag)
    if not calendar or days != [day for day in calendar if days[0] <= day <= days[-1]]:
        return {"n": len(days), "mean": mean(values), "interval": None, "p": None,
                "reason": "TRADING_DAY_GAPS_OR_CALENDAR_UNPROVEN"}
    return hac_mean(values, lag)


def stability(daily, lag, calendar):
    from statsmodels.stats.multitest import multipletests

    months = defaultdict(dict)
    ordered = sorted(daily.items())
    for day, value in ordered:
        months[day[:7]][day] = value
    family = sorted({day[:7] for day in calendar or ()} | set(months))
    report = {month: stable_estimate(months[month], lag, calendar) for month in family}
    if family:
        p_values = [row["p"] if row["p"] is not None else 1.0 for row in report.values()]
        corrected = multipletests(p_values, method="fdr_bh")[1]
        for row, value in zip(report.values(), corrected, strict=True):
            row["p_bh"] = float(value) if row["p"] is not None else None
    return {"estimate": stable_estimate(daily, lag, calendar), "months": report,
            "daily_observations": dict(ordered), "interval_method": "HAC_t_95",
            "monthly_correction": "Benjamini-Hochberg over frozen-window months; unavailable month uses p=1", "hac_lag": lag}


def panel(payload):
    from scipy.stats import rankdata, spearmanr

    expected = set(payload["source"]["member_ids"])
    clock_groups = defaultdict(dict)
    missing = Counter()
    for row in payload["samples"]:
        clock = row["available_at"]
        member = row["member"]
        if member in clock_groups[clock]:
            raise ValueError("DUPLICATE_PANEL_MEMBER_AT_CLOCK")
        clock_groups[clock][member] = row
    daily = defaultdict(list)
    bucket_daily = defaultdict(lambda: defaultdict(list))
    bucket_sizes = Counter()
    excluded = Counter()
    for cohort in clock_groups.values():
        if cohort.keys() != expected:
            missing.update(expected - cohort.keys())
            excluded["INCOMPLETE_CROSS_SECTION"] += 1
            continue
        rows = [cohort[member] for member in sorted(expected)]
        if len({row["trading_day"] for row in rows}) != 1 or len({row["label_available_at"] for row in rows}) != 1:
            excluded["INCOMPARABLE_TRADING_DAY_OR_LABEL_CLOCK"] += 1
            continue
        feature = [row["feature"] for row in rows]
        label = [float(row["label"]) for row in rows]
        if len(set(feature)) < 2:
            excluded["RANK_HAS_NO_VARIATION"] += 1
            continue
        day = rows[0]["trading_day"]
        if len(set(label)) < 2:
            excluded["RANK_HAS_NO_VARIATION"] += 1
        else:
            daily[day].append(float(spearmanr(feature, label).statistic))
        outcomes = defaultdict(list)
        for rank, observation in zip(rankdata(feature, method="average"), label, strict=True):
            bucket = str(min(4, int(4 * (rank - 1) / (len(rows) - 1)) + 1))
            outcomes[bucket].append(observation)
        for bucket, values in outcomes.items():
            bucket_daily[bucket][day].append(mean(values))
            bucket_sizes[bucket] += len(values)
    result = stability({day: mean(values) for day, values in daily.items()},
                       payload["policy"]["hac_lag"], payload.get("trading_days"))
    quantiles = {rank: {"mean_label": mean([mean(values) for values in by_day.values()]),
                        "member_observations": bucket_sizes[rank], "trading_days": len(by_day),
                        "cross_sections": sum(map(len, by_day.values()))}
                 for rank, by_day in sorted(bucket_daily.items())}
    return {"advanced": {**result, "estimand": "daily_mean_of_complete_cross_section_rank_ic",
                         "quantiles": quantiles, "quantile_policy": "fixed_relative_rank_bands_average_ties",
                         "eligible_cross_sections": sum(map(len, daily.values())),
                         "excluded": dict(excluded), "missing_member_counts": dict(missing)}}


def events(payload):
    selected, overlap = [], 0
    previous_end = None
    clocks = sorted(payload["samples"], key=lambda row: (row["available_at"], row["at"]))
    for row in clocks:
        anchor = datetime.fromisoformat(row["available_at"])
        end = datetime.fromisoformat(row["label_available_at"])
        if end <= anchor:
            raise ValueError("EVENT_LABEL_CLOCK_INVALID")
        if previous_end is not None and anchor <= previous_end:
            overlap += 1
            continue
        previous_end = end
        selected.append(row)
    groups = defaultdict(lambda: {True: [], False: []})
    for row in selected:
        groups[row["trading_day"]][row["confirmed"]].append(float(row["label"]))
    paired = {day: mean(group[True]) - mean(group[False]) for day, group in groups.items()
              if group[True] and group[False]}
    result = stability(paired, payload["policy"]["hac_lag"], payload.get("trading_days"))
    return {"advanced": {**result, "estimand": "within_day_confirmed_minus_control_price_label",
                         "purged_overlapping_events": overlap, "accepted_events": len(selected),
                         "accepted_confirmed": sum(row["confirmed"] for row in selected),
                         "accepted_controls": sum(not row["confirmed"] for row in selected),
                         "excluded_unpaired_days": len(groups) - len(paired)}}


def search(payload):
    import optuna

    options = payload["policy"]
    candidates = options["choices"]
    sampler = optuna.samplers.GridSampler({"delay": candidates}, seed=options["seed"])
    study = optuna.create_study(sampler=sampler)
    sampled = [study.ask().suggest_categorical("delay", candidates) for _ in range(options["budget"])]
    if len(set(sampled)) != len(sampled):
        raise ValueError("OPTUNA_DUPLICATE_PARAMETER")
    return {"experiment_plan": {"delays": sampled, "scored": False,
                                "selection": "backtest_center_completed_training_settlement_only"}}
