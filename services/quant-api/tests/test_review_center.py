from app.models.review import ReviewNote
from app.review.payloads import apply_review_fields, review_response


def test_review_fields_keep_signal_review_tags_and_notes() -> None:
    note = ReviewNote(
        source_type="signal_event",
        source_id=7,
        mistake_tags=[],
        rule_tags=[],
        emotion_tags=[],
        screenshot_paths=[],
        extra={},
    )

    apply_review_fields(
        note,
        {
            "mistake_tags": ["追价"],
            "setup_tags": ["带量突破"],
            "execution_note": "等待确认收盘",
            "improvement_note": "减少主观提前入场",
        },
    )

    assert note.mistake_tags == ["追价"]
    assert note.rule_tags == ["带量突破"]
    assert note.extra == {"execution_note": "等待确认收盘"}
    assert note.lesson == "减少主观提前入场"


def test_review_response_preserves_non_backtest_source_identity() -> None:
    note = ReviewNote(
        id=11,
        source_type="strategy_signal",
        source_id=6,
        mistake_tags=[],
        rule_tags=[],
        emotion_tags=[],
        screenshot_paths=[],
        extra={},
    )

    payload = review_response(note)

    assert payload["source_type"] == "strategy_signal"
    assert payload["source_id"] == 6
    assert payload["review_object_type"] == "strategy_signal"
