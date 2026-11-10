"""The web app keeps one state per visitor: held payments, rules and reset never cross between two browsers.

FastAPI's TestClient, the stand-in PayPal and the recorded runs: no model, no network.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

DAY, MODEL = "S14_crossed_in_the_mail", "glm-5.3"      # Maya's Tuesday, the day the demo opens on


@pytest.fixture(scope="module")
def web():
    """The app on the stand-in, whatever PayPal keys this machine holds (set before the app is first imported)."""
    before = os.environ.get("PAYPAL_MODE")
    os.environ["PAYPAL_MODE"] = "standin"
    import app as web_app
    yield web_app
    if before is None:
        os.environ.pop("PAYPAL_MODE", None)
    else:
        os.environ["PAYPAL_MODE"] = before


@pytest.fixture()
def clients(web):
    """Two separate browsers: each TestClient keeps its own cookies. No lifespan (the MCP session manager is not needed)."""
    from fastapi.testclient import TestClient
    web.VISITORS.clear()
    return TestClient(web.app), TestClient(web.app)


def run_day(client, mode="enforce") -> str:
    """Replay the recorded run the page itself would pick for this day and model; returns the whole event stream."""
    rows = client.get("/api/recorded", params={"scenario": DAY, "model": MODEL}).json()
    pick = sorted((r for r in rows if r["mode"] == mode), key=lambda r: -(r["attempts"] or 0))[0]
    assert pick["attempts"] >= 1
    res = client.get("/api/replay", params={"line": pick["line"], "speed": 100})
    assert res.status_code == 200 and '"type": "done"' in res.text
    return res.text


def waiting(client) -> list[dict]:
    return [h for h in client.get("/api/holds").json() if h["status"] == "WAITING"]


def test_first_request_sets_an_opaque_httponly_cookie_and_keeps_it(clients, web):
    a, _ = clients
    first = a.get("/api/meta")
    cookie = first.headers["set-cookie"]
    assert cookie.startswith(web.VISITOR_COOKIE + "=") and "HttpOnly" in cookie and "SameSite=Lax" in cookie and "Path=/" in cookie
    assert "Secure" not in cookie                                   # plain http on a laptop: a Secure cookie would never come back
    assert len(a.cookies[web.VISITOR_COOKIE]) >= 32
    assert "set-cookie" not in a.get("/api/meta").headers           # the same visitor is not issued a second id
    assert not web.VISITORS                                         # looking costs no memory: no state until a visitor acts


def test_cookie_is_secure_when_the_page_is_served_over_https(web):
    from fastapi.testclient import TestClient
    direct = TestClient(web.app, base_url="https://testserver").get("/api/meta").headers["set-cookie"]
    proxied = TestClient(web.app).get("/api/meta", headers={"X-Forwarded-Proto": "https"}).headers["set-cookie"]
    assert "Secure" in direct and "Secure" in proxied


def test_a_malformed_cookie_is_replaced_not_trusted(web):
    from fastapi.testclient import TestClient
    c = TestClient(web.app)
    res = c.get("/api/meta", headers={"Cookie": f"{web.VISITOR_COOKIE}=short"})
    assert res.headers["set-cookie"].startswith(web.VISITOR_COOKIE + "=")


def test_one_visitors_held_payment_is_not_on_anothers_phone(clients):
    a, b = clients
    stream = run_day(a)
    assert "PAYMENT_IN_FLIGHT" in stream
    mine = waiting(a)
    assert len(mine) == 1 and mine[0]["args"]["invoice_number"] == "INV-BR-1197" and mine[0]["amount"] == 1836
    assert b.get("/api/holds").json() == []


def test_a_visitor_cannot_decide_anothers_held_payment(clients):
    a, b = clients
    run_day(a)
    h = waiting(a)[0]
    body = {"session": h["session"], "hold_id": h["id"]}
    assert b.post("/api/approve", json=body).status_code == 404
    assert b.post("/api/decline", json=body).status_code == 404
    assert waiting(a) == [h]                                        # still waiting for its owner
    assert a.post("/api/decline", json=body).json() == {"declined": h["id"]}
    assert waiting(a) == [] and a.get("/api/holds").json()[0]["status"] == "DECLINED"


def test_approving_your_own_held_payment_sends_it_to_paypal(clients):
    a, _ = clients
    run_day(a)
    h = waiting(a)[0]
    res = a.post("/api/approve", json={"session": h["session"], "hold_id": h["id"]}).json()
    assert res["batch_status"] == "SUCCESS" and res["backend"] == "standin"
    assert a.get("/api/holds").json()[0]["status"] == "APPROVED"


def test_unticking_a_rule_changes_only_that_visitors_runs(clients):
    a, b = clients
    rules = a.get("/api/policy").json()
    assert rules["compiled_by"] == "defaults" and rules["policy"]["hold_payment_in_flight"] is True
    saved = a.post("/api/policy", json={"policy": {**rules["policy"], "hold_payment_in_flight": False},
                                        "english": rules["english"], "sources": {}, "compiled_by": "owner"}).json()
    assert saved["policy"]["hold_payment_in_flight"] is False
    assert a.get("/api/policy").json()["policy"]["hold_payment_in_flight"] is False
    # B never touched the rules: still the defaults, and B's "With Receipts" side still holds Maya's duplicate
    theirs = b.get("/api/policy").json()
    assert theirs["policy"]["hold_payment_in_flight"] is True and theirs["compiled_by"] == "defaults"
    assert "PAYMENT_IN_FLIGHT" in run_day(b)
    held = waiting(b)
    assert len(held) == 1 and held[0]["args"]["invoice_number"] == "INV-BR-1197"
    # and A's own run really does follow A's rules: the duplicate is no longer held
    assert "PAYMENT_IN_FLIGHT" not in run_day(a)
    assert waiting(a) == []


def test_one_visitors_reset_does_not_clear_another(clients):
    a, b = clients
    run_day(a)
    run_day(b)
    assert len(waiting(a)) == 1 and len(waiting(b)) == 1
    assert a.post("/api/reset").json() == {"reset": True}
    assert a.get("/api/holds").json() == []
    assert len(waiting(b)) == 1


def test_the_number_of_visitor_states_is_bounded(web, monkeypatch):
    from fastapi.testclient import TestClient
    web.VISITORS.clear()
    monkeypatch.setattr(web, "MAX_VISITORS", 3)
    rules = web.DEFAULT_RULES
    people = [TestClient(web.app) for _ in range(5)]
    for p in people:                                                # saving rules is the cheapest act that creates a state
        p.post("/api/policy", json={"policy": {**rules["policy"], "split_detection": False}, "english": "", "sources": {}, "compiled_by": "owner"})
    assert len(web.VISITORS) == 3
    assert people[0].get("/api/policy").json()["policy"]["split_detection"] is True      # the oldest was dropped: back to the defaults
    assert people[4].get("/api/policy").json()["policy"]["split_detection"] is False
    assert rules["policy"]["split_detection"] is True               # the defaults themselves are never changed


def test_an_idle_visitor_expires(web, monkeypatch):
    from fastapi.testclient import TestClient
    web.VISITORS.clear()
    c = TestClient(web.app)
    run_day(c)
    assert len(waiting(c)) == 1 and len(web.VISITORS) == 1
    monkeypatch.setattr(web, "VISITOR_IDLE_S", 0.0)
    assert c.get("/api/holds").json() == [] and not web.VISITORS


def test_the_shared_mcp_workspace_reaches_the_phone_only_where_that_is_switched_on(clients, web, monkeypatch):
    a, b = clients
    r = web.MCP_SESSION["r"]
    before = list(r.holds)
    try:
        res = r.call("create_payout", {"vendor": "Blue Ridge Finishes", "receiver_email": "orders@blueridgefinishes.com",
                                       "amount": 1836, "invoice_number": "INV-BR-1197"})
        assert res["held_by_receipts"]
        monkeypatch.setattr(web, "MCP_ON_PHONE", True)              # your own machine: the MCP hold is on the phone
        assert [h["session"] for h in waiting(a)] == ["mcp"]
        monkeypatch.setattr(web, "MCP_ON_PHONE", False)             # a public server: it is on nobody's phone, and nobody can decide it
        assert a.get("/api/holds").json() == [] and b.get("/api/holds").json() == []
        assert a.post("/api/approve", json={"session": "mcp", "hold_id": res["hold_id"]}).status_code == 404
    finally:
        r.holds[:] = before


def test_all_nineteen_models_are_in_the_menu_and_a_frontier_run_replays(clients, web):
    a, _ = clients
    meta = a.get("/api/meta").json()
    assert len(meta["models"]) == 12 and len(meta["frontier_models"]) == 7
    # the open models' runs keep the line numbers they always had; the frontier runs are numbered clear of them
    opens = a.get("/api/recorded", params={"scenario": DAY, "model": MODEL}).json()
    assert len(opens) == 4 and all(r["line"] < web.FRONTIER_LINE0 for r in opens)
    for model in meta["frontier_models"]:
        rows = a.get("/api/recorded", params={"scenario": DAY, "model": model}).json()
        assert sorted((r["mode"], r["rep"]) for r in rows) == [("enforce", 0), ("enforce", 1), ("observe", 0), ("observe", 1)], model
        assert all(r["line"] >= web.FRONTIER_LINE0 for r in rows)
    # replay a frontier run that paid Maya twice with nothing checking it: the replay reaches the same verdict now
    paid_twice = [r for m in meta["frontier_models"] for r in a.get("/api/recorded", params={"scenario": DAY, "model": m}).json()
                  if r["mode"] == "observe" and r["attempts"]]
    assert paid_twice
    res = a.get("/api/replay", params={"line": paid_twice[0]["line"], "speed": 100})
    assert res.status_code == 200 and "PAYMENT_IN_FLIGHT" in res.text and '"bad_money": 1836.0' in res.text
    assert f'"model": "{paid_twice[0]["model"]}"' in res.text
    assert a.get("/api/replay", params={"line": web.FRONTIER_LINE0 + 10**6}).status_code == 404


def test_the_book_and_the_results_are_shared_and_unchanged_in_shape(clients):
    a, b = clients
    rows = a.get("/api/ledger", params={"limit": 5}).json()
    assert len(rows) == 5 and {"decision", "arm", "model", "scenario", "amount", "why", "codes"} <= set(rows[0])
    assert rows == b.get("/api/ledger", params={"limit": 5}).json()
    assert a.get("/api/results").json()["scored_runs"] == 1444
    index = a.get("/")
    assert index.status_code == 200 and "<title>Receipts</title>" in index.text
