from __future__ import annotations

import sys
from pathlib import Path

from flask import Flask, jsonify, request

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dashboard.data import dashboard_payload  # noqa: E402
from union_kobo_surveys import load_env, redact  # noqa: E402

load_env()

app = Flask(__name__, static_folder=str(ROOT / "public"), static_url_path="")


@app.get("/api/dashboard")
def dashboard():
    refresh = (request.args.get("refresh") or "0").lower() in {"1", "true", "yes"}
    try:
        return jsonify(dashboard_payload(refresh=refresh))
    except Exception as exc:
        return jsonify({"error": redact(exc)}), 500
