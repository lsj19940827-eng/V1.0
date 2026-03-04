# -*- coding: utf-8 -*-
"""Test fixtures for environments without optional pytest plugins."""

from __future__ import annotations

import time
import pytest


@pytest.fixture
def benchmark():
    """
    Minimal fallback for pytest-benchmark.

    It preserves the common call form:
        benchmark(func, *args, **kwargs)
    """

    def _run(func, *args, **kwargs):
        start = time.perf_counter()
        result = func(*args, **kwargs)
        _run.last_duration = time.perf_counter() - start
        return result

    _run.last_duration = None
    return _run

