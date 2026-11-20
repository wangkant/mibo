"use strict";
// Settings: the sections in a sidebar on the left, one shown on the right.
// This file is the shell: the sidebar, the controls the sections share, and
// loading. Each section is a file of its own under setup/ that registers with
// paSetup.part(key, make) before app.js mounts the page; make(kit) returns
// {node, show}, built the first time the section opens, show() each time.
(() => {
  const ORDER = ["character", "model", "connect", "language", "recs", "memory", "privacy", "shell", "programs", "abilities", "schedule", "device", "about"];
  // Older names for a place in Settings, as ctx.go, the first run and older links say them.
  const ALIASES = {
    figure: "character",
    look: "character",
    where: "language",
    know: "recs",
    computer: "device",
    more: "about",
    places: "connect",
    skills: "abilities",
    tools: "abilities",
  };
  const SVG = "http://www.w3.org/2000/svg";
  const ICONS = {
    check: "M5 12.5l4.2 4.2L19 7",
    eye: "M2.5 12s3.5-6.5 9.5-6.5 9.5 6.5 9.5 6.5-3.5 6.5-9.5 6.5S2.5 12 2.5 12zM12 9.2a2.8 2.8 0 1 0 0 5.6 2.8 2.8 0 0 0 0-5.6z",
    eyeOff: "M3.5 3.5l17 17M10.6 5.6A10 10 0 0 1 12 5.5c6 0 9.5 6.5 9.5 6.5a17 17 0 0 1-2.9 3.7M6.4 6.9C3.9 8.6 2.5 12 2.5 12s3.5 6.5 9.5 6.5a9.6 9.6 0 0 0 4.3-1M9.9 9.9a2.8 2.8 0 0 0 4.2 4.2",
    out: "M14 4.5h5.5V10M19.5 4.5L11 13M18 14v4.5a1 1 0 0 1-1 1H5.5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1H10",
    arrow: "M5 12h14M13 6l6 6-6 6",
    chevron: "M9 6l6 6-6 6",
    cross: "M6.5 6.5l11 11M17.5 6.5l-11 11",
    question: "M9.3 9.2a2.8 2.8 0 1 1 3.8 2.6c-.7.3-1.1.9-1.1 1.6v.3M12 17h.01",
    refresh: "M19.5 11A7.6 7.6 0 0 0 5.6 7.4M5 4v3.8h3.8M4.5 13a7.6 7.6 0 0 0 13.9 3.6M19 20v-3.8h-3.8",
    spark: "M12 3.5l1.9 5.6 5.6 1.9-5.6 1.9L12 18.5l-1.9-5.6-5.6-1.9 5.6-1.9z",
    pencil: "M14.5 5.5l4 4M4.5 19.5l1-4.5L15.8 4.7a1.4 1.4 0 0 1 2 0l1.5 1.5a1.4 1.4 0 0 1 0 2L9 18.5z",
    // The sidebar's marks, one per section.
    character: "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4.5 20a7.5 7.5 0 0 1 15 0",
    model: "M8 3.5v3M16 3.5v3M8 17.5v3M16 17.5v3M3.5 8h3M3.5 16h3M17.5 8h3M17.5 16h3M7.5 6.5h9a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1h-9a1 1 0 0 1-1-1v-9a1 1 0 0 1 1-1z",
    connect: "M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1",
    language: "M4 5.5h9M8.5 3.5v2M6 5.5c.8 3.2 3 5.7 6 7M11 5.5c-.8 3.6-3.4 6.4-6.5 7.5M12.5 20.5l4-9.5 4 9.5M14 17h5",
    recs: "M12 3.5l2.6 5.3 5.9.9-4.3 4.1 1 5.8-5.2-2.7-5.2 2.7 1-5.8-4.3-4.1 5.9-.9z",
    memory: "M9 4.5a3 3 0 0 0-3 3 3 3 0 0 0-1.5 5.3A3 3 0 0 0 9 17.5a2.5 2.5 0 0 0 3 2V5.5a2.5 2.5 0 0 0-3-1zM15 4.5a3 3 0 0 1 3 3 3 3 0 0 1 1.5 5.3 3 3 0 0 1-4.5 4.7 2.5 2.5 0 0 1-3 2",
    privacy: "M12 3.5l7 2.8v5.2c0 4.3-2.9 7.6-7 9-4.1-1.4-7-4.7-7-9V6.3z",
    device: "M4.5 5h15a1 1 0 0 1 1 1v9.5a1 1 0 0 1-1 1h-15a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1zM9 20h6M12 16.5V20",
    shell: "M4.5 4.5h15a1 1 0 0 1 1 1v13a1 1 0 0 1-1 1h-15a1 1 0 0 1-1-1v-13a1 1 0 0 1 1-1zM7.5 9.5l3 2.5-3 2.5M12.5 15h4",
    programs: "M4.5 4.5h15a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1h-6M4.5 4.5a1 1 0 0 0-1 1v9a1 1 0 0 0 1 1h3M3.5 8h17M11 11.5l7.5 2.6-3.2 1.2 2.4 3.2-1.4 1-2.4-3.2-2 2.7z",
    about: "M12 3.5a8.5 8.5 0 1 0 0 17 8.5 8.5 0 0 0 0-17zM12 11v5.5M12 7.8h.01",
    abilities: "M4.5 4.5h6v6h-6zM13.5 4.5h6v6h-6zM4.5 13.5h6v6h-6zM16.5 13.5v6M13.5 16.5h6",
    folder: "M3.5 7a1.5 1.5 0 0 1 1.5-1.5h4.2l2 2.2H19a1.5 1.5 0 0 1 1.5 1.5v8.3A1.5 1.5 0 0 1 19 19H5a1.5 1.5 0 0 1-1.5-1.5z",
    schedule: "M12 3.5a8.5 8.5 0 1 0 0 17 8.5 8.5 0 0 0 0-17zM12 7.5V12l3 2",
    play: "M8 5.5v13l10.5-6.5z",
    trash: "M4.5 6.5h15M9.5 6.5V4.5h5v2M6.5 6.5l1 13h9l1-13",
  };

  let ctx, t;
  let state = null;
  let catalog = null;
  let root, nav, pane;
  // Each section's maker, as its file registers it; the sections built so far; the one shown.
  const makers = {};
  const built = {};
  let current = "";

  // ------------------------------------------------------------- helpers --

  function el(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  }
  function icon(name, cls = "setup-icon") {
    const svg = document.createElementNS(SVG, "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("class", cls);
    const path = document.createElementNS(SVG, "path");
    path.setAttribute("d", ICONS[name]);
    svg.append(path);
    return svg;
  }
  function fill(text, values = {}) {
    return text.replace(/\{(\w+)\}/g, (_, key) => values[key] ?? "");
  }
  // A section's words in the page's language (its namespace in the catalog), its errors over the shared ones.
  // setup/tools.js still brings its own zh and en table.
  function words(ns) {
    const own = typeof ns === "string" ? paI18n.words(ns) : ns[paI18n.lang] || ns.en;
    return { ...own, errors: { ...t.errors, ...own.errors } };
  }
  // A failed fetch has no code of its own: the app itself is gone.
  function say(error, words = t) {
    const code = error instanceof TypeError ? "offline" : error?.message || error;
    return words.errors[code] || words.errors.generic;
  }
  function button(cls, text, onClick) {
    const node = el("button", `setup-button ${cls}`);
    node.type = "button";
    const label = el("span", "setup-button-label", text);
    node.append(label);
    if (onClick) node.addEventListener("click", onClick);
    return node;
  }
  function relabel(node, text) {
    node.querySelector(".setup-button-label").textContent = text;
  }
  // Busy: the button keeps its size, shows a spinner and its new words, and takes no clicks.
  function busy(node, on, text) {
    node.disabled = on;
    node.classList.toggle("setup-busy", on);
    node.setAttribute("aria-busy", String(on));
    if (text !== undefined) relabel(node, text);
  }
  let fieldCount = 0;
  // A label above the control, help under it, and the error under that, tied by aria.
  function field(label, control, help = "") {
    const id = `setup-field-${++fieldCount}`;
    const wrap = el("div", "setup-field");
    const head = el("div", "setup-label-row");
    const name = el("label", "setup-label", label);
    name.htmlFor = id;
    head.append(name);
    control.id = id;
    const helpLine = el("p", "setup-help", help);
    helpLine.id = `${id}-help`;
    helpLine.hidden = !help;
    const error = el("p", "setup-error");
    error.id = `${id}-error`;
    error.hidden = true;
    error.setAttribute("role", "alert");
    wrap.append(head, control, helpLine, error);
    const described = () =>
      [!helpLine.hidden && helpLine.id, !error.hidden && error.id].filter(Boolean).join(" ");
    const target = control.matches("input, textarea, select") ? control : control.querySelector("input, textarea, select");
    target.setAttribute("aria-describedby", described());
    return {
      wrap,
      head,
      label: name,
      control: target,
      help(text) {
        helpLine.replaceChildren();
        if (typeof text === "string") helpLine.textContent = text;
        else if (text) helpLine.append(...text);
        helpLine.hidden = !text || (typeof text === "string" && !text);
        target.setAttribute("aria-describedby", described());
      },
      error(text) {
        error.textContent = text || "";
        error.hidden = !text;
        target.setAttribute("aria-invalid", String(Boolean(text)));
        target.setAttribute("aria-describedby", described());
      },
    };
  }
  function input(cls = "") {
    const node = el("input", `setup-input ${cls}`.trim());
    node.type = "text";
    node.autocomplete = "off";
    node.spellcheck = false;
    return node;
  }
  // A section: its heading and what it is for, then its cards.
  function section(key, hint) {
    const node = el("section", `setup-section setup-section-${key}`);
    node.dataset.part = key;
    const head = el("header", "setup-section-head");
    const heading = el("h2", "setup-section-title", t.names[key]);
    heading.id = `setup-title-${key}`;
    heading.tabIndex = -1;
    node.setAttribute("aria-labelledby", heading.id);
    head.append(heading);
    if (hint) head.append(el("p", "setup-section-hint", hint));
    node.append(head);
    return node;
  }
  // A card on the canvas, with an optional small heading above its rows.
  function card(title) {
    const node = el("div", "setup-card");
    if (title) node.append(el("h3", "setup-card-title", title));
    return node;
  }
  // One line with a switch: its name, what it does, the switch at the end.
  function switchRow(id, name, text, changed) {
    const row = el("div", "setup-option");
    const words = el("div", "setup-option-words");
    const label = el("label", "setup-option-name", name);
    label.htmlFor = `setup-switch-${id}`;
    const about = el("p", "setup-option-text", text);
    about.hidden = !text;
    words.append(label, about);
    const box = el("input", "setup-switch");
    box.type = "checkbox";
    box.id = `setup-switch-${id}`;
    box.setAttribute("role", "switch");
    box.addEventListener("change", () => changed(box));
    row.append(words, box);
    return { row, words, box, about };
  }
  // One line with its name and words on the left and any control on the right.
  function optionRow(name, text, control) {
    const row = el("div", "setup-option");
    const words = el("div", "setup-option-words");
    const about = el("p", "setup-option-text", text || "");
    about.hidden = !text;
    words.append(el("p", "setup-option-name", name), about);
    row.append(words);
    if (control) row.append(control);
    return { row, words, about };
  }
  // A few choices side by side, one of them on.
  function choices(label, options, changed) {
    const group = el("div", "setup-segments");
    group.setAttribute("role", "radiogroup");
    group.setAttribute("aria-label", label);
    for (const [value, text] of options) {
      const item = el("button", "setup-segment", text);
      item.type = "button";
      item.setAttribute("role", "radio");
      item.dataset.value = value;
      item.addEventListener("click", () => changed(value));
      group.append(item);
    }
    return {
      group,
      set(value, disabled = false) {
        for (const item of group.children) {
          item.setAttribute("aria-checked", String(item.dataset.value === value));
          item.disabled = disabled;
        }
      },
    };
  }
  function errorLine() {
    const line = el("p", "setup-error");
    line.setAttribute("role", "alert");
    line.hidden = true;
    return line;
  }
  function failed(line, error, words = t) {
    line.textContent = say(error, words);
    line.hidden = false;
  }
  // A fold for what most people leave alone.
  function fold(title) {
    const node = el("details", "setup-fold");
    const summary = el("summary", "setup-fold-summary");
    summary.append(icon("chevron", "setup-icon setup-fold-chevron"), el("span", "", title));
    const body = el("div", "setup-fold-body");
    node.append(summary, body);
    return { node, summary, body };
  }
  // A small icon button; an aria label says what it does.
  function iconButton(cls, mark, label, onClick) {
    const node = el("button", cls);
    node.type = "button";
    node.title = label;
    node.setAttribute("aria-label", label);
    node.append(icon(mark, "setup-icon setup-icon-sm"));
    if (onClick) node.addEventListener("click", onClick);
    return node;
  }

  // What the sections are handed: the helpers, and the app's state as the shell last read it.
  const kit = {
    el, icon, fill, words, say, button, relabel, busy, field, input, section, card, switchRow, optionRow,
    choices, errorLine, failed, fold, iconButton,
    get ctx() {
      return ctx;
    },
    get lang() {
      return paI18n.lang;
    },
    get state() {
      return state;
    },
    set state(value) {
      state = value;
    },
    get catalog() {
      return catalog;
    },
    // Another section, as the sidebar opens it.
    open: (key) => open(key, false),
  };

  // ============================================================== frame ==

  function buildNav() {
    nav = el("nav", "setup-nav");
    nav.setAttribute("aria-label", t.nav);
    const list = el("div", "setup-nav-list");
    for (const key of ORDER) {
      if (!makers[key]) continue;
      const item = el("button", "setup-nav-item");
      item.type = "button";
      item.dataset.part = key;
      item.append(icon(key, "setup-icon setup-nav-icon"), el("span", "setup-nav-name", t.names[key]));
      item.addEventListener("click", () => open(key, false));
      list.append(item);
    }
    nav.append(el("h1", "setup-title", t.title), list);
    return nav;
  }

  async function mount(node, context) {
    ctx = context;
    t = paI18n.words("setup");
    root = el("div", "setup-page");
    root.lang = paI18n.locale;
    pane = el("div", "setup-pane");
    const loading = el("div", "setup-loading");
    for (let i = 0; i < 2; i++) loading.append(el("div", "setup-loading-block"));
    pane.append(loading);
    root.append(buildNav(), pane);
    node.replaceChildren(root);
    try {
      [state, catalog] = await Promise.all([ctx.api("state"), ctx.api("catalog")]);
    } catch (error) {
      loading.replaceWith(el("p", "setup-error setup-error-page", say(error)));
      return;
    }
    loading.remove();
    const { part, asked, place } = waiting;
    waiting = { part: "", asked: false, place: "" };
    open(resolve(part), asked, place);
  }

  // The section a name asks for; else the one shown last, else the first.
  function resolve(key) {
    if (makers[key]) return key;
    if (current) return current;
    return state.configured ? ORDER.find((one) => makers[one]) : "model";
  }

  // `asked`: a link named this section, which may do more with it (the model opens its form); `place`: the
  // rest of the link, for the section to read. Asked for before the page finished loading: done once it has.
  let waiting = { part: "", asked: false, place: "" };
  function open(key, asked, place = "") {
    if (!state) {
      waiting = { part: key, asked, place };
      return;
    }
    if (!built[key]) {
      built[key] = makers[key](kit);
      pane.append(built[key].node);
    }
    current = key;
    for (const [one, made] of Object.entries(built)) made.node.hidden = one !== key;
    for (const item of nav.querySelectorAll(".setup-nav-item")) {
      const on = item.dataset.part === key;
      item.classList.toggle("active", on);
      if (on) item.setAttribute("aria-current", "page");
      else item.removeAttribute("aria-current");
    }
    built[key].show(asked, place);
    root.parentElement.scrollTop = 0;
  }

  // A place in Settings by name, as app.js passes on a link like "setup/model" or "setup/tools/market/time".
  function show(part) {
    const [name, ...rest] = String(part || "").split("/");
    const key = ALIASES[name] || name;
    // Skills and connectors are tabs of one section: the tab's name goes on with the rest of the link.
    const place = (key === "abilities" && name !== key ? [name, ...rest] : rest).join("/");
    // Before the page has loaded the name waits as it is; the sections are known once it has.
    if (!state) waiting = { part: key, asked: Boolean(key), place };
    else open(resolve(key), Boolean(makers[key]), place);
  }

  function part(key, make) {
    makers[key] = make;
  }

  // 能力: skills and connectors in one section, a tab each (setup/skills.js, setup/tools.js), each tab built the
  // first time it opens; the tabs' own headings give way to the section's.
  part("abilities", () => {
    const node = section("abilities");
    const tabs = choices(t.names.abilities, [["skills", t.names.skills], ["tools", t.names.tools]], (key) => tab(key, false, ""));
    node.firstChild.append(tabs.group);
    const inner = {};
    let shown = "skills";
    function tab(key, asked, place) {
      shown = key;
      tabs.set(key);
      if (!inner[key]) {
        inner[key] = makers[key](kit);
        inner[key].node.querySelector(".setup-section-title").hidden = true;
        node.append(inner[key].node);
      }
      for (const [one, made] of Object.entries(inner)) made.node.hidden = one !== key;
      inner[key].show(asked, place);
    }
    // `place`: "skills" or "tools", then what that tab reads ("tools/market/<id>").
    function show(asked, place) {
      const [key, ...rest] = place.split("/");
      tab(key === "skills" || key === "tools" ? key : shown, asked, rest.join("/"));
    }
    return { node, show };
  });

  window.paSetup = { mount, show, part };
})();
