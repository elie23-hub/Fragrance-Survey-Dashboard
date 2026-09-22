from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dashboard.data import dashboard_payload  # noqa: E402
from union_kobo_surveys import load_env, redact  # noqa: E402

load_env()


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        query = parse_qs(urlparse(self.path).query)
        refresh = (query.get("refresh") or ["0"])[0].lower() in {"1", "true", "yes"}
        try:
            payload = dashboard_payload(refresh=refresh)
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            status = 200
        except Exception as exc:
            body = json.dumps({"error": redact(exc)}).encode("utf-8")
            status = 500
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), redact(format % args)))
