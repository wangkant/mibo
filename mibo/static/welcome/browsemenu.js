"use strict";
// The pane's ··· menu, at the bar's end: the site's zoom (−, its percentage, +, and fit to width), find and print
// (the browser's own find bar and print preview, as Ctrl+F and Ctrl+P open them), copy link, open in the system
// browser, and the last downloads with open and show in folder. browser.py does the work and tells the zoom and
// the downloads; a download begun while the menu is shut marks its button until it is opened.
// It also takes 问 Mibo from the page's right-click menu: the selection goes into the chat beside the page as a
// quote, for the person to send or not. browse.js mounts it and hands it what it is told.
window.paBrowseMenu = ({ pane, bar, stage, post, place, page, beside, chat }) => {
  const ICONS = {
    more: '<circle cx="6" cy="12" r="1.3" /><circle cx="12" cy="12" r="1.3" /><circle cx="18" cy="12" r="1.3" />',
    find: '<circle cx="11" cy="11" r="6.5" /><path d="M16 16l4.5 4.5" />',
    print: '<path d="M7 9V4h10v5" /><rect x="3.5" y="9" width="17" height="8" rx="2" /><path d="M7 14h10v6H7z" />',
    copy: '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1" /><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1" />',
    system: '<path d="M14 4h6v6" /><path d="M10 14 20 4" /><path d="M18 14v4a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4" />',
    minus: '<path d="M6 12h12" />',
    plus: '<path d="M12 6v12M6 12h12" />',
    fit: '<path d="M3.5 12h17M7 8.5 3.5 12 7 15.5M17 8.5l3.5 3.5-3.5 3.5" />',
    file: '<path d="M14 3.5H7a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8.5z" /><path d="M14 3.5v5h5" />',
    folder: '<path d="M3.5 7a2 2 0 0 1 2-2h4l2 2h7a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2z" />',
  };
  const say = (key) => paI18n.words("browse")[key];
  const svg = (name) => `<svg viewBox="0 0 24 24" aria-hidden="true">${ICONS[name]}</svg>`;
  function el(tag, className = "", text = "") {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text) node.textContent = text;
    return node;
  }
  let zoom = 100;
  let fit = false;
  let downloads = [];
  let copied = false;
  // The list as the app page first hears it (the downloads kept from before) marks nothing.
  let heard = false;

  const more = el("button", "browse-btn browse-more");
  more.type = "button";
  more.setAttribute("aria-haspopup", "menu");
  more.addEventListener("click", () => (menu.hidden ? open() : shut()));
  bar.insertBefore(more, bar.querySelector(".browse-minimize"));
  // Over the page, as the address's suggestions are: the WebView is cut away under it (browse.js place()).
  const menu = el("div", "browse-menu browse-over");
  menu.setAttribute("role", "menu");
  menu.hidden = true;
  stage.append(menu);

  function item(act, icon, text, keys = "") {
    const node = el("button", "browse-menu-item");
    node.type = "button";
    node.dataset.act = act;
    node.setAttribute("role", "menuitem");
    node.innerHTML = svg(icon);
    node.append(el("span", "browse-menu-words", text));
    if (keys) node.append(el("kbd", "browse-key", keys));
    return node;
  }
  function small(act, icon, label) {
    const node = el("button", "browse-btn");
    node.type = "button";
    node.dataset.act = act;
    node.innerHTML = svg(icon);
    node.title = label;
    node.setAttribute("aria-label", label);
    return node;
  }
  const size = (bytes) => (bytes >= 1048576 ? `${(bytes / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`);
  function downloadRow(row) {
    const node = el("div", "browse-download");
    node.classList.toggle("is-done", row.state === "done" && !row.gone);
    const icon = el("span", "browse-download-icon");
    icon.innerHTML = svg("file");
    const words = el("div", "browse-download-words");
    const states = say("downloadStates");
    const status = row.gone ? states.gone : row.state === "done" ? size(row.bytes || row.got)
      : row.state === "progress" ? (row.bytes ? states.progressPart.replace("{n}", Math.floor((100 * row.got) / row.bytes)) : states.progress)
        : states[row.state];
    words.append(el("span", "browse-download-name", row.name), el("span", "browse-download-state", status));
    words.title = row.name;
    node.append(icon, words);
    if (row.state === "done" && !row.gone) {
      const go = el("button", "pa-btn pa-btn-ghost pa-btn-sm", say("downloadOpen"));
      go.type = "button";
      go.dataset.act = "dl_open";
      go.dataset.id = row.id;
      node.append(go);
    }
    const folder = small("dl_folder", "folder", say("downloadFolder"));
    folder.dataset.id = row.id;
    node.append(folder);
    return node;
  }
  function draw() {
    const zoomRow = el("div", "browse-menu-zoom");
    const value = el("button", "browse-menu-zoom-value", `${zoom}%`);
    value.type = "button";
    value.dataset.act = "zoom_reset";
    value.title = say("zoomReset");
    const fitNode = el("button", "browse-menu-fit", say("fit"));
    fitNode.type = "button";
    fitNode.dataset.act = "fit";
    fitNode.setAttribute("aria-pressed", String(fit));
    fitNode.title = say(fit ? "fitTitle" : "fitOffTitle");
    fitNode.insertAdjacentHTML("afterbegin", svg("fit"));
    zoomRow.append(el("span", "browse-menu-words", say("zoom")), small("zoom_out", "minus", say("zoomOut")), value,
      small("zoom_in", "plus", say("zoomIn")), fitNode);
    const web = /^https?:/.test(page().url);
    const parts = [zoomRow, el("div", "browse-menu-line"),
      item("find", "find", say("find"), "Ctrl+F"), item("print", "print", say("print"), "Ctrl+P"),
      el("div", "browse-menu-line"),
      item("copy", "copy", say(copied ? "copied" : "copyLink")), item("system", "system", say("system"))];
    for (const node of parts.slice(2)) if (node.dataset?.act) node.disabled = !web;
    if (downloads.length) parts.push(el("div", "browse-menu-line"), el("p", "browse-menu-head", say("downloads")), ...downloads.map(downloadRow));
    // Drawn again as the zoom or a download changes: the focus stays on the same button.
    const focused = menu.contains(document.activeElement) ? document.activeElement.dataset.act : "";
    menu.replaceChildren(...parts);
    menu.setAttribute("aria-label", say("more"));
    if (focused) menu.querySelector(`[data-act="${focused}"]`)?.focus({ preventScroll: true });
  }
  // Under the ··· button, its right edge on the button's, within the stage.
  function position() {
    const button = more.getBoundingClientRect();
    const box = stage.getBoundingClientRect();
    menu.style.right = `${Math.max(8, box.right - button.right)}px`;
    menu.style.top = `${button.bottom + 6 - box.top}px`;
  }
  function open() {
    more.classList.remove("has-new");
    copied = false;
    draw();
    menu.hidden = false;
    more.setAttribute("aria-expanded", "true");
    position();
    place();
    post("browser/do", { action: "menu" });
    menu.querySelector("button:not(:disabled)")?.focus({ preventScroll: true });
  }
  function shut() {
    if (menu.hidden) return;
    menu.hidden = true;
    more.setAttribute("aria-expanded", "false");
    place();
  }
  menu.addEventListener("click", async (event) => {
    const node = event.target.closest("[data-act]");
    if (!node || node.disabled) return;
    const act = node.dataset.act;
    if (act === "copy") {
      await navigator.clipboard.writeText(page().url).catch(() => {});
      copied = true;
      node.querySelector(".browse-menu-words").textContent = say("copied");
      return setTimeout(shut, 700);
    }
    post("browser/do", { action: act, tab: Number(node.dataset.id || 0) });
    // The zoom row stays open for another step; everything else is done with the menu.
    if (!act.startsWith("zoom") && act !== "fit") shut();
  });
  menu.addEventListener("keydown", (event) => {
    const items = [...menu.querySelectorAll("button:not(:disabled)")];
    const at = items.indexOf(document.activeElement);
    if (event.key === "Escape") {
      event.stopPropagation();
      shut();
      more.focus();
    } else if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      items[(at + (event.key === "ArrowDown" ? 1 : -1) + items.length) % items.length]?.focus();
    }
  });
  // A press anywhere else, the app page losing the focus (a click into the site), or the pane leaving shuts it.
  document.addEventListener("mousedown", (event) => {
    if (!menu.contains(event.target) && !more.contains(event.target)) shut();
  });
  window.addEventListener("blur", shut);

  // 问 Mibo on a selection: the chat beside the page comes, and the text goes into its box as a quote.
  function quote(text) {
    beside(true);
    const input = chat()?.querySelector(".chat-input");
    if (!input) return;
    const block = `${text.trim().split(/\r?\n/).map((line) => `> ${line}`).join("\n")}\n\n`;
    const at = input.selectionStart ?? input.value.length;
    input.setRangeText(block, at, input.selectionEnd ?? at, "end");
    input.dispatchEvent(new Event("input"));
    input.focus();
  }

  return (state) => {
    more.innerHTML = svg("more");
    more.title = say("more");
    more.setAttribute("aria-label", say("more"));
    if ("zoom" in state) zoom = state.zoom;
    if ("fit" in state) fit = state.fit;
    if ("downloads" in state) {
      // A new download marks the button while the menu is shut.
      const fresh = state.downloads.some((row) => !downloads.some((old) => old.id === row.id));
      if (fresh && heard && menu.hidden) more.classList.add("has-new");
      downloads = state.downloads;
      heard = true;
    }
    if (state.ask) quote(state.ask);
    if (state.open === false || pane.hidden) shut();
    if (!menu.hidden && ("zoom" in state || "fit" in state || "downloads" in state || "url" in state)) {
      draw();
      position();
      place();
    }
  };
};
