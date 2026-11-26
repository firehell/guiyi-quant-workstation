"""Scheduling for the durable Live worker."""


def due_observations(pending, source_events, now):
    return [
        (key, bar, window, contract) for key, (bar, window, contract) in pending
        if (now - bar.bar_end).total_seconds() >= 2
        and (
            not source_events[(contract, bar.bar_end)].source_generation
            or (
                (received_at := source_events[(contract, bar.bar_end)].raw_received_at) is not None
                and received_at <= now
            )
        )
    ]
