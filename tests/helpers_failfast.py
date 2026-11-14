"""Helpers to assert worker init/work never hang on failure paths."""

from __future__ import annotations

import concurrent.futures
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")

# Plenty for local mocked work; real hangs would exceed this.
DEFAULT_BUDGET_S = 2.0


def run_within(fn: Callable[[], T], budget_s: float = DEFAULT_BUDGET_S) -> T:
    """Run ``fn`` in a worker thread; raise TimeoutError if it exceeds budget."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        fut = pool.submit(fn)
        try:
            return fut.result(timeout=budget_s)
        except concurrent.futures.TimeoutError as e:
            raise TimeoutError(
                f"call did not finish within {budget_s:.1f}s (possible hang)"
            ) from e
