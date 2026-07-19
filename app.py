from __future__ import annotations

import os
import socket
import threading
import webbrowser

from gifmaker import create_app


def available_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


if __name__ == "__main__":
    port = available_port()
    address = f"http://127.0.0.1:{port}"
    print(f"GIFmakerAthome is running locally at {address}", flush=True)
    print("Close this window or press Ctrl+C to stop it.", flush=True)
    if os.environ.get("GIFMAKER_ATHOME_NO_BROWSER") != "1":
        threading.Timer(1.0, lambda: webbrowser.open(address)).start()
    create_app().run(host="127.0.0.1", port=port, debug=False, threaded=True)
