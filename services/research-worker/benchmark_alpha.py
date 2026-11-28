"""Time one bounded batch against a frozen completed-Bar feature export."""

import argparse
from datetime import UTC, datetime
import gzip
from hashlib import sha256
import json
from math import isfinite
from pathlib import Path
import resource
from time import monotonic

from verify_alpha import FEATURES, LABEL_CODES, alpha_roundtrip


def run(universe, archive, since, through):
    started = monotonic()
    universe_bytes = universe.read_bytes()
    products = tuple(universe_bytes.decode().split())
    if len(products) != 57 or len(set(products)) != len(products):
        raise ValueError("EXPECTED_57_DISTINCT_PRODUCTS")
    rows, coverage, failures = [], {}, {}
    for symbol in products:
        product_rows = []
        try:
            with gzip.open(archive / f"{symbol}-60m.jsonl.gz", "rt", encoding="utf-8") as source:
                for line in source:
                    row = json.loads(line)
                    if not row["owned"] or not since <= row["day"] <= through:
                        continue
                    if row["symbol"] != symbol or row["frequency"] != "60m":
                        raise ValueError("SOURCE_IDENTITY_MISMATCH")
                    label = row["reference"]["label"]
                    features = row["features"]
                    if label not in LABEL_CODES or not features or not all(isfinite(features[key]) for key in FEATURES):
                        continue
                    product_rows.append({
                        "datetime": datetime.fromisoformat(row["time"]).astimezone(UTC).replace(tzinfo=None),
                        "vt_symbol": f"{row['contract']}:{row['segment']}",
                        **{name: features[name] for name in FEATURES},
                        "regime_label": LABEL_CODES[label],
                    })
        except FileNotFoundError:
            failures[symbol] = "FEATURE_EXPORT_NOT_FOUND"
            continue
        except (ValueError, KeyError, TypeError, OSError):
            failures[symbol] = "FEATURE_EXPORT_INVALID"
            continue
        coverage[symbol] = len(product_rows)
        if not product_rows:
            failures[symbol] = "NO_ELIGIBLE_ROWS"
        rows.extend(product_rows)
    verified = alpha_roundtrip(rows, "regime_label")
    checksum = sha256(json.dumps(rows, default=str, sort_keys=True, allow_nan=False).encode()).hexdigest()
    return {
        "universe_sha256": sha256(universe_bytes).hexdigest(),
        "calendar_window": [since, through], "verified_rows": verified, "input_sha256": checksum,
        "counts": coverage, "failures": failures, "elapsed_seconds": round(monotonic() - started, 3),
        "process_peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "worker_peak_rss_bytes": resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("universe", type=Path)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--since", required=True)
    parser.add_argument("--through", required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.universe, args.archive, args.since, args.through), indent=2, allow_nan=False))
