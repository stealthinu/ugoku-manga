"use strict";
(async () => {
  const d = await (await fetch("data.json")).json();
  let scores = {};
  try { scores = await (await fetch("scores.json")).json(); } catch {}
  const list = document.getElementById("list");
  let np = 0, nv = 0;
  for (const w of d.works) {
    const h = document.createElement("div"); h.className = "work"; h.textContent = w.title || w.id; list.appendChild(h);
    const g = document.createElement("div"); g.className = "grid"; list.appendChild(g);
    for (const p of d.pages.filter(p => p.work === w.id)) {
      np++;
      const n = p.panels.filter(q => q.mp4).length; nv += n;
      const sv = p.panels.filter(q => q.mp4 && scores[q.id]).map(q => scores[q.id]);
      const avg = sv.length ? sv.reduce((a, b) => a + b, 0) / sv.length : null;
      const a = document.createElement("a"); a.className = "card"; a.href = `page.html?p=${encodeURIComponent(p.id)}`;
      const img = document.createElement("img"); img.src = p.thumb || p.image; img.alt = p.id; a.appendChild(img);
      if (avg) { const b = document.createElement("span"); b.className = "badge"; b.textContent = avg.toFixed(1); a.appendChild(b); }
      const cap = document.createElement("div"); cap.className = "cap";
      cap.innerHTML = "<span></span><span></span>"; cap.children[0].textContent = p.label || p.id; cap.children[1].textContent = `${n} moving`;
      a.appendChild(cap); g.appendChild(a);
    }
  }
  document.getElementById("sum").textContent = `${d.works.length} work(s) / ${np} pages / ${nv} moving panels`;
  window.__ready = true;
})();
