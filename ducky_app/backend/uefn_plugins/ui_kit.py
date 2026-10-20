"""Ducky plugin UI kit, served to every plugin panel at ``/plugin-ui/_kit/<file>``.

- ``ducky.js``: the one tag a panel needs. It links ``ducky.css`` beside it, applies
  the app's Appearance variables (``theme.get`` on load, ``appearance_theme`` after)
  and marks the page hidden on ``panel.visibility`` so kit animations pause.
- ``ducky.css``: the page layout (floating side panels, a frameless main area), nav
  rows, buttons, inputs, selects, checkboxes, choice rows, pill tabs, cards, tables,
  badges, empty / loading / error states and a visible focus ring, built only from
  the app's Appearance variables (:mod:`appearance_vars`), never a color literal.

Also :data:`PANEL_ERROR_SCRIPT`, which :mod:`webview` puts at the top of every plugin
HTML page: uncaught errors, rejected promises and ``console.error`` go to the host
over the bridge (``panel.error``), so ``ducky_plugin_errors`` can show them.

Kept as Python strings so the frozen app always carries them.
"""

from __future__ import annotations

CSS = """\
/* Ducky plugin UI kit. Colors, fonts and radii come from the app's Appearance
   variables only, so a panel follows the user's theme. Element defaults use
   :where() (no specificity): a plugin's own rules always win. */

:where(body) {
  margin: 0;
  color: var(--fg);
  background: var(--bg);
  font-family: var(--font-ui);
  font-size: var(--font-ui-size);
  line-height: 1.5;
}
:where(code, pre, kbd, samp) {
  font-family: var(--font-mono);
  font-size: var(--font-mono-size);
}
:where(a) { color: var(--accent); }
:where(a):hover { color: var(--accent-hover); }
:where(h1, h2, h3, h4) { margin: 0 0 8px; color: var(--fg); line-height: 1.25; }
:where(hr) { border: 0; border-top: 1px solid var(--border); }
.dk-muted { color: var(--muted); }
.dk-dim { color: var(--fg-dim); }
.dk-page { padding: 12px; }
.dk-stack { display: flex; flex-direction: column; gap: 8px; }
.dk-row { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }

/* Focus ring: every control, keyboard focus only. */
:where(button, a, input, select, textarea, summary, [tabindex]):focus-visible,
.dk-btn:focus-visible,
.dk-tab:focus-visible,
.dk-input:focus-visible,
.dk-select:focus-visible {
  outline: 2px solid var(--border-focus);
  outline-offset: 2px;
}

/* Buttons: .dk-btn plus --primary / --secondary / --ghost / --danger / --icon. */
:where(button),
.dk-btn {
  box-sizing: border-box;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  min-height: 28px;
  padding: 4px 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--btn-bg);
  color: var(--fg);
  font: inherit;
  cursor: pointer;
}
:where(button):hover,
.dk-btn:hover { background: var(--btn-hover); }
:where(button):active,
.dk-btn:active { background: var(--btn-pressed); }
:where(button):disabled,
.dk-btn:disabled,
.dk-btn[aria-disabled="true"] { opacity: 0.5; cursor: not-allowed; }
.dk-btn--primary { border-color: var(--accent); background: var(--accent); color: var(--fg-inverse); }
.dk-btn--primary:hover { border-color: var(--accent-hover); background: var(--accent-hover); }
.dk-btn--primary:active { background: var(--accent); }
.dk-btn--secondary { background: var(--card); }
.dk-btn--secondary:hover { background: var(--card-hover); }
.dk-btn--ghost { padding: 5px 13px; border: 0; background: none; color: var(--fg-dim); }
.dk-btn--ghost:hover { background: var(--tab-hover); color: var(--fg); }
.dk-btn--danger { border-color: var(--red); background: var(--red-dim); color: var(--red); }
.dk-btn--danger:hover { background: var(--red); color: var(--fg-inverse); }
.dk-btn--icon { width: 28px; min-width: 28px; padding: 0; }
.dk-btn--icon svg { width: 16px; height: 16px; }

/* Inputs, textareas and selects. */
:where(input:not([type="checkbox"], [type="radio"], [type="range"], [type="color"], [type="file"]), textarea, select),
.dk-input,
.dk-select {
  box-sizing: border-box;
  min-height: 28px;
  padding: 4px 8px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--input-bg);
  color: var(--fg);
  font: inherit;
}
:where(input, textarea, select):hover,
.dk-input:hover,
.dk-select:hover { border-color: var(--border-light); }
:where(input, textarea, select):focus,
.dk-input:focus,
.dk-select:focus { border-color: var(--border-focus); }
:where(input, textarea)::placeholder { color: var(--muted); }
:where(input, textarea, select):disabled { opacity: 0.5; cursor: not-allowed; }
:where(select) option,
.dk-select option { background: var(--dropdown-bg); color: var(--fg); }
.dk-input[aria-invalid="true"] { border-color: var(--red); }
.dk-field { display: flex; flex-direction: column; gap: 4px; }
.dk-field__label { color: var(--fg-dim); font-weight: 600; }
.dk-field__hint { color: var(--muted); }

/* Checkboxes and radios: <label class="dk-check"><input type="checkbox"> Label</label>. */
:where(input[type="checkbox"], input[type="radio"]) {
  width: 14px;
  height: 14px;
  margin: 0;
  accent-color: var(--accent);
}
.dk-check { display: inline-flex; align-items: center; gap: 6px; cursor: pointer; }

/* Tabs: .dk-tabs > button.dk-tab[aria-selected="true"]. Rounded pills on the page
   background, like the app's editor tabs; no strip, no underline. */
.dk-tabs { display: flex; flex-wrap: wrap; gap: 4px; }
.dk-tab {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 0;
  padding: 5px 12px;
  border: 0;
  border-radius: var(--radius-sm);
  background: none;
  color: var(--fg-dim);
  font: inherit;
  cursor: pointer;
}
.dk-tab:hover { background: var(--tab-hover); color: var(--fg); }
.dk-tab[aria-selected="true"],
.dk-tab.is-active { background: var(--tab-active); color: var(--fg); }

/* Page layout, like the app: side panels are floating cards, the main area is the page
   background itself (no frame). <div class="dk-layout"><aside class="dk-sidebar">…</aside>
   <main class="dk-main">…</main></div>; .dk-sidebar--right for a panel on the right. */
.dk-layout {
  box-sizing: border-box;
  display: flex;
  gap: 6px;
  height: 100vh;
  padding: 6px;
}
.dk-sidebar {
  box-sizing: border-box;
  flex: 0 0 auto;
  display: flex;
  flex-direction: column;
  gap: 2px;
  width: 220px;
  min-height: 0;
  padding: 8px 4px;
  overflow-y: auto;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--panel-header);
}
.dk-sidebar--right { order: 2; }
.dk-sidebar__title {
  padding: 4px 8px 6px;
  color: var(--muted);
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
.dk-main { flex: 1 1 auto; min-width: 0; min-height: 0; overflow-y: auto; }

/* Nav rows in a side panel: icon + label, rounded and inset, the open one lit.
   <button class="dk-nav-item" aria-current="page"><svg…/> Label</button>. */
.dk-nav-item {
  display: flex;
  align-items: center;
  justify-content: flex-start;
  gap: 8px;
  width: 100%;
  min-height: 30px;
  padding: 4px 8px;
  border: 0;
  border-radius: var(--radius-sm);
  background: none;
  color: var(--fg-dim);
  font: inherit;
  text-align: left;
  cursor: pointer;
}
.dk-nav-item svg { flex: none; width: 15px; height: 15px; }
.dk-nav-item:hover { background: var(--tab-hover); color: var(--fg); }
.dk-nav-item[aria-current="page"],
.dk-nav-item.is-active { background: var(--tab-active); color: var(--fg); }

/* Choice rows instead of radio circles: an icon tile, a title and hint, and a check on
   the picked one. <button class="dk-choice" role="radio" aria-checked="true">
   <span class="dk-choice__icon">…</span><span class="dk-choice__text"><b>Title</b>
   <span class="dk-choice__hint">Hint</span></span></button>. */
.dk-choice {
  display: flex;
  align-items: center;
  justify-content: flex-start;
  gap: 10px;
  width: 100%;
  min-height: 0;
  padding: 7px 10px 7px 8px;
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  background: none;
  color: var(--fg);
  font: inherit;
  text-align: left;
  cursor: pointer;
}
.dk-choice:hover { background: var(--tab-hover); }
.dk-choice[aria-checked="true"],
.dk-choice.is-selected {
  border-color: var(--accent);
  background: color-mix(in srgb, var(--accent) 12%, transparent);
}
.dk-choice__icon {
  flex: none;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: var(--radius-sm);
  background: var(--tab-active);
  color: var(--fg-dim);
}
.dk-choice[aria-checked="true"] .dk-choice__icon,
.dk-choice.is-selected .dk-choice__icon {
  background: color-mix(in srgb, var(--accent) 24%, transparent);
  color: var(--accent);
}
.dk-choice__text { flex: 1; min-width: 0; display: flex; flex-direction: column; }
.dk-choice__hint { color: var(--muted); font-size: 11px; }
.dk-choice[aria-checked="true"]::after,
.dk-choice.is-selected::after {
  content: "\\2713";
  flex: none;
  color: var(--accent);
  font-weight: 700;
}

/* Cards. */
.dk-card {
  padding: 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--card);
  box-shadow: var(--shadow-sm);
}
.dk-card--interactive { cursor: pointer; }
.dk-card--interactive:hover { background: var(--card-hover); border-color: var(--border-light); }
.dk-card__title { margin: 0 0 6px; font-weight: 600; }

/* Tables. */
.dk-table { width: 100%; border-collapse: collapse; }
.dk-table th,
.dk-table td { padding: 6px 8px; border-bottom: 1px solid var(--border); text-align: left; }
.dk-table th { background: var(--panel-header); color: var(--fg-dim); font-weight: 600; }
.dk-table tbody tr:hover { background: var(--bg-hover); }

/* Badges: .dk-badge plus --accent / --success / --warn / --danger / --info. */
.dk-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 1px 8px;
  border: 1px solid var(--border);
  border-radius: 999px;
  background: var(--bg-elevated);
  color: var(--fg-dim);
  font-size: 11px;
  font-weight: 600;
  white-space: nowrap;
}
.dk-badge--accent { border-color: var(--accent); color: var(--accent); }
.dk-badge--success { border-color: var(--green); background: var(--green-dim); color: var(--green); }
.dk-badge--warn { border-color: var(--amber); background: var(--amber-dim); color: var(--amber); }
.dk-badge--danger { border-color: var(--red); background: var(--red-dim); color: var(--red); }
.dk-badge--info { border-color: var(--blue); background: var(--blue-dim); color: var(--blue); }

/* Empty, loading and error states. */
.dk-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 32px 16px;
  color: var(--muted);
  text-align: center;
}
.dk-empty__title { color: var(--fg); font-weight: 600; }
.dk-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 24px;
  color: var(--muted);
}
.dk-loading::before {
  content: "";
  width: 16px;
  height: 16px;
  border: 2px solid var(--border);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: dk-spin 0.8s linear infinite;
}
@keyframes dk-spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) {
  .dk-loading::before { animation-duration: 2.4s; }
}
.dk-error {
  padding: 10px 12px;
  border: 1px solid var(--red);
  border-radius: var(--radius-sm);
  background: var(--red-dim);
  color: var(--red);
}
.dk-error__title { font-weight: 600; }

/* The panel's tab is hidden (panel.visibility): kit animations pause. */
:where(html[data-dk-hidden]) *,
:where(html[data-dk-hidden]) *::before,
:where(html[data-dk-hidden]) *::after { animation-play-state: paused; }
"""

JS = """\
/* Ducky plugin UI kit: <script src="../../_kit/ducky.js"></script> in a panel page.
   Links ducky.css, applies the app's Appearance variables (now and on every theme
   change) and sets html[data-dk-hidden] while the panel's tab is hidden. */
(function () {
  "use strict";
  var CHANNEL = "uefn-plugin-ui";
  var root = document.documentElement;
  var me = document.currentScript;
  if (me && me.src && !document.querySelector("link[data-ducky-kit]")) {
    var link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = me.src.replace(/ducky\\.js(\\?.*)?$/, "ducky.css");
    link.setAttribute("data-ducky-kit", "");
    (document.head || root).appendChild(link);
  }
  function theme(vars) {
    if (!vars || typeof vars !== "object") return;
    Object.keys(vars).forEach(function (key) {
      var value = vars[key];
      if (typeof value === "string") root.style.setProperty("--" + key.replace(/^--/, ""), value);
    });
  }
  window.addEventListener("message", function (ev) {
    var data = ev.data;
    if (!data || data.channel !== CHANNEL) return;
    if (data.id === "ducky-kit-theme" && data.ok && data.result) theme(data.result.vars);
    var event = data.event;
    if (!event) return;
    if (event.type === "appearance_theme") theme(event.vars);
    if (event.type === "panel.visibility") {
      if (event.visible) root.removeAttribute("data-dk-hidden");
      else root.setAttribute("data-dk-hidden", "");
    }
  });
  parent.postMessage({ channel: CHANNEL, id: "ducky-kit-theme", method: "theme.get", params: {} }, "*");
})();
"""

# Put first in every plugin HTML page (webview.py). At most 20 reports per page load.
PANEL_ERROR_SCRIPT = (
    "<script>(function(){var C='uefn-plugin-ui',n=0;"
    "function send(kind,msg,stack){if(n>=20)return;n++;try{parent.postMessage({channel:C,"
    "id:'ducky-panel-error-'+n,method:'panel.error',params:{kind:kind,"
    "message:String(msg==null?'':msg).slice(0,1000),stack:String(stack==null?'':stack).slice(0,4000)}},'*')}"
    "catch(e){}}"
    "window.addEventListener('error',function(e){if(e&&e.message)send('error',e.message,e.error&&e.error.stack)},true);"
    "window.addEventListener('unhandledrejection',function(e){var r=e&&e.reason;"
    "send('rejection',r&&r.message||r,r&&r.stack)});"
    "var ce=console.error;console.error=function(){try{send('console',Array.prototype.map.call(arguments,"
    "function(a){if(a&&a.stack)return a.stack;if(typeof a==='string')return a;try{return JSON.stringify(a)}"
    "catch(e){return String(a)}}).join(' '))}catch(e){}return ce.apply(console,arguments)};})();</script>"
)

# Live editing in every panel, with no plugin code: while the host says the plugin is live
# (bridge event ``live.state``), the pointer is reported about 20 times a second as the
# element under it (``data-live-id``, else an id, else a short tag path from the nearest id)
# and the point as a fraction of that element, so it lands on the same thing at any window
# size; a click or focus reports a selection. Teammates' pointers (``live.message`` topic
# ``ducky.pointer``) are drawn with their name in a click-through layer and fade after 5 s;
# a pointer whose element isn't on this screen doesn't show. Selections get an outline in
# the teammate's colour for 10 s.
LIVE_PRESENCE_SCRIPT = (
    "<script>(function(){var C='uefn-plugin-ui',on=false,n=0,last=0,cur={},sel={},L=null;"
    "function req(m,p){try{parent.postMessage({channel:C,id:'ducky-live-'+(++n),method:m,params:p},'*')}catch(e){}}"
    "function q(s){return String(s).replace(/[\"\\\\]/g,'\\\\$&')}"
    "function anchor(el){var parts=[],e=el;for(var d=0;e&&e.nodeType===1&&e!==document.body&&d<8;d++,e=e.parentElement){"
    "var lid=e.getAttribute('data-live-id');if(lid){parts.unshift('[data-live-id=\"'+q(lid)+'\"]');return parts.join('>')}"
    "if(e.id){parts.unshift('[id=\"'+q(e.id)+'\"]');return parts.join('>')}"
    "var i=1,s=e;while((s=s.previousElementSibling))if(s.tagName===e.tagName)i++;"
    "parts.unshift(e.tagName.toLowerCase()+':nth-of-type('+i+')')}parts.unshift('body');return parts.join('>')}"
    "function layer(){if(!L){L=document.createElement('div');L.setAttribute('data-ducky-live','');"
    "L.style.cssText='position:fixed;left:0;top:0;width:0;height:0;pointer-events:none;z-index:2147483647';"
    "document.documentElement.appendChild(L)}return L}"
    "function ours(el){return L&&el&&(el===L||L.contains(el))}"
    "function tone(k){var h=0;for(var i=0;i<k.length;i++)h=(h*31+k.charCodeAt(i))>>>0;return 'hsl('+(h%360)+',80%,58%)'}"
    "function key(f){return String(f.device||f.user||'')}"
    "function find(a){try{return a?document.querySelector(a):null}catch(e){return null}}"
    "function pointer(f,d){var k=key(f);if(!k)return;var c=cur[k];if(!c){var el=document.createElement('div'),col=tone(k);"
    "el.style.cssText='position:absolute;left:0;top:0;transition:transform 60ms linear,opacity .4s';"
    "el.innerHTML='<svg width=\"16\" height=\"20\" viewBox=\"0 0 16 20\"><path d=\"M1 1l13 10-6 1-3 6z\" stroke=\"#000\" stroke-width=\"1\"/></svg><span></span>';"
    "el.firstChild.firstChild.setAttribute('fill',col);var lab=el.lastChild;"
    "lab.style.cssText='position:absolute;left:14px;top:14px;padding:1px 6px;border-radius:4px;font:600 11px system-ui,sans-serif;color:#000;white-space:nowrap';"
    "lab.style.background=col;lab.textContent=String(f.name||'Teammate').slice(0,40);layer().appendChild(el);c=cur[k]={el:el,at:0}}"
    "var t=find(d.anchor);if(!t){c.el.style.display='none';return}var r=t.getBoundingClientRect();"
    "c.el.style.display='block';c.el.style.opacity='1';"
    "c.el.style.transform='translate('+(r.left+(+d.fx||0)*r.width)+'px,'+(r.top+(+d.fy||0)*r.height)+'px)';c.at=Date.now()}"
    "function select(f,d){var k=key(f);if(!k)return;var s=sel[k];if(!s){var el=document.createElement('div'),col=tone(k);"
    "el.style.cssText='position:absolute;left:0;top:0;border:2px solid;border-radius:4px;box-sizing:border-box';"
    "el.style.borderColor=col;var lab=document.createElement('span');"
    "lab.style.cssText='position:absolute;left:-2px;top:-18px;padding:0 5px;border-radius:3px;font:600 10px system-ui,sans-serif;color:#000;white-space:nowrap';"
    "lab.style.background=col;lab.textContent=String(f.name||'Teammate').slice(0,40);el.appendChild(lab);"
    "layer().appendChild(el);s=sel[k]={el:el,at:0,a:''}}s.a=String(d.anchor||'');s.at=Date.now();place(s)}"
    "function place(s){var t=find(s.a);if(!t){s.el.style.display='none';return}var r=t.getBoundingClientRect();"
    "s.el.style.display='block';s.el.style.transform='translate('+r.left+'px,'+r.top+'px)';"
    "s.el.style.width=r.width+'px';s.el.style.height=r.height+'px'}"
    "function clear(){for(var k in cur)cur[k].el.remove();for(var j in sel)sel[j].el.remove();cur={};sel={}}"
    "setInterval(function(){var t=Date.now();for(var k in cur)if(t-cur[k].at>5000)cur[k].el.style.opacity='0';"
    "for(var j in sel){if(t-sel[j].at>10000){sel[j].el.remove();delete sel[j]}else place(sel[j])}},1000);"
    "document.addEventListener('pointermove',function(e){if(!on||document.hidden)return;var t=Date.now();if(t-last<50)return;"
    "var el=e.target;if(!el||el.nodeType!==1||ours(el))return;var r=el.getBoundingClientRect();if(!r.width||!r.height)return;last=t;"
    "req('live.pointer',{anchor:anchor(el),fx:Math.round((e.clientX-r.left)/r.width*1e4)/1e4,"
    "fy:Math.round((e.clientY-r.top)/r.height*1e4)/1e4})},true);"
    "function picked(e){if(!on)return;var el=e.target;if(el&&el.nodeType===1&&!ours(el))req('live.select',{anchor:anchor(el)})}"
    "document.addEventListener('pointerdown',picked,true);document.addEventListener('focusin',picked,true);"
    "window.addEventListener('message',function(ev){if(ev.source&&ev.source!==parent)return;var d=ev.data;"
    "if(!d||d.channel!==C||!d.event)return;var e=d.event;"
    "if(e.type==='live.state'){on=!!e.on;if(!on)clear()}"
    "else if(e.type==='live.message'&&e.topic==='ducky.pointer'&&on)pointer(e.from||{},e.data||{});"
    "else if(e.type==='live.message'&&e.topic==='ducky.select'&&on)select(e.from||{},e.data||{});"
    "else if(e.type==='live.peers'){var keep={};(e.peers||[]).forEach(function(p){keep[key(p)]=1});"
    "for(var k in cur)if(!keep[k]){cur[k].el.remove();delete cur[k]}for(var j in sel)if(!keep[j]){sel[j].el.remove();delete sel[j]}}});"
    "})();</script>"
)

FILES: dict[str, tuple[str, str]] = {
    "ducky.css": (CSS, "text/css; charset=utf-8"),
    "ducky.js": (JS, "text/javascript; charset=utf-8"),
}
