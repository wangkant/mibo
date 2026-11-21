"use strict";
// The tab strip over the pane's bar. browser.py keeps the tabs (one WebView each) and tells each state with
// them; this draws a tab per page, the one in front marked, a private tab with the struck eye and a speaker on a
// tab that plays. A press brings a tab to the front, its cross closes it, + opens a new one. Ctrl+T, Ctrl+W,
// Ctrl+Shift+T and Ctrl+Tab do the same from the bar and the strip; inside the site browser.py hears them.
// browse.js mounts it and hands it what it is told.
window.paBrowseTabs = (pane, bar, post) => {
  const ICONS = {
    page: '<rect x="3.5" y="5" width="17" height="14" rx="2" /><path d="M3.5 9h17" />',
    private: '<path d="M3 3l18 18" /><path d="M10.6 5.1A9.8 9.8 0 0 1 12 5c5 0 8.5 4.5 9.5 7a13 13 0 0 1-2.6 3.8M6.6 6.6C4.4 8 3 10.2 2.5 12c1 2.5 4.5 7 9.5 7 1.9 0 3.6-.6 5-1.5" /><path d="M9.9 9.9a3 3 0 0 0 4.2 4.2" />',
    sound: '<path d="M4 9.5h3.5L12 5.5v13l-4.5-4H4z" /><path d="M15.5 9a4 4 0 0 1 0 6" />',
    close: '<path d="M7 7l10 10M17 7 7 17" />',
    plus: '<path d="M12 6v12M6 12h12" />',
  };
  const say = (key) => paI18n.words("browse")[key];
  const svg = (name) => `<svg viewBox="0 0 24 24" aria-hidden="true">${ICONS[name]}</svg>`;
  const strip = document.createElement("div");
  strip.className = "browse-tabs";
  strip.setAttribute("role", "tablist");
  pane.insertBefore(strip, bar);
  let tabs = [];
  let front = 0;

  function button(className, name, label, run) {
    const node = document.createElement("button");
    node.type = "button";
    node.className = className;
    node.innerHTML = svg(name);
    node.title = label;
    node.setAttribute("aria-label", label);
    node.addEventListener("click", run);
    return node;
  }
  function tabNode(tab) {
    const node = document.createElement("div");
    node.className = "browse-tab";
    node.classList.toggle("active", tab.id === front);
    node.classList.toggle("private", tab.private);
    node.classList.toggle("loading", tab.loading);
    let name = tab.title;
    if (!name) {
      try {
        name = new URL(tab.url).hostname.replace(/^www\./, "");
      } catch {
        name = say("newTab");
      }
    }
    const go = document.createElement("button");
    go.type = "button";
    go.className = "browse-tab-go";
    go.setAttribute("role", "tab");
    go.setAttribute("aria-selected", String(tab.id === front));
    go.title = [tab.private ? say("privateTag") : "", name, tab.url].filter(Boolean).join("\n");
    go.innerHTML = svg(tab.private ? "private" : "page");
    const words = document.createElement("span");
    words.textContent = name;
    go.append(words);
    if (tab.sound) go.insertAdjacentHTML("beforeend", svg("sound"));
    go.addEventListener("click", () => tab.id !== front && post("browser/do", { action: "tab_select", tab: tab.id }));
    // A middle press closes a tab, as in browsers.
    go.addEventListener("auxclick", (event) => event.button === 1 && post("browser/do", { action: "tab_close", tab: tab.id }));
    node.append(go, button("browse-tab-x", "close", say("closeTab"), () => post("browser/do", { action: "tab_close", tab: tab.id })));
    return node;
  }
  function draw() {
    strip.setAttribute("aria-label", say("tabs"));
    strip.replaceChildren(...tabs.map(tabNode),
      button("browse-btn browse-tab-new", "plus", `${say("newTab")} (Ctrl+T)`, () => post("browser/do", { action: "tab_new" })));
    strip.querySelector(".browse-tab.active")?.scrollIntoView({ block: "nearest", inline: "nearest" });
  }

  // The tab keys while the bar or the strip has the focus, or nothing does (not while typing in the chat).
  document.addEventListener("keydown", (event) => {
    const focus = document.activeElement;
    if (pane.hidden || !(event.ctrlKey || event.metaKey) || event.altKey || (focus !== document.body && !pane.contains(focus))) return;
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
