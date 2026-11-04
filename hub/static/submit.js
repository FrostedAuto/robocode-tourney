// Team page: sign up, upload a bot, watch its status. The key lives only in this tab (sessionStorage).
"use strict";

const $ = (id) => document.getElementById(id);
let key = sessionStorage.getItem("teamKey") || "";
let poll = null;

function say(text, kind = "") {
  const m = $("msg");
  m.textContent = text;
  m.className = "msg " + kind;
}

async function api(path, opts = {}) {
  const headers = Object.assign({}, opts.headers || {});
  if (key) headers["X-Team-Key"] = key;
  const r = await fetch(path, Object.assign({}, opts, { headers }));
  let data = {};
  try { data = await r.json(); } catch (e) { data = { ok: false, error: "Server error (" + r.status + ")" }; }
  if (!r.ok || data.ok === false) throw new Error(data.error || "Request failed");
  return data;
}

async function loadPublic() {
  try {
    const p = await (await fetch("/api/public")).json();
    $("title").textContent = p.title;
    $("register-card").hidden = !p.reg_open || !!key;
  } catch (e) { /* page still works without it */ }
}

function fmtTime(t) { return new Date(t * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }); }

function renderTeam(t) {
  $("login-card").hidden = true;
  $("register-card").hidden = true;
  $("team-card").hidden = false;
  $("team-name").textContent = t.team;
  const st = $("status");
  st.innerHTML = "";
  const row = (label, value, cls = "") => {
    const d = document.createElement("div");
    d.className = "row " + cls;
    const a = document.createElement("span"); a.textContent = label;
    const b = document.createElement("b"); b.textContent = value;
    d.append(a, b); st.append(d);
  };
  row("Bot", t.bot || "none uploaded yet");
  if (t.pending) row("Upload", "checking…", "wait");
  else if (t.last_import) row("Last upload", (t.last_import.result === "PASS" ? "accepted " : "rejected ") + fmtTime(t.last_import.at),
    t.last_import.result === "PASS" ? "good" : "bad");
  if (t.last_import && t.last_import.result !== "PASS" && !t.pending) {
    const pre = document.createElement("pre"); pre.textContent = t.last_import.detail; st.append(pre);
  }
  row("In the game", t.connected ? "connected ✔" : t.stopped ? "stopped" : t.bot ? "not connected yet" : "—",
    t.connected ? "good" : t.stopped ? "bad" : t.bot ? "wait" : "");
  if (t.notice && !t.pending) {
    const p = document.createElement("p"); p.className = "hint"; p.textContent = "⚠ " + t.notice; st.append(p);
  }
  if (t.stopped && !t.pending) {
    const pre = document.createElement("pre"); pre.textContent = t.stopped; st.append(pre);
  } else if (t.bot && !t.connected && !t.pending) {
    const p = document.createElement("p"); p.className = "hint";
    p.textContent = "If this stays 'not connected' for more than a minute, your bot probably crashes or loops before start(). Test it in the Robocode app, then upload again.";
    st.append(p);
  }
  $("send").disabled = !t.uploads_open;
  if (!t.uploads_open) say("Uploads are closed right now.", "bad");
}

async function refresh() {
  try {
    renderTeam(await api("/api/team"));
  } catch (e) {
    if (/key/i.test(e.message)) { logout(); say(e.message, "bad"); }
  }
}

function startPoll() {
  clearInterval(poll);
  refresh();
  poll = setInterval(refresh, 3000);
}

function logout() {
  key = ""; sessionStorage.removeItem("teamKey"); clearInterval(poll);
  $("team-card").hidden = true; $("login-card").hidden = false; $("key").value = "";
  loadPublic();
}

$("login").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  key = $("key").value.trim();
  try {
    await api("/api/team");
    sessionStorage.setItem("teamKey", key);
    say("");
    startPoll();
  } catch (e) { key = ""; say(e.message, "bad"); }
});

$("register").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  try {
    const r = await api("/api/register", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: $("tname").value, code: $("code").value }) });
    key = r.key;
    sessionStorage.setItem("teamKey", key);
    say("Team “" + r.team + "” created. Your team key is " + r.key + " — write it down now, it is shown only once.", "good key");
    startPoll();
  } catch (e) { say(e.message, "bad"); }
});

$("files").addEventListener("change", () => {
  const f = $("files").files;
  $("drop-text").textContent = f.length ? Array.from(f).map((x) => x.name).join(", ") : "Choose files";
});

$("upload").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const f = $("files").files;
  if (!f.length) { say("Choose your bot's files first.", "bad"); return; }
  const fd = new FormData();
  for (const file of f) fd.append("files", file, file.name);
  $("send").disabled = true;
  say("Uploading…");
  try {
    const r = await api("/api/upload", { method: "POST", body: fd });
    say(r.message + (r.warnings.length ? " Note: " + r.warnings.join(" ") : ""), r.warnings.length ? "wait" : "good");
    $("files").value = ""; $("drop-text").textContent = "Choose files";
    refresh();
  } catch (e) { say(e.message, "bad"); }
  finally { $("send").disabled = false; }
});

$("logout").addEventListener("click", logout);

loadPublic();
if (key) startPoll();
