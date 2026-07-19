from __future__ import annotations

import os
import secrets
import sys
from pathlib import Path
from typing import Any

from flask import Flask, Response, abort, jsonify, render_template, request, send_file, url_for
from werkzeug.exceptions import RequestEntityTooLarge

from .media import (
    ExportOptions,
    FrameExportOptions,
    FrameSequence,
    MediaAsset,
    MediaError,
    MediaStore,
    import_media_url,
)


def default_data_root(project_root: Path) -> Path:
    configured_root = os.environ.get("GIFMAKER_ATHOME_DATA_ROOT")
    if configured_root:
        return Path(configured_root)
    if getattr(sys, "frozen", False):
        local_app_data = os.environ.get("LOCALAPPDATA")
        base = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
        return base / "GIFmakerAthome" / "cache"
    return project_root / ".gifmaker-athome-data"


def create_app(data_root: Path | None = None, testing: bool = False) -> Flask:
    project_root = Path(__file__).resolve().parent.parent
    app = Flask(
        __name__,
        template_folder=str(project_root / "templates"),
        static_folder=str(project_root / "static"),
    )
    app.config.update(
        TESTING=testing,
        MAX_CONTENT_LENGTH=4 * 1024 * 1024 * 1024,
        JSON_SORT_KEYS=False,
    )
    store = MediaStore((data_root or default_data_root(project_root)).resolve())
    request_token = secrets.token_urlsafe(32)
    app.extensions["gifmaker_athome_store"] = store
    app.extensions["gifmaker_athome_token"] = request_token

    def asset_json(asset: MediaAsset) -> dict[str, Any]:
        payload = asset.as_api_dict()
        payload["media_url"] = url_for("serve_media", asset_id=asset.id)
        payload["download_url"] = url_for("download_media", asset_id=asset.id)
        return payload

    def frame_sequence_json(sequence: FrameSequence) -> dict[str, Any]:
        return {
            "id": sequence.id,
            "width": sequence.width,
            "height": sequence.height,
            "fps": sequence.fps,
            "frames": [
                {
                    "id": path.stem,
                    "url": url_for(
                        "serve_frame",
                        sequence_id=sequence.id,
                        frame_id=path.stem,
                    ),
                    "hold": 1,
                }
                for path in sequence.frames
            ],
        }

    @app.before_request
    def protect_local_api() -> None:
        if (
            request.method in {"POST", "PUT", "PATCH", "DELETE"}
            and request.path.startswith("/api/")
            and request.headers.get("X-GIFmakerAthome-Token") != request_token
        ):
            abort(403)

    @app.after_request
    def local_security_headers(response: Response) -> Response:
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' blob: data:; media-src 'self' blob:; "
            "style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'"
        )
        return response

    @app.get("/")
    def index() -> str:
        return render_template("index.html", request_token=request_token)

    @app.post("/api/upload")
    def upload_media() -> Response:
        upload = request.files.get("file")
        if upload is None or not upload.filename:
            raise MediaError("Choose a video or animated image to upload.")
        destination = store.allocate_import_path(upload.filename)
        try:
            upload.save(destination)
            if destination.stat().st_size == 0:
                raise MediaError("The uploaded file is empty.")
            asset = store.register(destination, upload.filename)
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        return jsonify({"asset": asset_json(asset)})

    @app.post("/api/import")
    def import_link() -> Response:
        payload = request.get_json(silent=True) or {}
        link = str(payload.get("url") or "").strip()
        if not link:
            raise MediaError("Paste a supported media URL first.")
        asset = import_media_url(link, store)
        return jsonify({"asset": asset_json(asset)})

    @app.post("/api/export")
    def export_media() -> Response:
        payload = request.get_json(silent=True) or {}
        source = store.get(str(payload.get("media_id") or ""))
        options = ExportOptions.from_payload(payload, source)
        exported = store.create_export(source, options)
        return jsonify({"asset": asset_json(exported)})

    @app.post("/api/frame-sequences")
    def create_frame_sequence() -> Response:
        payload = request.get_json(silent=True) or {}
        source = store.get(str(payload.get("media_id") or ""))
        options = ExportOptions.from_payload(payload, source)
        sequence = store.create_frame_sequence(source, options)
        return jsonify({"sequence": frame_sequence_json(sequence)})

    @app.post("/api/frame-sequences/<sequence_id>/export")
    def export_frame_sequence(sequence_id: str) -> Response:
        payload = request.get_json(silent=True) or {}
        sequence = store.get_frame_sequence(sequence_id)
        options = FrameExportOptions.from_payload(payload, sequence)
        exported = store.create_frame_export(sequence, payload.get("frames"), options)
        return jsonify({"asset": asset_json(exported)})

    @app.post("/api/extend")
    def extend_loop() -> Response:
        payload = request.get_json(silent=True) or {}
        source = store.get(str(payload.get("media_id") or ""))
        extended = store.create_pingpong_loop(source)
        return jsonify({"asset": asset_json(extended)})

    @app.post("/api/clear")
    def clear_cache() -> Response:
        cleared = store.clear_all()
        return jsonify({"cleared": cleared})

    @app.post("/api/media/<asset_id>/preview")
    def create_browser_preview(asset_id: str) -> Response:
        source = store.get(asset_id)
        if source.kind != "video":
            raise MediaError("This media does not need a video preview.")
        store.create_preview(source)
        return jsonify({"preview_url": url_for("serve_preview", asset_id=source.id)})

    @app.get("/media/<asset_id>")
    def serve_media(asset_id: str) -> Response:
        asset = store.get(asset_id)
        return send_file(asset.path, mimetype=asset.mime, conditional=True)

    @app.get("/preview/<asset_id>")
    def serve_preview(asset_id: str) -> Response:
        asset = store.get(asset_id)
        path = store.get_preview(asset)
        return send_file(path, mimetype="video/mp4", conditional=True)

    @app.get("/frames/<sequence_id>/<frame_id>")
    def serve_frame(sequence_id: str, frame_id: str) -> Response:
        sequence = store.get_frame_sequence(sequence_id)
        path = store.get_frame(sequence, frame_id)
        return send_file(path, mimetype="image/png", conditional=True)

    @app.get("/download/<asset_id>")
    def download_media(asset_id: str) -> Response:
        asset = store.get(asset_id)
        return send_file(asset.path, mimetype=asset.mime, as_attachment=True, download_name=asset.name)

    @app.errorhandler(MediaError)
    def handle_media_error(error: MediaError) -> tuple[Response, int]:
        return jsonify({"error": str(error)}), 400

    @app.errorhandler(RequestEntityTooLarge)
    def handle_large_upload(_error: RequestEntityTooLarge) -> tuple[Response, int]:
        return jsonify({"error": "The upload exceeds the 4 GB local file limit."}), 413

    return app
