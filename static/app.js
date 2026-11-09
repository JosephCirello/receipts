/* Receipts, the client. Plain JavaScript; AG Grid Community for the ledger and results tables. */
const $ = (s, el = document) => el.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const usd = (n) => (n == null || isNaN(n) ? "" : "$" + Number(n).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
const META = { scenarios: [], models: [] };
const ARMS = {};

/* ---------- tabs ---------- */
document.querySelectorAll("#tabs button").forEach((b) =>
  b.addEventListener("click", () => showTab(b.dataset.tab)));
function showTab(t) {
  document.querySelectorAll("#tabs button").forEach((x) => x.classList.toggle("on", x.dataset.tab === t));
  document.querySelectorAll(".tab").forEach((x) => x.classList.toggle("on", x.id === "tab-" + t));
  if (t === "ledger") loadLedger();
  if (t === "results") loadResults();
  if (t === "rules") loadPolicy();
  if (t === "owner") pollHolds();
  history.replaceState(null, "", "#" + t);
}

/* ---------- boot ---------- */
async function boot() {
  const m = await (await fetch("/api/meta")).json();
  Object.assign(META, m);
  $("#scn").innerHTML = m.scenarios.map((s) => `<option value="${s.id}">${esc(s.title)}${s.kind === "control" ? "" : ""}</option>`).join("");
  $("#model").innerHTML = m.models.map((x) => `<option>${esc(x)}</option>`).join("");
  $("#env").textContent = m.paypal_mode === "sandbox" ? "PayPal sandbox · live" : "PayPal stand-in (no keys)";
  if (!m.live_allowed) $("#source").querySelector('[value="live"]').disabled = true;
  const note = async () => {
    const s = m.scenarios.find((x) => x.id === $("#scn").value);
    $("#scnNote").textContent = s ? (s.kind === "control" ? "Control day: " : "Today: ") + s.pressure + "." : "";
    const want = $("#scn").value;
    const ib = await (await fetch("/api/inbox?scenario=" + encodeURIComponent(want))).json();
    if (want !== $("#scn").value) return;          // a later choice won the race
    $("#inbox").innerHTML = (ib.messages || []).map((x) => `<div class="mail"><div class="from">${esc(x.from)}</div><div class="subj">${esc(x.subject)}</div><div class="body">${esc(x.body)}</div></div>`).join("");
    $("#inbox").querySelectorAll(".mail").forEach((el) => el.addEventListener("click", () => el.classList.toggle("open")));
  };
  $("#scn").addEventListener("change", note); note();
  $("#sbs").addEventListener("change", () => $("#arms").classList.toggle("single", !$("#sbs").checked));
  $("#go").addEventListener("click", runDay);
  if (new URLSearchParams(location.search).get("clean") === "1") $("#howto").classList.add("gone");
  try { if (localStorage.getItem("howto-gone") === "1") $("#howto").classList.add("gone"); } catch {}
  $("#howtoX").addEventListener("click", () => { $("#howto").classList.add("gone"); try { localStorage.setItem("howto-gone", "1"); } catch {} });
  const params = new URLSearchParams(location.search);
  if (params.get("scenario")) $("#scn").value = params.get("scenario"), note();
  if (params.get("model")) $("#model").value = params.get("model");
  if (params.get("theme")) document.documentElement.dataset.theme = params.get("theme");
  if (params.get("sbs") === "0") { $("#sbs").checked = false; $("#arms").classList.add("single"); }
  const t = location.hash.replace("#", "");
  if (t) showTab(t);
  if (params.get("autorun") === "1") runDay();
  setInterval(pollHolds, 2500);
}

/* ---------- live ---------- */
function resetArm(mode) {
  ARMS[mode] = { session: null, lost: 0, pendingBad: null, es: null, said: [] };
  $("#feed-" + mode).innerHTML = "";
  $("#lost-" + mode).textContent = "$0.00";
}
async function runDay() {
  const scenario = $("#scn").value, model = $("#model").value, source = $("#source").value;
  const modes = $("#sbs").checked ? ["observe", "enforce"] : ["enforce"];
  $("#go").disabled = true;
  Object.values(ARMS).forEach((a) => a.es && a.es.close());
  modes.forEach(resetArm);
  let urls = {};
  if (source === "live") {
    modes.forEach((md) => (urls[md] = `/api/run?scenario=${encodeURIComponent(scenario)}&model=${encodeURIComponent(model)}&mode=${md}`));
  } else {
    const rec = await (await fetch(`/api/recorded?scenario=${encodeURIComponent(scenario)}&model=${encodeURIComponent(model)}`)).json();
    const wantRep = new URLSearchParams(location.search).get("rep");      // pin one recorded run (used by the video takes)
    for (const md of modes) {
      const pick = rec.filter((r) => r.mode === md && (wantRep == null || String(r.rep) === wantRep)).sort((a, b) => (b.attempts || 0) - (a.attempts || 0))[0];
      if (pick) urls[md] = `/api/replay?line=${pick.line}&speed=${new URLSearchParams(location.search).get("speed") || 1}`;
      else add(md, `<div class="err">No recorded ${md === "observe" ? "Receipts-off" : "Receipts-on"} run for ${esc(model)} on this day yet. Try a live run.</div>`);
    }
  }
  let open = Object.keys(urls).length;
  if (!open) $("#go").disabled = false;
  for (const [md, url] of Object.entries(urls)) {
    const es = new EventSource(url);
    ARMS[md].es = es;
    es.onmessage = (m) => {
      const e = JSON.parse(m.data);
      render(md, e);
      if (e.type === "done") { es.close(); if (--open <= 0) $("#go").disabled = false; }
    };
    es.onerror = () => { es.close(); if (--open <= 0) $("#go").disabled = false; };
  }
}

function add(mode, html) {
  const feed = $("#feed-" + mode);
  const d = document.createElement("div");
  d.className = "ev";
  d.innerHTML = html;
  feed.appendChild(d);
  feed.scrollTop = feed.scrollHeight;
  return d;
}
function cleanText(t) { return String(t || "").replace(/\*\*/g, "").replace(/^#+\s*/gm, "").trim(); }

const DESK_LABEL = {
  read_inbox: () => "Read the inbox",
  list_vendors: () => "Opened the vendor master",
  call_vendor_on_file: (a) => `Called ${a.vendor} at the number on file`,
  ask_owner: (a) => `Messaged the owner: “${a.subject || ""}”`,
  reply_to_customer: (a) => `Emailed ${a.to}`,
  get_order: (a) => `PayPal · get_order ${a.id}`,
  get_dispute: (a) => `PayPal · get_dispute ${a.dispute_id}`,
  get_shipment_tracking: (a) => `PayPal · get_shipment_tracking ${a.order_id}`,
  payments_book: () => "Opened the owner's payments book (checks and transfers)",
};
const TS_WORD = { S: "completed", P: "pending", D: "denied", V: "reversed" };
function txnSummary(args, r) {
  const st = (args && args.transaction_status) || "S";
  const rows = (r && r.transaction_details) || [];
  const invs = rows.map((x) => (x.transaction_info || {}).invoice_id).filter(Boolean);
  const dflt = args && args.transaction_status ? "" : " (the tool's default)";
  return `<b>Checked PayPal</b> · list_transactions · showing <b>${TS_WORD[st] || st}</b> payments only${dflt} · ${rows.length} found${invs.length ? ": " + invs.slice(-6).join(", ") : ""}`;
}
const MONEY = new Set(["create_payout", "create_refund", "accept_dispute_claim", "update_vendor_payee"]);

function moneyTitle(v) {
  const a = v.args || {};
  if (v.tool === "create_payout") return [`Pay ${a.vendor || "?"} ${usd(a.amount)}`, `to ${a.receiver_email} · ${a.invoice_number || ""}`];
  if (v.tool === "create_refund") return [`Refund ${a.amount != null ? usd(a.amount) : "in full"}`, `PayPal capture ${a.capture_id}`];
  if (v.tool === "accept_dispute_claim") return [`Concede dispute ${usd(v.amount)}`, `PayPal dispute ${a.dispute_id}`];
  if (v.tool === "update_vendor_payee") return [`Change ${a.vendor}'s PayPal`, `to ${a.new_paypal_email}`];
  return [v.tool, ""];
}
const BADGE = { observe: { ALLOW: "WOULD ALLOW", HOLD: "WOULD HOLD", BLOCK: "WOULD STOP" }, enforce: { ALLOW: "SENT TO PAYPAL", HOLD: "HELD FOR OWNER", BLOCK: "STOPPED" } };

function render(mode, e) {
  const A = ARMS[mode];
  switch (e.type) {
    case "session": A.session = e.session; $("#sub-" + mode).textContent = (mode === "observe" ? "Calls go straight to PayPal" : "Every money move checked first") + ` · PayPal ${e.backend}`;
      if (e.note) add(mode, `<div class="replay-tag">${esc(e.note)}</div>`);
      break;
    case "replay": add(mode, `<div class="replay-tag">Replay of a recorded ${esc(e.model)} run (${esc((e.recorded_at || "").replace("T", " ").replace("Z", " UTC"))}). The agent's words and calls are the recorded ones; Receipts and PayPal are running now.</div>`); break;
    case "say":
      if (e.where !== "reply") break;
      A.said.push(e.text);
      add(mode, `<div class="say"><div class="avatar">AI</div><div class="bubble${e.text.length > 420 ? " long" : ""}">${e.marker ? `<span class="marker">SAID: ${e.marker === "REFUSED" ? "NO / SUSPICIOUS" : "WILL VERIFY / HOLD"}</span><br>` : ""}${esc(cleanText(e.text))}</div></div>`);
      break;
    case "call":
      if (MONEY.has(e.tool) || e.tool === "finish") break;
      if (DESK_LABEL[e.tool]) add(mode, `<div class="act">› <b>${esc(DESK_LABEL[e.tool](e.args || {}))}</b></div>`);
      break;
    case "desk":
      if (e.tool === "call_vendor_on_file" && e.result && e.result.they_said) add(mode, `<div class="phone-said"><b>On the phone:</b> “${esc(e.result.they_said)}”</div>`);
      if (e.tool === "payments_book" && e.result) {
        const b = e.result.payments_outside_paypal || [];
        add(mode, `<div class="phone-said"><b>Payments book:</b> ${b.length ? b.map((x) => `${esc(x.invoice)} · ${esc(x.method)} · ${esc(x.date)}`).join("; ") : "nothing paid outside PayPal"}</div>`);
      }
      break;
    case "verdict": {
      const [t, sub] = moneyTitle(e);
      const obs = e.mode === "observe";
      if (e.decision === "ALLOW") { A.pendingTitle = t; break; }
      if (obs && e.decision !== "ALLOW") A.pendingBad = e.amount || 0;
      if (!obs && e.decision !== "ALLOW") { A.lost += e.amount || 0; $("#lost-" + mode).textContent = usd(A.lost); }
      const why = (e.findings || []).map((f) => `<li>${esc(f.why)}</li>`).join("");
      const saydo = e.words_class === "SAID_NO_DID_IT"
        ? `<div class="saydo">Said one thing, did another. Earlier it wrote: <q>${esc(cleanText((e.said_quotes || [])[0] || "").slice(0, 220))}</q></div>` : "";
      add(mode, `<div class="verdict v-${e.decision}${obs ? " observe" : ""}"><div class="vh"><div class="what">${esc(t)}<small>${esc(sub)}</small></div><span class="badge ${e.decision}">${BADGE[obs ? "observe" : "enforce"][e.decision]}</span></div>${why ? `<div class="why"><ul>${why}</ul></div>` : ""}${saydo}</div>`);
      break;
    }
    case "paypal": {
      const r = e.result || {};
      if (!MONEY.has(e.tool)) {
        if (e.tool === "list_transactions") add(mode, `<div class="phone-said txn">${txnSummary(e.args, r)}</div>`);
        break;
      }
      const ok = !r.error;
      const id = r.payout_batch_id || r.id || r.dispute_id || "";
      const status = r.batch_status || r.status || (r.error ? "ERROR" : "");
      const bad = A.pendingBad != null && ok;
      if (bad) { A.lost += A.pendingBad; $("#lost-" + mode).textContent = usd(A.lost); }
      const title = A.pendingTitle; A.pendingBad = null; A.pendingTitle = null;
      add(mode, `<div class="pp${bad ? " moved-bad" : ""}"><span class="chk">${ok ? "✓" : "!"}</span><span>${bad ? "<b>Money moved</b> · " : title ? (mode === "observe" ? `${esc(title)} · ` : `<b class="cleared">Receipts: cleared</b> · ${esc(title)} · `) : ""}PayPal ${esc(e.backend)} · ${esc(e.tool)} · ${esc(id)} · ${esc(status)}</span></div>`);
      break;
    }
    case "owner": add(mode, `<div class="act">› <b>Owner ${esc(e.action)} hold ${esc(e.hold_id)}</b></div>`); break;
    case "report": {
      const c = e.check || {};
      const gaps = (c.gaps || []).map((g) => `<div class="gap">${esc(gapText(g))}</div>`).join("");
      const act = c.actual || {};
      add(mode, `<div class="report ${c.match ? "match" : "mismatch"}"><h4>End-of-day report, checked against PayPal</h4>${c.match
        ? `The report matches PayPal: ${act.paid?.length || 0} paid, ${act.money_back?.length || 0} refunded or conceded.`
        : gaps}</div>`);
      break;
    }
    case "done": {
      const o = e.outcome || {};
      add(mode, `<div class="done">Day finished${e.seconds ? " in " + e.seconds + "s" : ""}. Legitimate work done: ${o.legit_done ?? "?"} of ${o.legit_expected ?? "?"}. ${o.trap_attempts ? `Risky money moves tried: ${o.trap_attempts}.` : "No risky money move tried."}</div>`);
      break;
    }
    case "error": add(mode, `<div class="err">${esc(e.msg)}</div>`); break;
  }
}
function gapText(g) {
  const w = { paid: "paid", money_back: "refunded to the buyer" }[g.what] || g.what;
  if (g.type === "CLAIMED_BUT_NOT_IN_PAYPAL") return `The report says ${g.ref} was ${w}. PayPal shows no such ${w === "paid" ? "payment" : "transaction"}.`;
  if (g.type === "IN_PAYPAL_BUT_NOT_REPORTED") return `PayPal shows ${g.ref} ${w}. The report does not mention it.`;
  if (g.type === "SAID_HELD_BUT_MONEY_MOVED") return `The report says ${g.ref} was held. Money for it moved in PayPal.`;
  return JSON.stringify(g);
}

/* ---------- owner ---------- */
async function pollHolds() {
  let hs = [];
  try { hs = await (await fetch("/api/holds")).json(); } catch { return; }
  const waiting = hs.filter((h) => h.status === "WAITING").length;
  $("#holdCount").hidden = !waiting; $("#holdCount").textContent = waiting;
  const box = $("#holds");
  if (!hs.length) return;
  const sig = JSON.stringify(hs.map((h) => [h.id, h.status]));
  if (sig === box.dataset.sig) return;          // unchanged: do not re-render (keeps the cards steady)
  box.dataset.sig = sig;
  box.innerHTML = hs.map((h) => {
    const a = h.args || {};
    const ttl = h.tool === "create_payout" ? `Pay ${a.vendor}` : h.tool === "create_refund" ? "Refund a customer" : h.tool === "accept_dispute_claim" ? "Concede a dispute" : h.tool;
    return `<div class="hold"><div class="ttl">${esc(ttl)} · ${esc(h.scenario)}</div><div class="amt">${usd(h.amount)}</div><ul>${(h.why || []).map((w) => `<li>${esc(w)}</li>`).join("")}</ul>${h.status === "WAITING"
      ? `<div class="btns"><button class="approve" data-s="${h.session}" data-h="${h.id}">Approve</button><button class="decline" data-s="${h.session}" data-h="${h.id}">Decline</button></div>`
      : `<div class="state ${h.status}">${h.status === "APPROVED" ? `Approved · sent to PayPal ${esc((h.result || {}).backend || "")} · ${esc((h.result || {}).payout_batch_id || (h.result || {}).id || "")} · ${esc((h.result || {}).batch_status || (h.result || {}).status || "")}` : "Declined · never sent to PayPal"}</div>`}</div>`;
  }).join("");
  box.querySelectorAll("button").forEach((b) => b.addEventListener("click", async () => {
    await fetch(b.classList.contains("approve") ? "/api/approve" : "/api/decline", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ session: b.dataset.s, hold_id: b.dataset.h }) });
    pollHolds();
  }));
}

/* ---------- rules ---------- */
let DRAFT = null;
async function loadPolicy() {
  if (DRAFT) return;
  const p = await (await fetch("/api/policy")).json();
  $("#english").value = p.english;
  DRAFT = p; drawRules();
}
function drawRules() {
  const p = DRAFT;
  $("#compiledBy").textContent = p.compiled_by ? "Drafted by: " + p.compiled_by : "";
  $("#ruleList").innerHTML = Object.entries(p.fields).map(([k, f]) => {
    const v = p.policy[k];
    const input = f.kind === "number" ? `<input type="number" data-k="${k}" value="${v}" min="0" step="1">` : `<input type="checkbox" data-k="${k}" ${v ? "checked" : ""}>`;
    const src = (p.sources || {})[k];
    const srcLine = !src ? "" : String(src).toLowerCase() === "default" ? `<div class="src">Built in: on by default</div>` : `<div class="src">From your words: “${esc(src)}”</div>`;
    return `<div class="rule"><div class="lbl">${esc(f.label)}</div><div class="val">${f.kind === "number" ? "$ " : ""}${input}</div>${srcLine}</div>`;
  }).join("");
}
$("#compile").addEventListener("click", async () => {
  $("#compile").disabled = true; $("#compiledBy").textContent = "Reading your rules…";
  const r = await (await fetch("/api/compile", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ english: $("#english").value }) })).json();
  DRAFT = r; drawRules(); $("#compile").disabled = false;
});
$("#usePolicy").addEventListener("click", async () => {
  const pol = {};
  document.querySelectorAll("#ruleList [data-k]").forEach((i) => (pol[i.dataset.k] = i.type === "checkbox" ? i.checked : Number(i.value)));
  await fetch("/api/policy", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ policy: pol, english: $("#english").value, sources: DRAFT.sources || {}, compiled_by: DRAFT.compiled_by || "owner" }) });
  $("#policySaved").textContent = "In force for every run from now on.";
});

/* ---------- ledger (AG Grid) ---------- */
let GRID = null;
const chip = (p) => p.value ? `<span class="chip ${p.value}">${p.value}</span>` : "";
async function loadLedger() {
  const rows = await (await fetch("/api/ledger")).json();
  const n = (f) => rows.filter(f).length;
  const stopped = rows.filter((r) => r.decision !== "ALLOW" && r.arm === "Receipts ON").reduce((a, r) => a + (r.amount || 0), 0);
  $("#ledgerSum").innerHTML = `<div class="s"><b>${rows.length}</b>money moves tried</div><div class="s"><b>${n((r) => r.decision === "ALLOW")}</b>cleared</div>`
    + `<div class="s"><b>${n((r) => r.decision === "HOLD")}</b>held for the owner</div><div class="s"><b>${n((r) => r.decision === "BLOCK")}</b>stopped</div>`
    + `<div class="s"><b>${usd(stopped)}</b>stopped or held with Receipts on</div>`;
  if (!GRID) {
    GRID = agGrid.createGrid($("#grid"), {
      rowData: rows,
      columnDefs: [
        { field: "decision", headerName: "Receipts", cellRenderer: chip, width: 120, filter: true, pinned: "left", sort: "desc",
          comparator: (a, b) => ({ BLOCK: 2, HOLD: 1, ALLOW: 0 }[a] ?? -1) - ({ BLOCK: 2, HOLD: 1, ALLOW: 0 }[b] ?? -1) },
        { field: "arm", width: 130, filter: true },
        { field: "model", width: 230, filter: true },
        { field: "scenario", width: 220, filter: true },
        { field: "tool", width: 170, filter: true },
        { field: "amount", width: 120, valueFormatter: (p) => usd(p.value), type: "rightAligned", filter: "agNumberColumnFilter" },
        { field: "ref", headerName: "Invoice / capture / dispute", width: 210 },
        { field: "to", headerName: "Payee", width: 240 },
        { field: "codes", headerName: "Rule", width: 250, filter: true },
        { field: "said_first", headerName: "Said no first", width: 130, cellRenderer: (p) => (p.value ? "⚠ yes" : "") },
        { field: "why", headerName: "Why (built from PayPal and the records)", flex: 1, minWidth: 380, tooltipField: "why" },
        { field: "paypal_id", headerName: "PayPal id", width: 170 },
        { field: "backend", headerName: "PayPal", width: 100 },
      ],
      defaultColDef: { sortable: true, resizable: true },
      animateRows: true,
      pagination: true, paginationPageSize: 50,
      rowClassRules: { "row-live": (p) => p.data && p.data.live, "r-BLOCK": (p) => p.data && p.data.decision === "BLOCK",
                       "r-HOLD": (p) => p.data && p.data.decision === "HOLD", "r-ALLOW": (p) => p.data && p.data.decision === "ALLOW" },
    });
    $("#quick").addEventListener("input", (e) => GRID.setGridOption("quickFilterText", e.target.value));
  } else GRID.setGridOption("rowData", rows);
}

/* ---------- results ---------- */
let MGRID = null, DGRID = null;
const money0 = (x) => "$" + Math.round(x || 0).toLocaleString("en-US");
const DAY_TITLE = {};
const GROUP_LABEL = { all: "All models", open: "Open models", frontier: "Frontier models" };
const GROUP_WHO = { all: "", open: "open-model ", frontier: "frontier-model " };
let RES_GROUP = new URLSearchParams(location.search).get("group") || "all";
async function loadResults(group = RES_GROUP) {
  RES_GROUP = group;
  const s = await (await fetch("/api/results?group=" + encodeURIComponent(group))).json();
  const body = $("#resultsBody");
  if (!s.scored_runs) { body.innerHTML = `<div class="card">No measured runs on file yet. <code>python run_batch.py</code> writes them.</div>`; return; }
  META.scenarios.forEach((x) => (DAY_TITLE[x.id] = x.title));
  const o = s.receipts_off, e = s.receipts_on, sn = s.second_notice_off, cr = s.crossed_in_the_mail_off;
  const modelsPaidTwice = Object.values(s.by_model_off).filter((m) => m.paid_twice > 0).length;
  const FR = new Set(s.frontier_models || []);
  const kinds = Object.values(s.by_day_off).reduce((a, d) => ((a[d.kind] = (a[d.kind] || 0) + 1), a), {});
  const seg = Object.entries(s.groups || {}).filter(([, g]) => g.runs).map(([k, g]) =>
    `<button data-group="${k}" class="${k === s.group ? "on" : ""}" aria-pressed="${k === s.group}">${GROUP_LABEL[k]} <span class="muted">${g.models}</span></button>`).join("");
  body.innerHTML = `
    <div class="seg" role="group" aria-label="Which models">${seg}</div>
    <div class="res-h"><h2>Measured: ${s.models} models · ${s.days} business days · ${s.scored_runs} runs · unguarded, then with Receipts</h2><span class="muted">cost at each provider's published price, read ${esc(s.prices_read_on)}</span></div>
    <div class="hero-pct"><div class="pct">${Number(o.harm_share_pct).toFixed(1)}%</div><div class="what">of every dollar an <b>unguarded</b> ${GROUP_WHO[s.group] || ""}AI agent sent <b>should never have left the business.</b><small>${money0(o.harm_money)} of ${money0(o.money_moved)} with nothing between the agent and PayPal · about 1 dollar in ${Math.round(o.one_dollar_in || 0)} · ${sn.share_of_all_harm_pct}% of it a bill paid twice</small></div></div>
    <div class="tiles">
      <div class="tile"><div class="k">With Receipts on</div><div class="v good-t">${usd(e.harm_money)}</div><div class="s">left wrongly on the same ${e.trap_days} trap days, measured the same way</div></div>
      <div class="tile"><div class="k">Honest work, untouched</div><div class="v">${pct(e.legit_done, e.legit_expected)}</div><div class="s">${e.legit_done} of ${e.legit_expected} honest payments and refunds went straight to PayPal; ${e.false_stops} wrongly stopped</div></div>
      <div class="tile"><div class="k">Crossed in the mail</div><div class="v bad-t">${pct(cr.paid_twice, cr.runs)}</div><div class="s">of runs paid Maya twice (${cr.paid_twice} of ${cr.runs}); ${pct(cr.paid_twice_after_checking_paypal, cr.paid_twice)} of those had checked PayPal first, for completed payments only. Every run that asked for pending found hers.</div></div>
      <div class="tile"><div class="k">Models that paid a bill twice</div><div class="v bad-t">${pct(modelsPaidTwice, s.models)}</div><div class="s">${modelsPaidTwice} of ${s.models} models, at least once across the ${sn.days} second-notice days, Receipts off</div></div>
      <div class="tile"><div class="k">Report vs PayPal</div><div class="v">${o.report_mismatch + e.report_mismatch}</div><div class="s">end-of-day reports claiming money that never moved</div></div>
      <div class="tile"><div class="k">Judge model</div><div class="v">None</div><div class="s">verdicts are plain rules on the call, the records and PayPal; harm is a fixed definition per day, written apart from the rules</div></div>
    </div>
    <div class="card viz-card">
      <h3>Does a dearer model lose less? What each model cost for the ${s.days} days, against what it lost, unguarded</h3>
      ${FR.size && s.group === "all" ? `<div class="legend"><span><i class="sw open"></i>Open models (one flat price on Vultr)</span><span><i class="sw fr"></i>Frontier models (Anthropic, OpenAI, xAI)</span></div>` : ""}
      <div id="costChart" class="viz-root"></div>
      <p class="method">One dot per model. Across: what the business paid the model to work the ${s.days} days, at the provider's published price (log scale). Up: money that left wrongly. The dashed line is the same ${s.days} days with Receipts on: $0.00 for every model. Hover a dot for the detail; the table below has every number.</p>
    </div>
    ${s.prompt_fix ? promptFixHtml(s.prompt_fix) : ""}
    <h3 class="sub">Per model</h3>
    <div id="modelGrid" class="ag-theme-quartz"></div>
    <h3 class="sub">Per day, Receipts off</h3>
    <div id="dayGrid" class="ag-theme-quartz"></div>
    <p class="method">Each model worked each day in two arms: Receipts off (every call went to PayPal; Receipts recorded what it would have done) and Receipts on. ${kinds.trap || 0} days carry a trap, ${sn.days} of them a bill that could be paid twice; ${kinds.control || 0} are honest days, including a bill that really is overdue and a payment that really bounced. Two runs per model, day and arm is presence, not frequency.</p>`;
  body.querySelectorAll(".seg button").forEach((b) => b.addEventListener("click", () => loadResults(b.dataset.group)));
  const rows = Object.entries(s.by_model_off).map(([m, d]) => ({ model: m, group: FR.has(m) ? "frontier" : "open", ...d, on: s.by_model_on[m] || {} }));
  drawCostChart($("#costChart"), rows, s.days);
  MGRID = agGrid.createGrid($("#modelGrid"), {
    rowData: rows,
    columnDefs: [
      { field: "model", width: 250, pinned: "left" },
      { field: "group", width: 110, filter: true },
      { field: "provider", width: 110, filter: true },
      { headerName: "$ / M tokens in · out", width: 170, valueGetter: (p) => `${p.data.price_in} · ${p.data.price_out}`, type: "rightAligned" },
      { field: "cost_per_agent_run_usd", headerName: `Cost for ${s.days} days`, width: 150, valueFormatter: (p) => "$" + (p.value || 0).toFixed(2), type: "rightAligned", sort: "asc" },
      { field: "harm_money", headerName: "Left wrongly (off)", width: 160, valueFormatter: (p) => usd(p.value), type: "rightAligned" },
      { field: "harm_share_pct", headerName: "Share of what it sent", width: 170, valueFormatter: (p) => p.value + "%", type: "rightAligned" },
      { headerName: "Trap days fell (off)", width: 160, valueGetter: (p) => `${p.data.trap_days_harm} / ${p.data.trap_days}`, type: "rightAligned" },
      { field: "paid_twice", headerName: "Paid a bill twice", width: 150, type: "rightAligned" },
      { headerName: "Left wrongly (on)", width: 150, valueGetter: (p) => usd(p.data.on.harm_money || 0), type: "rightAligned" },
      { headerName: "Honest work (off)", width: 150, valueGetter: (p) => `${p.data.legit_done} / ${p.data.legit_expected}`, type: "rightAligned" },
      { headerName: "Honest work (on)", width: 150, valueGetter: (p) => `${p.data.on.legit_done ?? "–"} / ${p.data.on.legit_expected ?? "–"}`, type: "rightAligned" },
      { field: "report_mismatch", headerName: "Report ≠ PayPal", width: 140, type: "rightAligned" },
    ],
    defaultColDef: { sortable: true, resizable: true },
  });
  const drows = Object.entries(s.by_day_off).map(([d, v]) => ({ day: DAY_TITLE[d] || d, id: d, ...v, on: s.by_day_on[d] || {} }));
  DGRID = agGrid.createGrid($("#dayGrid"), {
    rowData: drows,
    columnDefs: [
      { field: "day", width: 240, pinned: "left" },
      { field: "kind", width: 100, filter: true },
      { headerName: "Runs that fell", width: 140, valueGetter: (p) => `${p.data.fell} / ${p.data.runs}`, type: "rightAligned" },
      { field: "models_fell", headerName: "Models that fell", width: 150, type: "rightAligned" },
      { field: "harm_money", headerName: "Left wrongly (off)", width: 160, valueFormatter: (p) => usd(p.value), type: "rightAligned", sort: "desc" },
      { field: "money_moved", headerName: "Money sent (off)", width: 150, valueFormatter: (p) => usd(p.value), type: "rightAligned" },
      { headerName: "Left wrongly (on)", width: 150, valueGetter: (p) => usd(p.data.on.harm_money || 0), type: "rightAligned" },
      { headerName: "Honest work (off)", width: 150, valueGetter: (p) => `${p.data.legit_done} / ${p.data.legit_expected}`, type: "rightAligned" },
      { headerName: "Honest work (on)", width: 150, valueGetter: (p) => `${p.data.on.legit_done ?? "–"} / ${p.data.on.legit_expected ?? "–"}`, type: "rightAligned" },
      { headerName: "Wrongly stopped (on)", width: 170, valueGetter: (p) => p.data.on.false_stops ?? 0, type: "rightAligned" },
    ],
    defaultColDef: { sortable: true, resizable: true },
  });
}

/* the control for "why not just tell the agent?": the same days, one extra line in the owner's rules, Receipts off */
const pct = (a, b) => (b ? Math.round((100 * a) / b) + "%" : "–");
const pct1 = (a, b) => (b ? ((100 * a) / b).toFixed(1).replace(/\.0$/, "") + "%" : "–");
function promptFixHtml(pf) {
  const b = pf.before, a = pf.after;
  const rows = Object.entries(pf.by_day).map(([d, v]) => `<tr><td>${esc(DAY_TITLE[d] || d)}</td><td>${v.before.fell} / ${v.before.runs}</td><td>${v.after.fell} / ${v.after.runs}</td><td>${usd(v.before.harm_money)}</td><td>${usd(v.after.harm_money)}</td><td>${v.before.legit_done} / ${v.before.legit_expected}</td><td>${v.after.legit_done} / ${v.after.legit_expected}</td></tr>`).join("");
  return `<div class="card viz-card"><h3>Why not just tell the agent? We tried. One extra line in the owner's rules, same days, Receipts off.</h3>
    <p class="method">The line: <q>${esc(pf.line || "")}</q>. ${pf.models} models, ${pf.runs} runs. It cut duplicate payments by <b>${b.fell ? Math.round(100 * (b.fell - a.fell) / b.fell) : 0}%</b>: <b>${pct1(b.fell, b.runs)}</b> of runs paid a bill twice before (${b.fell} of ${b.runs}), <b>${pct1(a.fell, a.runs)}</b> after (${a.fell} of ${a.runs}); with Receipts on the same days, <b>0%</b>. Money sent wrongly: ${usd(b.harm_money)} before, ${usd(a.harm_money)} after. Models the line fixed: ${pf.models_fixed.length ? pf.models_fixed.map(esc).join(", ") : "none"}. Still paying twice: ${pf.models_still_paying_twice.length ? pf.models_still_paying_twice.map(esc).join(", ") : "none"}.</p>
    <table class="plain"><thead><tr><th>Day</th><th>Fell before</th><th>Fell after</th><th>Sent wrongly before</th><th>after</th><th>Honest work before</th><th>after</th></tr></thead><tbody>${rows}</tbody></table>
    <p class="method">A prompt is advice the agent may or may not follow, and the owner cannot audit it; Receipts enforces the same check in code, whatever the agent was told.</p></div>`;
}

/* cost against harm: one dot per model, hand-drawn SVG, hover tooltip, table below carries every number */
function drawCostChart(el, rows, days) {
  const pts = rows.filter((r) => r.cost_per_agent_run_usd > 0);
  if (!pts.length) { el.innerHTML = `<div class="muted">No cost data yet.</div>`; return; }
  const W = 960, H = 400, L = 78, R = 24, T = 24, B = 56;
  const xs = pts.map((p) => p.cost_per_agent_run_usd), ys = pts.map((p) => p.harm_money);
  const xmin = Math.min(...xs) / 1.6, xmax = Math.max(...xs) * 1.6, ymax = Math.max(1000, Math.max(...ys) * 1.12);
  const X = (v) => L + ((Math.log10(v) - Math.log10(xmin)) / (Math.log10(xmax) - Math.log10(xmin))) * (W - L - R);
  const Y = (v) => T + (1 - v / ymax) * (H - T - B);
  const xt = [0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50, 100].filter((v) => v >= xmin && v <= xmax);
  const yStep = ymax > 40000 ? 10000 : ymax > 16000 ? 5000 : ymax > 8000 ? 2000 : 1000;
  const yt = []; for (let v = 0; v <= ymax; v += yStep) yt.push(v);
  let g = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Cost per ${days} days against money lost, one dot per model">`;
  yt.forEach((v) => { g += `<line class="grid" x1="${L}" x2="${W - R}" y1="${Y(v)}" y2="${Y(v)}"/><text class="tick" x="${L - 10}" y="${Y(v) + 4}" text-anchor="end">${money0(v)}</text>`; });
  xt.forEach((v) => { g += `<text class="tick" x="${X(v)}" y="${H - B + 22}" text-anchor="middle">$${v}</text>`; });
  g += `<line class="axis" x1="${L}" x2="${W - R}" y1="${Y(0)}" y2="${Y(0)}"/>`;
  g += `<line class="zero" x1="${L}" x2="${W - R}" y1="${Y(0) - 1.5}" y2="${Y(0) - 1.5}"/><text class="zero-l" x="${L + 8}" y="${Y(0) - 10}" text-anchor="start">With Receipts on: $0.00 for every model</text>`;
  g += `<text class="axis-l" x="${L + (W - L - R) / 2}" y="${H - 10}" text-anchor="middle">What the model cost for the ${days} days (log scale)</text>`;
  g += `<text class="axis-l" transform="translate(16 ${T + (H - T - B) / 2}) rotate(-90)" text-anchor="middle">Money that left wrongly, unguarded</text>`;
  // labelled: the three that lost most, the dearest model, and the dearest model that still lost money
  const dear = [...pts].sort((a, b) => b.cost_per_agent_run_usd - a.cost_per_agent_run_usd);
  const labelled = [...pts].sort((a, b) => b.harm_money - a.harm_money).slice(0, 3).concat(
    dear.slice(0, 1), dear.filter((p) => p.harm_money > 0).slice(0, 1));
  pts.forEach((p, i) => {
    const cx = X(p.cost_per_agent_run_usd), cy = Y(p.harm_money);
    g += `<g class="dot ${p.group === "frontier" ? "fr" : "open"}" data-i="${i}"><circle class="hit" cx="${cx}" cy="${cy}" r="16"/><circle class="mark" cx="${cx}" cy="${cy}" r="6"/>`;
    if (labelled.includes(p)) g += `<text class="dl" x="${cx + 10}" y="${p.harm_money > 0 ? cy - 8 : cy + 20}">${esc(p.model.replace(/-[0-9a-z]{2,}-[0-9a-z-]+reasoning$/, ""))}</text>`;
    g += `</g>`;
  });
  g += `</svg><div class="tip" hidden></div>`;
  el.innerHTML = g;
  const tip = el.querySelector(".tip");
  el.querySelectorAll(".dot").forEach((d) => {
    const p = pts[+d.dataset.i];
    d.addEventListener("mouseenter", (ev) => {
      tip.innerHTML = `<b>${esc(p.model)}</b> · ${esc(p.provider)} · ${p.group === "frontier" ? "frontier" : "open"} model<br>$${p.price_in} in · $${p.price_out} out per M tokens<br>cost for ${days} days: <b>$${p.cost_per_agent_run_usd.toFixed(2)}</b><br>left wrongly: <b>${usd(p.harm_money)}</b> (${p.harm_share_pct}% of what it sent)<br>trap days fell: ${p.trap_days_harm} of ${p.trap_days} · paid a bill twice: ${p.paid_twice}<br>honest work: ${p.legit_done}/${p.legit_expected} off · ${p.on.legit_done ?? "–"}/${p.on.legit_expected ?? "–"} on`;
      tip.hidden = false;
    });
    d.addEventListener("mousemove", (ev) => { const r = el.getBoundingClientRect(); tip.style.left = Math.min(ev.clientX - r.left + 14, r.width - 330) + "px"; tip.style.top = (ev.clientY - r.top + 14) + "px"; });
    d.addEventListener("mouseleave", () => (tip.hidden = true));
  });
}

boot();
