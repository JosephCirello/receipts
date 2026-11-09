"""Every number the video, the cards and the README state, read from results/episodes_scored.jsonl.

  python media/stated_numbers.py            # the full summary as JSON
  python media/stated_numbers.py --table    # cost against harm, one line per model

The computation lives in receipts/measure.py, which the app's Results tab also reads.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from receipts import measure  # noqa: E402

rows = measure.load_scored(ROOT / "results" / "episodes_scored.jsonl")
s = measure.summary(rows)

if "--table" in sys.argv:
    print(f"{'model':30s} {'provider':9s} {'$/M in':>7s} {'$/M out':>8s} {'cost/17d':>9s} {'harm off':>10s} {'share':>6s} {'fell':>6s} {'honest off':>10s} {'honest on':>10s}")
    for m, v in s["by_model_off"].items():
        on = s["by_model_on"].get(m, {})
        print(f"{m[:30]:30s} {v['provider']:9s} {v['price_in']:>7.2f} {v['price_out']:>8.2f} {v['cost_per_agent_run_usd'] or 0:>9.2f} "
              f"{v['harm_money']:>10,.2f} {v['harm_share_pct']:>5.1f}% {v['trap_days_harm']:>2d}/{v['trap_days']:<3d} "
              f"{v['legit_done']:>4d}/{v['legit_expected']:<5d} {on.get('legit_done', 0):>4d}/{on.get('legit_expected', 0):<5d}")
    o, e = s["receipts_off"], s["receipts_on"]
    print(f"\n{s['scored_runs']} runs, {s['models']} models, {s['days']} days. Off: ${o['harm_money']:,.2f} of ${o['money_moved']:,.2f} ({o['harm_share_pct']}%). "
          f"On: ${e['harm_money']:,.2f}. Spend on the runs: ${o['cost_usd'] + e['cost_usd']:,.2f}")
else:
    print(json.dumps(s, indent=1))
