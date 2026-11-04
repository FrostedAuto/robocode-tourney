// Projector view: live arena + standings. Data comes from /ws/live (robocode-hub).
"use strict";

const $ = (id) => document.getElementById(id);
const cv = $("arena");
const ctx = cv.getContext("2d");
const PALETTE = ["#4cc9f0", "#f72585", "#ffd166", "#06d6a0", "#ff8c42", "#b388ff", "#ef476f", "#8ac926",
                 "#00b4d8", "#ffadad", "#caffbf", "#fdffb6", "#9bf6ff", "#bdb2ff", "#ffc6ff", "#e9c46a"];

let S = null;            // last public state
let frame = null;        // last tick
let effects = [];        // [{kind, x, y, t}]
let finalShow = null;    // {stage, results, until}
let arenaW = 800, arenaH = 600;

function el(tag, attrs = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") e.className = v; else if (k === "style") e.style.cssText = v; else e.setAttribute(k, v);
  }
  for (const k of kids) e.append(k instanceof Node ? k : document.createTextNode(String(k)));
  return e;
}

function colorOf(id) {
  const b = S && S.game && S.game.bots[id];
  return (b && b.colors && (b.colors.bodyColor || b.colors.turretColor)) || PALETTE[(id - 1) % PALETTE.length];
}
function nameOf(id) {
  const b = S && S.game && S.game.bots[id];
  return b ? b.name : "Bot " + id;
}

// ---------------------------------------------------------------- side panels
function render() {
  if (!S) return;
  $("title").textContent = S.title;
  $("dot").className = "dot " + (S.server_ok ? "ok" : "bad");
  const url = S.public_url ? S.public_url.replace(/\/$/, "") + "/submit" : location.host + "/submit";
  $("cta").textContent = S.uploads_open ? "Submit your bot: " + url : "";

  const g = S.game;
  if (g) {
    arenaW = g.arena[0]; arenaH = g.arena[1];
    $("now").innerHTML = "";
    $("now").append(el("span", { class: "pill" + (g.counted ? "" : " muted") }, g.stage),
      " Round " + g.round + (g.rounds ? " / " + g.rounds : "") + (g.paused ? " — paused" : ""));
  } else {
    $("now").textContent = S.server_ok ? "Waiting for the next battle" : "Reconnecting to the game server…";
  }
  renderFighters();
  renderStandings();
  renderTicker();
  renderOverlay();
}

function renderFighters() {
  const list = $("fighters");
  list.innerHTML = "";
  const g = S.game;
  if (!g) {
    $("fighters-h").textContent = "Teams";
    const teams = S.teams.length ? S.teams : [];
    if (!teams.length) list.append(el("li", { class: "muted" }, "No teams yet"));
    for (const t of teams) {
      list.append(el("li", {}, el("span", { class: "sw " + (t.connected ? "on" : "off") }),
        el("span", { class: "nm" }, t.name),
        el("span", { class: "tag" }, t.connected ? "ready" : t.has_bot ? "starting…" : "no bot yet")));
    }
    return;
  }
  $("fighters-h").textContent = "In the arena";
  const energy = {};
  if (frame) for (const b of frame.bots) energy[b[0]] = b[7];
  const ids = Object.keys(g.bots).map(Number).sort((a, b) => (energy[b] ?? -1) - (energy[a] ?? -1));
  for (const id of ids) {
    const e = energy[id];
    const alive = e !== undefined;
    const bar = el("span", { class: "bar-e" }, el("i", { style: `width:${Math.max(0, Math.min(100, e || 0))}%;background:${colorOf(id)}` }));
    list.append(el("li", { class: alive ? "" : "dead" },
      el("span", { class: "sw", style: `background:${colorOf(id)}` }),
      el("span", { class: "nm" }, nameOf(id) + (g.bots[id].house ? " (house)" : "")),
      bar, el("span", { class: "num" }, alive ? Math.round(e) : "✖")));
  }
}

function currentStage() {
  if (S.game && S.game.counted) return S.game.stage;
  const order = ["Final", ...S.heats.map((h) => h.name).reverse()];
  for (const st of order) if (S.standings[st]) return st;
  return Object.keys(S.standings)[0] || null;
}

function renderStandings() {
  const st = currentStage();
  $("standings-h").textContent = st ? "Standings — " + st : "Standings";
  const tb = $("standings");
  tb.innerHTML = "";
  const rows = st ? S.standings[st] : [];
  if (!rows.length) tb.append(el("tr", {}, el("td", { colspan: 4, class: "muted" }, "Scores appear after the first counted battle")));
  rows.slice(0, 12).forEach((r) => tb.append(el("tr", { class: r.rank <= 3 ? "top" + r.rank : "" },
    el("td", {}, r.rank), el("td", {}, r.name), el("td", { class: "num" }, r.score), el("td", { class: "num" }, r.firsts))));
  const others = $("others");
  others.innerHTML = "";
  if (S.final.length && st !== "Final") others.append(el("div", {}, el("b", {}, "Finalists: "), S.final.join(", ")));
  for (const h of S.heats) if (h.name !== st) others.append(el("div", {}, el("b", {}, h.name + ": "), h.teams.join(", ")));
}

function renderTicker() {
  const tk = $("ticker");
  tk.innerHTML = "";
  if (!S.battles.length) { tk.append(el("span", { class: "muted" }, S.teams.length + " teams registered · " + S.joined + " bots connected")); return; }
  for (const b of S.battles.slice(0, 6)) {
    const w = b.results[0];
    tk.append(el("span", { class: "tick-item" }, el("b", {}, b.stage), " won by ", w ? w.name : "—"));
  }
}

function renderOverlay() {
  const ov = $("overlay");
  ov.innerHTML = "";
  ov.className = "overlay";
  const t = Date.now();
  if (finalShow && finalShow.until > t) {
    ov.classList.add("show");
    ov.append(el("h1", {}, finalShow.stage + " — results"));
    const pod = el("ol", { class: "podium" });
    finalShow.results.slice(0, 8).forEach((r) => pod.append(el("li", { class: "p" + r.rank },
      el("span", { class: "rk" }, r.rank), el("span", { class: "nm" }, r.name + (r.team ? "" : " (house)")),
      el("span", { class: "num" }, r.total))));
    ov.append(pod);
    return;
  }
  if (S.game) {
    if (S.game.round_results) {
      ov.classList.add("show", "small");
      ov.append(el("h2", {}, "Round " + S.game.round + " — " + (S.game.round_results[0] || {}).name + " leads"));
    }
    return;
  }
  ov.classList.add("show");
  ov.append(el("h1", {}, S.title));
  const next = S.final.length ? [{ name: "Final", teams: S.final }] : S.heats;
  if (next.length) {
    const grid = el("div", { class: "heats" });
    for (const h of next) grid.append(el("div", { class: "heat" }, el("h3", {}, h.name), el("p", {}, h.teams.join(" · "))));
    ov.append(grid);
  } else {
    ov.append(el("p", { class: "big" }, S.teams.length + " teams · " + S.joined + " bots ready"));
  }
  if (S.uploads_open) ov.append(el("p", { class: "cta-big" }, "Submit your bot at " + $("cta").textContent.replace("Submit your bot: ", "")));
}

// ---------------------------------------------------------------- arena drawing
function fit() {
  const wrap = cv.parentElement.getBoundingClientRect();
  const s = Math.min(wrap.width / arenaW, wrap.height / arenaH);
  const dpr = window.devicePixelRatio || 1;
  cv.style.width = arenaW * s + "px";
  cv.style.height = arenaH * s + "px";
  cv.width = Math.round(arenaW * s * dpr);
  cv.height = Math.round(arenaH * s * dpr);
  return s * dpr;
}

function draw() {
  const k = fit();
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.fillStyle = "#0b1320";
  ctx.fillRect(0, 0, cv.width, cv.height);
  ctx.setTransform(k, 0, 0, -k, 0, arenaH * k);       // Tank Royale: origin bottom-left, y up
  // grid
  ctx.strokeStyle = "rgba(120,160,220,0.07)";
  ctx.lineWidth = 1 / k;
  for (let x = 0; x <= arenaW; x += 50) { ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, arenaH); ctx.stroke(); }
  for (let y = 0; y <= arenaH; y += 50) { ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(arenaW, y); ctx.stroke(); }

  const t = performance.now();
  if (frame && S && S.game) {
    for (const [x, y, p, owner] of frame.bullets) {
      ctx.fillStyle = (S.game.bots[owner] && S.game.bots[owner].colors.bulletColor) || "#ffb703";
      ctx.beginPath(); ctx.arc(x, y, 2 + Math.sqrt(p) * 2, 0, Math.PI * 2); ctx.fill();
    }
    for (const b of frame.bots) drawBot(b, k);
  }
  effects = effects.filter((e) => t - e.t < e.life);
  for (const e of effects) {
    const a = (t - e.t) / e.life;
    ctx.strokeStyle = e.kind === "death" ? `rgba(255,140,60,${1 - a})` : `rgba(255,255,255,${0.8 - 0.8 * a})`;
    ctx.lineWidth = (e.kind === "death" ? 6 : 2) / k * (1 - a) + 1 / k;
    ctx.beginPath(); ctx.arc(e.x, e.y, (e.kind === "death" ? 60 : 26) * a + 10, 0, Math.PI * 2); ctx.stroke();
  }
  requestAnimationFrame(draw);
}

const rad = (deg) => (deg * Math.PI) / 180;

function drawBot([id, x, y, dir, gun, radar, sweep, energy], k) {
  const c = colorOf(id);
  const col = (S.game.bots[id] && S.game.bots[id].colors) || {};
  // radar sweep
  ctx.fillStyle = "rgba(255,255,255,0.05)";
  ctx.beginPath(); ctx.moveTo(x, y);
  ctx.arc(x, y, 120, rad(radar), rad(radar - (sweep || 0)), (sweep || 0) > 0); ctx.closePath(); ctx.fill();
  // body
  ctx.save(); ctx.translate(x, y); ctx.rotate(rad(dir));
  ctx.fillStyle = "#1d2a3d"; ctx.fillRect(-18, -18, 36, 8); ctx.fillRect(-18, 10, 36, 8);   // tracks
  ctx.fillStyle = c; ctx.fillRect(-15, -12, 30, 24);
  ctx.restore();
  // turret + gun
  ctx.save(); ctx.translate(x, y); ctx.rotate(rad(gun));
  ctx.fillStyle = col.gunColor || "#d8dee9"; ctx.fillRect(0, -2.5, 26, 5);
  ctx.fillStyle = col.turretColor || shade(c); ctx.beginPath(); ctx.arc(0, 0, 8, 0, Math.PI * 2); ctx.fill();
  ctx.restore();
  // label (unflip text)
  ctx.save(); ctx.translate(x, y); ctx.scale(1, -1);
  ctx.fillStyle = "rgba(0,0,0,0.55)"; ctx.fillRect(-22, -34, 44, 5);
  ctx.fillStyle = energy > 30 ? "#06d6a0" : energy > 10 ? "#ffd166" : "#ef476f";
  ctx.fillRect(-22, -34, 44 * Math.max(0, Math.min(1, energy / 100)), 5);
  ctx.font = "600 13px system-ui, sans-serif"; ctx.textAlign = "center"; ctx.fillStyle = "#e6edf7";
  ctx.fillText(nameOf(id), 0, 36);
  ctx.restore();
}

function shade(hex) {
  const m = /^#?([0-9a-f]{6})/i.exec(hex || "");
  if (!m) return "#888";
  const n = parseInt(m[1], 16);
  const f = (v) => Math.max(0, Math.round(v * 0.7));
  return `rgb(${f(n >> 16)},${f((n >> 8) & 255)},${f(n & 255)})`;
}

// ---------------------------------------------------------------- data
function connect() {
  const ws = new WebSocket((location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/ws/live");
  ws.onmessage = (ev) => {
    const m = JSON.parse(ev.data);
    if (m.t === "tick") {
      const prev = frame;
      frame = m;
      const pos = {};
      for (const b of (prev || m).bots) pos[b[0]] = b;
      for (const [kind, id] of m.fx || []) {
        const b = pos[id];
        if (b) effects.push({ kind, x: b[1], y: b[2], t: performance.now(), life: kind === "death" ? 900 : 300 });
      }
      if (!prev || prev.round !== m.round || (m.turn % 6) === 0) renderFighters();
    } else if (m.t === "state") {
      S = m.state;
      if (!S.game) frame = null;
      if (m.final) finalShow = { ...m.final, until: Date.now() + 20000 };
      render();
    }
  };
  ws.onclose = () => { $("dot").className = "dot bad"; setTimeout(connect, 2000); };
}

setInterval(() => { if (S && finalShow && finalShow.until < Date.now()) { finalShow = null; render(); } }, 1000);
window.addEventListener("resize", () => render());
connect();
requestAnimationFrame(draw);
