"use strict";
// Layer stack: base page < panel videos (each plays once at `start`) < layers (appear at `t_in`). Page timeline is absolute seconds.
// Test hooks: ?native=1&auto=0 and window.__at(t) freeze the page at time t for screenshots.
const $ = s => document.querySelector(s);
const el = (t, c, p) => { const e = document.createElement(t); if (c) e.className = c; p?.appendChild(e); return e; };
function rng(seed) { let s = seed >>> 0 || 1; return () => (s = (s * 1664525 + 1013904223) >>> 0) / 4294967296; }
function jitter(n, end, ax, ay, ar, seed) {
  const r = rng(seed), k = [{ transform: "translate(0,0) rotate(0)", offset: 0 }];
  for (let i = 1; i <= n; i++) {
    const env = Math.pow(Math.sin(Math.PI * i / (n + 1)), .6);
    k.push({ transform: `translate(${(r() * 2 - 1) * ax * env}px,${(r() * 2 - 1) * ay * env}px) rotate(${(r() * 2 - 1) * ar * env}deg)`, offset: end * i / (n + 1) });
  }
  k.push({ transform: "translate(0,0) rotate(0)", offset: end }, { transform: "translate(0,0) rotate(0)", offset: 1 });
  return k;
}
const seq = (vals, f) => vals.map((v, i) => Object.assign({ offset: i / (vals.length - 1) }, f(v)));
const still = (t, off) => ({ transform: t, offset: off });
// Motion after appearing. dur in ms; u = page px -> display px; r = layer rect
const PRESETS = {
  impact: u => ({ dur: 1200, kf: [still("scale(1)", 0), still(`translate(${-3 * u}px,${2 * u}px) scale(1.6) rotate(-3deg)`, .05), still(`translate(${2 * u}px,${-1 * u}px) scale(.9) rotate(1.5deg)`, .15), still("scale(1.12) rotate(-1deg)", .25), still("scale(1)", .4), still("scale(1)", 1)] }),
  jolt: u => ({ dur: 600, kf: jitter(10, .9, 4 * u, 4 * u, 1.5, 3) }),
  tremble: u => ({ dur: 2400, kf: jitter(46, .95, 1.8 * u, 1.8 * u, .9, 7) }),
  pulse: () => ({ dur: 1500, kf: seq([1, 1.16, 1, 1.16, 1, 1.16, 1], v => ({ transform: `scale(${v})` })) }),
  sway: () => ({ dur: 2200, origin: "50% 90%", kf: seq([0, 5, -5, 5, -5, 0], v => ({ transform: `rotate(${v}deg)` })) }),
  creep: u => ({ dur: 2400, kf: [still("translate(0,0) scale(1)", 0), still(`translate(${4 * u}px,${-2 * u}px) scale(1.07)`, 1)] }),
  slide: u => ({ dur: 500, kf: [still(`translateX(${-16 * u}px)`, 0), still("translateX(0)", 1)], easing: "ease-out" }),
  drop: u => ({ dur: 600, kf: [still(`translateY(${-16 * u}px)`, 0), still("translateY(0)", .5), still(`translateY(${-4 * u}px)`, .7), still("translateY(0)", 1)], easing: "ease-in" }),
  repeat_pop: () => ({ dur: 1500, kf: seq([1, 1.4, 1, 1.4, 1, 1.4, 1], v => ({ transform: `scale(${v})` })) }),
  rhythm: () => ({ dur: 1800, kf: seq([1, 1.14, 1, 1.14, 1, 1.14, 1, 1.14, 1], v => ({ transform: `scale(${v})` })) }),
  tick: u => ({ dur: 700, kf: [still("translate(0,0)", 0), still(`translate(${2 * u}px,${-3 * u}px)`, .2), still("translate(0,0)", .35), still(`translate(${2 * u}px,${-3 * u}px)`, .6), still("translate(0,0)", .8), still("translate(0,0)", 1)] }),
  drip: u => ({ dur: 1400, origin: "50% 0%", kf: [still("translateY(0) scaleY(1)", 0), { transform: `translateY(${9 * u}px) scaleY(1.1)`, offset: .6, easing: "ease-in" }, still(`translateY(${9 * u}px) scaleY(1.1)`, .75), still("translateY(0) scaleY(1)", 1)] }),
  pop: () => ({ dur: 600, kf: seq([1, 1.3, .92, 1.06, 1], v => ({ transform: `scale(${v})` })) }),
  stretch: (u, r) => { const h = r[2] >= r[3]; return { dur: 1300, origin: h ? "0% 50%" : "50% 100%", kf: seq([1, 1.4, 1.4, 1], v => ({ transform: h ? `scale(${v},1)` : `scale(1,${v})`, opacity: v > 1 ? .8 : 1 })) }; },
  line_stretch: (u, r) => { const h = r[2] >= r[3]; return { dur: 1000, iter: 2, kf: seq([1, 1.35, 1], v => ({ transform: h ? `scale(${v},1)` : `scale(1,${v})` })) }; },
  sparkle_blink: () => ({ dur: 1500, iter: 2, kf: seq([1, .1, 1, .1, 1], v => ({ opacity: v, transform: `scale(${v > .5 ? 1.12 : .8}) rotate(${v > .5 ? 8 : 0}deg)` })) }),
  flicker: () => ({ dur: 1600, kf: [1, .2, 1, .3, 1, .15, 1].map((o, i, a) => ({ opacity: o, offset: i / (a.length - 1) })) }),
};
// Entrance animation
function entry(o, u) {
  const a = o.anim || "pop";
  if (o.preset === "mail_slide") return { dur: 550, kf: [{ transform: "translateY(-125%)", opacity: 1, offset: 0 }, { transform: "translateY(0)", opacity: 1, offset: 1 }], easing: "cubic-bezier(.2,.9,.3,1)" };
  if (a === "slide") return { dur: 380, kf: [{ transform: `translateX(${22 * u}px)`, opacity: 0, offset: 0 }, { transform: "translateX(0)", opacity: 1, offset: 1 }], easing: "ease-out" };
  if (a === "fade") return { dur: 450, kf: [{ opacity: 0 }, { opacity: 1 }] };
  if (a === "shake") {
    const mid = jitter(9, .9, 3.5 * u, 2.5 * u, 2, 11).slice(1, -2);
    return { dur: 700, kf: [{ transform: "scale(.5)", opacity: 0, offset: 0 }, { transform: `translate(${3 * u}px,0) scale(1.22)`, opacity: 1, offset: .1 },
      ...mid.map((k, i, arr) => ({ ...k, opacity: 1, offset: .1 + .9 * (i + 1) / (arr.length + 1) })), { transform: "none", opacity: 1, offset: 1 }] };
  }
  return { dur: 380, kf: [{ transform: "scale(.4)", opacity: 0, offset: 0 }, { transform: "scale(1.22)", opacity: 1, offset: .45 }, { transform: "scale(.95)", opacity: 1, offset: .75 }, { transform: "scale(1)", opacity: 1, offset: 1 }], easing: "ease-out" };
}
let GEN = 0, A = [], VIDS = [], TIMERS = [], PG = null, PAGEEL = null, LAYERS = [], OVS = [];
const pct = r => ({ left: r[0] * 100 + "%", top: r[1] * 100 + "%", width: r[2] * 100 + "%", height: r[3] * 100 + "%" });
function reset() {
  GEN++; TIMERS.forEach(clearTimeout); TIMERS = [];
  A.forEach(a => { try { a.cancel(); } catch {} }); A = [];
  for (const v of VIDS) { v.el.pause(); try { v.el.currentTime = 0.001; } catch {} }
}
function schedule(at) {   // at: null = play, number = freeze at that time (s)
  reset();
  const u = PAGEEL.clientWidth / PG.w;
  const add = (node, kf, opts) => { const a = node.animate(kf, opts); A.push(a); if (at != null) { a.pause(); a.currentTime = at * 1000; } return a; };
  for (const L of LAYERS) {
    const e = entry(L.o, u), d = L.o.t_in * 1000;
    add(L.img, e.kf.map(k => ({ ...k })), { duration: e.dur, delay: d, fill: "both", easing: e.easing || "linear" });
    L.img.style.opacity = ""; L.wrap.style.opacity = 1;
    const pn = L.o.preset && L.o.preset !== "mail_slide" ? L.o.preset : (L.o.anim === "shake" ? "tremble" : null);
    if (pn && PRESETS[pn]) {
      const P = PRESETS[pn](u, L.o.rect);
      L.wrap.style.transformOrigin = P.origin || "50% 50%";
      add(L.wrap, P.kf, { duration: P.dur, delay: d + e.dur, iterations: pn === "tremble" ? 2 : (P.iter || 1), easing: P.easing || "linear", fill: "none" });
    }
  }
  for (const O of OVS) {
    O.el.style.opacity = 0;
    add(O.el, [1, .2, 1, .3, 1, .15, 1].map((o, i, a) => ({ opacity: o * .12, offset: i / (a.length - 1) })), { duration: 1600, delay: O.o.t_in * 1000, iterations: 2, fill: "none" });
  }
  for (const v of VIDS) {
    if (at != null) v.el.currentTime = Math.max(0.001, Math.min(at - v.o.start, v.el.duration || 5.1));
    else { const g = GEN; TIMERS.push(setTimeout(() => { if (g === GEN) { v.el.currentTime = 0.001; v.el.play().catch(() => {}); } }, v.o.start * 1000)); }
  }
  if (at == null) {
    const g = GEN, ts = performance.now();
    const tick = () => {
      if (g !== GEN) return;
      const s = (performance.now() - ts) / 1000;
      $("#tbar").textContent = `t = ${s.toFixed(1)}s / ${PG.total_s}s`;
      if (s < PG.total_s + 1) requestAnimationFrame(tick); else $("#status").textContent = "done";
    };
    tick(); $("#status").textContent = "playing";
  }
}
async function init() {
  const d = await (await fetch("data.json")).json(), q = new URLSearchParams(location.search);
  const id = q.get("p") || d.pages[0].id, i = d.pages.findIndex(p => p.id === id), pg = PG = d.pages[i];
  $("#ttl").textContent = (pg.title ? pg.title + " " : "") + (pg.label || pg.id);
  if (i > 0) $("#prev").href = `page.html?p=${encodeURIComponent(d.pages[i - 1].id)}`; else $("#prev").style.visibility = "hidden";
  if (i < d.pages.length - 1) $("#next").href = `page.html?p=${encodeURIComponent(d.pages[i + 1].id)}`; else $("#next").style.visibility = "hidden";
  const page = PAGEEL = $("#page");
  if (q.get("native")) {
    page.classList.add("native"); page.style.setProperty("--nw", pg.w + "px");
    $("#bar").style.display = "none"; $("#tbar").style.display = "none"; document.querySelector("header").style.display = "none"; $("#wrap").style.padding = "0";
  }
  const base = el("img", "base", page); base.src = pg.image; base.draggable = false;
  for (const p of pg.panels) if (p.mp4) {
    const v = el("video", "vlayer", page);
    v.muted = true; v.playsInline = true; v.preload = "auto"; v.loop = false; Object.assign(v.style, pct(p.rect));
    for (const [src, type] of [[p.mp4, "video/mp4"], [p.webm, "video/webm"]]) { if (!src) continue; const so = el("source", "", v); so.src = src; so.type = type; }
    v.addEventListener("loadeddata", () => { try { v.currentTime = 0.001; } catch {} });
    VIDS.push({ el: v, o: p });
  }
  for (const o of [...pg.layers].sort((a, b) => a.order - b.order || a.t_in - b.t_in)) {
    let parent = page, r = o.rect;
    if (o.clip) {
      const c = el("div", "clip", page); Object.assign(c.style, pct(o.clip)); parent = c;
      r = [(o.rect[0] - o.clip[0]) / o.clip[2], (o.rect[1] - o.clip[1]) / o.clip[3], o.rect[2] / o.clip[2], o.rect[3] / o.clip[3]];
    }
    const wrap = el("div", "lay", parent); Object.assign(wrap.style, pct(r));
    const img = el("img", "", wrap); img.src = o.src; img.draggable = false; img.dataset.id = o.id;
    LAYERS.push({ o, wrap, img });
  }
  for (const o of pg.overlays || []) { const e = el("div", "ov", page); Object.assign(e.style, pct(o.rect)); OVS.push({ o, el: e }); }
  const info = $("#info"); info.innerHTML = "";
  for (const p of pg.panels) el("div", "", info).textContent = p.mp4 ? `${p.id}  ${p.start}s  ${p.action}` : `${p.id}  static  ${p.reason || ""}`;
  for (const L of LAYERS) el("div", "", info).textContent = `${L.o.t_in}s ${L.o.kind} ${L.o.anim || L.o.preset || ""} ${L.o.text || ""}`;
  $("#stop").onclick = () => { reset(); $("#status").textContent = "stopped"; };
  $("#replay").onclick = () => schedule(null);
  window.__at = async t => { schedule(t); await new Promise(res => setTimeout(res, 350)); await new Promise(res => requestAnimationFrame(() => requestAnimationFrame(res))); };
  await Promise.all(VIDS.map(v => new Promise(res => {
    if (v.el.readyState >= 2) res(); else { v.el.addEventListener("loadeddata", res, { once: true }); v.el.addEventListener("error", res, { once: true }); setTimeout(res, 6000); }
  })));
  window.__ready = true; window.__pg = pg;
  if (q.get("auto") !== "0" && !q.get("native")) setTimeout(() => schedule(null), 600);
}
init();
