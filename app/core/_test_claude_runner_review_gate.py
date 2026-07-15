"""Tests for the Claude runner boundary and the two-seat cross-review gate."""
import os
import sys
import unittest

sys.path.insert(
    0,
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."),
)

from app.core import codex_runner  # noqa: E402
from app.core.claude_runner import (  # noqa: E402
    ClaudeRunnerMode,
    ClaudeRunnerRequest,
    DEFAULT_RUNNER_MODE,
    build_claude_prompt_from_task,
    build_disabled_claude_runner_result,
    can_claude_runner_execute_task,
    run_claude_task,
)
from app.core.codex_tasks import (  # noqa: E402
    CodexTaskStatus,
    create_codex_task_plan,
)
from app.core.review_gate import (  # noqa: E402
    BuildSeat,
    CrossReviewSpec,
    DO_NOT_SHIP_TOKEN,
    ReviewGateStatus,
    SHIP_TOKEN,
    assert_two_seat_rule,
    build_cross_review_spec,
    evaluate_review_outcome,
    parse_review_verdict,
    reviewer_for,
)


def _plan(goal: str = "Add a pure helper for calendar summaries"):
    return create_codex_task_plan(user_goal=goal)


def _raw_plan_with(goal: str):
    """Build a plan directly, bypassing the factory's own scope guard.

    This simulates a plan arriving from a path other than
    create_codex_task_plan so the runner boundary's second guard layer
    can be exercised on its own.
    """
    safe = _plan()
    from dataclasses import replace

    return replace(safe, user_goal=goal)


class ClaudeRunnerBoundaryTests(unittest.TestCase):
    def test_default_mode_is_disabled(self):
        self.assertEqual(DEFAULT_RUNNER_MODE, ClaudeRunnerMode.DISABLED)

    def test_disabled_mode_refuses_and_prepares_prompt(self):
        decision = can_claude_runner_execute_task(_plan())
        self.assertFalse(decision.execution_allowed)
        self.assertFalse(decision.claude_execution_invoked)
        self.assertEqual(decision.refusal_reason, "runner_disabled")
        self.assertTrue(decision.safe_prompt_prepared)
        self.assertGreater(decision.safe_prompt_length, 0)

    def test_every_mode_refuses_execution(self):
        for mode in ClaudeRunnerMode:
            decision = can_claude_runner_execute_task(_plan(), mode)
            self.assertFalse(decision.execution_allowed, mode)
            self.assertFalse(decision.claude_execution_invoked, mode)

    def test_unknown_mode_fails_closed(self):
        decision = can_claude_runner_execute_task(_plan(), "warp_speed")
        self.assertFalse(decision.execution_allowed)
        self.assertEqual(decision.refusal_reason, "unknown_runner_mode")
        self.assertFalse(decision.safe_prompt_prepared)

    def test_invalid_plan_fails_closed(self):
        decision = can_claude_runner_execute_task("not a plan")
        self.assertFalse(decision.execution_allowed)
        self.assertEqual(decision.task_id, "invalid_plan")
        self.assertEqual(decision.refusal_reason, "codex_task_plan_required")

    def test_blocked_terms_are_shared_with_codex_runner(self):
        self.assertIs(
            codex_runner.BLOCKED_PLAN_TERMS,
            codex_runner._BLOCKED_PLAN_TERMS,
        )
        plan = _raw_plan_with("Improve payment transfer handling for orders")
        claude_decision = can_claude_runner_execute_task(plan)
        codex_decision = codex_runner.can_runner_execute_task(plan)
        self.assertEqual(
            claude_decision.refusal_reason,
            "claude_runner_plan_scope_blocked",
        )
        self.assertEqual(
            codex_decision.refusal_reason,
            "codex_runner_plan_scope_blocked",
        )

    def test_prompt_has_claude_header_and_constraints(self):
        prompt = build_claude_prompt_from_task(_plan())
        self.assertTrue(
            prompt.startswith("Tony-managed Claude Code task (headless claude -p)")
        )
        self.assertIn("--allowedTools", prompt)
        self.assertIn("--max-turns", prompt)
        self.assertIn("--max-budget-usd", prompt)
        self.assertIn("never skip permissions", prompt)
        self.assertIn("Secret-printing bans:", prompt)
        self.assertNotIn("Tony-managed Codex task", prompt.splitlines()[0])

    def test_boundary_result_ready_to_report_when_prompt_prepared(self):
        result = build_disabled_claude_runner_result(_plan())
        self.assertEqual(result.status, CodexTaskStatus.READY_TO_REPORT)
        self.assertFalse(result.codex_execution_invoked)
        self.assertFalse(result.secrets_exposed)
        self.assertIn("claude_runner_execution_not_invoked", result.tests_summary)

    def test_boundary_result_failed_safe_on_blocked_plan(self):
        plan = _raw_plan_with("Adjust bank transfer flow")
        result = build_disabled_claude_runner_result(plan)
        self.assertEqual(result.status, CodexTaskStatus.FAILED_SAFE)

    def test_factory_itself_blocks_dangerous_scope_at_creation(self):
        # Layer one: dangerous scopes cannot even be planned via the
        # factory; the runner guard above is the second, independent layer.
        with self.assertRaises(ValueError):
            create_codex_task_plan(user_goal="Adjust bank transfer flow")

    def test_run_claude_task_accepts_request_and_bare_plan(self):
        plan = _plan()
        via_request = run_claude_task(ClaudeRunnerRequest(plan=plan))
        via_plan = run_claude_task(plan, ClaudeRunnerMode.DRY_RUN)
        self.assertEqual(via_request.decision.mode, "disabled")
        self.assertEqual(via_plan.decision.mode, "dry_run")
        self.assertFalse(via_request.decision.execution_allowed)
        self.assertFalse(via_plan.decision.execution_allowed)

    def test_decision_is_immutable(self):
        decision = can_claude_runner_execute_task(_plan())
        with self.assertRaises(Exception):
            decision.execution_allowed = True


class ReviewGateSeatTests(unittest.TestCase):
    def test_reviewer_is_always_the_opposite_seat(self):
        self.assertEqual(reviewer_for(BuildSeat.CLAUDE), BuildSeat.CODEX)
        self.assertEqual(reviewer_for(BuildSeat.CODEX), BuildSeat.CLAUDE)
        self.assertEqual(reviewer_for("claude"), BuildSeat.CODEX)
        self.assertEqual(reviewer_for("CODEX"), BuildSeat.CLAUDE)

    def test_unknown_seat_fails_closed(self):
        with self.assertRaises(ValueError):
            reviewer_for("gemini")

    def test_same_seat_rule_blocks(self):
        with self.assertRaises(ValueError):
            assert_two_seat_rule(BuildSeat.CLAUDE, BuildSeat.CLAUDE)
        with self.assertRaises(ValueError):
            assert_two_seat_rule("codex", "codex")
        assert_two_seat_rule("claude", "codex")
        assert_two_seat_rule(BuildSeat.CODEX, BuildSeat.CLAUDE)


class CrossReviewSpecTests(unittest.TestCase):
    def test_claude_implements_codex_reviews(self):
        spec = build_cross_review_spec(_plan(), BuildSeat.CLAUDE)
        self.assertEqual(spec.implementer_seat, "claude")
        self.assertEqual(spec.reviewer_seat, "codex")
        self.assertIn("codex review --base main", spec.reviewer_command_template)
        self.assertFalse(spec.execution_allowed)
        self.assertFalse(spec.review_invoked)

    def test_codex_implements_claude_reviews(self):
        spec = build_cross_review_spec(_plan(), "codex", base_branch="master")
        self.assertEqual(spec.implementer_seat, "codex")
        self.assertEqual(spec.reviewer_seat, "claude")
        self.assertIn("claude -p", spec.reviewer_command_template)
        self.assertIn("--allowedTools", spec.reviewer_command_template)
        self.assertIn("--max-turns", spec.reviewer_command_template)
        self.assertEqual(spec.base_branch, "master")

    def test_command_template_never_skips_permissions(self):
        for seat in (BuildSeat.CLAUDE, BuildSeat.CODEX):
            spec = build_cross_review_spec(_plan(), seat)
            self.assertNotIn("dangerously", spec.reviewer_command_template.lower())
            self.assertNotIn("--yolo", spec.reviewer_command_template.lower())

    def test_review_prompt_contains_verdict_protocol_and_bans(self):
        spec = build_cross_review_spec(_plan(), BuildSeat.CLAUDE)
        self.assertIn(SHIP_TOKEN, spec.review_prompt)
        self.assertIn(DO_NOT_SHIP_TOKEN, spec.review_prompt)
        self.assertIn("Secret-printing bans:", spec.review_prompt)
        self.assertIn("Blocked scope:", spec.review_prompt)

    def test_invalid_base_branch_fails_closed(self):
        with self.assertRaises(ValueError):
            build_cross_review_spec(_plan(), "claude", base_branch="main; rm -rf /")
        with self.assertRaises(ValueError):
            build_cross_review_spec(_plan(), "claude", base_branch="   ")

    def test_invalid_plan_fails_closed(self):
        with self.assertRaises(ValueError):
            build_cross_review_spec("not a plan", "claude")

    def test_spec_is_immutable(self):
        spec = build_cross_review_spec(_plan(), "claude")
        with self.assertRaises(Exception):
            spec.reviewer_seat = "claude"


class VerdictParsingTests(unittest.TestCase):
    def test_ship_passes(self):
        self.assertEqual(
            parse_review_verdict(f"Looks solid.\n{SHIP_TOKEN}"),
            ReviewGateStatus.REVIEW_PASSED,
        )

    def test_ship_is_case_insensitive(self):
        self.assertEqual(
            parse_review_verdict("all good\nverdict: ship"),
            ReviewGateStatus.REVIEW_PASSED,
        )

    def test_do_not_ship_fails(self):
        self.assertEqual(
            parse_review_verdict(f"Problems found.\n{DO_NOT_SHIP_TOKEN}"),
            ReviewGateStatus.REVIEW_FAILED,
        )

    def test_both_tokens_fail_closed(self):
        text = f"{SHIP_TOKEN}\nactually wait\n{DO_NOT_SHIP_TOKEN}"
        self.assertEqual(
            parse_review_verdict(text),
            ReviewGateStatus.REVIEW_FAILED,
        )

    def test_no_token_fails_closed(self):
        self.assertEqual(
            parse_review_verdict("This looks fine to me, ship it"),
            ReviewGateStatus.REVIEW_FAILED,
        )

    def test_empty_and_none_fail_closed(self):
        self.assertEqual(parse_review_verdict(""), ReviewGateStatus.REVIEW_FAILED)
        self.assertEqual(parse_review_verdict("   "), ReviewGateStatus.REVIEW_FAILED)
        self.assertEqual(parse_review_verdict(None), ReviewGateStatus.REVIEW_FAILED)


class ReviewOutcomeTests(unittest.TestCase):
    def test_ship_verdict_advances_to_tests(self):
        spec = build_cross_review_spec(_plan(), "claude")
        outcome = evaluate_review_outcome(spec, f"Reviewed.\n{SHIP_TOKEN}")
        self.assertEqual(outcome.status, ReviewGateStatus.REVIEW_PASSED)
        self.assertTrue(outcome.can_advance_to_tests)
        self.assertIsNone(outcome.refusal_reason)
        self.assertEqual(outcome.implementer_seat, "claude")
        self.assertEqual(outcome.reviewer_seat, "codex")

    def test_do_not_ship_blocks_tests(self):
        spec = build_cross_review_spec(_plan(), "codex")
        outcome = evaluate_review_outcome(spec, DO_NOT_SHIP_TOKEN)
        self.assertEqual(outcome.status, ReviewGateStatus.REVIEW_FAILED)
        self.assertFalse(outcome.can_advance_to_tests)
        self.assertEqual(outcome.refusal_reason, "reviewer_verdict_not_ship")

    def test_tampered_same_seat_spec_fails_closed(self):
        base = build_cross_review_spec(_plan(), "claude")
        tampered = CrossReviewSpec(
            task_id=base.task_id,
            implementer_seat="claude",
            reviewer_seat="claude",
            base_branch=base.base_branch,
            review_prompt=base.review_prompt,
            reviewer_command_template=base.reviewer_command_template,
            execution_allowed=False,
            review_invoked=False,
        )
        outcome = evaluate_review_outcome(tampered, SHIP_TOKEN)
        self.assertEqual(outcome.status, ReviewGateStatus.REVIEW_FAILED)
        self.assertFalse(outcome.can_advance_to_tests)
        self.assertEqual(outcome.refusal_reason, "same_seat_review_blocked")

    def test_invalid_spec_raises(self):
        with self.assertRaises(ValueError):
            evaluate_review_outcome("not a spec", SHIP_TOKEN)


if __name__ == "__main__":
    unittest.main()
