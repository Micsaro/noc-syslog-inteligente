"use strict";
/* Consola simulada (solo lectura) y generador de plantillas - Fase 5.
   Usa los ayudantes de app.js: $, el, api, toast, state, SEV.
   REGLA DE ORO: la salida de un equipo o de un log se muestra como TEXTO y nunca
   se convierte en comando. Los comandos solo salen del teclado, de un botón
   predefinido o de una macro (validada otra vez por el servidor en cada ejecución). */

const con = { device: null, connected: false, prompt: "", policy: null, history: [], hIdx: 0 };
let devSignature = "";

/* ---------- carga de equipos (pestañas Consola y Plantillas) ---------- */
async function loadConsolePanel() {
  const list = await api("/api/devices");
  state.devices = list;
  const sig = list.map((d) => `${d.id}:${d.name}:${d.status}`).join("|");
  if (sig === devSignature) return;               // sin cambios: no se toca lo que el usuario eligió
  devSignature = sig;
  const cur = { c: $("#c-device").value, g: $("#g-device").value };
  $("#c-device").replaceChildren(...list.filter((d) => d.status !== "inactive")
    .map((d) => el("option", { value: d.id }, `${d.name} (${d.vendor})`)));
  $("#g-device").replaceChildren(el("option", { value: "" }, "(ninguno)"),
    ...list.map((d) => el("option", { value: d.id }, `${d.name} (${d.vendor})`)));
  if (cur.c) $("#c-device").value = cur.c;
  if (cur.g) $("#g-device").value = cur.g;
}

/* ---------- terminal ---------- */
function termPrint(text, cls = "") {
  const out = $("#term-out");
  out.append(el("span", { class: cls }, text + "\n"));       // siempre texto, nunca HTML
  while (out.childNodes.length > 600) out.firstChild.remove();
  const t = $("#term");
  t.scrollTop = t.scrollHeight;
}

function printResult(r) {
  if (r.allowed) { if (r.output) termPrint(r.output); }
  else termPrint(`% BLOQUEADO [${r.category}]: ${r.reason}`, "bad");
}

async function sendCommand(raw) {
  const cmd = raw.trim();
  if (!con.connected || !cmd) return;
  if (cmd === "clear" || cmd === "cls") { $("#term-out").replaceChildren(); return; }
  termPrint(`${con.prompt} ${cmd}`, "cmd");
  if (cmd === "help") { showHelp(); return; }
  try {
    const r = await api("/api/console/exec", { method: "POST", body: { device_id: con.device.id, command: cmd } });
    printResult(r);
  } catch (err) { termPrint(err.message, "bad"); }
}

function showHelp() {
  termPrint("Comandos permitidos (solo lectura):", "sim");
  con.policy.allowed.forEach((a) => termPrint(`  ${a.command.padEnd(38)} ${a.description}`, "sim"));
  termPrint("Filtro opcional: comando | include texto   (include, exclude, begin, section, grep, count)", "sim");
  termPrint("Locales: help, clear", "sim");
}

/* ---------- conexión ---------- */
async function detectAndConnect() {
  try {
    const info = await api("/api/console/ports");
    $("#c-port").replaceChildren(...info.ports.map((p) =>
      el("option", { value: p.device, selected: p.device === info.recommended },
        `${p.device} · ${p.description}${p.simulated ? "" : " (detectado)"}`)));
    if (!info.pyserial) toast("pyserial no está instalado: solo se ofrece el puerto simulado", "alert");
    await connectConsole();
  } catch (err) { toast(err.message, "err"); }
}

async function connectConsole() {
  const id = Number($("#c-device").value);
  if (!id) { toast("Selecciona un equipo", "err"); return; }
  const r = await api("/api/console/connect",
    { method: "POST", body: { device_id: id, port: $("#c-port").value || null } });
  Object.assign(con, { device: r.device, connected: true, prompt: r.prompt, policy: r.policy, history: [], hIdx: 0 });
  $("#term-out").replaceChildren();
  r.banner.forEach((l) => termPrint(l, "sim"));
  $("#term-prompt").textContent = r.prompt;
  $("#term-in").disabled = false;
  $("#term-in").focus();
  $("#c-disconnect").disabled = false;
  $("#c-status").textContent = `Conectado a ${r.device.name} por ${r.port} (${r.baudrate} 8N1) · modo simulado`;
  renderPresets(r.presets);
  renderPolicy(r.policy);
  await loadMacros();
}

function disconnectConsole() {
  if (!con.connected) return;
  con.connected = false;
  termPrint("[sesión cerrada]", "sim");
  $("#term-in").disabled = true;
  $("#term-prompt").textContent = "—";
  $("#c-disconnect").disabled = true;
  $("#c-status").textContent = "Sin conexión";
}

function renderPresets(list) {
  $("#c-presets").replaceChildren(...(list.length ? list.map((p) =>
    el("button", { type: "button", title: p.description, onclick: () => sendCommand(p.command) }, p.command))
    : [el("span", { class: "muted" }, "Sin botones para este fabricante.")]));
}

function renderPolicy(p) {
  $("#c-policy").replaceChildren(
    el("details", { open: true }, el("summary", {}, `Permitidos (${p.allowed.length})`),
      el("ul", { class: "plain" }, p.allowed.map((a) =>
        el("li", {}, el("code", {}, a.command), el("span", { class: "muted" }, a.description))))),
    el("details", {}, el("summary", {}, `Bloqueados (${p.blocked.length} categorías)`),
      el("ul", { class: "plain" }, p.blocked.map((b) =>
        el("li", {}, el("strong", {}, b.category), el("span", { class: "muted" }, `${b.reason}. Ej.: ${b.examples.join(", ")}`))))),
    el("details", {}, el("summary", {}, "Reglas generales"),
      el("ul", {}, p.rules.map((r) => el("li", {}, r)))));
}

/* ---------- macros ---------- */
async function loadMacros() {
  const list = await api(`/api/console/macros?vendor=${encodeURIComponent(con.device.vendor)}`);
  $("#c-macros").replaceChildren(...(list.length ? list.map((m) =>
    el("li", {}, el("strong", {}, m.name), el("span", { class: "muted" }, `${m.commands.length} comandos`),
      el("button", { type: "button", onclick: () => runMacro(m) }, "Ejecutar"),
      el("button", { type: "button", onclick: () => deleteMacro(m) }, "Borrar")))
    : [el("li", { class: "muted" }, "Sin macros para este fabricante")]));
}

async function runMacro(m) {
  if (!con.connected) { toast("Conéctate a un equipo primero", "err"); return; }
  termPrint(`[macro] ${m.name}`, "sim");
  try {
    const r = await api(`/api/console/macros/${m.id}/run`, { method: "POST", body: { device_id: con.device.id } });
    r.results.forEach((x) => { termPrint(`${x.prompt} ${x.command}`, "cmd"); printResult(x); });
    if (r.results.some((x) => !x.allowed)) termPrint("[macro] detenida por un comando bloqueado", "bad");
  } catch (err) { toast(err.message, "err"); }
}

async function deleteMacro(m) {
  try { await api(`/api/console/macros/${m.id}`, { method: "DELETE" }); await loadMacros(); }
  catch (err) { toast(err.message, "err"); }
}

async function createMacro(ev) {
  ev.preventDefault();
  if (!con.connected) { toast("Conéctate a un equipo para crear la macro de su fabricante", "err"); return; }
  const commands = $("#c-macro-cmds").value.split("\n").map((l) => l.trim()).filter(Boolean);
  try {
    await api("/api/console/macros", { method: "POST",
      body: { name: $("#c-macro-name").value.trim(), vendor: con.device.vendor, commands } });
    $("#c-macro-name").value = ""; $("#c-macro-cmds").value = "";
    toast("Macro guardada", "ok");
    await loadMacros();
  } catch (err) { toast(err.message, "err"); }
}

/* ---------- plantillas ---------- */
async function generateConfig(ev) {
  ev.preventDefault();
  const body = {
    vendor: $("#g-vendor").value, template: $("#g-template").value,
    syslog_host: $("#g-host").value.trim(), syslog_port: Number($("#g-port").value),
    severity: Number($("#g-sev").value), ntp_host: $("#g-ntp").value.trim(),
  };
  if ($("#g-device").value) body.device_id = Number($("#g-device").value);
  try {
    const r = await api("/api/config/generate", { method: "POST", body });
    $("#g-out").textContent = r.content;
  } catch (err) { toast(err.message, "err"); }
}

async function copyConfig() {
  try { await navigator.clipboard.writeText($("#g-out").textContent); toast("Copiado al portapapeles", "ok"); }
  catch { toast("No se pudo copiar: selecciona el texto manualmente", "err"); }
}

/* ---------- inicialización ---------- */
function initConsole() {
  $("#g-sev").replaceChildren(...SEV.map((n, i) => el("option", { value: i, selected: i === 6 }, `${i} ${n}`)));
  $("#c-detect").addEventListener("click", detectAndConnect);
  $("#c-disconnect").addEventListener("click", disconnectConsole);
  $("#c-device").addEventListener("change", disconnectConsole);
  $("#c-macro-form").addEventListener("submit", createMacro);
  $("#g-form").addEventListener("submit", generateConfig);
  $("#g-copy").addEventListener("click", copyConfig);
  $("#g-device").addEventListener("change", () => {
    const d = state.devices.find((x) => String(x.id) === $("#g-device").value);
    if (d && ["cisco", "fortinet", "huawei"].includes(d.vendor)) $("#g-vendor").value = d.vendor;
  });
  $("#term").addEventListener("click", () => { if (!$("#term-in").disabled) $("#term-in").focus(); });
  $("#term-in").addEventListener("keydown", (e) => {
    const input = e.target;
    if (e.key === "Enter") {
      const v = input.value; input.value = "";
      if (v.trim()) { con.history.push(v); con.hIdx = con.history.length; }
      sendCommand(v);
    } else if (e.key === "ArrowUp" && con.history.length) {
      e.preventDefault(); con.hIdx = Math.max(0, con.hIdx - 1); input.value = con.history[con.hIdx];
    } else if (e.key === "ArrowDown" && con.history.length) {
      e.preventDefault(); con.hIdx = Math.min(con.history.length, con.hIdx + 1); input.value = con.history[con.hIdx] || "";
    }
  });
}

initConsole();