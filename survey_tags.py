from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
TAGS_PATH = ROOT / "survey_tags.json"


def load_tag_map() -> dict:
    return json.loads(TAGS_PATH.read_text(encoding="utf-8"))


def lookup_tag(survey_name: str | None, survey_uid: str | None, tag_map: dict | None = None) -> dict[str, str]:
    data = tag_map or load_tag_map()
    surveys = data.get("surveys") or {}
    if survey_name and survey_name in surveys:
        row = surveys[survey_name]
        return {"brand": row.get("brand", "Untagged"), "arm": row.get("arm", "untagged")}
    if survey_uid:
        for row in surveys.values():
            if row.get("uid") == survey_uid:
                return {"brand": row.get("brand", "Untagged"), "arm": row.get("arm", "untagged")}
    return {"brand": "Untagged", "arm": "untagged"}


def apply_survey_tags(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        frame = frame.copy()
        frame["brand"] = pd.Series(dtype="object")
        frame["arm"] = pd.Series(dtype="object")
        return frame
    tag_map = load_tag_map()
    tagged = frame.copy()
    brands = []
    arms = []
    for _, row in tagged.iterrows():
        tag = lookup_tag(row.get("survey_name"), row.get("survey_uid"), tag_map)
        brands.append(tag["brand"])
        arms.append(tag["arm"])
    tagged["brand"] = brands
    tagged["arm"] = arms
    preferred = [col for col in ["survey_name", "survey_uid", "brand", "arm"] if col in tagged.columns]
    remaining = [col for col in tagged.columns if col not in preferred]
    return tagged[preferred + remaining]
