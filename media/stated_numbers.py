"""Every number the video, the cards and the README state, read from the scored runs.

  python media/stated_numbers.py                       # the full summary as JSON, every model
  python media/stated_numbers.py --table               # cost against harm, one line per model
  python media/stated_numbers.py --group open --table  # open models only (also: frontier)

The computation lives in receipts/measure.py (measure.results), which the app's Results tab also reads.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from receipts import measure  # noqa: E402

group = sys.argv[sys.argv.index("--group") + 1] if "--group" in sys.argv else "all"
s = measure.results(ROOT / "results", group)
print(f"group: {s['group']} | {s.get('groups')}", file=sys.stderr)

if "--table" in sys.argv:
    print(f"{'model':30s} {'provider':9s} {'$/M in':>7s} {'$/M out':>8s} {'cost/19d':>9s} {'harm off':>10s} {'share':>6s} {'fell':>6s} {'honest off':>10s} {'honest on':>10s}")
    for m, v in s["by_model_off"].items():
        on = s["by_model_on"].get(m, {})
        print(f"{m[:30]:30s} {v['provider']:9s} {v['price_in']:>7.2f} {v['price_out']:>8.2f} {v['cost_per_agent_run_usd'] or 0:>9.2f} "
              f"{v['harm_money']:>10,.2f} {v['harm_share_pct']:>5.1f}% {v['trap_days_harm']:>2d}/{v['trap_days']:<3d} "
              f"{v['legit_done']:>4d}/{v['legit_expected']:<5d} {on.get('legit_done', 0):>4d}/{on.get('legit_expected', 0):<5d}")
    o, e = s["receipts_off"], s["receipts_on"]
    print(f"\n{s['scored_runs']} runs, {s['models']} models, {s['days']} days. Off: ${o['harm_money']:,.2f} of ${o['money_moved']:,.2f} ({o['harm_share_pct']}%). "
          f"On: ${e['harm_money']:,.2f}. Spend on the runs: ${o['cost_usd'] + e['cost_usd']:,.2f}")
    if "prompt_fix" in s:
        pf = s["prompt_fix"]
        print(f"\nPROMPT FIX CONTROL ({pf['runs']} runs, {pf['models']} models, Receipts off): one extra line in the owner's rules: \"{pf['line']}\"")
        print(f"{'day':30s} {'fell before':>12s} {'fell after':>11s} {'harm before':>12s} {'harm after':>11s} {'honest before':>14s} {'honest after':>13s}")
        for d, v in pf["by_day"].items():
            b, a = v["before"], v["after"]
            print(f"{d[:30]:30s} {b['fell']:>5d}/{b['runs']:<6d} {a['fell']:>5d}/{a['runs']:<5d} {b['harm_money']:>12,.2f} {a['harm_money']:>11,.2f} "
                  f"{b['legit_done']:>6d}/{b['legit_expected']:<7d} {a['legit_done']:>6d}/{a['legit_expected']:<6d}")
        b, a = pf["before"], pf["after"]
        print(f"{'ALL':30s} {b['fell']:>5d}/{b['runs']:<6d} {a['fell']:>5d}/{a['runs']:<5d} {b['harm_money']:>12,.2f} {a['harm_money']:>11,.2f} "
              f"{b['legit_done']:>6d}/{b['legit_expected']:<7d} {a['legit_done']:>6d}/{a['legit_expected']:<6d}")
        print("models fixed by the line:", pf["models_fixed"]); print("models still paying twice:", pf["models_still_paying_twice"])
        lk = pf["paid_twice_lookups"]
        print(f"\nThe {lk['duplicates']} duplicate payments made after the line, by what the agent had looked at before paying:")
        print(f"  asked PayPal for pending payments, the invoice was in no list, paid again: {lk['asked_pending_found_nothing']}")
        print(f"  looked in PayPal for completed payments only: {lk['completed_only']}")
        print(f"  the owner's payments book listed the earlier payment, paid anyway: {lk['shown_in_payments_book_and_paid']}")
        print(f"  paid without looking anywhere: {lk['no_lookup']}")
        print(f"  opened the payments book only: {lk['book_only']}")
        print(f"  PayPal listed the earlier payment before the agent paid: {lk['shown_in_paypal_and_paid']}")
        for c in lk["cases"]:
            print(f"    {c['group']:32s} {c['model'][:30]:30s} {c['scenario']:26s} run {c['rep']}  {c['invoice']}")
        print()
        print(f"{'model':30s} {'fell before':>12s} {'fell after':>11s} {'honest before':>14s} {'honest after':>13s}")
        for m, v in pf["by_model"].items():
            b, a = v["before"], v["after"]
            print(f"{m[:30]:30s} {b['fell']:>5d}/{b['runs']:<6d} {a['fell']:>5d}/{a['runs']:<5d} {b['legit_done']:>6d}/{b['legit_expected']:<7d} {a['legit_done']:>6d}/{a['legit_expected']:<6d}")
else:
    print(json.dumps(s, indent=1))
