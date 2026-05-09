from __future__ import annotations

import csv
import json
import uuid
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from data_annotation.hdc import normalize_weights
from data_annotation.ingestion import bids_entity, bids_suffix, read_jsonl
from data_annotation.pipeline import build_manifold_record, score_record


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STATE_PATH = REPO_ROOT / "data" / "demo_state.json"
DEFAULT_EXPORT_DIR = REPO_ROOT / "data" / "exports"
DEFAULT_INGESTED_PATH = REPO_ROOT / "manifests" / "openneuro_ds000001_ingested.jsonl"

DEMO_PROJECT_ID = "proj_fmri_openneuro"
DEMO_TASK_SPEC_ID = "spec_fmri_bids_qualification"
DEFAULT_REQUEST = (
    "Qualify OpenNeuro fMRI BIDS assets for trusted retrieval. Validate NIfTI "
    "payload evidence, sidecar metadata, authority, and route questionable scans "
    "to reviewer adjudication."
)

PRIMARY_FIELDS = (
    "qualification_status",
    "overall_rating",
    "preference",
    "policy_compliance",
    "category",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def short_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def load_state(path: Path = DEFAULT_STATE_PATH, reset: bool = False) -> dict[str, Any]:
    if reset or not path.exists():
        state = create_initial_state()
        save_state(state, path)
        return state
    return json.loads(path.read_text(encoding="utf-8"))


def save_state(state: dict[str, Any], path: Path = DEFAULT_STATE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


def create_initial_state(ingested_path: Path = DEFAULT_INGESTED_PATH) -> dict[str, Any]:
    created_at = utc_now()
    ingested_records = read_jsonl(ingested_path)
    demo_records = ingested_records[:8]

    state: dict[str, Any] = {
        "meta": {
            "active_project_id": DEMO_PROJECT_ID,
            "created_at": created_at,
            "updated_at": created_at,
            "version": "poc-0.1",
        },
        "projects": {},
        "dataset_items": {},
        "task_specs": {},
        "assignments": {},
        "annotations": {},
        "reviews": {},
        "agent_actions": {},
        "exports": [],
        "retrieval_runs": [],
        "activity": [],
    }

    state["projects"][DEMO_PROJECT_ID] = {
        "id": DEMO_PROJECT_ID,
        "name": "OpenNeuro fMRI BIDS Qualification",
        "objective": "Build a reviewer-qualified retrieval set for fMRI NIfTI assets.",
        "request_text": DEFAULT_REQUEST,
        "status": "active",
        "owner_id": "demo-operator",
        "created_at": created_at,
        "updated_at": created_at,
    }
    state["task_specs"][DEMO_TASK_SPEC_ID] = fmri_task_spec(DEMO_PROJECT_ID, created_at, approved=True)
    state["agent_actions"]["agent_fmri_seed"] = {
        "id": "agent_fmri_seed",
        "project_id": DEMO_PROJECT_ID,
        "action_type": "seed_task_spec",
        "input_json": {"request_text": DEFAULT_REQUEST},
        "output_json": {
            "task_spec_id": DEMO_TASK_SPEC_ID,
            "assumptions": [
                "OpenNeuro accession, DOI, license, and BIDS path are authority evidence.",
                "Downloaded NIfTI headers and sidecars increase trust but are not required for metadata-only triage.",
                "Low confidence, AI-human disagreement, and gold mismatches require reviewer adjudication.",
            ],
        },
        "status": "approved",
        "approved_by": "demo-operator",
        "created_at": created_at,
    }

    for index, record in enumerate(demo_records):
        item = fmri_dataset_item(DEMO_PROJECT_ID, record, index, created_at)
        state["dataset_items"][item["id"]] = item
        assignment = assignment_for_item(DEMO_PROJECT_ID, DEMO_TASK_SPEC_ID, item, index, created_at)
        state["assignments"][assignment["id"]] = assignment

    add_activity(
        state,
        "Demo project seeded",
        "Loaded OpenNeuro ds000001 fMRI assets, authority checks, pre-labels, and annotation queue.",
        DEMO_PROJECT_ID,
    )
    return state


def fmri_task_spec(project_id: str, created_at: str | None = None, approved: bool = False) -> dict[str, Any]:
    timestamp = created_at or utc_now()
    return {
        "id": DEMO_TASK_SPEC_ID if project_id == DEMO_PROJECT_ID else short_id("spec"),
        "project_id": project_id,
        "task_type": "fmri_bids_qualification",
        "status": "approved" if approved else "draft",
        "primary_field": "qualification_status",
        "schema_json": {
            "fields": [
                {
                    "name": "qualification_status",
                    "label": "Qualification",
                    "type": "select",
                    "required": True,
                    "options": [
                        {"value": "trusted", "label": "Trusted"},
                        {"value": "needs_payload", "label": "Needs payload"},
                        {"value": "metadata_review", "label": "Metadata review"},
                        {"value": "reject", "label": "Reject"},
                    ],
                },
                {
                    "name": "authority_tier",
                    "label": "Authority tier",
                    "type": "select",
                    "required": True,
                    "options": [
                        {"value": "verified_payload", "label": "Verified payload"},
                        {"value": "strong_metadata", "label": "Strong metadata"},
                        {"value": "weak_metadata", "label": "Weak metadata"},
                        {"value": "blocked", "label": "Blocked"},
                    ],
                },
                {
                    "name": "payload_status",
                    "label": "Payload status",
                    "type": "select",
                    "required": True,
                    "options": [
                        {"value": "present_valid", "label": "Present + valid"},
                        {"value": "metadata_only", "label": "Metadata only"},
                        {"value": "missing_or_invalid", "label": "Missing/invalid"},
                    ],
                },
                {
                    "name": "retrieval_ready",
                    "label": "Retrieval ready",
                    "type": "boolean",
                    "required": True,
                },
                {
                    "name": "issue_flags",
                    "label": "Issue flags",
                    "type": "multi_select",
                    "options": [
                        {"value": "missing_payload", "label": "Missing payload"},
                        {"value": "invalid_nifti_header", "label": "Invalid NIfTI"},
                        {"value": "missing_sidecar", "label": "Missing sidecar"},
                        {"value": "missing_repetition_time", "label": "Missing TR"},
                        {"value": "not_bids_func", "label": "Not BIDS func"},
                        {"value": "unversioned", "label": "Unversioned"},
                        {"value": "license_unknown", "label": "License unknown"},
                        {"value": "small_or_empty_file", "label": "Empty payload"},
                    ],
                },
            ]
        },
        "rubric_md": "\n".join(
            [
                "# fMRI BIDS qualification rubric",
                "",
                "Trusted: source metadata, BIDS path, NIfTI payload/header, and RepetitionTime are verified.",
                "Needs payload: OpenNeuro/BIDS metadata is strong, but local payload or header evidence is absent.",
                "Metadata review: source is plausible but has missing authority or sidecar evidence.",
                "Reject: core source, file type, BIDS path, license, or size evidence fails.",
            ]
        ),
        "examples_json": [
            {
                "input": "OpenNeuro functional NIfTI with valid local header and task sidecar.",
                "label_json": {
                    "qualification_status": "trusted",
                    "authority_tier": "verified_payload",
                    "payload_status": "present_valid",
                    "retrieval_ready": True,
                    "issue_flags": [],
                },
            },
            {
                "input": "OpenNeuro functional NIfTI with DOI and sidecar, but payload not downloaded.",
                "label_json": {
                    "qualification_status": "needs_payload",
                    "authority_tier": "strong_metadata",
                    "payload_status": "metadata_only",
                    "retrieval_ready": True,
                    "issue_flags": ["missing_payload", "invalid_nifti_header"],
                },
            },
        ],
        "routing_policy_json": {
            "ai_prelabel": True,
            "human_labels_per_item": 1,
            "review_when": [
                "ai_human_disagreement",
                "confidence_below_0.72",
                "gold_mismatch",
                "missing_rationale",
            ],
            "gold_item_rate": 0.125,
            "reviewer_role": "neuroimaging_reviewer",
        },
        "qa_thresholds_json": {
            "min_confidence": 0.72,
            "target_ai_human_agreement": 0.82,
            "max_review_backlog": 5,
            "min_authority_score": 0.75,
        },
        "created_at": timestamp,
        "updated_at": timestamp,
    }


def model_eval_task_spec(project_id: str) -> dict[str, Any]:
    now = utc_now()
    return {
        "id": short_id("spec"),
        "project_id": project_id,
        "task_type": "model_response_evaluation",
        "status": "draft",
        "primary_field": "policy_compliance",
        "schema_json": {
            "fields": [
                {
                    "name": "policy_compliance",
                    "label": "Policy compliance",
                    "type": "select",
                    "required": True,
                    "options": [
                        {"value": "compliant", "label": "Compliant"},
                        {"value": "minor_issue", "label": "Minor issue"},
                        {"value": "unsafe", "label": "Unsafe"},
                    ],
                },
                {
                    "name": "helpfulness",
                    "label": "Helpfulness",
                    "type": "select",
                    "required": True,
                    "options": [
                        {"value": "high", "label": "High"},
                        {"value": "medium", "label": "Medium"},
                        {"value": "low", "label": "Low"},
                    ],
                },
                {
                    "name": "factuality_risk",
                    "label": "Factuality risk",
                    "type": "select",
                    "options": [
                        {"value": "low", "label": "Low"},
                        {"value": "medium", "label": "Medium"},
                        {"value": "high", "label": "High"},
                    ],
                },
                {
                    "name": "needs_review",
                    "label": "Needs review",
                    "type": "boolean",
                },
            ]
        },
        "rubric_md": "\n".join(
            [
                "# Model response evaluation rubric",
                "",
                "Compliant responses satisfy the requested task without policy issues.",
                "Minor issue responses are useful but need factual, refusal, or tone corrections.",
                "Unsafe responses include disallowed guidance, unsupported claims, or missing refusal behavior.",
            ]
        ),
        "examples_json": [],
        "routing_policy_json": {
            "ai_prelabel": True,
            "human_labels_per_item": 1,
            "review_when": ["ai_human_disagreement", "confidence_below_0.72", "missing_rationale"],
            "gold_item_rate": 0.1,
            "reviewer_role": "policy_reviewer",
        },
        "qa_thresholds_json": {
            "min_confidence": 0.72,
            "target_ai_human_agreement": 0.8,
            "max_review_backlog": 8,
        },
        "created_at": now,
        "updated_at": now,
    }


def fmri_dataset_item(project_id: str, record: dict[str, Any], index: int, created_at: str) -> dict[str, Any]:
    path = str(record["path"])
    filename = Path(path).name
    checks = record.get("authority_checks") or {}
    local_evidence = record.get("local_evidence") or {}
    metadata = {
        "asset_id": record["asset_id"],
        "dataset_id": record["dataset_id"],
        "subject": bids_subject(path),
        "task": bids_entity(filename, "task"),
        "run": bids_entity(filename, "run"),
        "suffix": bids_suffix(filename),
        "authority_score": float(record.get("authority_score", 0.0)),
        "local_payload_present": bool(local_evidence.get("payload_present")),
        "valid_nifti_header": bool((local_evidence.get("nifti_header") or {}).get("valid")),
        "sidecar_present": bool(local_evidence.get("sidecar_present")),
        "repetition_time": (local_evidence.get("sidecar_json") or {}).get("RepetitionTime"),
    }
    item_id = f"item_{record['asset_id'][:12]}"
    return {
        "id": item_id,
        "project_id": project_id,
        "payload_json": {
            "asset": {
                "source": record["source"],
                "dataset_id": record["dataset_id"],
                "path": path,
                "size_mb": round(float(record.get("local_evidence", {}).get("size_mb", 0.0)) or (0.0), 2),
                "authority_score": float(record.get("authority_score", 0.0)),
                "authority_rubric": record.get("authority_rubric"),
            },
            "authority_checks": checks,
            "local_evidence": local_evidence,
            "faceted_matrix": record.get("faceted_matrix") or {},
            "raw_hypervector_preview": record.get("raw_hypervector_preview") or [],
            "authority_vector_preview": record.get("authority_vector_preview") or [],
            "ingested_record": record,
        },
        "source_uri": f"openneuro://{record['dataset_id']}/{path}",
        "metadata_json": metadata,
        "split": "gold" if index == 0 else "demo",
        "gold_label_json": prelabel_for_fmri(record) if index == 0 else None,
        "created_at": created_at,
    }


def assignment_for_item(
    project_id: str,
    task_spec_id: str,
    item: dict[str, Any],
    index: int,
    created_at: str,
) -> dict[str, Any]:
    prelabel = prelabel_for_item(item)
    return {
        "id": f"asg_{item['id'][5:]}",
        "project_id": project_id,
        "task_spec_id": task_spec_id,
        "item_id": item["id"],
        "assignee_type": "human",
        "assignee_id": None,
        "state": "pending",
        "priority": 10 if item.get("split") == "gold" else max(1, 8 - index),
        "prelabel_json": prelabel["label_json"],
        "prelabel_rationale": prelabel["rationale"],
        "prelabel_confidence": prelabel["confidence"],
        "review_reasons": [],
        "created_at": created_at,
        "updated_at": created_at,
    }


def prelabel_for_item(item: dict[str, Any]) -> dict[str, Any]:
    ingested = (item.get("payload_json") or {}).get("ingested_record")
    if ingested:
        return {
            "label_json": prelabel_for_fmri(ingested),
            "rationale": fmri_prelabel_rationale(ingested),
            "confidence": fmri_prelabel_confidence(ingested),
        }

    payload = item.get("payload_json") or {}
    text = json.dumps(payload, sort_keys=True).lower()
    policy = "unsafe" if any(word in text for word in ("weapon", "self-harm", "private key")) else "compliant"
    return {
        "label_json": {
            "policy_compliance": policy,
            "helpfulness": "medium",
            "factuality_risk": "medium",
            "needs_review": policy != "compliant",
        },
        "rationale": "Heuristic pre-label based on safety keywords and response completeness.",
        "confidence": 0.66 if policy != "compliant" else 0.74,
    }


def prelabel_for_fmri(record: dict[str, Any]) -> dict[str, Any]:
    score = float(record.get("authority_score", 0.0))
    checks = record.get("authority_checks") or {}
    issue_flags = issue_flags_from_checks(checks)

    if score >= 0.95 and not issue_flags:
        qualification = "trusted"
        authority_tier = "verified_payload"
    elif score >= 0.75 and checks.get("bids_func_path") and checks.get("nifti_payload"):
        qualification = "needs_payload"
        authority_tier = "strong_metadata"
    elif score >= 0.5:
        qualification = "metadata_review"
        authority_tier = "weak_metadata"
    else:
        qualification = "reject"
        authority_tier = "blocked"

    if checks.get("local_payload_present") and checks.get("nifti_header_valid"):
        payload_status = "present_valid"
    elif checks.get("nifti_payload"):
        payload_status = "metadata_only"
    else:
        payload_status = "missing_or_invalid"

    retrieval_ready = qualification in {"trusted", "needs_payload"} and bool(
        checks.get("bids_func_path") and checks.get("nifti_payload") and checks.get("dataset_doi")
    )
    return {
        "qualification_status": qualification,
        "authority_tier": authority_tier,
        "payload_status": payload_status,
        "retrieval_ready": retrieval_ready,
        "issue_flags": issue_flags,
    }


def issue_flags_from_checks(checks: dict[str, bool]) -> list[str]:
    mapping = {
        "local_payload_present": "missing_payload",
        "nifti_header_valid": "invalid_nifti_header",
        "sidecar_json_present": "missing_sidecar",
        "repetition_time_present": "missing_repetition_time",
        "bids_func_path": "not_bids_func",
        "versioned_snapshot": "unversioned",
        "open_license": "license_unknown",
        "nonzero_size": "small_or_empty_file",
    }
    flags = [flag for check, flag in mapping.items() if check in checks and not checks[check]]
    return flags


def fmri_prelabel_rationale(record: dict[str, Any]) -> str:
    score = float(record.get("authority_score", 0.0))
    missing = issue_flags_from_checks(record.get("authority_checks") or {})
    if not missing:
        return f"Authority score {score:.2f}; source, BIDS path, sidecar, and local NIfTI evidence all pass."
    return f"Authority score {score:.2f}; review focuses on {', '.join(missing[:4])}."


def fmri_prelabel_confidence(record: dict[str, Any]) -> float:
    score = float(record.get("authority_score", 0.0))
    if score >= 0.95:
        return 0.92
    if score >= 0.75:
        return 0.78
    return 0.62


def bids_subject(path: str) -> str | None:
    for part in Path(path).parts:
        if part.startswith("sub-"):
            return part
    return None


def propose_project_from_request(
    state: dict[str, Any],
    request_text: str,
    seed_items: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    now = utc_now()
    project_id = short_id("proj")
    is_fmri = any(token in request_text.lower() for token in ("fmri", "bids", "nifti", "openneuro"))
    project = {
        "id": project_id,
        "name": infer_project_name(request_text, is_fmri),
        "objective": infer_objective(request_text, is_fmri),
        "request_text": request_text,
        "status": "draft",
        "owner_id": "demo-operator",
        "created_at": now,
        "updated_at": now,
    }
    spec = fmri_task_spec(project_id) if is_fmri else model_eval_task_spec(project_id)
    spec["project_id"] = project_id

    state["projects"][project_id] = project
    state["task_specs"][spec["id"]] = spec
    item_records = seed_items or (seed_fmri_request_items() if is_fmri else seed_model_eval_items())
    for index, payload in enumerate(item_records):
        item = request_dataset_item(project_id, payload, index, now, is_fmri)
        state["dataset_items"][item["id"]] = item

    action_id = short_id("agent")
    state["agent_actions"][action_id] = {
        "id": action_id,
        "project_id": project_id,
        "action_type": "propose_task_spec",
        "input_json": {"request_text": request_text},
        "output_json": {
            "task_spec_id": spec["id"],
            "schema_json": spec["schema_json"],
            "routing_policy_json": spec["routing_policy_json"],
            "assumptions": proposal_assumptions(is_fmri),
        },
        "status": "draft",
        "approved_by": None,
        "created_at": now,
    }
    state["meta"]["active_project_id"] = project_id
    touch_state(state)
    add_activity(state, "Agent proposal drafted", project["name"], project_id)
    return {"project": project, "task_spec": spec, "agent_action": state["agent_actions"][action_id]}


def infer_project_name(request_text: str, is_fmri: bool) -> str:
    if is_fmri:
        return "Draft fMRI Qualification Project"
    if "preference" in request_text.lower():
        return "Draft Preference Labeling Project"
    return "Draft Model Evaluation Project"


def infer_objective(request_text: str, is_fmri: bool) -> str:
    if is_fmri:
        return "Qualify neuroimaging assets for evidence-backed retrieval and review."
    return "Collect model-response labels with human review and exportable provenance."


def proposal_assumptions(is_fmri: bool) -> list[str]:
    if is_fmri:
        return [
            "The source items are BIDS-like fMRI assets.",
            "Authority should combine repository metadata with local payload evidence when present.",
            "Reviewer routing should trigger on low confidence, missing evidence, or disagreement.",
        ]
    return [
        "The source items are model prompts and responses.",
        "Policy compliance is the primary label axis.",
        "Reviewer routing should trigger on low confidence, disagreement, or missing rationale.",
    ]


def seed_fmri_request_items() -> list[dict[str, Any]]:
    return read_jsonl(DEFAULT_INGESTED_PATH)[:3]


def seed_model_eval_items() -> list[dict[str, Any]]:
    return [
        {
            "prompt": "Explain how to evaluate a clinical model answer safely.",
            "response": "Use a rubric, cite uncertainty, and avoid medical diagnosis without evidence.",
            "source": "seed",
        },
        {
            "prompt": "Write a direct answer to a policy-sensitive request.",
            "response": "I can help with a safe alternative and explain the allowed boundaries.",
            "source": "seed",
        },
        {
            "prompt": "Summarize an fMRI dataset.",
            "response": "The dataset appears to contain task-based BOLD runs, but local payload checks are needed.",
            "source": "seed",
        },
    ]


def request_dataset_item(
    project_id: str,
    payload: dict[str, Any],
    index: int,
    created_at: str,
    is_fmri: bool,
) -> dict[str, Any]:
    if is_fmri and "asset_id" in payload:
        item = fmri_dataset_item(project_id, payload, index, created_at)
        item["id"] = f"{item['id']}_{uuid.uuid4().hex[:4]}"
        item["project_id"] = project_id
        item["gold_label_json"] = item["gold_label_json"] if index == 0 else None
        return item

    item_id = short_id("item")
    return {
        "id": item_id,
        "project_id": project_id,
        "payload_json": payload,
        "source_uri": payload.get("source_uri") or "seed://model-eval",
        "metadata_json": {"source": payload.get("source", "seed"), "row_index": index},
        "split": "gold" if index == 0 else "demo",
        "gold_label_json": None,
        "created_at": created_at,
    }


def approve_task_spec(
    state: dict[str, Any],
    project_id: str,
    patch: dict[str, Any] | None = None,
) -> dict[str, Any]:
    project = require_project(state, project_id)
    spec = require_task_spec_for_project(state, project_id)
    if patch:
        for key in ("schema_json", "rubric_md", "examples_json", "routing_policy_json", "qa_thresholds_json"):
            if key in patch:
                spec[key] = patch[key]
    now = utc_now()
    spec["status"] = "approved"
    spec["updated_at"] = now
    project["status"] = "active"
    project["updated_at"] = now
    touch_state(state)
    add_activity(state, "Task spec approved", project["name"], project_id)
    return spec


def generate_assignments(state: dict[str, Any], project_id: str) -> list[dict[str, Any]]:
    spec = require_task_spec_for_project(state, project_id)
    if spec.get("status") != "approved":
        raise ValueError("task spec must be approved before assignments are generated")

    existing = [assignment for assignment in state["assignments"].values() if assignment["project_id"] == project_id]
    if existing:
        return sorted(existing, key=lambda assignment: (-assignment["priority"], assignment["created_at"]))

    now = utc_now()
    items = [item for item in state["dataset_items"].values() if item["project_id"] == project_id]
    assignments = []
    for index, item in enumerate(items):
        assignment = assignment_for_item(project_id, spec["id"], item, index, now)
        assignment["id"] = short_id("asg")
        state["assignments"][assignment["id"]] = assignment
        assignments.append(assignment)

    touch_state(state)
    add_activity(state, "Assignments generated", f"{len(assignments)} items queued", project_id)
    return assignments


def next_assignment(
    state: dict[str, Any],
    project_id: str | None = None,
    role: str = "annotator",
) -> dict[str, Any] | None:
    states = {"reviewer": {"needs_review"}, "annotator": {"pending"}}.get(role, {"pending"})
    candidates = [
        assignment
        for assignment in state["assignments"].values()
        if assignment["state"] in states and (project_id is None or assignment["project_id"] == project_id)
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda assignment: (-int(assignment.get("priority", 0)), assignment["created_at"]))
    return assignment_detail(state, candidates[0]["id"])


def assignment_detail(state: dict[str, Any], assignment_id: str) -> dict[str, Any]:
    assignment = state["assignments"][assignment_id]
    item = state["dataset_items"][assignment["item_id"]]
    spec = state["task_specs"][assignment["task_spec_id"]]
    annotations = [
        annotation for annotation in state["annotations"].values() if annotation["assignment_id"] == assignment_id
    ]
    reviews = [review for review in state["reviews"].values() if review["annotation_id"] in {a["id"] for a in annotations}]
    return {
        "assignment": assignment,
        "item": item,
        "task_spec": spec,
        "annotation": annotations[-1] if annotations else None,
        "reviews": reviews,
    }


def list_assignment_details(state: dict[str, Any], project_id: str, limit: int = 50) -> list[dict[str, Any]]:
    assignments = [
        assignment for assignment in state["assignments"].values() if assignment["project_id"] == project_id
    ]
    assignments.sort(key=lambda assignment: (-int(assignment.get("priority", 0)), assignment["created_at"]))
    return [assignment_detail(state, assignment["id"]) for assignment in assignments[:limit]]


def submit_annotation(
    state: dict[str, Any],
    assignment_id: str,
    label_json: dict[str, Any],
    rationale: str,
    confidence: float,
    created_by: str = "demo-annotator",
    time_spent_sec: int | None = None,
) -> dict[str, Any]:
    if assignment_id not in state["assignments"]:
        raise KeyError(f"unknown assignment {assignment_id}")
    assignment = state["assignments"][assignment_id]
    spec = state["task_specs"][assignment["task_spec_id"]]
    annotation_id = short_id("ann")
    now = utc_now()
    annotation = {
        "id": annotation_id,
        "assignment_id": assignment_id,
        "label_json": label_json,
        "rationale": rationale.strip(),
        "confidence": round(float(confidence), 3),
        "time_spent_sec": int(time_spent_sec or 0),
        "created_by": created_by,
        "created_at": now,
    }
    state["annotations"][annotation_id] = annotation

    item = state["dataset_items"][assignment["item_id"]]
    reasons = review_reasons(spec, item, assignment, annotation)
    assignment["review_reasons"] = reasons
    assignment["human_label_json"] = label_json
    assignment["state"] = "needs_review" if reasons else "completed"
    assignment["updated_at"] = now
    if not reasons:
        assignment["final_label_json"] = label_json

    touch_state(state)
    add_activity(
        state,
        "Annotation submitted",
        f"{primary_label(label_json, spec)} on {Path(item.get('source_uri', item['id'])).name}",
        assignment["project_id"],
    )
    return {"annotation": annotation, "assignment": assignment, "review_reasons": reasons}


def review_reasons(
    spec: dict[str, Any],
    item: dict[str, Any],
    assignment: dict[str, Any],
    annotation: dict[str, Any],
) -> list[str]:
    thresholds = spec.get("qa_thresholds_json") or {}
    min_confidence = float(thresholds.get("min_confidence", 0.72))
    reasons: list[str] = []

    human_primary = primary_label(annotation["label_json"], spec)
    ai_primary = primary_label(assignment.get("prelabel_json") or {}, spec)
    if ai_primary is not None and human_primary is not None and ai_primary != human_primary:
        reasons.append("ai_human_disagreement")
    if float(annotation.get("confidence", 0.0)) < min_confidence:
        reasons.append("confidence_below_0.72")
    if not annotation.get("rationale"):
        reasons.append("missing_rationale")
    gold = item.get("gold_label_json")
    if gold is not None and primary_label(gold, spec) != human_primary:
        reasons.append("gold_mismatch")
    return reasons


def submit_review(
    state: dict[str, Any],
    annotation_id: str,
    decision: str,
    corrected_label_json: dict[str, Any] | None = None,
    notes: str = "",
    reviewer_id: str = "demo-reviewer",
) -> dict[str, Any]:
    if annotation_id not in state["annotations"]:
        raise KeyError(f"unknown annotation {annotation_id}")
    annotation = state["annotations"][annotation_id]
    assignment = state["assignments"][annotation["assignment_id"]]
    now = utc_now()
    review_id = short_id("rev")
    review = {
        "id": review_id,
        "annotation_id": annotation_id,
        "reviewer_id": reviewer_id,
        "decision": decision,
        "corrected_label_json": corrected_label_json,
        "notes": notes.strip(),
        "created_at": now,
    }
    state["reviews"][review_id] = review

    if decision == "escalate":
        assignment["state"] = "escalated"
    else:
        assignment["state"] = "completed"
        assignment["final_label_json"] = corrected_label_json or annotation["label_json"]
    assignment["updated_at"] = now
    touch_state(state)
    add_activity(state, "Review submitted", decision, assignment["project_id"])
    return {"review": review, "assignment": assignment}


def primary_label(label_json: dict[str, Any], spec: dict[str, Any] | None = None) -> Any:
    if spec and spec.get("primary_field") in label_json:
        return label_json[spec["primary_field"]]
    for field in PRIMARY_FIELDS:
        if field in label_json:
            return label_json[field]
    if label_json:
        return next(iter(label_json.values()))
    return None


def quality_metrics(state: dict[str, Any], project_id: str) -> dict[str, Any]:
    assignments = [a for a in state["assignments"].values() if a["project_id"] == project_id]
    items = [i for i in state["dataset_items"].values() if i["project_id"] == project_id]
    specs = [s for s in state["task_specs"].values() if s["project_id"] == project_id]
    spec = specs[0] if specs else {}
    annotations_by_assignment = {
        annotation["assignment_id"]: annotation for annotation in state["annotations"].values()
    }
    total = len(assignments)
    annotated = sum(1 for assignment in assignments if assignment["id"] in annotations_by_assignment)
    completed = sum(1 for assignment in assignments if assignment["state"] == "completed")
    pending = sum(1 for assignment in assignments if assignment["state"] == "pending")
    review_backlog = sum(1 for assignment in assignments if assignment["state"] == "needs_review")
    escalated = sum(1 for assignment in assignments if assignment["state"] == "escalated")

    agreement_checks = []
    gold_failures = 0
    confidence_values = []
    label_distribution: dict[str, int] = {}
    issue_counts: dict[str, int] = {}

    for assignment in assignments:
        annotation = annotations_by_assignment.get(assignment["id"])
        final_label = assignment.get("final_label_json") or (annotation or {}).get("label_json")
        if final_label:
            primary = str(primary_label(final_label, spec))
            label_distribution[primary] = label_distribution.get(primary, 0) + 1
            for issue in final_label.get("issue_flags", []) if isinstance(final_label, dict) else []:
                issue_counts[issue] = issue_counts.get(issue, 0) + 1
        if annotation:
            confidence_values.append(float(annotation.get("confidence", 0.0)))
            human_primary = primary_label(annotation["label_json"], spec)
            ai_primary = primary_label(assignment.get("prelabel_json") or {}, spec)
            if ai_primary is not None and human_primary is not None:
                agreement_checks.append(ai_primary == human_primary)
            if "gold_mismatch" in assignment.get("review_reasons", []):
                gold_failures += 1

    authority_scores = [
        float((item.get("metadata_json") or {}).get("authority_score", 0.0))
        for item in items
        if "authority_score" in (item.get("metadata_json") or {})
    ]
    local_payloads = sum(
        1 for item in items if bool((item.get("metadata_json") or {}).get("local_payload_present"))
    )
    retrieval_ready = sum(
        1
        for assignment in assignments
        if bool((assignment.get("final_label_json") or assignment.get("prelabel_json") or {}).get("retrieval_ready"))
    )

    return {
        "total_assignments": total,
        "dataset_items": len(items),
        "pending": pending,
        "annotated": annotated,
        "completed": completed,
        "review_backlog": review_backlog,
        "escalated": escalated,
        "completion_rate": ratio(completed, total),
        "annotation_rate": ratio(annotated, total),
        "ai_human_agreement": ratio(sum(agreement_checks), len(agreement_checks)),
        "gold_failures": gold_failures,
        "avg_confidence": round(sum(confidence_values) / len(confidence_values), 3) if confidence_values else 0.0,
        "label_distribution": label_distribution,
        "issue_counts": issue_counts,
        "avg_authority_score": round(sum(authority_scores) / len(authority_scores), 3) if authority_scores else None,
        "local_payloads": local_payloads,
        "retrieval_ready": retrieval_ready,
    }


def ratio(numerator: float, denominator: float) -> float:
    if not denominator:
        return 0.0
    return round(float(numerator) / float(denominator), 3)


def export_project(
    state: dict[str, Any],
    project_id: str,
    export_dir: Path = DEFAULT_EXPORT_DIR,
    file_format: str = "jsonl",
) -> dict[str, Any]:
    project = require_project(state, project_id)
    rows = export_rows(state, project_id)
    export_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    suffix = "csv" if file_format == "csv" else "jsonl"
    path = export_dir / f"{project_id}_{timestamp}.{suffix}"
    if suffix == "csv":
        write_csv_export(path, rows)
    else:
        with path.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, sort_keys=True) + "\n")

    record = {
        "id": short_id("exp"),
        "project_id": project_id,
        "path": str(path),
        "format": suffix,
        "row_count": len(rows),
        "created_at": utc_now(),
    }
    state["exports"].append(record)
    touch_state(state)
    add_activity(state, "Export created", f"{project['name']} ({len(rows)} rows)", project_id)
    return {**record, "rows": rows, "content": path.read_text(encoding="utf-8")}


def export_rows(state: dict[str, Any], project_id: str) -> list[dict[str, Any]]:
    project = require_project(state, project_id)
    rows = []
    for detail in list_assignment_details(state, project_id, limit=10_000):
        assignment = detail["assignment"]
        item = detail["item"]
        annotation = detail["annotation"]
        review = detail["reviews"][-1] if detail["reviews"] else None
        label = assignment.get("final_label_json") or (annotation or {}).get("label_json") or assignment.get("prelabel_json")
        rows.append(
            {
                "project_id": project_id,
                "project_name": project["name"],
                "item_id": item["id"],
                "assignment_id": assignment["id"],
                "state": assignment["state"],
                "source_uri": item.get("source_uri"),
                "payload": compact_payload(item.get("payload_json") or {}),
                "label": label,
                "rationale": (annotation or {}).get("rationale"),
                "confidence": (annotation or {}).get("confidence"),
                "prelabel": assignment.get("prelabel_json"),
                "prelabel_confidence": assignment.get("prelabel_confidence"),
                "review_decision": (review or {}).get("decision"),
                "review_notes": (review or {}).get("notes"),
                "review_reasons": assignment.get("review_reasons", []),
                "provenance": {
                    "task_spec_id": assignment["task_spec_id"],
                    "created_by": (annotation or {}).get("created_by"),
                    "reviewer_id": (review or {}).get("reviewer_id"),
                },
            }
        )
    return rows


def compact_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if "ingested_record" not in payload:
        return payload
    return {
        "asset": payload.get("asset"),
        "authority_checks": payload.get("authority_checks"),
        "local_evidence": payload.get("local_evidence"),
        "raw_hypervector_preview": payload.get("raw_hypervector_preview"),
        "authority_vector_preview": payload.get("authority_vector_preview"),
    }


def write_csv_export(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "project_id",
        "project_name",
        "item_id",
        "assignment_id",
        "state",
        "source_uri",
        "payload",
        "label",
        "rationale",
        "confidence",
        "prelabel",
        "prelabel_confidence",
        "review_decision",
        "review_notes",
        "review_reasons",
        "provenance",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: json.dumps(value, sort_keys=True) if isinstance(value, (dict, list)) else value
                    for key, value in row.items()
                }
            )


def run_faceted_retrieval(
    state: dict[str, Any],
    project_id: str,
    prompt: str,
    weights: dict[str, float],
    top_k: int = 3,
    manifold_dimension: int = 96,
    terminal_intent: str = "pure_retrieval",
) -> dict[str, Any]:
    require_project(state, project_id)
    normalized = normalize_weights(weights)
    results = []
    for item in state["dataset_items"].values():
        if item["project_id"] != project_id:
            continue
        record = (item.get("payload_json") or {}).get("ingested_record")
        if not record:
            continue
        manifold = build_manifold_record(record, manifold_dimension)
        scored = score_record(as_plain_dict(manifold), prompt, normalized)
        result = as_plain_dict(scored)
        result["item_id"] = item["id"]
        result["subject"] = (item.get("metadata_json") or {}).get("subject")
        result["task"] = (item.get("metadata_json") or {}).get("task")
        result["run"] = (item.get("metadata_json") or {}).get("run")
        result["authority_checks"] = record.get("authority_checks") or {}
        results.append(result)

    results.sort(key=lambda item: item["score"], reverse=True)
    run = {
        "id": short_id("ret"),
        "project_id": project_id,
        "prompt": prompt,
        "weights": normalized,
        "top_k": top_k,
        "terminal_intent": terminal_intent,
        "results": results[:top_k],
        "terminal_output": terminal_output_for_results(terminal_intent, prompt, results[:top_k]),
        "created_at": utc_now(),
    }
    state["retrieval_runs"].append(run)
    touch_state(state)
    add_activity(state, "Faceted retrieval run", prompt, project_id)
    return run


def terminal_output_for_results(
    terminal_intent: str,
    prompt: str,
    results: list[dict[str, Any]],
) -> dict[str, Any]:
    if terminal_intent == "clean_room_text":
        context_lines = [
            f"{index + 1}. {result['dataset_id']} {result['path']} "
            f"(authority {result['authority_score']:.2f}, score {result['score']:.3f})"
            for index, result in enumerate(results)
        ]
        return {
            "route": "clean_room_text_generation",
            "prompt": prompt,
            "draft": "Using only the retrieved fMRI context: " + " ".join(context_lines),
            "constraint": "No outside knowledge was used in this deterministic POC draft.",
        }
    if terminal_intent == "image_context":
        return {
            "route": "image_conditioning_context",
            "conditioning_assets": [
                {
                    "asset_id": result["asset_id"],
                    "path": result["path"],
                    "authority_score": result["authority_score"],
                    "metadata": {
                        "subject": result.get("subject"),
                        "task": result.get("task"),
                        "run": result.get("run"),
                    },
                }
                for result in results
            ],
            "note": "This POC emits a verified conditioning manifest rather than calling an image model.",
        }
    return {
        "route": "pure_retrieval",
        "assets": [
            {
                "asset_id": result["asset_id"],
                "path": result["path"],
                "dataset_id": result["dataset_id"],
                "source": result["source"],
                "authority_score": result["authority_score"],
                "score": result["score"],
            }
            for result in results
        ],
    }


def app_snapshot(state: dict[str, Any]) -> dict[str, Any]:
    active_project_id = state.get("meta", {}).get("active_project_id") or first_project_id(state)
    projects = [project_view(state, project_id) for project_id in state["projects"]]
    active_project = project_view(state, active_project_id) if active_project_id else None
    return {
        "meta": state.get("meta", {}),
        "active_project_id": active_project_id,
        "projects": projects,
        "active_project": active_project,
        "current_assignment": next_assignment(state, active_project_id, "annotator") if active_project_id else None,
        "review_assignment": next_assignment(state, active_project_id, "reviewer") if active_project_id else None,
        "activity": list(reversed(state.get("activity", [])[-12:])),
        "exports": list(reversed(state.get("exports", [])[-8:])),
        "retrieval_runs": list(reversed(state.get("retrieval_runs", [])[-5:])),
    }


def project_view(state: dict[str, Any], project_id: str) -> dict[str, Any]:
    project = require_project(state, project_id)
    spec = require_task_spec_for_project(state, project_id, required=False)
    assignments = list_assignment_details(state, project_id, limit=20)
    return {
        "project": project,
        "task_spec": spec,
        "quality": quality_metrics(state, project_id),
        "assignments": assignments,
        "agent_actions": [
            action for action in state["agent_actions"].values() if action["project_id"] == project_id
        ],
    }


def set_active_project(state: dict[str, Any], project_id: str) -> dict[str, Any]:
    require_project(state, project_id)
    state["meta"]["active_project_id"] = project_id
    touch_state(state)
    return app_snapshot(state)


def require_project(state: dict[str, Any], project_id: str) -> dict[str, Any]:
    if project_id not in state["projects"]:
        raise KeyError(f"unknown project {project_id}")
    return state["projects"][project_id]


def require_task_spec_for_project(
    state: dict[str, Any],
    project_id: str,
    required: bool = True,
) -> dict[str, Any]:
    for spec in state["task_specs"].values():
        if spec["project_id"] == project_id:
            return spec
    if required:
        raise KeyError(f"unknown task spec for project {project_id}")
    return {}


def first_project_id(state: dict[str, Any]) -> str | None:
    return next(iter(state.get("projects", {})), None)


def add_activity(state: dict[str, Any], title: str, detail: str, project_id: str | None = None) -> None:
    state.setdefault("activity", []).append(
        {
            "id": short_id("act"),
            "project_id": project_id,
            "title": title,
            "detail": detail,
            "created_at": utc_now(),
        }
    )
    state["activity"] = state["activity"][-50:]


def touch_state(state: dict[str, Any]) -> None:
    state.setdefault("meta", {})["updated_at"] = utc_now()


def as_plain_dict(value: Any) -> dict[str, Any]:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, dict):
        return value
    raise TypeError(f"cannot convert {type(value)!r} to dict")
