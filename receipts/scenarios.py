"""Load the public scenarios and give each one the business's shared records."""
from __future__ import annotations

import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILE = ROOT / "scenarios" / "scenarios.json"


def load(path: Path | None = None) -> tuple[dict, list[dict]]:
    data = json.loads((path or FILE).read_text(encoding="utf-8"))
    biz = data["business"]
    out = []
    for s in data["scenarios"]:
        s = copy.deepcopy(s)
        s["desk"].setdefault("vendors", copy.deepcopy(data["vendors"]))
        s["policy"] = {**data.get("policy", {}), **s.get("policy", {})}
        s["business"] = biz
        out.append(s)
    return biz, out


def by_id() -> dict[str, dict]:
    return {s["id"]: s for s in load()[1]}
