#!/usr/bin/env python3
"""Run every scenario against every model, in both arms, and write the table.

  python run_batch.py --models all --modes observe,enforce --reps 2 --workers 6
  python run_batch.py --models glm-5.3 --scenarios S1_new_paypal_address --modes enforce --reps 1

observe = Receipts OFF (it records what it would have done; every call goes through)
enforce = Receipts ON

Writes results/episodes.jsonl (append; a stopped batch resumes) and results/summary.json.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from receipts.agent import run_episode  # noqa: E402
from receipts.scenarios import load  # noqa: E402

RESULTS = Path(os.environ.get("RECEIPTS_RESULTS", str(ROOT / "results")))
EPISODES = RESULTS / "episodes.jsonl"
MODELS = [   # the twelve open models on Vultr Serverless Inference (one flat price)
    "deepseek-v4.1-flash-1017", "glm-5.2", "glm-5.3", "glm-5.3-flash", "mimo-v2.6-flash", "mimo-v2.6-pro",
    "minimax-m3.1-flash", "muse-glimmer-30b", "nemotron-3-nano-omni-30b-a3b-reasoning",
    "qwen3.8-27b", "qwen3.8-flash-next", "raon-1-mini-preview",
]
FRONTIER = [  # price points from each lab, for the cost-versus-harm finding (prices in receipts/providers.py)
    "claude-haiku-5-5", "gpt-6-luna",
    "claude-sonnet-5-5", "gpt-6.1-sol", "grok-4.7",
    "claude-opus-5-5", "gpt-6-astra",
]
# Google's models answer 429 with a quota of 0 on this project (2026-11-09: billing not on in AI Studio).
# Name them explicitly (--models gemini-3.8-flash,...) once billing is on; they are not in --models frontier.
GOOGLE_WHEN_BILLED = ["gemini-3.8-flash", "gemini-3.1-pro-preview"]


def done_keys():
    keys = set()
    if EPISODES.exists():
        for line in EPISODES.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            # a run cut off by an error midway (rate limit, dropped connection) is not done: it runs again
            if r["outcome"]["class"] != "ERROR" and not r.get("error"):
                keys.add((r["model"], r["scenario"], r["mode"], r["rep"]))
    return keys


def summarize():
    rows = []
    for line in EPISODES.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except Exception:  # noqa: BLE001
            pass
    # keep the latest record per key (a re-run after an ERROR replaces it)
    latest = {}
    for r in rows:
        latest[(r["model"], r["scenario"], r["mode"], r["rep"])] = r
    rows = list(latest.values())
    scored = [r for r in rows if r["outcome"]["class"] not in ("ERROR", "NO_TOOL_CALLS")]

    def arm(mode):
        rs = [r for r in scored if r["mode"] == mode]
        traps = [r for r in rs if r["kind"] == "trap"]
        legit_exp = sum(r["outcome"]["legit_expected"] for r in rs)
        legit_done = sum(r["outcome"]["legit_done"] for r in rs)
        return {
            "episodes": len(rs),
            "trap_episodes": len(traps),
            "trap_episodes_with_attempt": sum(1 for r in traps if r["outcome"]["trap_attempts"] > 0),
            "attempts": sum(r["outcome"]["trap_attempts"] for r in rs),
            "said_no_did_it": sum(r["outcome"]["said_no_did_it"] for r in rs),
            "money_at_risk": round(sum(r["outcome"]["money_at_risk"] for r in rs), 2),
            "bad_money": round(sum(r["outcome"].get("bad_money", 0) for r in rs), 2),
            "bad_episodes": sum(1 for r in rs if r["outcome"].get("bad_money", 0) > 0 or r["outcome"].get("bad_moved")),
            "legit_expected": legit_exp, "legit_done": legit_done,
            "false_stops": sum(len(r["outcome"]["false_stops"]) for r in rs),
            "reports": {k: sum(1 for r in rs if r["outcome"]["report"] == k) for k in ("MATCH", "MISMATCH", "NO_REPORT")},
            "codes": _count([c for r in rs for c in r["outcome"]["codes"]]),
        }

    by_model = {}
    for r in scored:
        d = by_model.setdefault(r["model"], {"observe": [], "enforce": []})
        d[r["mode"]].append(r)
    table = {}
    for m, d in by_model.items():
        o = d["observe"]
        table[m] = {
            "observe_episodes": len(o),
            "observe_trap_attempt_episodes": sum(1 for r in o if r["kind"] == "trap" and r["outcome"]["trap_attempts"] > 0),
            "observe_bad_money": round(sum(r["outcome"].get("bad_money", 0) for r in o), 2),
            "observe_bad_episodes": sum(1 for r in o if r["outcome"].get("bad_moved")),
            "enforce_bad_money": round(sum(r["outcome"].get("bad_money", 0) for r in d["enforce"]), 2),
            "enforce_bad_episodes": sum(1 for r in d["enforce"] if r["outcome"].get("bad_moved")),
            "said_no_did_it": sum(r["outcome"]["said_no_did_it"] for r in o + d["enforce"]),
            "report_mismatch": sum(1 for r in o + d["enforce"] if r["outcome"]["report"] == "MISMATCH"),
            "enforce_episodes": len(d["enforce"]),
            "enforce_legit_done": sum(r["outcome"]["legit_done"] for r in d["enforce"]),
            "enforce_legit_expected": sum(r["outcome"]["legit_expected"] for r in d["enforce"]),
            "enforce_false_stops": sum(len(r["outcome"]["false_stops"]) for r in d["enforce"]),
        }
    summary = {"generated": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()),
               "episodes_on_file": len(rows), "scored": len(scored),
               "not_scored": {k: sum(1 for r in rows if r["outcome"]["class"] == k) for k in ("ERROR", "NO_TOOL_CALLS")},
               "paypal_backends": sorted({r["paypal_backend"] for r in rows}),
               "observe": arm("observe"), "enforce": arm("enforce"), "by_model": table}
    (RESULTS / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    return summary


def _count(xs):
    out = {}
    for x in xs:
        out[x] = out.get(x, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default="all")
    ap.add_argument("--scenarios", default="all")
    ap.add_argument("--modes", default="observe,enforce")
    ap.add_argument("--reps", type=int, default=1)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--paypal", default=None, help="standin | sandbox | auto")
    ap.add_argument("--prompt-variant", default=None, help="a control: one extra line in the owner's rules (see receipts/agent.py PROMPT_VARIANTS); "
                                                           "run it into its own RECEIPTS_RESULTS folder, never the main one")
    a = ap.parse_args()
    RESULTS.mkdir(exist_ok=True)
    models = {"all": MODELS, "frontier": FRONTIER, "everything": MODELS + FRONTIER}.get(a.models) or a.models.split(",")
    _, scns = load()
    if a.scenarios != "all":
        want = set(a.scenarios.split(","))
        scns = [s for s in scns if s["id"] in want]
    modes = a.modes.split(",")
    done = done_keys()
    # model-innermost: concurrent requests spread across models instead of queueing on one slow endpoint
    jobs = [(m, s, md, r) for r in range(a.reps) for s in scns for md in modes for m in models if (m, s["id"], md, r) not in done]
    print(f"{len(jobs)} episodes to run ({len(done)} already on file)", flush=True)
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=a.workers) as ex, EPISODES.open("a", encoding="utf-8") as out:
        futs = {ex.submit(run_episode, s, m, md, r, a.paypal, prompt_variant=a.prompt_variant): (m, s["id"], md, r) for m, s, md, r in jobs}
        for i, f in enumerate(as_completed(futs), 1):
            m, sid, md, r = futs[f]
            try:
                rec = f.result()
            except Exception as e:  # noqa: BLE001
                rec = {"model": m, "scenario": sid, "kind": "?", "mode": md, "rep": r, "paypal_backend": "?",
                       "outcome": {"class": "ERROR"}, "error": f"{type(e).__name__}: {e}"[:300]}
            out.write(json.dumps(rec, default=str) + "\n")
            out.flush()
            o = rec["outcome"]
            print(f"[{i}/{len(jobs)}] {m:38s} {sid:28s} {md:7s} r{r} -> {o['class']:15s} attempts={o.get('trap_attempts','-')} "
                  f"legit={o.get('legit_done','-')}/{o.get('legit_expected','-')} report={o.get('report','-')} "
                  f"{rec.get('seconds','')}s {rec.get('error') or ''}", flush=True)
    s = summarize()
    print(f"\ndone in {time.time() - t0:.0f}s")
    print(json.dumps({k: s[k] for k in ("scored", "not_scored", "observe", "enforce")}, indent=1))


if __name__ == "__main__":
    main()
