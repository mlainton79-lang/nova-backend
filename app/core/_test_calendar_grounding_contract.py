#!/usr/bin/env python3
"""Unit tests for app.core.calendar_grounding_contract.

Invokable directly, no pytest dependency:
    /usr/bin/python3 app/core/_test_calendar_grounding_contract.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from app.core import calendar_grounding_contract as contract  # noqa: E402


RANGE_START = "2026-06-29T00:00:00Z"
RANGE_END = "2026-06-30T00:00:00Z"


class CalendarGroundingContractTests(unittest.TestCase):
    def test_absent_fetched_records_returns_unavailable(self):
        decision = contract.evaluate_calendar_grounding(
            RANGE_START,
            RANGE_END,
            fetched_events=None,
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.status, contract.UNAVAILABLE)
        self.assertEqual(decision.reason, contract.NO_FETCHED_EVENT_RECORDS)
        self.assertFalse(decision.factual_schedule_allowed)

    def test_empty_fetched_records_allows_no_events_statement_only(self):
        decision = contract.evaluate_calendar_grounding(
            RANGE_START,
            RANGE_END,
            fetched_events=[],
        )

        self.assertTrue(decision.allowed)
        self.assertEqual(decision.reason, contract.NO_EVENTS_IN_REQUESTED_RANGE)
        self.assertEqual(decision.backed_event_count, 0)

    def test_fetched_event_inside_requested_range_allows_factual_claim(self):
        events = [
            {
                "id": "cal_1",
                "title": "Dentist",
                "start": "2026-06-29T09:00:00Z",
            }
        ]
        decision = contract.evaluate_calendar_grounding(
            RANGE_START,
            RANGE_END,
            fetched_events=events,
            candidate_items=[
                {
                    "event_id": "cal_1",
                    "title": "Dentist",
                    "start": "2026-06-29T09:00:00Z",
                    "source": "calendar_fetch",
                }
            ],
        )

        self.assertTrue(decision.allowed)
        self.assertEqual(decision.status, contract.ALLOWED)
        self.assertEqual(decision.reason, contract.FETCHED_RECORDS_AVAILABLE)
        self.assertEqual(decision.backed_event_count, 1)

    def test_memory_only_event_claim_is_rejected_even_if_text_looks_plausible(self):
        decision = contract.evaluate_calendar_grounding(
            RANGE_START,
            RANGE_END,
            fetched_events=[],
            candidate_items=[
                {
                    "title": "Physio",
                    "start": "2026-06-29T11:00:00Z",
                    "source": "memory",
                }
            ],
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.status, contract.REJECTED)
        self.assertEqual(decision.reason, contract.MEMORY_ONLY_EVENT_CLAIM)
        self.assertEqual(len(decision.rejected_claims), 1)

    def test_unmatched_non_memory_claim_is_rejected_as_unbacked(self):
        decision = contract.evaluate_calendar_grounding(
            RANGE_START,
            RANGE_END,
            fetched_events=[
                {
                    "id": "cal_1",
                    "title": "Dentist",
                    "start": "2026-06-29T09:00:00Z",
                }
            ],
            candidate_items=[
                {
                    "event_id": "missing",
                    "title": "Lunch",
                    "start": "2026-06-29T13:00:00Z",
                    "source": "calendar_fetch",
                }
            ],
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, contract.UNBACKED_EVENT_CLAIM)

    def test_event_id_match_does_not_allow_changed_event_details(self):
        decision = contract.evaluate_calendar_grounding(
            RANGE_START,
            RANGE_END,
            fetched_events=[
                {
                    "id": "cal_1",
                    "title": "Dentist",
                    "start": "2026-06-29T09:00:00+01:00",
                }
            ],
            candidate_items=[
                {
                    "event_id": "cal_1",
                    "title": "Dentist",
                    "start": "2026-06-29T11:00:00+01:00",
                    "source": "calendar_fetch",
                }
            ],
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, contract.UNBACKED_EVENT_CLAIM)

    def test_fetched_event_outside_requested_range_is_stale_claim(self):
        decision = contract.evaluate_calendar_grounding(
            RANGE_START,
            RANGE_END,
            fetched_events=[
                {
                    "id": "cal_old",
                    "title": "Dentist",
                    "start": "2026-06-28T09:00:00Z",
                }
            ],
            candidate_items=[
                {
                    "event_id": "cal_old",
                    "title": "Dentist",
                    "start": "2026-06-28T09:00:00Z",
                    "source": "calendar_fetch",
                }
            ],
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.status, contract.REJECTED)
        self.assertEqual(decision.reason, contract.STALE_EVENT_CLAIM)

    def test_title_and_start_can_back_claim_when_event_id_is_absent(self):
        decision = contract.evaluate_calendar_grounding(
            RANGE_START,
            RANGE_END,
            fetched_events=[
                {
                    "summary": "All day reminder",
                    "start": {"date": "2026-06-29"},
                }
            ],
            candidate_items=[
                {
                    "title": "All day reminder",
                    "start": "2026-06-29",
                    "source": "calendar_fetch",
                }
            ],
        )

        self.assertTrue(decision.allowed)
        self.assertEqual(decision.backed_event_count, 1)

    def test_invalid_range_fails_closed(self):
        decision = contract.evaluate_calendar_grounding(
            RANGE_END,
            RANGE_START,
            fetched_events=[],
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.status, contract.REJECTED)
        self.assertEqual(decision.reason, contract.INVALID_REQUESTED_RANGE)


if __name__ == "__main__":
    unittest.main(verbosity=2)
