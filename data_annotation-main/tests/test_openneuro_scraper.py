import unittest

from data_annotation.openneuro_scraper import is_functional_nifti


class OpenNeuroScraperTests(unittest.TestCase):
    def test_is_functional_nifti_accepts_bids_func_paths(self):
        self.assertTrue(is_functional_nifti("sub-01/func/sub-01_task-bart_bold.nii.gz"))
        self.assertTrue(is_functional_nifti("sub-01/func/sub-01_task-bart_bold.nii"))

    def test_is_functional_nifti_rejects_non_func_paths(self):
        self.assertFalse(is_functional_nifti("sub-01/anat/sub-01_T1w.nii.gz"))
        self.assertFalse(is_functional_nifti("sub-01/func/sub-01_task-bart_events.tsv"))


if __name__ == "__main__":
    unittest.main()
