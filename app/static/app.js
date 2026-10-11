"use strict";
/* Bitácora · NOC Syslog Inteligente - panel de operación.
   REGLA DE ORO: todo texto que viene de logs o de usuarios se inserta como TEXTO
   (createTextNode / textContent). Nunca se construye HTML a partir de datos. */

const $ = (sel, root = document) => root.querySelector(sel);
const SEV = ["Emergency", "Alert", "Critical", "Error", "Warning", "Notice", "Informational", "Debug"];
const STATUS_ES = { open: "Abierto", assigned: "Asignado", in_progress: "En curso", resolved: "Resuelto", closed: "Cerrado" };
const HEALTH_ES = { critico: "Crítico", alerta: "Alerta", ok: "Normal", "sin-datos": "Sin datos", inactivo: "Inactivo", mantenimiento: "Mantenimiento" };
const NS = "http://www.w3.org/2000/svg";

const TABS = {
  resumen: { title: "Panorama", deck: "" },   // el texto lo compone loadSummary con las cifras del momento
  eventos: { title: "Eventos", deck: "Lo que escribieron los equipos, del más reciente al más antiguo. Abre una línea para ver su evidencia original." },
  incidentes: { title: "Incidentes", deck: "Los casos en curso, quién los lleva y cómo se cerraron." },
  consola: { title: "Consola", deck: "Sesión simulada de solo lectura. Cada comando bloqueado queda en la auditoría." },
  plantillas: { title: "Plantillas", deck: "Propuestas de configuración comentadas. Nada se envía a los equipos." },
};

const state = { tab: "resumen", hours: 24, devices: [], filters: new URLSearchParams(),
                evOffset: 0, evLimit: 25, lastMaxId: null, timer: null, plotted: false };

/* ---------- utilidades ---------- */
const store = {
  get(k) { try { return localStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch { /* sin almacenamiento */ } },
};

// Crea un elemento HTML. Los hijos string se insertan como texto.
function el(tag, attrs = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k === "class") e.className = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else e.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat(Infinity)) {
    if (kid == null || kid === false) continue;
    e.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  }
  return e;
}
// Igual, para SVG.
function s(tag, attrs = {}, ...kids) {
  const e = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  for (const kid of kids.flat(Infinity)) e.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  return e;
}

const utc = (str) => new Date(str.replace(" ", "T") + "Z");   // el servidor guarda UTC
const fmt = (str) => str ? utc(str).toLocaleString("es-CO", { dateStyle: "short", timeStyle: "medium" }) : "—";
const hourLabel = (h, short = false) => {
  const d = utc(h + ":00");
  return short ? String(d.getHours()).padStart(2, "0") + "h"
               : d.toLocaleString("es-CO", { dateStyle: "short", timeStyle: "short" });
};
const pill = (sev) => el("span", { class: `pill sev-${sev}` }, `${sev} ${SEV[sev]}`);
const clip = (t, n) => (t.length > n ? t.slice(0, n - 1) + "…" : t);
const plural = (n, one, many) => (n === 1 ? one : many);
const sinceUtc = (hours) => new Date(Date.now() - hours * 3600e3).toISOString().slice(0, 19).replace("T", " ");

// Hace visibles los caracteres de control o invisibles (ESC, bidireccionales...) de la evidencia.
function revealRaw(text) {
  return Array.from(text).map((ch) => {
    const c = ch.codePointAt(0);
    const hidden = (c < 32 && c !== 10) || (c >= 0x7f && c <= 0x9f) || (c >= 0x200b && c <= 0x200f) ||
                   (c >= 0x202a && c <= 0x202e) || (c >= 0x2066 && c <= 0x2069);
    return hidden ? "\\u" + c.toString(16).padStart(4, "0") : ch;
  }).join("");
}

function toast(msg, kind = "info") {
  const t = el("div", { class: `toast-item ${kind}` }, msg);
  const box = $("#toast");
  box.append(t);
  // Popover: se dibuja por encima de los diálogos modales.
  if (box.showPopover && !box.matches(":popover-open")) box.showPopover();
  setTimeout(() => {
    t.remove();
    if (!box.children.length && box.matches(":popover-open")) box.hidePopover();
  }, 5000);
}

const actor = () => (store.get("noc.actor") || "").replace(/[^\w .@-]/g, "").trim().slice(0, 64) || "anonymous";

function formatError(data, status) {
  if (data && typeof data.detail === "string") return data.detail;
  if (data && Array.isArray(data.detail)) {
    return data.detail.map((d) => `${(d.loc || []).slice(1).join(".")}: ${d.msg}`).join("; ");
  }
  return `Error ${status}`;
}

async function api(path, opts = {}) {
  const method = opts.method || "GET";
  const headers = { Accept: "application/json" };
  if (opts.body) headers["Content-Type"] = "application/json";
  if (method !== "GET") headers["X-Actor"] = actor();   // temporal: se reemplaza por la sesión autenticada
  const res = await fetch(path, { method, headers, body: opts.body ? JSON.stringify(opts.body) : undefined });
  if (res.status === 204) return null;
  const data = await res.json().catch(() => null);
  if (!res.ok) throw new Error(formatError(data, res.status));
  return data;
}

/* ---------- tema: papel (claro) y plano nocturno (oscuro) ---------- */
function applyTheme(t) { document.documentElement.dataset.theme = t; store.set("bitacora.theme", t); }
function toggleTheme() {
  const cur = document.documentElement.dataset.theme;
  const dark = cur === "dark" || (cur === "auto" && matchMedia("(prefers-color-scheme: dark)").matches);
  applyTheme(dark ? "light" : "dark");
}

/* ---------- panorama ---------- */
async function loadSummary() {
  const [d, tl] = await Promise.all([
    api(`/api/dashboard/summary?hours=${state.hours}`),
    api(`/api/events?limit=500&date_from=${encodeURIComponent(sinceUtc(state.hours))}`),
  ]);
  renderDeck(d);
  renderKpis(d);
  renderMap(d.devices);
  renderTimeline(tl, d.devices, state.hours);
  renderDevices(d.devices);
  renderRecent(d.recent);
  renderSeverity(d.by_severity);
  renderTrend(d.timeline);
  renderHeat(d.heatmap, d.timeline.map((t) => t.hour));
}

// Frase de apertura: resume el estado con las cifras del momento.
function renderDeck(d) {
  const k = d.kpis, n = k.occurrences;
  let text;
  if (n === 0) {
    text = `No llegó ningún mensaje en las últimas ${d.hours} h. Genera tráfico simulado desde /docs para poblar el panel.`;
  } else {
    const parts = [`En las últimas ${d.hours} h llegaron ${n} ${plural(n, "mensaje", "mensajes")}.`];
    parts.push(k.errors === 0
      ? "Ninguno es un error."
      : `${k.errors} ${plural(k.errors, "es un error", "son errores")}, entre ellos ${k.critical} ${plural(k.critical, "crítico", "críticos")}.`);
    const a = d.incidents.active;
    parts.push(a === 0 ? "No hay incidentes activos." : `Hay ${a} ${plural(a, "incidente activo", "incidentes activos")}.`);
    if (k.suspicious > 0) {
      parts.push(`${k.suspicious} ${plural(k.suspicious, "evento está etiquetado como sospechoso", "eventos están etiquetados como sospechosos")}.`);
    }
    text = parts.join(" ");
  }
  if (state.tab === "resumen") $("#page-deck").textContent = text;
}

function spark(values) {
  const W = 84, H = 24, max = Math.max(1, ...values), n = values.length;
  const pts = values.map((v, i) =>
    `${(n === 1 ? W : (i / (n - 1)) * W).toFixed(1)},${(H - 2 - (v / max) * (H - 4)).toFixed(1)}`).join(" ");
  return s("svg", { viewBox: `0 0 ${W} ${H}`, class: "spark", "aria-hidden": "true" }, s("polyline", { points: pts }));
}

function renderKpis(d) {
  const k = d.kpis, tl = d.timeline;
  const rows = [
    { label: "Mensajes recibidos", value: k.occurrences, note: `${k.events} eventos únicos tras deduplicar`, spark: tl.map((t) => t.total), tone: "" },
    { label: "Críticos", value: k.critical, note: "severidad 0 a 2", tone: k.critical > 0 ? "bad" : "" },
    { label: "Errores", value: k.errors, note: "severidad 0 a 3", spark: tl.map((t) => t.errors), tone: k.errors > 0 ? "warn" : "" },
    { label: "Incidentes activos", value: d.incidents.active, note: `${d.incidents.open} en estado abierto`, tone: "" },
    { label: "Sospechosos", value: k.suspicious, note: "eventos con la etiqueta sospechoso", tone: k.suspicious > 0 ? "warn" : "" },
  ];
  $("#kpis").replaceChildren(...rows.map((r) =>
    el("li", { class: `ledger-row ${r.tone}` },
      el("div", { class: "l-text" }, el("span", { class: "l-label" }, r.label), el("span", { class: "l-note" }, r.note)),
      el("span", { class: "l-lead" }),
      el("span", { class: "l-spark" }, r.spark ? spark(r.spark) : null),
      el("span", { class: "l-val" }, r.value))));
}

// Mapa de fuentes: el NOC al centro y cada equipo alrededor. No es la topología física: muestra quién escribe en la bitácora.
function renderMap(devs) {
  const box = $("#map");
  if (!devs.length) { box.replaceChildren(el("p", { class: "empty" }, "Sin equipos en el inventario. Ejecuta python -m scripts.seed_demo.")); return; }
  const W = 480, H = 360, cx = W / 2, cy = H / 2 - 4, R = 124;
  const max = Math.max(1, ...devs.map((d) => d.occurrences));
  const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Mapa de fuentes de log" });
  const pos = devs.map((d, i) => {
    const a = -Math.PI / 2 + (2 * Math.PI * i) / devs.length;
    return { d, x: cx + R * Math.cos(a) * 1.25, y: cy + R * Math.sin(a) };
  });
  pos.forEach(({ d, x, y }) => svg.append(s("line", {
    x1: cx, y1: cy, x2: x.toFixed(1), y2: y.toFixed(1), class: `link h-${d.health}`,
    "stroke-width": (1.2 + 5 * Math.sqrt(d.occurrences / max)).toFixed(1) })));
  svg.append(s("circle", { cx, cy, r: 30, class: "hub" }), s("text", { x: cx, y: cy + 4.5, class: "hub-label" }, "NOC"));
  pos.forEach(({ d, x, y }) => {
    const r = 15 + 10 * Math.sqrt(d.occurrences / max);
    const letter = { cisco: "C", fortinet: "F", huawei: "H" }[d.vendor] || "?";
    const above = y < cy;
    const g = s("g", { class: "node", tabindex: "0", role: "link", "aria-label": `Ver eventos de ${d.name}` },
      s("title", {}, `${d.name} · ${HEALTH_ES[d.health]} · ${d.occurrences} mensajes`),
      s("circle", { cx: x.toFixed(1), cy: y.toFixed(1), r: r.toFixed(1), class: `node-dot h-${d.health}` }),
      s("text", { x: x.toFixed(1), y: (y + 5).toFixed(1), class: "node-letter" }, letter),
      s("text", { x: x.toFixed(1), y: (above ? y - r - 18 : y + r + 15).toFixed(1), class: "node-name" }, clip(d.name, 18)),
      s("text", { x: x.toFixed(1), y: (above ? y - r - 6 : y + r + 27).toFixed(1), class: "node-sub" }, `${d.occurrences} msg`));
    g.addEventListener("click", () => goDevice(d.name));
    g.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); goDevice(d.name); } });
    svg.append(g);
  });
  box.replaceChildren(svg);
}

// Cronología: un carril por equipo, un punto por evento sobre un eje de horas.
function renderTimeline(events, devices, hours) {
  const box = $("#timeline");
  $("#tl-note").textContent = events.length >= 500 ? "Se muestran los 500 eventos más recientes de la ventana." : "";
  if (!events.length) {
    box.replaceChildren(el("p", { class: "empty" }, "No hay eventos en esta ventana. Amplíala o genera tráfico simulado desde /docs."));
    return;
  }
  const lanes = devices.map((d) => d.name);
  events.forEach((e) => { const n = e.device_name || "(desconocido)"; if (!lanes.includes(n)) lanes.push(n); });
  const laneIndex = new Map(lanes.map((n, i) => [n, i]));
  const W = 1000, L = 160, R = 30, T = 18, laneH = 38, B = 32;
  const H = T + lanes.length * laneH + B;
  const end = Date.now(), start = end - hours * 3600e3;
  const x = (t) => L + ((t - start) / (end - start)) * (W - L - R);
  const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": `Cronología de eventos de las últimas ${hours} horas` });

  const first = new Date(start); first.setMinutes(0, 0, 0); first.setHours(first.getHours() + 1);
  const step = hours <= 6 ? 1 : hours <= 24 ? 3 : hours <= 48 ? 6 : 12;
  for (let t = first.getTime(); t <= end; t += 3600e3) {
    const hr = new Date(t).getHours(), major = hr % step === 0;
    svg.append(s("line", { x1: x(t).toFixed(1), y1: T, x2: x(t).toFixed(1), y2: H - B, class: major ? "gridv major" : "gridv" }));
    if (major) svg.append(s("text", { x: x(t).toFixed(1), y: H - 12, class: "tick" }, `${String(hr).padStart(2, "0")}h`));
  }
  lanes.forEach((name, i) => {
    const y = T + i * laneH + laneH / 2;
    svg.append(s("line", { x1: L, y1: y, x2: W - R, y2: y, class: "lane" }),
               s("text", { x: L - 14, y: y + 4.5, class: "lane-label" }, clip(name, 20)));
  });

  const dots = s("g", { class: "dots" });
  events.slice().sort((a, b) => b.severity - a.severity).forEach((e) => {     // lo más grave se dibuja encima
    const t = utc(e.received_at).getTime();
    if (t < start || t > end) return;
    const i = laneIndex.get(e.device_name || "(desconocido)");
    const cy = T + i * laneH + laneH / 2 + (((e.id * 7) % 9) - 4);
    const r = 3.6 + Math.min(5, Math.log2(e.repeat_count || 1) * 0.9);
    const c = s("circle", { cx: x(t).toFixed(1), cy: cy.toFixed(1), r: r.toFixed(1), class: `dot sev-${e.severity}` },
      s("title", {}, `${fmt(e.received_at)} · ${e.severity} ${SEV[e.severity]} · ${e.device_name || "desconocido"}` +
        `${e.repeat_count > 1 ? ` · ×${e.repeat_count}` : ""}\n${clip(e.message, 140)}`));
    c.addEventListener("click", () => openEvent(e.id).catch((err) => toast(err.message, "err")));
    dots.append(c);
  });
  svg.append(dots,
    s("line", { x1: x(end).toFixed(1), y1: T - 6, x2: x(end).toFixed(1), y2: H - B, class: "now" }),
    s("text", { x: (x(end) - 8).toFixed(1), y: 12, class: "now-tag" }, "ahora"));
  if (!state.plotted) { svg.classList.add("sweep"); state.plotted = true; }   // el único movimiento de la pantalla
  box.replaceChildren(svg);
}

function renderDevices(devs) {
  $("#dev-body").replaceChildren(...devs.map((d) =>
    el("tr", { class: "click", onclick: () => goDevice(d.name) },
      el("td", { class: "name" }, d.name, d.is_simulated ? el("span", { class: "chip" }, "sim") : null),
      el("td", {}, d.vendor), el("td", { class: "mono" }, d.ip_address), el("td", {}, d.status),
      el("td", {}, el("span", { class: `pill h-${d.health}` }, HEALTH_ES[d.health])),
      el("td", { class: "num" }, d.occurrences), el("td", { class: "mono" }, fmt(d.last_event)))));
}

function renderSeverity(rows) {
  const max = Math.max(1, ...rows.map((r) => r.occurrences));
  const rowH = 26, barX = 118, barW = 300;
  const svg = s("svg", { viewBox: `0 0 520 ${rowH * 8 + 6}`, role: "img", "aria-label": "Mensajes por severidad" });
  rows.forEach((r, i) => {
    const y = i * rowH + 3, w = Math.round((r.occurrences / max) * barW);
    svg.append(
      s("text", { x: 0, y: y + 16, class: "lbl" }, `${r.severity} ${SEV[r.severity]}`),
      s("rect", { x: barX, y: y + 4, width: Math.max(w, r.occurrences > 0 ? 2 : 0), height: 15, class: `bar sev-${r.severity}` },
        s("title", {}, `${r.events} eventos, ${r.occurrences} mensajes`)),
      s("text", { x: barX + w + 8, y: y + 16, class: "num-lbl" }, r.occurrences));
  });
  $("#chart-sev").replaceChildren(svg);
}

function renderTrend(tl) {
  const W = 620, H = 190, L = 36, B = 24, T = 8, n = tl.length;
  const bw = (W - L - 6) / n, ph = H - B - T, max = Math.max(1, ...tl.map((t) => t.total));
  const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Mensajes por hora" });
  [0.5, 1].forEach((f) => svg.append(s("line", { x1: L, y1: H - B - f * ph, x2: W, y2: H - B - f * ph, class: "gridh" })));
  svg.append(
    s("text", { x: 0, y: T + 9, class: "num-lbl" }, max), s("text", { x: 0, y: H - B, class: "num-lbl" }, "0"),
    s("line", { x1: L, y1: H - B, x2: W, y2: H - B, class: "axis" }));
  const step = Math.ceil(n / 12);
  tl.forEach((t, i) => {
    const x = L + i * bw, h1 = (t.total / max) * ph, h2 = (t.errors / max) * ph, w = Math.max(bw - 2, 1);
    svg.append(
      s("rect", { x: x + 1, y: H - B - h1, width: w, height: h1, class: "bar-total" },
        s("title", {}, `${hourLabel(t.hour)}: ${t.total} mensajes, ${t.errors} errores`)),
      s("rect", { x: x + 1, y: H - B - h2, width: w, height: h2, class: "bar-err" }));
    if (i % step === 0) svg.append(s("text", { x, y: H - 7, class: "num-lbl" }, hourLabel(t.hour, true)));
  });
  $("#chart-trend").replaceChildren(svg);
}

function heatLevel(c, max) { return c <= 0 ? 0 : 1 + Math.min(4, Math.floor((c / max) * 5)); }

function renderHeat(h, hours) {
  if (!h.devices.length) { $("#heat").replaceChildren(el("p", { class: "empty" }, "Sin equipos en el inventario.")); return; }
  const step = Math.ceil(hours.length / 12);
  const head = el("tr", {}, el("th", {}), hours.map((hr, i) => el("th", {}, i % step === 0 ? hourLabel(hr, true) : "")));
  const rows = h.devices.map((dev) => el("tr", {},
    el("th", { class: "rowh" }, dev.name),
    dev.counts.map((c, i) => el("td", { class: `heat-${heatLevel(c, h.max)}`, title: `${dev.name} · ${hourLabel(hours[i])}: ${c}` }))));
  $("#heat").replaceChildren(el("table", { class: "heat" }, head, rows));
}

function renderRecent(list) {
  $("#recent").replaceChildren(...(list.length ? list.map((e) =>
    el("li", { class: "click", onclick: () => openEvent(e.id).catch((err) => toast(err.message, "err")) },
      pill(e.severity), el("strong", {}, e.device_name || e.source_ip || "?"),
      el("span", { class: "when" }, fmt(e.received_at)), el("span", { class: "msg-inline" }, e.message)))
    : [el("li", { class: "muted" }, "Sin eventos graves en esta ventana.")]));
}

function goDevice(name) {
  $("#f-device").value = name;
  try { state.filters = collectFilters(); } catch (err) { toast(err.message, "err"); return; }
  state.evOffset = 0;
  showTab("eventos");
}

/* ---------- eventos ---------- */
function collectFilters() {
  const p = new URLSearchParams();
  const v = (id) => $(id).value.trim();
  if (v("#f-from")) p.set("date_from", v("#f-from"));
  if (v("#f-to")) p.set("date_to", v("#f-to"));
  if (v("#f-vendor")) p.set("vendor", v("#f-vendor"));
  const dn = v("#f-device");
  if (dn) {
    const d = state.devices.find((x) => x.name.toLowerCase() === dn.toLowerCase());
    if (!d) throw new Error(`Equipo no encontrado: ${dn}`);
    p.set("device_id", d.id);
  }
  const sev = v("#f-sev");
  if (sev) { const [mode, n] = sev.split(":"); p.set(mode === "max" ? "max_severity" : "severity", n); }
  if (v("#f-tag")) p.set("tag", v("#f-tag").toLowerCase());
  if (v("#f-sim")) p.set("simulated", v("#f-sim"));
  if (v("#f-q")) p.set("q", v("#f-q"));
  return p;
}

function eventRow(e) {
  return el("tr", { class: e.tags.includes("sospechoso") ? "suspect" : "" },
    el("td", { class: "mono" }, fmt(e.received_at)),
    el("td", {}, pill(e.severity)),
    el("td", { class: "name" }, e.device_name || e.hostname || e.source_ip || "—"),
    el("td", {}, e.vendor || "—"),
    el("td", { class: "mono" }, e.facility_name),
    el("td", { class: "msg", title: e.message }, e.message),
    el("td", {}, e.tags.map((t) => el("span", { class: "chip" + (t === "sospechoso" ? " chip-bad" : "") }, t))),
    el("td", { class: "num" }, e.repeat_count > 1 ? `×${e.repeat_count}` : ""),
    el("td", { class: "acts" },
      el("button", { type: "button", onclick: () => openEvent(e.id).catch((err) => toast(err.message, "err")) }, "Ver"), " ",
      el("button", { type: "button", onclick: () => newIncidentFromEvent(e) }, "Incidente")));
}

async function loadEvents() {
  const p = new URLSearchParams(state.filters);
  p.set("limit", state.evLimit + 1);          // uno extra para saber si hay página siguiente
  p.set("offset", state.evOffset);
  const evs = await api("/api/events?" + p);
  const rows = evs.slice(0, state.evLimit);
  $("#ev-body").replaceChildren(...rows.map(eventRow));
  $("#ev-page").textContent = rows.length ? `Mostrando ${state.evOffset + 1}–${state.evOffset + rows.length}` : "Sin resultados";
  $("#ev-prev").disabled = state.evOffset === 0;
  $("#ev-next").disabled = evs.length <= state.evLimit;
}

const kv = (pairs) => el("dl", { class: "kv" }, pairs.map(([k, v]) => [el("dt", {}, k), el("dd", {}, v)]));

async function openEvent(id) {
  const e = await api(`/api/events/${id}`);
  const dlg = $("#dlg-event");
  dlg.replaceChildren(el("div", {},
    el("h2", {}, `Evento #${e.id}`),
    kv([["Recibido (hora local)", fmt(e.received_at)],
        ["Hora declarada por el equipo (no confiable)", e.event_time || "—"],
        ["Equipo", e.device_name || e.hostname || "desconocido"],
        ["IP de origen", e.source_ip || "—"],
        ["Facility", `${e.facility} ${e.facility_name}`],
        ["Severidad", `${e.severity} ${e.severity_name}`],
        ["Repeticiones", e.repeat_count],
        ["Origen del dato", e.is_simulated ? "Simulado" : "Real"]]),
    el("div", {}, e.tags.map((t) => el("span", { class: "chip" + (t === "sospechoso" ? " chip-bad" : "") }, t))),
    el("h3", {}, "Mensaje saneado"), el("pre", {}, e.message),
    el("h3", {}, "Evidencia original (contenido no confiable)"),
    el("p", { class: "warn-text" }, e.warning),
    el("pre", { class: "raw" }, revealRaw(e.raw_message || "")),
    el("div", { class: "dlg-actions" },
      el("button", { type: "button", class: "primary", onclick: () => { dlg.close(); newIncidentFromEvent(e); } }, "Crear incidente"),
      el("button", { type: "button", onclick: () => dlg.close() }, "Cerrar"))));
  if (!dlg.open) dlg.showModal();
}

/* ---------- incidentes ---------- */
async function loadIncidents() {
  const p = new URLSearchParams();
  const st = $("#i-status").value;
  if (st === "active") p.set("active", "true"); else if (st) p.set("status", st);
  const list = await api("/api/incidents?" + p);
  $("#inc-body").replaceChildren(...(list.length ? list.map((i) =>
    el("tr", { class: "click", onclick: () => openIncident(i.id).catch((e) => toast(e.message, "err")) },
      el("td", { class: "mono" }, i.id), el("td", {}, i.title), el("td", {}, pill(i.severity)),
      el("td", {}, el("span", { class: `pill st-${i.status}` }, STATUS_ES[i.status])),
      el("td", { class: "name" }, i.device_name || "—"), el("td", {}, i.assigned_to || "—"),
      el("td", { class: "num" }, i.events_count), el("td", { class: "mono" }, fmt(i.updated_at))))
    : [el("tr", {}, el("td", { colspan: 8, class: "muted" }, "No hay incidentes con este filtro."))]));
}

function newIncidentFromEvent(e) {
  openNewIncident({
    title: `${e.severity_name}: ${clip(e.message, 90)}`,
    severity: e.severity, device_id: e.device_id, event_ids: [e.id],
  });
}

function openNewIncident(pre = {}) {
  const dlg = $("#dlg-inc-new");
  const title = el("input", { maxlength: 120, required: true, value: pre.title || "" });
  const desc = el("textarea", { maxlength: 2000, rows: 3 }, pre.description || "");
  const sev = el("select", {}, SEV.map((n, i) => el("option", { value: i, selected: i === (pre.severity ?? 4) }, `${i} ${n}`)));
  const dev = el("select", {}, el("option", { value: "" }, "(sin equipo)"),
    state.devices.map((d) => el("option", { value: d.id, selected: d.id === pre.device_id }, d.name)));
  const asg = el("input", { maxlength: 64, placeholder: "opcional" });
  const ids = pre.event_ids || [];
  const form = el("form", {
    onsubmit: async (ev) => {
      ev.preventDefault();
      const body = { title: title.value.trim(), description: desc.value.trim() || null, severity: Number(sev.value),
                     device_id: dev.value ? Number(dev.value) : null, assigned_to: asg.value.trim() || null, event_ids: ids };
      try {
        await api("/api/incidents", { method: "POST", body });
        dlg.close(); toast("Incidente creado", "ok"); showTab("incidentes");
      } catch (err) { toast(err.message, "err"); }
    },
  },
    el("label", {}, "Título", title), el("label", {}, "Descripción", desc),
    el("label", {}, "Severidad", sev), el("label", {}, "Equipo", dev), el("label", {}, "Asignar a", asg),
    el("p", { class: "muted" }, ids.length ? `Eventos vinculados: ${ids.map((i) => "#" + i).join(", ")}` : "Sin eventos vinculados"),
    el("div", { class: "dlg-actions" },
      el("button", { type: "submit" }, "Crear incidente"),
      el("button", { type: "button", onclick: () => dlg.close() }, "Cancelar")));
  dlg.replaceChildren(el("div", {}, el("h2", {}, "Nuevo incidente"), form));
  if (!dlg.open) dlg.showModal();
}

function describe(h) {
  const d = h.details || {};
  if (h.action === "incident.note") return `Nota: ${d.text}`;
  if (h.action === "incident.create") return `Creado: ${d.title} (sev ${d.severity})`;
  if (h.action === "incident.update") {
    const FIELD = { status: "estado", assigned_to: "asignado a", severity: "severidad", title: "título", description: "descripción" };
    const tr = (k, v) => (k === "status" && STATUS_ES[v]) ? STATUS_ES[v] : (v ?? "—");
    const ch = Object.keys(d.despues || {})
      .map((k) => `${FIELD[k] || k}: ${tr(k, d.antes?.[k])} → ${tr(k, d.despues[k])}`).join("; ");
    return `Cambios: ${ch}` + (d.nota ? ` · Nota: ${d.nota}` : "");
  }
  return h.action;
}

async function openIncident(id) {
  const [inc, hist] = await Promise.all([api(`/api/incidents/${id}`), api(`/api/incidents/${id}/history`)]);
  const dlg = $("#dlg-inc");
  const closed = inc.status === "closed";
  const act = async (fn) => {
    try { await fn(); await openIncident(id); await loadIncidents(); }
    catch (err) { toast(err.message, "err"); }
  };
  const patch = (body) => api(`/api/incidents/${id}`, { method: "PATCH", body });

  const asg = el("input", { maxlength: 64, value: inc.assigned_to || "", placeholder: "persona responsable" });
  const next = el("select", {}, inc.allowed_next.map((s2) => el("option", { value: s2 }, STATUS_ES[s2])));
  const stNote = el("input", { maxlength: 500, placeholder: "nota (obligatoria al resolver o cerrar)" });
  const note = el("input", { maxlength: 500, placeholder: "agregar nota de seguimiento" });

  const actions = closed
    ? [el("p", { class: "muted" }, "Incidente cerrado: es de solo lectura.")]
    : [
        el("h3", {}, "Asignación"),
        el("div", { class: "row" }, asg, el("button", { type: "button", onclick: () => act(() => patch({ assigned_to: asg.value.trim() })) }, "Asignar")),
        el("h3", {}, "Cambiar estado"),
        el("div", { class: "row" }, next, stNote,
          el("button", { type: "button", onclick: () => act(() => patch({ status: next.value, note: stNote.value.trim() || null })) }, "Aplicar")),
        el("h3", {}, "Nota de seguimiento"),
        el("div", { class: "row" }, note,
          el("button", { type: "button", onclick: () => act(() => api(`/api/incidents/${id}/notes`, { method: "POST", body: { text: note.value.trim() } })) }, "Agregar")),
      ];

  dlg.replaceChildren(el("div", {},
    el("h2", {}, `Incidente #${inc.id}: ${inc.title}`),
    el("div", {}, pill(inc.severity), " ", el("span", { class: `pill st-${inc.status}` }, STATUS_ES[inc.status])),
    kv([["Equipo", inc.device_name || "—"], ["Asignado a", inc.assigned_to || "—"],
        ["Creado", fmt(inc.created_at)], ["Actualizado", fmt(inc.updated_at)], ["Cerrado", fmt(inc.closed_at)]]),
    inc.description ? el("pre", {}, inc.description) : null,
    el("h3", {}, `Eventos vinculados (${inc.events.length})`),
    el("ul", { class: "plain" }, inc.events.length ? inc.events.map((e) =>
      el("li", {}, pill(e.severity), el("strong", {}, e.device_name || "?"),
        el("span", { class: "msg-inline" }, e.message),
        el("button", { type: "button", onclick: () => openEvent(e.id).catch((er) => toast(er.message, "err")) }, "Ver")))
      : [el("li", { class: "muted" }, "Sin eventos vinculados")]),
    actions,
    el("h3", {}, "Historial"),
    el("ol", { class: "hist" }, hist.slice().reverse().map((h) =>
      el("li", {}, el("small", { class: "muted" }, `${fmt(h.timestamp)} · ${h.actor}`), el("div", {}, describe(h))))),
    el("div", { class: "dlg-actions" }, el("button", { type: "button", onclick: () => dlg.close() }, "Cerrar"))));
  if (!dlg.open) dlg.showModal();
}

/* ---------- notificaciones ---------- */
function notify(e) {
  const who = e.device_name || e.source_ip || "?";
  toast(`[${SEV[e.severity]}] ${who}: ${clip(e.message, 120)}`, "alert");
  if ("Notification" in window && Notification.permission === "granted") {
    new Notification(`Bitácora · ${SEV[e.severity]} en ${who}`, { body: clip(e.message, 140) });   // solo texto
  }
}

async function checkNotifications() {
  const lvl = $("#notify").value;
  if (lvl === "") return;
  const evs = await api(`/api/events?max_severity=${encodeURIComponent(lvl)}&limit=10`);
  const maxId = evs.reduce((m, e) => Math.max(m, e.id), 0);
  if (state.lastMaxId !== null) evs.filter((e) => e.id > state.lastMaxId).reverse().forEach(notify);
  state.lastMaxId = Math.max(state.lastMaxId || 0, maxId);
}

/* ---------- navegación y arranque ---------- */
async function refresh() {
  try {
    if (state.tab === "resumen") await loadSummary();
    else if (state.tab === "eventos") await loadEvents();
    else if (state.tab === "incidentes") await loadIncidents();
    else await loadConsolePanel();   // pestañas Consola y Plantillas (en console.js)
    await checkNotifications();
    $("#updated").textContent = "Actualizado " + new Date().toLocaleTimeString("es-CO");
  } catch (err) { toast(err.message, "err"); }
}

function showTab(name) {
  state.tab = name;
  document.querySelectorAll(".tab").forEach((sec) => { sec.hidden = sec.id !== `tab-${name}`; });
  document.querySelectorAll("[data-tab]").forEach((b) => {
    const on = b.dataset.tab === name;
    b.classList.toggle("active", on);
    if (on) b.setAttribute("aria-current", "page"); else b.removeAttribute("aria-current");
  });
  const t = TABS[name];
  $("#page-title").textContent = t.title;
  $("#page-deck").textContent = t.deck;
  document.title = `${t.title} · Bitácora · NOC Syslog Inteligente`;
  refresh();
}

function setAuto() {
  clearInterval(state.timer);
  if ($("#auto").checked) state.timer = setInterval(refresh, 15000);
}

async function loadLookups() {
  state.devices = await api("/api/devices");
  $("#dl-devices").replaceChildren(...state.devices.map((d) => el("option", { value: d.name })));
  const tags = await api("/api/events/tags");
  $("#dl-tags").replaceChildren(...tags.map((t) => el("option", { value: t })));
}

async function main() {
  applyTheme(store.get("bitacora.theme") || "light");
  $("#actor").value = actor() === "anonymous" ? "" : actor();
  $("#today").textContent = new Date().toLocaleDateString("es-CO", { weekday: "long", day: "numeric", month: "long", year: "numeric" });
  $("#tl-legend").replaceChildren("Severidad:", ...SEV.map((_, i) => pill(i)));

  document.querySelectorAll("[data-tab]").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.tab)));
  $("#theme").addEventListener("click", toggleTheme);
  $("#win").addEventListener("change", () => { state.hours = Number($("#win").value); if (state.tab === "resumen") refresh(); });
  $("#auto").addEventListener("change", setAuto);
  $("#actor").addEventListener("change", () => {
    const v = $("#actor").value.replace(/[^\w .@-]/g, "").trim().slice(0, 64);
    $("#actor").value = v; store.set("noc.actor", v);
  });
  $("#notify").addEventListener("change", async () => {
    state.lastMaxId = null;
    if ($("#notify").value !== "" && "Notification" in window && Notification.permission === "default") {
      await Notification.requestPermission();
    }
  });
  $("#filters").addEventListener("submit", (e) => {
    e.preventDefault();
    try { state.filters = collectFilters(); state.evOffset = 0; loadEvents().catch((er) => toast(er.message, "err")); }
    catch (err) { toast(err.message, "err"); }
  });
  $("#f-reset").addEventListener("click", () => {
    $("#filters").reset(); state.filters = new URLSearchParams(); state.evOffset = 0;
    loadEvents().catch((er) => toast(er.message, "err"));
  });
  $("#ev-prev").addEventListener("click", () => { state.evOffset = Math.max(0, state.evOffset - state.evLimit); refresh(); });
  $("#ev-next").addEventListener("click", () => { state.evOffset += state.evLimit; refresh(); });
  $("#i-status").addEventListener("change", () => loadIncidents().catch((er) => toast(er.message, "err")));
  $("#i-new").addEventListener("click", () => openNewIncident());

  try { await loadLookups(); } catch (err) { toast(err.message, "err"); }
  showTab("resumen");
  setAuto();
}

main();
