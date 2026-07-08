import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


class ScheduledBriefingsTests(unittest.TestCase):
    def test_on_shift_schedules_pre_and_post_shift_briefs(self):
        from app.core import scheduled_briefings
        from app.core import rota
        from app.core import task_queue

        original_get_conn = scheduled_briefings.get_conn
        original_seconds_until = scheduled_briefings._seconds_until
        original_on_shift = rota.is_currently_on_shift
        original_next_shift = rota.next_shift_start
        original_queue_task = task_queue.queue_task

        queued = []

        class FakeCursor:
            def execute(self, *_args, **_kwargs):
                return None

            def fetchone(self):
                return None

            def close(self):
                return None

        class FakeConn:
            def cursor(self):
                return FakeCursor()

            def close(self):
                return None

        def fake_queue_task(task_type, payload, delay_seconds=0):
            queued.append((task_type, payload, delay_seconds))
            return len(queued)

        try:
            scheduled_briefings.get_conn = lambda: FakeConn()
            scheduled_briefings._seconds_until = lambda hour, minute=0: {
                (18, 30): 60,
                (8, 30): 120,
            }[(hour, minute)]
            rota.is_currently_on_shift = lambda: True
            rota.next_shift_start = lambda: None
            task_queue.queue_task = fake_queue_task

            scheduled = scheduled_briefings.schedule_todays_briefs()

            self.assertEqual([item["type"] for item in scheduled], ["pre_shift", "post_shift"])
            self.assertEqual(
                queued,
                [
                    ("scheduled_brief", {"type": "pre_shift"}, 60),
                    ("scheduled_brief", {"type": "post_shift"}, 120),
                ],
            )
        finally:
            scheduled_briefings.get_conn = original_get_conn
            scheduled_briefings._seconds_until = original_seconds_until
            rota.is_currently_on_shift = original_on_shift
            rota.next_shift_start = original_next_shift
            task_queue.queue_task = original_queue_task


if __name__ == "__main__":
    unittest.main()
