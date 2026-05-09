import unittest

from data_annotation import demo_poc
from data_annotation.demo_server import asset_preview, heuristic_text_facets, openneuro_source_url


class DemoServerTests(unittest.TestCase):
    def test_openneuro_source_url_uses_public_s3_path(self):
        url = openneuro_source_url(
            "ds000001",
            "sub-15/func/sub-15_task-balloonanalogrisktask_run-02_bold.nii.gz",
        )

        self.assertEqual(
            url,
            "https://s3.amazonaws.com/openneuro.org/ds000001/sub-15/func/sub-15_task-balloonanalogrisktask_run-02_bold.nii.gz",
        )

    def test_asset_preview_returns_source_link_for_assignment_item(self):
        state = demo_poc.create_initial_state()
        item_id = next(iter(state["dataset_items"]))

        preview = asset_preview(state, item_id)

        self.assertEqual(preview["item_id"], item_id)
        self.assertTrue(preview["source_url"].startswith("https://s3.amazonaws.com/openneuro.org/ds000001/"))
        self.assertIn("local_payload_present", preview)

    def test_heuristic_text_facets_classifies_email(self):
        facets = heuristic_text_facets("Hi team, want to book a call about our API pipeline this week?")

        self.assertTrue(facets["type_text"])
        self.assertTrue(facets["modality_b2b_email"])
        self.assertFalse(facets["modality_landing_page"])
        self.assertGreater(facets["strict_technicality"], 0.0)

    def test_heuristic_text_facets_classifies_landing_page(self):
        facets = heuristic_text_facets("Start today. Explore features, pricing, and a landing page built for teams.")

        self.assertTrue(facets["modality_landing_page"])
        self.assertFalse(facets["modality_b2b_email"])


if __name__ == "__main__":
    unittest.main()
