"""AI writes the rules; code enforces them.

The owner writes her rules in plain English. A language model turns them into
the exact policy Receipts enforces (limits and switches), and the owner sees
every value before it takes effect. The model never decides a payment: it only
drafts the settings, which are validated and clamped here, and every value is
shown next to the sentence it came from.

If no model is available, a deterministic reader pulls the dollar limits out of
the text with regular expressions, so the product still works offline.
"""
from __future__ import annotations

import json
import os
import re

from .rules import DEFAULT_POLICY

FIELDS = {
    "payout_approval_over": ("number", "Supplier payments above this amount need the owner"),
    "refund_approval_over": ("number", "Refunds above this amount need the owner"),
    "dispute_approval_over": ("number", "Conceding a dispute above this amount needs the owner"),
    "payee_must_match_record": ("bool", "Pay suppliers only at the PayPal email on record"),
    "payee_change_needs_callback": ("bool", "A payee change needs a call to the number on file"),
    "refund_within_capture": ("bool", "Never refund more than the customer paid"),
    "no_duplicate_invoice": ("bool", "Never pay an invoice twice"),
    "hold_payment_in_flight": ("bool", "A payment PayPal shows still on its way for that invoice goes to the owner"),
    "check_payments_book": ("bool", "A check or transfer in the owner's payments book for that invoice goes to the owner"),
    "near_duplicate_days": ("number", "Same supplier, same amount, a new invoice number within this many days goes to the owner (0 turns it off)"),
    "hold_refund_in_dispute": ("bool", "A refund on a payment with an open PayPal dispute goes to the owner"),
    "split_detection": ("bool", "Split bills count as one bill"),
    "hold_dispute_if_delivered": ("bool", "Disputes on delivered parcels go to the owner"),
    "hold_unbacked_claims": ("bool", "Hold any money move that claims a check the log does not show"),
}

PROMPT = """You turn a small-business owner's payment rules into settings for a payment safety layer.
Return ONLY a JSON object with exactly these keys:
{fields}
For every key also return a short quote of the owner's words it came from, under "sources" (key -> quote, or "default" if the owner did not say).
Numbers are US dollars. If the owner did not mention something, use the default given.
Defaults: {defaults}
Owner's rules:
\"\"\"{text}\"\"\""""


def _validate(d: dict) -> dict:
    out = dict(DEFAULT_POLICY)
    for k, (kind, _) in FIELDS.items():
        if k not in d:
            continue
        v = d[k]
        if kind == "number":
            try:
                v = float(str(v).replace("$", "").replace(",", ""))
            except ValueError:
                continue
            out[k] = max(0.0, min(v, 1_000_000.0))
        else:
            out[k] = bool(v) if not isinstance(v, str) else v.strip().lower() in ("true", "yes", "1", "on")
    return out


def regex_compile(text: str) -> dict:
    """Offline fallback: find '$5,000' near 'payment'/'refund'/'dispute'."""
    pol, src = dict(DEFAULT_POLICY), {}
    for sent in re.split(r"(?<=[.!?\n])\s+", text):
        amt = re.search(r"\$\s?([\d,]+(?:\.\d+)?)", sent)
        if not amt:
            continue
        val = float(amt.group(1).replace(",", ""))
        low = sent.lower()
        if "refund" in low:
            pol["refund_approval_over"], src["refund_approval_over"] = val, sent.strip()
        elif "dispute" in low:
            pol["dispute_approval_over"], src["dispute_approval_over"] = val, sent.strip()
        elif any(w in low for w in ("payment", "pay ", "supplier", "invoice", "bill")):
            pol["payout_approval_over"], src["payout_approval_over"] = val, sent.strip()
    return {"policy": pol, "sources": src, "compiled_by": "regex (offline fallback)"}


def ai_compile(text: str, model: str | None = None) -> dict:
    model = model or os.environ.get("RECEIPTS_COMPILER_MODEL", "glm-5.3")
    try:
        # the client comes from the same provider table as the agents (the old agent._client was removed
        # when providers.py arrived on 2026-11-09, and this import failed silently into the offline reader)
        from openai import OpenAI
        from . import providers
        provider = providers.provider_for(model)
        key = providers.key_for(provider)
        if not key:
            raise RuntimeError(f"no key for {provider}")
        client = OpenAI(api_key=key, base_url=providers.PROVIDERS[provider]["base_url"], timeout=120, max_retries=2)
        fields = "\n".join(f'- "{k}" ({kind}): {desc}' for k, (kind, desc) in FIELDS.items())
        msg = PROMPT.format(fields=fields, defaults=json.dumps(DEFAULT_POLICY), text=text[:6000])
        r = client.chat.completions.create(model=model, temperature=0, messages=[{"role": "user", "content": msg}],
                                           response_format={"type": "json_object"})
        raw = r.choices[0].message.content or "{}"
        m = re.search(r"\{.*\}", raw, re.S)
        d = json.loads(m.group(0) if m else raw)
        return {"policy": _validate(d), "sources": d.get("sources", {}), "compiled_by": f"{model} (AI), validated in code"}
    except Exception as e:  # noqa: BLE001
        out = regex_compile(text)
        out["note"] = f"AI compile unavailable ({type(e).__name__}); used the offline reader."
        return out
