from __future__ import annotations

import unittest

from glee_eval.adapters.glee_env import check_official_adapter
from glee_eval.audit import generate_audit_markdown


class AuditAdapterTests(unittest.TestCase):
    def test_audit_markdown_contains_sections(self) -> None:
        markdown = generate_audit_markdown()
        self.assertIn("Bargaining", markdown)
        self.assertIn("Negotiation", markdown)
        self.assertIn("Persuasion", markdown)

    def test_adapter_status_is_structured(self) -> None:
        status = check_official_adapter()
        self.assertIsInstance(status.available, bool)
        self.assertTrue(status.glee_root)


if __name__ == "__main__":
    unittest.main()

