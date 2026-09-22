from __future__ import annotations

import json
import os
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
if str(ROOT.parent) not in sys.path:
    sys.path.insert(0, str(ROOT.parent))

from union_kobo_surveys import load_env, redact  # noqa: E402
from dashboard.data import dashboard_payload  # noqa: E402


class DashboardHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC), **kwargs)

    def log_message(self, format: str, *args) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), redact(format % args)))

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        lowered = parsed.path.lower()
        if lowered.endswith(".env") or "/.env" in lowered or "/.git" in lowered:
            self.send_error(404)
            return
        if parsed.path in {"/", "/index.html"}:
            self.path = "/index.html"
            return super().do_GET()
        if parsed.path == "/api/dashboard":
            query = parse_qs(parsed.query)
            refresh = (query.get("refresh") or ["0"])[0].lower() in {"1", "true", "yes"}
            try:
                payload = dashboard_payload(refresh=refresh)
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
            except Exception as exc:
                body = json.dumps({"error": redact(exc)}).encode("utf-8")
                self.send_response(500)
                self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        return super().do_GET()


def main(host: str | None = None, port: int | None = None) -> None:
    load_env()
    host = host or os.environ.get("HOST", "127.0.0.1")
    port = port or int(os.environ.get("PORT", "8050"))
    server = ThreadingHTTPServer((host, port), DashboardHandler)
    print(f"Dashboard: http://{host}:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
