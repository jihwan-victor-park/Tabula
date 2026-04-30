from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Sequence

from clawbot.api.routes import ApiRoutes


def serve(
    host: str = "127.0.0.1",
    port: int = 8000,
    watch_recipients: Sequence[str] = (),
    forward_url: str = "http://localhost:8006/ask",
    business_name: str = "My Store",
    business_location: str = "US",
) -> None:
    routes = ApiRoutes()

    # Start inbox listener if recipients are configured
    if watch_recipients:
        from clawbot.agents.inbox_listener import InboxListener
        listener = InboxListener(
            watched_numbers=list(watch_recipients),
            forward_url=forward_url,
            business_name=business_name,
            business_location=business_location,
        )
        listener.start()

    class RequestHandler(BaseHTTPRequestHandler):
        def _send_json(self, status: int, payload: dict) -> None:
            body = json.dumps(payload, indent=2).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            status, payload = routes.handle("GET", self.path)
            self._send_json(int(status), payload)

        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length > 0 else b"{}"
            try:
                body = json.loads(raw)
            except Exception:
                body = {}
            status, payload = routes.handle("POST", self.path, body)
            self._send_json(int(status), payload)

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer((host, port), RequestHandler)
    print(f"Serving Clawbot API on http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
