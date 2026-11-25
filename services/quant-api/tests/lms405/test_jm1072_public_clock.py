from lms405_jm1072_public_clock import event_context
from lms405_right_side_study import ONE, US, at


def test_jm_1072_active_run_must_be_known_before_shape_and_late_article_stays_late():
    first = at("2025-11-27T09:15")
    confirm = first + ONE
    source = at("2025-11-27T17:07")
    event = dict(confirmed_at=confirm, shape_start=first - 5 * ONE)
    runs = {confirm: dict(close_count=2)}
    trace = event_context(event, runs, published_minute_end=source)
    assert trace["active_below_run_start"] == first
    assert trace["confirmed_in_current_run"] is True
    assert trace["active_below_run_known_before_shape"] is False
    assert trace["cited_article_entry_before_shape"] is False

    event["shape_start"] = first + US
    assert event_context(event, runs, published_minute_end=source)["active_below_run_known_before_shape"] is False
    event["shape_start"] += US
    assert event_context(event, runs, published_minute_end=source)["active_below_run_known_before_shape"] is True
    assert event_context(event, {}, published_minute_end=source)["confirmed_in_current_run"] is False
