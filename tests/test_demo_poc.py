import tempfile
import unittest
from pathlib import Path

from data_annotation import demo_poc


class DemoPocTests(unittest.TestCase):
    def test_initial_state_seeds_fmri_project_and_queue(self):
        state = demo_poc.create_initial_state()

        self.assertIn(demo_poc.DEMO_PROJECT_ID, state["projects"])
        self.assertEqual(len(state["dataset_items"]), 8)
        self.assertEqual(len(state["assignments"]), 8)
        self.assertEqual(
            demo_poc.next_assignment(state, demo_poc.DEMO_PROJECT_ID)["assignment"]["state"],
            "pending",
        )

    def test_annotation_review_and_export_flow(self):
        state = demo_poc.create_initial_state()
        next_task = demo_poc.next_assignment(state, demo_poc.DEMO_PROJECT_ID)
        assignment_id = next_task["assignment"]["id"]

        result = demo_poc.submit_annotation(
            state,
            assignment_id,
            {
                "qualification_status": "reject",
                "authority_tier": "blocked",
                "payload_status": "missing_or_invalid",
                "retrieval_ready": False,
                "issue_flags": ["missing_payload"],
            },
            "Conflicting gold label for test coverage.",
            0.61,
        )

        self.assertEqual(result["assignment"]["state"], "needs_review")
        self.assertIn("gold_mismatch", result["review_reasons"])

        review = demo_poc.submit_review(
            state,
            result["annotation"]["id"],
            "correct",
            corrected_label_json=next_task["assignment"]["prelabel_json"],
            notes="Use verified gold label.",
        )
        self.assertEqual(review["assignment"]["state"], "completed")

        with tempfile.TemporaryDirectory() as tmp:
            export = demo_poc.export_project(
                state,
                demo_poc.DEMO_PROJECT_ID,
                Path(tmp),
                "jsonl",
            )

        self.assertEqual(export["row_count"], 8)
        self.assertIn("OpenNeuro", export["content"])

    def test_proposal_approval_and_assignment_generation(self):
        state = demo_poc.create_initial_state()
        proposal = demo_poc.propose_project_from_request(
            state,
            "Collect preference and policy-compliance labels for these model answers.",
        )
        project_id = proposal["project"]["id"]

        self.assertEqual(proposal["task_spec"]["status"], "draft")
        demo_poc.approve_task_spec(state, project_id)
        assignments = demo_poc.generate_assignments(state, project_id)

        self.assertEqual(len(assignments), 3)
        self.assertEqual(state["projects"][project_id]["status"], "active")

    def test_faceted_retrieval_supports_terminal_routes(self):
        state = demo_poc.create_initial_state()

        run = demo_poc.run_faceted_retrieval(
            state,
            demo_poc.DEMO_PROJECT_ID,
            "high authority fMRI balloon risk task",
            {"authority": 1, "type": 1, "modality": 1, "strictness": 1, "tone": 0.2},
            terminal_intent="clean_room_text",
        )

        self.assertEqual(run["terminal_output"]["route"], "clean_room_text_generation")
        self.assertEqual(len(run["results"]), 3)


if __name__ == "__main__":
    unittest.main()
