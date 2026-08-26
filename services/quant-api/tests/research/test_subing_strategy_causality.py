from __future__ import annotations

from app.market_data.subing_strategy.contracts import (
    SubingStrategyEpisodeState,
    SubingStrategyFillBasis,
)

from .test_subing_strategy_engine import (
    _bar,
    _entry_frames,
    _run,
)


def test_all_prior_ordinary_actions_and_closed_episodes_are_prefix_stable() -> None:
    all_frames = _entry_frames(
        exit_bar=_bar(2, close="98"),
        exit_ema="99",
    )
    ordinary_full = _run(all_frames)

    for end in range(1, len(all_frames) + 1):
        prefix = _run(all_frames[:end])
        cutoff = all_frames[end - 1].bar.bar_end
        expected_actions = tuple(
            action
            for action in ordinary_full.actions
            if action.effective_bar_end <= cutoff
        )
        assert prefix.actions == expected_actions
        expected_closed = tuple(
            episode
            for episode in ordinary_full.episodes
            if episode.state is SubingStrategyEpisodeState.CLOSED
            and episode.exit_action is not None
            and episode.exit_action.effective_bar_end <= cutoff
        )
        assert tuple(
            episode
            for episode in prefix.episodes
            if episode.state is SubingStrategyEpisodeState.CLOSED
        ) == expected_closed


def test_authoritative_terminal_adds_only_segment_terminal_projection() -> None:
    frames = _entry_frames()[:2]
    ordinary = _run(frames)
    terminal = _run(frames, terminal_bar_end=frames[-1].bar.bar_end)

    assert terminal.actions[: len(ordinary.actions)] == ordinary.actions
    assert terminal.actions[-1].fill_basis is SubingStrategyFillBasis.SEGMENT_TERMINAL_CLOSE
    assert terminal.actions[-1].reason_codes[-1] == "CONTRACT_SEGMENT_END"
