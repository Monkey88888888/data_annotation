"""Text-archetype workflow surface.

Mirrors the *spirit* of the fMRI workflow (Setup -> Annotate -> Review)
without reintroducing the human-in-the-loop assignment queue we
deliberately skipped for text/visual archetypes.

Project state piggybacks on demo_poc's existing state dict: text projects
live in ``state["projects"]`` with ``archetype_id == "text_document"``
so the snapshot endpoint can surface them.

Heavier reads (recent annotations, quality, retrieval) come from Supabase
not local state.
"""

from __future__ import annotations

from typing import Any

from data_annotation import demo_poc


ARCHETYPE_ID = "text_document"


# ---------------------------------------------------------------------------
# Project intake
# ---------------------------------------------------------------------------

def propose_project(state: dict[str, Any], request_text: str) -> dict[str, Any]:
    """Create a lightweight text project. Mirrors propose_project_from_request
    in demo_poc but skips the fMRI-specific dataset_items/task_specs setup --
    text projects are populated by the LLM annotator, not pre-seeded."""
    if not request_text.strip():
        raise ValueError("request_text is required")
    now = demo_poc.utc_now()
    project_id = demo_poc.short_id("text")
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
    state["meta"]["active_text_project_id"] = project_id
    demo_poc.touch_state(state)
    demo_poc.add_activity(
        state,
        "Text project created",
        project["name"],
        project_id,
    )
    return project


def list_projects(state: dict[str, Any]) -> list[dict[str, Any]]:
    return _filter_projects(state, ARCHETYPE_ID)


def _infer_name(request_text: str) -> str:
    head = request_text.strip().splitlines()[0] if request_text.strip() else ""
    head = head.strip().rstrip(".")
    return (head[:80] or "Text annotation project").strip()


def _infer_objective(request_text: str) -> str:
    text = request_text.strip().replace("\n", " ")
    return (text[:160] or "Annotate and retrieve text assets.").strip()


# ---------------------------------------------------------------------------
# Snapshot (UI pulls this for the Setup + Annotate pages)
# ---------------------------------------------------------------------------

def snapshot(state: dict[str, Any], supabase_client: Any | None = None) -> dict[str, Any]:
    """Compose what the text workspace needs in one round-trip:
    projects (filtered), recent annotations, recent activity."""
    return {
        "archetype_id": ARCHETYPE_ID,
        "projects": list_projects(state),
        "active_project_id": state.get("meta", {}).get("active_text_project_id"),
        "activity": _activity_for_archetype(state, ARCHETYPE_ID, limit=12),
        "recent_documents": _recent_documents(supabase_client, ARCHETYPE_ID, limit=10) if supabase_client else [],
    }


# ---------------------------------------------------------------------------
# Helpers shared between text + image workflows
# ---------------------------------------------------------------------------

def _filter_projects(state: dict[str, Any], archetype_id: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for project in state.get("projects", {}).values():
        if project.get("archetype_id") == archetype_id:
            out.append(project)
    out.sort(key=lambda p: p.get("created_at") or "", reverse=True)
    return out


def _activity_for_archetype(
    state: dict[str, Any],
    archetype_id: str,
    *,
    limit: int = 12,
) -> list[dict[str, Any]]:
    project_ids = {p["id"] for p in _filter_projects(state, archetype_id)}
    activity = state.get("activity", [])
    relevant = [
        entry for entry in activity
        if entry.get("project_id") in project_ids
        or entry.get("project_id") is None and archetype_id in (entry.get("title", "") + entry.get("detail", "")).lower()
    ]
    return list(reversed(relevant[-limit:]))


def _recent_documents(client: Any, archetype_id: str, *, limit: int = 10) -> list[dict[str, Any]]:
    """Pull the last N annotated rows for this archetype from Supabase."""
    try:
        result = (
            client._client.table("documents_raw")
            .select("id,source_name,content_payload,is_processed,is_indexed,created_at,modality_b2b_email,modality_landing_page,tone_formality,tone_aggressiveness,tone_creativity,strict_regulatory,strict_technicality")
            .eq("archetype_id", archetype_id)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
    except Exception:
        return []
    return [_compact_document(row) for row in (result.data or [])]


def _compact_document(row: dict[str, Any]) -> dict[str, Any]:
    payload = row.get("content_payload") or ""
    return {
        "id": row.get("id"),
        "source_name": row.get("source_name"),
        "snippet": payload[:160],
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
