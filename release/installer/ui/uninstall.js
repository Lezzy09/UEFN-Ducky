(function () {
  "use strict";

  // Same ids as the host's Stats.Reasons; the Store drops anything else.
  const REASONS = [
    ["reinstall", "Reinstalling or moving to another PC"],
    ["not_using", "I don't use it anymore"],
    ["setup_hard", "Setting it up was too hard"],
    ["ai_trouble", "I couldn't get the AI working"],
    ["uefn_trouble", "It wouldn't connect to UEFN"],
    ["bugs", "Too many bugs or crashes"],
    ["slow", "It's slow or uses too much"],
    ["missing", "It's missing something I need"],
    ["other", "Something else"],
  ];

  const state = { screen: "", reason: "", version: "", running: false };

  const $ = (id) => document.getElementById(id);
  const bridge = window.chrome && window.chrome.webview;
  const send = (msg) => {
    try {
      bridge.postMessage(msg);
    } catch (_) {}
  };

  function show(name) {
    state.screen = name;
    document.querySelectorAll(".screen").forEach((el) => {
      el.classList.toggle("active", el.dataset.screen === name);
    });
  }

  function answer() {
    return { reason: state.reason, text: $("text").value, deleteData: $("delete-data").checked };
  }

  function pick(id) {
    // Pressing the chosen reason again clears it: answering stays optional.
    state.reason = state.reason === id ? "" : id;
    document.querySelectorAll(".reason").forEach((el) => {
      el.setAttribute("aria-checked", String(el.dataset.reason === state.reason));
    });
  }

  function renderReasons() {
    const box = $("reasons");
    REASONS.forEach(([id, label]) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "choice reason";
      btn.dataset.reason = id;
      btn.setAttribute("role", "radio");
      btn.setAttribute("aria-checked", "false");
      const dot = document.createElement("span");
      dot.className = "radio";
      dot.setAttribute("aria-hidden", "true");
      const text = document.createElement("span");
      text.textContent = label;
      btn.append(dot, text);
      btn.addEventListener("click", () => pick(id));
      box.appendChild(btn);
    });
  }

  function setProgress(percent, status) {
    const pct = Math.max(0, Math.min(100, Math.round(percent || 0)));
    $("bar").style.width = pct + "%";
    $("progress").setAttribute("aria-valuenow", String(pct));
    $("progress").classList.toggle("has-progress", pct > 0);
    $("percent").textContent = pct > 0 ? pct + "%" : "";
    if (status) $("status").textContent = status;
  }

  function startUninstall() {
    if (state.running) return;
    state.running = true;
    setProgress(0, "Getting ready…");
    show("progress");
    send(Object.assign({ type: "uninstall" }, answer()));
  }

  function onInit(data) {
    state.version = data.version || "";
    $("version").textContent = state.version ? "v" + state.version : "";
    $("progress-version").textContent = state.version ? "v" + state.version : "";
    if (!data.installed) {
      $("error-title").textContent = "UEFN Ducky isn't installed";
      $("error").textContent = "There's nothing to remove on this PC.";
      $("retry").classList.add("hidden");
      document.querySelector('[data-screen="error"]').classList.add("is-cancelled");
      show("error");
      return;
    }
    show("ask");
  }

  function onDone(data) {
    state.running = false;
    if (data.ok) {
      setProgress(100, "Done");
      $("done-sub").textContent = data.deleted
        ? "Thanks for trying it. Your chats, settings and project data were deleted too."
        : "Thanks for trying it. Your chats and settings are still on this PC, so a reinstall picks up where you left off.";
      show("done");
      return;
    }
    $("error-title").textContent = "Uninstall didn't finish";
    $("error").textContent = data.error || "UEFN Ducky is still installed.";
    show("error");
  }

  // Closing before Uninstall is the same answer as Keep UEFN Ducky.
  function close() {
    if (state.running) return;
    if (state.screen === "ask") send(Object.assign({ type: "keep" }, answer()));
    else send({ type: "finish" });
  }

  // The window has no title bar: any spot that isn't a control drags it.
  const INTERACTIVE = "button, input, textarea, label, a, .choice";
  $("app").addEventListener("mousedown", (ev) => {
    if (ev.button !== 0 || ev.target.closest(INTERACTIVE)) return;
    send({ type: "drag" });
  });

  $("btn-min").addEventListener("click", () => send({ type: "minimize" }));
  $("btn-close").addEventListener("click", close);
  $("keep").addEventListener("click", close);
  $("uninstall").addEventListener("click", startUninstall);
  $("close-done").addEventListener("click", close);
  $("close-error").addEventListener("click", close);
  $("retry").addEventListener("click", startUninstall);

  document.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape") close();
  });

  renderReasons();

  if (bridge) {
    bridge.addEventListener("message", (ev) => {
      const data = ev.data || {};
      if (data.type === "init") onInit(data);
      if (data.type === "progress") setProgress(data.percent, data.status);
      if (data.type === "done") onDone(data);
    });
  }

  send({ type: "ready" });
})();
