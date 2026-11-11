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
  history.replaceState(null, "", location.search + "#" + t);
  window.scrollTo(0, 0);                       // a new tab opens at its top, not at the last tab's scroll position
}

/* ---------- boot ---------- */
async function boot() {
  const m = await (await fetch("/api/meta")).json();
  Object.assign(META, m);
  $("#scn").innerHTML = m.scenarios.map((s) => `<option value="${s.id}">${esc(s.title)}${s.kind === "control" ? "" : ""}</option>`).join("");
  // every measured model can be replayed: the twelve open ones, then the seven frontier ones, under their own headings
  const opt = (x) => `<option>${esc(x)}</option>`;
  const fr = m.frontier_models || [];
  $("#model").innerHTML = fr.length
    ? `<optgroup label="Open models (${m.models.length})">${m.models.map(opt).join("")}</optgroup><optgroup label="Frontier models (${fr.length})">${fr.map(opt).join("")}</optgroup>`
    : m.models.map(opt).join("");
  $("#env").textContent = m.paypal_mode === "sandbox" ? "PayPal sandbox · live" : "PayPal stand-in (no keys)";
  $("#env").title = m.paypal_mode === "sandbox" ? "Every allowed money move goes to PayPal's sandbox now."
    : "PayPal's tools and records, mirrored in memory, so anyone can try it without a PayPal account. With two sandbox keys the same runs go to PayPal's real sandbox (see the README).";
  if (m.paypal_mode !== "sandbox") $("#source").querySelector('[value="recorded"]').textContent = "Recorded real run (replayed through Receipts now)";
  if (!m.live_allowed) {
    const live = $("#source").querySelector('[value="live"]');
    live.disabled = true; live.textContent = "Live model run (off on this demo)";
  }
  const note = async () => {
    const s = m.scenarios.find((x) => x.id === $("#scn").value);
    $("#scnNote").textContent = s ? (s.kind === "control" ? "Control day: " : "Today: ") + s.pressure + "." : "";
    const want = $("#scn").value;
    const ib = await (await fetch("/api/inbox?scenario=" + encodeURIComponent(want))).json();
    if (want !== $("#scn").value) return;          // a later choice won the race
    $("#inbox").innerHTML = (ib.messages || []).map((x) => `<div class="mail"><div class="from">${esc(x.from)}</div><div class="subj">${esc(x.subject)}</div><div class="body">${esc(x.body)}</div></div>`).join("");
    $("#inbox").querySelectorAll(".mail").forEach((el) => el.addEventListener("click", () => el.classList.toggle("open")));
  };
  $("#scn").addEventListener("change", note);
  $("#sbs").addEventListener("change", () => $("#arms").classList.toggle("single", !$("#sbs").checked));
  $("#every").addEventListener("change", () => $("#arms").classList.toggle("every", $("#every").checked));
  $("#source").addEventListener("change", () => ($("#runNote").textContent = $("#source").value === "live"
    ? "A new run: the AI works the day live, right now." : "A real recorded run, replayed through Receipts now."));
  $("#arms").addEventListener("click", (ev) => { const b = ev.target.closest(".bubble"); if (b) b.classList.toggle("open"); });
  $("#go").addEventListener("click", runDay);
  if (new URLSearchParams(location.search).get("clean") === "1") $("#howto").classList.add("gone");
  try { if (localStorage.getItem("howto-gone") === "1") $("#howto").classList.add("gone"); } catch {}
  $("#howtoX").addEventListener("click", () => { $("#howto").classList.add("gone"); try { localStorage.setItem("howto-gone", "1"); } catch {} });
  const params = new URLSearchParams(location.search);
  // With no link parameters the page opens on Maya's Tuesday with a model that paid her twice, the story the video tells;
  // every other day and model stays in the two menus. An unknown value in a link is ignored rather than blanking the menu.
  const choose = (sel, want) => { if ([...sel.options].some((o) => o.value === want)) sel.value = want; };
  choose($("#scn"), params.get("scenario") || "S14_crossed_in_the_mail");
  choose($("#model"), params.get("model") || "glm-5.3");
  note();
  if (params.get("theme")) document.documentElement.dataset.theme = params.get("theme");
  if (params.get("sbs") === "0") { $("#sbs").checked = false; $("#arms").classList.add("single"); }
  if (params.get("every") === "1") { $("#every").checked = true; $("#arms").classList.add("every"); }
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
  $("#outcome").hidden = true;
  const s3 = $("#step3").getBoundingClientRect();           // bring the two sides into view as they start to fill
  if (s3.top > innerHeight * 0.55) window.scrollTo({ top: scrollY + s3.top - 80, behavior: "smooth" });
  Object.values(ARMS).forEach((a) => a.es && a.es.close());
  GONE = []; drawHolds();                      // a new run: the "expired" notes from before have done their job
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
    let ended = false;
    const end = () => {
      if (ended) return;
      ended = true; es.close();
      if (--open <= 0) { $("#go").disabled = false; showOutcome(modes); }
    };
    es.onmessage = (m) => {
      const e = JSON.parse(m.data);
      render(md, e);
      if (e.type === "done") end();
    };
    es.onerror = end;
  }
}

/* After a run: the answer in one plain line, and the way to Maya's phone when something is waiting for her. */
async function showOutcome(modes) {
  const off = modes.includes("observe") ? ARMS.observe.lost : null;
  const on = modes.includes("enforce") ? ARMS.enforce.lost : 0;
  let html;
  if (!off && !on) html = `<span><b>No money left wrongly on either side today.</b></span>`;
  else html = (off === null ? "" : `<span>Without Receipts: <b class="${off ? "bad" : ""}">${off ? usd(off) + " left Maya's business wrongly." : "no money left wrongly."}</b></span>`)
    + `<span>With Receipts: <b class="${on ? "good" : ""}">${on ? usd(on) + " stopped before it reached PayPal." : "no money left wrongly."}</b></span>`;
  await pollHolds();
  const waiting = $("#holdCount").hidden ? 0 : Number($("#holdCount").textContent) || 0;
  const box = $("#outcome");
  box.innerHTML = html + (waiting ? `<button class="go" id="toPhone">Open Maya's phone (${waiting} waiting)</button>` : "");
  box.hidden = false;
  const tp = $("#toPhone");
  if (tp) tp.addEventListener("click", () => showTab("owner"));
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
// Why PayPal refused a send, in PayPal's own words (its error message, else its error name), kept short.
function ppWhy(err) {
  const said = err && typeof err === "object" ? (err.message || err.name || "") : (err || "");
  return said ? `: ${esc(String(said).slice(0, 160))}` : "";
}
function txnSummary(args, r) {
  const st = (args && args.transaction_status) || "S";
  const rows = (r && r.transaction_details) || [];
  const invs = rows.map((x) => (x.transaction_info || {}).invoice_id).filter(Boolean);
  const dflt = args && args.transaction_status ? "" : " (the tool's default)";
  return `<b>Checked PayPal</b> · list_transactions · showing <b>${TS_WORD[st] || st}</b> payments only${dflt} · ${rows.length} found${invs.length ? ": " + invs.slice(-6).join(", ") : ""}`;
}
const MONEY = new Set(["create_payout", "create_refund", "accept_dispute_claim", "update_vendor_payee"]);
const MINOR = new Set(["read_inbox", "list_vendors", "payments_book"]);   // housekeeping steps the plain view leaves out

function moneyTitle(v) {
  const a = v.args || {};
  if (v.tool === "create_payout") return [`Pay ${a.vendor || "?"} ${usd(a.amount)}`, `to ${a.receiver_email} · ${a.invoice_number || ""}`];
  if (v.tool === "create_refund") return [`Refund ${a.amount != null ? usd(a.amount) : "in full"}`, `PayPal capture ${a.capture_id}`];
  if (v.tool === "accept_dispute_claim") return [`Concede dispute ${usd(v.amount)}`, `PayPal dispute ${a.dispute_id}`];
  if (v.tool === "update_vendor_payee") return [`Change ${a.vendor}'s PayPal`, `to ${a.new_paypal_email}`];
  return [v.tool, ""];
}
const BADGE = { observe: { ALLOW: "RECEIPTS WOULD ALLOW", HOLD: "RECEIPTS WOULD HOLD", BLOCK: "RECEIPTS WOULD STOP" }, enforce: { ALLOW: "SENT TO PAYPAL", HOLD: "HELD FOR OWNER", BLOCK: "STOPPED" } };

function render(mode, e) {
  const A = ARMS[mode];
  switch (e.type) {
    case "session": A.session = e.session; $("#sub-" + mode).textContent = mode === "observe" ? "Nothing checks the AI's payments" : "Receipts checks PayPal before any money leaves";
      $("#sub-" + mode).title = `PayPal ${e.backend}`;
      if (e.note) add(mode, `<div class="replay-tag">${esc(e.note)}</div>`);
      break;
    case "replay": add(mode, `<div class="replay-tag">Replay of a recorded ${esc(e.model)} run (${esc((e.recorded_at || "").replace("T", " ").replace("Z", " UTC"))}). The agent's words and calls are the recorded ones; Receipts and PayPal are running now.</div>`); break;
    case "say":
      if (e.where !== "reply") break;
      A.said.push(e.text);
      add(mode, `<div class="say"><div class="avatar">AI</div><div class="bubble${e.text.length > 420 ? " long" : ""}">${e.marker ? `<span class="marker">SAID: ${e.marker === "REFUSED" ? "NO / SUSPICIOUS" : "WILL VERIFY / HOLD"}</span>` : ""}<div class="txt">${esc(cleanText(e.text))}</div></div></div>`);
      break;
    case "call":
      if (MONEY.has(e.tool) || e.tool === "finish") break;
      if (DESK_LABEL[e.tool]) add(mode, `<div class="act${MINOR.has(e.tool) ? " minor" : ""}">› <b>${esc(DESK_LABEL[e.tool](e.args || {}))}</b></div>`);
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
      if (obs && e.decision !== "ALLOW") { A.pendingBad = e.amount || 0; A.pendingTitle = t; }
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
      const lead = bad ? ["<b>Money moved</b>", title && esc(title)] : title ? (mode === "observe" ? [esc(title)] : ['<b class="cleared">Receipts: cleared</b>', esc(title)]) : ["Sent to PayPal"];
      const plain = lead.filter(Boolean).join(" · ");
      // PayPal can still say no to a move Receipts let through (in the sandbox: no play money left). Say so in PayPal's own words.
      const refused = ok ? "" : ` · <b class="pp-no">PayPal refused it</b>${ppWhy(r.error)}`;
      add(mode, `<div class="pp${bad ? " moved-bad" : ""}${ok ? "" : " refused"}"><span class="chk">${ok ? "✓" : "!"}</span><span>${plain}${refused}<span class="tech"> · PayPal ${esc(e.backend)} · ${esc(e.tool)} · ${esc(id)} · ${esc(status)}</span></span></div>`);
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
      if (o.class === "ERROR" || o.legit_expected === undefined) {
        add(mode, `<div class="done">The run stopped before the day was worked${e.error ? ": " + esc(String(e.error).slice(0, 160)) : ""}.</div>`);
        break;
      }
      add(mode, `<div class="done">Day finished${e.seconds ? " in " + e.seconds + "s" : ""}. Honest work done: ${o.legit_done ?? "?"} of ${o.legit_expected ?? "?"}. ${o.trap_attempts ? `Risky money moves tried: ${o.trap_attempts}.` : "No risky money move tried."}</div>`);
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
const LOGO = `<svg viewBox="0 0 100 100" aria-hidden="true"><rect width="100" height="100" rx="22" fill="#14213d"/><path d="M26 84V16h21c15 0 24 8 24 21s-9 21-24 21H26m17 0l30 26" fill="none" stroke="#fffdf8" stroke-width="13" stroke-linecap="round" stroke-linejoin="round"/><path d="M55 70l12 12 26-28" fill="none" stroke="#1f9d55" stroke-width="13" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
// A visitor's held payments live in the server's memory. When the server restarts, or a run is more than an hour
// old, they are gone from it: the card on the phone then says so in plain words instead of keeping buttons that do nothing.
const EXPIRED_TEXT = "This one has expired, because the demo restarted or it waited too long. Go back to Watch and press Run the day again.";
const NO_HOLDS = $("#holds").innerHTML;          // the phone with nothing on it, as the page ships it
const holdKey = (h) => h.session + "/" + h.id;
let SHOWN = [];                                  // the held payments the server lists for this visitor, as last heard
let GONE = [];                                   // ones that were waiting on the phone and are no longer on the server
let HOLDS_ASKED = 0, HOLDS_DRAWN = 0;            // answers are drawn in the order they were asked for, never an older one over a newer
function holdTitle(h) {
  const a = h.args || {};
  return h.tool === "create_payout" ? `Pay ${a.vendor}` : h.tool === "create_refund" ? "Refund a customer" : h.tool === "accept_dispute_claim" ? "Concede a dispute" : h.tool;
}
function holdCard(h) {
  return `<div class="hold"><div class="nt">${LOGO}<span>RECEIPTS</span><span class="when">${h.status === "WAITING" ? "needs you" : "done"}</span></div><div class="ttl">${esc(holdTitle(h))} · ${esc(h.scenario)}</div><div class="amt">${usd(h.amount)}</div><ul>${(h.why || []).map((w) => `<li>${esc(w)}</li>`).join("")}</ul>${h.status === "WAITING"
    ? `<div class="btns"><button class="approve" data-s="${h.session}" data-h="${h.id}">Approve</button><button class="decline" data-s="${h.session}" data-h="${h.id}">Decline</button></div>`
    : `<div class="state ${h.status}">${h.status === "APPROVED" ? `Approved · sent to PayPal ${esc((h.result || {}).backend || "")} · ${esc((h.result || {}).payout_batch_id || (h.result || {}).id || "")} · ${esc((h.result || {}).batch_status || (h.result || {}).status || "")}` : "Declined · never sent to PayPal"}</div>`}</div>`;
}
function expiredCard(h) {
  return `<div class="hold expired" role="status"><div class="nt">${LOGO}<span>RECEIPTS</span><span class="when">expired</span></div><div class="ttl">${esc(holdTitle(h))} · ${esc(h.scenario)}</div><div class="amt">${usd(h.amount)}</div><p class="gone">${EXPIRED_TEXT}</p><button class="to-watch">Back to Watch</button></div>`;
}
function expireHold(session, id) {
  const k = session + "/" + id;
  const h = SHOWN.find((x) => holdKey(x) === k);
  if (!h) return;
  SHOWN = SHOWN.filter((x) => x !== h);
  if (!GONE.some((g) => holdKey(g) === k)) GONE.push(h);
  drawHolds();
}
function drawHolds() {
  const isWaiting = (h) => h.status === "WAITING";
  const waiting = SHOWN.filter(isWaiting).length;
  $("#holdCount").hidden = !waiting; $("#holdCount").textContent = waiting;
  const box = $("#holds");
  const sig = JSON.stringify([SHOWN.map((h) => [h.session, h.id, h.status]), GONE.map(holdKey)]);
  if (sig === box.dataset.sig) return;          // unchanged: do not re-render (keeps the cards steady)
  box.dataset.sig = sig;
  if (!SHOWN.length && !GONE.length) { box.innerHTML = NO_HOLDS; return; }
  box.innerHTML = SHOWN.filter(isWaiting).map(holdCard).join("") + GONE.map(expiredCard).join("") + SHOWN.filter((h) => !isWaiting(h)).map(holdCard).join("");
  box.querySelectorAll(".to-watch").forEach((b) => b.addEventListener("click", () => showTab("live")));
  box.querySelectorAll(".btns button").forEach((b) => b.addEventListener("click", async () => {
    let res = null;
    try {
      res = await fetch(b.classList.contains("approve") ? "/api/approve" : "/api/decline", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ session: b.dataset.s, hold_id: b.dataset.h }) });
    } catch {}
    if (!res) {                                  // the tap never reached the server: say so, and leave the buttons to try again
      const card = b.closest(".hold");
      if (card && !card.querySelector(".retry")) card.insertAdjacentHTML("beforeend", `<p class="retry" role="status">That tap did not reach the demo. Check your connection and tap again.</p>`);
      return;
    }
    if (!res.ok) expireHold(b.dataset.s, b.dataset.h);      // the server no longer has this payment (404 after a restart)
    pollHolds();
  }));
}
async function pollHolds() {
  const asked = ++HOLDS_ASKED;
  let hs;
  try {
    const res = await fetch("/api/holds");
    if (!res.ok) return;
    hs = await res.json();
  } catch { return; }
  if (!Array.isArray(hs) || asked < HOLDS_DRAWN) return;
  HOLDS_DRAWN = asked;
  const here = new Set(hs.map(holdKey));
  // a payment that was waiting on the phone and is no longer on the server has expired; one the server still lists has not
  SHOWN.forEach((h) => { if (h.status === "WAITING" && !here.has(holdKey(h)) && !GONE.some((g) => holdKey(g) === holdKey(h))) GONE.push(h); });
  GONE = GONE.filter((g) => !here.has(holdKey(g)));
  // with nothing on the server, the cards already answered stay on the phone as they were (a record of the tap)
  SHOWN = hs.length ? hs : SHOWN.filter((h) => h.status !== "WAITING");
  drawHolds();
}

/* ---------- rules ---------- */
let DRAFT = null;
async function loadPolicy() {
  if (DRAFT) return;
  const p = await (await fetch("/api/policy")).json();
  $("#english").value = p.english;
  DRAFT = p; drawRules();
}
// who drafted the settings, in plain words (the API keeps its own value; "regex (offline fallback)" is the built-in reader)
function drafter(by) {
  if (!by) return "";
  if (/^regex/i.test(by)) return "Drafted by: the built-in reader (" + (META.live_allowed === false
    ? "AI drafting is switched off on this public demo" : "no AI model key on this copy, so AI drafting is off") + ")";
  if (by === "defaults") return "The rules Receipts starts with";
  if (by === "owner") return "Set by the owner";
  return "Drafted by: " + by;
}
function drawRules() {
  const p = DRAFT;
  $("#compiledBy").textContent = drafter(p.compiled_by);
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

/* ---------- ledger (AG Grid): Maya's book of every money move ---------- */
let GRID = null;
let LEDGER_VIEW = "all";
const chip = (p) => (p.node && p.node.rowPinned) ? `<b>${esc(p.value)}</b>` : (p.value ? `<span class="chip ${p.value}">${p.value}</span>` : "");
const codeSet = (r) => new Set(String(r.codes || "").split(",").map((c) => c.trim()).filter(Boolean));
const TWICE = ["ALREADY_PAID_IN_PAYPAL", "PAYMENT_IN_FLIGHT", "ALREADY_PAID_OUTSIDE_PAYPAL", "NEAR_DUPLICATE_BILL"];
const WORDS = ["APPROVAL_CLAIMED_NOT_ON_FILE", "CLAIMED_CHECK_NOT_IN_LOG"];
// one-tap views: AG Grid's external filter, on top of the column filters and the search box
const VIEWS = {
  all: () => true,
  held: (r) => r.decision === "HOLD",
  stopped: (r) => r.decision === "BLOCK",
  twice: (r) => TWICE.some((c) => codeSet(r).has(c)),
  words: (r) => r.said_first || WORDS.some((c) => codeSet(r).has(c)),
};
const VIEW_NAME = { all: "everything", held: "held-for-maya", stopped: "stopped", twice: "would-have-paid-twice", words: "agents-words" };
// plain words on screen and in the accountant's download (the family test, 2026-11-10); the raw codes stay in the data
const TOOL_LABEL = { create_payout: "Pay a supplier", create_refund: "Refund a customer", update_vendor_payee: "Change where a supplier is paid",
  accept_dispute_claim: "Concede a dispute" };
const CODE_LABEL = { PAYEE_NOT_ON_RECORD: "Payee not on record", ALREADY_PAID_IN_PAYPAL: "Already paid in PayPal",
  PAYMENT_IN_FLIGHT: "A payment already on its way", ALREADY_PAID_OUTSIDE_PAYPAL: "Paid outside PayPal (check or transfer)",
  NEAR_DUPLICATE_BILL: "Same bill, new number", REFUND_WHILE_DISPUTED: "Refund during an open dispute",
  REFUND_MORE_THAN_PAID: "Refund more than the customer paid", PAYEE_CHANGE_WITHOUT_CALLBACK: "Payee change without a call",
  OVER_OWNER_LIMIT: "Over the owner's limit", SPLIT_UNDER_LIMIT: "One bill split to slip under the limit",
  DELIVERED_PER_TRACKING: "Dispute on a delivered parcel", APPROVAL_CLAIMED_NOT_ON_FILE: "Claimed an approval that isn't on file",
  CLAIMED_CHECK_NOT_IN_LOG: "Claimed a phone check that isn't in the log", CALLBACK_SAID_NO: "The call said no",
  NO_SUCH_CAPTURE: "No such payment in PayPal", NO_SUCH_DISPUTE: "No such dispute in PayPal", UNKNOWN_VENDOR: "Unknown supplier" };
const codesPlain = (r) => [...codeSet(r)].map((c) => CODE_LABEL[c] || c).join("; ");
const dayTitle = (id) => ((META && META.scenarios || []).find((s) => s.id === id) || {}).title || id;

// the totals for exactly what is on screen: the summary strip and a pinned row under the grid
function ledgerTotals() {
  // with Receipts ON a HOLD waited for Maya and a BLOCK never left; with it OFF every move went to PayPal,
  // and HOLD/BLOCK only records what Receipts would have done
  const t = { n: 0, sent: 0, money: 0, held: 0, heldN: 0, stopped: 0, stoppedN: 0, through: 0, throughN: 0, models: new Set() };
  GRID.forEachNodeAfterFilter((node) => {
    const r = node.data; if (!r) return;
    const on = r.arm === "Receipts ON", amt = r.amount || 0;
    t.n++; t.money += amt; t.models.add(r.model);
    if (r.decision === "ALLOW" || !on) t.sent++;
    if (on && r.decision === "HOLD") { t.held += amt; t.heldN++; }
    if (on && r.decision === "BLOCK") { t.stopped += amt; t.stoppedN++; }
    if (!on && r.decision !== "ALLOW") { t.through += amt; t.throughN++; }
  });
  $("#ledgerSum").innerHTML = `<div class="s"><b>${t.n.toLocaleString("en-US")}</b>money moves, ${t.models.size} AI model${t.models.size === 1 ? "" : "s"}</div>`
    + `<div class="s"><b>${t.sent.toLocaleString("en-US")}</b>went to PayPal</div>`
    + `<div class="s good"><b>${usd(t.held)}</b>held for Maya (${t.heldN})</div>`
    + `<div class="s good"><b>${usd(t.stopped)}</b>stopped before PayPal (${t.stoppedN})</div>`
    + `<div class="s bad" title="With Receipts off nothing was checked. This adds up every move Receipts would have held or stopped, each at its full amount. It is more than the harm figure on the Results tab, which counts only money that wrongly left: for a split bill, only the part over the owner's limit, and nothing for a refund PayPal itself refused."><b>${usd(t.through)}</b>with Receipts off: moves it would have held or stopped (${t.throughN})</div>`;
  GRID.setGridOption("pinnedBottomRowData", [{ decision: `${t.n.toLocaleString("en-US")} moves`, amount: t.money,
    why: `With Receipts on: ${usd(t.held)} held for Maya, ${usd(t.stopped)} stopped before PayPal. With it off: ${usd(t.through)} in moves it would have held or stopped, each at its full amount.` }]);
}

async function loadLedger() {
  const rows = await (await fetch("/api/ledger")).json();
  if (!GRID) {
    GRID = agGrid.createGrid($("#grid"), {
      rowData: rows,
      columnDefs: [
        { field: "decision", headerName: "Receipts", cellRenderer: chip, width: 130, filter: true, pinned: "left", sort: "desc",
          comparator: (a, b) => ({ BLOCK: 2, HOLD: 1, ALLOW: 0 }[a] ?? -1) - ({ BLOCK: 2, HOLD: 1, ALLOW: 0 }[b] ?? -1) },
        { colId: "arm", headerName: "Run", width: 140, filter: true,
          valueGetter: (p) => (p.data && p.data.arm ? p.data.arm.replace("ON", "on").replace("OFF", "off") : "") },
        { field: "model", headerName: "AI model", width: 230, filter: true },
        { colId: "day", headerName: "Day", width: 230, filter: true, valueGetter: (p) => (p.data && p.data.scenario ? dayTitle(p.data.scenario) : "") },
        { colId: "action", headerName: "What the AI tried", width: 220, filter: true,
          valueGetter: (p) => (p.data && p.data.tool ? (TOOL_LABEL[p.data.tool] || p.data.tool) : "") },
        { field: "amount", width: 130, valueFormatter: (p) => usd(p.value), type: "rightAligned", filter: "agNumberColumnFilter" },
        { field: "ref", headerName: "Invoice or order", width: 200, filter: true },
        { field: "to", headerName: "Paid to", width: 240, filter: true },
        { colId: "rule", headerName: "Rule", width: 280, filter: true, tooltipValueGetter: (p) => p.data && p.data.codes,
          valueGetter: (p) => (p.data ? codesPlain(p.data) : "") },
        { field: "said_first", headerName: "Said no first", width: 130, cellRenderer: (p) => (p.value ? "⚠ yes" : "") },
        { field: "why", headerName: "Why (built from PayPal and the records)", flex: 1, minWidth: 380, tooltipField: "why", filter: true },
        { field: "paypal_id", headerName: "PayPal id", width: 170 },
        { field: "backend", headerName: "PayPal", width: 110, filter: true, valueFormatter: (p) => (p.value === "standin" ? "stand-in" : p.value || "") },
      ],
      defaultColDef: { sortable: true, resizable: true, floatingFilter: true, suppressHeaderMenuButton: true },
      animateRows: true,
      pagination: true, paginationPageSize: 50,
      tooltipShowDelay: 300,
      isExternalFilterPresent: () => LEDGER_VIEW !== "all",
      doesExternalFilterPass: (node) => VIEWS[LEDGER_VIEW](node.data),
      onFilterChanged: ledgerTotals,
      onRowDataUpdated: ledgerTotals,
      getRowClass: (p) => (p.node.rowPinned ? "r-total" : ""),
      rowClassRules: { "row-live": (p) => p.data && p.data.live, "r-BLOCK": (p) => p.data && p.data.decision === "BLOCK",
                       "r-HOLD": (p) => p.data && p.data.decision === "HOLD", "r-ALLOW": (p) => p.data && p.data.decision === "ALLOW" },
    });
    $("#quick").addEventListener("input", (e) => GRID.setGridOption("quickFilterText", e.target.value));
    $("#ledgerViews").querySelectorAll("button").forEach((b) => b.addEventListener("click", () => {
      LEDGER_VIEW = b.dataset.view;
      $("#ledgerViews").querySelectorAll("button").forEach((x) => { x.classList.toggle("on", x === b); x.setAttribute("aria-pressed", x === b); });
      GRID.onFilterChanged();
    }));
    // a spreadsheet of exactly what is on screen (views, column filters and search applied), every reason included
    $("#exportCsv").addEventListener("click", () => GRID.exportDataAsCsv({
      fileName: `receipts_${VIEW_NAME[LEDGER_VIEW]}_${new Date().toISOString().slice(0, 10)}.csv`,
      skipPinnedBottom: true,
      processCellCallback: (p) => (p.column.getColId() === "said_first" ? (p.value ? "yes" : "") : p.value),
    }));
    ledgerTotals();
  } else GRID.setGridOption("rowData", rows);
}

/* ---------- results ---------- */
let MGRID = null, DGRID = null;
const money0 = (x) => "$" + Math.round(x || 0).toLocaleString("en-US");
const num = (x) => Number(x || 0).toLocaleString("en-US");          // 1,444 not 1444
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
    <div class="res-h"><h2>Measured: ${s.models} models · ${s.days} business days · ${num(s.scored_runs)} runs · unguarded, then with Receipts</h2><span class="muted">cost at each provider's published price, read ${esc(s.prices_read_on)}</span></div>
    <div class="hero-pct"><div class="pct">${Number(o.harm_share_pct).toFixed(1)}%</div><div class="what">of every dollar an <b>unguarded</b> ${GROUP_WHO[s.group] || ""}AI agent sent <b>should never have left the business.</b><small>${money0(o.harm_money)} of ${money0(o.money_moved)} with nothing between the agent and PayPal · about 1 dollar in ${Math.round(o.one_dollar_in || 0)} · ${sn.share_of_all_harm_pct}% of it a bill paid twice</small></div></div>
    <div class="tiles">
      <div class="tile"><div class="k">With Receipts on</div><div class="v good-t">${usd(e.harm_money)}</div><div class="s">left wrongly on the same ${e.trap_days} trap days, measured the same way</div></div>
      <div class="tile"><div class="k">Honest work, untouched</div><div class="v">${pct(e.legit_done, e.legit_expected)}</div><div class="s">${num(e.legit_done)} of ${num(e.legit_expected)} honest payments and refunds went straight to PayPal; ${e.false_stops} wrongly stopped</div></div>
      <div class="tile"><div class="k">Crossed in the mail</div><div class="v bad-t">${pct(cr.paid_twice, cr.runs)}</div><div class="s">of runs paid Maya twice (${cr.paid_twice} of ${cr.runs}); ${pct(cr.paid_twice_after_checking_paypal, cr.paid_twice)} of those had checked PayPal first, for completed payments only. Every run that asked for pending found hers.</div></div>
      <div class="tile"><div class="k">Models that paid a bill twice</div><div class="v bad-t">${pct(modelsPaidTwice, s.models)}</div><div class="s">${modelsPaidTwice} of ${s.models} models, at least once across the ${sn.days} second-notice days, Receipts off</div></div>
      <div class="tile"><div class="k">Report vs PayPal</div><div class="v">${o.report_mismatch + e.report_mismatch}</div><div class="s">end-of-day reports claiming money that never moved</div></div>
      <div class="tile"><div class="k">Judge model</div><div class="v">None</div><div class="s">verdicts are plain rules on the call, the records and PayPal; harm is a fixed definition per day, written apart from the rules</div></div>
    </div>
    <div class="card viz-card">
      <h3>Does a pricier model lose less? What each model cost for the ${s.days} days, against what it lost, unguarded</h3>
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
    <p class="method">The line: <q>${esc((pf.line || "").replace(/\.\s*$/, ""))}</q>. ${pf.models} models, ${num(pf.runs)} runs. It cut duplicate payments by <b>${b.fell ? Math.round(100 * (b.fell - a.fell) / b.fell) : 0}%</b>: <b>${pct1(b.fell, b.runs)}</b> of runs paid a bill twice before (${b.fell} of ${b.runs}), <b>${pct1(a.fell, a.runs)}</b> after (${a.fell} of ${a.runs}); with Receipts on the same days, <b>0%</b>. Money sent wrongly: ${usd(b.harm_money)} before, ${usd(a.harm_money)} after. Models the line fixed: ${pf.models_fixed.length ? pf.models_fixed.map(esc).join(", ") : "none"}. Still paying twice: ${pf.models_still_paying_twice.length ? pf.models_still_paying_twice.map(esc).join(", ") : "none"}.</p>
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
  // labeled: the three that lost most, the priciest model, and the priciest model that still lost money
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
