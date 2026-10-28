"""In-memory call limits: per-user cooldown, per-user quota, global quota."""

import time
from collections import defaultdict, deque

from .models import WikiError

WINDOW = 60.0


class Limiter:
    """Sliding-window counters; every value of 0 disables that layer.

    Cooldown applies to entry-point calls only (commands and searches); a
    single AI turn often issues a search plus several reads, so reads must
    not be cooldown-gated. Reads still count toward both windows.
    """

    def __init__(self, cooldown: float = 5.0, per_user: int = 6, per_minute: int = 30):
        self.cooldown = cooldown
        self.per_user = per_user
        self.per_minute = per_minute
        self._last: dict[str, float] = {}
        self._user_windows: dict[str, deque] = defaultdict(deque)
        self._global: deque = deque()
        self._next_cleanup = 0.0

    def check(self, user: str, cooldown: bool = True) -> None:
        now = time.monotonic()
        if now >= self._next_cleanup:
            self._cleanup(now)
        user_window = self._user_windows[user]
        self._prune(user_window, now)
        self._prune(self._global, now)
        last = self._last.get(user)
        if cooldown and self.cooldown > 0 and last is not None:
            # A fresh monotonic clock starts near zero; only a real previous
            # call may trigger the cooldown.
            elapsed = now - last
            if elapsed < self.cooldown:
                raise WikiError(
                    "user_limited",
                    f"查询太频繁，请 {max(1, int(self.cooldown - elapsed))} 秒后再试。",
                )
        if self.per_user > 0 and len(user_window) >= self.per_user:
            raise WikiError(
                "user_limited",
                f"已达每分钟 {self.per_user} 次查询上限，请约 {self._wait(user_window, now)} 秒后再试。",
            )
        if self.per_minute > 0 and len(self._global) >= self.per_minute:
            raise WikiError(
                "user_limited",
                f"当前查询人数较多，请约 {self._wait(self._global, now)} 秒后再试。",
            )
        if cooldown and self.cooldown > 0:
            self._last[user] = now
        user_window.append(now)
        self._global.append(now)

    def stats(self) -> dict:
        self._cleanup(time.monotonic())
        return {
            "tracked_users": sum(
                bool(window) for window in self._user_windows.values()
            ),
            "window_calls": len(self._global),
        }

    def _cleanup(self, now: float) -> None:
        self._prune(self._global, now)
        for user, window in list(self._user_windows.items()):
            self._prune(window, now)
            if not window:
                del self._user_windows[user]
        for user, last in list(self._last.items()):
            if now - last >= self.cooldown:
                del self._last[user]
        self._next_cleanup = now + WINDOW

    @staticmethod
    def _prune(window: deque, now: float) -> None:
        while window and now - window[0] >= WINDOW:
            window.popleft()

    @staticmethod
    def _wait(window: deque, now: float) -> int:
        return max(1, int(WINDOW - (now - window[0])) + 1)
