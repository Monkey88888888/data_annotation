"""Image-archetype workflow surface. Mirrors text_workflow.py.

Image projects piggyback on demo_poc state with
``archetype_id == "image_asset"``. Images themselves live as base64 in
``content_payload`` (or a URI for off-platform assets); for the demo we
keep upload payload-in-row simple. Production should swap to Supabase
Storage with a signed URL referenced from content_payload.
"""

from __future__ import annotations

from typing import Any

from data_annotation import demo_poc
from data_annotation.text_workflow import (
    _activity_for_archetype,
    _filter_projects,
)


ARCHETYPE_ID = "image_asset"


def propose_project(state: dict[str, Any], request_text: str) -> dict[str, Any]:
    if not request_text.strip():
        raise ValueError("request_text is required")
    now = demo_poc.utc_now()
    project_id = demo_poc.short_id("img")
    project = {
        "id": project_id,
        "archetype_id": ARCHETYPE_ID,
        "name": _infer_name(request_text),
        "objective": _infer_objective(request_text),
        "request_text": request_text,
        "status": "active",
        "owner_id": "demo-operator",
        "created_at": now,
        "updated_at": now,
    }
    state["projects"][project_id] = project
    state["meta"]["active_image_project_id"] = project_id
    demo_poc.touch_state(state)
    demo_poc.add_activity(
        state,
        "Image project created",
        project["name"],
        project_id,
    )
    return project


def list_projects(state: dict[str, Any]) -> list[dict[str, Any]]:
    return _filter_projects(state, ARCHETYPE_ID)


def snapshot(state: dict[str, Any], supabase_client: Any | None = None) -> dict[str, Any]:
    return {
        "archetype_id": ARCHETYPE_ID,
        "projects": list_projects(state),
        "active_project_id": state.get("meta", {}).get("active_image_project_id"),
        "activity": _activity_for_archetype(state, ARCHETYPE_ID, limit=12),
        "recent_documents": _recent_image_documents(supabase_client, limit=10) if supabase_client else [],
    }


def _infer_name(request_text: str) -> str:
    head = request_text.strip().splitlines()[0] if request_text.strip() else ""
    head = head.strip().rstrip(".")
    return (head[:80] or "Visual annotation project").strip()


def _infer_objective(request_text: str) -> str:
    text = request_text.strip().replace("\n", " ")
    return (text[:160] or "Annotate and retrieve image assets.").strip()


def _recent_image_documents(client: Any, *, limit: int = 10) -> list[dict[str, Any]]:
    try:
        result = (
            client._client.table("documents_raw")
            .select("id,source_name,is_processed,is_indexed,created_at,modality_b2b_email,modality_landing_page,tone_formality,tone_aggressiveness,tone_creativity,strict_regulatory,strict_technicality")
            .eq("archetype_id", ARCHETYPE_ID)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
    except Exception:
        return []
    return [
        {
            "id": row.get("id"),
            "source_name": row.get("source_name"),
            "is_processed": bool(row.get("is_processed")),
            "is_indexed": bool(row.get("is_indexed")),
            "created_at": row.get("created_at"),
            "facets": {
                "modality_b2b_email": row.get("modality_b2b_email"),
                "modality_landing_page": row.get("modality_landing_page"),
                "tone_formality": row.get("tone_formality"),
                "tone_aggressiveness": row.get("tone_aggressiveness"),
                "tone_creativity": row.get("tone_creativity"),
                "strict_regulatory": row.get("strict_regulatory"),
                "strict_technicality": row.get("strict_technicality"),
            },
        }
        for row in (result.data or [])
    ]
