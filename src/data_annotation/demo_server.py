from __future__ import annotations

import argparse
import gzip
import json
import mimetypes
import struct
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import base64

from dotenv import load_dotenv

from data_annotation import demo_poc, image_workflow, text_workflow
from data_annotation.annotator.image import annotate_image
from data_annotation.annotator.text import annotate_text


WEB_ROOT = Path(__file__).resolve().parent / "web"


class DemoRequestHandler(BaseHTTPRequestHandler):
    state_path = demo_poc.DEFAULT_STATE_PATH
    export_dir = demo_poc.DEFAULT_EXPORT_DIR

    server_version = "FMRIAnnotationPOC/0.1"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            self.handle_api_get(parsed.path, parse_qs(parsed.query))
            return
        self.serve_static(parsed.path)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if not parsed.path.startswith("/api/"):
            self.send_error(404)
            return
        self.handle_api_post(parsed.path, parse_qs(parsed.query))

    def handle_api_get(self, path: str, query: dict[str, list[str]]) -> None:
        try:
            state = demo_poc.load_state(self.state_path)
            segments = path_segments(path)
            if segments == ["api", "state"]:
                self.send_json(demo_poc.app_snapshot(state))
                return
            if segments == ["api", "text", "snapshot"]:
                self.send_json(text_workflow.snapshot(state, _safe_supabase_client()))
                return
            if segments == ["api", "image", "snapshot"]:
                self.send_json(image_workflow.snapshot(state, _safe_supabase_client()))
                return

            if len(segments) == 3 and segments[:2] == ["api", "document"]:
                self.send_json(_get_document(segments[2]))
                return
            if len(segments) == 4 and segments[:2] == ["api", "projects"] and segments[3] == "quality":
                self.send_json(demo_poc.quality_metrics(state, segments[2]))
                return
            if segments == ["api", "assignments", "next"]:
                project_id = single(query, "project_id") or state.get("meta", {}).get("active_project_id")
                role = single(query, "role") or "annotator"
                self.send_json(demo_poc.next_assignment(state, project_id, role) or {})
                return
            if len(segments) == 4 and segments[:2] == ["api", "assets"] and segments[3] == "preview":
                self.send_json(asset_preview(state, segments[2]))
                return
            self.send_error(404)
        except Exception as exc:  # pragma: no cover - exercised by browser.
            self.send_json({"error": str(exc)}, status=400)

    def handle_api_post(self, path: str, query: dict[str, list[str]]) -> None:
        try:
            state = demo_poc.load_state(self.state_path)
            payload = self.read_json()
            segments = path_segments(path)

            if segments == ["api", "reset"]:
                state = demo_poc.load_state(self.state_path, reset=True)
                self.send_json(demo_poc.app_snapshot(state))
                return

            if segments == ["api", "projects", "propose"]:
                request_text = str(payload.get("request_text") or "").strip()
                if not request_text:
                    raise ValueError("request_text is required")
                result = demo_poc.propose_project_from_request(state, request_text)
                demo_poc.save_state(state, self.state_path)
                self.send_json({"result": result, "snapshot": demo_poc.app_snapshot(state)})
                return

            if len(segments) == 4 and segments[:2] == ["api", "projects"] and segments[3] == "activate":
                snapshot = demo_poc.set_active_project(state, segments[2])
                demo_poc.save_state(state, self.state_path)
                self.send_json(snapshot)
                return

            if len(segments) == 4 and segments[:2] == ["api", "projects"] and segments[3] == "approve":
                spec = demo_poc.approve_task_spec(state, segments[2], payload.get("patch"))
                demo_poc.save_state(state, self.state_path)
                self.send_json({"task_spec": spec, "snapshot": demo_poc.app_snapshot(state)})
                return

            if len(segments) == 5 and segments[:2] == ["api", "projects"] and segments[3:] == ["assignments", "generate"]:
                assignments = demo_poc.generate_assignments(state, segments[2])
                demo_poc.save_state(state, self.state_path)
                self.send_json({"assignments": assignments, "snapshot": demo_poc.app_snapshot(state)})
                return

            if len(segments) == 4 and segments[:2] == ["api", "assignments"] and segments[3] == "annotations":
                result = demo_poc.submit_annotation(
                    state,
                    assignment_id=segments[2],
                    label_json=payload.get("label_json") or {},
                    rationale=str(payload.get("rationale") or ""),
                    confidence=float(payload.get("confidence", 0.0)),
                    created_by=str(payload.get("created_by") or "demo-annotator"),
                    time_spent_sec=int(payload.get("time_spent_sec") or 0),
                )
                demo_poc.save_state(state, self.state_path)
                self.send_json({"result": result, "snapshot": demo_poc.app_snapshot(state)})
                return

            if segments == ["api", "reviews"]:
                result = demo_poc.submit_review(
                    state,
                    annotation_id=str(payload.get("annotation_id") or ""),
                    decision=str(payload.get("decision") or "approve"),
                    corrected_label_json=payload.get("corrected_label_json"),
                    notes=str(payload.get("notes") or ""),
                    reviewer_id=str(payload.get("reviewer_id") or "demo-reviewer"),
                )
                demo_poc.save_state(state, self.state_path)
                self.send_json({"result": result, "snapshot": demo_poc.app_snapshot(state)})
                return

            if len(segments) == 4 and segments[:2] == ["api", "projects"] and segments[3] == "export":
                file_format = str(payload.get("format") or single(query, "format") or "jsonl")
                export = demo_poc.export_project(state, segments[2], self.export_dir, file_format)
                demo_poc.save_state(state, self.state_path)
                self.send_json({"export": export, "snapshot": demo_poc.app_snapshot(state)})
                return

            if len(segments) == 4 and segments[:2] == ["api", "projects"] and segments[3] == "retrieval":
                run = demo_poc.run_faceted_retrieval(
                    state,
                    project_id=segments[2],
                    prompt=str(payload.get("prompt") or "high authority fMRI balloon risk task"),
                    weights={
                        "authority": float(payload.get("authority_weight", 1.0)),
                        "type": float(payload.get("type_weight", 1.0)),
                        "modality": float(payload.get("modality_weight", 1.0)),
                        "strictness": float(payload.get("strictness_weight", 1.0)),
                        "tone": float(payload.get("tone_weight", 0.2)),
                    },
                    top_k=int(payload.get("top_k") or 3),
                    manifold_dimension=int(payload.get("manifold_dimension") or 96),
                    terminal_intent=str(payload.get("terminal_intent") or "pure_retrieval"),
                )
                demo_poc.save_state(state, self.state_path)
                self.send_json({"retrieval": run, "snapshot": demo_poc.app_snapshot(state)})
                return

            if segments == ["api", "text", "projects", "propose"]:
                request_text = str(payload.get("request_text") or "").strip()
                project = text_workflow.propose_project(state, request_text)
                demo_poc.save_state(state, self.state_path)
                self.send_json({
                    "project": project,
                    "snapshot": text_workflow.snapshot(state, _safe_supabase_client()),
                })
                return

            if segments == ["api", "image", "projects", "propose"]:
                request_text = str(payload.get("request_text") or "").strip()
                project = image_workflow.propose_project(state, request_text)
                demo_poc.save_state(state, self.state_path)
                self.send_json({
                    "project": project,
                    "snapshot": image_workflow.snapshot(state, _safe_supabase_client()),
                })
                return

            if len(segments) == 4 and segments[:2] == ["api", "document"] and segments[3] == "reannotate":
                self.send_json(_reannotate_document(segments[2]))
                return

            if len(segments) == 4 and segments[:2] == ["api", "document"] and segments[3] == "edit":
                self.send_json(_edit_document(segments[2], payload.get("facets") or {}))
                return

            if segments == ["api", "text", "save"]:
                self.send_json(_save_text_document(payload))
                return

            if segments == ["api", "image", "save"]:
                self.send_json(_save_image_document(payload))
                return

            if segments == ["api", "text", "annotate"]:
                text = str(payload.get("text") or "").strip()
                if not text:
                    raise ValueError("text is required")
                result = annotate_text(text, client=HeuristicTextClient())
                self.send_json({"annotation": result.to_db_row(), "text_length": len(text)})
                return

            if segments == ["api", "text", "search"]:
                self.send_json(_run_search(payload, archetype_filter="text_document"))
                return

            if segments == ["api", "text", "generate"]:
                self.send_json(_run_text_generate(payload))
                return

            if segments == ["api", "image", "annotate"]:
                self.send_json(_run_image_annotate(payload))
                return

            if segments == ["api", "image", "search"]:
                self.send_json(_run_search(payload, archetype_filter="image_asset"))
                return

            if segments == ["api", "image", "generate"]:
                self.send_json(_run_image_brief(payload))
                return

            self.send_error(404)
        except Exception as exc:
            self.send_json({"error": str(exc)}, status=400)

    def serve_static(self, path: str) -> None:
        rel = "index.html" if path in {"", "/", "/index.html"} else unquote(path.lstrip("/"))
        target = (WEB_ROOT / rel).resolve()
        web_root = WEB_ROOT.resolve()
        if not str(target).startswith(str(web_root)) or not target.exists() or target.is_dir():
            self.send_error(404)
            return
        content = target.read_bytes()
        mime_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", mime_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length == 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw) if raw else {}

    def send_json(self, payload: dict[str, Any] | list[Any], status: int = 200) -> None:
        body = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), format % args))


def path_segments(path: str) -> list[str]:
    return [unquote(segment) for segment in path.strip("/").split("/") if segment]


def single(query: dict[str, list[str]], key: str) -> str | None:
    values = query.get(key) or []
    return values[0] if values else None


def asset_preview(state: dict[str, Any], item_id: str) -> dict[str, Any]:
    item = state.get("dataset_items", {}).get(item_id)
    if not item:
        raise ValueError("asset item not found")

    payload = item.get("payload_json") or {}
    asset = payload.get("asset") or {}
    asset_path = str(asset.get("path") or "")
    local_path = local_payload_path(payload)
    preview: dict[str, Any] = {
        "item_id": item_id,
        "source_uri": item.get("source_uri"),
        "source_url": openneuro_source_url(asset.get("dataset_id"), asset_path),
        "asset_path": asset_path,
        "local_path": str(local_path) if local_path else None,
        "local_payload_present": bool(local_path and local_path.exists()),
        "renderable": False,
    }
    if local_path and local_path.exists():
        preview.update(read_nifti_preview(local_path))
    return preview


def openneuro_source_url(dataset_id: Any, asset_path: str) -> str | None:
    if not dataset_id or not asset_path:
        return None
    return f"https://s3.amazonaws.com/openneuro.org/{dataset_id}/{asset_path}"


def local_payload_path(payload: dict[str, Any]) -> Path | None:
    evidence = payload.get("local_evidence") or {}
    raw_path = evidence.get("payload_path")
    if not raw_path:
        return None
    path = Path(str(raw_path))
    if path.is_absolute():
        return path
    return demo_poc.REPO_ROOT / path


def read_nifti_preview(path: Path) -> dict[str, Any]:
    with open_maybe_gzip(path) as handle:
        header = handle.read(348)
        if len(header) < 348:
            return {"renderable": False, "error": "NIfTI header is too short"}
        sizeof_hdr = struct.unpack("<i", header[0:4])[0]
        dimensions = list(struct.unpack("<8h", header[40:56]))
        datatype = struct.unpack("<h", header[70:72])[0]
        vox_offset = int(struct.unpack("<f", header[108:112])[0])
        magic = header[344:348].rstrip(b"\x00").decode("ascii", errors="replace")
        if sizeof_hdr != 348 or magic not in {"n+1", "ni1"}:
            return {"renderable": False, "error": "Invalid NIfTI-1 header"}
        if dimensions[0] < 3:
            return {"renderable": False, "error": "NIfTI preview needs at least 3 dimensions"}

        width = int(dimensions[1])
        height = int(dimensions[2])
        depth = int(dimensions[3])
        z_index = max(0, depth // 2)
        type_info = nifti_datatype(datatype)
        if type_info is None:
            return {"renderable": False, "error": f"Unsupported NIfTI datatype {datatype}"}

        handle.seek(vox_offset)
        data = handle.read()

    values = extract_nifti_slice(data, width, height, depth, z_index, type_info)
    pixels = normalize_pixels(values)
    return {
        "renderable": True,
        "width": width,
        "height": height,
        "z_index": z_index,
        "depth": depth,
        "datatype": datatype,
        "pixels": pixels,
    }


def open_maybe_gzip(path: Path):
    return gzip.open(path, "rb") if path.name.endswith(".gz") else path.open("rb")


def nifti_datatype(datatype: int) -> tuple[str, int] | None:
    return {
        2: ("<B", 1),
        4: ("<h", 2),
        8: ("<i", 4),
        16: ("<f", 4),
        64: ("<d", 8),
    }.get(datatype)


def extract_nifti_slice(
    data: bytes,
    width: int,
    height: int,
    depth: int,
    z_index: int,
    type_info: tuple[str, int],
) -> list[float]:
    fmt, byte_width = type_info
    values: list[float] = []
    plane_offset = z_index * width * height * byte_width
    max_offset = len(data) - byte_width
    for y in range(height):
        for x in range(width):
            offset = plane_offset + ((y * width) + x) * byte_width
            if offset > max_offset:
                values.append(0.0)
            else:
                values.append(float(struct.unpack_from(fmt, data, offset)[0]))
    return values


def normalize_pixels(values: list[float]) -> list[int]:
    if not values:
        return []
    low = min(values)
    high = max(values)
    if high == low:
        return [0 for _ in values]
    return [max(0, min(255, round(((value - low) / (high - low)) * 255))) for value in values]


class HeuristicTextClient:
    """Local deterministic demo client that satisfies the text annotator protocol."""

    def call_with_tool(
        self,
        *,
        model: str,
        system: str,
        tool: dict[str, Any],
        content: list[dict[str, Any]],
        max_tokens: int,
    ) -> dict[str, Any]:
        text = " ".join(str(block.get("text", "")) for block in content if block.get("type") == "text")
        return heuristic_text_facets(text)


def heuristic_text_facets(text: str) -> dict[str, Any]:
    lower = text.lower()
    word_count = max(1, len(text.split()))
    regulatory_hits = count_hits(lower, ("compliance", "policy", "legal", "regulatory", "privacy", "terms", "audit"))
    technical_hits = count_hits(lower, ("api", "dataset", "model", "vector", "schema", "latency", "pipeline", "architecture"))
    aggressive_hits = count_hits(lower, ("now", "urgent", "limited", "must", "immediately", "guarantee", "unlock"))
    creative_hits = count_hits(lower, ("imagine", "story", "beautiful", "transform", "spark", "craft", "delight"))
    formal_hits = count_hits(lower, ("therefore", "regarding", "pursuant", "sincerely", "enterprise", "stakeholder"))

    is_email = any(token in lower for token in ("hi ", "hello", "dear ", "sincerely", "book a call", "reply"))
    is_landing = any(token in lower for token in ("start", "sign up", "features", "pricing", "hero", "cta", "landing"))
    if is_email and is_landing:
        is_landing = lower.count("sign up") + lower.count("features") >= lower.count("reply") + lower.count("call")

    return {
        "type_text": True,
        "modality_b2b_email": bool(is_email and not is_landing),
        "modality_landing_page": bool(is_landing),
        "strict_regulatory": clamp01((regulatory_hits * 0.18) + (0.08 if word_count > 120 else 0.0)),
        "strict_technicality": clamp01((technical_hits * 0.16) + (0.05 if word_count > 80 else 0.0)),
        "tone_formality": clamp01(0.28 + formal_hits * 0.12 + regulatory_hits * 0.06),
        "tone_aggressiveness": clamp01(0.18 + aggressive_hits * 0.15),
        "tone_creativity": clamp01(0.16 + creative_hits * 0.16),
    }


def count_hits(text: str, terms: tuple[str, ...]) -> int:
    return sum(text.count(term) for term in terms)


def clamp01(value: float) -> float:
    return round(max(0.0, min(1.0, value)), 3)


# ---------------------------------------------------------------------------
# Tier-2 retrieval / generation handlers (text + image).
#
# These call the live Pinecone index + Anthropic API. They fail loudly with
# a JSON error if the corresponding env vars are missing, so the existing
# heuristic-only flows (e.g. /api/text/annotate) keep working without keys.
# ---------------------------------------------------------------------------

_supabase_client_cache: Any = None


def _safe_supabase_client() -> Any | None:
    """Return a SupabaseClient if creds are present, else None.
    Cached so the snapshot endpoints reuse the same connection.
    The snapshot helpers tolerate None (they return empty recent_documents)."""
    global _supabase_client_cache
    if _supabase_client_cache is not None:
        return _supabase_client_cache
    try:
        from data_annotation.db import SupabaseClient
        _supabase_client_cache = SupabaseClient()
    except Exception:
        _supabase_client_cache = None
    return _supabase_client_cache


_EDITABLE_FACETS = frozenset({
    "auth_domain", "auth_author", "auth_institution",
    "type_text", "type_image", "type_timeseries",
    "modality_b2b_email", "modality_landing_page",
    "modality_fmri_t1", "modality_fmri_bold",
    "strict_regulatory", "strict_technicality",
    "tone_formality", "tone_aggressiveness", "tone_creativity",
})


def _require_supabase() -> Any:
    client = _safe_supabase_client()
    if client is None:
        raise RuntimeError("supabase client unavailable -- check SUPABASE_URL / SUPABASE_SERVICE_KEY")
    return client


def _get_document(doc_id: str) -> dict[str, Any]:
    client = _require_supabase()
    rows = client.fetch_by_ids([doc_id])
    row = rows.get(doc_id)
    if not row:
        raise ValueError(f"document {doc_id} not found")
    return {"document": row}


def _refresh_document(client: Any, doc_id: str) -> dict[str, Any]:
    rows = client.fetch_by_ids([doc_id])
    return rows.get(doc_id) or {}


def _parse_data_url(value: str) -> tuple[str, str]:
    """data:image/png;base64,iVBORw... -> ('image/png', 'iVBORw...')"""
    if not value.startswith("data:"):
        raise ValueError("payload is not a data URL; cannot re-annotate image")
    header, _, body = value[5:].partition(",")
    media_type, _, encoding = header.partition(";")
    if encoding != "base64":
        raise ValueError("data URL must be base64-encoded")
    return media_type or "image/png", body


def _reannotate_document(doc_id: str) -> dict[str, Any]:
    client = _require_supabase()
    rows = client.fetch_by_ids([doc_id])
    row = rows.get(doc_id)
    if not row:
        raise ValueError(f"document {doc_id} not found")
    archetype_id = row.get("archetype_id")
    payload = row.get("content_payload") or ""

    if archetype_id == "text_document":
        result = annotate_text(payload)
    elif archetype_id == "image_asset":
        media_type, b64 = _parse_data_url(payload)
        data = base64.b64decode(b64)
        result = annotate_image(data, media_type=media_type)
    else:
        raise ValueError(f"no annotator for archetype {archetype_id!r}")

    facets = result.facets
    client._client.table("documents_raw").update(facets).eq("id", doc_id).execute()
    client.upsert_annotation(result.to_db_row(document_id=doc_id))
    return {
        "document": _refresh_document(client, doc_id),
        "annotation": result.to_db_row(document_id=doc_id),
    }


def _edit_document(doc_id: str, facets: dict[str, Any]) -> dict[str, Any]:
    client = _require_supabase()
    update = {k: v for k, v in facets.items() if k in _EDITABLE_FACETS}
    if not update:
        raise ValueError("no recognised facet columns in payload")
    client._client.table("documents_raw").update(update).eq("id", doc_id).execute()
    return {"document": _refresh_document(client, doc_id)}


def _save_text_document(payload: dict[str, Any]) -> dict[str, Any]:
    """Insert a text row into documents_raw with the supplied facets +
    text payload. The annotator runner / indexer will then pick it up
    on the next pass (or you can call /reannotate immediately)."""
    client = _require_supabase()
    text = str(payload.get("content_payload") or "").strip()
    if not text:
        raise ValueError("content_payload is required")
    facets = payload.get("facets") or {}
    row: dict[str, Any] = {
        "source_name": str(payload.get("source_name") or "ui-text-save")[:255],
        "content_payload": text,
        "archetype_id": "text_document",
        "is_processed": True if facets else False,
    }
    for key, value in facets.items():
        if key in _EDITABLE_FACETS:
            row[key] = value
    inserted = client._client.table("documents_raw").insert(row).execute()
    return {"document": inserted.data[0]}


def _save_image_document(payload: dict[str, Any]) -> dict[str, Any]:
    """Insert an image row with a data URL in content_payload so the
    detail view can render the image after retrieval."""
    client = _require_supabase()
    image_b64 = str(payload.get("image_base64") or "")
    media_type = str(payload.get("media_type") or "image/png")
    if not image_b64:
        raise ValueError("image_base64 is required")
    data_url = f"data:{media_type};base64,{image_b64}"
    facets = payload.get("facets") or {}
    row: dict[str, Any] = {
        "source_name": str(payload.get("source_name") or "ui-image-save")[:255],
        "content_payload": data_url,
        "archetype_id": "image_asset",
        "is_processed": True if facets else False,
    }
    for key, value in facets.items():
        if key in _EDITABLE_FACETS:
            row[key] = value
    inserted = client._client.table("documents_raw").insert(row).execute()
    return {"document": inserted.data[0]}


def _facet_weights_from_payload(payload: dict[str, Any]) -> dict[str, float]:
    return {
        "authority": float(payload.get("authority_weight", 1.0)),
        "type": float(payload.get("type_weight", 1.0)),
        "modality": float(payload.get("modality_weight", 1.0)),
        "strictness": float(payload.get("strictness_weight", 1.0)),
        "tone": float(payload.get("tone_weight", 0.2)),
    }


def _run_search(payload: dict[str, Any], *, archetype_filter: str) -> dict[str, Any]:
    from data_annotation.pinecone_search import search

    prompt = str(payload.get("prompt") or "").strip()
    if not prompt:
        raise ValueError("prompt is required")
    plan = bool(payload.get("plan"))
    top_k = int(payload.get("top_k") or 5)

    matches = search(
        prompt,
        weights=None if plan else _facet_weights_from_payload(payload),
        plan_prompt=plan,
        top_k=top_k,
        archetype_filter=archetype_filter,
        enrich=bool(payload.get("enrich", True)),
    )
    return {
        "matches": [
            {
                "document_id": match.document_id,
                "score": match.score,
                "metadata": match.metadata,
                "document": match.document,
            }
            for match in matches
        ],
        "archetype_filter": archetype_filter,
        "planned_weights_used": plan,
    }


def _run_text_generate(payload: dict[str, Any]) -> dict[str, Any]:
    from data_annotation.generator import generate_text_from_context
    from data_annotation.pinecone_search import search

    prompt = str(payload.get("prompt") or "").strip()
    if not prompt:
        raise ValueError("prompt is required")
    plan = bool(payload.get("plan"))
    top_k = int(payload.get("top_k") or 3)

    matches = search(
        prompt,
        weights=None if plan else _facet_weights_from_payload(payload),
        plan_prompt=plan,
        top_k=top_k,
        archetype_filter="text_document",
        enrich=True,
    )
    examples = [match.document for match in matches if match.document]
    generated = generate_text_from_context(prompt, examples)
    return {
        "generated_text": generated,
        "retrieved_count": len(matches),
        "sources": [
            {"document_id": m.document_id, "source_name": (m.document or {}).get("source_name")}
            for m in matches
        ],
    }


def _run_image_annotate(payload: dict[str, Any]) -> dict[str, Any]:
    image_b64 = payload.get("image_base64") or ""
    media_type = payload.get("media_type") or "image/png"
    if not image_b64:
        raise ValueError("image_base64 is required")
    data = base64.b64decode(image_b64)
    result = annotate_image(data, media_type=str(media_type))
    return {"annotation": result.to_db_row(), "byte_count": len(data)}


def _run_image_brief(payload: dict[str, Any]) -> dict[str, Any]:
    from data_annotation.generator import generate_image_brief_from_context
    from data_annotation.pinecone_search import search

    prompt = str(payload.get("prompt") or "").strip()
    if not prompt:
        raise ValueError("prompt is required")
    plan = bool(payload.get("plan"))
    top_k = int(payload.get("top_k") or 3)

    matches = search(
        prompt,
        weights=None if plan else _facet_weights_from_payload(payload),
        plan_prompt=plan,
        top_k=top_k,
        archetype_filter="image_asset",
        enrich=True,
    )
    examples = [match.document for match in matches if match.document]
    brief = generate_image_brief_from_context(prompt, examples)
    return {
        "brief_text": brief,
        "retrieved_count": len(matches),
        "sources": [
            {"document_id": m.document_id, "source_name": (m.document or {}).get("source_name")}
            for m in matches
        ],
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the fMRI data annotation POC server.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--state", type=Path, default=demo_poc.DEFAULT_STATE_PATH)
    parser.add_argument("--export-dir", type=Path, default=demo_poc.DEFAULT_EXPORT_DIR)
    parser.add_argument("--reset", action="store_true", help="Rebuild demo state before serving.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = parse_args(argv or sys.argv[1:])
    DemoRequestHandler.state_path = args.state
    DemoRequestHandler.export_dir = args.export_dir
    demo_poc.load_state(args.state, reset=args.reset)
    server = ThreadingHTTPServer((args.host, args.port), DemoRequestHandler)
    print(f"fMRI annotation POC running at http://{args.host}:{args.port}")
    print(f"state: {args.state}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nserver stopped")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
