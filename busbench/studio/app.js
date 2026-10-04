/* BusBench Studio - one page per module, all driven through the local REST API. */
"use strict";

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
let LAST_CALL = null;

async function api(name, body = {}) {
  LAST_CALL = { name, body };
  const r = await fetch(`/api/${name}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const j = await r.json();
  if (!r.ok) throw new Error(j.error || r.statusText);
  return j;
}
const fmt = (v, d = 4) => (v == null ? "—" : Number.isInteger(v) ? String(v) : (+v.toPrecision(d)).toString());
const bytesOf = (hex) => (hex || "").split(" ").filter(Boolean);

/* ------------------------------------------------------------ bit ribbon */
/* cells: [{v, k}] left to right; fields: [{name, n, k}] spans in cells; idx: labels above */
function ribbon(cells, fields = [], { idx = null, bytes = false, title = "" } = {}) {
  const n = cells.length;
  const cell = bytes ? (n > 36 ? 18 : n > 20 ? 21 : n > 12 ? 25 : 30) : (n > 24 ? 17 : 22);
  return `<div class="ribbon${bytes ? " bytes" : ""}${cell < 20 ? " tiny" : ""}" style="--cell:${cell}px" ${title ? `title="${esc(title)}"` : ""}>
    ${idx ? `<div class="idx">${idx.map((i) => `<span>${i}</span>`).join("")}</div>` : ""}
    <div class="cells">${cells.map((c) => `<span class="k-${c.k}${c.v === "0" ? " b0" : ""}">${esc(c.v)}</span>`).join("")}</div>
    ${fields.length ? `<div class="fields">${fields.map((f) => `<span class="k-${f.k}" style="grid-column: span ${f.n}" title="${esc(f.name)}">${esc(f.name)}</span>`).join("")}</div>` : ""}
  </div>`;
}
function bitsRibbon(bits, layout, numbering) {
  const cells = [], fields = [];
  let i = 0;
  for (const [name, n, k] of layout) {
    for (let j = 0; j < n; j++) cells.push({ v: bits[i + j], k });
    fields.push({ name, n, k });
    i += n;
  }
  return ribbon(cells, fields, { idx: numbering });
}
function bytesRibbon(hex, layout) {   // layout: [[name, nBytes|"rest", k]]
  const b = bytesOf(hex), cells = [], fields = [];
  let i = 0;
  for (const [name, n0, k] of layout) {
    const n = n0 === "rest" ? b.length - i : Math.min(n0, b.length - i);
    if (n <= 0) continue;
    for (let j = 0; j < n; j++) cells.push({ v: b[i + j], k });
    fields.push({ name, n, k });
    i += n;
  }
  return ribbon(cells, fields, { bytes: true });
}
const ISOTP_K = { SF: "ctrl", FF: "id", CF: "data", FC: "status" };
function isotpRibbon(kind, hex) {
  const b = bytesOf(hex);
  const pci = b[0] || "00";
  const cells = [{ v: pci[0], k: "ctrl" }, { v: pci[1], k: "status" }];
  const fields = [{ name: "type", n: 1, k: "ctrl" }, { name: { SF: "len", FF: "len", CF: "SN", FC: "flag" }[kind] || "", n: 1, k: "status" }];
  let rest = b.slice(1);
  if (kind === "FF") { cells.push({ v: rest[0], k: "status" }); fields[1].n = 2; rest = rest.slice(1); }
  if (kind === "FC") { rest.forEach((x, i) => cells.push({ v: x, k: "status" })); fields.push({ name: "BS · STmin", n: rest.length, k: "status" }); rest = []; }
  rest.forEach((x) => cells.push({ v: x, k: "data" }));
  if (rest.length) fields.push({ name: "payload", n: rest.length, k: "data" });
  return `<div class="ribbon bytes">
    <div class="cells">${cells.map((c, i) => `<span class="k-${c.k}" style="${i < 2 ? "width:15px" : ""}">${esc(c.v)}</span>`).join("")}</div>
    <div class="fields" style="grid-template-columns: 15px 15px repeat(${cells.length - 2}, 30px)">${fields.map((f) => `<span class="k-${f.k}" style="grid-column: span ${f.n}">${esc(f.name)}</span>`).join("")}</div>
  </div>`.replace('<div class="cells">', `<div class="cells" style="grid-template-columns: 15px 15px repeat(${cells.length - 2}, 30px)">`);
}
function wireFrames(frames, left = "tester") {
  return `<div class="wire">${frames.map((f) => `
    <div class="frame ${f.from === left ? "" : "right"}">
      <span class="who">${esc(f.from)}</span>
      <span class="kind k-${ISOTP_K[f.kind] || "pad"}">${f.kind}</span>
      ${isotpRibbon(f.kind, f.bytes)}
    </div>`).join("")}</div>`;
}

/* ------------------------------------------------------------ shell */
let MODS = [], BY = {}, TEST = { report: null, done: [] };

function chipFor(status, label) {
  if (!status || status === "") return "";
  const cls = status === "pass" ? "pass" : status === "FAIL" ? "fail" : "";
  return `<span class="chip ${cls}">${label} ${status === "pass" ? "✓" : status === "FAIL" ? "✗" : "–"}</span>`;
}
function resultFor(id) {
  const all = TEST.report ? TEST.report.results : TEST.done;
  return (all || []).find((r) => r.module === id);
}
function testChips(id) {
  const r = resultFor(id);
  if (!r) return `<span class="chip">not run</span>`;
  return chipFor(r.c, "C") + chipFor(r.py, "Py") + (r.interop ? chipFor(r.interop, "C⇄Py") : "");
}
function header(id) {
  const m = BY[id];
  return `<header class="head">
    <div><p class="eyebrow">${m.domain} · <b>${esc(m.standard)}</b></p><h1>${esc(m.title)}</h1><p class="lesson">${esc(m.lesson)}.</p></div>
    <div class="chips" title="Last test run (Overview → Run all tests)">${testChips(id)}</div>
  </header>`;
}
function navDots() {
  for (const m of MODS) {
    const r = resultFor(m.id), d = $(`[data-dot="${m.id}"]`);
    if (!d) continue;
    d.className = "dot" + (!r ? (TEST.running ? " run" : "") : [r.c, r.py, r.interop].includes("FAIL") ? " fail" : " pass");
  }
  const all = $('[data-dot="all"]');
  all.className = "dot" + (TEST.running ? " run" : TEST.report ? (TEST.report.failures ? " fail" : " pass") : "");
}
function fail(el, e) { el.innerHTML = `<p class="err">${esc(e.message || e)}</p>`; }

/* ------------------------------------------------------------ overview */
function renderOverview(el) {
  const card = (m) => `<a class="card mcard" href="#/${m.id}">
      <span class="std">${esc(m.standard)}</span><b>${esc(m.title)}</b><p>${esc(m.lesson)}</p>
      <span class="row">${testChips(m.id)}</span></a>`;
  const group = (d) => MODS.filter((m) => m.domain === d).map(card).join("");
  el.innerHTML = `
    <section class="hero">
      <div><p class="eyebrow">Automotive &amp; avionics protocol workbench</p>
        <h1>Ten protocols. Two languages. <em>One bench.</em></h1>
        <p class="lesson">Every module is implemented twice, in C against a shared header and in idiomatic Python, and both halves are tested against the same expected values. Everything is simulated: no CAN interface, no 1553 card, no aircraft required.</p></div>
      <div class="stack" style="align-items:flex-end">
        <button class="primary" id="run-tests">${TEST.running ? "Running…" : "Run all tests"}</button>
        <span class="muted mono" id="compiler">${TEST.report ? `compiler: ${esc(TEST.report.compiler || "none - C skipped")}` : "C + Python + C⇄Python interop"}</span>
      </div>
    </section>
    <h2>Automotive</h2><div class="grid" style="grid-template-columns:repeat(auto-fill,minmax(230px,1fr))">${group("automotive")}</div>
    <h2 style="margin-top:22px">Avionics</h2><div class="grid" style="grid-template-columns:repeat(auto-fill,minmax(230px,1fr))">${group("avionics")}</div>
    <div class="card" style="margin-top:22px">
      <h2>How the modules connect</h2>
      <div class="stack">
        <div class="flow"><span class="node">DoIP tester</span><span class="arrow">→ TCP 13400 →</span><span class="node">DoIP gateway</span><span class="arrow">→ ISO-TP frames →</span><span class="node">UDS ECU</span><span class="muted">the gateway really segments onto the CAN side</span></div>
        <div class="flow"><span class="node">CAN log</span><span class="arrow">+</span><span class="node">ARINC 429 capture</span><span class="arrow">→</span><span class="node">Flight data recorder</span><span class="muted">one CRC'd 32-byte frame per bus message</span></div>
        <div class="flow"><span class="node">Python DoIP tester</span><span class="arrow">⇄</span><span class="node">C DoIP gateway</span><span class="muted">the interop check in every test run</span></div>
        <div class="flow"><span class="node">CAN bit layout</span><span class="arrow">→</span><span class="node">AUTOSAR BSW</span><span class="arrow">→ RTE →</span><span class="node">Application SWC</span><span class="muted">raw counts are scaled below the RTE, never above</span></div>
      </div>
    </div>`;
  $("#run-tests").onclick = runTests;
}
async function runTests() {
  await api("test_start", {});
  TEST = { running: true, done: [], report: null };
  route();
  const poll = async () => {
    const s = await fetch("/api/test_status", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" }).then((r) => r.json());
    TEST = s;
    navDots();
    if (location.hash.startsWith("#/overview") || location.hash === "") route(false);
    if (s.running) setTimeout(poll, 500);
  };
  poll();
}

/* ------------------------------------------------------------ CAN */
const CAN = { data: null, sig: 0, frame: 0, inputs: null };
async function renderCan(el) {
  if (!CAN.inputs) CAN.inputs = await api("can_sample");
  el.innerHTML = header("can") + `
    <div class="grid g-side">
      <div class="card stack">
        <h2>Inputs <span class="muted">DBC dictionary + candump log</span></h2>
        <label>DBC<textarea id="can-dbc" rows="11" spellcheck="false">${esc(CAN.inputs.dbc)}</textarea></label>
        <label>candump -l log<textarea id="can-log" rows="6" spellcheck="false">${esc(CAN.inputs.log)}</textarea></label>
        <div class="row"><button class="primary" id="can-go">Decode</button><button class="ghost" id="can-reset">Load sample</button></div>
      </div>
      <div class="stack" style="gap:16px">
        <div class="card"><h2>Bus traffic <span class="muted">click a frame to see its bits</span></h2><div id="can-frames"></div></div>
        <div class="card"><h2>Signal layout</h2><div id="can-sig"></div></div>
      </div>
    </div>`;
  const decode = async () => {
    try {
      CAN.inputs = { dbc: $("#can-dbc").value, log: $("#can-log").value };
      CAN.data = await api("can_decode", CAN.inputs);
      CAN.frame = Math.min(CAN.frame, CAN.data.frames.length - 1);
      drawCan();
    } catch (e) { fail($("#can-frames"), e); }
  };
  $("#can-go").onclick = decode;
  $("#can-reset").onclick = async () => { CAN.inputs = await api("can_sample"); renderCan(el); };
  decode();
}
function drawCan() {
  const { frames, signals } = CAN.data;
  const t0 = frames.length ? frames[0].t : 0;
  $("#can-frames").innerHTML = `<table><thead><tr><th>t [s]</th><th>ID</th><th>Data</th><th>Decoded</th></tr></thead><tbody>
    ${frames.map((f, i) => `<tr class="pick ${i === CAN.frame ? "sel" : ""}" data-i="${i}"><td class="num">${(f.t - t0).toFixed(3)}</td>
      <td class="mono">0x${f.id.toString(16).toUpperCase().padStart(3, "0")}</td><td class="mono">${esc(f.data)}</td>
      <td>${Object.entries(f.values).map(([k, v]) => { const s = signals.find((x) => x.name === k); return `<span class="chip info">${esc(k)} ${fmt(v, 6)} ${esc(s?.unit)}</span>`; }).join(" ")}</td></tr>`).join("")}
  </tbody></table>`;
  $$("#can-frames tr.pick").forEach((tr) => (tr.onclick = () => {
    CAN.frame = +tr.dataset.i;
    const f = frames[CAN.frame], idx = signals.findIndex((s) => s.can_id === f.id);
    if (idx >= 0 && signals[CAN.sig].can_id !== f.id) CAN.sig = idx;
    drawCan();
  }));
  const frame = frames[CAN.frame];
  const s = signals[CAN.sig] || signals[0];
  if (!s) { $("#can-sig").innerHTML = `<p class="muted">No signals in this DBC.</p>`; return; }
  const order = new Map(s.bits.map((b, i) => [b, i]));
  const bytes = bytesOf(frame?.can_id === s.can_id || frame?.id === s.can_id ? frame.data : "").map((x) => parseInt(x, 16));
  let grid = `<div class="bitmap"><span></span>${[7, 6, 5, 4, 3, 2, 1, 0].map((b) => `<span class="hd">bit ${b}</span>`).join("")}`;
  for (let by = 0; by < 8; by++) {
    grid += `<span class="by">byte ${by}</span>`;
    for (let bit = 7; bit >= 0; bit--) {
      const pos = by * 8 + bit, k = order.get(pos);
      const val = bytes.length > by ? (bytes[by] >> bit) & 1 : "";
      const cls = k === undefined ? "" : k === 0 ? "on lsb" : k === s.bits.length - 1 ? "on msb" : "on";
      grid += `<span class="bit ${cls}" title="DBC bit ${pos}${k !== undefined ? ` · significance ${k}` : ""}"><small>${k ?? ""}</small>${val}</span>`;
    }
  }
  grid += "</div>";
  const value = frame && frame.id === s.can_id ? frame.values[s.name] : null;
  $("#can-sig").innerHTML = `
    <div class="row" style="margin-bottom:12px">${signals.map((x, i) => `<button class="ghost small" data-s="${i}" ${i === CAN.sig ? 'style="border-color:var(--accent);font-weight:600"' : ""}>${esc(x.name)}</button>`).join("")}</div>
    <div class="grid g2" style="align-items:start">
      ${grid}
      <div class="stack">
        <p><b>${esc(s.name)}</b> in <b>${esc(s.message)}</b> (0x${s.can_id.toString(16).toUpperCase()}) — ${s.little_endian ? "<span class='chip info'>Intel · little endian</span>" : "<span class='chip warn'>Motorola · big endian</span>"} ${s.is_signed ? "<span class='chip'>signed</span>" : ""}</p>
        <p class="muted">${s.little_endian
          ? `Intel: start bit ${s.start_bit} is the <b>least</b> significant bit, and the signal climbs upward through the byte and on into the next one.`
          : `Motorola: start bit ${s.start_bit} is the <b>most</b> significant bit. The walk steps <b>down</b> inside the byte, then jumps to the top bit of the next byte. Same DBC syntax, opposite direction.`}</p>
        <div class="legend"><span><i style="background:var(--f-ctrl)"></i>LSB (significance 0)</span><span><i style="background:var(--f-id)"></i>MSB</span><span><i style="background:var(--f-data)"></i>signal bit</span></div>
        <p class="mono">physical = raw × ${s.scale} + ${s.offset}${value != null ? ` = <b>${fmt(value, 6)} ${esc(s.unit)}</b>` : ""}</p>
        <p class="muted">Small numbers show each bit's significance. Large digits are the bit values in the selected frame.</p>
      </div>
    </div>`;
  $$("#can-sig [data-s]").forEach((b) => (b.onclick = () => {
    CAN.sig = +b.dataset.s;
    const fi = CAN.data.frames.findIndex((f) => f.id === signals[CAN.sig].can_id);
    if (fi >= 0 && CAN.data.frames[CAN.frame].id !== signals[CAN.sig].can_id) CAN.frame = fi;
    drawCan();
  }));
}

/* ------------------------------------------------------------ UDS */
const UDS = { log: [], ecu: null };
const UDS_PRESETS = [
  ["Default session", "10 01", "DiagnosticSessionControl"],
  ["Extended session", "10 03", "needed before security access"],
  ["Read VIN", "22 F1 90", "17 bytes, so ISO-TP segments it"],
  ["Read software version", "22 F1 95", "fits in one single frame"],
  ["Read engine speed (slow)", "22 01 10", "the ECU answers 0x78 pending first"],
  ["Read unknown DID", "22 DE AD", "requestOutOfRange"],
  ["Write DID 0xF199", "2E F1 99 12 34", "refused until unlocked"],
];
async function renderUds(el) {
  el.innerHTML = header("uds") + `
    <div class="grid g-side">
      <div class="stack" style="gap:16px">
        <div class="card stack"><h2>Services</h2>
          ${UDS_PRESETS.map(([t, req, note]) => `<button class="ghost preset" data-req="${req}"><b>${t}</b><span>${req} · ${note}</span></button>`).join("")}
          <button class="ghost preset" data-unlock="1"><b>Security unlock</b><span>27 01 seed → key → 27 02</span></button>
          <label>Raw request (hex)<input id="uds-raw" value="22 F1 90" spellcheck="false"></label>
          <div class="row"><button class="primary" id="uds-send">Send</button><button class="ghost" id="uds-reset">Power-cycle ECU</button></div>
        </div>
        <div class="card"><h2>ECU state</h2><div id="uds-ecu"></div></div>
      </div>
      <div class="card"><h2>Transcript <span class="muted">newest first · every CAN frame on the wire</span></h2>
        <div class="legend" style="margin-bottom:10px"><span><i style="background:var(--f-ctrl)"></i>SF single frame</span><span><i style="background:var(--f-id)"></i>FF first frame</span><span><i style="background:var(--f-status)"></i>FC flow control</span><span><i style="background:var(--f-data)"></i>CF consecutive (SN = sequence number)</span></div>
        <div id="uds-log"></div></div>
    </div>`;
  const send = async (body, title) => {
    try {
      const r = await api("uds_request", body);
      UDS.ecu = r.ecu;
      UDS.log.unshift({ title, ...r });
      UDS.log = UDS.log.slice(0, 8);
    } catch (e) { UDS.log.unshift({ title, ok: false, error: e.message, frames: [] }); }
    drawUds();
  };
  $$("[data-req]").forEach((b) => (b.onclick = () => send({ request: b.dataset.req }, $("b", b).textContent)));
  $("[data-unlock]").onclick = () => send({ action: "unlock" }, "Security unlock");
  $("#uds-send").onclick = () => send({ request: $("#uds-raw").value }, "Raw request");
  $("#uds-reset").onclick = async () => { UDS.ecu = (await api("uds_reset")).ecu; UDS.log = []; drawUds(); };
  if (!UDS.ecu) UDS.ecu = (await api("uds_reset")).ecu;
  drawUds();
}
function drawUds() {
  const e = UDS.ecu || {};
  $("#uds-ecu").innerHTML = `<div class="row"><span class="chip ${e.session === "extended" ? "warn" : "info"}">session: ${e.session}</span>
    <span class="chip ${e.unlocked ? "pass" : ""}">${e.unlocked ? "unlocked" : "locked"}</span></div>
    ${Object.keys(e.written || {}).length ? `<p class="mono" style="margin:10px 0 0">written: ${Object.entries(e.written).map(([k, v]) => `${k} = ${v}`).join(", ")}</p>` : ""}`;
  $("#uds-log").innerHTML = UDS.log.length ? UDS.log.map((x) => `
    <div class="exchange">
      <div class="ex-head"><b>${esc(x.title)}</b>
        ${x.request ? `<span class="mono">${esc(x.request)}</span><span class="muted">→</span>` : ""}
        ${x.ok ? `<span class="chip pass">${esc(x.response || "positive")}</span>` : `<span class="chip fail">${esc(x.nrc ? `NRC ${x.nrc} ${x.nrc_name}` : x.error)}</span>`}
        ${x.pending ? `<span class="chip warn">0x78 responsePending ×${x.pending}, kept waiting</span>` : ""}
        ${x.note ? `<span class="muted">${esc(x.note)}</span>` : ""}</div>
      ${wireFrames(x.frames || [])}
    </div>`).join("") : `<p class="muted">Pick a service. Every request and every ISO-TP frame shows up here.</p>`;
}

/* ------------------------------------------------------------ AUTOSAR */
const AUT = { samples: [], mode: "traffic", speed: 90, brake: false, chart: null };
async function renderAutosar(el) {
  el.innerHTML = header("autosar") + `
    <div class="grid g-side">
      <div class="card stack"><h2>Vehicle bus</h2>
        <div class="seg" id="aut-mode">${[["traffic", "Traffic generator"], ["manual", "Manual"], ["dead", "Dead bus"]].map(([v, t]) => `<button data-v="${v}" aria-pressed="${AUT.mode === v}">${t}</button>`).join("")}</div>
        <div id="aut-manual" class="stack">
          <label>Vehicle speed <span id="aut-sv">${AUT.speed} km/h</span><input type="range" id="aut-speed" min="0" max="200" value="${AUT.speed}"></label>
          <label class="inline"><input type="checkbox" id="aut-brake" ${AUT.brake ? "checked" : ""}> Brake pressed</label>
        </div>
        <p class="muted" id="aut-hint"></p>
        <div class="row"><button class="primary" id="aut-run">Run 1 s</button><button class="ghost" id="aut-run5">Run 5 s</button><button class="ghost" id="aut-reset">Reset ECU</button></div>
      </div>
      <div class="stack" style="gap:16px">
        <div class="card"><h2>Layers <span class="muted">data flows up through the RTE, commands flow down</span></h2><div id="aut-layers" class="layers"></div></div>
        <div class="card"><h2>Timeline</h2><div class="legend" style="margin-bottom:6px"><span><i style="background:var(--f-id)"></i>vehicle speed [km/h]</span><span><i style="background:var(--fail)"></i>120 km/h limit</span><span><i style="background:#F4B400"></i>warning lamp</span><span><i style="background:var(--f-ctrl)"></i>brake</span></div><div class="chart" id="aut-chart"></div></div>
      </div>
    </div>`;
  const hint = () => {
    $("#aut-manual").style.opacity = AUT.mode === "manual" ? 1 : 0.4;
    $("#aut-hint").innerHTML = { traffic: "The BSW generates a speed sweep 0 → 199 km/h. Above 120 the lamp latches; only braking below the limit clears it.",
      manual: "Inject your own chassis frame (0x101) every tick. Go above 120, then brake below it.",
      dead: "Nothing on the bus. After 100 ms the speed signal is <b>stale</b>, and the SWC fails visible: lamp ON. A stale signal is a missing one, not a slow one." }[AUT.mode];
  };
  $$("#aut-mode button").forEach((b) => (b.onclick = () => { AUT.mode = b.dataset.v; $$("#aut-mode button").forEach((x) => x.setAttribute("aria-pressed", x === b)); hint(); }));
  $("#aut-speed").oninput = (e) => { AUT.speed = +e.target.value; $("#aut-sv").textContent = `${AUT.speed} km/h`; };
  $("#aut-brake").onchange = (e) => (AUT.brake = e.target.checked);
  const run = async (ms) => {
    const r = await api("autosar_run", { ms, mode: AUT.mode, speed: AUT.speed, brake: AUT.brake });
    AUT.samples = AUT.samples.concat(r.samples).slice(-3000);
    drawAutosar();
  };
  $("#aut-run").onclick = () => run(1000);
  $("#aut-run5").onclick = () => run(5000);
  $("#aut-reset").onclick = async () => { await api("autosar_reset"); AUT.samples = []; drawAutosar(); };
  hint();
  AUT.chart = null;
  if (!AUT.samples.length) await run(2000); else drawAutosar();
}
function drawAutosar() {
  const s = AUT.samples.at(-1) || { speed: 0, rpm: 0, brake: 0, lamp: 0, fresh: false, t: 0 };
  $("#aut-layers").innerHTML = `
    <div class="layer app"><b>Application SWC</b><div class="vals"><span>overspeed monitor reads only the RTE</span><span>lamp <span class="lamp ${s.lamp ? "on" : ""}"></span></span></div></div>
    <div class="layer rte"><b>RTE</b><div class="vals"><span>VehicleSpeed <b>${s.speed}</b> km/h</span><span>EngineRpm <b>${s.rpm}</b></span><span>Brake <b>${s.brake}</b></span><span class="chip ${s.fresh ? "pass" : "fail"}">${s.fresh ? "fresh" : "STALE"}</span></div></div>
    <div class="layer bsw"><b>BSW · CAN driver</b><div class="vals"><span>0x100 engine → rpm = raw / 4</span><span>0x101 chassis → speed = raw / 100</span></div></div>
    <div class="layer hw"><b>CAN bus</b><div class="vals"><span>${{ traffic: "traffic generator", manual: "manual injection", dead: "silent" }[AUT.mode]}</span><span>t = ${s.t} ms</span></div></div>`;
  const el = $("#aut-chart");
  const data = [AUT.samples.map((x) => x.t / 1000), AUT.samples.map((x) => x.speed), AUT.samples.map(() => 120),
    AUT.samples.map((x) => x.lamp), AUT.samples.map((x) => x.brake * 0.5)];
  if (!AUT.chart || !document.body.contains(AUT.chart.root)) {
    el.innerHTML = "";
    const axis = { stroke: css("--muted"), grid: { stroke: "#E6EAF0" }, ticks: { stroke: "#E6EAF0" }, font: `11px ${css("--f-num")}` };
    AUT.chart = new uPlot({
      width: el.clientWidth, height: el.clientHeight, legend: { show: false }, scales: { x: { time: false }, b: { range: [0, 1.15] } },
      series: [{ label: "t [s]" }, { label: "speed km/h", stroke: css("--f-id"), width: 2 }, { label: "limit", stroke: css("--fail"), dash: [5, 4], width: 1 },
        { label: "lamp", stroke: "#E1A400", fill: "#F4B40033", width: 1.5, scale: "b", paths: uPlot.paths.stepped({ align: 1 }) },
        { label: "brake", stroke: css("--f-ctrl"), width: 1.5, scale: "b", paths: uPlot.paths.stepped({ align: 1 }) }],
      axes: [{ ...axis }, { ...axis, size: 46 }, { ...axis, scale: "b", side: 1, grid: { show: false }, values: (u, v) => v.map((x) => (x === 1 ? "ON" : x === 0 ? "off" : "")) }],
    }, data, el);
    new ResizeObserver(() => AUT.chart && AUT.chart.setSize({ width: el.clientWidth, height: el.clientHeight })).observe(el);
  } else AUT.chart.setData(data);
}

/* ------------------------------------------------------------ ISO 26262 */
const SAF = { ops: [] };
async function renderSafety(el) {
  el.innerHTML = header("safety") + `
    <div class="grid g3">
      <div class="card stack"><h2>Windowed watchdog</h2>
        <div class="row"><label style="flex:1">Window opens [ms]<input id="wd-open" value="8"></label><label style="flex:1">closes [ms]<input id="wd-close" value="12"></label></div>
        <label>Kick times [ms]<input id="wd-kicks" value="10, 20, 31, 36, 46, 80" spellcheck="false"></label>
        <button class="primary" id="wd-go">Replay</button>
        <div id="wd-out"></div>
        <p class="muted">A kick is only healthy <b>inside</b> the window. Too early means the task is spinning in a loop, which a plain timeout watchdog would call healthy.</p>
      </div>
      <div class="card stack"><h2>Plausibility check</h2>
        <div class="row"><label style="flex:1">Previous<input id="pl-prev" value="0"></label><label style="flex:1">New<input id="pl-new" value="500"></label></div>
        <div class="row"><label style="flex:1">dt [s]<input id="pl-dt" value="1"></label><label style="flex:1">Max rate / s<input id="pl-max" value="100"></label></div>
        <button class="primary" id="pl-go">Check</button>
        <div id="pl-out"></div>
        <p class="muted">Is the new reading physically reachable from the last one? dt = 0 or NaN is refused, never divided by.</p>
      </div>
      <div class="card stack"><h2>Fault escalation</h2>
        <div class="row"><label style="flex:1">Fault id<input id="fm-id" value="0x100"></label>
          <label style="flex:1">Severity<select id="fm-sev"><option value="1">1 · degraded</option><option value="2" selected>2 · limp home</option><option value="3">3 · shutdown</option></select></label></div>
        <div class="row"><button class="primary" id="fm-report">Report</button><button class="ghost" id="fm-heal">Heal</button><button class="ghost" id="fm-clear">Clear</button></div>
        <div id="fm-out"></div>
      </div>
    </div>`;
  const wd = async () => {
    try {
      const kicks = $("#wd-kicks").value.split(/[ ,;]+/).filter(Boolean).map(Number);
      const r = await api("safety_watchdog", { open: +$("#wd-open").value, close: +$("#wd-close").value, kicks });
      drawWatchdog(r, +$("#wd-open").value, +$("#wd-close").value);
    } catch (e) { fail($("#wd-out"), e); }
  };
  $("#wd-go").onclick = wd;
  $("#pl-go").onclick = async () => {
    try {
      const r = await api("safety_plausibility", { prev: $("#pl-prev").value, new: $("#pl-new").value, dt: $("#pl-dt").value, max_rate: $("#pl-max").value });
      $("#pl-out").innerHTML = `<p class="verdict ${r.plausible ? "pass" : "fail"}">${r.plausible ? "PLAUSIBLE" : "IMPLAUSIBLE"}</p><p class="mono">rate = ${r.rate == null ? "undefined (dt ≤ 0)" : fmt(r.rate)} / s  vs  limit ${$("#pl-max").value}</p>`;
    } catch (e) { fail($("#pl-out"), e); }
  };
  const fm = async () => drawFaults(await api("safety_faults", { ops: SAF.ops }));
  $("#fm-report").onclick = () => { SAF.ops.push({ op: "report", id: $("#fm-id").value, severity: +$("#fm-sev").value }); fm(); };
  $("#fm-heal").onclick = () => { SAF.ops.push({ op: "heal", id: $("#fm-id").value }); fm(); };
  $("#fm-clear").onclick = () => { SAF.ops = []; fm(); };
  wd(); $("#pl-go").click(); fm();
}
function drawWatchdog(r, open, close) {
  const W = 420, H = 110, until = Math.max(r.until, 1), x = (t) => 10 + (t / until) * (W - 20);
  const colour = { ok: css("--pass"), early: css("--fail"), late: css("--fail"), expired: css("--warn") };
  const wins = (r.windows || []).map((w) => `<rect x="${x(w.start + open)}" y="22" width="${Math.max(1, x(w.start + close) - x(w.start + open))}" height="40" fill="#1E9C5822" stroke="#1E9C5866"/>`).join("");
  const marks = r.events.map((e) => `<g><line x1="${x(e.t)}" x2="${x(e.t)}" y1="16" y2="68" stroke="${colour[e.kind]}" stroke-width="2"/>
      <text x="${x(e.t)}" y="${e.kind === "expired" ? 82 : 12}" text-anchor="middle" fill="${colour[e.kind]}">${e.kind === "expired" ? "⏱" : e.t}</text></g>`).join("");
  const ticks = [...Array(6)].map((_, i) => { const t = Math.round((until * i) / 5); return `<text x="${x(t)}" y="100" text-anchor="middle" fill="#8893A2">${t}</text>`; }).join("");
  $("#wd-out").innerHTML = `<svg class="timeline" viewBox="0 0 ${W} ${H}"><line x1="10" x2="${W - 10}" y1="62" y2="62" stroke="#C3CAD4"/>${wins}${marks}${ticks}</svg>
    <div class="row">${r.events.map((e) => `<span class="chip ${e.kind === "ok" ? "pass" : e.kind === "expired" ? "warn" : "fail"}">${e.t} ms ${e.kind}${e.since != null && e.kind !== "ok" ? ` (${e.since} ms)` : ""}</span>`).join("")}</div>`;
}
function drawFaults(r) {
  const last = r.steps.at(-1);
  const state = last ? last.state : "NORMAL";
  const names = ["NORMAL", "DEGRADED", "LIMP_HOME", "SHUTDOWN"];
  $("#fm-out").innerHTML = `<div class="ladder">${names.map((n, i) => `<span class="s${i} ${n === state ? "on" : ""}">${n.replace("_", " ")}</span>`).join("")}</div>
    ${last && Object.keys(last.faults).length ? `<table style="margin-top:10px"><thead><tr><th>Fault</th><th>Severity</th><th>Debounce</th></tr></thead><tbody>
      ${Object.entries(last.faults).map(([id, f]) => `<tr><td class="mono">${id}</td><td>${f.severity}</td><td><span class="chip ${f.count >= r.debounce ? "fail" : "warn"}">${f.count} / ${r.debounce}${f.count >= r.debounce ? " confirmed" : ""}</span></td></tr>`).join("")}</tbody></table>` : ""}
    <p class="muted" style="margin-top:10px">A fault only counts after ${r.debounce} consecutive reports, so one glitch cannot limp-home a car. The state is recomputed from scratch, so healing really lowers it.</p>`;
}

/* ------------------------------------------------------------ DoIP */
const DOIP = { impl: "python", started: null, log: [] };
const DOIP_STEPS = [
  ["identify", null, "Identify vehicle", "answered before routing activation, on purpose"],
  ["uds", "22 F1 90", "Diagnose before activation", "must be refused"],
  ["activate", null, "Activate routing", "tester 0x0E00"],
  ["uds", "22 F1 90", "Read VIN over DoIP", "forwarded to the ECU"],
  ["uds", "22 01 10", "Read engine speed", "the slow DID, 0x78 absorbed by the gateway"],
];
async function renderDoip(el) {
  el.innerHTML = header("doip") + `
    <div class="grid g-side">
      <div class="stack" style="gap:16px">
        <div class="card stack"><h2>Gateway</h2>
          <div class="seg" id="doip-impl"><button data-v="python" aria-pressed="${DOIP.impl === "python"}">Python → UDS ECU</button><button data-v="c" aria-pressed="${DOIP.impl === "c"}">C gateway</button></div>
          <p class="muted" id="doip-impl-note"></p>
          <button class="primary" id="doip-start">Start gateway</button>
          <div id="doip-state" class="muted"></div>
        </div>
        <div class="card stack"><h2>Tester steps</h2>
          ${DOIP_STEPS.map(([a, uds, t, note], i) => `<button class="ghost preset" data-step="${i}"><b>${i + 1}. ${t}</b><span>${note}</span></button>`).join("")}
          <label>Raw UDS (hex)<input id="doip-raw" value="10 03" spellcheck="false"></label>
          <button class="ghost" id="doip-send">Send raw UDS</button>
        </div>
      </div>
      <div class="card"><h2>Messages <span class="muted">TCP on top, CAN side underneath</span></h2>
        <div class="legend" style="margin-bottom:10px"><span><i style="background:var(--f-ctrl)"></i>protocol version</span><span><i style="background:var(--f-check)"></i>inverse (version ^ 0xFF)</span><span><i style="background:var(--f-id)"></i>payload type</span><span><i style="background:var(--f-status)"></i>length</span><span><i style="background:var(--f-data)"></i>payload</span></div>
        <div id="doip-log"></div></div>
    </div>`;
  const note = () => ($("#doip-impl-note").innerHTML = DOIP.impl === "python"
    ? "The Python gateway segments each request with ISO-TP and delivers it to the UDS ECU from the <a href='#/uds'>UDS module</a>. You see both sides."
    : "Builds the C gateway from <code>doip/src</code> with the compiler BusBench finds, runs it on 127.0.0.1:13400 and connects the Python tester to it.");
  $$("#doip-impl button").forEach((b) => (b.onclick = () => { DOIP.impl = b.dataset.v; $$("#doip-impl button").forEach((x) => x.setAttribute("aria-pressed", x === b)); note(); }));
  note();
  $("#doip-start").onclick = async () => {
    $("#doip-state").textContent = DOIP.impl === "c" ? "building the C gateway…" : "starting…";
    try {
      DOIP.started = await api("doip_start", { impl: DOIP.impl });
      DOIP.log = [];
      drawDoip();
    } catch (e) { $("#doip-state").innerHTML = `<span class="err">${esc(e.message)}</span>`; }
  };
  const send = async (body, title) => {
    try { DOIP.log.unshift({ title, ...(await api("doip_send", body)) }); }
    catch (e) { DOIP.log.unshift({ title, error: e.message }); }
    DOIP.log = DOIP.log.slice(0, 8);
    drawDoip();
  };
  $$("[data-step]").forEach((b) => (b.onclick = () => { const [a, uds, t] = DOIP_STEPS[+b.dataset.step]; send({ action: a, uds }, t); }));
  $("#doip-send").onclick = () => send({ action: "uds", uds: $("#doip-raw").value }, "Raw UDS");
  if (!DOIP.started) $("#doip-start").click(); else drawDoip();
}
const DOIP_LAYOUT = [["ver", 1, "ctrl"], ["inv", 1, "check"], ["type", 2, "id"], ["length", 4, "status"], ["payload", "rest", "data"]];
function drawDoip() {
  const s = DOIP.started;
  $("#doip-state").innerHTML = s ? `<span class="chip pass">${s.impl === "c" ? `C gateway (${esc(s.compiler)})` : "Python gateway"} · port ${s.port}</span>` : "";
  $("#doip-log").innerHTML = DOIP.log.length ? DOIP.log.map((x) => x.error ? `<div class="exchange"><div class="ex-head"><b>${esc(x.title)}</b><span class="chip fail">${esc(x.error)}</span></div></div>` : `
    <div class="exchange">
      <div class="ex-head"><b>${esc(x.title)}</b><span class="muted">${esc(x.request.type_name)} →</span>
        <span class="chip ${/NACK/.test(x.response.type_name) ? "fail" : "pass"}">${esc(x.response.type_name)}</span></div>
      <div class="frame"><span class="who">tester</span><span class="kind k-id">TX</span>${bytesRibbon(x.request.hex, DOIP_LAYOUT)}</div>
      <div class="frame right"><span class="who">gateway</span><span class="kind k-data">RX</span>${bytesRibbon(x.response.hex, DOIP_LAYOUT)}</div>
      ${x.can && x.can.length ? `<h3>CAN side · ISO-TP to the ECU</h3>${wireFrames(x.can, "gateway")}` : ""}
    </div>`).join("") : `<p class="muted">Run the tester steps in order. Step 2 shows why routing activation exists: without it anyone on port 13400 could talk UDS to the car.</p>`;
}

/* ------------------------------------------------------------ ARINC 429 */
const A429 = { inputs: null, words: [], sel: 0, built: null };
const A429_LAYOUT = [["P", 1, "check"], ["SSM", 2, "status"], ["data (bits 29–11)", 19, "data"], ["SDI", 2, "ctrl"], ["label", 8, "id"]];
const A429_IDX = [...Array(32)].map((_, i) => 32 - i);
async function renderArinc429(el) {
  if (!A429.inputs) A429.inputs = await api("arinc429_sample");
  el.innerHTML = header("arinc429") + `
    <div class="grid g2">
      <div class="card"><h2>Capture <span class="muted">one 32-bit word per line</span></h2><div id="a4-table"></div>
        <details style="margin-top:12px"><summary>Edit label dictionary and capture</summary>
          <div class="grid g2" style="margin-top:8px"><label>labels.csv<textarea id="a4-labels" rows="7" spellcheck="false">${esc(A429.inputs.labels)}</textarea></label>
          <label>capture<textarea id="a4-capture" rows="7" spellcheck="false">${esc(A429.inputs.capture)}</textarea></label></div>
          <button class="ghost" id="a4-go" style="margin-top:8px">Analyze</button></details></div>
      <div class="stack" style="gap:16px">
        <div class="card"><h2>Word</h2><div id="a4-word"></div></div>
        <div class="card stack"><h2>Word builder</h2>
          <div class="row"><label style="flex:1">Label (octal)<input id="b-label" value="203"></label><label style="flex:1">Value<input id="b-value" value="35000"></label>
            <label style="flex:.6">SDI<select id="b-sdi"><option>0</option><option>1</option><option>2</option><option>3</option></select></label>
            <label style="flex:1.3">SSM<select id="b-ssm"><option value="3">3 normal</option><option value="1">1 no computed data</option><option value="2">2 functional test</option><option value="0">0 failure warning</option></select></label></div>
          <div class="row"><button class="primary" id="b-go">Build word</button><button class="ghost" id="b-add" disabled>Add to capture</button></div>
          <div id="b-out"></div></div>
      </div>
    </div>`;
  const analyze = async () => {
    A429.inputs = { labels: $("#a4-labels").value, capture: $("#a4-capture").value };
    try { A429.words = (await api("arinc429_analyze", A429.inputs)).words; drawA429(); } catch (e) { fail($("#a4-table"), e); }
  };
  $("#a4-go").onclick = analyze;
  $("#b-go").onclick = async () => {
    try {
      A429.built = await api("arinc429_build", { labels: $("#a4-labels").value, label: $("#b-label").value, value: $("#b-value").value, sdi: $("#b-sdi").value, ssm: $("#b-ssm").value });
      $("#b-out").innerHTML = wordView(A429.built);
      $("#b-add").disabled = false;
    } catch (e) { fail($("#b-out"), e); }
  };
  $("#b-add").onclick = () => { $("#a4-capture").value = $("#a4-capture").value.trimEnd() + `\n${A429.built.hex}\n`; analyze().then(() => { A429.sel = A429.words.length - 1; drawA429(); }); };
  analyze();
}
function wordView(w) {
  return `<div class="stack">${bitsRibbon(w.bits, A429_LAYOUT, A429_IDX)}
    <div class="row"><span class="mono" style="font-size:15px"><b>0x${w.hex}</b></span>
      <span class="chip info">label ${w.label}${w.name ? ` · ${esc(w.name)}` : ""}</span>
      ${w.value != null ? `<span class="chip pass">${fmt(w.value, 6)} ${esc(w.unit)}</span>` : ""}
      <span class="chip ${w.parity_ok ? "pass" : "fail"}">parity ${w.parity_ok ? "odd ✓" : "ERROR"}</span>
      <span class="chip ${w.usable ? "pass" : "warn"}">SSM ${w.ssm} ${esc(w.ssm_name)}</span><span class="chip">SDI ${w.sdi}</span></div>
    <p class="muted">The label goes on the wire most significant bit first while every other field goes least significant first, so bits 8–1 hold label ${w.label} <b>reversed</b>. ${!w.usable && w.parity_ok ? "This word decodes perfectly and is still meaningless: the source says it has no valid data." : ""}${!w.parity_ok ? "Even number of ones: a bit flipped in flight, so nothing in this word is believed." : ""}</p></div>`;
}
function drawA429() {
  $("#a4-table").innerHTML = `<table><thead><tr><th>Word</th><th>Label</th><th>Name</th><th>Value</th><th>SSM</th><th>Parity</th></tr></thead><tbody>
    ${A429.words.map((w, i) => `<tr class="pick ${i === A429.sel ? "sel" : ""}" data-i="${i}"><td class="mono">${w.hex}</td><td class="mono">${w.label}</td><td>${esc(w.name || "—")}</td>
      <td class="num">${w.value != null ? `${fmt(w.value, 6)} ${esc(w.unit)}` : "—"}</td><td><span class="chip ${w.usable ? "pass" : "warn"}">${esc(w.ssm_name)}</span></td>
      <td><span class="chip ${w.parity_ok ? "pass" : "fail"}">${w.parity_ok ? "ok" : "error"}</span></td></tr>`).join("")}</tbody></table>`;
  $$("#a4-table tr.pick").forEach((tr) => (tr.onclick = () => { A429.sel = +tr.dataset.i; drawA429(); }));
  const w = A429.words[A429.sel];
  $("#a4-word").innerHTML = w ? wordView(w) : "";
}

/* ------------------------------------------------------------ MIL-STD-1553 */
const M1553 = { bus: null, last: null, sched: null };
const M1553_LAYOUT = [["RT address", 5, "id"], ["T/R", 1, "ctrl"], ["subaddress", 5, "status"], ["word count / mode", 5, "data"]];
const M1553_IDX = [...Array(16)].map((_, i) => 15 - i);
async function renderMil1553(el) {
  el.innerHTML = header("mil1553") + `
    <div class="card" style="margin-bottom:16px"><h2>Bus <span class="muted">nothing speaks unless the bus controller asks</span></h2><div id="m-bus"></div>
      <div class="row" style="margin-top:10px"><label class="inline">Add RT <input id="m-add" value="7" style="width:60px"></label><button class="ghost small" id="m-addb">Connect</button><button class="ghost small" id="m-reset">Reset bus</button></div></div>
    <div class="grid g2">
      <div class="card stack"><h2>Command</h2>
        <div class="row"><label style="flex:1">RT (31 = broadcast)<input id="m-rt" value="3"></label>
          <label style="flex:1">Direction<select id="m-tr"><option value="1">T · RT → BC</option><option value="0">R · BC → RT</option></select></label>
          <label style="flex:1">Subaddress<input id="m-sa" value="1"></label><label style="flex:1">Word count<input id="m-wc" value="4"></label></div>
        <label>Data words for BC → RT (hex)<input id="m-data" value="0x1111 0x2222 0x3333 0x4444" spellcheck="false"></label>
        <div class="row"><button class="primary" id="m-go">Transact</button></div>
        <div id="m-out"></div></div>
      <div class="card stack"><h2>Minor frame schedule <span class="muted">one retry, then move on</span></h2>
        <label>One command per line: RT T/R SA WC<textarea id="m-sched" rows="5" spellcheck="false">3 1 1 4\n9 1 1 4\n5 0 2 2\n31 0 7 4</textarea></label>
        <div class="row"><button class="primary" id="m-run">Run frame</button></div>
        <div id="m-sout"></div></div>
    </div>`;
  const set = (r) => { M1553.bus = r.bus || r; drawBus(); };
  $("#m-addb").onclick = async () => set(await api("mil1553_rt", { address: +$("#m-add").value }));
  $("#m-reset").onclick = async () => set(await api("mil1553_reset"));
  $("#m-go").onclick = async () => {
    try {
      const data = $("#m-data").value.split(/[ ,]+/).filter(Boolean);
      M1553.last = await api("mil1553_transact", { rt: $("#m-rt").value, tr: $("#m-tr").value, sa: $("#m-sa").value, wc: $("#m-wc").value, data });
      set(M1553.last);
      const r = M1553.last;
      $("#m-out").innerHTML = `${bitsRibbon(r.command.bits, M1553_LAYOUT, M1553_IDX)}
        <div class="row" style="margin-top:8px"><span class="mono"><b>0x${r.command.hex}</b></span>${r.command.mode_code ? `<span class="chip warn">mode code ${r.command.wc}</span>` : ""}
        ${r.ok ? `<span class="chip pass">${r.broadcast ? "broadcast taken by every RT, no status word" : "status word received"}</span>` : `<span class="chip fail">${esc(r.kind)}: ${esc(r.error)}</span>`}</div>
        ${r.ok && r.words.length ? `<p class="mono">data: ${r.words.join(" ")}</p>` : ""}
        <p class="muted">Word count 32 goes on the wire as 0. On subaddress 0 or 31 those five bits are a mode code instead.</p>`;
    } catch (e) { fail($("#m-out"), e); }
  };
  $("#m-run").onclick = async () => {
    try {
      const commands = $("#m-sched").value.split("\n").map((l) => l.trim().split(/\s+/)).filter((p) => p.length === 4).map(([rt, tr, sa, wc]) => ({ rt, tr, sa, wc }));
      const r = await api("mil1553_schedule", { commands });
      set(r);
      $("#m-sout").innerHTML = `<table><thead><tr><th>Command</th><th>RT</th><th>Dir</th><th>SA</th><th>WC</th><th>Attempts</th></tr></thead><tbody>
        ${r.log.map((e) => `<tr><td class="mono">0x${e.hex}</td><td>${e.rt}</td><td>${e.tr ? "T" : "R"}</td><td>${e.sa}</td><td>${e.wc}</td>
          <td>${e.attempts.map((a) => `<span class="chip ${a === "ok" ? "pass" : "fail"}">${esc(a)}</span>`).join(" ")}</td></tr>`).join("")}</tbody></table>
        <p class="muted">A sulking terminal gets one retry and is skipped. Every other RT on the bus has a deadline that does not care.</p>`;
    } catch (e) { fail($("#m-sout"), e); }
  };
  set(await api("mil1553_state"));
}
function drawBus() {
  const b = M1553.bus;
  $("#m-bus").innerHTML = `<div class="row" style="align-items:stretch;gap:12px">
    <div class="card sunk" style="padding:10px 14px;min-width:120px"><b style="font:600 13px var(--f-label)">BUS CONTROLLER</b>
      <p class="mono" style="margin:4px 0 0">${b.transactions} transactions<br>${b.retries} retries · ${b.failures} failures</p></div>
    ${b.rts.map((rt) => `<div class="card" style="padding:10px 12px;min-width:150px;border-top:3px solid ${!rt.connected ? "var(--f-pad)" : rt.busy || rt.subsystem_fault ? "var(--warn)" : "var(--pass)"}">
      <div class="row"><b style="font:600 13px var(--f-label)">RT ${rt.address}</b><span class="spacer"></span><button class="ghost small" data-rm="${rt.address}" title="Remove">×</button></div>
      ${["connected", "busy", "subsystem_fault"].map((k) => `<label class="inline" style="font-size:12px"><input type="checkbox" data-rt="${rt.address}" data-k="${k}" ${rt[k] ? "checked" : ""}> ${k.replace("_", " ")}</label>`).join("")}
      <p class="mono" style="margin:4px 0 0;font-size:11px">${Object.entries(rt.data).map(([sa, w]) => `SA${sa}: ${w.join(" ")}`).join("<br>") || "no data"}${rt.broadcasts ? `<br>${rt.broadcasts} broadcasts` : ""}</p></div>`).join("")}</div>`;
  $$("#m-bus [data-rt]").forEach((c) => (c.onchange = async () => { M1553.bus = await api("mil1553_rt", { address: +c.dataset.rt, [c.dataset.k]: c.checked }); drawBus(); }));
  $$("#m-bus [data-rm]").forEach((c) => (c.onclick = async () => { M1553.bus = await api("mil1553_rt", { address: +c.dataset.rm, remove: true }); drawBus(); }));
}

/* ------------------------------------------------------------ ARINC 653 */
const A653 = {
  frame: 40, frames: 3,
  rows: [{ name: "FMS", offset: 0, duration: 10, behaviour: "nominal", work: 6 },
    { name: "DISPLAY", offset: 12, duration: 8, behaviour: "greedy", work: 4 },
    { name: "MAINT", offset: 22, duration: 6, behaviour: "nosy", work: 2 },
    { name: "IO", offset: 30, duration: 8, behaviour: "nominal", work: 3 }],
};
const PCOL = ["#3D63DD", "#159A78", "#8A5CD6", "#D3901A", "#2B9CC7", "#C2457A"];
async function renderArinc653(el) {
  el.innerHTML = header("arinc653") + `
    <div class="grid g-side" style="grid-template-columns: 470px minmax(0, 1fr)">
      <div class="card stack"><h2>Schedule <span class="muted">fixed offline</span></h2>
        <table id="p-table"></table>
        <div class="row"><button class="ghost small" id="p-add">+ Partition</button></div>
        <div class="row"><label style="flex:1">Major frame [ms]<input id="p-frame" value="${A653.frame}"></label><label style="flex:1">Frames<input id="p-frames" value="${A653.frames}"></label></div>
        <button class="primary" id="p-run">Run</button>
        <p class="muted"><b>greedy</b> never stops asking for time, <b>hung</b> never yields, <b>nosy</b> writes into its neighbour's memory region. None of them can move the next partition's start by a single millisecond.</p>
      </div>
      <div class="stack" style="gap:16px"><div class="card"><h2>Timeline</h2><div id="p-out"></div></div><div class="card"><h2>Health monitor</h2><div id="p-health"></div></div></div>
    </div>`;
  const table = () => {
    $("#p-table").innerHTML = `<thead><tr><th>Name</th><th>Offset</th><th>Slice</th><th>Behaviour</th><th>Work</th><th></th></tr></thead><tbody>
      ${A653.rows.map((r, i) => `<tr>
        <td><input data-i="${i}" data-k="name" value="${esc(r.name)}" style="width:92px"></td><td><input data-i="${i}" data-k="offset" value="${r.offset}" style="width:52px"></td>
        <td><input data-i="${i}" data-k="duration" value="${r.duration}" style="width:52px"></td>
        <td><select data-i="${i}" data-k="behaviour" style="width:98px">${["nominal", "greedy", "hung", "nosy"].map((b) => `<option ${b === r.behaviour ? "selected" : ""}>${b}</option>`).join("")}</select></td>
        <td><input data-i="${i}" data-k="work" value="${r.work}" style="width:46px"></td><td><button class="ghost small" data-del="${i}">×</button></td></tr>`).join("")}</tbody>`;
    $$("#p-table [data-k]").forEach((inp) => (inp.oninput = inp.onchange = () => { const r = A653.rows[+inp.dataset.i]; r[inp.dataset.k] = inp.dataset.k === "name" || inp.dataset.k === "behaviour" ? inp.value : +inp.value; }));
    $$("#p-table [data-del]").forEach((b) => (b.onclick = () => { A653.rows.splice(+b.dataset.del, 1); table(); }));
  };
  table();
  $("#p-add").onclick = () => { const end = Math.max(0, ...A653.rows.map((r) => r.offset + r.duration)); A653.rows.push({ name: `P${A653.rows.length + 1}`, offset: end, duration: 4, behaviour: "nominal", work: 2 }); table(); };
  $("#p-run").onclick = async () => {
    A653.frame = +$("#p-frame").value; A653.frames = +$("#p-frames").value;
    const r = await api("arinc653_run", { partitions: A653.rows, major_frame: A653.frame, frames: A653.frames });
    if (!r.ok) { $("#p-out").innerHTML = `<p class="verdict fail">Configuration rejected</p><p class="err">${esc(r.error)}</p><p class="muted">A bad schedule is a build error, not a surprise in the air.</p>`; $("#p-health").innerHTML = ""; return; }
    drawTimeline(r);
  };
  $("#p-run").click();
}
function drawTimeline(r) {
  const W = 760, rowH = 38, top = 22, F = r.major_frame, frames = Math.max(...r.segments.map((s) => s.frame)) + 1;
  const x = (ms) => 70 + (ms / F) * (W - 90);
  const names = A653.rows.map((p) => p.name);
  let svg = "";
  for (let f = 0; f < frames; f++) {
    const y = top + f * rowH;
    svg += `<text x="0" y="${y + 20}" fill="#5B6676">frame ${f}</text><rect x="${x(0)}" y="${y}" width="${x(F) - x(0)}" height="28" fill="#F5F7FA" stroke="#D6DCE4"/>`;
    A653.rows.forEach((p, i) => { svg += `<rect x="${x(p.offset)}" y="${y}" width="${x(p.offset + p.duration) - x(p.offset)}" height="28" fill="none" stroke="${PCOL[i % 6]}" stroke-dasharray="3 2"/>`; });
    r.segments.filter((s) => s.frame === f).forEach((s) => {
      const i = names.indexOf(s.partition), c = PCOL[i % 6], fs = s.start - f * F, fe = s.end - f * F;
      svg += `<rect x="${x(fs)}" y="${y + 3}" width="${Math.max(2, x(fe) - x(fs))}" height="22" rx="2" fill="${c}"/>`;
      if (x(fe) - x(fs) > 34) svg += `<text x="${x(fs) + 5}" y="${y + 18}" fill="#fff" style="font-weight:600">${esc(s.partition)}</text>`;
      if (s.cut_off) svg += `<rect x="${x(fe) - 3}" y="${y - 2}" width="3" height="32" fill="#D6455D"><title>cut off at its own boundary</title></rect>`;
    });
  }
  for (let t = 0; t <= F; t += Math.max(1, Math.round(F / 8))) svg += `<text x="${x(t)}" y="12" text-anchor="middle" fill="#8893A2">${t}</text>`;
  $("#p-out").innerHTML = `<svg class="timeline" viewBox="0 0 ${W} ${top + frames * rowH + 4}">${svg}</svg>
    <div class="legend"><span><i style="border:1px dashed #5B6676;background:none"></i>planned slice</span><span><i style="background:#3D63DD"></i>time actually used</span><span><i style="background:#D6455D"></i>cut off at its own boundary</span></div>`;
  $("#p-health").innerHTML = `<table><thead><tr><th>Partition</th><th>Overruns</th><th>Memory violations</th></tr></thead><tbody>
    ${Object.entries(r.health).map(([n, h]) => `<tr><td><b>${esc(n)}</b></td><td><span class="chip ${h.overruns ? "warn" : "pass"}">${h.overruns}</span></td><td><span class="chip ${h.violations ? "fail" : "pass"}">${h.violations}</span></td></tr>`).join("")}</tbody></table>
    <p class="muted">Every fault is recorded against the partition that caused it, and nobody else.</p>`;
}

/* ------------------------------------------------------------ DO-178C */
const TRC = { inputs: null, res: null };
async function renderTraceability(el) {
  if (!TRC.inputs) TRC.inputs = await api("traceability_sample");
  const srcs = TRC.inputs.sources;
  el.innerHTML = header("traceability") + `
    <div class="card" style="margin-bottom:16px"><div class="row" id="t-summary"></div></div>
    <div class="grid g2">
      <div class="card"><h2>Traceability matrix</h2><div id="t-matrix"></div></div>
      <div class="stack" style="gap:16px">
        <div class="card"><h2>Seen from the other direction</h2><div id="t-other"></div></div>
        <div class="card"><details><summary>Edit inputs: requirements, JUnit results, source tree</summary>
          <div class="stack" style="margin-top:8px">
            <label>requirements.csv<textarea id="t-req" rows="6" spellcheck="false">${esc(TRC.inputs.requirements)}</textarea></label>
            <label>results.xml (JUnit)<textarea id="t-res" rows="7" spellcheck="false">${esc(TRC.inputs.results)}</textarea></label>
            ${Object.entries(srcs).map(([n, t]) => `<label>src/${esc(n)}<textarea data-src="${esc(n)}" rows="6" spellcheck="false">${esc(t)}</textarea></label>`).join("")}
            <div class="row"><button class="primary" id="t-go">Analyze</button></div></div></details></div>
      </div>
    </div>`;
  const go = async () => {
    const sources = {};
    $$("[data-src]").forEach((t) => (sources[t.dataset.src] = t.value));
    TRC.inputs = { requirements: $("#t-req").value, results: $("#t-res").value, sources };
    try { TRC.res = await api("traceability_analyze", TRC.inputs); drawTrace(); } catch (e) { fail($("#t-matrix"), e); }
  };
  $("#t-go").onclick = go;
  go();
}
function drawTrace() {
  const r = TRC.res, s = r.summary;
  const tone = { pass: "pass", FAIL: "fail", "NO TEST": "warn", "NOT RUN": "fail" };
  $("#t-summary").innerHTML = `<span class="verdict ${s.problems ? "fail" : "pass"}">Build gate: ${s.problems ? "FAIL" : "PASS"}</span>
    <span class="muted">${s.requirements} requirements · exit code ${s.problems}</span><span class="spacer"></span>
    <span class="chip warn">no test ${s.orphan_requirements.length}</span><span class="chip fail">named, never ran ${s.not_run.length}</span>
    <span class="chip fail">failing ${s.failing.length}</span><span class="chip warn">unclaimed tests ${s.orphan_tests.length}</span><span class="chip warn">stale annotations ${s.bad_annotations.length}</span>
    <button class="ghost small" id="t-save">Save report</button>`;
  $("#t-matrix").innerHTML = `<table><thead><tr><th>Requirement</th><th>Verified by</th><th>Status</th></tr></thead><tbody>
    ${r.requirements.map((q) => `<tr><td><b class="mono">${esc(q.req_id)}</b><br><span class="muted">${esc(q.description)}</span></td>
      <td class="mono">${esc(q.verified_by || "(none)")}</td><td><span class="chip ${tone[q.status] || ""}">${esc(q.status)}</span></td></tr>`).join("")}</tbody></table>`;
  $("#t-other").innerHTML = `<h3>Tests no requirement asks for</h3>${s.orphan_tests.length ? s.orphan_tests.map((t) => `<span class="chip warn">${esc(t)}</span>`).join(" ") : `<span class="muted">none</span>`}
    <h3>Source annotations pointing at a missing requirement</h3>${s.bad_annotations.length ? s.bad_annotations.map((b) => `<p class="mono" style="margin:4px 0"><b>${esc(b.test_name)}</b> in ${esc(b.file)} claims <span class="chip fail">${esc(b.req_id)}</span>, which does not exist</p>`).join("") : `<span class="muted">none</span>`}
    <p class="muted" style="margin-top:12px">A requirement whose test was deleted, or a test pointing at a renumbered requirement, looks fine from one side. That is why the tool reads the source tree back.</p>`;
  $("#t-save").onclick = () => saveFile("trace_report.md", r.report);
}

/* ------------------------------------------------------------ FDR */
const FDR = { st: null, sel: null };
const FDR_LAYOUT = [["magic", 4, "ctrl"], ["timestamp µs", 8, "id"], ["src", 1, "status"], ["len", 1, "status"], ["payload", 16, "data"], ["CRC", 2, "check"]];
async function renderFdr(el) {
  el.innerHTML = header("fdr") + `
    <div class="ringwrap">
      <div class="card stack"><h2>Recorder</h2>
        <label>Capacity [frames]<input id="f-cap" value="${FDR.st ? FDR.st.capacity : 16}"></label>
        <button class="ghost" id="f-reset">Format store</button>
        <button class="primary" id="f-buses">Record CAN + ARINC traffic</button>
        <div class="row"><button class="ghost" id="f-event">Append event</button><button class="ghost" id="f-ten">Append ×10</button></div>
        <p class="muted">Click a slot to select it, then <b>flip a byte</b> to simulate a torn write.</p>
        <button class="ghost" id="f-corrupt" disabled>Flip a byte in the selected slot</button>
      </div>
      <div class="stack" style="gap:16px">
        <div class="grid g2" style="align-items:start">
          <div class="card"><h2>Ring store <span class="muted">orange = next write</span></h2><div id="f-ring"></div></div>
          <div class="card"><h2>Replay</h2><div id="f-replay"></div></div>
        </div>
        <div class="card"><h2>Slot <span class="muted">the 32-byte frame, field by field</span></h2><div id="f-slot"><p class="muted">Select a slot.</p></div></div>
      </div>
    </div>`;
  const set = (st) => { FDR.st = st; drawFdr(); };
  $("#f-reset").onclick = async () => { FDR.sel = null; set(await api("fdr_reset", { capacity: +$("#f-cap").value })); };
  $("#f-buses").onclick = async () => set(await api("fdr_record_buses"));
  $("#f-event").onclick = async () => set(await api("fdr_append", { payload: "01", count: 1 }));
  $("#f-ten").onclick = async () => set(await api("fdr_append", { payload: "02", count: 10 }));
  $("#f-corrupt").onclick = async () => set(await api("fdr_corrupt", { slot: FDR.sel }));
  set(FDR.st ? await api("fdr_state") : await api("fdr_reset", { capacity: 16 }));
}
function drawFdr() {
  const st = FDR.st, n = st.capacity, R = 100, C = 140;
  const col = { empty: "#E3E8EE", valid: css("--f-data"), corrupt: css("--f-check") };
  let svg = `<circle cx="${C}" cy="${C}" r="${R}" fill="none" stroke="#E3E8EE" stroke-width="30"/>`;
  st.slots.forEach((s, i) => {
    const a0 = (i / n) * 2 * Math.PI - Math.PI / 2, a1 = ((i + 1) / n) * 2 * Math.PI - Math.PI / 2 - 0.03;
    const p = (a, r) => `${C + r * Math.cos(a)} ${C + r * Math.sin(a)}`;
    const big = a1 - a0 > Math.PI ? 1 : 0;
    const d = `M ${p(a0, R + 15)} A ${R + 15} ${R + 15} 0 ${big} 1 ${p(a1, R + 15)} L ${p(a1, R - 15)} A ${R - 15} ${R - 15} 0 ${big} 0 ${p(a0, R - 15)} Z`;
    svg += `<path d="${d}" fill="${col[s.state]}" stroke="${i === st.next_slot ? css("--accent") : i === FDR.sel ? "#101722" : "#fff"}" stroke-width="${i === st.next_slot || i === FDR.sel ? 3 : 1}" data-slot="${i}" style="cursor:pointer"><title>slot ${i} · ${s.state}</title></path>`;
    const am = (a0 + a1) / 2;
    svg += `<text x="${C + (R + 28) * Math.cos(am)}" y="${C + (R + 28) * Math.sin(am) + 3}" text-anchor="middle" fill="#8893A2">${i}</text>`;
  });
  svg += `<text x="${C}" y="${C - 4}" text-anchor="middle" style="font:600 26px var(--f-label)" fill="#101722">${st.replay.recovered}</text><text x="${C}" y="${C + 14}" text-anchor="middle" fill="#5B6676">frames recovered</text>`;
  $("#f-ring").innerHTML = `<svg viewBox="0 0 280 280" style="width:100%;max-width:340px;display:block;margin:auto;font:10px var(--f-num)">${svg}</svg>
    <div class="legend"><span><i style="background:var(--f-data)"></i>valid</span><span><i style="background:#E3E8EE"></i>never written</span><span><i style="background:var(--f-check)"></i>CRC fails</span></div>`;
  $$("#f-ring [data-slot]").forEach((p) => (p.onclick = () => { FDR.sel = +p.dataset.slot; drawFdr(); }));
  $("#f-replay").innerHTML = `<div class="row" style="gap:22px"><div><span class="verdict pass">${st.replay.recovered}</span><br><span class="muted">recovered, in time order</span></div>
    <div><span class="verdict ${st.replay.discarded ? "fail" : ""}">${st.replay.discarded}</span><br><span class="muted">discarded, and counted</span></div></div>
    <p class="muted">A CRC per frame, not per file: one torn write costs one frame. When the ring is full the oldest frame is overwritten; the recorder never stops.</p>`;
  $("#f-corrupt").disabled = FDR.sel == null;
  const s = FDR.sel != null ? st.slots[FDR.sel] : null;
  if (s) $("#f-slot").innerHTML = `<div class="row" style="margin-bottom:8px"><b>slot ${s.slot}</b><span class="chip ${s.state === "valid" ? "pass" : s.state === "corrupt" ? "fail" : ""}">${s.state}</span>
      ${s.source ? `<span class="chip info">${esc(s.source)}</span><span class="mono">t = ${s.t} µs</span>` : ""}</div>
      ${s.state === "empty" ? `<p class="muted">All zeros: simply never written. That is not counted as damage.</p>` : bytesRibbon(s.hex, FDR_LAYOUT)}
      ${s.payload ? `<p class="mono">payload ${esc(s.payload)}</p>` : ""}`;
}

/* ------------------------------------------------------------ files, api dialog, router */
async function saveFile(name, text) {
  if (window.pywebview?.api?.save_file) { await window.pywebview.api.save_file(name, text); return; }
  const a = Object.assign(document.createElement("a"), { href: URL.createObjectURL(new Blob([text], { type: "text/plain" })), download: name });
  a.click();
}
$("#api-open").onclick = () => {
  $("#api-code").textContent = LAST_CALL
    ? `curl -X POST ${location.origin}/api/${LAST_CALL.name} \\\n  -H "Content-Type: application/json" \\\n  -d '${JSON.stringify(LAST_CALL.body)}'`
    : "Click any button in Studio first.";
  $("#api-dlg").showModal();
};
$("#api-copy").onclick = () => navigator.clipboard.writeText($("#api-code").textContent);

const PAGES = { overview: renderOverview, can: renderCan, uds: renderUds, autosar: renderAutosar, safety: renderSafety, doip: renderDoip,
  arinc429: renderArinc429, mil1553: renderMil1553, arinc653: renderArinc653, traceability: renderTraceability, fdr: renderFdr };
let CURRENT = null;
async function route(full = true) {
  const id = (location.hash.replace("#/", "") || "overview");
  const page = PAGES[id] ? id : "overview";
  $$(".nav-link").forEach((a) => a.classList.toggle("on", a.dataset.page === page));
  if (!full && page !== "overview") return;
  const el = $("#page");
  if (CURRENT !== page) el.scrollTop = 0;
  CURRENT = page;
  try { await PAGES[page](el); } catch (e) { fail(el, e); }
}

async function health() {
  const c = $("#conn");
  try {
    const h = await fetch("/api/health").then((r) => r.json());
    c.className = "conn ok"; $("span", c).textContent = `API ${location.host} · v${h.version}`;
  } catch { c.className = "conn bad"; $("span", c).textContent = "API not reachable"; }
}

(async function boot() {
  const m = await api("modules");
  MODS = m.modules; BY = Object.fromEntries(MODS.map((x) => [x.id, x]));
  if (m.last_test) TEST = { report: m.last_test, done: [] };
  for (const d of ["automotive", "avionics"]) {
    $(`#nav-${d}`).innerHTML = MODS.filter((x) => x.domain === d).map((x) => `<a class="nav-link" href="#/${x.id}" data-page="${x.id}"><span>${esc(x.title)}</span><small>${esc(x.standard.split(" · ")[0])}</small><i class="dot" data-dot="${x.id}"></i></a>`).join("");
  }
  navDots();
  window.addEventListener("hashchange", () => route());
  route();
  health(); setInterval(health, 5000);
})();
