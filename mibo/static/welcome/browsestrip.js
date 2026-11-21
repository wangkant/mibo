"use strict";
// What a site asks of the person, under the pane's bar at the page's top left, as browsers ask: the camera, the
// microphone, the location and the rest (本次允许 / 始终允许 / 不允许), a link that would start a program of this
// computer (打开 / 取消), and a popup the page opened by itself, which was stopped (打开 / 关闭). It has the asking
// cards' one look. browser.py keeps what each tab asked and tells the first of the tab in front; nothing a site asks
// is granted but by a press here. browse.js mounts it and hands it what it is told.
window.paBrowseStrip = ({ pane, area, stage, post, place }) => {
  const ICONS = {
    camera: '<path d="M3.5 8a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-8a2 2 0 0 1-2-2z" /><path d="M15.5 10.5 20.5 7.5v9l-5-3" />',
    microphone: '<rect x="9" y="3.5" width="6" height="11" rx="3" /><path d="M5.5 11.5a6.5 6.5 0 0 0 13 0M12 18v2.5" />',
    geolocation: '<path d="M12 21s-6.5-5.6-6.5-11a6.5 6.5 0 0 1 13 0c0 5.4-6.5 11-6.5 11z" /><circle cx="12" cy="10" r="2.3" />',
    clipboard: '<rect x="5.5" y="5" width="13" height="15.5" rx="2" /><path d="M9 5V3.5h6V5" />',
    ask: '<circle cx="12" cy="12" r="8.5" /><path d="M12 7.5v5.5M12 16.2v.3" />',
    app: '<path d="M14 4h6v6" /><path d="M10 14 20 4" /><path d="M18 14v4a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4" />',
    popup: '<rect x="3.5" y="5" width="17" height="14" rx="2" /><path d="M3.5 9h17" /><path d="M9.5 12.5l5 5M14.5 12.5l-5 5" />',
  };
  // The buttons of each kind, as the page's data-act and what browser.py is told.
  const BUTTONS = {
    permission: [["once", "pa-btn-primary", "allow_once"], ["always", "pa-btn-secondary", "allow_always"], ["no", "pa-btn-ghost", "refuse"]],
    app: [["open", "pa-btn-primary", "allow_once"], ["cancel", "pa-btn-secondary", "refuse"]],
    popup: [["open", "pa-btn-primary", "allow_once"], ["close", "pa-btn-secondary", "refuse"]],
  };
  const words = () => paI18n.words("browse").prompt;
  function el(tag, className = "", text = "") {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text) node.textContent = text;
    return node;
  }
  const strip = el("div", "op-card browse-prompt browse-over");
  strip.setAttribute("role", "dialog");
  strip.setAttribute("aria-live", "polite");
  strip.hidden = true;
  stage.append(strip);
  let prompt = null;
  let drawn = "";

  function draw() {
    const said = words();
    const site = prompt.host || said.thisPage;
    let icon = prompt.kind;
    let title = "";
    let meta = "";
    if (prompt.kind === "permission") {
      icon = ICONS[prompt.what[0]] && prompt.what.length === 1 ? prompt.what[0] : prompt.what.includes("camera") ? "camera" : "ask";
      const what = new Intl.ListFormat(paI18n.locale, { type: "conjunction" }).format(prompt.what.map((kind) => said.kinds[kind]));
      title = paI18n.fill(said.permission, { site, what });
    } else {
      title = paI18n.fill(said[prompt.kind], { site });
      meta = prompt.url.length > 120 ? `${prompt.url.slice(0, 120)}…` : prompt.url;
    }
    const head = el("div", "op-card-head");
    const tile = el("span", "op-card-icon");
    tile.innerHTML = `<svg class="i" viewBox="0 0 24 24" aria-hidden="true">${ICONS[icon]}</svg>`;
    const text = el("div", "op-card-words");
    text.append(el("p", "op-card-title", title));
    if (meta) text.append(el("p", "op-card-meta", meta));
    head.append(tile, text);
    const row = el("div", "op-card-buttons");
    for (const [act, look, action] of BUTTONS[prompt.kind]) {
      const button = el("button", `pa-btn ${look} pa-btn-sm`, said[act]);
      button.type = "button";
      button.dataset.act = act;
      button.addEventListener("click", () => {
        for (const other of row.querySelectorAll("button")) other.disabled = true;
        post("browser/do", { action, tab: prompt.id });
      });
      row.append(button);
    }
    strip.replaceChildren(head, row);
    strip.setAttribute("aria-label", title);
  }
  // At the page's top left, under the bar, within the page.
  function position() {
    const box = area.getBoundingClientRect();
    const room = stage.getBoundingClientRect();
    strip.style.left = `${box.left - room.left + 8}px`;
    strip.style.top = `${box.top - room.top + 8}px`;
    strip.style.maxWidth = `${Math.max(240, box.width - 16)}px`;
  }
  function show() {
    const shown = Boolean(prompt) && !pane.hidden;
    if (shown) {
      const key = JSON.stringify([prompt, paI18n.lang]);
      if (key !== drawn) draw();
      drawn = key;
      position();
    } else drawn = "";
    if (strip.hidden === !shown && !shown) return;
    strip.hidden = !shown;
    place();
  }
  new ResizeObserver(() => {
    if (!strip.hidden) {
      position();
      place();
    }
  }).observe(area);

  return (state) => {
    if (state.open === false) prompt = null;
    if ("prompt" in state) prompt = state.prompt;
    show();
  };
};
