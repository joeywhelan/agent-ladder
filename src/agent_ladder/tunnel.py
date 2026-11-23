"""Start and stop the detection service, the page server and the ngrok tunnel.

The servers run in daemon threads only because the notebook has to stay usable
while they serve requests; nothing else in the project is concurrent.
"""

import http.server
import json
import logging
import socket
import threading
import time

import uvicorn
from pyngrok import ngrok

from agent_ladder.service import create_app
from agent_ladder.store import REPO_ROOT

SERVICE_PORT = 8000
PAGE_PORT = 8001
PAGE_DIR = REPO_ROOT / "assets" / "page"
STARTUP_TIMEOUT_S = 10
SHUTDOWN_TIMEOUT_S = 10

# ngrok's agent log and the MCP library's startup lines would otherwise appear
# in the notebook as unexplained output. Warnings and errors still show.
logging.getLogger("pyngrok").setLevel(logging.WARNING)
logging.getLogger("mcp").setLevel(logging.WARNING)
# The Ollama client and the Chat API both use httpx, which logs every request at
# INFO; during a level run that would bury the progress lines.
logging.getLogger("httpx").setLevel(logging.WARNING)


def start_service(bearer_token: str) -> uvicorn.Server:
    """Run the detection service on SERVICE_PORT and wait until it's accepting requests."""
    app = create_app(bearer_token)
    config = uvicorn.Config(app, host="127.0.0.1", port=SERVICE_PORT, log_level="warning")
    server = uvicorn.Server(config)

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    deadline = time.monotonic() + STARTUP_TIMEOUT_S
    while not server.started:
        if not thread.is_alive() or time.monotonic() > deadline:
            message = f"Detection service didn't start on port {SERVICE_PORT} (is the port in use?)"
            raise RuntimeError(message)
        time.sleep(0.1)
    return server


def make_page_handler(channel_ref_id: str) -> type:
    """A request handler that serves assets/page/, plus /config.js with the VA's channel ID.

    The channel reference ID (the widget calls it botRefId) lives in .env, not
    in index.html, so the page loads whichever VA .env names; index.html reads
    it from config.js.
    """
    config_js = f"window.NETOMI_CHANNEL_REF_ID = {json.dumps(channel_ref_id)};\n".encode("utf-8")

    class PageRequestHandler(http.server.SimpleHTTPRequestHandler):
        """Serves the demo page's files and its generated config.js."""

        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(PAGE_DIR), **kwargs)

        def do_GET(self):
            path = self.path.split("?")[0]
            if path != "/config.js":
                super().do_GET()
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/javascript")
            self.send_header("Content-Length", str(len(config_js)))
            self.end_headers()
            self.wfile.write(config_js)

        def log_message(self, format, *args):  # pylint: disable=redefined-builtin
            # Without this, every page request prints a line in the notebook.
            return

    return PageRequestHandler


def start_page_server(channel_ref_id: str) -> http.server.ThreadingHTTPServer:
    """Serve the demo page on PAGE_PORT, loading the VA named by channel_ref_id."""
    PAGE_DIR.mkdir(parents=True, exist_ok=True)
    handler = make_page_handler(channel_ref_id)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", PAGE_PORT), handler)

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def start_tunnel(ngrok_domain: str) -> str:
    """Expose the detection service on the fixed ngrok domain and return its public URL.

    The ngrok account is taken from ngrok's own config (~/.config/ngrok/ngrok.yml).
    """
    # The ngrok config is version 3, where tunnels are "endpoints" and the
    # public address is given as a full `url`, not a `domain`.
    tunnel = ngrok.connect(str(SERVICE_PORT), url=f"https://{ngrok_domain}")
    return tunnel.public_url


def port_is_free(port: int) -> bool:
    """True if nothing is listening on this local port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        result = probe.connect_ex(("127.0.0.1", port))
    return result != 0


def stop_all(service: uvicorn.Server, page_server: http.server.ThreadingHTTPServer) -> None:
    """Close the tunnel, then stop the page server and the detection service.

    Waits until both ports are free, so Section 1 can be run again straight
    after. Safe to call twice.
    """
    ngrok.kill()
    page_server.shutdown()
    page_server.server_close()
    service.should_exit = True

    # The service stops on its own thread, a moment after should_exit is set.
    deadline = time.monotonic() + SHUTDOWN_TIMEOUT_S
    for port in (SERVICE_PORT, PAGE_PORT):
        while not port_is_free(port):
            if time.monotonic() > deadline:
                raise RuntimeError(f"Something is still listening on port {port}")
            time.sleep(0.1)
