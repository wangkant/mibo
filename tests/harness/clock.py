"""One movable now for the modules that read the time for behaviour: life.clock (schedules, finds, pacing,
the feed) and the wall-clock reads of updates' staleness, recent.json's keep window, usage's day, walks' daily
count and spending's month. asyncio's monotonic clock is never moved, so waits and timeouts stay real."""
from __future__ import annotations

import time

from mibo import life, recent, roam, spend, updates, usage

# The modules that read `time.time()` for behaviour: each gets a `time` whose time() is the clock's.
READ_TIME = (updates, recent, usage, roam, spend)


class _Time:
    """The time module, but time() reads the clock."""

    def __init__(self, clock: Clock) -> None:
        self._clock = clock

    def time(self) -> float:
        return self._clock.now

    def __getattr__(self, name: str):
        return getattr(time, name)


class Clock:
    """`Clock(monkeypatch, now)`; `move(seconds)` goes forward (or back), `now` is where it stands."""

    def __init__(self, monkeypatch, now: float) -> None:
        self.now = float(now)
        monkeypatch.setattr(life, "clock", lambda: self.now)
        for module in READ_TIME:
            monkeypatch.setattr(module, "time", _Time(self))

    def move(self, seconds: float) -> float:
        self.now += seconds
        return self.now
