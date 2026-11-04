// Downloads page: lists /api/downloads.
"use strict";

function size(n) {
  return n > 1048576 ? (n / 1048576).toFixed(1) + " MB" : Math.max(1, Math.round(n / 1024)) + " KB";
}

fetch("/api/downloads").then((r) => r.json()).then((list) => {
  const box = document.getElementById("files");
  box.innerHTML = "";
  if (!list.length) { box.textContent = "No files offered."; return; }
  for (const d of list) {
    const row = document.createElement("div"); row.className = "file";
    const a = document.createElement("a"); a.href = "/files/" + encodeURIComponent(d.name); a.textContent = d.title;
    const meta = document.createElement("span"); meta.className = "hint"; meta.textContent = d.name + " · " + size(d.size);
    const about = document.createElement("p"); about.className = "hint"; about.textContent = d.about;
    const sum = document.createElement("code"); sum.className = "sum"; sum.textContent = "SHA256 " + d.sha256;
    row.append(a, meta, about, sum);
    box.append(row);
  }
}).catch(() => { document.getElementById("files").textContent = "Could not load the list."; });
