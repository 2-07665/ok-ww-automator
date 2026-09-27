"""Automator-owned progress messages and display statistics; no OK or GUI imports."""

from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass, field
import json
import math

PROGRESS_PREFIX = "@@AUTOMATOR_FARM "


@dataclass(frozen=True)
class FarmProgress:
    state: str
    count: int = 0
    elapsed: float = 0
    remaining: float = 0
    message: str = ""


def emit_progress(progress: FarmProgress) -> None:
    try:
        print(PROGRESS_PREFIX + json.dumps(asdict(progress), ensure_ascii=True), flush=True)
    except OSError:
        pass  # Losing the display must not stop farming.


def read_progress(line: str) -> FarmProgress | None:
    if not line.startswith(PROGRESS_PREFIX):
        return None
    try:
        progress = FarmProgress(**json.loads(line[len(PROGRESS_PREFIX):]))
        if progress.state not in {"connecting", "running", "shutdown", "failed"}:
            return None
        if not isinstance(progress.count, int) or progress.count < 0:
            return None
        if not all(math.isfinite(value) and value >= 0 for value in (progress.elapsed, progress.remaining)):
            return None
        if not isinstance(progress.message, str):
            return None
        return progress
    except (ValueError, TypeError):
        return None


@dataclass
class FarmStatistics:
    count: int = 0
    elapsed: float = 0
    remaining: float = 0
    samples: deque[tuple[float, int]] = field(default_factory=lambda: deque([(0.0, 0)]))

    def update(self, progress: FarmProgress) -> None:
        self.count = progress.count
        self.elapsed = progress.elapsed
        self.remaining = progress.remaining
        self.samples.append((self.elapsed, self.count))
        # Keep the last sample at/before the start of the five-minute window.
        while len(self.samples) > 2 and self.samples[1][0] <= self.elapsed - 300:
            self.samples.popleft()

    @property
    def hourly_rate(self) -> float | None:
        return self.count * 3600 / self.elapsed if self.count and self.elapsed > 0 else None

    @property
    def recent_hourly_rate(self) -> float | None:
        start, count = self.samples[0]
        duration = self.elapsed - start
        if duration <= 0 or not self.count:
            return None
        return (self.count - count) * 3600 / duration

    @property
    def seconds_per_fight(self) -> float | None:
        return self.elapsed / self.count if self.count else None
