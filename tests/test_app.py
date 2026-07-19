from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import requests


def test_browser_close_stops_command_process(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    environment.update(
        {
            "GIFMAKER_ATHOME_NO_BROWSER": "1",
            "GIFMAKER_ATHOME_DATA_ROOT": str(tmp_path / "data"),
        }
    )
    process = subprocess.Popen(
        [sys.executable, str(project_root / "app.py")],
        cwd=project_root,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout is not None
        startup_line = process.stdout.readline().strip()
        assert startup_line.startswith("GIFmakerAthome is running locally at http://127.0.0.1:")
        address = startup_line.rsplit(" ", 1)[-1]

        page = requests.get(address, timeout=5)
        page.raise_for_status()
        token_match = re.search(r'name="gifmaker-athome-token" content="([^"]+)"', page.text)
        session_match = re.search(r'name="gifmaker-athome-browser-session" content="([^"]+)"', page.text)
        assert token_match is not None
        assert session_match is not None

        closed = requests.post(
            f"{address}/api/browser-session/close",
            json={
                "session_id": session_match.group(1),
                "token": token_match.group(1),
            },
            timeout=5,
        )
        assert closed.status_code == 202
        assert process.wait(timeout=5) == 0
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
