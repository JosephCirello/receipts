"""Talk to Receipts the way any MCP client would (Claude Desktop, Cursor, an agent framework).

  python examples/mcp_client_demo.py            # server running on http://127.0.0.1:8090

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

URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8090/mcp/"


async def main():
    async with streamable_http_client(URL) as (r, w, *_):
        async with ClientSession(r, w) as s:
            await s.initialize()
            print("tools:", ", ".join(t.name for t in (await s.list_tools()).tools))

            async def call(name, args):
                res = await s.call_tool(name, args)
                text = "".join(getattr(c, "text", "") for c in res.content)
                try:
                    return json.loads(text)
                except Exception:
                    return {"text": text}

            orders = {o["description"]: o for o in await call("list_recent_orders", {})}

            r1 = await call("create_payout", {"vendor": "Ashwood Timber Co.", "receiver_email": "payments@ashwoodtimber-pay.com",
                                              "amount": 4860, "invoice_number": "INV-AT-5531"})
            print("\n1. payout to a new PayPal email ->", json.dumps(r1)[:320])

            r2 = await call("create_payout", {"vendor": "Blue Ridge Finishes", "receiver_email": "orders@blueridgefinishes.com",
                                              "amount": 2315.40, "invoice_number": "INV-BR-1180"})
            print("\n2. invoice PayPal already paid ->", json.dumps(r2)[:320])

            table = orders["Walnut side table"]
            r3 = await call("create_refund", {"capture_id": table["capture_id"], "amount": 480, "note_to_payer": "Sorry about the scratch"})
            print(f"\n3. refund $480 on a ${table['amount']:.2f} order ->", json.dumps(r3)[:320])

            pulls = orders["Set of 8 brass drawer pulls"]
            r4 = await call("create_refund", {"capture_id": pulls["capture_id"], "amount": 64, "note_to_payer": "Wrong finish, sorry"})
            print("\n4. honest $64 refund ->", json.dumps(r4)[:320])


asyncio.run(main())
