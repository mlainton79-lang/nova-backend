#!/usr/bin/env python3
"""Structural checks for Tony Green-Amber-Red Capability Policy v1."""

import ast
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from app.core import capability_policy as policy_module  # noqa: E402


REQUIRED_KEYS = {
    "chat.local_reasoning",
    "memory.read",
    "memory.low_risk_save",
    "drafts.review",
    "selling.draft_review",
    "selling.draft_list",
    "vinted.prepare_listing_draft_local",
    "fcm.register_device",
    "approval.create_external_action_request",
    "gmail.create_draft",
    "gmail.legacy_send",
    "gmail.legacy_delete_or_trash",
    "calendar.write_update_delete",
    "selling.draft_archive",
    "vinted.create_marketplace_job",
    "vinted.worker_handoff",
    "ebay.oauth_or_operator",
    "whatsapp.send_message",
    "notifications.non_approval_urgent",
    "code.self_modify_or_deploy",
    "vinted.post_listing",
    "vinted.browser_automation_autonomous",
    "vinted.buyer_message",
    "vinted.accept_offer",
    "vinted.change_live_price",
    "vinted.buy_postage",
    "vinted.payment_or_order_handling",
    "marketplace.scraping",
    "browser.real_account_automation_without_unlock",
    "banking.payment_or_transfer",
    "gmail.send_without_approval",
    "gmail.delete_without_approval",
    "calendar.write_without_approval",
    "external_write_without_approval",
    "broad_self_expansion_without_matthew_approval",
    "test.approval_resume",
    "test.approved_noop",
}


class CapabilityPolicyTests(unittest.TestCase):
    def test_policy_module_exists_and_lists_required_entries(self):
        policies = policy_module.list_capability_policy()
        keys = {policy.key for policy in policies}

        self.assertTrue(policies)
        self.assertTrue(REQUIRED_KEYS.issubset(keys))
        self.assertEqual(len(keys), len(policies))
        with self.assertRaises(TypeError):
            policy_module.CAPABILITY_POLICY["new.key"] = policies[0]

    def test_get_and_classify_helpers_are_safe_for_unknown_keys(self):
        self.assertIsNone(policy_module.get_capability_policy("missing.key"))
        self.assertIsNone(policy_module.classify_capability("missing.key"))
        self.assertEqual(
            policy_module.classify_capability("chat.local_reasoning"),
            policy_module.GREEN,
        )

    def test_green_actions_have_no_external_write_and_no_approval_requirement(self):
        for item in policy_module.list_capability_policy():
            if item.autonomy_class != policy_module.GREEN:
                continue
            self.assertFalse(item.external_action, item.key)
            self.assertFalse(item.approval_required, item.key)
            risk_text = item.risk_notes.lower()
            for phrase in (
                "no external write",
                "no user-facing external consequence",
                "read-only",
                "local",
                "internal",
            ):
                if phrase in risk_text:
                    break
            else:
                self.fail(f"green policy lacks local/read-only safety note: {item.key}")

    def test_red_actions_are_not_marked_autonomous(self):
        for item in policy_module.list_capability_policy():
            if item.autonomy_class == policy_module.RED:
                self.assertNotEqual(item.autonomy_class, policy_module.GREEN)
                self.assertTrue(item.approval_required, item.key)
                self.assertIn("refuse", item.recommended_next_state.lower())

    def test_amber_actions_require_approval(self):
        for item in policy_module.list_capability_policy():
            if item.autonomy_class == policy_module.AMBER:
                self.assertTrue(item.approval_required, item.key)

    def test_vinted_local_draft_is_green_and_worker_browser_automation_is_red(self):
        local = policy_module.get_capability_policy(
            "vinted.prepare_listing_draft_local"
        )
        worker = policy_module.get_capability_policy(
            "vinted.browser_automation_autonomous"
        )
        handoff = policy_module.get_capability_policy("vinted.worker_handoff")

        self.assertEqual(local.autonomy_class, policy_module.GREEN)
        self.assertFalse(local.external_action)
        self.assertIn("no Vinted account access", local.risk_notes)
        self.assertEqual(worker.autonomy_class, policy_module.RED)
        self.assertTrue(worker.external_action)
        self.assertEqual(handoff.autonomy_class, policy_module.AMBER)
        self.assertTrue(handoff.approval_required)

    def test_vinted_marketplace_consequences_are_red(self):
        for key in (
            "vinted.post_listing",
            "vinted.buyer_message",
            "vinted.accept_offer",
            "vinted.change_live_price",
            "vinted.buy_postage",
            "vinted.payment_or_order_handling",
        ):
            item = policy_module.get_capability_policy(key)
            self.assertEqual(item.autonomy_class, policy_module.RED, key)
            self.assertTrue(item.external_action, key)

    def test_gmail_create_draft_is_amber_and_legacy_gmail_writes_are_not_green(self):
        draft = policy_module.get_capability_policy("gmail.create_draft")
        send = policy_module.get_capability_policy("gmail.legacy_send")
        delete = policy_module.get_capability_policy("gmail.legacy_delete_or_trash")

        self.assertEqual(draft.autonomy_class, policy_module.AMBER)
        self.assertTrue(draft.approval_required)
        self.assertFalse(draft.connected)
        for item in (send, delete):
            self.assertNotEqual(item.autonomy_class, policy_module.GREEN)
            self.assertTrue(item.external_action)
            self.assertTrue(item.approval_required)

    def test_calendar_write_and_banking_payment_are_not_green(self):
        calendar = policy_module.get_capability_policy("calendar.write_update_delete")
        banking = policy_module.get_capability_policy("banking.payment_or_transfer")

        self.assertEqual(calendar.autonomy_class, policy_module.AMBER)
        self.assertNotEqual(calendar.autonomy_class, policy_module.GREEN)
        self.assertEqual(banking.autonomy_class, policy_module.RED)
        self.assertNotEqual(banking.autonomy_class, policy_module.GREEN)

    def test_existing_safe_test_capabilities_remain_test_only(self):
        for key in ("test.approval_resume", "test.approved_noop"):
            item = policy_module.get_capability_policy(key)
            self.assertEqual(item.autonomy_class, policy_module.TEST_ONLY)
            self.assertTrue(item.approval_required)
            self.assertFalse(item.external_action)
            self.assertIn("Test-only", item.human_name)

    def test_policy_covers_known_dangerous_surface_terms(self):
        terms = (
            "vinted",
            "gmail",
            "calendar",
            "banking",
            "ebay",
            "whatsapp",
            "browser",
            "worker",
            "notification",
            "approval",
        )
        keys_and_notes = "\n".join(
            f"{item.key} {item.current_runtime_surface} {item.risk_notes}"
            for item in policy_module.list_capability_policy()
        ).lower()
        for term in terms:
            self.assertIn(term, keys_and_notes)

    def test_policy_module_imports_no_external_integrations(self):
        with open(policy_module.__file__, encoding="utf-8") as source_file:
            tree = ast.parse(source_file.read())

        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.append(node.module or "")

        self.assertEqual(sorted(imports), ["dataclasses", "types"])

    def test_policy_entries_do_not_expose_private_identifier_terms(self):
        prohibited = (
            "pending_id",
            "approval_challenge",
            "action_hash",
            "grant_id",
            "token",
            "secret",
            "oauth material",
            "raw gmail payload",
            "request body",
            "database_url",
            "authorization header",
        )
        for item in policy_module.list_capability_policy():
            text = " ".join(
                (
                    item.key,
                    item.human_name,
                    item.risk_notes,
                    item.current_runtime_surface,
                    item.recommended_next_state,
                )
            ).lower()
            for term in prohibited:
                self.assertNotIn(term, text, item.key)


if __name__ == "__main__":
    unittest.main()
