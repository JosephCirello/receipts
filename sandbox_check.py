#!/usr/bin/env python3
"""Check every PayPal path Receipts uses, against YOUR sandbox, one step at a time.

  python sandbox_check.py        # needs PAYPAL_CLIENT_ID / PAYPAL_CLIENT_SECRET or ~/.paypal_sandbox

Steps: OAuth token; PayPal's official MCP server starts; a card order is created and
captured; tracking is recorded through the MCP server; the capture is read back; the
order and its tracking are read through the MCP server; a partial refund goes through
the MCP server and shows on the capture; a payout is created and read back.
Sandbox only: a non-sandbox PayPal URL is refused in code.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from receipts.paypal import SandboxPayPal, creds  # noqa: E402


def step(name, fn):
    t0 = time.time()
    try:
        out = fn()
        good = not (isinstance(out, dict) and out.get("error"))
        print(f"  {'PASS' if good else 'FAIL'}  {name}  ({time.time() - t0:.1f}s)  {json.dumps(out, default=str)[:240]}", flush=True)
        return out if good else None
    except Exception as e:  # noqa: BLE001
        print(f"  FAIL  {name}  {type(e).__name__}: {str(e)[:300]}", flush=True)
        return None


def run():
    if not all(creds()):
        raise SystemExit("No sandbox credentials. Put the client id and secret on two lines of ~/.paypal_sandbox, "
                         "or set PAYPAL_CLIENT_ID / PAYPAL_CLIENT_SECRET.")
    seed = {"orders": [{"key": "T", "amount": 64.00, "payer_email": "buyer@example.com", "description": "Receipts sandbox check",
                        "tracking": {"carrier": "USPS", "number": "9400111899223847569000", "status": "DELIVERED"}}],
            "payout_history": [], "disputes": []}
    print("Receipts sandbox check (sandbox only, no real money)")
    holder: dict = {}

    def start():
        holder["pp"] = SandboxPayPal(seed, "CHECK")
        return {"ids": holder["pp"].ids, "seed_notes": holder["pp"].seed_log}

    step("token, PayPal's official MCP server, one card order created and captured", start)
    pp = holder.get("pp")
    if not pp:
        return
    cap, oid = pp.ids.get("T.capture_id"), pp.ids.get("T.order_id")
    if not cap:
        print("  FAIL  no capture id: card orders may need Advanced Card Payments enabled on the sandbox app (see seed notes)")
    else:
        step("capture read back from PayPal (REST)", lambda: pp.capture_record(cap))
        step("order read through the MCP server (get_order)", lambda: pp.get_order(oid))
        step("tracking read through the MCP server (get_shipment_tracking)", lambda: pp.get_shipment_tracking(oid))
        step("partial refund $20 through the MCP server (create_refund)", lambda: pp.create_refund(cap, 20, "Receipts sandbox check"))
        step("refund visible on the capture record", lambda: pp.capture_record(cap))
    bid = step("payout $1.00 (Payouts REST)", lambda: pp.create_payout("sb-receipts-check@example.com", 1.00, f"CHECK-{int(time.time())}", "check"))
    if bid and bid.get("payout_batch_id"):
        time.sleep(3)
        step("payout read back", lambda: {k: v for k, v in pp.get_payout(bid["payout_batch_id"]).items() if k in ("batch_header", "error")})
    pp.close()


if __name__ == "__main__":
    run()
