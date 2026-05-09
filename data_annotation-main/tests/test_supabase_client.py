"""Round-trip smoke test against a live Supabase project.

Skips automatically when SUPABASE_URL or SUPABASE_SERVICE_KEY are missing,
so plain `python -m unittest discover` stays green on a fresh checkout.

Run against a real project with::

    SUPABASE_URL=... SUPABASE_SERVICE_KEY=... \\
        python -m unittest tests.test_supabase_client
"""

from __future__ import annotations

import os
import unittest


def _has_credentials() -> bool:
    return bool(os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_SERVICE_KEY"))


@unittest.skipUnless(_has_credentials(), "Supabase credentials not set; skipping live round-trip.")
class SupabaseRoundTripTests(unittest.TestCase):
    def setUp(self) -> None:
        from data_annotation.db import SupabaseClient, DocumentRow

        self.client = SupabaseClient()
        self.DocumentRow = DocumentRow
        self._row_id: str | None = None

    def tearDown(self) -> None:
        if self._row_id is not None:
            self.client.delete(self._row_id)

    def test_insert_fetch_mark_processed(self) -> None:
        row = self.DocumentRow(
            source_name="smoke-test",
            content_payload="hello supabase",
            type_text=True,
            tone_formality=0.5,
        )

        inserted = self.client.insert(row)
        self.assertIn("id", inserted)
        self._row_id = inserted["id"]
        self.assertEqual(inserted["source_name"], "smoke-test")
        self.assertFalse(inserted["is_processed"])

        unprocessed_ids = {r["id"] for r in self.client.fetch_unprocessed(limit=200)}
        self.assertIn(self._row_id, unprocessed_ids)

        updated = self.client.mark_processed(self._row_id)
        self.assertTrue(updated["is_processed"])


if __name__ == "__main__":
    unittest.main()
