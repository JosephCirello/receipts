#!/usr/bin/env python3
"""Receipts, the web app.

  uvicorn app:app --host 0.0.0.0 --port 8090

  /                 the product: live console, owner's phone, rules, ledger, results
  /api/run          live: a model works a day's inbox through Receipts (server-sent events)
  /api/replay       a recorded real run, re-driven through Receipts and PayPal now
  /api/approve      the owner approves a held money move (it then goes to PayPal)
  /api/compile      plain-English rules -> exact policy (AI drafts, code validates)

Every visitor has their own state. The first request sets an opaque random id in a cookie; the held
payments, the runs, the rules and the reset are kept under that id, so one visitor never sees or changes
another's. The recorded runs and the book built from them are read-only and shared.
"""
from __future__ import annotations

import copy
import json
import os
import queue
import re
import secrets
import threading
import time
import uuid
from collections import OrderedDict
from pathlib import Path

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from receipts.agent import run_episode
from receipts.compiler import FIELDS, ai_compile
from receipts.core import Receipts
from receipts.paypal import make_paypal
from receipts.rules import DEFAULT_POLICY
from receipts.scenarios import load
from run_batch import FRONTIER, MODELS

ROOT = Path(__file__).resolve().parent
RESULTS = Path(os.environ.get("RECEIPTS_RESULTS", str(ROOT / "results")))
BIZ, SCENARIOS = load()
BY_ID = {s["id"]: s for s in SCENARIOS}
LIVE_ALLOWED = os.environ.get("RECEIPTS_LIVE", "1") == "1"      # hosted demo can turn live model runs off

# Receipts as an MCP server, mounted at /mcp: a drop-in in front of PayPal's own tools. Its workspace is one
# standing workspace shared by every MCP client, so its holds reach the web phone only where that is wanted:
# on your own machine (the default), not on a public server (RECEIPTS_MCP_ON_PHONE=0, set in the Docker image),
# where they would show on every visitor's phone. The receipts_holds MCP tool lists them either way.
MCP_ON_PHONE = os.environ.get("RECEIPTS_MCP_ON_PHONE", "1") == "1"
MCP_SESSION: dict = {}              # {"r": Receipts} once the MCP server is built
from receipts.mcp_server import build as build_mcp  # noqa: E402
MCP_SERVER, MCP_RECEIPTS = build_mcp(register=lambda r: MCP_SESSION.__setitem__("r", r))


def _warm():
    """Parse the recorded runs once at start-up, so the first visitor to Results or the Ledger does not wait
    (on a small hosted machine the first parse takes several seconds)."""
    try:
        from receipts import measure
        measure.results(RESULTS, "all")
        _episodes()
    except Exception:  # noqa: BLE001
        pass


@asynccontextmanager
async def lifespan(_app):
    threading.Thread(target=_warm, daemon=True).start()
    async with MCP_SERVER.session_manager.run():
        yield


app = FastAPI(title="Receipts", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")
# The rules every visitor starts from. Never changed after start-up: a visitor's own rules are a copy.
DEFAULT_RULES = {"policy": dict(BIZ and {**DEFAULT_POLICY, **json.loads((ROOT / "scenarios" / "scenarios.json").read_text(encoding="utf-8"))["policy"]}),
                 "english": BIZ["owner_rules_english"], "sources": {}, "compiled_by": "defaults"}

# ---- one state per visitor ------------------------------------------------------------------------------
VISITOR_COOKIE = "receipts_visitor"
VISITOR_SCOPE_KEY = "receipts.visitor"
MAX_VISITORS = int(os.environ.get("RECEIPTS_MAX_VISITORS", "300"))            # least recently used is dropped past this
VISITOR_IDLE_S = float(os.environ.get("RECEIPTS_VISITOR_IDLE_HOURS", "3")) * 3600
SESSION_MAX_AGE_S = 3600            # a run and its holds are kept for an hour
MAX_SESSIONS_PER_VISITOR = 40       # oldest run dropped past this
_VISITOR_ID_OK = re.compile(r"^[A-Za-z0-9_-]{24,64}$")


class Visitor:
    """What one visitor has done: their runs (and the holds inside them), their rules, their live-run ledger rows."""
    __slots__ = ("sessions", "rules", "live_ledger", "seen")

    def __init__(self):
        self.sessions: dict[str, dict] = {}      # session id -> {"r": Receipts, "t": created}
        self.rules: dict = copy.deepcopy(DEFAULT_RULES)
        self.live_ledger: list[dict] = []
        self.seen = time.time()


VISITORS: "OrderedDict[str, Visitor]" = OrderedDict()      # least recently seen first
_VISITORS_LOCK = threading.RLock()


class VisitorCookie:
    """Plain ASGI middleware (it never buffers, so the event streams pass straight through): reads the visitor
    id from the cookie, or makes a new random one and sets it on the response. HttpOnly, SameSite=Lax, and
    Secure when the page was served over https (directly, or behind a proxy that says so)."""

    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("path", "").startswith("/mcp"):
            return await self.inner(scope, receive, send)
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        vid = None
        for part in headers.get("cookie", "").split(";"):
            name, _, value = part.strip().partition("=")
            if name == VISITOR_COOKIE and _VISITOR_ID_OK.match(value):
                vid = value
        issued = vid is None
        if issued:
            vid = secrets.token_urlsafe(32)
        scope[VISITOR_SCOPE_KEY] = vid
        if not issued:
            return await self.inner(scope, receive, send)
        https = scope.get("scheme") == "https" or headers.get("x-forwarded-proto", "").split(",")[0].strip().lower() == "https"
        cookie = f"{VISITOR_COOKIE}={vid}; Path=/; Max-Age=604800; HttpOnly; SameSite=Lax" + ("; Secure" if https else "")

        async def send_with_cookie(message):
            if message["type"] == "http.response.start":
                message = {**message, "headers": list(message.get("headers", [])) + [(b"set-cookie", cookie.encode("latin-1"))]}
            await send(message)

        await self.inner(scope, receive, send_with_cookie)


app.add_middleware(VisitorCookie)


def _visitor(request: Request, create: bool = False) -> Visitor | None:
    """This visitor's state. Reading never creates one (a visitor who has done nothing costs no memory);
    acting does. Idle visitors expire, and past MAX_VISITORS the least recently seen is dropped."""
    vid = request.scope.get(VISITOR_SCOPE_KEY)
    now = time.time()
    with _VISITORS_LOCK:
        for k in [k for k, v in VISITORS.items() if now - v.seen > VISITOR_IDLE_S]:
            VISITORS.pop(k, None)
        v = VISITORS.get(vid) if vid else None
        if v is None:
            if not create:
                return None
            v = Visitor()
            if vid:
                VISITORS[vid] = v
                while len(VISITORS) > max(1, MAX_VISITORS):
                    VISITORS.popitem(last=False)
        else:
            VISITORS.move_to_end(vid)
        v.seen = now
        for k in [k for k, s in v.sessions.items() if now - s["t"] > SESSION_MAX_AGE_S]:
            v.sessions.pop(k, None)
        return v


def _rules(request: Request) -> dict:
    v = _visitor(request)
    return v.rules if v else DEFAULT_RULES


@app.get("/", response_class=HTMLResponse)
def index():
    return (ROOT / "static" / "index.html").read_text(encoding="utf-8")


def _resolved_paypal() -> str:
    from receipts.paypal import creds
    m = os.environ.get("PAYPAL_MODE", "auto").lower()
    return ("sandbox" if all(creds()) else "standin") if m == "auto" else m


@app.get("/api/meta")
def meta():
    # "models" stays the twelve open models; the seven frontier models are listed beside them when their recorded runs
    # are on disk. A file check only: this is the hosted demo's health check and must never wait on parsing the runs.
    frontier = FRONTIER if any((RESULTS / "frontier" / n).exists() for n in ("episodes_scored.jsonl", "episodes.jsonl")) else []
    return {"business": BIZ, "models": MODELS, "frontier_models": frontier, "live_allowed": LIVE_ALLOWED,
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
def get_policy(request: Request):
    return {**_rules(request), "fields": {k: {"kind": v[0], "label": v[1]} for k, v in FIELDS.items()}}


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
def set_policy(body: PolicyIn, request: Request):
    """This visitor's rules, for this visitor's runs from now on. Nobody else's change."""
    from receipts.compiler import _validate
    rules = _visitor(request, create=True).rules
    rules.update({"policy": _validate(body.policy), "english": body.english or rules["english"],
                  "sources": body.sources, "compiled_by": body.compiled_by})
    return rules


def _sse(q: queue.Queue):
    while True:
        ev = q.get()
        if ev is None:
            break
        yield f"data: {json.dumps(ev, default=str)}\n\n"


def _register(r: Receipts, q: queue.Queue, sid: str, visitor: Visitor):
    with _VISITORS_LOCK:
        visitor.sessions[sid] = {"r": r, "t": time.time()}
        while len(visitor.sessions) > MAX_SESSIONS_PER_VISITOR:
            visitor.sessions.pop(next(iter(visitor.sessions)))
    q.put({"type": "session", "session": sid, "mode": r.mode, "backend": r.paypal.backend, "note": getattr(r.paypal, "note", None)})


@app.get("/api/run")
def run(request: Request, scenario: str, model: str, mode: str = "enforce"):
    if not LIVE_ALLOWED:
        raise HTTPException(403, "Live model runs are off on this demo; use a recorded run.")
    if scenario not in BY_ID or mode not in ("enforce", "observe"):
        raise HTTPException(400, "bad scenario or mode")
    visitor = _visitor(request, create=True)
    policy = dict(visitor.rules["policy"])          # the rules as they stand when the run starts
    q: queue.Queue = queue.Queue()
    sid = uuid.uuid4().hex[:10]

    def work():
        # no key for this model's provider: say so plainly, instead of a run that "finishes" having done nothing
        # (found 2026-11-10 by running a fresh public clone with no keys, as a judge would)
        from receipts import providers
        prov = providers.provider_for(model)
        if not providers.key_for(prov):
            q.put({"type": "error", "msg": f"A live run needs an AI model key for {prov} ({' or '.join(providers.PROVIDERS[prov]['keys'])}), "
                                          "and this copy has none. Choose \"Recorded real run\" above: it replays real runs "
                                          "through Receipts and PayPal now, with no keys."})
            q.put({"type": "done", "outcome": {"class": "ERROR"}, "error": "no model key"})
            q.put(None)
            return
        try:
            rec = run_episode(BY_ID[scenario], model, mode=mode, on_event=q.put, policy=policy,
                              on_start=lambda r: _register(r, q, sid, visitor))
            visitor.live_ledger.extend(_ledger_from(rec, live=True))
            q.put({"type": "done", "outcome": rec["outcome"], "seconds": rec["seconds"], "error": rec["error"]})
        except Exception as e:  # noqa: BLE001
            q.put({"type": "error", "msg": f"{type(e).__name__}: {e}"[:300]})
            q.put({"type": "done", "outcome": {"class": "ERROR"}})
        q.put(None)

    threading.Thread(target=work, daemon=True).start()
    return StreamingResponse(_sse(q), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _episodes() -> list[dict]:
    """Every recorded run with its line number (the replay index), parsed once and reused until the file changes."""
    from receipts import measure
    p = RESULTS / "episodes_scored.jsonl"
    if not p.exists():
        p = RESULTS / "episodes.jsonl"
    if not p.exists():
        return []
    return measure.cached(("episodes", str(p)), measure._stamp(p), lambda: _parse_episodes(p))


def _parse_episodes(p: Path) -> list[dict]:
    out = []
    for i, line in enumerate(p.read_text(encoding="utf-8").splitlines()):
        try:
            r = json.loads(line)
        except Exception:  # noqa: BLE001
            continue
        r["_line"] = i
        out.append(r)
    return out


# The seven frontier models' runs live in their own folder (results/frontier). They are replayed from the rows the
# Results tab and the book already hold in memory (measure.load_scored: the latest finished run per model, day, arm
# and run number), so no second copy is parsed. Their replay numbers start here, clear of the open models' line numbers.
FRONTIER_LINE0 = 1_000_000


def _frontier_episodes() -> list[dict]:
    from receipts import measure
    return measure._pick(RESULTS / "frontier")


def _recorded_run(line: int) -> dict | None:
    if line >= FRONTIER_LINE0:
        rows = _frontier_episodes()
        return rows[line - FRONTIER_LINE0] if line - FRONTIER_LINE0 < len(rows) else None
    return next((r for r in _episodes() if r["_line"] == line), None)


@app.get("/api/recorded")
def recorded(scenario: str | None = None, model: str | None = None):
    rows = []
    numbered = [(r["_line"], r) for r in _episodes()] + [(FRONTIER_LINE0 + i, r) for i, r in enumerate(_frontier_episodes())]
    for line, r in numbered:
        if r["outcome"].get("class") in ("ERROR", "NO_TOOL_CALLS"):
            continue
        if scenario and r["scenario"] != scenario:
            continue
        if model and r["model"] != model:
            continue
        rows.append({"line": line, "scenario": r["scenario"], "model": r["model"], "mode": r["mode"], "rep": r["rep"],
                     "ts": r.get("ts"), "class": r["outcome"]["class"], "attempts": r["outcome"].get("trap_attempts"),
                     "money_at_risk": r["outcome"].get("money_at_risk"), "report": r["outcome"].get("report"),
                     "said_no_did_it": r["outcome"].get("said_no_did_it")})
    return rows


@app.get("/api/replay")
def replay(request: Request, line: int, speed: float = 1.0, mode: str | None = None):
    """Re-drive a recorded run: the model's words and tool calls are the recorded ones;
    Receipts and PayPal run NOW. Labelled as a replay everywhere it is shown."""
    rec = _recorded_run(line)
    if rec is None or rec["outcome"].get("class") in ("ERROR", "NO_TOOL_CALLS"):
        raise HTTPException(404, "no such recorded run")
    scn = BY_ID[rec["scenario"]]
    visitor = _visitor(request, create=True)
    policy = dict(visitor.rules["policy"])          # this visitor's rules as they stand when the run starts
    q: queue.Queue = queue.Queue()
    sid = uuid.uuid4().hex[:10]
    use_mode = mode or rec["mode"]

    def work():
        try:
            pp = make_paypal(scn.get("paypal", {}), scn["id"])
            r = Receipts(scn, pp, mode=use_mode, policy=policy, on_event=q.put)
            _register(r, q, sid, visitor)
            q.put({"type": "replay", "model": rec["model"], "recorded_at": rec.get("ts"), "recorded_mode": rec["mode"], "mode": use_mode})
            # Recorded against the stand-in; in the sandbox the same orders carry real PayPal ids.
            # Both are keyed by the same names ("A.capture_id"), so recorded ids translate one to one.
            from receipts.paypal import StandIn
            tr = {}
            if pp.backend == "sandbox":
                fake = StandIn(scn.get("paypal", {}), scn["id"]).ids
                tr = {v: pp.ids[k] for k, v in fake.items() if k in pp.ids}

            def T(x):
                if not tr:
                    return x
                if isinstance(x, str):
                    for a, b in tr.items():
                        x = x.replace(a, b)
                    return x
                if isinstance(x, dict):
                    return {k: T(v) for k, v in x.items()}
                if isinstance(x, list):
                    return [T(v) for v in x]
                return x

            last_text = ""
            for e in T(rec["events"]):
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


def _sessions(request: Request) -> dict[str, Receipts]:
    """The runs whose holds this visitor may see and decide: their own, and the MCP workspace's where that is on."""
    v = _visitor(request)
    with _VISITORS_LOCK:
        out = {sid: s["r"] for sid, s in (v.sessions.items() if v else [])}
    if MCP_ON_PHONE and MCP_SESSION.get("r") is not None:
        out["mcp"] = MCP_SESSION["r"]
    return out


@app.get("/api/holds")
def holds(request: Request):
    out = []
    for sid, r in _sessions(request).items():
        for h in list(r.holds):
            out.append({"session": sid, **h, "scenario": r.scenario["title"], "amount": _amt(h)})
    return sorted(out, key=lambda h: h["status"] != "WAITING")


def _amt(h):
    a = h["args"]
    return a.get("amount")


@app.post("/api/reset")
def reset(request: Request):
    """Clear this visitor's runs and holds, nobody else's (their rules and the MCP workspace stay)."""
    v = _visitor(request)
    if v:
        with _VISITORS_LOCK:
            v.sessions.clear()
            v.live_ledger.clear()
    return {"reset": True}


@app.post("/api/approve")
def approve(body: HoldIn, request: Request):
    r = _sessions(request).get(body.session)
    if not r:
        raise HTTPException(404, "session expired")
    return r.approve(body.hold_id)


@app.post("/api/decline")
def decline(body: HoldIn, request: Request):
    r = _sessions(request).get(body.session)
    if not r:
        raise HTTPException(404, "session expired")
    return r.decline(body.hold_id)


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
    return rows


@app.get("/api/ledger")
def ledger(request: Request, limit: int = 6000):
    """Every money move: this visitor's live runs first, then the measured runs of all 19 models, read through the
    same loader as the results (receipts/measure.py), so an errored run never appears and the frontier runs do."""
    from receipts import measure
    v = _visitor(request)
    rows = list(v.live_ledger) if v else []
    for r in measure.load_groups(RESULTS)["all"]:
        rows.extend(_ledger_from(r))
    return rows[:limit]


@app.get("/api/results")
def results(group: str = "all"):
    """The measurement, computed from the scored runs (receipts/measure.py), the same numbers the README states.
    group: all | open | frontier."""
    from receipts import measure
    return measure.results(RESULTS, group)


app.mount("/mcp", MCP_SERVER.streamable_http_app(streamable_http_path="/"))
