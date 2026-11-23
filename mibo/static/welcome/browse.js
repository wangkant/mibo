"use strict";
// The browser inside the app window: its one bar, in the window's title bar over the page (as compact browsers
// lay it: the tabs, the tab in front being the address, and the buttons), and the space under it, where
// window.py lays the site's own WebView (browser.py). The site never runs in this page and never sees its token.
// The conversation stays beside the page: the chat on screen, as it is (chat.js), in a column at the page's
// right, so the person talks to the character and watches it work in the page. A window too narrow for both
// lays that column over the page instead, opened and closed from the bar. While the page is in the chat's
// context (the chip in its box) what is sent is done in the page (turns "page" / "page_on").
// 最小化 or Settings put the page behind a chip: it goes on, with its sound and its history, and the chip
// brings it back.
// The bar's ··· menu (zoom, find, print, copy link, the system browser, a private tab, 最小化, downloads) is
// browsemenu.js.
// While the character operates the page for the person (web/operate.py), the chat's box carries the run: each
// step as it happens, a card when something needs their yes, and how it ended (browserun.js); a border round the
// page says whose it is.
(() => {
  const ICONS = {
    back: '<path d="M15 18l-6-6 6-6" />',
    forward: '<path d="M9 18l6-6-6-6" />',
    reload: '<path d="M20 12a8 8 0 1 1-2.34-5.66L20 8.5" /><path d="M20 3.5v5h-5" />',
    stop: '<rect x="6.5" y="6.5" width="11" height="11" rx="1.5" />',
    close: '<path d="M6 6l12 12M18 6 6 18" />',
    minimize: '<path d="M6 18h12" />',
    // The chat beside the page: a window with its right column marked.
    beside: '<rect x="3" y="4" width="18" height="16" rx="2.5" /><path d="M14.5 4v16" /><path d="M17 9h1.5M17 12h1.5" />',
    // The page behind the chip, and its sound: playing, or muted.
    page: '<rect x="3.5" y="5" width="17" height="14" rx="2" /><path d="M3.5 9h17" />',
    sound: '<path d="M4 9.5h3.5L12 5.5v13l-4.5-4H4z" /><path d="M15.5 9a4 4 0 0 1 0 6M18 6.5a7.5 7.5 0 0 1 0 11" />',
    muted: '<path d="M4 9.5h3.5L12 5.5v13l-4.5-4H4z" /><path d="M16 9.5l5 5M21 9.5l-5 5" />',
    plus: '<path d="M12 6v12M6 12h12" />',
    // The address field: a search, a site, a site reached without encryption.
    search: '<circle cx="11" cy="11" r="6.5" /><path d="M16 16l4.5 4.5" />',
    globe: '<circle cx="12" cy="12" r="8.5" /><path d="M3.5 12h17M12 3.5c2.5 2.6 3.5 5.4 3.5 8.5s-1 5.9-3.5 8.5c-2.5-2.6-3.5-5.4-3.5-8.5s1-5.9 3.5-8.5z" />',
    warn: '<path d="M12 4 21 19.5H3z" /><path d="M12 10v4.5M12 17.2v.3" />',
  };
  const say = (key) => paI18n.words("browse")[key];
  const svg = (name) => `<svg viewBox="0 0 24 24" aria-hidden="true">${ICONS[name]}</svg>`;
  // app.js has kept these from the fragment by now.
  const token = sessionStorage.getItem("mibo-setup-token") || "";
  const frameKey = sessionStorage.getItem("mibo-frame") || "";
  const stage = document.querySelector(".stage");
  const chatView = document.getElementById("chat-view");
  if (!frameKey || !stage) return;
  // The chat beside the page, CSS px (browse.css); what a site laid out for a desktop wants, which the window
  // grows to give it (browser.py); and the least a page keeps beside the chat before the chat lies over it instead.
  const BESIDE = parseFloat(getComputedStyle(document.body).getPropertyValue("--pa-beside"));
  const PAGE_WIDE = 1024;
  const PAGE_LEAST = 720;

  const HEADERS = { "Content-Type": "application/json", "X-Mibo-Setup-Token": token,
    "X-Mibo-Window": frameKey };
  function post(path, body) {
    return fetch(`/api/${path}`, {
      method: "POST",
      headers: HEADERS,
      body: JSON.stringify(body),
      credentials: "same-origin",
    }).catch(() => {});
  }
  function el(tag, className = "", text = "") {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text) node.textContent = text;
    return node;
  }

  const pane = el("section", "browse");
  pane.hidden = true;
  const bar = el("div", "browse-bar");
  // The page's frame is the border round it while the character works in it.
  const body = el("div", "browse-body");
  const frame = el("div", "browse-frame");
  const area = el("div", "browse-area");
  frame.append(area);
  // The address field. What the person types opens there: the site it names, else a search for the words
  // (panels/browser.py); the pages they read that match are offered as they type (browsed.py). Not focused, it
  // shows the site and the page's title, and marks a site reached without encryption.
  const field = el("div", "browse-field");
  const mark = el("span", "browse-mark");
  mark.hidden = true;
  const address = el("input", "browse-address");
  address.spellcheck = false;
  address.autocomplete = "off";
  address.setAttribute("role", "combobox");
  address.setAttribute("aria-autocomplete", "list");
  address.setAttribute("aria-controls", "browse-suggest");
  address.setAttribute("aria-expanded", "false");
  const where = el("span", "browse-where");
  const whereHost = el("span", "browse-where-host");
  const whereTitle = el("span", "browse-where-title");
  where.append(whereHost, whereTitle);
  field.append(mark, address, where);
  field.addEventListener("mousedown", (event) => {
    if (event.target === address) return;
    event.preventDefault();
    address.focus();
  });
  // The whole address selected once the field is focused, as browsers do (a click's mouseup would undo it).
  let picked = false;
  address.addEventListener("focus", () => {
    picked = true;
    address.select();
  });
  address.addEventListener("mouseup", (event) => {
    if (picked) event.preventDefault();
    picked = false;
  });
  address.addEventListener("blur", () => {
    close();
    address.value = page.url;
  });
  address.addEventListener("input", offer);
  address.addEventListener("keydown", (event) => {
    if (event.isComposing) return;
    if ((event.key === "ArrowDown" || event.key === "ArrowUp") && rows.length) {
      event.preventDefault();
      active = (active + (event.key === "ArrowDown" ? 1 : -1) + rows.length) % rows.length;
      drawSuggest();
    } else if (event.key === "Enter" && address.value.trim()) {
      const row = rows[active];
      go(row && !row.go ? row.url : address.value.trim());
    } else if (event.key === "Escape") {
      // Not a stop of the run (the page's own Esc): the first puts the address back, the second leaves the field.
      event.stopPropagation();
      if (address.value !== page.url) {
        close();
        address.value = page.url;
        address.select();
      } else address.blur();
    }
  });
  // Under the field: what Enter opens (a search for the words, or the site), then the pages read that match.
  const suggest = el("div", "browse-suggest browse-over");
  suggest.id = "browse-suggest";
  suggest.hidden = true;
  suggest.setAttribute("role", "listbox");
  let rows = [];
  let active = 0;
  let asked = 0;
  const bare = (url) => url.replace(/^https?:\/\/(www\.)?/, "");
  async function offer() {
    const text = address.value.trim();
    const mine = ++asked;
    // Enter before the answer comes opens what is typed.
    active = 0;
    if (!text) return close();
    const answer = await fetch(`/api/browser/suggest?q=${encodeURIComponent(text)}`, { headers: HEADERS, credentials: "same-origin" })
      .then((response) => (response.ok ? response.json() : null)).catch(() => null);
    if (mine !== asked || !answer || document.activeElement !== address) return;
    // In private mode nothing read before is shown.
    const pages = pane.classList.contains("private") ? [] : answer.pages.filter((row) => row.url !== answer.go.url);
    rows = [{ ...answer.go, go: true, text }, ...pages];
    active = 0;
    drawSuggest();
  }
  function option(row, n) {
    const node = el("div", "browse-option");
    node.id = `browse-option-${n}`;
    node.setAttribute("role", "option");
    node.innerHTML = svg(row.go ? (row.search ? "search" : "globe") : "page");
    const words = el("span", "browse-option-words");
    const main = row.go ? (row.search ? row.text : bare(row.url)) : row.title || bare(row.url);
    words.append(el("span", "browse-option-main", main),
      el("span", "browse-option-tail", row.go ? say(row.search ? "searchWeb" : "openAddress") : bare(row.url)));
    node.append(words);
    node.addEventListener("mousedown", (event) => {
      event.preventDefault();
      go(row.go ? row.text : row.url);
    });
    node.addEventListener("mousemove", () => {
      if (active === n) return;
      active = n;
      drawSuggest();
    });
    return node;
  }
  function drawSuggest() {
    suggest.replaceChildren(...rows.map(option));
    suggest.children[active]?.classList.add("active");
    suggest.children[active]?.setAttribute("aria-selected", "true");
    suggest.setAttribute("aria-label", say("suggestions"));
    address.setAttribute("aria-activedescendant", rows.length ? `browse-option-${active}` : "");
    address.setAttribute("aria-expanded", String(rows.length > 0));
    // Under the field, as wide as it or wide enough to read, within the pane.
    const box = field.getBoundingClientRect();
    const room = pane.getBoundingClientRect();
    const stageBox = stage.getBoundingClientRect();
    const wide = Math.min(room.width - 16, Math.max(box.width, 420));
    suggest.style.width = `${wide}px`;
    suggest.style.left = `${Math.max(room.left + 8, Math.min(box.left, room.right - 8 - wide)) - stageBox.left}px`;
    suggest.style.top = `${box.bottom + 6 - stageBox.top}px`;
    suggest.hidden = !rows.length;
    place();
  }
  function close() {
    asked++;
    rows = [];
    suggest.hidden = true;
    address.setAttribute("aria-expanded", "false");
    address.removeAttribute("aria-activedescendant");
    place();
  }
  function go(text) {
    post("browser/go", { text });
    address.blur();
  }
  // The site and the page's title, with the mark of a site reached without encryption (this computer's own
  // addresses are not marked, as in browsers).
  const LOCAL = /^(localhost|127(\.\d+){3}|\[::1\])$/;
  function drawWhere() {
    let url = null;
    try {
      url = new URL(page.url);
    } catch {
      // No page yet: the field shows its hint.
    }
    const host = url ? url.hostname.replace(/^www\./, "") : "";
    whereHost.textContent = host;
    whereTitle.textContent = page.title && page.title !== host ? page.title : "";
    field.title = page.title ? `${page.title}\n${page.url}` : page.url;
    mark.hidden = !(url?.protocol === "http:" && !LOCAL.test(url.hostname));
    mark.innerHTML = svg("warn");
    mark.append(el("span", "", say("notSecure")));
    mark.title = say("notSecureTitle");
  }
  const buttons = {};
  function button(name) {
    const node = el("button", `browse-btn browse-${name}`);
    node.type = "button";
    node.addEventListener("click", () => {
      const action = name === "reload" && pane.classList.contains("loading") ? "stop" : name;
      if (action === "minimize") return hide();
      if (action === "beside") return toggleBeside();
      if (action === "close") shut();
      post("browser/do", { action });
    });
    buttons[name] = node;
    return node;
  }
  function icon(node, name) {
    node.innerHTML = svg(name);
    node.title = say(name);
    node.setAttribute("aria-label", say(name));
  }
  // The menu's private tab opens beside the others (browsetabs.js marks it); while one is in front the address
  // field is tinted.
  function drawPrivate(on) {
    pane.classList.toggle("private", on);
  }
  // The site's zoom, shown a moment as it changes, at the field's end (the ··· menu changes it, and fits the site
  // to the pane's width: browsemenu.js).
  const zoomTag = el("span", "browse-zoom");
  zoomTag.hidden = true;
  field.append(zoomTag);
  let zoomTimer = null;
  // One row: back, forward, reload, the tabs (the one in front is the field), the run, the sound, the chat, ···,
  // 最小化 and close. It lies in the window's title bar, which shows nothing else over the page.
  bar.hidden = true;
  bar.append(button("back"), button("forward"), button("reload"));
  const drawTabs = window.paBrowseTabs({ pane, bar, field, post });
  // The run while the character works in the page (browserun.js): said in the bar while the chat is out of sight.
  const run = window.paBrowseRun({ pane, post, chatNow: () => chatNow(), beside: setBeside, goOn });
  bar.append(run.pill, button("mute"), button("beside"), button("minimize"), button("close"));
  document.getElementById("titlebar").prepend(bar);
  body.append(frame);
  pane.append(body);
  const drawMenu = window.paBrowseMenu({ pane, bar, stage, post, place, page: () => page, beside: setBeside, chat: () => chatNow(), hide });
  const drawStrip = window.paBrowseStrip({ pane, area, stage, post, place });
  // The suggestions lie over the page and over a chat laid on it.
  stage.append(pane, suggest);

  // The page in the chat's context: a chip in its box, taken out with its cross and put back with the button
  // that stands there then.
  const contextRow = el("div", "browse-context");
  // How much the character may do in the page by itself (acting.py), beside the chip: read again at each step.
  const modeSelect = el("select", "pa-select browse-mode");
  for (const value of ["off", "read", "auto"]) modeSelect.append(new Option("", value));
  modeSelect.addEventListener("change", () => post("browser/acting", { area: "browser", mode: modeSelect.value }));
  fetch("/api/browser/acting", { headers: HEADERS, credentials: "same-origin" })
    .then((response) => response.json())
    .then((data) => {
      modeSelect.value = data.modes.browser;
    })
    .catch(() => {});

  // The chat beside the page: the person's own choice ("open" / "closed", kept in this browser), what shows now
  // (null: beside in a window wide enough, out of the way in a narrow one), whether the window is too narrow
  // for both, and whether the page is in the chat's context.
  let choice = "";
  try {
    choice = localStorage.getItem("mibo-beside") || "";
  } catch {
    // Storage refused: it holds for this page only.
  }
  let wanted = choice ? choice === "open" : null;
  let narrow = false;
  let beside = false;
  let context = true;
  // The chat on screen, when one is (Settings has the stage otherwise).
  const chatNow = () => (chatView.hidden ? null : chatView.querySelector(":scope > .chat:not([hidden])"));
  function textButton(className, text, click, title = "") {
    const node = el("button", className, text);
    node.type = "button";
    if (title) node.title = title;
    node.addEventListener("click", click);
    return node;
  }
  // 继续: sent as the person's own message in the chat beside the page (what they typed there, else the
  // button's word), and it goes on with the run that waits (paBeside.take).
  function goOn(text) {
    const input = chatNow()?.querySelector(".chat-input");
    if (!input) return;
    context = true;
    drawContext();
    if (!input.value.trim()) {
      input.value = text;
      input.dispatchEvent(new Event("input"));
    }
    // Sent as Enter in the box sends: the form's own submit would stop a reply on its way instead.
    input.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true }));
  }
  function showOp(next) {
    const before = run.op;
    run.op = next;
    const { needs } = run;
    // A run begins: in a window wide enough the chat shows it beside the page; in a narrow one the chat gets out
    // of the page's way while it acts, and comes back when the run needs the person or has ended.
    if (next && !next.end && (!before || before.end)) wanted = !narrow;
    if (narrow && next && !next.end && needs(before) && !needs(next)) wanted = false;
    if ((needs(next) && !needs(before)) || (narrow && next?.end && before && !before.end)) wanted = true;
    layout();
  }
  // Esc in the app page stops a run (in the page itself, browser.py hears it). Ctrl L goes to the address, as in
  // any browser.
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && run.running() && !pane.hidden) post("browser/do", { action: "op_stop" });
    if ((event.ctrlKey || event.metaKey) && !event.altKey && event.key.toLowerCase() === "l" && !pane.hidden) {
      event.preventDefault();
      address.focus();
    }
  });

  // ---- The chat beside the page
  function drawContext() {
    const form = beside ? chatNow()?.querySelector(".chat-composer") : null;
    if (!form) return contextRow.remove();
    if (contextRow.parentElement !== form) form.prepend(contextRow);
    const modes = say("modes");
    modeSelect.title = modes.title;
    modeSelect.setAttribute("aria-label", modes.title);
    for (const option of modeSelect.options) option.textContent = modes[option.value];
    if (!context) {
      const add = textButton("browse-context-add", say("contextAdd"), () => {
        context = true;
        drawContext();
      }, say("contextAddTitle"));
      add.insertAdjacentHTML("afterbegin", svg("plus"));
      return contextRow.replaceChildren(add, modeSelect);
    }
    const chip = el("span", "browse-context-chip");
    chip.title = `${say("context")}\n${page.url}`;
    chip.innerHTML = svg("page");
    chip.append(el("span", "", page.title || (page.url ? new URL(page.url).hostname : "")));
    const out = textButton("browse-context-x", "", () => {
      context = false;
      drawContext();
    }, say("contextOff"));
    out.innerHTML = svg("close");
    out.setAttribute("aria-label", say("contextOff"));
    chip.append(out);
    contextRow.replaceChildren(chip, modeSelect);
  }
  // Where everything is: the chat beside the page or over it, the chip and the run in its box, the WebView.
  function layout() {
    narrow = stage.clientWidth - BESIDE < PAGE_LEAST;
    beside = !pane.hidden && Boolean(chatNow()) && (wanted ?? !narrow);
    document.body.classList.toggle("beside", beside);
    document.body.classList.toggle("beside-over", beside && narrow);
    buttons.beside.classList.toggle("on", beside);
    buttons.beside.setAttribute("aria-pressed", String(beside));
    buttons.beside.title = say(beside ? "besideOn" : "beside");
    buttons.beside.setAttribute("aria-label", buttons.beside.title);
    drawContext();
    run.draw(beside);
    if (rows.length) drawSuggest();
    place();
  }
  function setBeside(on) {
    wanted = on;
    // Settings has the stage: the chat comes to it first (app.js).
    if (on && !chatNow()) window.paAsk?.("");
    layout();
    if (on) chatNow()?.querySelector(".chat-input")?.focus();
  }
  // The bar's button: the person's own choice, kept.
  function toggleBeside() {
    setBeside(!beside);
    choice = wanted ? "open" : "closed";
    try {
      localStorage.setItem("mibo-beside", choice);
    } catch {
      // Storage refused: it holds for this page only.
    }
  }
  // What a message sent from the chat beside the page carries (chat.js): done in the page while it is in the
  // chat's context, going on with the run that waits on the person.
  window.paBeside = { take: () => (beside && context ? [run.waits() ? "page_on" : "page"] : []) };
  // Another chat or a new one, Settings and back: the chip and the run follow the chat on screen.
  new MutationObserver((records) => {
    if (records.some((record) => record.target === chatView || record.target.parentElement === chatView)) layout();
  }).observe(chatView, { childList: true, attributes: true, attributeFilter: ["hidden"], subtree: true });

  // 最小化 or Settings: the page goes on behind this chip, on the right. Its title brings the page back as it
  // was, the speaker mutes it while it plays, the cross closes it. After a restart, or a reload with no page
  // open, it offers the page open last.
  const chip = el("div", "browse-return");
  chip.hidden = true;
  const chipMute = el("button", "browse-btn browse-sound");
  chipMute.type = "button";
  chipMute.addEventListener("click", () => post("browser/do", { action: "mute" }));
  const chipGo = el("button", "browse-return-go");
  chipGo.type = "button";
  chipGo.addEventListener("click", () => (kept ? post("browser/go", { text: kept.url }) : show()));
  const chipClose = el("button", "browse-btn browse-return-close");
  chipClose.type = "button";
  chipClose.addEventListener("click", () => {
    shut();
    post("browser/do", { action: "close" });
  });
  chip.append(chipMute, chipGo, chipClose);
  stage.append(chip);
  // Whether a page is open (in front or behind the chip), its address and title, its sound, and the page open last.
  let holding = false;
  let page = { url: "", title: "" };
  let sound = { playing: false, muted: false };
  let kept = null;
  function drawChip() {
    chip.hidden = !(kept || (holding && pane.hidden));
    const shown = kept || page;
    const name = shown.title || (shown.url ? new URL(shown.url).hostname : "");
    chipGo.innerHTML = svg("page");
    chipGo.append(el("span", "", kept ? say("reopen").replace("{title}", name) : name));
    chipGo.title = `${say(kept ? "reopenTitle" : "return")}\n${shown.url}`;
    chipMute.hidden = Boolean(kept) || !(sound.playing || sound.muted);
    icon(chipClose, "close");
  }
  // The speaker, in the bar and on the chip, while the page plays sound or is muted.
  function drawSound() {
    for (const node of [buttons.mute, chipMute]) {
      node.innerHTML = svg(sound.muted ? "muted" : "sound");
      node.title = say(sound.muted ? "unmute" : "mute");
      node.setAttribute("aria-label", node.title);
      node.setAttribute("aria-pressed", String(sound.muted));
    }
    buttons.mute.hidden = !(sound.playing || sound.muted);
  }
  // The pane comes to the front, or leaves it: the window makes room for the site, or takes back the size it
  // had for the chat.
  function front(on) {
    if (pane.hidden === !on) return;
    if (!on && document.activeElement === address) address.blur();
    pane.hidden = !on;
    bar.hidden = !on;
    placed = "";
    fold(on);
    drawChip();
    layout();
    room(on);
  }
  // The sidebar folds to its rail while the page is in front, and unfolds when it leaves (app.js decides, by the
  // person's setting): told here whether the screen has no room for the sidebar, a site laid out for a desktop
  // and the chat beside it.
  function fold(on) {
    const side = parseFloat(getComputedStyle(document.body).getPropertyValue("--pa-side-width"));
    window.paSideFold?.(on, side + PAGE_WIDE + (choice === "closed" ? 0 : BESIDE) > screen.availWidth);
  }
  function show() {
    post("browser/do", { action: "return" });
    // Back from Settings: the chat comes to the stage with the page (app.js).
    if (!chatNow()) window.paAsk?.("");
    front(true);
  }
  function hide() {
    post("browser/do", { action: "hide" });
    front(false);
  }

  function words() {
    for (const name of ["back", "forward", "minimize", "close"]) icon(buttons[name], name);
    buttons.beside.innerHTML = svg("beside");
    drawPrivate(pane.classList.contains("private"));
    icon(buttons.reload, pane.classList.contains("loading") ? "stop" : "reload");
    address.setAttribute("aria-label", say("address"));
    address.placeholder = say("typeAddress");
    drawWhere();
    drawSound();
    drawChip();
    layout();
  }

  // Where the WebView goes: the page's space inside its frame, in CSS px, what of this page lies over it (the chat
  // in a narrow window, the suggestions and the ··· menu with their shadow: the WebView is cut there, not made
  // smaller), and the
  // page's device pixels per px. Told again only when it changed.
  let placed = "";
  function place() {
    if (pane.hidden) return;
    const box = area.getBoundingClientRect();
    const cuts = [];
    if (beside && narrow) {
      const left = Math.max(box.left, Math.round(chatView.getBoundingClientRect().left));
      if (left < box.right) cuts.push([left - box.left, 0, box.right - left, box.height]);
    }
    for (const over of stage.querySelectorAll(".browse-over")) {
      if (over.hidden) continue;
      const r = over.getBoundingClientRect();
      const [x, y] = [Math.max(box.left, r.left - 12), Math.max(box.top, r.top)];
      const [x2, y2] = [Math.min(box.right, r.right + 12), Math.min(box.bottom, r.bottom + 16)];
      if (x2 > x && y2 > y) cuts.push([x - box.left, y - box.top, x2 - x, y2 - y]);
    }
    const told = JSON.stringify({ box: [box.left, box.top, box.width, box.height], cuts, scale: devicePixelRatio });
    if (told === placed) return;
    placed = told;
    post("browser/place", JSON.parse(told));
  }
  new ResizeObserver(layout).observe(stage);
  new ResizeObserver(place).observe(area);
  // The window as wide as the site and the chat beside it want, where the screen allows (browser.py grows it
  // once, and keeps the size the person gives it after); 0 when the page leaves the front.
  function room(on) {
    const besideIt = beside && !narrow;
    const wide = innerWidth - area.clientWidth + PAGE_WIDE + (besideIt || choice === "closed" ? 0 : BESIDE);
    post("browser/room", { wide: on ? wide : 0, scale: devicePixelRatio });
  }

  function shut() {
    holding = false;
    kept = null;
    sound = { playing: false, muted: false };
    front(false);
    drawChip();
  }

  // window.py: what the bar shows, and whether the pane is open.
  window.paBrowse = (state) => {
    if (state.open === false) return shut();
    if ("url" in state) page = { url: state.url, title: state.title || "" };
    if ("private" in state) {
      // A private page stays out of the chat until the person puts it in.
      if (state.open || state.private !== pane.classList.contains("private")) context = !state.private;
      drawPrivate(state.private);
    }
    if (state.open) {
      holding = true;
      kept = null;
      wanted = choice ? choice === "open" : null;
      front(true);
    }
    if ("hidden" in state) {
      holding = true;
      front(!state.hidden);
    }
    if ("kept" in state && !holding) kept = state.kept;
    if ("sound" in state) sound = { playing: state.sound, muted: state.muted };
    if ("url" in state && document.activeElement !== address) address.value = state.url;
    // Ctrl L in the site (browser.py): to the address.
    if (state.focus === "address") address.focus();
    if ("back" in state) buttons.back.disabled = !state.back;
    if ("forward" in state) buttons.forward.disabled = !state.forward;
    if ("loading" in state) pane.classList.toggle("loading", state.loading);
    if ("zoom" in state) {
      zoomTag.textContent = `${state.zoom}%`;
      if (state.zoom_show) {
        zoomTag.hidden = false;
        clearTimeout(zoomTimer);
        zoomTimer = setTimeout(() => (zoomTag.hidden = true), 1500);
      }
    }
    if ("operating" in state) showOp(state.operating);
    drawTabs(state);
    drawMenu(state);
    drawStrip(state);
    words();
  };
  // The sidebar while a page is in front: Settings needs the stage, so the page goes behind its chip; a chat,
  // or a new one, shows beside the page (not the sidebar's own fold button).
  document.getElementById("side")?.addEventListener("click", (event) => {
    if (!event.isTrusted || pane.hidden || !event.target.closest("button") || event.target.closest("#side-toggle")) return;
    if (event.target.closest("#side-settings")) return hide();
    wanted = true;
    setTimeout(layout);
  }, true);
  // A player full screen (window.py makes it the whole monitor) whose card is hidden, another chat
  // or page shown, gives full screen up: the window comes back and nothing is left over the page.
  document.addEventListener("fullscreenchange", () => {
    const full = document.fullscreenElement;
    if (!full) return;
    const watch = new ResizeObserver(() => {
      if (document.fullscreenElement !== full) watch.disconnect();
      else if (!full.getClientRects().length) document.exitFullscreen().catch(() => {});
    });
    watch.observe(full);
  });
  words();
  // This page loaded again: a page still open comes back behind its chip, or the page open last is offered.
  post("browser/do", { action: "loaded" });
})();
