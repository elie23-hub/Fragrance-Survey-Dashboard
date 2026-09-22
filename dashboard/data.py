from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from survey_tags import apply_survey_tags, load_tag_map
from union_kobo_surveys import BASE_URL, get_json, load_env, paginate, redact, session, submissions_to_frame

ROOT = Path(__file__).resolve().parent.parent
UNION_CSV = ROOT / "output" / "kobo_union.csv"
REQUIRED_COLUMNS = (
    "survey_name",
    "survey_uid",
    "brand",
    "arm",
    "S1",
    "S2",
    "S3",
    "_submission_time",
    "_status",
)
QUESTION_META = {
    "S1": {
        "title": "S1 · Age",
        "labels": {
            "1": "Under 25",
            "2": "25–35",
            "3": "36–45",
            "4": "46–55",
            "5": "56–65",
            "6": "65+",
        },
    },
    "S2": {
        "title": "S2 · Gender",
        "labels": {"1": "Male", "2": "Female"},
    },
    "S3": {
        "title": "S3 · Used fragrance in last 3 months",
        "labels": {"1": "Yes", "2": "No"},
    },
}

_LOCK = threading.Lock()
_CACHE: dict[str, Any] = {
    "frame": None,
    "counts": None,
    "fetched_at": None,
    "source": None,
    "error": None,
}


def _code(value: Any) -> str | None:
    if pd.isna(value):
        return None
    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    return text or None


def _empty_frame() -> pd.DataFrame:
    return pd.DataFrame({column: pd.Series(dtype="object") for column in REQUIRED_COLUMNS})


def _column_or_grouped(frame: pd.DataFrame, name: str) -> pd.Series:
    if name in frame.columns and frame[name].notna().any():
        return frame[name]
    matches = [
        column
        for column in frame.columns
        if str(column).endswith(f"/{name}") or str(column).endswith(f".{name}")
    ]
    if matches:
        return frame[matches[0]]
    if name in frame.columns:
        return frame[name]
    return pd.Series(index=frame.index, dtype="object")


def _prepare_frame(frame: pd.DataFrame) -> pd.DataFrame:
    prepared = apply_survey_tags(frame)
    for column in REQUIRED_COLUMNS:
        if column not in prepared.columns:
            prepared[column] = pd.Series(dtype="object")
    if "_submission_time" in prepared.columns:
        prepared["_submission_time"] = pd.to_datetime(prepared["_submission_time"], utc=True, errors="coerce")
    for column in ("S1", "S2", "S3"):
        prepared[column] = _column_or_grouped(prepared, column).map(_code)
    return prepared


def _read_csv_union() -> pd.DataFrame:
    if not UNION_CSV.exists():
        return _empty_frame()
    return _prepare_frame(pd.read_csv(UNION_CSV))


def _tagged_surveys() -> dict[str, dict[str, str]]:
    return load_tag_map().get("surveys") or {}


def _fetch_survey_count(uid: str) -> tuple[str, int]:
    http = session()
    asset = get_json(http, f"{BASE_URL}/api/v2/assets/{uid}/", params={"format": "json"})
    return uid, int(asset.get("deployment__submission_count") or 0)


def _current_counts() -> dict[str, int]:
    surveys = _tagged_surveys()
    counts: dict[str, int] = {}
    with ThreadPoolExecutor(max_workers=min(8, max(1, len(surveys)))) as pool:
        futures = [pool.submit(_fetch_survey_count, info["uid"]) for info in surveys.values()]
        for future in as_completed(futures):
            uid, count = future.result()
            counts[uid] = count
    return counts


def _fetch_survey_frame(name: str, uid: str) -> pd.DataFrame:
    http = session()
    submissions = paginate(
        http,
        f"{BASE_URL}/api/v2/assets/{uid}/data/",
        params={"format": "json", "limit": 1000},
    )
    frame = submissions_to_frame(submissions)
    if frame.empty:
        frame = pd.DataFrame()
    frame.insert(0, "survey_name", name)
    frame.insert(1, "survey_uid", uid)
    return frame


def _fetch_live_union() -> tuple[pd.DataFrame, dict[str, int]]:
    load_env()
    surveys = _tagged_surveys()
    if not surveys:
        return _empty_frame(), {}

    counts = _current_counts()
    frames: list[pd.DataFrame] = []
    errors: list[BaseException] = []
    with ThreadPoolExecutor(max_workers=min(8, max(1, len(surveys)))) as pool:
        futures = {
            pool.submit(_fetch_survey_frame, name, info["uid"]): name
            for name, info in surveys.items()
        }
        for future in as_completed(futures):
            try:
                frames.append(future.result())
            except Exception as exc:
                errors.append(exc)

    if not frames:
        raise errors[0] if errors else RuntimeError("No Kobo surveys could be fetched.")

    union = pd.concat(frames, ignore_index=True, sort=False)
    prepared = _prepare_frame(union)
    try:
        UNION_CSV.parent.mkdir(parents=True, exist_ok=True)
        prepared.to_csv(UNION_CSV, index=False, encoding="utf-8-sig")
    except OSError:
        pass
    return prepared, counts


def load_union(refresh: bool = False) -> tuple[pd.DataFrame, dict[str, Any]]:
    load_env()
    with _LOCK:
        cached = _CACHE["frame"]
        cached_counts = _CACHE["counts"]
        if cached is not None and not refresh:
            try:
                counts = _current_counts()
            except (Exception, SystemExit) as exc:
                return cached, {
                    "source": _CACHE["source"] or "kobo",
                    "fetched_at": _CACHE["fetched_at"],
                    "error": redact(exc),
                    "stale": True,
                }
            if counts == cached_counts:
                return cached, {
                    "source": _CACHE["source"] or "kobo",
                    "fetched_at": _CACHE["fetched_at"],
                    "error": None,
                    "stale": False,
                }

        try:
            frame, counts = _fetch_live_union()
            fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
            _CACHE.update(
                {
                    "frame": frame,
                    "counts": counts,
                    "fetched_at": fetched_at,
                    "source": "kobo",
                    "error": None,
                }
            )
            return frame, {"source": "kobo", "fetched_at": fetched_at, "error": None, "stale": False}
        except (Exception, SystemExit) as exc:
            fallback = cached if cached is not None else _read_csv_union()
            fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
            source = "csv_fallback" if cached is None else (_CACHE["source"] or "kobo")
            _CACHE.update({"error": redact(exc)})
            return fallback, {
                "source": source,
                "fetched_at": _CACHE["fetched_at"] or fetched_at,
                "error": redact(exc),
                "stale": True,
            }


def frequencies(frame: pd.DataFrame, column: str) -> list[dict[str, Any]]:
    total = len(frame)
    labels = QUESTION_META[column]["labels"]
    if column not in frame.columns or not total:
        counts: dict[Any, int] = {}
    else:
        counts = frame[column].fillna("__na__").value_counts(dropna=False).to_dict()

    rows = []
    seen: set[str] = set()
    for code, label in labels.items():
        count = int(counts.get(code, 0))
        seen.add(code)
        rows.append(
            {
                "code": code,
                "label": label,
                "count": count,
                "pct": round((count / total) * 100, 1) if total else 0,
            }
        )
    for raw, count in counts.items():
        code = None if raw == "__na__" else str(raw)
        if code is None or code in seen:
            continue
        rows.append(
            {
                "code": code,
                "label": f"Code {code}",
                "count": int(count),
                "pct": round((int(count) / total) * 100, 1) if total else 0,
            }
        )
    missing = int(counts.get("__na__", 0))
    if missing:
        rows.append(
            {
                "code": None,
                "label": "Not asked",
                "count": missing,
                "pct": round((missing / total) * 100, 1) if total else 0,
            }
        )
    return rows


def _arm_slice(frame: pd.DataFrame, arm: str) -> pd.DataFrame:
    if not len(frame) or "arm" not in frame.columns:
        return frame.iloc[0:0]
    return frame[frame["arm"] == arm]


def _arm_frequencies(group: pd.DataFrame, survey: str, arm: str) -> dict[str, Any]:
    last = group["_submission_time"].max() if len(group) and "_submission_time" in group.columns else pd.NaT
    return {
        "arm": arm,
        "survey": survey,
        "submissions": int(len(group)),
        "last_submission": last.isoformat() if pd.notna(last) else None,
        "gender": frequencies(group, "S2"),
        "age": frequencies(group, "S1"),
    }


def survey_frequencies(frame: pd.DataFrame) -> list[dict[str, Any]]:
    tag_map = load_tag_map()
    blocks = []
    for brand, spec in (tag_map.get("brands") or {}).items():
        group = frame[frame["brand"] == brand] if len(frame) else frame.iloc[0:0]
        control_name = spec.get("control") or f"{brand}1"
        experimental_name = spec.get("experimental") or f"{brand}2"
        blocks.append(
            {
                "brand": brand,
                "title": "Fragrance Survey",
                "control": _arm_frequencies(_arm_slice(group, "control"), control_name, "control"),
                "experimental": _arm_frequencies(
                    _arm_slice(group, "experimental"), experimental_name, "experimental"
                ),
            }
        )
    blocks.sort(key=lambda row: row["brand"])
    return blocks


def dashboard_payload(refresh: bool = False) -> dict[str, Any]:
    full, meta = load_union(refresh=refresh)
    last = full["_submission_time"].max() if len(full) else pd.NaT
    control_n = int((full["arm"] == "control").sum()) if len(full) else 0
    experimental_n = int((full["arm"] == "experimental").sum()) if len(full) else 0
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fetched_at": meta.get("fetched_at"),
        "source": meta.get("source") or "kobo",
        "stale": bool(meta.get("stale")),
        "error": meta.get("error"),
        "submissions": int(len(full)),
        "control_n": control_n,
        "experimental_n": experimental_n,
        "last_submission": last.isoformat() if pd.notna(last) else None,
        "surveys": survey_frequencies(full),
    }
