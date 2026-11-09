"""Talk to Receipts the way any MCP client would (Claude Desktop, Cursor, an agent framework).

  python examples/mcp_client_demo.py [url] [--json]     # server running on http://127.0.0.1:8090

It lists the tools, then tries four money moves through Receipts:
  1. a payout to a PayPal email that is not the supplier's      -> blocked
  2. a payout of an invoice PayPal already paid                 -> blocked
  3. a refund larger than the customer paid                     -> blocked
  4. a small, honest refund                                     -> goes to PayPal
"""
import asyncio
import json
import sys

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

ARGS = [a for a in sys.argv[1:] if not a.startswith("--")]
URL = ARGS[0] if ARGS else "http://127.0.0.1:8090/mcp/"
RAW = "--json" in sys.argv


def show(n, what, res):
    if RAW:
        print(f"{n}. {what} -> {json.dumps(res)}")
        return
    if res.get("blocked_by_receipts") or res.get("held_by_receipts"):
        verdict = "BLOCKED" if res.get("blocked_by_receipts") else "HELD FOR OWNER"
        print(f"{n}. {what}\n   Receipts: {verdict}. {res['why'][0]}\n")
    else:
        pid = res.get("payout_batch_id") or res.get("id")
        print(f"{n}. {what}\n   Receipts: cleared. PayPal ({res.get('backend', '?')}): {pid} {res.get('batch_status') or res.get('status')}\n")


async def main():
    async with streamable_http_client(URL) as (r, w, *_):
        async with ClientSession(r, w) as s:
            await s.initialize()
            tools = [t.name for t in (await s.list_tools()).tools]
            print(f"Connected to Receipts over MCP at {URL}\n{len(tools)} tools: {', '.join(tools)}\n")

            async def call(name, args):
                res = await s.call_tool(name, args)
                text = "".join(getattr(c, "text", "") for c in res.content)
                try:
                    return json.loads(text)
                except Exception:
                    return {"text": text}

            orders = {o["description"]: o for o in await call("list_recent_orders", {})}
            show(1, "create_payout  $4,860.00 to payments@ashwoodtimber-pay.com (invoice INV-AT-5531)",
                 await call("create_payout", {"vendor": "Ashwood Timber Co.", "receiver_email": "payments@ashwoodtimber-pay.com",
                                              "amount": 4860, "invoice_number": "INV-AT-5531"}))
            show(2, "create_payout  $2,315.40 to orders@blueridgefinishes.com (invoice INV-BR-1180)",
                 await call("create_payout", {"vendor": "Blue Ridge Finishes", "receiver_email": "orders@blueridgefinishes.com",
                                              "amount": 2315.40, "invoice_number": "INV-BR-1180"}))
            t = orders["Walnut side table"]
            show(3, f"create_refund  $480.00 on a ${t['amount']:.2f} order",
                 await call("create_refund", {"capture_id": t["capture_id"], "amount": 480, "note_to_payer": "Sorry about the scratch"}))
            p = orders["Set of 8 brass drawer pulls"]
            show(4, f"create_refund  $64.00 on a ${p['amount']:.2f} order (wrong finish sent)",
                 await call("create_refund", {"capture_id": p["capture_id"], "amount": 64, "note_to_payer": "Wrong finish, sorry"}))


asyncio.run(main())
