"""Phase timing for chat stream latency diagnostics."""

from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Iterator


@dataclass
class ChatLatencyTracker:
    """Accumulates wall-clock ms per chat pipeline phase."""

    phases: dict[str, float] = field(default_factory=dict)
    _stack: list[tuple[str, float]] = field(default_factory=list)
    synthesis_ttft_ms: float | None = None
    _synthesis_start: float | None = None

    @contextmanager
    def phase(self, name: str) -> Iterator[None]:
        t0 = time.perf_counter()
        self._stack.append((name, t0))
        try:
            yield
        finally:
            _, start = self._stack.pop()
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            self.phases[name] = self.phases.get(name, 0.0) + elapsed_ms

    def mark_synthesis_start(self) -> None:
        self._synthesis_start = time.perf_counter()

    def mark_first_content_token(self) -> None:
        if self._synthesis_start is not None and self.synthesis_ttft_ms is None:
            self.synthesis_ttft_ms = (time.perf_counter() - self._synthesis_start) * 1000.0

    def to_dict(self) -> dict[str, float]:
        out = dict(self.phases)
        if self.synthesis_ttft_ms is not None:
            out["synthesis_ttft"] = self.synthesis_ttft_ms
        total = sum(v for k, v in out.items() if k != "synthesis_ttft")
        out["total_pre_synthesis"] = total
        return out
