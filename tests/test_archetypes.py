import unittest

from data_annotation.archetypes import Archetype, default_archetype_path


class ArchetypeTests(unittest.TestCase):
    def test_fmri_archetype_has_blueprint_facets(self):
        archetype = Archetype.from_file(default_archetype_path("fmri_scan"))

        self.assertEqual(archetype.id, "fmri_scan")
        self.assertEqual(
            [facet.name for facet in archetype.facets],
            [
                "authority_base",
                "type",
                "modality",
                "strictness",
                "tone",
            ],
        )

    def test_master_matrix_preview_is_deterministic(self):
        archetype = Archetype.from_file(default_archetype_path("fmri_scan"))

        self.assertEqual(archetype.master_matrix_preview(), archetype.master_matrix_preview())


if __name__ == "__main__":
    unittest.main()
