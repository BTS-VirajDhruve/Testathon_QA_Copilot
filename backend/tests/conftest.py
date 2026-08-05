"""Shared pytest fixtures."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _reset_model_router_singleton():
    from app.services import model_router as mr

    mr.reset_model_router()
    yield
    mr.reset_model_router()
