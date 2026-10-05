"use strict";

const state = { docs: [], lang: "en", result: null, live: false, models: {} };
const $ = (s, el = document) => el.querySelector(s);

const T = {
  en: {
    risk: { high: "High risk: don't pay yet", medium: "Some things need checking", low: "No problems found in these papers" },
    chain: "Ownership chain", flags: "Red flags", holdings: "Who holds the land now, according to these papers",
    checklist: "What to verify before you pay", how: "How Dalil checked this",
    name: "Name", dag: "Dag", area: "Area (decimals)", must: "Must do", none: "No red flags.",
    noHold: "Nobody holds a valid share according to these papers.",
  },
  bn: {
    risk: { high: "উচ্চ ঝুঁকি: এখনই টাকা দেবেন না", medium: "কিছু বিষয় যাচাই করা দরকার", low: "এই কাগজে কোনো সমস্যা পাওয়া যায়নি" },
    chain: "মালিকানার ধারাবাহিকতা", flags: "সতর্ক সংকেত", holdings: "কাগজ অনুযায়ী এখন জমির মালিক কে",
    checklist: "টাকা দেওয়ার আগে যা যাচাই করবেন", how: "দলিল কীভাবে যাচাই করেছে",
    name: "নাম", dag: "দাগ", area: "পরিমাণ (শতাংশ)", must: "অবশ্যই", none: "কোনো সতর্ক সংকেত নেই।",
    noHold: "এই কাগজ অনুযায়ী কারও বৈধ মালিকানা নেই।",
  },
};

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function fmtDate(d) {
  if (!d) return "";
  const t = new Date(d + "T00:00:00Z");
  return isNaN(t) ? d : t.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
}

// ---------- status ----------
async function loadStatus() {
  const el = $("#mode");
  try {
    const s = await (await fetch("/api/status")).json();
    state.live = s.live; state.models = s.models;
    el.textContent = s.live ? "Live: Nebius Token Factory" : "Offline: rules only";
    el.className = "mode " + (s.live ? "live" : "offline");
    el.title = s.live ? `Nemotron models via ${s.base_url}` : "Set NEBIUS_API_KEY to enable Nemotron reading and review";
  } catch { el.textContent = "Server unreachable"; }
}

// ---------- samples ----------
async function loadSamples() {
  const wrap = $("#samples");
  const list = await (await fetch("/api/samples")).json();
  wrap.innerHTML = list.map(s =>
    `<button type="button" class="sample" data-id="${esc(s.id)}" aria-pressed="false"><strong>Sample: ${esc(s.name)}</strong><span>${esc(s.description)}</span></button>`
  ).join("");
  wrap.addEventListener("click", async e => {
    const b = e.target.closest(".sample"); if (!b) return;
    wrap.querySelectorAll(".sample").forEach(x => x.setAttribute("aria-pressed", String(x === b)));
    const c = await (await fetch(`/api/samples/${encodeURIComponent(b.dataset.id)}`)).json();
    state.docs = c.documents;
    $("#p-seller").value = c.proposed?.seller ?? "";
    $("#p-dag").value = c.proposed?.dag ?? "";
    $("#p-area").value = c.proposed?.area_decimal ?? "";
    renderDocs();
    analyze();
  });
}

// ---------- document editor ----------
const partyStr = ps => (ps || []).map(p => p.share != null ? `${p.name} (${p.share})` : p.name).join(", ");
const parcelStr = ps => (ps || []).map(p => `${p.dag}: ${p.area_decimal}`).join(", ");
function parseParties(s) {
  return s.split(",").map(x => x.trim()).filter(Boolean).map(x => {
    const m = x.match(/^(.*?)\s*\(\s*([\d.\/]+)\s*\)$/);
    if (!m) return { name: x };
    let share = m[2].includes("/") ? m[2].split("/").reduce((a, b) => Number(a) / Number(b)) : Number(m[2]);
    return { name: m[1].trim(), share: isFinite(share) ? share : null };
  });
}
function parseParcels(s) {
  return s.split(",").map(x => x.trim()).filter(Boolean).map(x => {
    const [dag, area] = x.split(":").map(y => y.trim());
    return { dag: dag || "", area_decimal: Number(area) || 0 };
  });
}

function renderDocs() {
  const wrap = $("#docs");
  wrap.innerHTML = "";
  if (!state.docs.length) {
    wrap.innerHTML = `<p class="empty">No documents yet. Load a sample case or upload pages.</p>`;
  }
  state.docs.forEach((d, i) => {
    const node = $("#doc-tpl").content.firstElementChild.cloneNode(true);
    node.dataset.type = d.doc_type;
    $(".f-type", node).value = d.doc_type;
    $(".doc-src", node).textContent = d.source_file ? `${d.source_file}${d.extracted_by ? " · read by " + d.extracted_by.split("/").pop() : ""}` : (d.title || "");
    $(".f-date", node).value = d.date || "";
    $(".f-mouza", node).value = d.mouza || "";
    $(".f-khatian", node).value = d.khatian_no || "";
    $(".f-deedno", node).value = d.deed_no || "";
    $(".f-owners", node).value = partyStr(d.owners);
    $(".f-sellers", node).value = partyStr(d.sellers);
    $(".f-buyers", node).value = partyStr(d.buyers);
    $(".f-parcels", node).value = parcelStr(d.parcels);
    node.addEventListener("change", () => {
      d.doc_type = $(".f-type", node).value; node.dataset.type = d.doc_type;
      d.date = $(".f-date", node).value || null;
      d.mouza = $(".f-mouza", node).value.trim() || null;
      d.khatian_no = $(".f-khatian", node).value.trim() || null;
      d.deed_no = $(".f-deedno", node).value.trim() || null;
      d.owners = parseParties($(".f-owners", node).value);
      d.sellers = parseParties($(".f-sellers", node).value);
      d.buyers = parseParties($(".f-buyers", node).value);
      d.parcels = parseParcels($(".f-parcels", node).value);
    });
    $(".remove", node).addEventListener("click", () => { state.docs.splice(i, 1); renderDocs(); });
    wrap.appendChild(node);
  });
  $("#analyze").disabled = state.docs.length === 0;
}

$("#add-doc").addEventListener("click", () => {
  state.docs.push({ id: "H" + Date.now().toString(36), doc_type: "deed", owners: [], sellers: [], buyers: [], parcels: [] });
  renderDocs();
  $("#docs").lastElementChild?.querySelector("select")?.focus();
});

// ---------- upload ----------
const dz = $("#dropzone"), fileInput = $("#file-input");
fileInput.addEventListener("change", () => upload(fileInput.files));
["dragover", "dragenter"].forEach(ev => dz.addEventListener(ev, e => { e.preventDefault(); dz.classList.add("over"); }));
["dragleave", "drop"].forEach(ev => dz.addEventListener(ev, () => dz.classList.remove("over")));
dz.addEventListener("drop", e => { e.preventDefault(); upload(e.dataTransfer.files); });

async function upload(files) {
  if (!files?.length) return;
  const st = $("#upload-status");
  st.className = "status-line";
  st.textContent = `Reading ${files.length} page(s) with Nemotron…`;
  const fd = new FormData();
  [...files].forEach(f => fd.append("files", f));
  try {
    const r = await fetch("/api/extract", { method: "POST", body: fd });
    const body = await r.json();
    if (!r.ok) throw new Error(body.detail || "Upload failed");
    state.docs.push(...body.documents);
    renderDocs();
    const errs = body.trace.filter(t => t.status === "error");
    st.textContent = `Read ${body.documents.length} of ${files.length} page(s).` + (errs.length ? ` Couldn't read: ${errs.map(e => e.step.replace(/^Read.*?: /, "") + " (" + e.note + ")").join("; ")}` : " Check the details below.");
    if (errs.length) st.classList.add("error");
  } catch (e) {
    st.textContent = e.message; st.classList.add("error");
  }
  fileInput.value = "";
}

// ---------- analyze ----------
$("#analyze").addEventListener("click", analyze);

async function analyze() {
  if (!state.docs.length) return;
  const st = $("#analyze-status");
  st.className = "status-line"; st.textContent = "";
  const seller = $("#p-seller").value.trim(), dag = $("#p-dag").value.trim(), area = Number($("#p-area").value);
  const proposed = seller && dag && area > 0 ? { seller, dag, area_decimal: area } : null;
  $("#analyze").disabled = true;
  $("#report-body").innerHTML = `<div class="working"><span class="dot" aria-hidden="true"></span><span>${state.live ? "Rebuilding the chain and asking Nemotron 3 Ultra to review it…" : "Rebuilding the ownership chain…"}</span></div>`;
  try {
    const r = await fetch("/api/analyze", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ documents: state.docs, proposed, language: state.lang }),
    });
    const body = await r.json();
    if (!r.ok) throw new Error(typeof body.detail === "string" ? body.detail : "Check the document details and try again.");
    state.result = body;
    renderReport();
    if (window.matchMedia("(max-width: 900px)").matches) $("#report-title").scrollIntoView({ behavior: "smooth" });
  } catch (e) {
    $("#report-body").innerHTML = `<p class="status-line error">${esc(e.message)}</p>`;
  } finally {
    $("#analyze").disabled = state.docs.length === 0;
  }
}

// ---------- report ----------
function renderReport() {
  const R = state.result; if (!R) return;
  const t = T[state.lang];
  const flagById = Object.fromEntries(R.flags.map(f => [f.id, f]));
  const placed = new Set(R.timeline.flatMap(e => e.flag_ids));
  const stamp = f => `<div class="stamp ${f.severity}"><b>${esc(f.title)}</b>${esc(f.detail)}${f.explanation ? `<span class="why">${esc(f.explanation)}</span>` : ""}</div>`;

  const ledger = R.timeline.map(e => {
    const who = e.kind === "sale" || e.kind === "proposed"
      ? `${esc(e.sellers.join(", "))}<span class="arrow" aria-label="to">→</span>${esc(e.buyers.join(", "))}`
      : esc(e.buyers.join(", "));
    const land = e.parcels.map(p => `dag ${esc(p.dag)}, ${esc(p.area_decimal)} dec.`).join("; ");
    return `<li class="entry k-${e.kind}${e.flag_ids.length ? " flagged" : ""}">
      <span class="node" aria-hidden="true"></span>
      <div class="entry-date">${esc(fmtDate(e.date) || (e.kind === "proposed" ? "Now" : "Undated"))}</div>
      <div class="entry-title">${esc(e.label)}</div>
      <p class="entry-line">${who}${land ? ` · ${land}` : ""}</p>
      ${e.flag_ids.map(id => flagById[id] ? stamp(flagById[id]) : "").join("")}
    </li>`;
  }).join("");

  const loose = R.flags.filter(f => !placed.has(f.id));
  const holdings = R.holdings.length
    ? `<table class="holdings"><thead><tr><th>${t.name}</th><th>${t.dag}</th><th class="num">${t.area}</th></tr></thead><tbody>${R.holdings.map(h => `<tr><td>${esc(h.name)}</td><td>${esc(h.dag)}</td><td class="num">${esc(h.area_decimal)}</td></tr>`).join("")}</tbody></table>`
    : `<p>${t.noHold}</p>`;

  const checklist = R.checklist.map((c, i) =>
    `<li><label><input type="checkbox" id="ck${i}"><span lang="${state.lang}">${esc(c[state.lang])}${c.priority === "must" ? `<span class="must">${t.must}</span>` : ""}</span></label></li>`
  ).join("");

  const trace = R.trace.map(s =>
    `<li>${esc(s.step)} ${s.model ? `<span class="model">${esc(s.model.split("/").pop())}</span>` : `<span class="model">rules engine</span>`}
      <span class="tstat ${s.status}">${esc(s.status)}${s.latency_ms ? ` · ${(s.latency_ms / 1000).toFixed(1)} s` : ""}${s.note ? ` · ${esc(s.note)}` : ""}</span></li>`
  ).join("");

  $("#report-body").innerHTML = `
    <div class="verdict ${R.risk}">
      <h3 lang="${state.lang}">${t.risk[R.risk]}</h3>
      <p lang="${state.lang}">${esc(state.lang === "bn" ? R.summary_bn : R.summary_en)}</p>
    </div>
    <h4>${t.chain}</h4>
    <ol class="ledger">${ledger}</ol>
    ${loose.length ? `<h4>${t.flags}</h4><div class="flag-list">${loose.map(stamp).join("")}</div>` : ""}
    ${!R.flags.length ? `<p>${t.none}</p>` : ""}
    <h4>${t.holdings}</h4>
    ${holdings}
    <h4>${t.checklist}</h4>
    <ul class="checklist">${checklist}</ul>
    <details class="trace"><summary>${t.how}</summary><ol>${trace}</ol></details>
    <p class="disclaimer">${esc(R.disclaimer)}</p>`;
}

// ---------- language ----------
document.querySelectorAll(".lang-toggle button").forEach(b => b.addEventListener("click", () => {
  state.lang = b.dataset.lang;
  document.querySelectorAll(".lang-toggle button").forEach(x => x.setAttribute("aria-pressed", String(x === b)));
  renderReport();
}));

loadStatus();
loadSamples();
