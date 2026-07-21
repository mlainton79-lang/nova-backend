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
    def test_dedupe_skips_when_recent_task_exists(self):
        from app.core import self_check

        with mock.patch.object(self_check, "_run_query", return_value=([(1,)], None)):
            self.assertIsNone(self_check.schedule_todays_self_check())

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


if __name__ == "__main__":
    unittest.main()
