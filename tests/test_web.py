from __future__ import annotations

import io
import re
import threading
import time
from pathlib import Path

from PIL import Image

from gifmaker import create_app
from gifmaker.media import ImportProgress
from gifmaker.web import default_data_root


def animated_gif_bytes() -> bytes:
    output = io.BytesIO()
    frames = [Image.new("RGB", (40, 30), "red"), Image.new("RGB", (40, 30), "blue")]
    frames[0].save(output, format="GIF", save_all=True, append_images=frames[1:], duration=120, loop=0)
    return output.getvalue()


def animated_webp_bytes() -> bytes:
    output = io.BytesIO()
    frames = [Image.new("RGBA", (36, 36), (255, 0, 0, 180)), Image.new("RGBA", (36, 36), (0, 0, 255, 180))]
    frames[0].save(output, format="WEBP", save_all=True, append_images=frames[1:], duration=120, loop=0)
    return output.getvalue()


def test_default_data_root_honors_environment_override(tmp_path: Path, monkeypatch) -> None:
    configured = tmp_path / "configured-cache"
    monkeypatch.setenv("GIFMAKER_ATHOME_DATA_ROOT", str(configured))
    assert default_data_root(tmp_path / "project") == configured


def test_local_api_requires_page_token(tmp_path: Path) -> None:
    app = create_app(tmp_path / "data", testing=True)
    with app.test_client() as client:
        response = client.post("/api/import", json={"url": "https://example.com/video.mp4"})
    assert response.status_code == 403


def test_last_browser_tab_requests_shutdown_but_refresh_keeps_server_alive(tmp_path: Path) -> None:
    shutdown_requested = threading.Event()
    app = create_app(
        tmp_path / "data",
        testing=True,
        shutdown_callback=shutdown_requested.set,
        shutdown_delay=0.1,
    )
    token = app.extensions["gifmaker_athome_token"]

    with app.test_client() as client:
        first_page = client.get("/")
        first_match = re.search(rb'name="gifmaker-athome-browser-session" content="([^"]+)"', first_page.data)
        assert first_match is not None
        first_session = first_match.group(1).decode()
        closed = client.post(
            "/api/browser-session/close",
            json={"session_id": first_session, "token": token},
        )
        assert closed.status_code == 202

        refreshed_page = client.get("/")
        refreshed_match = re.search(
            rb'name="gifmaker-athome-browser-session" content="([^"]+)"',
            refreshed_page.data,
        )
        assert refreshed_match is not None
        refreshed_session = refreshed_match.group(1).decode()
        assert refreshed_session != first_session
        time.sleep(0.15)
        assert not shutdown_requested.is_set()

        closed = client.post(
            "/api/browser-session/close",
            json={"session_id": refreshed_session, "token": token},
        )
        assert closed.status_code == 202
        assert shutdown_requested.wait(0.5)


def test_link_import_job_reports_download_progress_and_returns_asset(tmp_path: Path, monkeypatch) -> None:
    progress_reported = threading.Event()
    finish_import = threading.Event()

    def fake_import_media_url(url, store, progress_callback=None):
        assert url == "https://example.com/video.mp4"
        assert progress_callback is not None
        progress_callback(
            ImportProgress(
                stage="downloading",
                downloaded_bytes=512,
                total_bytes=1024,
                speed_bytes_per_second=256,
                eta_seconds=2,
                detail="Downloading media from the source…",
            )
        )
        progress_reported.set()
        assert finish_import.wait(2)
        destination = store.allocate_import_path("linked.gif")
        destination.write_bytes(animated_gif_bytes())
        return store.register(destination, "Linked animation.gif")

    monkeypatch.setattr("gifmaker.web.import_media_url", fake_import_media_url)
    app = create_app(tmp_path / "data", testing=True)
    headers = {"X-GIFmakerAthome-Token": app.extensions["gifmaker_athome_token"]}
    with app.test_client() as client:
        started = client.post(
            "/api/import",
            json={"url": "https://example.com/video.mp4"},
            headers=headers,
        )
        assert started.status_code == 202
        job_id = started.get_json()["job"]["id"]
        assert progress_reported.wait(0.5)

        progress = client.get(f"/api/import/{job_id}").get_json()["job"]
        assert progress["status"] == "running"
        assert progress["stage"] == "downloading"
        assert progress["downloaded_bytes"] == 512
        assert progress["total_bytes"] == 1024
        assert progress["eta_seconds"] == 2

        finish_import.set()
        deadline = time.monotonic() + 2
        completed = None
        while time.monotonic() < deadline:
            completed = client.get(f"/api/import/{job_id}").get_json()
            if completed["job"]["status"] == "complete":
                break
            time.sleep(0.01)
        assert completed is not None
        assert completed["job"]["status"] == "complete"
        assert completed["asset"]["name"] == "Linked animation.gif"
        assert completed["asset"]["kind"] == "image"


def test_upload_and_media_delivery(tmp_path: Path) -> None:
    app = create_app(tmp_path / "data", testing=True)
    token = app.extensions["gifmaker_athome_token"]
    headers = {"X-GIFmakerAthome-Token": token}
    with app.test_client() as client:
        page = client.get("/")
        assert page.status_code == 200
        assert b"GIFmakerAthome" in page.data
        assert b"Turn any moment" in page.data
        assert b"Paste a supported media URL" in page.data
        assert b"Only import media you own or are authorized to use" in page.data
        assert b'<option value="webm" selected>' in page.data
        assert b'<option value="30" selected>' in page.data
        assert b'<option value="512square">512' in page.data
        assert b'<option value="1">1 FPS' in page.data
        assert b'<option value="1">Minimum' in page.data
        assert b'<option value="40" selected>' in page.data
        assert b'<option value="8">Extreme' in page.data
        assert b'<option value="0.1">10%' in page.data
        assert b'<option value="256">Maximum 256 KB' in page.data
        assert b'id="reduceColorsOption" type="checkbox" disabled' in page.data
        assert b'id="lossyGifOption" type="checkbox" disabled' in page.data
        assert b'id="optimizePixelsOption" type="checkbox" disabled' in page.data
        assert b'id="removeDuplicatesOption" type="checkbox" disabled' in page.data
        assert b'id="extendLoopButton"' in page.data
        assert b'id="openFrameEditorButton"' in page.data
        assert b'id="frameEditorPanel"' in page.data
        assert b'id="clearCacheButton"' in page.data
        assert b'id="loadingProgress"' in page.data
        script = (Path(__file__).resolve().parents[1] / "static" / "js" / "app.js").read_text(encoding="utf-8")
        assert "Revert to forward only" in script
        assert 'addEventListener("dragstart"' in script
        assert "Compile edited" in script
        assert "data-delete-frame" in script
        assert "Downloading linked media" in script
        assert "navigator.sendBeacon" in script
        assert b'class="chip active" data-aspect="original"' in page.data
        assert b'rel="icon"' in page.data
        assert 'applyCropAspect("original");' in script
        assert page.headers["Content-Security-Policy"].startswith("default-src 'self'")

        uploaded = client.post(
            "/api/upload",
            data={"file": (io.BytesIO(animated_gif_bytes()), "My colors.gif")},
            headers=headers,
            content_type="multipart/form-data",
        )
        assert uploaded.status_code == 200
        asset = uploaded.get_json()["asset"]
        assert asset["width"] == 40
        assert asset["height"] == 30
        assert asset["kind"] == "image"
        assert asset["name"] == "My colors.gif"

        served = client.get(asset["media_url"])
        assert served.status_code == 200
        assert served.data.startswith(b"GIF8")
        assert served.headers["Content-Type"].startswith("image/gif")
        served.close()

        downloaded = client.get(asset["download_url"])
        assert downloaded.status_code == 200
        assert 'filename="My colors.gif"' in downloaded.headers["Content-Disposition"]
        downloaded.close()

        frame_response = client.post(
            "/api/frame-sequences",
            json={
                "media_id": asset["id"],
                "start": 0,
                "end": asset["duration"],
                "discard_middle": False,
                "crop_x": 0,
                "crop_y": 0,
                "crop_width": asset["width"],
                "crop_height": asset["height"],
                "output_width": 20,
                "output_height": 20,
                "output_format": "webm",
                "fps": 10,
            },
            headers=headers,
        )
        assert frame_response.status_code == 200
        sequence = frame_response.get_json()["sequence"]
        assert (sequence["width"], sequence["height"], sequence["fps"]) == (20, 20, 10)
        assert len(sequence["frames"]) >= 2
        served_frame = client.get(sequence["frames"][0]["url"])
        assert served_frame.status_code == 200
        assert served_frame.data.startswith(b"\x89PNG")
        served_frame.close()

        frame_export = client.post(
            f"/api/frame-sequences/{sequence['id']}/export",
            json={
                "output_format": "gif",
                "colors": 64,
                "quality": 40,
                "frames": [
                    {"id": sequence["frames"][-1]["id"], "hold": 1},
                    {"id": sequence["frames"][0]["id"], "hold": 2},
                ],
            },
            headers=headers,
        )
        assert frame_export.status_code == 200
        frame_asset = frame_export.get_json()["asset"]
        assert frame_asset["name"] == "My colors.gif"
        assert (frame_asset["width"], frame_asset["height"]) == (20, 20)

        extended = client.post(
            "/api/extend",
            json={"media_id": asset["id"]},
            headers=headers,
        )
        assert extended.status_code == 200
        loop_asset = extended.get_json()["asset"]
        assert loop_asset["name"] == "My colors-loop.gif"
        assert asset["duration"] <= loop_asset["duration"] < asset["duration"] * 2

        webp_upload = client.post(
            "/api/upload",
            data={"file": (io.BytesIO(animated_webp_bytes()), "transparent-animation.webp")},
            headers=headers,
            content_type="multipart/form-data",
        )
        assert webp_upload.status_code == 200
        webp_asset = webp_upload.get_json()["asset"]
        assert webp_asset["kind"] == "image"
        assert webp_asset["mime"] == "image/webp"
        assert (webp_asset["width"], webp_asset["height"]) == (36, 36)

        cleared = client.post("/api/clear", headers=headers)
        assert cleared.status_code == 200
        assert cleared.get_json()["cleared"]["files"] >= 3
        missing = client.get(asset["media_url"])
        assert missing.status_code == 400


def test_bad_upload_returns_user_facing_error(tmp_path: Path) -> None:
    app = create_app(tmp_path / "data", testing=True)
    headers = {"X-GIFmakerAthome-Token": app.extensions["gifmaker_athome_token"]}
    with app.test_client() as client:
        response = client.post(
            "/api/upload",
            data={"file": (io.BytesIO(b"not media"), "notes.txt")},
            headers=headers,
            content_type="multipart/form-data",
        )
    assert response.status_code == 400
    assert "not a readable video" in response.get_json()["error"]
