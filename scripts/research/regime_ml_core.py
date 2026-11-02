"""Development evaluation helpers; no source resolution or fitting."""

import numpy as np


def fold_masks(data, fold):
    allowed = data["owned"] & data["eligible"]
    return (
        allowed & (data["day"] <= int(fold["train_through"].replace("-", ""))),
        allowed
        & (data["start_day"] >= int(fold["validation_from"].replace("-", "")))
        & (data["day"] <= int(fold["validation_through"].replace("-", ""))),
    )


def product_weights(products):
    _, inverse, counts = np.unique(products, return_inverse=True, return_counts=True)
    weights = 1.0 / counts[inverse]
    return weights * len(weights) / weights.sum()


def metrics(data, indices, prediction):
    truth = data["label"][indices]
    products = data["product"][indices]
    per_product = {}
    recall = [[], [], []]
    for product in np.unique(products):
        mask = (products == product) & (truth >= 0)
        if mask.sum() < 30:
            continue
        y, p = truth[mask], prediction[mask]
        f1 = []
        for c in range(3):
            tp = int(((y == c) & (p == c)).sum())
            fn = int(((y == c) & (p != c)).sum())
            fp = int(((y != c) & (p == c)).sum())
            f1.append(2 * tp / (2 * tp + fn + fp) if 2 * tp + fn + fp else 0.0)
            if tp + fn:
                recall[c].append(tp / (tp + fn))
        per_product[str(int(product))] = float(np.mean(f1))
    switch_rates = []
    product_delays = []
    miss_rates = []
    events = 0
    missed = 0
    switches = 0
    event_delays = {}
    miss_by_product = {}
    false_alarm_rates = []
    for product in np.unique(products):
        pick = products == product
        ix = indices[pick]
        y = truth[pick]
        p = prediction[pick]
        adjacent = (ix[1:] == ix[:-1] + 1) & (
            data["segment"][ix[1:]] == data["segment"][ix[:-1]]
        )
        n_switch = int(((p[1:] != p[:-1]) & adjacent).sum())
        switches += n_switch
        if adjacent.sum():
            switch_rates.append(100 * n_switch / int(adjacent.sum()))
        false = (y == 0) & np.isin(p, (1, 2))
        starts = false.copy()
        starts[1:] &= ~false[:-1] | ~adjacent
        false_alarm_rates.append(100 * int(starts.sum()) / max(len(ix), 1))
        delays = []
        local_missed = 0
        local_events = 0
        for j in range(1, len(ix) - 2):
            if not adjacent[j - 1] or y[j] not in (1, 2) or y[j - 1] == y[j]:
                continue
            if not adjacent[j : j + 2].all() or not (y[j : j + 3] == y[j]).all():
                continue
            local_events += 1
            k = j
            while (
                k < len(ix)
                and (k == j or adjacent[k - 1])
                and y[k] == y[j]
                and p[k] != y[j]
            ):
                k += 1
            success = (
                k < len(ix)
                and (k == j or adjacent[k - 1])
                and y[k] == y[j]
                and p[k] == y[j]
            )
            event_delays[str(int(ix[j]))] = dict(
                product=int(product), delay=k - j if success else None
            )
            if success:
                delays.append(k - j)
            else:
                local_missed += 1
        events += local_events
        missed += local_missed
        if delays:
            product_delays.append(float(np.median(delays)))
        if local_events:
            miss_rates.append(local_missed / local_events)
            miss_by_product[str(int(product))] = local_missed / local_events
    return dict(
        macro_f1=float(np.mean(list(per_product.values()))) if per_product else None,
        recall=[float(np.mean(x)) if x else None for x in recall],
        per_product=per_product,
        labeled=int((truth >= 0).sum()),
        disputed=int((truth == -1).sum()),
        bars=len(indices),
        switches_per_100=float(np.mean(switch_rates)) if switch_rates else 0.0,
        switches=switches,
        trend_delay_median=float(np.median(product_delays)) if product_delays else None,
        delay_definition="median of per-product successful proxy-label-onset median; miss rate separate",
        false_alarm_segments_per_100=float(np.mean(false_alarm_rates))
        if false_alarm_rates
        else None,
        false_alarm_definition="prediction trend episodes against explicit RANGE reference only; disputed not scored",
        event_delays=event_delays,
        trend_miss_by_product=miss_by_product,
        trend_events=events,
        trend_missed=missed,
        trend_miss_rate=float(np.mean(miss_rates)) if miss_rates else None,
    )


def gate(base, trial):
    common = set(base["per_product"]) & set(trial["per_product"])
    not_worse = (
        sum(trial["per_product"][p] >= base["per_product"][p] for p in common)
        / len(common)
        if common
        else 0.0
    )
    paired = {}
    dropped = False
    for event, before in base["event_delays"].items():
        after = trial["event_delays"].get(event)
        if after is None:
            dropped = True
            continue
        if before["delay"] is not None:
            if after["delay"] is None:
                dropped = True
            else:
                paired.setdefault(before["product"], []).append(
                    after["delay"] - before["delay"]
                )
    delay_delta = (
        float(np.median([np.median(v) for v in paired.values()])) if paired else None
    )
    checks = dict(
        f1=base["macro_f1"] is not None
        and trial["macro_f1"] is not None
        and trial["macro_f1"] >= base["macro_f1"] + 0.03,
        recall=all(
            a is not None and b is not None and b >= a - 0.02
            for a, b in zip(base["recall"], trial["recall"])
        ),
        switches=trial["switches_per_100"] <= base["switches_per_100"] * 1.1,
        delay=delay_delta is not None and delay_delta <= 1 and not dropped,
        products=not_worse >= 0.6,
        misses=bool(base["trend_miss_by_product"])
        and all(
            trial["trend_miss_by_product"].get(p, 1.0) <= value
            for p, value in base["trend_miss_by_product"].items()
        ),
    )
    return dict(
        checks=checks,
        passes=all(checks.values()),
        product_non_regression=not_worse,
        paired_delay_delta=delay_delta,
        baseline_detected_event_dropped=dropped,
        role="DEVELOPMENT_SCREEN_ONLY_NOT_TEST_ACCEPTANCE",
    )
