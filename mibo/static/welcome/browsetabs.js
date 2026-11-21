"use strict";
// The tabs, in the pane's one bar. browser.py keeps the tabs (one WebView each) and tells each state with them.
// The tab in front is the address field (browse.js); the others are their site's initial, or the struck eye of a
// private tab, with a dot on one that plays. A press brings a tab to the front, a middle press or its cross
// closes it, + opens a new one. Ctrl+T, Ctrl+W, Ctrl+Shift+T and Ctrl+Tab do the same from the bar and the pane;
// inside the site browser.py hears them. browse.js mounts it and hands it what it is told.
window.paBrowseTabs = ({ pane, bar, field, post }) => {
  const ICONS = {
    private: '<path d="M3 3l18 18" /><path d="M10.6 5.1A9.8 9.8 0 0 1 12 5c5 0 8.5 4.5 9.5 7a13 13 0 0 1-2.6 3.8M6.6 6.6C4.4 8 3 10.2 2.5 12c1 2.5 4.5 7 9.5 7 1.9 0 3.6-.6 5-1.5" /><path d="M9.9 9.9a3 3 0 0 0 4.2 4.2" />',
    close: '<path d="M7 7l10 10M17 7 7 17" />',
    plus: '<path d="M12 6v12M6 12h12" />',
  };
  const say = (key) => paI18n.words("browse")[key];
  const svg = (name) => `<svg viewBox="0 0 24 24" aria-hidden="true">${ICONS[name]}</svg>`;
  function el(tag, className) {
    const node = document.createElement(tag);
    node.className = className;
    return node;
  }
  function button(className, name, run) {
    const node = el("button", className);
    node.type = "button";
    node.innerHTML = svg(name);
    node.addEventListener("click", run);
    return node;
  }
  function label(node, text) {
    node.title = text;
    node.setAttribute("aria-label", text);
  }
  // The tabs before the one in front, the one in front (the field, never moved: it may have the focus), the
  // tabs after it, and +.
  const strip = el("div", "browse-tabs");
  strip.setAttribute("role", "tablist");
  const before = el("div", "browse-tabs-side");
  const after = el("div", "browse-tabs-side");
  const active = el("div", "browse-tab active");
  active.setAttribute("role", "tab");
  active.setAttribute("aria-selected", "true");
  const shut = button("browse-tab-x", "close", () => post("browser/do", { action: "tab_close", tab: front }));
  active.append(field, shut);
  const add = button("browse-btn browse-tab-new", "plus", () => post("browser/do", { action: "tab_new" }));
  strip.append(before, active, after, add);
  bar.append(strip);
  let tabs = [];
  let front = 0;

  const hostOf = (url) => {
    try {
      return new URL(url).hostname.replace(/^www\./, "");
    } catch {
      return "";
    }
  };
  function tabNode(tab) {
    const node = el("div", "browse-tab");
    node.classList.toggle("private", tab.private);
    node.classList.toggle("loading", tab.loading);
    node.classList.toggle("sound", Boolean(tab.sound));
    const host = hostOf(tab.url);
    const name = tab.title || host || say("newTab");
    const go = el("button", "browse-tab-go");
    go.type = "button";
    go.setAttribute("role", "tab");
    go.setAttribute("aria-selected", "false");
    go.setAttribute("aria-label", name);
    go.title = [tab.private ? say("privateTag") : "", name, tab.url].filter(Boolean).join("\n");
    // The site's initial, as browsers show a site with no icon of its own.
    if (tab.private) go.innerHTML = svg("private");
    else go.textContent = (host || name).slice(0, 1).toUpperCase();
    go.addEventListener("click", () => post("browser/do", { action: "tab_select", tab: tab.id }));
    // A middle press closes a tab, as in browsers.
    go.addEventListener("auxclick", (event) => event.button === 1 && post("browser/do", { action: "tab_close", tab: tab.id }));
    const x = button("browse-tab-x", "close", () => post("browser/do", { action: "tab_close", tab: tab.id }));
    label(x, say("closeTab"));
    node.append(go, x);
    return node;
  }
  function draw() {
    strip.setAttribute("aria-label", say("tabs"));
    const at = Math.max(0, tabs.findIndex((tab) => tab.id === front));
    before.replaceChildren(...tabs.slice(0, at).map(tabNode));
    after.replaceChildren(...tabs.slice(at + 1).map(tabNode));
    active.classList.toggle("loading", Boolean(tabs[at]?.loading));
    label(shut, say("closeTab"));
    label(add, `${say("newTab")} (Ctrl+T)`);
  }

  // The tab keys while the bar or the pane has the focus, or nothing does (not while typing in the chat).
  document.addEventListener("keydown", (event) => {
    const focus = document.activeElement;
    if (pane.hidden || !(event.ctrlKey || event.metaKey) || event.altKey
      || (focus !== document.body && !pane.contains(focus) && !bar.contains(focus))) return;
    const key = event.key.toLowerCase();
    const action = key === "t" ? (event.shiftKey ? "tab_reopen" : "tab_new") : key === "w" ? "tab_close"
      : key === "tab" ? (event.shiftKey ? "tab_prev" : "tab_next") : "";
    if (!action) return;
    event.preventDefault();
    post("browser/do", { action, tab: front });
  });

  return (state) => {
    if (state.open === false) tabs = [];
    if ("tabs" in state) {
      tabs = state.tabs;
      front = state.tab;
    }
    draw();
  };
};
