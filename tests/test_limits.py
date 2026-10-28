"""Regression tests for query rate limits."""

import time
import unittest
from unittest.mock import patch

import pytest

from wiki.limits import Limiter
from wiki.models import WikiError


class TestLimiter(unittest.IsolatedAsyncioTestCase):
    def test_cooldown_blocks_rapid_calls(self):
        limiter = Limiter(cooldown=5, per_user=0, per_minute=0)
        limiter.check("u1")
        with pytest.raises(WikiError) as exc:
            limiter.check("u1")
        assert exc.value.code == "user_limited"
        assert "秒后再试" in str(exc.value)
        limiter.check("u2")  # other users are unaffected

    def test_per_user_window_quota(self):
        limiter = Limiter(cooldown=0, per_user=3, per_minute=0)
        for _ in range(3):
            limiter.check("u1", cooldown=False)
        with pytest.raises(WikiError) as exc:
            limiter.check("u1", cooldown=False)
        assert "每分钟 3 次" in str(exc.value)
        limiter.check("u2", cooldown=False)

    def test_global_window_quota(self):
        limiter = Limiter(cooldown=0, per_user=0, per_minute=2)
        limiter.check("u1", cooldown=False)
        limiter.check("u2", cooldown=False)
        with pytest.raises(WikiError) as exc:
            limiter.check("u3", cooldown=False)
        assert "查询人数较多" in str(exc.value)

    def test_zero_values_disable_layers(self):
        limiter = Limiter(cooldown=0, per_user=0, per_minute=0)
        for _ in range(50):
            limiter.check("u1", cooldown=False)
        assert limiter.stats()["window_calls"] == 50

    def test_expired_window_entries_are_pruned(self):
        limiter = Limiter(cooldown=0, per_user=1, per_minute=0)
        # An entry older than the 60s window must not block; compute it
        # relative to the real monotonic clock (which may start near zero).
        limiter._user_windows["u1"].append(time.monotonic() - 61)
        limiter.check("u1", cooldown=False)
        assert len(limiter._user_windows["u1"]) == 1

    def test_reads_skip_cooldown_but_still_count(self):
        limiter = Limiter(cooldown=5, per_user=2, per_minute=0)
        limiter.check("u1")  # search
        limiter.check("u1", cooldown=False)  # read rides along the same turn
        with pytest.raises(WikiError):
            limiter.check("u1", cooldown=False)  # second read exceeds quota

    def test_stats_report_usage(self):
        limiter = Limiter(cooldown=0, per_user=0, per_minute=0)
        limiter.check("a", cooldown=False)
        limiter.check("b", cooldown=False)
        assert limiter.stats() == {"tracked_users": 2, "window_calls": 2}

    def test_cold_start_first_query_is_not_rate_limited(self):
        # Fresh containers start monotonic near zero; the very first call has
        # no previous timestamp and must skip the cooldown entirely.
        limiter = Limiter(cooldown=5, per_user=0, per_minute=0)
        with patch("wiki.limits.time.monotonic", return_value=2.0):
            limiter.check("u1")  # would raise under the old 0.0 default

    def test_stats_expire_idle_users_and_calls(self):
        limiter = Limiter(cooldown=5, per_user=1, per_minute=1000)
        with patch("wiki.limits.time.monotonic", return_value=100):
            for index in range(100):
                limiter.check(str(index))
        with patch("wiki.limits.time.monotonic", return_value=161):
            assert limiter.stats() == {"tracked_users": 0, "window_calls": 0}
        assert not limiter._last and not limiter._user_windows

    def test_queries_reclaim_users_without_stats(self):
        limiter = Limiter(cooldown=5)
        with patch("wiki.limits.time.monotonic", return_value=100):
            limiter.check("old")
        with patch("wiki.limits.time.monotonic", return_value=161):
            limiter.check("new")
        assert "old" not in limiter._last and "old" not in limiter._user_windows

    def test_cleanup_preserves_cooldown_longer_than_window(self):
        limiter = Limiter(cooldown=120, per_user=0, per_minute=0)
        with patch("wiki.limits.time.monotonic", return_value=100):
            limiter.check("user")
        with patch("wiki.limits.time.monotonic", return_value=161):
            assert limiter.stats()["tracked_users"] == 0
            with pytest.raises(WikiError):
                limiter.check("user")
        with patch("wiki.limits.time.monotonic", return_value=221):
            limiter.check("user")
