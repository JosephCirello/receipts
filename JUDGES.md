# Review Receipts in five minutes

A guide for the judges of the PayPal AI Hackathon. Nothing on this page needs an account, a key or an install.

## 1. See it work (three minutes)

1. Open **https://receipts-4nvn.onrender.com**. It opens on Maya's Tuesday: a second notice has crossed the payment she sent on Monday.
2. Press **Run the day**. The same AI works the same inbox twice. On the left nothing checks it, and it pays the bill a second time: $1,836.00 leaves wrongly. On the right Receipts holds that payment for Maya.
3. Press **Open Maya's phone** and tap **Decline**. The card reads *Declined · never sent to PayPal*.
4. Open **Her book**, tap **Would have paid twice**, and press **Download for the accountant**.
5. Open **Results**: what 19 AI models did with Maya's bills over 19 business days, first with nothing checking them and then with Receipts.

Prefer to watch? [The video is 2 minutes 54 seconds](https://youtu.be/vLFWDG3o_xA). The hosted demo replays the recorded runs on our stand-in for PayPal; the video shows the same runs on PayPal's real sandbox.

## 2. The five judging criteria, and where each one shows

| Criterion | Where to look |
|---|---|
| **Technological Implementation** | In sandbox mode the agent's PayPal tools go through PayPal's official MCP server (`@paypal/mcp`), supplier payments use the Payouts API, and Receipts reads PayPal's own records before it decides: [`receipts/paypal.py`](receipts/paypal.py), [`receipts/rules.py`](receipts/rules.py). Receipts is itself an MCP server: [`receipts/mcp_server.py`](receipts/mcp_server.py). The 86 tests run on a clean machine at every push (the badge at the top of the [README](README.md)). `python sandbox_check.py` walks each PayPal path against your own sandbox. |
| **Design** | The live demo is the product: *Watch*, *Maya's phone*, *Her rules*, *Her book*, *Results*. It fits a phone screen and follows light or dark mode. |
| **Potential Impact** | [Why it matters beyond Maya](README.md#why-it-matters-beyond-maya): duplicate payments, payments fraud and what merchants told PayPal, each figure with its source and the date we read it. [What we found](README.md#what-we-found): what happened when 19 AI models were handed the job. |
| **Innovation/Idea** | *The agent reads the email. Receipts reads PayPal.* Each decision is made from PayPal's records, not from what the agent says. The finding behind it: PayPal's `list_transactions` tool shows finished payments unless it is asked for the rest, so a careful agent can check, find nothing, and pay twice. See *A suggestion for PayPal*, the last paragraph of [What we measured](README.md#what-we-measured). |
| **Presentation** | [The video](https://youtu.be/vLFWDG3o_xA), [our entry on Devpost](https://devpost.com/software/receipts-yjs4tg), and the [README](README.md). |

## 3. Check our numbers yourself

Every number we state comes from one piece of code reading the recorded runs, and every run is in this repository.

| What we say | Where it comes from |
|---|---|
| 19 AI models, 19 business days, 1,444 runs | `python media/stated_numbers.py` prints every number the README states. The runs are in [`results/`](results/): `episodes.jsonl` as recorded, `episodes_scored.jsonl` as scored. |
| With nothing checking them, 7.0% of the money the AIs sent should never have left ($90,560 of $1,301,287) | The same command, under `receipts_off`. The Results tab of the live demo reads the same code: [`receipts/measure.py`](receipts/measure.py). |
| On Maya's Tuesday, 61% of runs paid her twice (23 of 38) | The same command, under `crossed_in_the_mail_off`. To replay any of them, pick the day *Crossed in the mail* and a model in the live demo. |
| With Receipts, $0.00 left wrongly, and 98% of honest payments and refunds went straight through (1,038 of 1,064) | The same command, under `receipts_on`. |
| One extra line in the prompt cut double payments by 67%, and one in three still got through | [`results/promptfix_check_pending/`](results/promptfix_check_pending/). `python media/stated_numbers.py --table` lists the eleven that got through. |
| What counts as harm | Written per day in [`scenarios/scenarios.json`](scenarios/scenarios.json) (`bad_outcomes`), apart from the rules, so Receipts is not grading its own homework. |

## 4. What we do not claim

The README's [Honest limits](README.md#honest-limits) says it in full. The short version:

- Two runs per model, day and arm show that a model can fail, not how often it does.
- Our 19 days hold far more traps than a real month, so 7.0% is about this test, not about every business.
- The measurement ran on our stand-in for PayPal, which mirrors PayPal's tools. The video shows the same runs on PayPal's real sandbox.
- We make no compliance claim.

## 5. What the hackathon asks, and where it is

| The hackathon asks | Where it is |
|---|---|
| Meaningfully integrate a PayPal technology | PayPal's official MCP server, the Payouts API, and the Orders, Captures, Refunds and Transaction Search APIs: [How it works](README.md#how-it-works). |
| Meaningfully incorporate AI | The agent is the AI: 19 models were measured doing Maya's job. A language model also drafts her plain-English rules into exact settings; code enforces them, and the model never decides a payment. |
| A working build the judges can run | The hosted demo above, or [two minutes on your own computer with no keys](README.md#run-it-two-minutes-no-keys). |
| A public, open-source repository with its licence visible | This repository, MIT. |
| A demo video under three minutes | https://youtu.be/vLFWDG3o_xA (2:54). |
| Sponsor tools we chose to use | AG Grid and Render: [Sponsor tools](README.md#sponsor-tools). |
