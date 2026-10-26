// The live script UEFN Ducky 1.2.433 put first in every panel page (backend/uefn_plugins/ui_kit.py
// LIVE_PRESENCE_SCRIPT at 3b0c0f69), kept as shipped: PCs still on it share live groups with newer
// ones (liveTwoPages.test.ts).
(function () {
  var C = "uefn-plugin-ui", on = false, n = 0, last = 0, cur = {}, sel = {}, L = null;
  var mine = {}, theirs = {}, far = [], boxes = {}, before = new WeakMap(), down = null, shared = false, incoming = 0, missing = [];
  var following = "", replaying = false, scrolled = [], sentView = "", viewAt = 0, holdsAsk = "";
  var lead = null, wentTo = "", wentFrom = "", wentAt = 0, scrolledTo = "", peers = {}, reached = {};
  var HOLD_AFTER_MS = 1500, HOLD_RENEW_MS = 10000, HOLD_STALE_MS = 30000, VIEW_GAP_MS = 250, VIEW_EVERY_MS = 5000;
  var CONTROL = 'input,textarea,select,button,[contenteditable=""],[contenteditable="true"],[role="button"],[role="slider"],' +
    '[role="checkbox"],[role="switch"],[role="textbox"],[role="spinbutton"],[role="combobox"],[role="option"],' +
    '[role="menuitem"],[draggable="true"],[data-live-lock]';
  var TEXT = 'textarea,select,[contenteditable=""],[contenteditable="true"],[role="textbox"],[role="spinbutton"],[role="combobox"]';
  var NAV = '[role="tab"],a[href^="#"],[data-live-nav]';
  var NOT_TEXT = /^(button|submit|reset|checkbox|radio|range|color|file|image)$/;
  var DOC = "@doc";
  function req(m, p, id) { try { parent.postMessage({ channel: C, id: id || "ducky-live-" + (++n), method: m, params: p }, "*"); } catch (e) {} }
  function q(s) { return String(s).replace(/["\\]/g, "\\$&"); }
  function anchor(el) {
    if (el === document.scrollingElement || el === document.documentElement) return DOC;
    var parts = [], e = el;
    for (var d = 0; e && e.nodeType === 1 && e !== document.body && d < 8; d++, e = e.parentElement) {
      var lid = e.getAttribute("data-live-id");
      if (lid) { parts.unshift('[data-live-id="' + q(lid) + '"]'); return parts.join(">"); }
      if (e.id) { parts.unshift('[id="' + q(e.id) + '"]'); return parts.join(">"); }
      var i = 1, s = e;
      while ((s = s.previousElementSibling)) if (s.tagName === e.tagName) i++;
      parts.unshift(e.tagName.toLowerCase() + ":nth-of-type(" + i + ")");
    }
    parts.unshift("body");
    return parts.join(">");
  }
  function find(a) {
    if (a === DOC) return document.scrollingElement || document.documentElement;
    try { return a ? document.querySelector(a) : null; } catch (e) { return null; }
  }
  function marks() {  // the screen as the plugin names it (data-live-view)
    var m = document.querySelectorAll("[data-live-view]"), parts = [];
    for (var i = 0; i < m.length && i < 8; i++) parts.push(m[i].getAttribute("data-live-view"));
    return parts;
  }
  // The screen this page shows: the plugin's data-live-view marks, else its title, address
  // and selected tabs. A hold or pointer from another screen never shows on this one.
  function view() {
    var parts = marks(), i;
    if (!parts.length) {
      parts.push(document.title, location.hash);
      var picked = document.querySelectorAll('[aria-selected="true"],[aria-current]:not([aria-current="false"])');
      for (i = 0; i < picked.length && i < 8; i++) parts.push((picked[i].textContent || "").trim().slice(0, 40));
    }
    var s = parts.join("|"), h = 0;
    for (i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
    return "v" + h.toString(36);
  }
  function here(v) { return !v || v === view(); }
  function layer() {
    if (!L) {
      L = document.createElement("div");
      L.setAttribute("data-ducky-live", "");
      L.style.cssText = "position:fixed;left:0;top:0;width:0;height:0;pointer-events:none;z-index:2147483647";
      document.documentElement.appendChild(L);
    }
    return L;
  }
  function ours(el) { return L && el && (el === L || L.contains(el)); }
  function tone(k) { var h = 0; for (var i = 0; i < k.length; i++) h = (h * 31 + k.charCodeAt(i)) >>> 0; return "hsl(" + (h % 360) + ",80%,58%)"; }
  function key(f) { return String(f.device || f.user || ""); }
  function tag(col, text, lock) {
    var lab = document.createElement("span");
    lab.style.cssText = "position:absolute;left:-2px;top:-20px;display:inline-flex;align-items:center;gap:4px;padding:1px 6px;" +
      "border-radius:4px;font:600 11px system-ui,sans-serif;color:#000;white-space:nowrap";
    lab.style.background = col;
    if (lock) lab.innerHTML = '<svg width="10" height="11" viewBox="0 0 10 11"><rect x="1" y="5" width="8" height="6" rx="1" fill="#000"/>' +
      '<path d="M3 5V3.5a2 2 0 0 1 4 0V5" stroke="#000" stroke-width="1.4" fill="none"/></svg>';
    lab.appendChild(document.createTextNode(String(text || "Teammate").slice(0, 40)));
    return lab;
  }
  function box(col, text, lock) {
    var el = document.createElement("div");
    el.style.cssText = "position:absolute;left:0;top:0;border:2px solid;border-radius:4px;box-sizing:border-box";
    el.style.borderColor = col;
    if (lock) { el.style.borderStyle = "dashed"; el.style.background = "rgba(128,128,128,.28)"; }
    el.appendChild(tag(col, text, lock));
    layer().appendChild(el);
    return el;
  }
  function over(el, t) {
    if (!t) { el.style.display = "none"; return; }
    var r = t.getBoundingClientRect();
    el.style.display = "block";
    el.style.transform = "translate(" + r.left + "px," + r.top + "px)";
    el.style.width = r.width + "px";
    el.style.height = r.height + "px";
  }
  function pointer(f, d) {
    var k = key(f); if (!k) return;
    var c = cur[k];
    if (!c) {
      var el = document.createElement("div"), col = tone(k);
      el.style.cssText = "position:absolute;left:0;top:0;transition:transform 60ms linear,opacity .4s";
      el.innerHTML = '<svg width="16" height="20" viewBox="0 0 16 20"><path d="M1 1l13 10-6 1-3 6z" stroke="#000" stroke-width="1"/></svg><span></span>';
      el.firstChild.firstChild.setAttribute("fill", col);
      var lab = el.lastChild;
      lab.style.cssText = "position:absolute;left:14px;top:14px;padding:1px 6px;border-radius:4px;font:600 11px system-ui,sans-serif;color:#000;white-space:nowrap";
      lab.style.background = col;
      lab.textContent = String(f.name || "Teammate").slice(0, 40);
      layer().appendChild(el);
      c = cur[k] = { el: el, at: 0 };
    }
    var t = here(d.v) ? find(d.anchor) : null;
    if (!t) { c.el.style.display = "none"; return; }
    var r = t.getBoundingClientRect();
    c.el.style.display = "block";
    c.el.style.opacity = "1";
    c.el.style.transform = "translate(" + (r.left + (+d.fx || 0) * r.width) + "px," + (r.top + (+d.fy || 0) * r.height) + "px)";
    c.at = Date.now();
  }
  function select(f, d) {
    var k = key(f); if (!k) return;
    var s = sel[k] || (sel[k] = { el: box(tone(k), f.name), at: 0, a: "" });
    s.a = String(d.anchor || ""); s.at = Date.now(); over(s.el, find(s.a));
  }

  // -- holds: what this PC presses, and what teammates press here (live at once, else through presence)
  function control(el) {
    if (!el || el.nodeType !== 1 || ours(el) || !el.closest || el.closest("[data-live-nolock],a[href],[role=tab]")) return null;
    return el.closest(CONTROL);
  }
  function isText(el) { return el.matches(TEXT) || (el.tagName === "INPUT" && !NOT_TEXT.test(el.type)); }
  function holding() { return on || shared; }
  function others() {  // anchor -> the hold that greys it here, pressed first wins
    var out = {}, v = view(), k, a, h, i;
    function take(anc, row) { if ((!row.v || row.v === v) && (!out[anc] || row.t < out[anc].t)) out[anc] = row; }
    for (k in theirs) for (a in theirs[k]) take(a, theirs[k][a]);
    for (i = 0; i < far.length; i++) {
      h = far[i];
      if (h && typeof h.anchor === "string" && !(theirs[h.device] && theirs[h.device][h.anchor]))
        take(h.anchor, { t: +h.t || 0, v: String(h.v || ""), name: String(h.name || "Teammate"), col: tone(String(h.device || h.name)) });
    }
    return out;
  }
  function hold(el) {
    var a = anchor(el), held = others()[a];
    if (held) return "";
    var h = mine[a];
    if (!h) { h = mine[a] = { t: Date.now(), sent: Date.now(), v: view() }; req("live.hold", { anchor: a, on: true, t: h.t, v: h.v }); }
    h.end = 0;
    return a;
  }
  function letGo(a) { if (mine[a]) mine[a].end = Date.now() + HOLD_AFTER_MS; }
  function yieldTo(a, t) {  // a teammate pressed the same control first: this PC lets go of it
    var m = mine[a];
    if (!m || m.t < t) return;
    delete mine[a];
    req("live.hold", { anchor: a, on: false });
    var el = find(a), act = document.activeElement;
    if (el && act && el.contains(act) && act.blur) act.blur();
  }
  function theirHold(f, d) {
    var k = key(f), a = d && typeof d.anchor === "string" ? d.anchor : "";
    if (!k || !a) return;
    var hs = theirs[k] || (theirs[k] = {});
    if (d.on === false) { delete hs[a]; paint(); return; }
    var t = +d.t || 0, m = mine[a];
    if (m && m.t < t) return;  // pressed here first: they let go of it
    yieldTo(a, t);
    hs[a] = { at: Date.now(), t: t, v: String(d.v || ""), name: String(f.name || "Teammate"), col: tone(k) };
    paint();
  }
  function farHolds(list) {
    far = Array.isArray(list) ? list : [];
    for (var i = 0; i < far.length; i++) if (far[i] && here(far[i].v)) yieldTo(far[i].anchor, +far[i].t || 0);
    paint();
  }
  function free(el) {
    var b = before.get(el); if (!b) return;
    before.delete(el);
    el.inert = b.inert;
    if (b.aria === null) el.removeAttribute("aria-disabled"); else el.setAttribute("aria-disabled", b.aria);
    el.removeAttribute("data-ducky-held");
  }
  function paint() {
    var want = others();
    for (var b in boxes) if (!want[b]) { free(boxes[b].t); boxes[b].el.remove(); delete boxes[b]; }
    for (var a in want) {
      var h = want[a], x = boxes[a] || (boxes[a] = { el: box(h.col, h.name, true), t: null }), t = find(a);
      if (x.t && x.t !== t) free(x.t);
      if (t && !before.has(t)) {
        before.set(t, { inert: !!t.inert, aria: t.getAttribute("aria-disabled") });
        t.inert = true;
        t.setAttribute("aria-disabled", "true");
        t.setAttribute("data-ducky-held", h.name);
      }
      x.t = t;
      over(x.el, t);
    }
  }
  function clear() {
    for (var k in cur) cur[k].el.remove();
    for (var j in sel) sel[j].el.remove();
    cur = {}; sel = {}; theirs = {}; peers = {}; down = null;
    if (!holding()) mine = {};
    paint();
  }

  // -- following the host: their screen's scroll and tab clicks
  function navOf(el) { return el && el.nodeType === 1 && !ours(el) && el.closest ? el.closest(NAV) : null; }
  function sendView(force) {
    if (!on || replaying) return;
    var t = Date.now(), v = view();
    if (!force && v === sentView && t - viewAt < VIEW_GAP_MS) return;
    sentView = v; viewAt = t;
    var rows = [], seen = [document.scrollingElement || document.documentElement].concat(scrolled);
    for (var i = 0; i < seen.length && rows.length < 8; i++) {
      var el = seen[i];
      if (el && (el === seen[0] || el.isConnected)) rows.push({ anchor: anchor(el), top: el.scrollTop || 0, left: el.scrollLeft || 0 });
    }
    req("live.view", { v: v, at: marks().join("|").slice(0, 400), scroll: rows });
  }
  // The host's screen: this page goes there when the host moved (the plugin opens it), again
  // every 5 s while this page is still where the last try left it (not there yet), never when
  // the follower moved away by themselves; and scrolls with it once it shows the same screen.
  function follow(d) {
    var at = typeof d.at === "string" ? d.at : "", mine = marks().join("|"), t = Date.now();
    if (at && at !== mine && (at !== wentTo || (mine === wentFrom && t - wentAt >= VIEW_EVERY_MS))) {
      wentTo = at; wentFrom = mine; wentAt = t;
      window.dispatchEvent(new CustomEvent("ducky-live-goto", { detail: { view: at } }));
    }
    lead = d;
    catchUp();
  }
  function catchUp() {
    if (!lead || !here(lead.v)) return;
    var rows = lead.scroll || [], s = JSON.stringify(rows);
    lead = null;
    if (s === scrolledTo) return;
    scrolledTo = s;
    replaying = true;
    try {
      rows.forEach(function (r) {
        var el = find(r.anchor);
        if (el) { el.scrollTop = +r.top || 0; el.scrollLeft = +r.left || 0; }
      });
    } finally { setTimeout(function () { replaying = false; }, 50); }
  }
  function navigate(d) {
    var el = navOf(find(d.anchor));
    if (!el) return;
    replaying = true;
    try { el.click(); } finally { replaying = false; }
  }

  // -- pictures that aren't on this PC yet
  function placeholder() {
    var text = incoming ? "Getting picture\u2026" : "Not on this PC yet";
    return "data:image/svg+xml;charset=utf-8," + encodeURIComponent(
      '<svg xmlns="http://www.w3.org/2000/svg" width="320" height="180" viewBox="0 0 320 180">' +
      '<rect width="320" height="180" fill="#80808033"/><g fill="none" stroke="#8a8a8a" stroke-width="2">' +
      '<rect x="138" y="54" width="44" height="34" rx="4"/><path d="M142 84l10-10 8 8 6-6 12 12"/></g>' +
      '<text x="160" y="116" font-family="system-ui,sans-serif" font-size="13" fill="#8a8a8a" text-anchor="middle">' + text + "</text></svg>");
  }
  function ph(el) { return String(el.getAttribute("src") || "").indexOf("data:image/svg+xml") === 0; }
  function stale(el) {  // the plugin loaded something else in it since: not ours any more
    return !el.isConnected || (el.tagName === "IMG" && !ph(el) && el.getAttribute("src") !== el.getAttribute("data-ducky-src"));
  }
  function showMissing(el) {
    if (!shared || stale(el)) return;
    if (el.tagName === "VIDEO") el.poster = placeholder(); else el.setAttribute("src", placeholder());
  }

  setInterval(function () {
    var t = Date.now();
    for (var k in cur) if (t - cur[k].at > 5000) cur[k].el.style.opacity = "0";
    for (var j in sel) { if (t - sel[j].at > 10000) { sel[j].el.remove(); delete sel[j]; } else over(sel[j].el, find(sel[j].a)); }
    for (var a in mine) {
      var h = mine[a];
      if (h.end && t >= h.end) { delete mine[a]; if (holding()) req("live.hold", { anchor: a, on: false }); }
      else if (t - h.sent >= HOLD_RENEW_MS) { h.sent = t; req("live.hold", { anchor: a, on: true, t: h.t, v: h.v }); }
    }
    for (var p in theirs) for (var b in theirs[p]) if (t - theirs[p][b].at > HOLD_STALE_MS) delete theirs[p][b];
    if (on && (view() !== sentView || t - viewAt >= VIEW_EVERY_MS)) sendView(true);
    if (following) catchUp();
    paint();
  }, 1000);
  function replace() { for (var j in sel) over(sel[j].el, find(sel[j].a)); for (var b in boxes) over(boxes[b].el, boxes[b].t); }
  window.addEventListener("scroll", function (e) {
    replace();
    var el = e.target === document ? document.scrollingElement : e.target;
    if (el && el.nodeType === 1 && el !== document.scrollingElement && scrolled.indexOf(el) < 0) {
      scrolled.unshift(el); scrolled.length = Math.min(scrolled.length, 7);
    }
    sendView(false);
  }, true);
  window.addEventListener("resize", replace);

  document.addEventListener("pointermove", function (e) {
    if (down && !down.a && holding() && e.buttons && Math.abs(e.clientX - down.x) + Math.abs(e.clientY - down.y) > 4) down.a = hold(down.el);
    if (!on || document.hidden) return;
    var t = Date.now(); if (t - last < 50) return;
    var el = e.target; if (!el || el.nodeType !== 1 || ours(el)) return;
    var r = el.getBoundingClientRect(); if (!r.width || !r.height) return;
    last = t;
    req("live.pointer", { anchor: anchor(el), fx: Math.round((e.clientX - r.left) / r.width * 1e4) / 1e4,
      fy: Math.round((e.clientY - r.top) / r.height * 1e4) / 1e4, v: view() });
  }, true);
  document.addEventListener("pointerdown", function (e) {
    var el = e.target; if (!el || el.nodeType !== 1 || ours(el)) return;
    var c = control(el);
    if (c) { down = isText(c) || !holding() ? null : { x: e.clientX, y: e.clientY, el: c, a: hold(c) }; return; }  // a text control: its focus holds it
    down = { x: e.clientX, y: e.clientY, el: el, a: "" };
    if (on) req("live.select", { anchor: anchor(el) });
  }, true);
  function up() { if (down && down.a) letGo(down.a); down = null; }
  document.addEventListener("pointerup", up, true);
  document.addEventListener("pointercancel", up, true);
  document.addEventListener("click", function (e) {
    var el = navOf(e.target);
    if (on && el && !replaying) req("live.nav", { anchor: anchor(el) });
  }, true);
  document.addEventListener("focusin", function (e) {
    if (!holding()) return;
    var c = control(e.target);
    if (c && isText(c)) hold(c);
  }, true);
  document.addEventListener("focusout", function (e) {
    var c = control(e.target);
    if (c && isText(c)) letGo(anchor(c));
  }, true);
  document.addEventListener("error", function (e) {
    var el = e.target;
    if (!el || (el.tagName !== "IMG" && el.tagName !== "VIDEO") || ours(el)) return;
    if (el.tagName === "IMG" && ph(el)) return;  // the placeholder itself
    if (missing.indexOf(el) < 0) missing.push(el);
    if (el.tagName === "IMG") el.setAttribute("data-ducky-src", el.getAttribute("src") || "");
    showMissing(el);
  }, true);

  window.addEventListener("message", function (ev) {
    if (ev.source && ev.source !== parent) return;
    var d = ev.data; if (!d || d.channel !== C) return;
    if (holdsAsk && d.id === holdsAsk) { holdsAsk = ""; if (d.ok && d.result) farHolds(d.result.holds); return; }
    if (!d.event) return;
    var e = d.event, from = e.from || {};
    if (e.type === "live.state") { on = !!e.on; if (!on) clear(); else sendView(true); }
    else if (e.type === "live.message" && on && e.topic === "ducky.pointer") pointer(from, e.data || {});
    else if (e.type === "live.message" && on && e.topic === "ducky.select") select(from, e.data || {});
    else if (e.type === "live.message" && on && e.topic === "ducky.hold") theirHold(from, e.data || {});
    else if (e.type === "live.message" && on && e.topic === "ducky.view" && following && key(from) === following) follow(e.data || {});
    else if (e.type === "live.message" && on && e.topic === "ducky.nav" && following && key(from) === following) navigate(e.data || {});
    else if (e.type === "live.follow") { following = String(e.device || ""); lead = null; wentTo = wentFrom = scrolledTo = ""; }
    else if (e.type === "live.holds") farHolds(e.holds);
    else if (e.type === "live.peers") {
      var keep = {}, linked = {}, fresh = false;
      (e.peers || []).forEach(function (p) {
        var pk = key(p); keep[pk] = 1;
        // Reachable ("none": in the group, no link yet; a view sent then reaches nobody).
        if (pk && p.path !== "none") { linked[pk] = 1; if (!reached[pk]) fresh = true; }
      });
      peers = keep; reached = linked;
      if (fresh && on) sendView(true);  // someone new: they get this screen now, not in up to 5 s
      for (var k in cur) if (!keep[k]) { cur[k].el.remove(); delete cur[k]; }
      for (var j in sel) if (!keep[j]) { sel[j].el.remove(); delete sel[j]; }
      for (var h in theirs) if (!keep[h]) delete theirs[h];
      paint();
    } else if (e.type === "sync.state") {
      var was = shared + ":" + incoming, team = shared;
      shared = !!e.shared; incoming = +e.incoming || 0;
      if (was !== shared + ":" + incoming) missing.forEach(showMissing);
      if (shared && !team) { holdsAsk = "ducky-live-holds-" + (++n); req("live.holds", {}, holdsAsk); }
      if (!shared) { far = []; if (!on) mine = {}; paint(); }
    } else if (e.type === "plugin_scope_changed" && e.reason === "synced") {
      var again = missing; missing = [];
      again.forEach(function (el) {
        if (stale(el)) return;
        if (el.tagName === "VIDEO") { el.removeAttribute("poster"); el.load(); return; }
        var src = el.getAttribute("data-ducky-src");
        el.removeAttribute("data-ducky-src");
        if (src) el.setAttribute("src", src);  // fails again: back on the list
      });
    }
  });
})();
