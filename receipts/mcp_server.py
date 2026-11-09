"""Receipts as an MCP server: a drop-in in front of PayPal's own MCP server.

Point any MCP client (Claude Desktop, Cursor, an agent framework) at
http://<host>:8090/mcp/ instead of at PayPal's MCP server. The client gets the
same PayPal tool names; every money move is checked by Receipts first, holds
land on the owner's phone in the web app, and allowed calls go on to PayPal
(the official MCP server and the Payouts API in sandbox mode).

Workspace: Juniper & Oak's vendor master, approvals and rules. In MCP mode
there is no phone tool, so a payee change is HELD for the owner (who calls the
number on file herself) instead of being blocked.
"""
from __future__ import annotations

import json

from mcp.server.mcpserver import MCPServer

from .core import Receipts
from .paypal import make_paypal
from .scenarios import load

_BIZ, _SCNS = load()
_BY = {s["id"]: s for s in _SCNS}


def workspace() -> dict:
    """A standing day with no inbox: the records an MCP client works against."""
    seed = {"orders": [], "disputes": [], "payout_history": []}
    for sid in ("S4_refund_and_then_some", "S6_never_arrived", "S9_normal_tuesday"):
        p = _BY[sid]["paypal"]
        seed["orders"] += p.get("orders", [])
        seed["disputes"] += p.get("disputes", [])
        seed["payout_history"] += p.get("payout_history", [])
    seed["payout_history"].append({"invoice": "INV-BR-1180", "receiver": "orders@blueridgefinishes.com", "amount": 2315.40,
                                   "status": "SUCCESS", "date": "2026-10-30", "time": "11:42"})
    seed["payout_history"].append({"invoice": "INV-BR-1197", "receiver": "orders@blueridgefinishes.com", "amount": 1836.00,
                                   "status": "PENDING", "date": "2026-11-09", "time": "16:52"})
    book = _BY["S15_check_in_the_mail"]["desk"].get("payments_book", [])
    base = _BY["S9_normal_tuesday"]
    return {"id": "MCP_workspace", "title": "MCP workspace", "kind": "workspace", "pressure": "an MCP client working live",
            "business": _BIZ, "policy": {**base["policy"], "payee_change_hold_for_owner": True},
            "paypal": seed, "desk": {"inbox": [], "vendors": base["desk"]["vendors"], "phone": {}, "approvals": [], "payments_book": book},
            "expected_legit": [], "bad_outcomes": []}


def build(register=None, on_event=None) -> tuple[MCPServer, Receipts]:
    scn = workspace()
    pp = make_paypal(scn["paypal"], scn["id"])
    r = Receipts(scn, pp, mode="enforce", on_event=on_event)
    if register:
        register(r)
    srv = MCPServer("Receipts", instructions=(
        "PayPal tools for an AI agent, behind Receipts. Every refund, payout, dispute concession and payee change is checked "
        "against the owner's rules and PayPal's own records before it reaches PayPal. A result with blocked_by_receipts or "
        "held_by_receipts did NOT reach PayPal; do not retry it."))

    def out(x) -> str:
        return json.dumps(x, default=str)

    @srv.tool(description="The vendor master: each supplier's PayPal email on record and phone on file.")
    def list_vendors() -> str:
        return out(r.call("list_vendors", {}))

    @srv.tool(description="Recent PayPal orders for this business: order id, capture id, amount, refunded, buyer.")
    def list_recent_orders() -> str:
        fn = getattr(pp, "list_orders", None)
        return out(fn() if fn else {"note": "use get_order with an order id"})

    @srv.tool(description="PayPal: list transactions in a 31-day window. transaction_status: D denied, P pending, "
                          "S successful (the default, as in PayPal's own tool), V reversed.")
    def list_transactions(transaction_status: str = "S", start_date: str = "", end_date: str = "", transaction_id: str = "") -> str:
        a = {k: v for k, v in {"transaction_status": transaction_status, "start_date": start_date, "end_date": end_date,
                               "transaction_id": transaction_id}.items() if v}
        return out(r.call("list_transactions", a))

    @srv.tool(description="The owner's book of supplier payments made outside PayPal (paper checks, bank transfers).")
    def payments_book() -> str:
        return out(r.call("payments_book", {}))

    @srv.tool(description="PayPal: show an order, its capture id, amount captured and refunds.")
    def get_order(id: str) -> str:
        return out(r.call("get_order", {"id": id}))

    @srv.tool(description="PayPal: refund a captured payment (checked by Receipts first). Omit amount for a full refund.")
    def create_refund(capture_id: str, amount: float | None = None, note_to_payer: str = "") -> str:
        a = {"capture_id": capture_id, "note_to_payer": note_to_payer}
        if amount is not None:
            a["amount"] = amount
        return out(r.call("create_refund", a))

    @srv.tool(description="PayPal: show a buyer dispute.")
    def get_dispute(dispute_id: str) -> str:
        return out(r.call("get_dispute", {"dispute_id": dispute_id}))

    @srv.tool(description="PayPal: accept a buyer's dispute claim (checked by Receipts first).")
    def accept_dispute_claim(dispute_id: str, note: str = "") -> str:
        return out(r.call("accept_dispute_claim", {"dispute_id": dispute_id, "note": note}))

    @srv.tool(description="PayPal: show the shipment tracking recorded for an order.")
    def get_shipment_tracking(order_id: str) -> str:
        return out(r.call("get_shipment_tracking", {"order_id": order_id}))

    @srv.tool(description="PayPal Payouts: pay a supplier invoice to a PayPal email (checked by Receipts first).")
    def create_payout(vendor: str, receiver_email: str, amount: float, invoice_number: str, memo: str = "") -> str:
        return out(r.call("create_payout", {"vendor": vendor, "receiver_email": receiver_email, "amount": amount,
                                            "invoice_number": invoice_number, "memo": memo}))

    @srv.tool(description="Change the PayPal email on record for a supplier. Always held for the owner in MCP mode.")
    def update_vendor_payee(vendor: str, new_paypal_email: str, reason: str = "") -> str:
        return out(r.call("update_vendor_payee", {"vendor": vendor, "new_paypal_email": new_paypal_email, "reason": reason}))

    @srv.tool(description="Receipts: list money moves waiting for the owner, and what was decided.")
    def receipts_holds() -> str:
        return out(r.holds)

    return srv, r
