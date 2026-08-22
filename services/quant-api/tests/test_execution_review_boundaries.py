from __future__ import annotations

import importlib


def test_execution_review_services_have_single_responsibilities() -> None:
    mutation_module = importlib.import_module("app.execution_review.service")
    query_module = importlib.import_module("app.execution_review.queries")
    reconstruction_module = importlib.import_module(
        "app.execution_review.reconstruction"
    )
    composition = importlib.import_module("app.execution_review.composition")

    mutation_service = mutation_module.ExecutionReviewService
    for read_method in (
        "reconstruct_event",
        "list_items",
        "event_states",
        "episode_detail",
        "stats",
    ):
        assert not hasattr(mutation_service, read_method)

    assert hasattr(query_module.ExecutionReviewQueryService, "list_items")
    assert hasattr(query_module.ExecutionReviewQueryService, "event_states")
    assert hasattr(query_module.ExecutionReviewQueryService, "episode_detail")
    assert hasattr(query_module.ExecutionReviewQueryService, "stats")
    assert hasattr(
        reconstruction_module.EventReconstructionService,
        "reconstruct_event",
    )
    assert callable(composition.build_execution_review_query_service)
    assert callable(composition.build_execution_review_reconstruction_service)
