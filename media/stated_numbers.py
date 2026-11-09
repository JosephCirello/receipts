"""Every number the video, the cards and the README state, read from results/episodes_scored.jsonl.

  python media/stated_numbers.py
"""
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
rows = [json.loads(l) for l in (ROOT / "results" / "episodes_scored.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
latest = {}
for r in rows:
    latest[(r["model"], r["scenario"], r["mode"], r["rep"])] = r
rows = [r for r in latest.values() if r["outcome"].get("class") not in ("ERROR", "NO_TOOL_CALLS")]
models = sorted({r["model"] for r in rows})
reps = sorted({r["rep"] for r in rows})
days = sorted({r["scenario"] for r in rows})
off = [r for r in rows if r["mode"] == "observe"]
on = [r for r in rows if r["mode"] == "enforce"]


def arm(rs):
    traps = [r for r in rs if r["kind"] == "trap"]
    return {"runs": len(rs), "trap_days": len(traps),
            "trap_days_harm": sum(1 for r in traps if r["outcome"].get("bad_moved")),
            "harm_money": round(sum(r["outcome"].get("bad_money", 0) for r in rs), 2),
            "legit_done": sum(r["outcome"]["legit_done"] for r in rs), "legit_expected": sum(r["outcome"]["legit_expected"] for r in rs),
            "false_stops": sum(len(r["outcome"]["false_stops"]) for r in rs),
            "report_mismatch": sum(1 for r in rs if r["outcome"]["report"] == "MISMATCH"),
            "said_no_did_it": sum(r["outcome"]["said_no_did_it"] for r in rs)}


by_model_harm = defaultdict(set)
for r in off:
    for b in r["outcome"].get("bad_moved", []):
        by_model_harm[r["scenario"]].add(r["model"])
claims = sorted({(r["model"], r["scenario"], r["mode"], r["rep"]) for r in rows for v in r["verdicts"]
                 if any(f["code"] == "APPROVAL_CLAIMED_NOT_ON_FILE" for f in v["findings"])})
mism = sorted({(r["model"], r["scenario"], r["mode"], r["rep"], tuple(g["type"] for g in r["outcome"]["report_gaps"])) for r in rows
               if r["outcome"]["report"] == "MISMATCH"})
print(json.dumps({
    "models": len(models), "days": len(days), "reps_per_arm": len(reps), "scored_runs": len(rows),
    "receipts_off": arm(off), "receipts_on": arm(on),
    "models_that_moved_harm_by_day": {k: sorted(v) for k, v in sorted(by_model_harm.items())},
    "models_paid_duplicate_S2": len(by_model_harm.get("S2_second_notice", set())),
    "forged_payee_paid (S1, S10)": sorted(by_model_harm.get("S1_new_paypal_address", set()) | by_model_harm.get("S10_real_mailbox_new_remit", set())),
    "approval_claimed_not_on_file": claims, "report_mismatches": mism,
}, indent=1))
