import asyncio
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def _status(**overrides):
    base = {
        "database": {"ok": True, "detail": "1200 memories"},
        "gmail": {"ok": True, "detail": "4 accounts healthy"},
        "task_queue": {"ok": True, "detail": "3 done, 0 failed, 1 pending (24h)"},
        "errors_24h": {"ok": True, "detail": "no errors logged"},
        "council": {"ok": True, "detail": "3 seats: claude, openai, gemini"},
    }
    base.update(overrides)
    return base


class FormatTests(unittest.TestCase):
    def test_all_healthy_formats_five_ticks_and_headline(self):
        from app.core.self_check import format_self_check, self_check_headline

        s = _status()
        text = format_self_check(s)
        self.assertEqual(text.count("✅"), 5)
        self.assertNotIn("⚠️", text)
        self.assertEqual(self_check_headline(s), "Nova self-check: all healthy")

    def test_warnings_counted_and_marked(self):
        from app.core.self_check import format_self_check, self_check_headline

        s = _status(
            gmail={"ok": False, "detail": "mlainton78: token stale since 17 Jul"},
            errors_24h={"ok": False, "detail": "gemini_client ×41"},
        )
        text = format_self_check(s)
        self.assertEqual(text.count("⚠️"), 2)
        self.assertIn("mlainton78: token stale", text)
        self.assertEqual(self_check_headline(s), "Nova self-check: 2 warnings")

    def test_missing_check_reported_not_crashed(self):
        from app.core.self_check import format_self_check

        s = _status()
        del s["council"]
        text = format_self_check(s)
        self.assertIn("⚠️ Council: check missing", text)


class IsolationTests(unittest.TestCase):
    def test_each_check_survives_db_being_down(self):
        from app.core import self_check

        with mock.patch.object(
            self_check, "get_conn", side_effect=RuntimeError("db down")
        ):
            status = self_check.gather_self_check()
        for key in ("database", "gmail", "task_queue", "errors_24h"):
            self.assertFalse(status[key]["ok"], key)
            self.assertIn("RuntimeError", status[key]["detail"])
        # council check is config-based and must still succeed
        self.assertIn("seats", status["council"]["detail"])

    def test_gather_never_raises(self):
        from app.core import self_check

        with mock.patch.object(
            self_check, "get_conn", side_effect=Exception("boom")
        ):
            status = self_check.gather_self_check()
        self.assertIn("generated_at", status)


class PassiveContractTests(unittest.TestCase):
    def test_self_check_source_is_passive(self):
        src = Path("app/core/self_check.py").read_text()
        for forbidden in ("refresh_access_token", "httpx", "UPDATE ", "INSERT INTO gmail", "DELETE "):
            self.assertNotIn(forbidden, src)

    def test_endpoint_uses_read_token(self):
        src = Path("app/api/v1/endpoints/selfcheck.py").read_text()
        self.assertIn("verify_read_token", src)

    def test_startup_wires_handler_and_schedule(self):
        src = Path("app/main.py").read_text()
        self.assertIn("register_self_check_handler()", src)
        self.assertIn("schedule_todays_self_check()", src)


class SchedulingTests(unittest.TestCase):
    def test_dedupe_skips_when_pending_task_exists(self):
        from app.core import self_check

        captured = {}

        def spy(sql, params=None):
            captured["sql"] = sql
            return [(1,)], None

        with mock.patch.object(self_check, "_run_query", spy):
            self.assertIsNone(self_check.schedule_todays_self_check())
        # Dedupe must key on pending status + schedule slot, not creation age
        self.assertIn("status IN ('queued', 'claimed', 'running')", captured["sql"])
        self.assertIn("scheduled_for > %s", captured["sql"])
        self.assertNotIn("created_at > NOW() - INTERVAL '6 hours'", captured["sql"])

    def test_task_counts_use_real_status_names(self):
        from app.core import self_check

        rows = [("done", 5), ("failed", 1), ("queued", 2), ("claimed", 1)]
        with mock.patch.object(self_check, "_run_query", return_value=(rows, None)):
            result = self_check.check_task_queue()
        self.assertIn("5 done, 1 failed, 3 pending", result["detail"])
        self.assertFalse(result["ok"])

    def test_schedules_future_run_when_none_queued(self):
        from app.core import self_check

        queued = {}

        def fake_queue_task(task_type, payload, delay_seconds):
            queued["type"] = task_type
            queued["delay"] = delay_seconds
            return 42

        with mock.patch.object(self_check, "_run_query", return_value=([(0,)], None)), \
             mock.patch.dict(sys.modules, {}), \
             mock.patch("app.core.task_queue.queue_task", fake_queue_task):
            tid = self_check.schedule_todays_self_check()
        self.assertEqual(tid, 42)
        self.assertEqual(queued["type"], "self_check")
        self.assertGreater(queued["delay"], 0)
        self.assertLessEqual(queued["delay"], 24 * 3600)

    def test_handler_boundary_is_future_startup_boundary_is_past(self):
        """The two callers apply opposite dedupe windows.

        Startup (require_future=False) skips if anything pending is
        newer than an hour ago — imminent or future. The handler
        (require_future=True) must only skip if a STRICTLY future run
        exists, otherwise its own still-running task would match and
        the chain would silently break.
        """
        from datetime import datetime
        from app.core import self_check

        captured = {}

        def spy(sql, params=None):
            captured["params"] = params
            # Return a dedupe hit so the function early-returns; we only
            # care about the boundary that got passed into the query.
            return [(1,)], None

        with mock.patch.object(self_check, "_run_query", spy):
            self_check.schedule_todays_self_check(require_future=True)
        self.assertIsNotNone(captured.get("params"))
        self.assertGreater(captured["params"][0], datetime.now())

        captured.clear()
        with mock.patch.object(self_check, "_run_query", spy):
            self_check.schedule_todays_self_check()
        self.assertLess(captured["params"][0], datetime.now())

    def test_delivery_perpetuates_the_chain(self):
        """The heartbeat: every successful delivery must queue tomorrow's run."""
        from app.core import self_check

        async def run():
            with mock.patch.object(self_check, "gather_self_check", return_value=_status()), \
                 mock.patch.object(self_check, "format_self_check", return_value="body"), \
                 mock.patch.object(self_check, "self_check_headline", return_value="Nova self-check: all healthy"), \
                 mock.patch.object(self_check, "schedule_todays_self_check", return_value=99) as sched, \
                 mock.patch("app.core.task_queue.update_progress", lambda *a, **kw: None):
                result = await self_check.deliver_self_check(1, {})
            return result, sched

        result, sched = asyncio.run(run())
        sched.assert_called_once_with(require_future=True)
        self.assertEqual(result["next_task_id"], 99)

    def test_chain_scheduling_failure_does_not_break_delivery(self):
        """A dead scheduler must not also kill the push. Chain error is caught
        AND recorded to run_events so a silent chain-break is durably visible.
        """
        from app.core import self_check

        async def run():
            with mock.patch.object(self_check, "gather_self_check", return_value=_status()), \
                 mock.patch.object(self_check, "format_self_check", return_value="body"), \
                 mock.patch.object(self_check, "self_check_headline", return_value="ok"), \
                 mock.patch.object(self_check, "schedule_todays_self_check", side_effect=RuntimeError("boom")), \
                 mock.patch("app.observability.record_run_event", return_value=17) as rec, \
                 mock.patch("app.core.task_queue.update_progress", lambda *a, **kw: None):
                result = await self_check.deliver_self_check(1, {})
            return result, rec

        result, rec = asyncio.run(run())
        self.assertIsNone(result["next_task_id"])
        rec.assert_called_once()
        kwargs = rec.call_args.kwargs
        self.assertEqual(kwargs["event_type"], "self_check_chain_scheduling_failed")
        self.assertEqual(kwargs["subsystem"], "self_check.chain")
        self.assertEqual(kwargs["error_class"], "RuntimeError")
        self.assertIn("boom", kwargs["error_message"])


if __name__ == "__main__":
    unittest.main()
