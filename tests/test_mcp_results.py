"""How a call to PayPal's MCP server is read when PayPal refuses it.

PayPal's server reports a refused call as ordinary content ({"ok": false, "status": 422, ...}), not as an MCP
error. Read as it stands, that carries no "error" key, and a refund PayPal had refused was recorded as money that
moved. REFUSED below is what the real sandbox returned on 2026-11-10 for a $720 refund asked of a $420 capture,
and WENT_THROUGH is what it returned for the $420 refund that followed. Nothing here touches the network.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from receipts.core import Receipts  # noqa: E402
from receipts.paypal import StandIn, _mcp_result  # noqa: E402
from receipts.scenarios import by_id  # noqa: E402

REFUSED = json.dumps({"ok": False, "status": 422, "code": "PAYPAL_API_HTTP_ERROR",
                      "message": "The requested action could not be performed, semantically incorrect, or failed business validation.: "
                                 "The refund amount must be less than or equal to the capture amount that has not yet been refunded."})
WENT_THROUGH = json.dumps({"id": "0RM85533JK041545C", "status": "PENDING", "status_details": {"reason": "ECHECK"}, "links": []})


def test_a_call_paypal_refused_carries_an_error():
    out = _mcp_result(REFUSED)
    assert out["error"]["code"] == "PAYPAL_API_HTTP_ERROR"
    assert "refund amount must be less than or equal" in out["error"]["message"]
    assert out["status"] == 422


def test_a_call_that_went_through_is_left_as_it_is():
    out = _mcp_result(WENT_THROUGH)
    assert "error" not in out
    assert out["id"] == "0RM85533JK041545C" and out["status"] == "PENDING"


def test_an_answer_that_only_says_ok_true_is_not_an_error():
    assert "error" not in _mcp_result(json.dumps({"ok": True, "id": "X"}))


def test_an_mcp_error_is_marked_whatever_it_holds():
    assert _mcp_result(json.dumps({"detail": "boom"}), is_error=True) == {"error": {"detail": "boom"}}
    assert _mcp_result("not json at all", is_error=True) == {"error": {"text": "not json at all"}}


def test_text_that_is_not_json_is_kept_as_text():
    assert _mcp_result("plain words") == {"text": "plain words"}


def test_a_list_is_passed_through():
    assert _mcp_result(json.dumps([{"id": 1}])) == [{"id": 1}]


def test_a_refund_paypal_refused_is_not_recorded_as_money_that_moved():
    scn = by_id()["S5_i_am_the_owner"]
    r = Receipts(scn, StandIn(scn.get("paypal", {}), scn["id"]), mode="observe")
    r._record_money("create_refund", {"capture_id": "ANY", "amount": 720}, _mcp_result(REFUSED))
    assert r.ledger == []
    # the same answer read without the fix has no "error" key: this is the reading that recorded $720 as moved
    assert "error" not in json.loads(REFUSED)
