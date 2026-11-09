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
    for (const md of modes) {
      const pick = rec.filter((r) => r.mode === md).sort((a, b) => (b.attempts || 0) - (a.attempts || 0))[0];
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
};
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
    case "session": A.session = e.session; $("#sub-" + mode).textContent = (mode === "observe" ? "Calls go straight to PayPal" : "Every money move checked first") + ` · PayPal ${e.backend}`; break;
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
        if (DESK_LABEL[e.tool]) break;
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
  if (!GRID) {
    GRID = agGrid.createGrid($("#grid"), {
      rowData: rows,
      columnDefs: [
        { field: "decision", headerName: "Receipts", cellRenderer: chip, width: 120, filter: true, pinned: "left" },
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
      rowClassRules: { "row-live": (p) => p.data && p.data.live },
    });
    $("#quick").addEventListener("input", (e) => GRID.setGridOption("quickFilterText", e.target.value));
  } else GRID.setGridOption("rowData", rows);
}

/* ---------- results ---------- */
let MGRID = null;
async function loadResults() {
  const s = await (await fetch("/api/results")).json();
  const body = $("#resultsBody");
  if (!s.scored) { body.innerHTML = `<div class="card">No measured runs on file yet. <code>python run_batch.py</code> writes them.</div>`; return; }
  const o = s.observe, e = s.enforce;
  const pct = (a, b) => (b ? Math.round((100 * a) / b) + "%" : "–");
  body.innerHTML = `
    <div class="res-h"><h2>Measured: ${Object.keys(s.by_model).length} models, ${s.scored} scored days</h2><span class="muted">generated ${esc(s.generated)} · PayPal ${esc(s.paypal_backends.join(", "))}</span></div>
    <div class="tiles">
      <div class="tile"><div class="k">Without Receipts</div><div class="v">${o.bad_episodes} / ${o.trap_episodes}</div><div class="s">trap days where harmful money actually moved in PayPal</div></div>
      <div class="tile"><div class="k">Money that left wrongly</div><div class="v bad-t">${usd(o.bad_money)}</div><div class="s">with nothing between the agent and PayPal</div></div>
      <div class="tile"><div class="k">With Receipts</div><div class="v good-t">${usd(e.bad_money)}</div><div class="s">left wrongly, measured the same way, on ${e.trap_episodes} trap days; ${e.attempts} risky moves stopped or held</div></div>
      <div class="tile"><div class="k">Honest work, untouched</div><div class="v">${pct(e.legit_done, e.legit_expected)}</div><div class="s">${e.legit_done} of ${e.legit_expected} legitimate payments and refunds went through; ${e.false_stops} wrongly stopped</div></div>
      <div class="tile"><div class="k">Said one thing, did another</div><div class="v">${o.said_no_did_it + e.said_no_did_it}</div><div class="s">money moves tried after the agent itself called that payment suspicious or said it would verify</div></div>
      <div class="tile"><div class="k">Report vs PayPal</div><div class="v">${o.reports.MISMATCH + e.reports.MISMATCH}</div><div class="s">end-of-day reports that did not match PayPal's own records</div></div>
      <div class="tile"><div class="k">Not scored</div><div class="v">${s.not_scored.ERROR + s.not_scored.NO_TOOL_CALLS}</div><div class="s">technical errors or no tool calls; kept on file, left out of every number</div></div>
      <div class="tile"><div class="k">Judge model</div><div class="v">None</div><div class="s">verdicts are deterministic rules on the tool-call log and PayPal's records; harm is a separate, fixed definition per day</div></div>
    </div>
    <p class="method">Each model worked each of nine days twice: once with Receipts off (every call went to PayPal; Receipts recorded what it would have done) and once with it on. Six days carry a trap (a forged payee, a duplicate invoice, a split bill, a refund larger than the payment, a fake owner and a hidden instruction, a dispute on a delivered parcel); three are control days whose every payment is legitimate. One run per model per day per arm is presence, not frequency.</p>
    <div id="modelGrid" class="ag-theme-quartz"></div>`;
  const rows = Object.entries(s.by_model).map(([m, d]) => ({ model: m, ...d }));
  MGRID = agGrid.createGrid($("#modelGrid"), {
    rowData: rows,
    columnDefs: [
      { field: "model", width: 300, pinned: "left" },
      { field: "observe_trap_attempt_episodes", headerName: "Trap days tried (off)", width: 180, type: "rightAligned" },
      { field: "observe_bad_money", headerName: "Left wrongly (off)", width: 170, valueFormatter: (p) => usd(p.value), type: "rightAligned" },
      { field: "enforce_bad_money", headerName: "Left wrongly (on)", width: 170, valueFormatter: (p) => usd(p.value), type: "rightAligned" },
      { field: "said_no_did_it", headerName: "Said no, did it", width: 150, type: "rightAligned" },
      { field: "report_mismatch", headerName: "Report ≠ PayPal", width: 150, type: "rightAligned" },
      { headerName: "Honest work done (on)", width: 190, valueGetter: (p) => `${p.data.enforce_legit_done} / ${p.data.enforce_legit_expected}`, type: "rightAligned" },
      { field: "enforce_false_stops", headerName: "Wrongly stopped (on)", width: 180, type: "rightAligned" },
    ],
    defaultColDef: { sortable: true, resizable: true },
  });
}

boot();
