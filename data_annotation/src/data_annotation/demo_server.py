from __future__ import annotations

import argparse
import json
import mimetypes
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from data_annotation import demo_poc


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
            if len(segments) == 4 and segments[:2] == ["api", "projects"] and segments[3] == "quality":
                self.send_json(demo_poc.quality_metrics(state, segments[2]))
                return
            if segments == ["api", "assignments", "next"]:
                project_id = single(query, "project_id") or state.get("meta", {}).get("active_project_id")
                role = single(query, "role") or "annotator"
                self.send_json(demo_poc.next_assignment(state, project_id, role) or {})
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


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the fMRI data annotation POC server.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--state", type=Path, default=demo_poc.DEFAULT_STATE_PATH)
    parser.add_argument("--export-dir", type=Path, default=demo_poc.DEFAULT_EXPORT_DIR)
    parser.add_argument("--reset", action="store_true", help="Rebuild demo state before serving.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
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
