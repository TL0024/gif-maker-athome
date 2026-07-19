from __future__ import annotations

import os
import socket
import threading
import webbrowser

from werkzeug.serving import make_server

from gifmaker import create_app


def available_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


if __name__ == "__main__":
    port = available_port()
    address = f"http://127.0.0.1:{port}"
    shutdown_requested = threading.Event()
    app = create_app(shutdown_callback=shutdown_requested.set)
    server = make_server("127.0.0.1", port, app, threaded=True)

    def stop_server_when_requested() -> None:
        shutdown_requested.wait()
        server.shutdown()

    print(f"GIFmakerAthome is running locally at {address}", flush=True)
    print("Close the browser tab, close this window, or press Ctrl+C to stop it.", flush=True)
    if os.environ.get("GIFMAKER_ATHOME_NO_BROWSER") != "1":
        threading.Timer(1.0, lambda: webbrowser.open(address)).start()
    threading.Thread(target=stop_server_when_requested, name="browser-shutdown", daemon=True).start()
    try:
        server.serve_forever()
    finally:
        server.server_close()
