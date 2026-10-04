"""BusBench REST API + Studio. Every function in busbench.api is POST /api/<name>.

    busbench serve            # http://127.0.0.1:8770 - API, and Studio in any browser

    curl -X POST http://127.0.0.1:8770/api/arinc429_build -H "Content-Type: application/json" \\
         -d '{"labels": "0203, ALTITUDE, ft, 1.0, 18", "label": "203", "value": 35000}'

Bound to 127.0.0.1 only. Requests must be JSON with a localhost Host
header, so a web page you visit cannot drive your bench.
"""
from __future__ import annotations

import json
import math
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import busbench
from busbench.api import LOCK, ROUTES

STATIC = os.path.join(os.path.dirname(__file__), "studio")
TYPES = {".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml", ".png": "image/png"}
PORT = 8770


def _clean(x):
    """JSON has no inf/nan; send null instead of a payload JS cannot parse."""
    if isinstance(x, float) and not math.isfinite(x):
        return None
    if isinstance(x, dict):
        return {k: _clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_clean(v) for v in x]
    return x


class Handler(BaseHTTPRequestHandler):
    server_version = f"BusBench/{busbench.__version__}"

    def log_message(self, *args):
        pass

    def _send(self, code, payload=None, body=None, ctype="application/json"):
        body = body if body is not None else json.dumps(_clean(payload)).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _guard(self) -> bool:
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
        if host not in ("127.0.0.1", "localhost"):
            self._send(403, {"error": "BusBench only answers on localhost"})
            return False
        return True

    def do_GET(self):
        if not self._guard():
            return
        path = self.path.split("?")[0]
        if path == "/api/health":
            return self._send(200, {"ok": True, "version": busbench.__version__})
        if path == "/api/routes":
            return self._send(200, sorted(ROUTES))
        rel = "index.html" if path == "/" else path.lstrip("/")
        full = os.path.normpath(os.path.join(STATIC, rel))
        if not full.startswith(STATIC) or not os.path.isfile(full):
            return self._send(404, {"error": "not found"})
        with open(full, "rb") as f:
            self._send(200, body=f.read(), ctype=TYPES.get(os.path.splitext(full)[1], "application/octet-stream"))

    def do_POST(self):
        if not self._guard():
            return
        name = self.path.split("?")[0].removeprefix("/api/")
        fn = ROUTES.get(name)
        if fn is None:
            return self._send(404, {"error": f"no endpoint /api/{name}"})
        if not (self.headers.get("Content-Type") or "").startswith("application/json"):
            return self._send(415, {"error": "requests must be sent as application/json"})
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            with LOCK:                       # one bench, one operator at a time
                out = fn(body)
            self._send(200, out)
        except Exception as exc:
            self._send(400, {"error": f"{type(exc).__name__}: {exc}"})


def make_server(port: int = PORT) -> ThreadingHTTPServer:
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    srv.daemon_threads = True
    return srv


def serve(port: int = PORT) -> None:
    print(f"BusBench API + Studio on http://127.0.0.1:{port}  (Ctrl+C to stop)")
    try:
        make_server(port).serve_forever()
    except KeyboardInterrupt:
        pass
