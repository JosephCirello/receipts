"""What the sandbox backend asks PayPal at the moment Receipts decides a supplier payment.

A fake REST layer stands in for PayPal: no network, no sandbox account, no MCP server. These checks were
never run against PayPal's real sandbox; sandbox_check.py carries the step that does that, read-only.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from receipts import paypal  # noqa: E402
from receipts.core import Receipts  # noqa: E402
from receipts.paypal import SANDBOX_BASE, SandboxPayPal  # noqa: E402
from receipts.scenarios import by_id  # noqa: E402

S = by_id()
DAY = "S14_crossed_in_the_mail"
BILL = {"vendor": "Blue Ridge Finishes", "receiver_email": "orders@blueridgefinishes.com", "amount": 1836, "invoice_number": "INV-BR-1197"}
HONEST = {"vendor": "Hollis Freight", "receiver_email": "invoices@hollisfreight.com", "amount": 298, "invoice_number": "INV-HF-0936"}


class FakeSandbox(SandboxPayPal):
    """The sandbox backend with PayPal's REST API replaced by a function. Nothing leaves the machine."""

    def __init__(self, history, rest):
        self.sid, self.seed, self.ids, self.orders, self.seed_log = "T", {}, {}, {}, []
        self.base = SANDBOX_BASE
        self.history = [dict(h) for h in history]
        self.from_paypal = {h["id"] for h in self.history}
        self.rest, self.calls = rest, []

    def _rest(self, method, path, body=None, timeout=60):
        self.calls.append((method, path.split("?")[0], timeout))
        return self.rest(method, path, body)


def payout(status, batch_id="BATCH-1"):
    return {"invoice": "INV-BR-1197", "receiver": "orders@blueridgefinishes.com", "amount": 1836.0, "status": status,
            "date": "2026-11-09", "time": "16:52", "id": batch_id}


def paypal_says(item_status=None, batch_status="SUCCESS", search=None, sent=None):
    """A fake PayPal: one payout whose item (or, with no item yet, batch) status is given, and a transaction list."""
    def rest(method, path, body):
        if method == "GET" and path.startswith("/v1/payments/payouts/"):
            items = [{"transaction_status": item_status}] if item_status else []
            return {"batch_header": {"payout_batch_id": path.rsplit("/", 1)[1], "batch_status": batch_status}, "items": items}
        if method == "GET" and path.startswith("/v1/reporting/transactions"):
            return search if search is not None else {"transaction_details": [], "total_pages": 1}
        if method == "POST" and path == "/v1/payments/payouts":
            if sent is not None:
                sent.append(body)
            return {"batch_header": {"payout_batch_id": "BATCH-NEW", "batch_status": "PENDING"}}
        raise AssertionError(f"unexpected call {method} {path}")
    return rest


def row(invoice_id=None, status="P", value="-298.00", note="", txn="5TY05013RG002845M", custom=None):
    return {"transaction_info": {"transaction_id": txn, "invoice_id": invoice_id, "custom_field": custom, "transaction_status": status,
                                 "transaction_amount": {"currency_code": "USD", "value": value}, "transaction_note": note,
                                 "transaction_initiation_date": "2026-11-09T16:52:10+0000"}}


def decide(pp, call=BILL):
    r = Receipts(S[DAY], pp, mode="enforce")
    res = r.call("create_payout", dict(call))
    return r.verdicts[-1], res


# ---- (a) the current status of every payout Receipts knows, read from PayPal at decision time -------------------

def test_the_status_in_the_verdict_is_the_one_paypal_gives_now_not_the_one_remembered():
    pp = FakeSandbox([payout("SUCCESS")], paypal_says("UNCLAIMED"))        # remembered as paid; PayPal now says still on its way
    v, res = decide(pp)
    f = v["findings"][0]
    assert res["held_by_receipts"] and f["code"] == "PAYMENT_IN_FLIGHT"
    assert "status UNCLAIMED" in f["why"] and f["facts"]["paypal_status"] == "UNCLAIMED" and f["facts"]["status_read"] == "live"
    assert ("GET", "/v1/payments/payouts/BATCH-1", paypal.LOOKUP_TIMEOUT) in pp.calls       # asked PayPal, with the short timeout


def test_a_payout_paypal_now_shows_completed_is_stopped_as_already_paid():
    pp = FakeSandbox([payout("UNCLAIMED")], paypal_says("SUCCESS"))
    v, res = decide(pp)
    assert res["blocked_by_receipts"] and v["findings"][0]["code"] == "ALREADY_PAID_IN_PAYPAL"
    assert v["findings"][0]["facts"]["status_read"] == "live"


def test_a_payout_paypal_now_shows_returned_can_be_sent_again():
    sent = []
    pp = FakeSandbox([payout("UNCLAIMED")], paypal_says("RETURNED", sent=sent))           # unclaimed for 30 days: the money came back
    v, res = decide(pp)
    assert v["decision"] == "ALLOW" and res["payout_batch_id"] == "BATCH-NEW"
    assert len(sent) == 1 and sent[0]["items"][0]["sender_item_id"] == "INV-BR-1197"


def test_a_batch_paypal_is_still_processing_counts_as_a_payment_on_its_way():
    pp = FakeSandbox([payout("SUCCESS")], paypal_says(None, batch_status="PROCESSING"))   # no item yet, only the batch
    v, res = decide(pp)
    assert res["held_by_receipts"] and v["findings"][0]["code"] == "PAYMENT_IN_FLIGHT" and "status PENDING" in v["findings"][0]["why"]


@pytest.mark.parametrize("broken", ["error", "timeout", "nonsense", "unknown status"])
def test_when_paypal_does_not_answer_the_last_known_status_stands_and_nothing_raises(broken):
    def rest(method, path, body):
        if broken == "error":
            return {"error": {"name": "NOT_AUTHORIZED"}, "status": 403}
        if broken == "timeout":
            raise requests.Timeout("PayPal did not answer")
        if broken == "nonsense":
            return {"text": "<html>502 Bad Gateway</html>"}
        return {"batch_header": {"batch_status": "SUCCESS"}, "items": [{"transaction_status": "SOMETHING_NEW"}]}
    pp = FakeSandbox([payout("UNCLAIMED")], rest)
    v, res = decide(pp)
    f = v["findings"][0]
    assert res["held_by_receipts"] and f["code"] == "PAYMENT_IN_FLIGHT" and "status UNCLAIMED" in f["why"]
    assert f["facts"]["status_read"] == "last known"
    assert pp.history[0]["status"] == "UNCLAIMED"


def test_an_id_paypal_never_issued_is_not_looked_up():
    pp = FakeSandbox([payout("PENDING")], paypal_says("SUCCESS"))
    pp.from_paypal.clear()                                                  # e.g. a day seeded from ids on file
    v, res = decide(pp)
    assert res["held_by_receipts"] and pp.calls == [] and "status_read" not in v["findings"][0]["facts"]


# ---- (b) payments made outside Receipts: PayPal's Transaction Search, off unless switched on ---------------------

def test_transaction_search_is_off_by_default(monkeypatch):
    monkeypatch.delenv("RECEIPTS_TRANSACTION_SEARCH", raising=False)
    sent = []
    pp = FakeSandbox([], paypal_says(search={"transaction_details": [row("INV-HF-0936")], "total_pages": 1}, sent=sent))
    v, _ = decide(pp, HONEST)
    assert v["decision"] == "ALLOW" and len(sent) == 1
    assert not any(path == "/v1/reporting/transactions" for _, path, _ in pp.calls)


def test_a_payment_found_only_by_transaction_search_is_held_for_the_owner(monkeypatch):
    monkeypatch.setenv("RECEIPTS_TRANSACTION_SEARCH", "1")
    sent = []
    found = {"transaction_details": [row("INV-HF-0001"), row("INV-HF-0936", status="P")], "total_pages": 1}
    pp = FakeSandbox([], paypal_says(search=found, sent=sent))             # Receipts itself knows no payout for this invoice
    v, res = decide(pp, HONEST)
    f = v["findings"][0]
    assert res["held_by_receipts"] and f["code"] == "PAYMENT_IN_FLIGHT" and sent == []
    assert "5TY05013RG002845M" in f["why"] and "not made through Receipts" in f["why"] and "$298.00" in f["why"]
    assert f["facts"]["source"] == "transaction_search" and f["facts"]["paypal_status"] == "PENDING"
    assert ("GET", "/v1/reporting/transactions", paypal.LOOKUP_TIMEOUT) in pp.calls


def test_a_completed_payment_found_only_by_transaction_search_is_held_not_stopped(monkeypatch):
    monkeypatch.setenv("RECEIPTS_TRANSACTION_SEARCH", "1")
    found = {"transaction_details": [row(None, status="S", note="Invoice INV-HF-0936, paid by hand")], "total_pages": 1}
    v, res = decide(FakeSandbox([], paypal_says(search=found)), HONEST)
    f = v["findings"][0]
    assert v["decision"] == "HOLD" and res["held_by_receipts"] and f["code"] == "ALREADY_PAID_IN_PAYPAL" and f["decision"] == "HOLD"


def test_transaction_search_asks_for_every_status_over_31_days(monkeypatch):
    monkeypatch.setenv("RECEIPTS_TRANSACTION_SEARCH", "1")
    asked = []

    def rest(method, path, body):
        asked.append(path)
        return {"transaction_details": [], "total_pages": 1}
    FakeSandbox([], rest).payout_records("INV-HF-0936")
    from datetime import datetime
    from urllib.parse import parse_qs, urlparse
    q = parse_qs(urlparse(asked[0]).query)
    assert "transaction_status" not in q                                   # no status filter: pending and completed alike
    start, end = (datetime.strptime(q[k][0], "%Y-%m-%dT%H:%M:%SZ") for k in ("start_date", "end_date"))
    assert (end - start).days == 31 and q["fields"] == ["transaction_info"] and q["page_size"] == ["500"]


def test_transaction_search_ignores_other_invoices_money_coming_in_and_lookalike_numbers(monkeypatch):
    monkeypatch.setenv("RECEIPTS_TRANSACTION_SEARCH", "1")
    found = {"transaction_details": [row("INV-HF-0937"),                                    # another invoice
                                     row("INV-HF-0936", value="298.00"),                    # money coming in, not a payment
                                     row(None, note="re INV-HF-0936R, the re-sent bill"),   # a different number that contains this one
                                     row("INV-HF-0936", status="X")],                       # a status this code does not know
             "total_pages": 1}
    sent = []
    v, _ = decide(FakeSandbox([], paypal_says(search=found, sent=sent)), HONEST)
    assert v["decision"] == "ALLOW" and len(sent) == 1


def test_a_payout_receipts_already_knows_is_not_counted_twice(monkeypatch):
    monkeypatch.setenv("RECEIPTS_TRANSACTION_SEARCH", "1")
    found = {"transaction_details": [row("INV-BR-1197", status="P", value="-1836.00")], "total_pages": 1}
    pp = FakeSandbox([payout("PENDING")], paypal_says("UNCLAIMED", search=found))
    recs = pp.payout_records("INV-BR-1197")
    assert len(recs) == 1 and recs[0]["status"] == "UNCLAIMED" and "source" not in recs[0]


@pytest.mark.parametrize("broken", ["no permission", "timeout", "empty", "malformed"])
def test_when_transaction_search_fails_the_decision_is_what_it_was_without_it(monkeypatch, broken):
    monkeypatch.setenv("RECEIPTS_TRANSACTION_SEARCH", "1")

    def rest(method, path, body):
        if path.startswith("/v1/reporting/transactions"):
            if broken == "no permission":
                return {"error": {"name": "NOT_AUTHORIZED", "message": "Authorization failed due to insufficient permissions."}, "status": 403}
            if broken == "timeout":
                raise requests.Timeout("PayPal did not answer")
            if broken == "empty":
                return {"transaction_details": [], "total_pages": 1}
            return {"transaction_details": [{"transaction_info": {"invoice_id": "INV-HF-0936", "transaction_status": "P",
                                                                  "transaction_amount": {"value": "not a number"}}}]}
        if path == "/v1/payments/payouts":
            return {"batch_header": {"payout_batch_id": "BATCH-NEW", "batch_status": "PENDING"}}
        return {"batch_header": {"batch_status": "SUCCESS"}, "items": [{"transaction_status": "UNCLAIMED"}]}
    v, res = decide(FakeSandbox([], rest), HONEST)                          # an honest bill still goes straight through
    assert v["decision"] == "ALLOW" and res["payout_batch_id"] == "BATCH-NEW"
    v2, res2 = decide(FakeSandbox([payout("PENDING")], rest))               # and Maya's duplicate is still held, from the payout Receipts knows
    assert res2["held_by_receipts"] and v2["findings"][0]["code"] == "PAYMENT_IN_FLIGHT" and "status UNCLAIMED" in v2["findings"][0]["why"]


def test_the_stand_in_and_the_recorded_runs_are_untouched():
    from receipts.paypal import StandIn
    pp = StandIn(S[DAY]["paypal"], DAY)
    v, res = decide(pp)
    f = v["findings"][0]
    assert res["held_by_receipts"] and set(f["facts"]) == {"invoice", "paypal_status", "sent"}
    assert f["why"] == ("PayPal shows a payment for invoice INV-BR-1197 already on its way: $1,836.00 to orders@blueridgefinishes.com, "
                        "sent Monday 9 November at 4:52 PM, status PENDING. The reminder crossed it. Pay again only if you know that payment failed.")
