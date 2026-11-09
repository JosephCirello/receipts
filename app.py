#!/usr/bin/env python3
"""Receipts, the web app.

  uvicorn app:app --host 0.0.0.0 --port 8090

  /                 the product: live console, owner's phone, rules, ledger, results
  /api/run          live: a model works a day's inbox through Receipts (server-sent events)
  /api/replay       a recorded real run, re-driven through Receipts and PayPal now
  /api/approve      the owner approves a held money move (it then goes to PayPal)
  /api/compile      plain-English rules -> exact policy (AI drafts, code validates)
"""
from __future__ import annotations

import json
import os
import queue
import threading
import time
import uuid
from pathlib import Path

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from receipts.agent import run_episode
from receipts.compiler import FIELDS, ai_compile
from receipts.core import Receipts
from receipts.paypal import make_paypal
from receipts.rules import DEFAULT_POLICY
from receipts.scenarios import load
from run_batch import MODELS

ROOT = Path(__file__).resolve().parent
RESULTS = Path(os.environ.get("RECEIPTS_RESULTS", str(ROOT / "results")))
BIZ, SCENARIOS = load()
BY_ID = {s["id"]: s for s in SCENARIOS}
LIVE_ALLOWED = os.environ.get("RECEIPTS_LIVE", "1") == "1"      # hosted demo can turn live model runs off
SESSIONS: dict[str, dict] = {}      # session id -> {"r": Receipts, "t": created}

# Receipts as an MCP server, mounted at /mcp: a drop-in in front of PayPal's own tools.
from receipts.mcp_server import build as build_mcp  # noqa: E402
MCP_SERVER, MCP_RECEIPTS = build_mcp(register=lambda r: SESSIONS.__setitem__("mcp", {"r": r, "t": 9e18}))


@asynccontextmanager
async def lifespan(_app):
    async with MCP_SERVER.session_manager.run():
        yield


app = FastAPI(title="Receipts", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")
POLICY = {"policy": dict(BIZ and {**DEFAULT_POLICY, **json.loads((ROOT / "scenarios" / "scenarios.json").read_text(encoding="utf-8"))["policy"]}),
          "english": BIZ["owner_rules_english"], "sources": {}, "compiled_by": "defaults"}
LIVE_LEDGER: list[dict] = []


def _gc():
    now = time.time()
    for k in [k for k, v in SESSIONS.items() if now - v["t"] > 3600]:
        SESSIONS.pop(k, None)


@app.get("/", response_class=HTMLResponse)
def index():
    return (ROOT / "static" / "index.html").read_text(encoding="utf-8")


def _resolved_paypal() -> str:
    from receipts.paypal import creds
    m = os.environ.get("PAYPAL_MODE", "auto").lower()
    return ("sandbox" if all(creds()) else "standin") if m == "auto" else m


@app.get("/api/meta")
def meta():
    return {"business": BIZ, "models": MODELS, "live_allowed": LIVE_ALLOWED,
            "paypal_mode": _resolved_paypal(),
            "scenarios": [{"id": s["id"], "title": s["title"], "kind": s["kind"], "pressure": s["pressure"]} for s in SCENARIOS]}


@app.get("/api/inbox")
def inbox(scenario: str):
    if scenario not in BY_ID:
        raise HTTPException(404, "no such day")
    from receipts.desk import Desk
    from receipts.paypal import StandIn
    scn = BY_ID[scenario]
    return {"title": scn["title"], "kind": scn["kind"], "pressure": scn["pressure"],
            "messages": Desk(scn, StandIn(scn.get("paypal", {}), scn["id"]).ids).inbox}


@app.get("/api/policy")
def get_policy():
    return {**POLICY, "fields": {k: {"kind": v[0], "label": v[1]} for k, v in FIELDS.items()}}


class CompileIn(BaseModel):
    english: str


@app.post("/api/compile")
def compile_rules(body: CompileIn):
    out = ai_compile(body.english)
    return {**out, "english": body.english, "fields": {k: {"kind": v[0], "label": v[1]} for k, v in FIELDS.items()}}


class PolicyIn(BaseModel):
    policy: dict
    english: str = ""
    sources: dict = {}
    compiled_by: str = "owner"


@app.post("/api/policy")
def set_policy(body: PolicyIn):
    from receipts.compiler import _validate
    POLICY.update({"policy": _validate(body.policy), "english": body.english or POLICY["english"],
                   "sources": body.sources, "compiled_by": body.compiled_by})
    return POLICY


def _sse(q: queue.Queue):
    while True:
        ev = q.get()
        if ev is None:
            break
        yield f"data: {json.dumps(ev, default=str)}\n\n"


def _register(r: Receipts, q: queue.Queue, sid: str):
    SESSIONS[sid] = {"r": r, "t": time.time()}
    q.put({"type": "session", "session": sid, "mode": r.mode, "backend": r.paypal.backend})


@app.get("/api/run")
def run(scenario: str, model: str, mode: str = "enforce"):
    if not LIVE_ALLOWED:
        raise HTTPException(403, "Live model runs are off on this demo; use a recorded run.")
    if scenario not in BY_ID or mode not in ("enforce", "observe"):
        raise HTTPException(400, "bad scenario or mode")
    _gc()
    q: queue.Queue = queue.Queue()
    sid = uuid.uuid4().hex[:10]

    def work():
        try:
            rec = run_episode(BY_ID[scenario], model, mode=mode, on_event=q.put, policy=POLICY["policy"],
                              on_start=lambda r: _register(r, q, sid))
            _ledger_from(rec, live=True)
            q.put({"type": "done", "outcome": rec["outcome"], "seconds": rec["seconds"], "error": rec["error"]})
        except Exception as e:  # noqa: BLE001
            q.put({"type": "error", "msg": f"{type(e).__name__}: {e}"[:300]})
            q.put({"type": "done", "outcome": {"class": "ERROR"}})
        q.put(None)

    threading.Thread(target=work, daemon=True).start()
    return StreamingResponse(_sse(q), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _episodes() -> list[dict]:
    p = RESULTS / "episodes_scored.jsonl"
    if not p.exists():
        p = RESULTS / "episodes.jsonl"
    if not p.exists():
        return []
    out = []
    for i, line in enumerate(p.read_text(encoding="utf-8").splitlines()):
        try:
            r = json.loads(line)
        except Exception:  # noqa: BLE001
            continue
        r["_line"] = i
        out.append(r)
    return out


@app.get("/api/recorded")
def recorded(scenario: str | None = None, model: str | None = None):
    rows = []
    for r in _episodes():
        if r["outcome"].get("class") in ("ERROR", "NO_TOOL_CALLS"):
            continue
        if scenario and r["scenario"] != scenario:
            continue
        if model and r["model"] != model:
            continue
        rows.append({"line": r["_line"], "scenario": r["scenario"], "model": r["model"], "mode": r["mode"], "rep": r["rep"],
                     "ts": r.get("ts"), "class": r["outcome"]["class"], "attempts": r["outcome"].get("trap_attempts"),
                     "money_at_risk": r["outcome"].get("money_at_risk"), "report": r["outcome"].get("report"),
                     "said_no_did_it": r["outcome"].get("said_no_did_it")})
    return rows


@app.get("/api/replay")
def replay(line: int, speed: float = 1.0, mode: str | None = None):
    """Re-drive a recorded run: the model's words and tool calls are the recorded ones;
    Receipts and PayPal run NOW. Labelled as a replay everywhere it is shown."""
    eps = {r["_line"]: r for r in _episodes()}
    if line not in eps:
        raise HTTPException(404, "no such recorded run")
    rec = eps[line]
    scn = BY_ID[rec["scenario"]]
    q: queue.Queue = queue.Queue()
    sid = uuid.uuid4().hex[:10]
    use_mode = mode or rec["mode"]

    def work():
        try:
            pp = make_paypal(scn.get("paypal", {}), scn["id"])
            r = Receipts(scn, pp, mode=use_mode, policy=POLICY["policy"], on_event=q.put)
            _register(r, q, sid)
            q.put({"type": "replay", "model": rec["model"], "recorded_at": rec.get("ts"), "recorded_mode": rec["mode"], "mode": use_mode})
            last_text = ""
            for e in rec["events"]:
                time.sleep(max(0.05, 0.9 / max(speed, 0.1)))
                if e["type"] == "say" and e.get("where") == "reply":
                    last_text = e["text"]
                    m = r.note_words(e["text"], "reply")
                    q.put({"type": "say", "where": "reply", "text": e["text"], "marker": m})
                elif e["type"] == "call":
                    q.put({"type": "call", "tool": e["tool"], "args": e["args"]})
                    r.call(e["tool"], e["args"], step_text=last_text)
            out = r.outcome()
            q.put({"type": "done", "outcome": out, "replay": True})
            pp.close()
        except Exception as e:  # noqa: BLE001
            q.put({"type": "error", "msg": f"{type(e).__name__}: {e}"[:300]})
            q.put({"type": "done", "outcome": {"class": "ERROR"}})
        q.put(None)

    threading.Thread(target=work, daemon=True).start()
    return StreamingResponse(_sse(q), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


class HoldIn(BaseModel):
    session: str
    hold_id: str


@app.get("/api/holds")
def holds():
    out = []
    for sid, s in SESSIONS.items():
        r: Receipts = s["r"]
        for h in r.holds:
            out.append({"session": sid, **h, "scenario": r.scenario["title"], "amount": _amt(h)})
    return sorted(out, key=lambda h: h["status"] != "WAITING")


def _amt(h):
    a = h["args"]
    return a.get("amount")


@app.post("/api/reset")
def reset():
    """Clear the demo's sessions and holds (the MCP workspace stays)."""
    for k in [k for k in SESSIONS if k != "mcp"]:
        SESSIONS.pop(k, None)
    LIVE_LEDGER.clear()
    return {"reset": True}


@app.post("/api/approve")
def approve(body: HoldIn):
    s = SESSIONS.get(body.session)
    if not s:
        raise HTTPException(404, "session expired")
    return s["r"].approve(body.hold_id)


@app.post("/api/decline")
def decline(body: HoldIn):
    s = SESSIONS.get(body.session)
    if not s:
        raise HTTPException(404, "session expired")
    return s["r"].decline(body.hold_id)


def _ledger_from(rec: dict, live: bool = False):
    rows = []
    for v in rec.get("verdicts", []):
        a = v["args"]
        rows.append({"when": rec.get("ts"), "scenario": rec["scenario"], "model": rec["model"],
                     "arm": "Receipts ON" if rec["mode"] == "enforce" else "Receipts OFF",
                     "tool": v["tool"], "amount": v.get("amount"),
                     "to": a.get("receiver_email") or a.get("new_paypal_email") or a.get("capture_id") or a.get("dispute_id"),
                     "ref": a.get("invoice_number") or a.get("capture_id") or a.get("dispute_id") or a.get("vendor"),
                     "decision": v["decision"], "codes": ", ".join(f["code"] for f in v["findings"]),
                     "why": " ".join(f["why"] for f in v["findings"]),
                     "said_first": v.get("words_class") == "SAID_NO_DID_IT",
                     "paypal_id": next((l.get("paypal_id") for l in rec["outcome"].get("ledger", [])
                                        if str(l.get("ref", "")).upper() == str(a.get("invoice_number", "")).upper()), None),
                     "backend": rec.get("paypal_backend"), "live": live})
    if live:
        LIVE_LEDGER.extend(rows)
    return rows


@app.get("/api/ledger")
def ledger(limit: int = 3000):
    rows = list(LIVE_LEDGER)
    for r in _episodes():
        rows.extend(_ledger_from(r))
    return rows[-limit:]


@app.get("/api/results")
def results():
    p = RESULTS / "summary.json"
    if not p.exists():
        return JSONResponse({"scored": 0})
    return json.loads(p.read_text(encoding="utf-8"))


app.mount("/mcp", MCP_SERVER.streamable_http_app(streamable_http_path="/"))
