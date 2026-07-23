from __future__ import annotations

import os
import secrets
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from flask import Flask, Response, abort, jsonify, render_template, request, send_file, url_for
from werkzeug.exceptions import RequestEntityTooLarge

from .media import (
    ExportOptions,
    FrameExportOptions,
    FrameSequence,
    ImportProgress,
    MediaAsset,
    MediaError,
    MediaStore,
    import_media_url,
)


class BrowserSessionManager:
    """Shut down the desktop server shortly after its last browser page closes."""

    def __init__(self, shutdown_callback: Callable[[], None] | None, close_delay: float = 1.5) -> None:
        self._shutdown_callback = shutdown_callback
        self._close_delay = close_delay
        self._sessions: set[str] = set()
        self._lock = threading.Lock()
        self._timer: threading.Timer | None = None

    def open(self, session_id: str) -> None:
        with self._lock:
            self._sessions.add(session_id)
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None

    def close(self, session_id: str) -> None:
        with self._lock:
            if session_id not in self._sessions:
                return
            self._sessions.remove(session_id)
            if self._sessions or self._shutdown_callback is None:
                return
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(self._close_delay, self._shutdown_if_inactive)
            self._timer.daemon = True
            self._timer.start()

    def _shutdown_if_inactive(self) -> None:
        with self._lock:
            self._timer = None
            if self._sessions:
                return
            callback = self._shutdown_callback
        if callback is not None:
            callback()


@dataclass
class ImportJob:
    id: str
    progress: ImportProgress = field(
        default_factory=lambda: ImportProgress(stage="extracting", detail="Finding downloadable media…")
    )
    asset: MediaAsset | None = None
    error: str | None = None
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def update(self, progress: ImportProgress) -> None:
        with self.lock:
            self.progress = progress

    def finish(self, asset: MediaAsset) -> None:
        with self.lock:
            self.asset = asset

    def fail(self, error: str) -> None:
        with self.lock:
            self.error = error

    def snapshot(self) -> tuple[dict[str, Any], MediaAsset | None]:
        with self.lock:
            payload = self.progress.as_api_dict()
            payload.update(
                {
                    "id": self.id,
                    "status": "failed"
                    if self.error is not None
                    else "complete"
                    if self.asset is not None
                    else "running",
                    "error": self.error,
                }
            )
            return payload, self.asset


def default_data_root(project_root: Path) -> Path:
    configured_root = os.environ.get("GIFMAKER_ATHOME_DATA_ROOT")
    if configured_root:
        return Path(configured_root)
    if getattr(sys, "frozen", False):
        local_app_data = os.environ.get("LOCALAPPDATA")
        base = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
        return base / "GIFmakerAthome" / "cache"
    return project_root / ".gifmaker-athome-data"


def create_app(
    data_root: Path | None = None,
    testing: bool = False,
    shutdown_callback: Callable[[], None] | None = None,
    shutdown_delay: float = 1.5,
) -> Flask:
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
    browser_sessions = BrowserSessionManager(shutdown_callback, shutdown_delay)
    import_jobs: dict[str, ImportJob] = {}
    import_jobs_lock = threading.Lock()
    app.extensions["gifmaker_athome_store"] = store
    app.extensions["gifmaker_athome_token"] = request_token
    app.extensions["gifmaker_athome_browser_sessions"] = browser_sessions

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
                    "hold": hold,
                }
                for path, hold in zip(sequence.frames, sequence.holds, strict=True)
            ],
        }

    @app.before_request
    def protect_local_api() -> None:
        if request.method not in {"POST", "PUT", "PATCH", "DELETE"} or not request.path.startswith("/api/"):
            return
        supplied_token = request.headers.get("X-GIFmakerAthome-Token", "")
        if request.path == "/api/browser-session/close" and not supplied_token:
            payload = request.get_json(silent=True) or {}
            supplied_token = str(payload.get("token") or "")
        if not secrets.compare_digest(supplied_token, request_token):
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
        browser_session_id = secrets.token_urlsafe(18)
        browser_sessions.open(browser_session_id)
        return render_template(
            "index.html",
            request_token=request_token,
            browser_session_id=browser_session_id,
        )

    @app.post("/api/browser-session/close")
    def close_browser_session() -> tuple[Response, int]:
        payload = request.get_json(silent=True) or {}
        session_id = str(payload.get("session_id") or "")
        if not session_id or len(session_id) > 128:
            raise MediaError("The browser session identifier is invalid.")
        browser_sessions.close(session_id)
        return jsonify({"closing": True}), 202

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
    def import_link() -> tuple[Response, int]:
        payload = request.get_json(silent=True) or {}
        link = str(payload.get("url") or "").strip()
        if not link:
            raise MediaError("Paste a supported media URL first.")
        job = ImportJob(secrets.token_urlsafe(18))
        with import_jobs_lock:
            import_jobs[job.id] = job

        def run_import() -> None:
            try:
                job.finish(import_media_url(link, store, job.update))
            except MediaError as exc:
                job.fail(str(exc))
            except Exception:
                app.logger.exception("Unexpected linked-media import failure")
                job.fail("The linked media could not be imported.")

        worker = threading.Thread(target=run_import, name=f"media-import-{job.id}", daemon=True)
        job_payload, _asset = job.snapshot()
        worker.start()
        return jsonify({"job": job_payload}), 202

    @app.get("/api/import/<job_id>")
    def import_status(job_id: str) -> Response:
        with import_jobs_lock:
            job = import_jobs.get(job_id)
        if job is None:
            abort(404)
        payload, asset = job.snapshot()
        response: dict[str, Any] = {"job": payload}
        if asset is not None:
            response["asset"] = asset_json(asset)
        return jsonify(response)

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
