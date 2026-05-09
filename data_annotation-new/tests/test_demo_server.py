import unittest

from data_annotation import demo_poc
from data_annotation.demo_server import asset_preview, openneuro_source_url


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


if __name__ == "__main__":
    unittest.main()
