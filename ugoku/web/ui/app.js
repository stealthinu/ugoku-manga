"use strict";
const $ = (s, r = document) => r.querySelector(s);
const el = (t, props = {}, ...kids) => { const e = Object.assign(document.createElement(t), props); for (const k of kids) e.append(k); return e; };
const api = async (url, opt) => { const r = await fetch(url, opt); if (!r.ok) { let m = r.statusText; try { const j = await r.json(); m = j.detail || (j.errors || []).join("; ") || m; } catch {} throw new Error(m); } return r.json(); };
let es = null;

function route() {
  if (es) { es.close(); es = null; }
  const m = location.hash.match(/^#\/project\/([\w.-]+)(?:\/page\/([\w.-]+))?/);
  if (m) return m[2] ? editorView(m[1], m[2]) : projectView(m[1]);
  return homeView();
}
window.addEventListener("hashchange", route);

// ------------------------------------------------------------------ home
async function homeView() {
  const app = $("#app"); app.innerHTML = "";
  const f = el("form", { className: "card", id: "up" });
  f.innerHTML = `<h2 style="margin-top:0">New project</h2>
  <label>Page image (png, jpg, webp) or a zip of pages (natural order)</label><input type="file" name="file" id="file" required accept=".zip,.png,.jpg,.jpeg,.webp,.bmp">
  <div class="row"><div><label>Name</label><input type="text" name="name" id="name"></div>
  <div><label>Reading direction</label><select name="reading" id="reading"><option value="rtl">right to left (Japanese)</option><option value="ltr">left to right</option></select></div>
  <div><label>Video backend</label><select name="backend" id="backend"><option value="dummy">dummy (slow push-in, no GPU)</option><option value="comfy_h3">comfy_h3 (GPU runner)</option><option value="minimax_api">minimax_api (hosted, your key)</option></select></div>
  <div><label>Direction</label><select name="direction" id="direction"><option value="heuristic">detector only (no LLM)</option><option value="llm">vision LLM</option><option value="upload">upload a direction file</option></select></div></div>
  <div class="row" id="llmrow" hidden><div><label>Provider</label><select name="provider" id="provider"><option>claude_cli</option><option>anthropic</option><option>openai_compat</option><option>gemini</option></select></div><div><label>Model (blank = provider default)</label><input type="text" name="model" id="model"></div></div>
  <div id="dfrow" hidden><label>Direction file (ugoku-direction/1 JSON)</label><input type="file" name="direction_file" id="dfile" accept=".json"></div>
  <label><input type="checkbox" name="rights" id="rights" value="true"> I have the right to process these pages (my own work, or permitted by the rights holder).</label>
  <p><button type="submit" id="go">Start</button> <span id="upmsg"></span></p>`;
  app.append(f);
  const sync = () => { $("#llmrow").hidden = $("#direction").value !== "llm"; $("#dfrow").hidden = $("#direction").value !== "upload"; };
  $("#direction").onchange = sync; sync();
  f.onsubmit = async e => {
    e.preventDefault();
    const fd = new FormData(f);
    if (!$("#rights").checked) { fd.delete("rights"); }
    if ($("#direction").value !== "upload") fd.delete("direction_file");
    $("#go").disabled = true; $("#upmsg").textContent = "uploading...";
    try { const r = await api("/api/projects", { method: "POST", body: fd }); location.hash = `#/project/${r.id}`; }
    catch (err) { $("#upmsg").textContent = err.message; $("#upmsg").className = "err"; $("#go").disabled = false; }
  };
  const list = el("div", { className: "card" }, el("h2", { textContent: "Projects" }));
  app.append(list);
  const ps = await api("/api/projects");
  const pl = el("div", { className: "plist" });
  for (const p of ps) pl.append(el("a", { href: `#/project/${p.id}` }, el("span", { textContent: p.name }), el("span", { className: `chip ${p.state}`, textContent: p.state })));
  list.append(ps.length ? pl : el("p", { textContent: "No projects yet.", className: "sub" }));
}

// ------------------------------------------------------------------ project
function chip(s) { return el("span", { className: `chip ${s}`, textContent: s }); }
async function projectView(pid) {
  const app = $("#app"); app.innerHTML = "";
  const head = el("div", { className: "card" }); app.append(head);
  const pages = el("div", { className: "card" }); app.append(pages);
  let lastState = null;
  const render = async s => {
    head.innerHTML = "";
    head.append(el("h2", { textContent: s.name, style: "margin-top:0" }), chip(s.state), " ", el("span", { className: "sub", textContent: `${s.backend} / ${s.direction}${s.stage ? " / " + s.stage : ""}${s.eta_s != null ? " / about " + s.eta_s + " s left" : ""}` }));
    const bar = el("div", { className: "bar", style: "margin:12px 0" }, el("div", { style: `width:${s.pct}%` })); bar.id = "bar"; head.append(bar);
    const st = el("div", { className: "sub", id: "stages" });
    st.textContent = Object.entries(s.stages).filter(([, v]) => v.total).map(([k, v]) => `${k} ${v.done}/${v.total}`).join("   ");
    head.append(st);
    if (s.error) head.append(el("pre", { className: "log err", textContent: s.error }));
    head.append(el("pre", { className: "log", id: "log", textContent: s.log_tail.join("\n") }));
    if (s.state === "done") {
      const ex = el("p");
      ex.append(el("a", { className: "btn", href: `/p/${pid}/out/index.html`, target: "_blank", id: "open", textContent: "Open player" }), " ",
        el("a", { className: "btn sec", href: `/api/projects/${pid}/export/gallery.zip`, textContent: "Gallery zip" }), " ",
        el("a", { className: "btn sec", href: `/api/projects/${pid}/export/clips.zip`, textContent: "Clips zip" }));
      head.append(ex);
    }
    if (s.state !== lastState || !pages.children.length) { lastState = s.state; await renderPages(); }
  };
  const renderPages = async () => {
    const d = await api(`/api/projects/${pid}`);
    pages.innerHTML = ""; pages.append(el("h2", { textContent: `Pages (${d.pages.length})`, style: "margin-top:0" }));
    const g = el("div", { className: "grid" });
    for (const p of d.pages) {
      const c = el("div", { className: "pg", onclick: () => location.hash = `#/project/${pid}/page/${p.page}` },
        el("img", { src: `/p/${pid}/input/${p.page}.png`, loading: "lazy" }), el("div", { textContent: p.page }), chip(p.direct), " ", chip(p.prep));
      if (d.state === "done") {
        const ex = el("div", { className: "sub" }); ex.append(el("a", { href: `/api/projects/${pid}/export/page/${p.page}.html`, textContent: "html", onclick: e => e.stopPropagation() }), " ", el("a", { href: `/api/projects/${pid}/export/page/${p.page}.mp4`, textContent: "mp4", onclick: e => e.stopPropagation() }));
        c.append(ex);
      }
      g.append(c);
    }
    pages.append(g);
  };
  render(await api(`/api/projects/${pid}`));
  es = new EventSource(`/api/projects/${pid}/events`);
  es.onmessage = ev => render(JSON.parse(ev.data));
  es.addEventListener("end", () => { es.close(); es = null; });
}

// ------------------------------------------------------------------ editor
async function editorView(pid, page) {
  const app = $("#app"); app.innerHTML = "";
  let dir;
  try { dir = await api(`/api/projects/${pid}/pages/${page}/direction`); } catch (e) { app.append(el("p", { className: "err", textContent: e.message })); return; }
  const proj = await api(`/api/projects/${pid}`);
  app.append(el("p", {}, el("a", { href: `#/project/${pid}`, textContent: "< project" })));
  const wrap = el("div", { className: "editor" }); app.append(wrap);
  const left = el("div"), right = el("div"); wrap.append(left, right);
  const box = el("div", { className: "stagebox" }); left.append(box);
  const img = el("img", { src: `/p/${pid}/input/${page}.png` }); box.append(img);
  const NS = "http://www.w3.org/2000/svg", svg = document.createElementNS(NS, "svg"); svg.setAttribute("viewBox", "0 0 1000 1000"); svg.setAttribute("preserveAspectRatio", "none"); box.append(svg);
  let sel = 0;
  const msg = el("p", { id: "emsg" });
  const forms = el("div"); right.append(el("h2", { textContent: `${page}: panels`, style: "margin-top:0" }), forms);
  const drawRects = () => {
    svg.innerHTML = "";
    dir.panels.forEach((p, i) => {
      const [x, y, w, h] = p.rect, S = 1000, g = document.createElementNS(NS, "g");
      const r = document.createElementNS(NS, "rect"); r.setAttribute("class", "rect" + (i === sel ? " sel" : "")); r.dataset.i = i;
      Object.entries({ x: x * S, y: y * S, width: w * S, height: h * S }).forEach(([k, v]) => r.setAttribute(k, v));
      const hd = document.createElementNS(NS, "rect"); hd.setAttribute("class", "handle");
      Object.entries({ x: (x + w) * S - 14, y: (y + h) * S - 14, width: 28, height: 28 }).forEach(([k, v]) => hd.setAttribute(k, v));
      const drag = (mode) => ev => {
        ev.preventDefault(); sel = i; const b = svg.getBoundingClientRect(), x0 = ev.clientX, y0 = ev.clientY, o = [...p.rect];
        const mv = e => { const dx = (e.clientX - x0) / b.width, dy = (e.clientY - y0) / b.height;
          if (mode === "move") { p.rect = [Math.min(Math.max(0, o[0] + dx), 1 - o[2]), Math.min(Math.max(0, o[1] + dy), 1 - o[3]), o[2], o[3]]; }
          else { p.rect = [o[0], o[1], Math.min(Math.max(0.02, o[2] + dx), 1 - o[0]), Math.min(Math.max(0.02, o[3] + dy), 1 - o[1])]; }
          drawRects(); drawForms(); };
        const up = () => { removeEventListener("pointermove", mv); removeEventListener("pointerup", up); };
        addEventListener("pointermove", mv); addEventListener("pointerup", up);
      };
      r.addEventListener("pointerdown", drag("move")); hd.addEventListener("pointerdown", drag("size"));
      g.append(r, hd); svg.append(g);
    });
  };
  const field = (lab, inp) => el("div", {}, el("label", { textContent: lab }), inp);
  const drawForms = () => {
    forms.innerHTML = "";
    dir.panels.forEach((p, i) => {
      const f = el("div", { className: "panelform", style: i === sel ? "outline:2px solid var(--warn)" : "" });
      f.onclick = () => { sel = i; drawRects(); };
      const type = el("select", { onchange: () => { p.type = type.value; if (p.type === "h3_full") { p.mode ||= "fl"; p.magnitude ||= "medium"; p.action ||= "The characters shift their weight and breathe naturally."; p.seed ||= 1; } drawForms(); } });
      for (const t of ["h3_full", "static"]) type.append(el("option", { value: t, textContent: t, selected: p.type === t }));
      f.append(el("b", { textContent: `${p.id}  order ${p.order}` }), field("type", type));
      if (p.type === "h3_full") {
        const act = el("textarea", { value: p.action || "", oninput: () => p.action = act.value });
        const mode = el("select", { onchange: () => p.mode = mode.value }); for (const t of ["fl", "f"]) mode.append(el("option", { value: t, textContent: t === "fl" ? "fl (returns to start)" : "f (one-way)", selected: p.mode === t }));
        const mag = el("select", { onchange: () => p.magnitude = mag.value }); for (const t of ["medium", "large"]) mag.append(el("option", { value: t, textContent: t, selected: p.magnitude === t }));
        const seed = el("input", { type: "number", value: p.seed || 0, onchange: () => p.seed = +seed.value });
        const rg = el("button", { className: "sec", textContent: "Regenerate (new seed)", type: "button", onclick: async () => { try { await api(`/api/projects/${pid}/pages/${page}/regenerate`, { method: "POST", body: JSON.stringify({ panel: p.id }) }); msg.textContent = "queued: reload the project page to follow progress"; msg.className = "ok"; } catch (e) { msg.textContent = e.message; msg.className = "err"; } } });
        f.append(field("action", act), el("div", { className: "row" }, field("mode", mode), field("magnitude", mag), field("seed", seed)), rg);
      }
      f.append(el("div", { className: "sub", textContent: `rect ${p.rect.map(v => v.toFixed(3)).join(", ")}` }));
      forms.append(f);
    });
  };
  const save = el("button", { textContent: "Save and rebuild", id: "save", onclick: async () => {
    try { await api(`/api/projects/${pid}/pages/${page}/direction`, { method: "PUT", body: JSON.stringify(dir) }); msg.textContent = "saved; rebuilding"; msg.className = "ok"; setTimeout(() => location.hash = `#/project/${pid}`, 600); }
    catch (e) { msg.textContent = e.message; msg.className = "err"; } } });
  right.append(save, " ", msg);
  const pv = el("div", { className: "previews" });
  for (const [lab, src] of [["original", `/p/${pid}/input/${page}.png`], ["base (text removed)", `/p/${pid}/out/pages/${page}.png`], ["mask", `/p/${pid}/out/work/hide_${page}.png`]]) {
    const i = el("img", { src, alt: lab, title: lab }); i.onerror = () => i.style.display = "none"; pv.append(i);
  }
  right.append(el("h2", { textContent: "Mask preview: original | base | mask" }), pv);
  if (proj.state === "done") right.append(el("h2", { textContent: "Player preview" }), el("iframe", { className: "player", src: `/p/${pid}/out/page.html?p=${page}` }));
  drawRects(); drawForms();
}
route();
