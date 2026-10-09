"use strict";
/* NOC Syslog Inteligente - Dashboard.
   REGLA DE ORO: todo texto que viene de logs o de usuarios se inserta como TEXTO
   (createTextNode / textContent). Nunca se construye HTML a partir de datos. */

const $ = (sel, root = document) => root.querySelector(sel);
const SEV = ["Emergency", "Alert", "Critical", "Error", "Warning", "Notice", "Informational", "Debug"];
const STATUS_ES = { open: "Abierto", assigned: "Asignado", in_progress: "En curso", resolved: "Resuelto", closed: "Cerrado" };
const HEALTH_ES = { critico: "Crítico", alerta: "Alerta", ok: "Normal", "sin-datos": "Sin datos", inactivo: "Inactivo", mantenimiento: "Mantenimiento" };
const NS = "http://www.w3.org/2000/svg";

const state = { tab: "resumen", hours: 24, devices: [], filters: new URLSearchParams(),
                evOffset: 0, evLimit: 25, lastMaxId: null, timer: null };

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

/* ---------- tema ---------- */
function applyTheme(t) { document.documentElement.dataset.theme = t; store.set("noc.theme", t); }
function toggleTheme() {
  const cur = document.documentElement.dataset.theme;
  const dark = cur === "dark" || (cur === "auto" && matchMedia("(prefers-color-scheme: dark)").matches);
  applyTheme(dark ? "light" : "dark");
}

/* ---------- resumen ---------- */
async function loadSummary() {
  const d = await api(`/api/dashboard/summary?hours=${state.hours}`);
  renderKpis(d);
  renderDevices(d.devices);
  renderSeverity(d.by_severity);
  renderTrend(d.timeline);
  renderHeat(d.heatmap, d.timeline.map((t) => t.hour));
  renderRecent(d.recent);
}

function renderKpis(d) {
  const k = d.kpis;
  const cards = [
    ["Mensajes", k.occurrences, `${k.events} eventos únicos`, ""],
    ["Críticos (sev 0-2)", k.critical, "mensajes", k.critical > 0 ? "bad" : ""],
    ["Errores (sev 0-3)", k.errors, "mensajes", k.errors > 0 ? "warn" : ""],
    ["Incidentes activos", d.incidents.active, `${d.incidents.open} sin asignar`, ""],
    ["Sospechosos", k.suspicious, "eventos etiquetados", k.suspicious > 0 ? "warn" : ""],
  ];
  $("#kpis").replaceChildren(...cards.map(([t, v, sub, cls]) =>
    el("div", { class: "kpi " + cls },
      el("div", { class: "kpi-val" }, v), el("div", { class: "kpi-lbl" }, t), el("div", { class: "kpi-sub" }, sub))));
}

function renderDevices(devs) {
  $("#dev-body").replaceChildren(...devs.map((d) =>
    el("tr", { class: "click", onclick: () => goDevice(d.name) },
      el("td", {}, d.name, d.is_simulated ? el("span", { class: "chip" }, "sim") : null),
      el("td", {}, d.vendor), el("td", {}, d.ip_address), el("td", {}, d.status),
      el("td", {}, el("span", { class: `pill h-${d.health}` }, HEALTH_ES[d.health])),
      el("td", {}, d.occurrences), el("td", {}, fmt(d.last_event)))));
}

function renderSeverity(rows) {
  const max = Math.max(1, ...rows.map((r) => r.occurrences));
  const rowH = 22, barX = 112, barW = 230;
  const svg = s("svg", { viewBox: `0 0 420 ${rowH * 8 + 6}`, role: "img", "aria-label": "Mensajes por severidad" });
  rows.forEach((r, i) => {
    const y = i * rowH + 3, w = Math.round((r.occurrences / max) * barW);
    svg.append(
      s("text", { x: 0, y: y + 14, class: "lbl" }, `${r.severity} ${SEV[r.severity]}`),
      s("rect", { x: barX, y: y + 3, width: Math.max(w, r.occurrences > 0 ? 2 : 0), height: 14, class: `bar sev-${r.severity}` },
        s("title", {}, `${r.events} eventos, ${r.occurrences} mensajes`)),
      s("text", { x: barX + w + 6, y: y + 14, class: "lbl" }, r.occurrences));
  });
  $("#chart-sev").replaceChildren(svg);
}

function renderTrend(tl) {
  const W = 600, H = 170, L = 34, B = 22, T = 8, n = tl.length;
  const bw = (W - L - 6) / n, ph = H - B - T, max = Math.max(1, ...tl.map((t) => t.total));
  const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Tendencia por hora" });
  svg.append(
    s("text", { x: 0, y: T + 8, class: "lbl" }, max), s("text", { x: 0, y: H - B, class: "lbl" }, "0"),
    s("line", { x1: L, y1: H - B, x2: W, y2: H - B, class: "axis" }));
  const step = Math.ceil(n / 12);
  tl.forEach((t, i) => {
    const x = L + i * bw, h1 = (t.total / max) * ph, h2 = (t.errors / max) * ph, w = Math.max(bw - 2, 1);
    svg.append(
      s("rect", { x: x + 1, y: H - B - h1, width: w, height: h1, class: "bar-total" },
        s("title", {}, `${hourLabel(t.hour)}: ${t.total} mensajes, ${t.errors} errores`)),
      s("rect", { x: x + 1, y: H - B - h2, width: w, height: h2, class: "bar-err" }));
    if (i % step === 0) svg.append(s("text", { x, y: H - 6, class: "lbl" }, hourLabel(t.hour, true)));
  });
  $("#chart-trend").replaceChildren(svg);
}

function heatLevel(c, max) { return c <= 0 ? 0 : 1 + Math.min(4, Math.floor((c / max) * 5)); }

function renderHeat(h, hours) {
  if (!h.devices.length) { $("#heat").replaceChildren(el("p", { class: "muted" }, "Sin equipos en el inventario.")); return; }
  const step = Math.ceil(hours.length / 12);
  const head = el("tr", {}, el("th", {}), hours.map((hr, i) => el("th", {}, i % step === 0 ? hourLabel(hr, true) : "")));
  const rows = h.devices.map((dev) => el("tr", {},
    el("th", { class: "rowh" }, dev.name),
    dev.counts.map((c, i) => el("td", { class: `heat-${heatLevel(c, h.max)}`, title: `${dev.name} · ${hourLabel(hours[i])}: ${c}` }))));
  $("#heat").replaceChildren(el("table", { class: "heat" }, head, rows));
}

function renderRecent(list) {
  $("#recent").replaceChildren(...(list.length ? list.map((e) =>
    el("li", { class: "click", onclick: () => openEvent(e.id) },
      pill(e.severity), el("strong", {}, e.device_name || e.source_ip || "?"),
      el("span", { class: "msg-inline" }, e.message), el("small", { class: "muted" }, fmt(e.received_at))))
    : [el("li", { class: "muted" }, "Sin eventos graves registrados.")]));
}

function goDevice(name) {
  $("#f-device").value = name;
  state.filters = collectFilters();
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
    el("td", {}, fmt(e.received_at)),
    el("td", {}, pill(e.severity)),
    el("td", {}, e.device_name || e.hostname || e.source_ip || "—"),
    el("td", {}, e.vendor || "—"),
    el("td", {}, e.facility_name),
    el("td", { class: "msg", title: e.message }, e.message),
    el("td", {}, e.tags.map((t) => el("span", { class: "chip" + (t === "sospechoso" ? " chip-bad" : "") }, t))),
    el("td", {}, e.repeat_count > 1 ? `×${e.repeat_count}` : ""),
    el("td", { class: "acts" },
      el("button", { type: "button", onclick: () => openEvent(e.id) }, "Ver"), " ",
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
  dlg.replaceChildren(
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
    el("h3", {}, "Evidencia original (contenido NO CONFIABLE)"),
    el("p", { class: "warn-text" }, e.warning),
    el("pre", { class: "raw" }, revealRaw(e.raw_message || "")),
    el("div", { class: "dlg-actions" },
      el("button", { type: "button", class: "primary", onclick: () => { dlg.close(); newIncidentFromEvent(e); } }, "Crear incidente"),
      el("button", { type: "button", onclick: () => dlg.close() }, "Cerrar")));
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
      el("td", {}, i.id), el("td", {}, i.title), el("td", {}, pill(i.severity)),
      el("td", {}, el("span", { class: `pill st-${i.status}` }, STATUS_ES[i.status])),
      el("td", {}, i.device_name || "—"), el("td", {}, i.assigned_to || "—"),
      el("td", {}, i.events_count), el("td", {}, fmt(i.updated_at))))
    : [el("tr", {}, el("td", { colspan: 8, class: "muted" }, "Sin incidentes para este filtro."))]));
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
  dlg.replaceChildren(el("h2", {}, "Nuevo incidente"), form);
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
    new Notification(`NOC · ${SEV[e.severity]} en ${who}`, { body: clip(e.message, 140) });   // solo texto
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
    else await loadIncidents();
    await checkNotifications();
    $("#updated").textContent = "Actualizado " + new Date().toLocaleTimeString("es-CO");
  } catch (err) { toast(err.message, "err"); }
}

function showTab(name) {
  state.tab = name;
  document.querySelectorAll(".tab").forEach((sec) => { sec.hidden = sec.id !== `tab-${name}`; });
  document.querySelectorAll("[data-tab]").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
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
  applyTheme(store.get("noc.theme") || "auto");
  $("#actor").value = actor() === "anonymous" ? "" : actor();

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