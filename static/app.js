"use strict";
const $ = (s) => document.querySelector(s);

// Crea elementos sin innerHTML: los nombres de usuario de Instagram nunca se interpretan como HTML.
function h(tag, attrs = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else if (k === "class") e.className = v;
    else if (k === "style") Object.assign(e.style, v); // CSSOM: permitido por la CSP
    else if (v === true) e.setAttribute(k, "");
    else if (v !== false && v != null) e.setAttribute(k, v);
  }
  e.append(...kids.flat().filter((x) => x != null && x !== false));
  return e;
}

async function api(path, body) {
  const r = await fetch("/api/" + path, body === undefined ? {} :
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) {
    if (r.status === 401 && d.detail === "No autenticado") poll();
    throw Object.assign(new Error(typeof d.detail === "string" ? d.detail : "Error inesperado"), { data: d });
  }
  return d;
}

let toastTimer;
function toast(msg) {
  const t = $("#toast");
  t.textContent = msg; t.hidden = false;
  clearTimeout(toastTimer); toastTimer = setTimeout(() => (t.hidden = true), 6000);
}

const S = { st: null, view: null, tab: "unfollow", cand: { unfollow: null, follow: null },
  sel: { unfollow: new Set(), follow: new Set() }, q: "", skipPrivate: false, loading: null };
const KIND = { unfollow: "Dejar de seguir", follow: "Seguir" };
const jobActive = () => S.st && ["running", "waiting"].includes(S.st.job.status);

/* ---------- vistas de acceso ---------- */
function viewGate() {
  const pw = h("input", { type: "password", autocomplete: "current-password", required: true, id: "pw" });
  const form = h("form", { class: "card narrow", onsubmit: async (e) => {
    e.preventDefault();
    try { await api("auth/login", { password: pw.value }); poll(); } catch (x) { toast(x.message); pw.select(); }
  } },
  h("h2", {}, "Acceso privado"),
  h("p", { class: "muted" }, "Ingresa la contraseña de tu panel."),
  h("label", { class: "field" }, "Contraseña", pw),
  h("button", { class: "primary", style: { width: "100%" } }, "Entrar"));
  $("#app").replaceChildren(form); pw.focus();
}

function viewConnect() {
  let mode = "session";
  const box = h("div");
  const draw = () => {
    const sid = h("input", { type: "password", autocomplete: "off", id: "sid", placeholder: "Pega aquí el valor de sessionid" });
    const user = h("input", { type: "text", autocomplete: "username", id: "iu" });
    const pass = h("input", { type: "password", autocomplete: "current-password", id: "ip" });
    const code = h("input", { type: "text", inputmode: "numeric", autocomplete: "one-time-code", id: "ic" });
    const codeField = h("label", { class: "field", hidden: true }, "Código de verificación en dos pasos", code);
    const form = h("form", { onsubmit: async (e) => {
      e.preventDefault();
      const btn = form.querySelector("button.primary"); btn.disabled = true; btn.textContent = "Conectando…";
      try {
        await api("ig/login", mode === "session" ? { sessionid: sid.value }
          : { username: user.value, password: pass.value, code: code.value });
        poll();
      } catch (x) {
        if (x.data && x.data.need_code) { codeField.hidden = false; code.focus(); }
        toast(x.message); btn.disabled = false; btn.textContent = "Conectar";
      }
    } },
    mode === "session" ? [
      h("p", { class: "muted small" }, "Recomendado en la nube: evita que Instagram bloquee el acceso por entrar desde un servidor nuevo. ",
        "Inicia sesión en instagram.com en tu navegador → F12 → Aplicación (Application) → Cookies → copia el valor de ",
        h("b", {}, "sessionid"), "."),
      h("label", { class: "field", for: "sid" }, "sessionid", sid),
    ] : [
      h("label", { class: "field", for: "iu" }, "Usuario de Instagram", user),
      h("label", { class: "field", for: "ip" }, "Contraseña", pass),
      codeField,
      h("p", { class: "hint" }, "Si tu cuenta pide verificación o te bloquea el acceso, usa la opción de cookie de sesión."),
    ],
    h("button", { class: "primary", style: { width: "100%" } }, "Conectar"),
    h("p", { class: "muted small center" }, "Tu contraseña nunca se guarda. Solo se conserva la sesión, cifrada en el servidor."));
    box.replaceChildren(h("div", { class: "tabs", role: "tablist", style: { marginBottom: "14px" } },
      ["session", "password"].map((m) => h("button", { type: "button", role: "tab", "aria-selected": String(m === mode),
        onclick: () => { mode = m; draw(); } }, m === "session" ? "Cookie de sesión" : "Usuario y contraseña"))), form);
  };
  draw();
  $("#app").replaceChildren(h("section", { class: "card narrow" }, h("h2", {}, "Conecta tu Instagram"), box));
}

/* ---------- panel principal ---------- */
function viewDash() {
  $("#app").replaceChildren(
    h("div", { id: "banner" }),
    h("section", { class: "card", id: "usage" }),
    h("div", { class: "tabs", role: "tablist", id: "tabs" }),
    h("section", { class: "card", id: "panel" }),
    h("section", { class: "card", id: "job", hidden: true, "aria-live": "polite" }),
    h("details", { class: "card" }, h("summary", {}, "Cómo se protege tu cuenta"),
      h("ul", {},
        h("li", {}, "Cupos conservadores por hora y por día (ventana móvil de 24 h), guardados aunque reinicies el servidor."),
        h("li", {}, "Ritmo parejo con variación aleatoria entre acciones, sin ráfagas."),
        h("li", {}, "Si Instagram pide esperar o detecta algo raro, todo se pausa automáticamente (1 h o 24 h)."),
        h("li", {}, "Aun así, Instagram no permite oficialmente automatizar seguimientos: el riesgo nunca es cero. Usa los cupos por defecto o más bajos."))));
  drawTabs(); live(); renderPanel();
}

function drawTabs() {
  $("#tabs").replaceChildren(...["unfollow", "follow"].map((t) => h("button", {
    role: "tab", "aria-selected": String(S.tab === t),
    onclick: () => { S.tab = t; S.q = ""; drawTabs(); renderPanel(); },
  }, t === "unfollow" ? "Dejar de seguir a quien no me sigue" : "Seguir seguidores de una cuenta")));
}

function meter(label, [used, lim]) {
  const pct = Math.min(100, (used / lim) * 100);
  return h("div", { class: "meter" },
    h("div", { class: "meter-top" }, h("span", {}, label), h("span", {}, `${used} / ${lim}`)),
    h("div", { class: "bar" + (pct >= 100 ? " full" : pct >= 75 ? " warn" : ""), role: "progressbar", "aria-label": label,
      "aria-valuemin": 0, "aria-valuemax": lim, "aria-valuenow": used }, h("i", { style: { width: pct + "%" } })));
}

const mins = (s) => (s < 90 ? "menos de 2 min" : s < 5400 ? `~${Math.round(s / 60)} min` : `~${(s / 3600).toFixed(1)} h`);
const clock = (t) => new Date(t * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });

function estimate(kind, n) {
  const [perH, perD] = S.st.usage[kind].map((x) => x[1]);
  const full = Math.ceil(n / perD) - 1; // días completos de espera por el tope diario
  return (full * 24 + (n - full * perD) / perH) * 3600;
}

function live() {
  const st = S.st;
  $("#usage").replaceChildren(h("div", { class: "usage" },
    ...["follow", "unfollow"].map((k) => h("div", {}, h("h3", {}, k === "follow" ? "Seguir" : "Dejar de seguir"),
      meter("Última hora", st.usage[k][0]), meter("Últimas 24 h", st.usage[k][1])))));
  $("#banner").replaceChildren(...(st.cooldown > 0 ? [h("div", { class: "banner bad", role: "status" },
    `Instagram pidió una pausa. Se reanuda en ${mins(st.cooldown)}.`)] : []));
  renderJob(st.job);
  const go = $("#go"); if (go) go.disabled = jobActive() || !S.sel[S.tab].size || st.cooldown > 0;
}

function renderJob(j) {
  const el = $("#job"); el.hidden = j.status === "idle";
  if (el.hidden) return;
  const pct = j.total ? ((j.done + j.failed) / j.total) * 100 : 0;
  const label = { running: "Ejecutando", waiting: "Esperando cupo", done: "Completado", stopped: "Detenido", error: "Detenido por un problema" }[j.status];
  const wait = j.status === "waiting" && j.resume_at ? ` · reanuda ${clock(j.resume_at)}` : "";
  el.replaceChildren(
    h("div", { class: "row", style: { justifyContent: "space-between", alignItems: "center" } },
      h("h2", {}, `${KIND[j.kind]}: ${j.done} de ${j.total}`, j.failed ? ` (${j.failed} con error)` : ""),
      jobActive() ? h("button", { class: "danger", onclick: () => api("job/stop", {}).then(poll) }, "Detener") : null),
    h("p", { class: "muted" }, jobActive() ? h("span", { class: "spin" }) : null, label + wait),
    h("div", { class: "progress" }, h("i", { style: { width: pct + "%" } })),
    j.log.length ? h("ul", { class: "log" }, [...j.log].reverse().map((l) => h("li", {}, h("time", {}, clock(l.t)), l.m))) : null);
}

function avatar(u) {
  const ini = h("div", { class: "avatar", "aria-hidden": "true" }, (u.username[0] || "?").toUpperCase());
  if (!u.pic) return ini;
  return h("img", { class: "avatar", src: u.pic, alt: "", loading: "lazy", referrerpolicy: "no-referrer", onerror: (e) => e.target.replaceWith(ini) });
}

async function search(t, body) {
  S.loading = t; renderPanel();
  try {
    const list = await api("analyze/" + t, body);
    S.cand[t] = list; S.sel[t] = new Set(list.map((u) => u.pk)); S.q = "";
  } catch (e) { toast(e.message); }
  S.loading = null; renderPanel();
}

function renderPanel() {
  const t = S.tab, p = $("#panel"), list = S.cand[t];
  if (S.loading === t) {
    return p.replaceChildren(h("p", { class: "center" }, h("span", { class: "spin" }), "Consultando Instagram… puede tardar un minuto según el tamaño de las cuentas."));
  }
  let head;
  if (t === "unfollow") {
    head = [h("h2", {}, "Dejar de seguir"), h("p", { class: "muted" }, "Cuentas que sigues y que no te siguen de vuelta. Revisa la lista y desmarca las que quieras conservar."),
      h("button", { class: "primary", onclick: () => search("unfollow", {}) }, list ? "Volver a buscar" : "Buscar cuentas")];
  } else {
    const u = h("input", { type: "text", id: "tu", placeholder: "cuenta_de_interes", autocomplete: "off", required: true, maxlength: 30 });
    const n = h("input", { type: "number", id: "tn", min: 1, max: 300, value: 100 });
    head = [h("h2", {}, "Seguir seguidores de una cuenta"),
      h("p", { class: "muted" }, "Indica una cuenta (pública) y revisaremos sus seguidores recientes, omitiendo a quienes ya sigues o ya seguiste con esta app."),
      h("form", { class: "row", onsubmit: (e) => { e.preventDefault(); search("follow", { username: u.value.trim().replace(/^@/, ""), amount: +n.value || 100 }); } },
        h("label", { class: "field grow", for: "tu" }, "Cuenta (sin @)", u),
        h("label", { class: "field", for: "tn", style: { width: "150px" } }, "Seguidores a revisar", n),
        h("button", { class: "primary", style: { marginBottom: "12px" } }, list ? "Volver a buscar" : "Buscar candidatos"))];
  }
  p.replaceChildren(...head, list ? h("div", { id: "results" }) : null);
  if (list) renderList();
  $("#bar")?.remove();
  if (list && list.length) { document.body.append(actionBar()); updateBar(); }
}

const visible = (t) => S.cand[t].filter((u) => (!S.q || (u.username + " " + u.name).toLowerCase().includes(S.q)) && !(t === "follow" && S.skipPrivate && u.private));

function renderList() {
  const t = S.tab, vis = visible(t), sel = S.sel[t];
  const search = h("input", { type: "search", placeholder: "Filtrar por usuario o nombre", value: S.q, "aria-label": "Filtrar",
    oninput: (e) => {
      S.q = e.target.value.toLowerCase(); renderList();
      const i = $("#results input[type=search]"); i.focus(); i.setSelectionRange(i.value.length, i.value.length);
    } });
  const rows = vis.map((u) => {
    const cb = h("input", { type: "checkbox", checked: sel.has(u.pk), onchange: (e) => { e.target.checked ? sel.add(u.pk) : sel.delete(u.pk); updateBar(); } });
    return h("label", { class: "item" }, cb, avatar(u),
      h("div", { class: "info" }, h("div", { class: "u" }, "@" + u.username, u.verified ? h("span", { class: "tag" }, "verificada") : null, u.private ? h("span", { class: "tag" }, "privada") : null),
        h("div", { class: "n" }, u.name || " ")));
  });
  const all = (on) => { vis.forEach((u) => (on ? sel.add(u.pk) : sel.delete(u.pk))); renderList(); updateBar(); };
  $("#results").replaceChildren(
    h("div", { class: "list-head" }, search,
      t === "follow" ? h("label", { class: "row small", style: { gap: "6px", alignItems: "center" } },
        h("input", { type: "checkbox", checked: S.skipPrivate, onchange: (e) => { S.skipPrivate = e.target.checked; renderList(); } }), "Omitir privadas") : null,
      h("button", { class: "ghost", onclick: () => all(true) }, "Marcar visibles"),
      h("button", { class: "ghost", onclick: () => all(false) }, "Desmarcar visibles")),
    rows.length ? h("div", { class: "list" }, rows) : h("div", { class: "empty" }, S.cand[t].length ? "Ningún resultado con ese filtro." : "No hay cuentas para mostrar. ¡Todo en orden!"));
}

function actionBar() {
  return h("div", { class: "actionbar", id: "bar" }, h("div", {},
    h("div", {}, h("b", { id: "cnt" }), h("div", { class: "muted small", id: "eta" })),
    h("button", { class: "primary", id: "go", onclick: () => start(S.tab) }, KIND[S.tab] + " a la selección")));
}

function updateBar() {
  const t = S.tab, n = S.sel[t].size;
  if (!$("#cnt")) return;
  $("#cnt").textContent = `${n} de ${S.cand[t].length} seleccionadas`;
  $("#eta").textContent = n ? `Tiempo estimado respetando tus límites: ${mins(estimate(t, Math.min(n, 500)))}` + (n > 500 ? " · máx. 500 por trabajo" : "") : "";
  live();
}

async function start(t) {
  const byPk = new Map(S.cand[t].map((u) => [u.pk, u]));
  const targets = [...S.sel[t]].slice(0, 500).map((pk) => ({ pk, username: byPk.get(pk).username }));
  try {
    await api("job/start", { kind: t, targets });
    S.cand[t] = null; S.sel[t] = new Set();
    await poll(); renderPanel();
    $("#job").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (e) { toast(e.message); }
}

/* ---------- ciclo de actualización ---------- */
function who() {
  const st = S.st;
  $("#who").replaceChildren(...(st.auth ? [
    st.ig ? h("span", { class: "chip" }, "@" + st.ig) : null,
    st.ig ? h("button", { class: "ghost", onclick: () => api("ig/logout", {}).then(poll) }, "Cambiar cuenta") : null,
    h("button", { class: "ghost", onclick: () => api("auth/logout", {}).then(poll) }, "Salir"),
  ] : []));
}

let timer;
async function poll() {
  clearTimeout(timer);
  try {
    S.st = await api("state");
    const view = !S.st.auth ? "gate" : !S.st.ig ? "connect" : "dash";
    if (view !== S.view) {
      S.view = view; $("#bar")?.remove();
      ({ gate: viewGate, connect: viewConnect, dash: viewDash })[view]();
    } else if (view === "dash") live();
    who();
  } catch { /* red caída: reintenta */ }
  timer = setTimeout(poll, jobActive() ? 2500 : 15000);
}
poll();
