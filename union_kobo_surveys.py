"""
Shared KoboToolbox helpers: discover REST-enabled surveys, submit records, fetch data, union.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

import pandas as pd
import requests

from survey_tags import apply_survey_tags, lookup_tag

ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "output"
BASE_URL = os.environ.get("KOBO_KF_URL", "https://kf.kobotoolbox.org").rstrip("/")
META_COLUMNS = [
    "survey_name",
    "survey_uid",
    "brand",
    "arm",
    "rest_service_name",
    "rest_service_endpoint",
]


def load_env(path: Path | None = None) -> None:
    env_path = path or (ROOT / ".env")
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def redact(text: str) -> str:
    value = os.environ.get("KOBO_TOKEN", "").strip()
    if value:
        return str(text).replace(value, "[redacted]")
    return str(text)


def token() -> str:
    value = os.environ.get("KOBO_TOKEN", "").strip()
    if not value:
        raise SystemExit("KOBO_TOKEN is missing. Put it in .env or set the environment variable.")
    return value


def auth_headers() -> dict[str, str]:
    return {
        "Authorization": f"Token {token()}",
        "Accept": "application/json",
    }


def session() -> requests.Session:
    s = requests.Session()
    s.headers.update(auth_headers())
    return s


def get_json(s: requests.Session, url: str, params: dict[str, Any] | None = None) -> Any:
    response = s.get(url, params=params, timeout=60)
    response.raise_for_status()
    return response.json()


def paginate(s: requests.Session, url: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    while url:
        payload = get_json(s, url, params=params)
        params = None
        if isinstance(payload, list):
            rows.extend(payload)
            break
        rows.extend(payload.get("results") or [])
        url = payload.get("next")
    return rows


def flatten_value(value: Any) -> Any:
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return value


def submissions_to_frame(submissions: list[dict[str, Any]]) -> pd.DataFrame:
    if not submissions:
        return pd.DataFrame()
    frame = pd.json_normalize(submissions)
    for column in frame.columns:
        frame[column] = frame[column].map(flatten_value)
    return frame


def form_field_order(asset: dict[str, Any]) -> list[str]:
    survey = ((asset.get("content") or {}).get("survey") or [])
    names: list[str] = []
    for row in survey:
        qtype = str(row.get("type") or "")
        if qtype in {"begin_group", "end_group", "begin_repeat", "end_repeat", "note"}:
            continue
        name = row.get("name") or row.get("$autoname")
        if name:
            names.append(str(name))
    return names


def discover_rest_surveys(s: requests.Session) -> list[dict[str, Any]]:
    assets = paginate(
        s,
        f"{BASE_URL}/api/v2/assets/",
        params={"format": "json", "asset_type": "survey", "limit": 100},
    )
    selected: list[dict[str, Any]] = []
    for asset in assets:
        uid = asset["uid"]
        hooks = paginate(s, f"{BASE_URL}/api/v2/assets/{uid}/hooks/", params={"format": "json"})
        if not hooks:
            continue
        detail = get_json(s, f"{BASE_URL}/api/v2/assets/{uid}/", params={"format": "json"})
        settings = (detail.get("content") or {}).get("settings") or {}
        selected.append(
            {
                "uid": uid,
                "name": asset.get("name") or uid,
                "owner": detail.get("owner__username") or "statometry",
                "id_string": settings.get("id_string") or uid,
                "version_id": detail.get("deployed_version_id") or detail.get("version_id") or "",
                "formhub_uuid": detail.get("deployment__uuid") or "",
                "submission_count": asset.get("deployment__submission_count") or 0,
                "data_url": detail.get("data") or f"{BASE_URL}/api/v2/assets/{uid}/data/",
                "hooks": hooks,
                "field_order": form_field_order(detail),
            }
        )
    return selected


def fetch_survey_frame(s: requests.Session, survey: dict[str, Any]) -> pd.DataFrame:
    submissions = paginate(
        s,
        survey["data_url"],
        params={"format": "json", "limit": 1000},
    )
    frame = submissions_to_frame(submissions)
    hook_names = ", ".join(str(h.get("name") or "") for h in survey["hooks"])
    hook_endpoints = ", ".join(str(h.get("endpoint") or "") for h in survey["hooks"])
    if frame.empty:
        frame = pd.DataFrame(columns=survey["field_order"])
    frame.insert(0, "survey_name", survey["name"])
    frame.insert(1, "survey_uid", survey["uid"])
    frame.insert(2, "rest_service_name", hook_names)
    frame.insert(3, "rest_service_endpoint", hook_endpoints)
    return frame


def order_columns(union: pd.DataFrame, surveys: list[dict[str, Any]]) -> pd.DataFrame:
    preferred: list[str] = []
    seen: set[str] = set()
    for name in META_COLUMNS:
        if name in union.columns and name not in seen:
            preferred.append(name)
            seen.add(name)
    for survey in surveys:
        for name in survey["field_order"]:
            if name in union.columns and name not in seen:
                preferred.append(name)
                seen.add(name)
    remaining = [c for c in union.columns if c not in seen]
    return union[preferred + remaining]


def union_surveys(surveys: list[dict[str, Any]], frames: list[pd.DataFrame]) -> pd.DataFrame:
    if not frames:
        return pd.DataFrame(columns=META_COLUMNS)
    union = apply_survey_tags(pd.concat(frames, ignore_index=True, sort=False))
    return order_columns(union, surveys)


def build_submission_xml(
    survey: dict[str, Any],
    answers: dict[str, str],
    instance_id: str,
) -> bytes:
    fields = "\n".join(
        f"  <{name}>{escape(str(value))}</{name}>" for name, value in answers.items()
    )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<{survey["uid"]} id="{escape(survey["id_string"])}" version="{escape(survey["version_id"])}">\n'
        f'  <formhub><uuid>{escape(survey["formhub_uuid"])}</uuid></formhub>\n'
        f"{fields}\n"
        f"  <meta><instanceID>{escape(instance_id)}</instanceID></meta>\n"
        f'</{survey["uid"]}>\n'
    )
    return xml.encode("utf-8")


def submit_record(survey: dict[str, Any], answers: dict[str, str], instance_id: str) -> requests.Response:
    url = f"{BASE_URL}/{survey['owner']}/submission"
    files = {
        "xml_submission_file": (
            "submission.xml",
            build_submission_xml(survey, answers, instance_id),
            "text/xml",
        )
    }
    headers = {
        "Authorization": f"Token {token()}",
        "X-OpenRosa-Version": "1.0",
    }
    return requests.post(url, headers=headers, files=files, timeout=60)


def save_outputs(
    union: pd.DataFrame,
    surveys: list[dict[str, Any]],
    frames: list[pd.DataFrame] | None = None,
    concurrent: pd.DataFrame | None = None,
) -> dict[str, Path]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    paths = {
        "csv": OUTPUT_DIR / "kobo_union.csv",
        "xlsx": OUTPUT_DIR / "kobo_union.xlsx",
        "html": OUTPUT_DIR / "kobo_union.html",
        "pickle": OUTPUT_DIR / "kobo_union.pkl",
    }
    union.to_csv(paths["csv"], index=False, encoding="utf-8-sig")
    union.to_pickle(paths["pickle"])
    union.to_html(paths["html"], index=False, border=0)

    inventory = pd.DataFrame(
        [
            {
                "survey_name": survey["name"],
                "survey_uid": survey["uid"],
                "brand": lookup_tag(survey["name"], survey["uid"])["brand"],
                "arm": lookup_tag(survey["name"], survey["uid"])["arm"],
                "submissions_in_kobo": survey["submission_count"],
                "rows_in_union": 0 if frames is None else len(frames[i]),
                "rest_services": len(survey["hooks"]),
                "rest_service_names": ", ".join(str(h.get("name") or "") for h in survey["hooks"]),
            }
            for i, survey in enumerate(surveys)
        ]
    )
    with pd.ExcelWriter(paths["xlsx"], engine="openpyxl") as writer:
        union.to_excel(writer, sheet_name="union", index=False)
        inventory.to_excel(writer, sheet_name="surveys_included", index=False)
        if concurrent is not None:
            concurrent.to_excel(writer, sheet_name="concurrent_test", index=False)
        if frames:
            for survey, frame in zip(surveys, frames):
                sheet = "".join(ch for ch in survey["name"] if ch.isalnum() or ch in " _-")[:28] or survey["uid"][:28]
                frame.to_excel(writer, sheet_name=sheet, index=False)
    return paths
