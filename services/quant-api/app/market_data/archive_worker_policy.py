"""Bounded diagnostics for the after-market worker."""
import re


def maintenance_failure_fields(failure, attempt, failure_count, *, product_code, reason_codes):
    fields: dict[str, object] = {
        "stage": "canonical_update_result", "attempt": attempt,
        "failure_count": min(failure_count, 100000),
    }
    dataset = failure.get("dataset")
    if isinstance(dataset, (tuple, list)) and len(dataset) == 4:
        kind, symbol, contract, frequency = dataset
        if kind in {"contract", "continuous"} and isinstance(symbol, str) and product_code.fullmatch(symbol):
            fields["symbol"] = symbol
            if kind == "contract" and isinstance(contract, str) and re.fullmatch(r"[A-Z]{1,2}[0-9]{3,4}\Z", contract):
                fields["contract"] = contract
        if isinstance(frequency, str) and frequency in {"1m", "1d", "1w", "5m", "15m", "30m", "60m"}:
            fields["frequency"] = frequency
    for name, upper in (("year", 9999), ("month", 12)):
        value = failure.get(name)
        if type(value) is int and 1 <= value <= upper:
            fields[name] = value
    reason = failure.get("reason_code")
    fields["reason_code"] = (
        reason if isinstance(reason, str) and reason in reason_codes
        else "OTHER_TARGET_FAILURE"
    )
    return fields
