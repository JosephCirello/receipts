"""PayPal for Receipts: the real sandbox, and a stand-in with the same shapes.

Receipts decides from PayPal's OWN records, not from the email in front of the
agent: what was actually captured on an order, what was already refunded,
whether tracking shows the parcel delivered, which invoice numbers PayPal has
already paid out. And when it allows a money move, the move happens in PayPal.

  SandboxPayPal  The agent's PayPal tools go through PayPal's OFFICIAL MCP
                 server (@paypal/mcp, run locally in sandbox mode): get_order,
                 create_refund, get_dispute, accept_dispute_claim,
                 get_shipment_tracking. Vendor payments use the Payouts REST API
                 (the MCP server has no payouts tool). Needs a sandbox app's
                 client id and secret. No real money, ever: a non-sandbox base
                 URL is refused.
  StandIn        In-memory, same tool names and the documented response
                 shapes, seeded from the scenario. Lets anyone run Receipts with
                 no PayPal account. Every record it writes says backend="standin".

PAYPAL_MODE = sandbox | standin | auto (auto: sandbox when credentials exist).
"""
from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import os
import shutil
import threading
import time
import uuid
from pathlib import Path

import requests

SANDBOX_BASE = "https://api-m.sandbox.paypal.com"
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def creds() -> tuple[str | None, str | None]:
    cid, sec = os.environ.get("PAYPAL_CLIENT_ID"), os.environ.get("PAYPAL_CLIENT_SECRET")
    if cid and sec:
        return cid, sec
    p = Path(os.environ.get("PAYPAL_KEYFILE", str(Path.home() / ".paypal_sandbox")))
    if p.exists():
        lines = [l.strip() for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
        if len(lines) >= 2:
            return lines[0], lines[1]
    return None, None


def _money(x) -> float:
    return round(float(str(x).replace("$", "").replace(",", "")), 2)


def _fake_id(seed: str, n: int = 17) -> str:
    h = hashlib.sha256(seed.encode()).hexdigest().upper()
    alphabet = "0123456789ABCDEFGHJKLMNPRSTUVWXY"
    return "".join(alphabet[int(h[i:i + 2], 16) % len(alphabet)] for i in range(0, n * 2, 2))


# ============================================================================
# The stand-in
# ============================================================================
class StandIn:
    backend = "standin"

    def __init__(self, seed: dict, scenario_id: str = "x"):
        self.sid = scenario_id
        self.orders: dict[str, dict] = {}
        self.captures: dict[str, str] = {}      # capture_id -> order_id
        self.disputes: dict[str, dict] = {}
        self.payouts: dict[str, dict] = {}
        self.paid: set[str] = set()
        self.ids: dict[str, str] = {}           # symbolic name -> real-looking id
        for o in seed.get("orders", []):
            oid = _fake_id(f"{scenario_id}:{o['key']}:order")
            cid = _fake_id(f"{scenario_id}:{o['key']}:capture")
            self.ids[f"{o['key']}.order_id"] = oid
            self.ids[f"{o['key']}.capture_id"] = cid
            self.orders[oid] = {"key": o["key"], "id": oid, "capture_id": cid, "amount": _money(o["amount"]),
                                "refunded": _money(o.get("already_refunded", 0)), "payer": o.get("payer_email", ""),
                                "description": o.get("description", ""), "created": o.get("date", "2026-11-02"),
                                "tracking": copy.deepcopy(o.get("tracking"))}
            self.captures[cid] = oid
        for d in seed.get("disputes", []):
            did = "PP-D-" + str(int(hashlib.sha256(f"{scenario_id}:{d['key']}".encode()).hexdigest(), 16) % 90000 + 10000)
            self.ids[f"{d['key']}.dispute_id"] = did
            oid = self.ids.get(f"{d['order']}.order_id")
            self.disputes[did] = {"id": did, "order_id": oid, "capture_id": self.orders[oid]["capture_id"] if oid else None,
                                  "amount": _money(d["amount"]), "reason": d.get("reason", "MERCHANDISE_OR_SERVICE_NOT_RECEIVED"),
                                  "status": "WAITING_FOR_SELLER_RESPONSE", "buyer_message": d.get("buyer_message", "")}
        for p in seed.get("payout_history", []):
            self.paid.add(str(p["invoice"]).upper())

    # ---- records Receipts reads ------------------------------------------------
    def capture_record(self, capture_id: str) -> dict | None:
        oid = self.captures.get(str(capture_id).strip())
        if not oid:
            return None
        o = self.orders[oid]
        return {"capture_id": o["capture_id"], "order_id": oid, "captured": o["amount"], "refunded": o["refunded"],
                "payer": o["payer"]}

    def dispute_record(self, dispute_id: str) -> dict | None:
        d = self.disputes.get(str(dispute_id).strip())
        if not d:
            return None
        o = self.orders.get(d["order_id"]) or {}
        return {**d, "tracking_status": (o.get("tracking") or {}).get("status")}

    def paid_invoices(self) -> set[str]:
        return set(self.paid)

    def list_orders(self) -> list[dict]:
        return [{"order_id": o["id"], "capture_id": o["capture_id"], "amount": o["amount"], "refunded": o["refunded"],
                 "payer": o["payer"], "description": o["description"]} for o in self.orders.values()]

    # ---- the agent's PayPal tools (official MCP tool names) ----------------------
    def get_order(self, id: str, **_):
        o = self.orders.get(str(id).strip())
        if not o:
            return {"error": "RESOURCE_NOT_FOUND", "message": f"order {id} not found"}
        refunds = [{"amount": {"currency_code": "USD", "value": f"{o['refunded']:.2f}"}, "status": "COMPLETED"}] if o["refunded"] else []
        return {"id": o["id"], "status": "COMPLETED", "create_time": o["created"],
                "payer": {"email_address": o["payer"]},
                "purchase_units": [{"description": o["description"],
                                    "amount": {"currency_code": "USD", "value": f"{o['amount']:.2f}"},
                                    "payments": {"captures": [{"id": o["capture_id"], "status": "PARTIALLY_REFUNDED" if o["refunded"] else "COMPLETED",
                                                               "amount": {"currency_code": "USD", "value": f"{o['amount']:.2f}"}}],
                                                 "refunds": refunds}}]}

    def create_refund(self, capture_id: str, amount=None, note_to_payer: str = "", **_):
        oid = self.captures.get(str(capture_id).strip())
        if not oid:
            return {"error": "RESOURCE_NOT_FOUND", "message": f"capture {capture_id} not found"}
        o = self.orders[oid]
        amt = _money(amount) if amount not in (None, "") else round(o["amount"] - o["refunded"], 2)
        if amt > round(o["amount"] - o["refunded"], 2) + 0.004:
            return {"error": "UNPROCESSABLE_ENTITY", "details": [{"issue": "REFUND_AMOUNT_EXCEEDED"}]}
        o["refunded"] = round(o["refunded"] + amt, 2)
        self._seq = getattr(self, "_seq", 0) + 1
        rid = _fake_id(f"{self.sid}:{capture_id}:refund:{self._seq}")
        return {"id": rid, "status": "COMPLETED", "amount": {"currency_code": "USD", "value": f"{amt:.2f}"}, "backend": self.backend}

    def get_dispute(self, dispute_id: str, **_):
        d = self.disputes.get(str(dispute_id).strip())
        if not d:
            return {"error": "RESOURCE_NOT_FOUND"}
        return {"dispute_id": d["id"], "reason": d["reason"], "status": d["status"],
                "dispute_amount": {"currency_code": "USD", "value": f"{d['amount']:.2f}"},
                "disputed_transactions": [{"seller_transaction_id": d["capture_id"]}],
                "messages": [{"posted_by": "BUYER", "content": d["buyer_message"]}] if d["buyer_message"] else []}

    def accept_dispute_claim(self, dispute_id: str, note: str = "", **_):
        d = self.disputes.get(str(dispute_id).strip())
        if not d:
            return {"error": "RESOURCE_NOT_FOUND"}
        d["status"] = "RESOLVED"
        o = self.orders.get(d["order_id"])
        if o:
            o["refunded"] = round(o["refunded"] + d["amount"], 2)
        return {"dispute_id": d["id"], "status": "RESOLVED", "outcome": "ACCEPTED_BY_SELLER", "backend": self.backend}

    def get_shipment_tracking(self, order_id: str, transaction_id: str = "", **_):
        o = self.orders.get(str(order_id).strip())
        if not o:
            return {"error": "RESOURCE_NOT_FOUND"}
        t = o.get("tracking")
        if not t:
            return {"trackers": []}
        return {"trackers": [{"transaction_id": o["capture_id"], "tracking_number": t.get("number"),
                              "carrier": t.get("carrier"), "status": t.get("status")}]}

    # ---- payouts (REST in the sandbox backend) -------------------------------------
    def create_payout(self, receiver: str, amount, invoice_number: str, note: str = "", currency: str = "USD", **_):
        self._seq = getattr(self, "_seq", 0) + 1
        bid = "SI" + _fake_id(f"{self.sid}:{invoice_number}:{receiver}:payout:{self._seq}", 11)
        self.payouts[bid] = {"receiver": receiver, "amount": _money(amount), "invoice": str(invoice_number).upper()}
        self.paid.add(str(invoice_number).upper())
        return {"payout_batch_id": bid, "batch_status": "SUCCESS", "backend": self.backend}

    def get_payout(self, payout_batch_id: str, **_):
        p = self.payouts.get(payout_batch_id)
        if not p:
            return {"error": "RESOURCE_NOT_FOUND"}
        return {"batch_header": {"payout_batch_id": payout_batch_id, "batch_status": "SUCCESS"},
                "items": [{"transaction_status": "SUCCESS", "payout_item": {"receiver": p["receiver"], "sender_item_id": p["invoice"],
                                                                             "amount": {"currency": "USD", "value": f"{p['amount']:.2f}"}}}]}

    def close(self):
        pass


# ============================================================================
# The real sandbox
# ============================================================================
class _MCPBridge:
    """Runs PayPal's official MCP server (node @paypal/mcp) and calls its tools
    synchronously from a background event loop."""

    def __init__(self, access_token: str):
        from mcp import ClientSession, StdioServerParameters  # local import: optional dependency
        from mcp.client.stdio import stdio_client
        self._ClientSession, self._stdio_client = ClientSession, stdio_client
        entry = ROOT / "node_modules" / "@paypal" / "mcp" / "dist" / "index.js"
        if entry.exists():
            cmd, args = "node", [str(entry), "--tools=all"]
        else:
            cmd, args = (shutil.which("npx") or "npx"), ["-y", "@paypal/mcp", "--tools=all"]
        self.params = StdioServerParameters(command=cmd, args=args, env={**os.environ, "PAYPAL_ACCESS_TOKEN": access_token,
                                                                        "PAYPAL_ENVIRONMENT": "SANDBOX"})
        self.loop = asyncio.new_event_loop()
        self.ready = threading.Event()
        self.q: asyncio.Queue | None = None
        self.err: Exception | None = None
        threading.Thread(target=self._run, daemon=True).start()
        if not self.ready.wait(60) or self.err:
            raise RuntimeError(f"PayPal MCP server did not start: {self.err}")

    def _run(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self._main())

    async def _main(self):
        try:
            async with self._stdio_client(self.params) as (r, w):
                async with self._ClientSession(r, w) as s:
                    await s.initialize()
                    self.q = asyncio.Queue()
                    self.ready.set()
                    while True:
                        item = await self.q.get()
                        if item is None:
                            return
                        name, args, fut = item
                        try:
                            res = await s.call_tool(name, args)
                            text = "".join(getattr(c, "text", "") for c in (res.content or []))
                            try:
                                out = json.loads(text)
                            except Exception:  # noqa: BLE001
                                out = {"text": text}
                            if getattr(res, "is_error", False) or getattr(res, "isError", False):
                                out = {"error": out}
                            fut.set_result(out)
                        except Exception as e:  # noqa: BLE001
                            fut.set_result({"error": f"{type(e).__name__}: {e}"})
        except Exception as e:  # noqa: BLE001
            self.err = e
            self.ready.set()

    def call(self, name: str, args: dict, timeout: float = 90) -> dict:
        done = threading.Event()
        box: dict = {}

        def put():
            f = self.loop.create_future()
            f.add_done_callback(lambda ff: (box.__setitem__("r", ff.result()), done.set()))
            self.q.put_nowait((name, args, f))

        self.loop.call_soon_threadsafe(put)
        if not done.wait(timeout):
            return {"error": f"timeout calling {name}"}
        return box["r"]

    def close(self):
        if self.q is not None:
            self.loop.call_soon_threadsafe(self.q.put_nowait, None)


class SandboxPayPal:
    backend = "sandbox"
    _tok: tuple[str, float] | None = None
    _lock = threading.Lock()

    def __init__(self, seed: dict, scenario_id: str = "x", seeded_ids: dict | None = None):
        self.cid, self.secret = creds()
        if not (self.cid and self.secret):
            raise RuntimeError("no sandbox credentials: set PAYPAL_CLIENT_ID/PAYPAL_CLIENT_SECRET or ~/.paypal_sandbox")
        self.base = os.environ.get("PAYPAL_BASE", SANDBOX_BASE)
        if "sandbox" not in self.base:
            raise RuntimeError("refusing a non-sandbox PayPal URL")
        self.sid = scenario_id
        self.seed = seed
        self.ids = dict(seeded_ids or {})
        self.paid: set[str] = {str(p["invoice"]).upper() for p in seed.get("payout_history", [])}
        self.mcp = _MCPBridge(self.token())

    # ---- auth and REST -------------------------------------------------------------
    def token(self) -> str:
        with SandboxPayPal._lock:
            t = SandboxPayPal._tok
            if t and t[1] > time.time() + 120:
                return t[0]
            r = requests.post(f"{self.base}/v1/oauth2/token", auth=(self.cid, self.secret),
                              data={"grant_type": "client_credentials"}, headers={"Accept": "application/json"}, timeout=30)
            r.raise_for_status()
            j = r.json()
            SandboxPayPal._tok = (j["access_token"], time.time() + int(j.get("expires_in", 3000)))
            return j["access_token"]

    def _rest(self, method: str, path: str, body: dict | None = None) -> dict:
        r = requests.request(method, f"{self.base}{path}", json=body, timeout=60,
                             headers={"Authorization": f"Bearer {self.token()}", "Content-Type": "application/json",
                                      "PayPal-Request-Id": uuid.uuid4().hex, "Prefer": "return=representation"})
        try:
            j = r.json()
        except Exception:  # noqa: BLE001
            j = {"text": r.text[:500]}
        if r.status_code >= 400:
            return {"error": j, "status": r.status_code}
        return j

    # ---- records Receipts reads (from PayPal itself) ----------------------------------
    def capture_record(self, capture_id: str) -> dict | None:
        j = self._rest("GET", f"/v2/payments/captures/{capture_id}")
        if "error" in j:
            return None
        captured = _money(j["amount"]["value"])
        oid = (j.get("supplementary_data") or {}).get("related_ids", {}).get("order_id")
        refunded = 0.0
        if oid:
            o = self._rest("GET", f"/v2/checkout/orders/{oid}")
            for pu in o.get("purchase_units", []):
                for rf in (pu.get("payments") or {}).get("refunds", []) or []:
                    if rf.get("status") in ("COMPLETED", "PENDING"):
                        refunded += _money(rf["amount"]["value"])
        return {"capture_id": capture_id, "order_id": oid, "captured": captured, "refunded": round(refunded, 2)}

    def dispute_record(self, dispute_id: str) -> dict | None:
        # Disputes cannot be created by API in the sandbox; see README. Scenario disputes run on the stand-in.
        return None

    def paid_invoices(self) -> set[str]:
        return set(self.paid)

    # ---- the agent's PayPal tools: through the official MCP server --------------------
    def get_order(self, id: str, **_):
        return self.mcp.call("get_order", {"id": id})

    def create_refund(self, capture_id: str, amount=None, note_to_payer: str = "", **_):
        args = {"capture_id": capture_id, "note_to_payer": note_to_payer or "Refund"}
        if amount not in (None, ""):
            args["amount"] = {"value": f"{_money(amount):.2f}", "currency_code": "USD"}
        return self.mcp.call("create_refund", args)

    def get_dispute(self, dispute_id: str, **_):
        return self.mcp.call("get_dispute", {"dispute_id": dispute_id})

    def accept_dispute_claim(self, dispute_id: str, note: str = "", **_):
        return self.mcp.call("accept_dispute_claim", {"dispute_id": dispute_id, "note": note or "Accepted"})

    def get_shipment_tracking(self, order_id: str, transaction_id: str = "", **_):
        return self.mcp.call("get_shipment_tracking", {"order_id": order_id, **({"transaction_id": transaction_id} if transaction_id else {})})

    # ---- payouts: REST -----------------------------------------------------------------
    def create_payout(self, receiver: str, amount, invoice_number: str, note: str = "", currency: str = "USD", **_):
        body = {"sender_batch_header": {"sender_batch_id": f"receipts-{uuid.uuid4().hex[:20]}",
                                        "email_subject": "You have a payment from Juniper & Oak",
                                        "email_message": "Released by an AI agent after Receipts checked it."},
                "items": [{"recipient_type": "EMAIL", "receiver": receiver, "sender_item_id": str(invoice_number)[:63],
                           "note": (note or f"Invoice {invoice_number}")[:4000],
                           "amount": {"value": f"{_money(amount):.2f}", "currency": currency or "USD"}}]}
        j = self._rest("POST", "/v1/payments/payouts", body)
        if "error" in j:
            return j
        self.paid.add(str(invoice_number).upper())
        return {"payout_batch_id": j["batch_header"]["payout_batch_id"], "batch_status": j["batch_header"].get("batch_status"),
                "backend": self.backend}

    def get_payout(self, payout_batch_id: str, **_):
        return self._rest("GET", f"/v1/payments/payouts/{payout_batch_id}")

    def close(self):
        self.mcp.close()


def make_paypal(seed: dict, scenario_id: str, mode: str | None = None, seeded_ids: dict | None = None):
    mode = (mode or os.environ.get("PAYPAL_MODE", "auto")).lower()
    if mode == "auto":
        mode = "sandbox" if all(creds()) else "standin"
    if mode == "sandbox":
        return SandboxPayPal(seed, scenario_id, seeded_ids)
    return StandIn(seed, scenario_id)
