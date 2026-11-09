#!/usr/bin/env python3
"""Re-score every recorded episode with the CURRENT rules and ground truth.

The model's words and tool calls are the recorded ones (nothing is re-asked of
any model). They are replayed, in order, through a fresh Receipts and a fresh
stand-in PayPal in the episode's own arm, and the outcome is recomputed. The raw
file is never edited: results/episodes.jsonl stays as recorded, and
results/episodes_scored.jsonl holds the re-scored copy that every table reads.

  python regrade.py            # re-score, then rewrite results/summary.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from receipts.core import Receipts  # noqa: E402
from receipts.paypal import StandIn  # noqa: E402
from receipts.scenarios import by_id  # noqa: E402
import run_batch  # noqa: E402

S = by_id()


def rescore(rec: dict) -> dict:
    scn = S.get(rec["scenario"])
    if not scn or rec["outcome"].get("class") in ("ERROR", "NO_TOOL_CALLS") or rec.get("paypal_backend") != "standin":
        return rec
    pp = StandIn(scn["paypal"], scn["id"])
    r = Receipts(scn, pp, mode=rec["mode"], policy=scn.get("policy"))
    # the recorded run's own refund ids (the agent may cite them in its report) -> the order they refunded
    for e in rec.get("events", []):
        if e["type"] == "paypal" and e.get("tool") == "create_refund" and isinstance(e.get("result"), dict) and e["result"].get("id"):
            cr = pp.capture_record(str(e["args"].get("capture_id", "")))
            if cr:
                r.id_aliases[str(e["result"]["id"]).upper()] = str(cr["order_id"]).upper()
    last = ""
    for e in rec.get("events", []):
        if e["type"] == "say" and e.get("where") == "reply":
            last = e["text"]
            r.note_words(e["text"], "reply")
        elif e["type"] == "call":
            r.call(e["tool"], e["args"], step_text=last)
    out = r.outcome()
    moved = {"class", "trap_attempts", "said_no_did_it", "money_at_risk", "bad_money", "report", "legit_done", "false_stops"}
    diff = {k: (rec["outcome"].get(k), out.get(k)) for k in moved if rec["outcome"].get(k) != out.get(k)}
    new = dict(rec)
    new["outcome"], new["verdicts"], new["said"], new["report_check"] = out, r.verdicts, r.said, r.report_check
    new["regraded"] = {"changed": diff}
    return new


def main():
    src = run_batch.RESULTS / "episodes.jsonl"
    dst = run_batch.RESULTS / "episodes_scored.jsonl"
    n = changed = 0
    with dst.open("w", encoding="utf-8") as out:
        for line in src.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            new = rescore(rec)
            n += 1
            if new.get("regraded", {}).get("changed"):
                changed += 1
            out.write(json.dumps(new, default=str) + "\n")
    print(f"re-scored {n} episodes; {changed} changed in at least one field")
    run_batch.EPISODES = dst
    s = run_batch.summarize()
    print(json.dumps({k: s[k] for k in ("scored", "not_scored", "observe", "enforce")}, indent=1))


if __name__ == "__main__":
    main()
