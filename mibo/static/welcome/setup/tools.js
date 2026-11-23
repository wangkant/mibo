"use strict";
// Settings › 能力 › 连接器: the person's MCP servers (/api/mcp, mcp_hub.py) and the connector market
// (/api/mcp/market, mcp_market.py), in two views like Skills. Installed: each server's state said plainly with
// what to do next, its pinned version and updates, its values (names only: a saved value never comes back),
// its tools each asking, always allowed or never, servers brought over from other apps, and pasting a
// configuration for one the market does not have. Market: a short list chosen for the app, searched here, the
// official MCP Registry searched by name beyond it, and a detail view whose form fills the entry in. A local
// program starts only once the person allows its exact command; every tool asks on a card in the chat first.
// Market entries are data from the network: every string goes on the page as text, never as markup.
// Its words are setup/toolswords.js.
(() => {
  const MAX_FILE = 200_000;
  // A saved secret's reference in an address, as the page shows it.
  const HIDDEN = /\$\{MIBO_MCP_[A-Z0-9_]+\}/g;

  window.paSetup.part("tools", (kit) => {
    const { el, icon, link, fact } = kit;
    const t = kit.words(window.paToolsWords);
    const ctx = kit.ctx;
    const zh = kit.lang === "zh";
    const node = kit.section("tools", t.hint);
    let view = null;
    let market = null;
    let timer = null;
    let shown = "installed";
    const query = { text: "", category: "" };
    let detailOf = null;

    const both = (pair) => (zh ? pair.zh || pair.en : pair.en || pair.zh) || "";

    // ---- The two views
    const head = el("div", "skm-head");
    const tabs = kit.choices(t.views, [["installed", t.installedTab], ["market", t.marketTab]], (value) => switchTo(value));
    head.append(tabs.group);
    const installedPane = el("div", "skm-pane");
    const marketPane = el("div", "skm-pane");
    node.append(head, installedPane, marketPane);

    // ================================================================ installed

    const toolbar = el("div", "skm-toolbar");
    const countLine = el("p", "skm-count");
    const updateAll = kit.button("setup-button-primary setup-button-sm", "", () => updateEvery());
    updateAll.hidden = true;
    const importOpen = kit.button("setup-button-secondary setup-button-sm", t.importOpen, () => lookElsewhere());
    const actions = el("div", "skm-toolbar-actions");
    actions.append(updateAll, importOpen);
    toolbar.append(countLine, actions);
    const installedNote = el("p", "setup-help skm-done");
    installedNote.setAttribute("role", "status");
    installedNote.hidden = true;

    const importCard = kit.card(t.importTitle);
    importCard.hidden = true;
    const importList = el("div", "setup-options");
    const importError = kit.errorLine();
    const importGo = kit.button("setup-button-primary setup-button-sm", t.importGo(0), () => importChosen());
    const importClose = kit.button("setup-button-ghost setup-button-sm", t.importClose, () => {
      importCard.hidden = true;
    });
    const importButtons = el("div", "skm-row");
    importButtons.append(importGo, importClose);
    importCard.append(el("p", "setup-help", t.importHelp), importList, importError, importButtons);

    const listCard = kit.card(t.listTitle);
    const notes = el("div");
    const list = el("div", "setup-options");
    const listError = kit.errorLine();
    listCard.append(notes, list, listError);

    // Pasting: a configuration, an address or a command, for a server the market does not have.
    const addFold = kit.fold(t.addTitle);
    addFold.node.classList.add("skm-add");
    const paste = el("textarea", "setup-input setup-textarea");
    paste.spellcheck = false;
    paste.placeholder = t.pastePlaceholder;
    paste.setAttribute("aria-label", t.addTitle);
    const picker = el("input");
    picker.type = "file";
    picker.hidden = true;
    picker.accept = ".json,application/json";
    const addButton = kit.button("setup-button-primary setup-button-sm", t.add, () => adding(addButton, { add: paste.value }));
    const pickButton = kit.button("setup-button-secondary setup-button-sm", t.pickFile, () => picker.click());
    const addRow = el("div", "setup-shell-add");
    addRow.append(addButton, pickButton, picker);
    const addError = kit.errorLine();
    const addDone = el("p", "setup-help", t.added);
    addDone.hidden = true;
    addFold.body.append(el("p", "setup-help", t.addText), paste, addRow, el("p", "setup-help", t.secretNote), addError, addDone);

    // The record.
    const record = kit.fold(t.logFold(0));
    const logList = el("div", "setup-shell-log");
    const clear = kit.button("setup-button-secondary setup-button-sm", t.logClear, clearLog);
    const logError = kit.errorLine();
    record.body.append(logList, clear, logError);
    record.node.addEventListener("toggle", () => {
      if (record.node.open) loadLog();
    });
    installedPane.append(toolbar, installedNote, importCard, listCard, addFold.node, record.node);

    // ---- Talking to the page.
    // Allowing a program to start is a press only this window's own page can give (panels/tools.py own_page).
    async function ownPost(body) {
      const response = await fetch("/api/mcp", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json",
          "X-Mibo-Setup-Token": sessionStorage.getItem("mibo-setup-token") || "",
          "X-Mibo-Window": sessionStorage.getItem("mibo-frame") || "" },
        body: JSON.stringify(body),
      });
      const value = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(value.error || "generic");
      return value;
    }

    async function change(what, line = listError, own = false) {
      line.hidden = true;
      try {
        view = own ? await ownPost(what) : await ctx.api("mcp", what);
        render();
        return true;
      } catch (error) {
        kit.failed(line, error, t);
        return false;
      }
    }

    // The market's answer carries both views as they now are.
    function took(value) {
      view = value.view;
      market = value.market;
      render();
      if (shown === "market") renderMarket();
    }

    function said(text) {
      installedNote.textContent = text;
      installedNote.hidden = !text;
    }

    async function adding(button, what) {
      addError.hidden = addDone.hidden = true;
      const label = button.querySelector(".setup-button-label").textContent;
      kit.busy(button, true, t.adding);
      if (await change(what, addError)) {
        addDone.hidden = false;
        paste.value = "";
      }
      kit.busy(button, false, label);
    }

    picker.addEventListener("change", async () => {
      const file = picker.files[0];
      picker.value = "";
      if (!file) return;
      if (file.size > MAX_FILE) return kit.failed(addError, new Error("file_too_large"), t);
      adding(pickButton, { add: await file.text() });
    });

    // ---- One server.
    // A runtime Mibo can fetch, as the page says it: its release, size in MB and source.
    function runtime(row) {
      const r = view.runtimes[row.need];
      return { ...r, size: Math.round(r.size / 1048576) };
    }

    function stateLine(row) {
      if (row.need) {
        const r = runtime(row);
        if (r.state === "fetching") return kit.fill(t.runtimeGetting, r);
        return [t.runtimeErrors[r.error], kit.fill(t.runtimeNeed, r)].filter(Boolean).join(zh ? "" : " ");
      }
      if (row.state === "signin") return [t.signinEnd[row.detail], t.state.signin].filter(Boolean).join(zh ? "" : " ");
      if (row.state !== "failed") return kit.fill(t.state[row.state] || "", { n: row.tools.length });
      const what = row.error === "missing_value" ? row.detail.replace(/MIBO_MCP_[A-Z0-9_]+/g, t.addressKey) : row.command.split(" ")[0];
      return kit.fill(t.errors_state[row.error] || t.errors_state.other, { what });
    }

    function versionLine(row) {
      const meta = el("div", "skm-meta");
      if (row.version) meta.append(el("span", "", kit.fill(t.version, { v: row.version })));
      if (row.unpinned) meta.append(el("span", "", t.unpinned));
      if (row.latest) {
        meta.append(el("span", "skm-badge skm-badge-new", kit.fill(t.updateReady, { v: row.latest })));
        const go = kit.button("setup-button-link", t.update, async () => {
          said("");
          kit.busy(go, true, t.updating);
          try {
            took(await ctx.api("mcp/market", { update: row.name }));
            said(t.updated);
          } catch (error) {
            kit.busy(go, false, t.update);
            kit.failed(listError, error, t);
          }
        });
        meta.append(go);
      }
      return meta.childElementCount ? meta : null;
    }

    function serverRow(row) {
      const box = el("div", "setup-option setup-mcp-server");
      box.dataset.server = row.name;
      box.style.flexDirection = "column";
      box.style.alignItems = "stretch";
      const top = el("div", "setup-option");
      top.style.padding = "0";
      const words = el("div", "setup-option-words");
      const title = el("p", "setup-option-name", row.name);
      const pill = el("span", `setup-pill ${row.state === "connected" ? "setup-pill-up" : row.state === "failed" || row.state === "signin" ? "setup-pill-down" : ""}`);
      pill.append(el("span", "setup-pill-dot"), el("span", "", t.pill[row.state] || row.state));
      pill.style.marginLeft = "8px";
      title.append(pill);
      words.append(title, el("p", "setup-option-text", stateLine(row)));
      const meta = versionLine(row);
      if (meta) words.append(meta);
      const switches = el("div", "setup-option-actions");
      const on = el("input", "setup-switch");
      on.type = "checkbox";
      on.setAttribute("role", "switch");
      on.setAttribute("aria-label", t.enable(row.name));
      on.checked = !row.disabled;
      on.addEventListener("change", () => change({ server: row.name, disabled: !on.checked }));
      switches.append(on, kit.iconButton("setup-word-off", "cross", t.remove(row.name), () => removeServer(row)));
      top.append(words, switches);
      box.append(top);
      // What it runs, or where it is.
      box.append(el("code", "setup-command", row.kind === "program" ? row.command : row.url.replace(HIDDEN, "…")));
      if (row.kind === "program") box.append(el("p", "setup-help", kit.fill(t.folder, { path: row.folder })));
      if (row.cut) box.append(el("p", "setup-help", kit.fill(t.cut, { n: row.cut })));
      if (row.always_start) box.append(el("p", "setup-help", t.alwaysStart));
      // What to do now.
      const line = kit.errorLine();
      const buttons = el("div", "setup-shell-add");
      const add = (cls, text, run) => buttons.append(kit.button(`${cls} setup-button-sm`, text, run));
      if (row.state === "waiting" || row.state === "declined") {
        add("setup-button-primary", row.state === "declined" ? t.allowAgain : t.once, () => change({ start: row.name, answer: "once" }, line, true));
        add("setup-button-secondary", t.always, () => change({ start: row.name, answer: "always" }, line, true));
        if (row.state === "waiting") add("setup-button-ghost", t.no, () => change({ start: row.name, answer: "no" }, line, true));
      }
      if (row.state === "signin") add("setup-button-primary", t.signin, () => change({ signin: row.name, lang: kit.lang }, line, true));
      if (row.state === "signing_in") {
        if (row.signin_url) {
          const where = el("p", "setup-help");
          where.append(link(t.signinOpen, row.signin_url));
          box.append(where);
        }
        add("setup-button-secondary", t.signinCancel, () => change({ signin_cancel: row.name }, line));
      }
      if (row.state === "connected" && row.signed_in) add("setup-button-ghost", t.signout, () => signOut(row, line));
      // A missing npx or uvx: one press downloads Node.js or uv (runtimes.py), and the server goes on by itself.
      if (row.need) {
        if (runtime(row).state !== "fetching")
          add("setup-button-primary", kit.fill(t.runtimeGet, runtime(row)), () => change({ runtime: row.need }, line, true));
      } else if (row.state === "failed") {
        if (row.retry_in) box.append(el("p", "setup-help", kit.fill(t.retryIn, { s: row.retry_in })));
        if (row.detail && row.error !== "missing_value" && row.error !== "not_found") {
          const out = kit.fold(t.output);
          out.body.append(el("pre", "setup-shell-pre", row.detail));
          box.append(out.node);
        }
        add("setup-button-secondary", t.retry, () => change({ retry: row.name }, line));
      }
      if (buttons.childElementCount) box.append(buttons);
      // Saved values: the names only; a new value may be written, never read back.
      if (row.values.length) {
        const fold = kit.fold(t.values);
        fold.node.open = row.error === "missing_value";
        for (const value of row.values) {
          const input = kit.input();
          input.type = "password";
          input.placeholder = t.valuePlaceholder;
          const label = value.kind === "url" ? t.addressKey : value.name;
          input.setAttribute("aria-label", label);
          const save = kit.button("setup-button-secondary setup-button-sm", t.valueSave, () =>
            change({ value: { server: row.name, kind: value.kind, name: value.name, value: input.value } }, line));
          const r = kit.optionRow(label, value.set ? t.valueSet : t.valueMissing);
          const inline = el("div", "setup-shell-add");
          inline.append(input, save);
          r.words.append(inline);
          fold.body.append(r.row);
        }
        box.append(fold.node);
      }
      // Its tools in two groups (Claude's connectors): those marked read-only run without asking, each may be set
      // to never; those that write or delete are set at once to auto review or never, and each also to always,
      // except a tool marked destructive or one that pays, deletes or changes an account (mcp_floor.hard), which
      // asks every time.
      if (row.tools.length) {
        const fold = kit.fold(kit.fill(t.tools, { n: row.tools.length }));
        for (const group of ["read", "write"]) {
          const tools = row.tools.filter((tool) => tool.group === group);
          if (!tools.length) continue;
          const name = group === "read" ? t.groupRead(tools.length) : t.groupWrite(tools.length);
          const head = kit.optionRow(name, group === "read" ? t.groupReadText : t.groupWriteText);
          if (group === "write") {
            const pickGroup = kit.choices(t.modeLabel(name), Object.entries(t.mode).filter(([mode]) => mode !== "always"),
              (mode) => change({ group: { server: row.name, group, mode } }, line));
            pickGroup.set(row.write);
            head.words.append(pickGroup.group);
          }
          fold.body.append(head.row);
          for (const tool of tools) {
            const marks = [tool.hard ? t.hardHint : tool.destructive ? t.destructiveHint : "", tool.changed ? t.changed : ""]
              .filter(Boolean).join(zh ? "；" : "; ");
            const read = group === "read";
            const modes = read ? [["auto", t.modeRead], ["never", t.mode.never]]
              : Object.entries(t.mode).filter(([mode]) => !tool.destructive || mode !== "always");
            const pickMode = kit.choices(t.modeLabel(tool.name), modes, (mode) =>
              change({ tool: { server: row.name, tool: tool.name, mode } }, line));
            pickMode.set(read && tool.mode === "always" ? "auto" : tool.mode);
            const r = kit.optionRow(tool.title && tool.title !== tool.name ? `${tool.title} · ${tool.name}` : tool.name, tool.description);
            if (marks) r.words.append(el("p", "setup-help", marks));
            r.words.append(pickMode.group);
            fold.body.append(r.row);
          }
        }
        box.append(fold.node);
      }
      box.append(line);
      return box;
    }

    function render() {
      countLine.textContent = t.count(view.servers.length);
      updateAll.hidden = !view.updates;
      kit.relabel(updateAll, t.updateAll(view.updates));
      notes.replaceChildren();
      if (view.elevated) notes.append(el("p", "setup-error", t.elevated));
      if (view.bad.length) notes.append(el("p", "setup-error", kit.fill(t.bad, { names: view.bad.join(", ") })));
      // A fold the person opened stays open across a refresh.
      const open = new Set([...list.querySelectorAll("details[open] > summary")].map((s) => s.closest("[data-server]").dataset.server + s.textContent));
      if (!view.servers.length) list.replaceChildren(el("p", "setup-help", t.none));
      else list.replaceChildren(...view.servers.map(serverRow));
      for (const summary of list.querySelectorAll("details > summary"))
        if (open.has(summary.closest("[data-server]").dataset.server + summary.textContent)) summary.parentElement.open = true;
      // While one is starting or about to retry, the page asks again.
      clearTimeout(timer);
      const fetching = Object.values(view.runtimes).some((r) => r.state === "fetching");
      if ((fetching || view.servers.some((row) => row.state === "starting" || row.state === "signing_in" || row.retry_in)) && !node.closest("[hidden]"))
        timer = setTimeout(load, 2000);
    }

    async function load() {
      try {
        view = await ctx.api("mcp");
        listError.hidden = true;
        render();
      } catch (error) {
        kit.failed(listError, error, t);
      }
    }

    // Signing out ends the access at the server first; a server that did not confirm it is said once.
    async function signOut(row, line) {
      if (await change({ signout: row.name }, line, true) && view.revoked === false)
        notes.append(el("p", "setup-help", t.notRevoked));
    }

    async function removeServer(row) {
      const sure = await ctx.confirm({ title: kit.fill(t.removeAsk, { name: row.name }), text: t.removeText, ok: t.removeOk });
      if (sure && await change({ remove: row.name })) market = null;
    }

    async function updateEvery() {
      said("");
      const label = updateAll.querySelector(".setup-button-label").textContent;
      kit.busy(updateAll, true, t.updating);
      try {
        took(await ctx.api("mcp/market", { update_all: true }));
        said(t.updated);
      } catch (error) {
        kit.failed(listError, error, t);
      } finally {
        kit.busy(updateAll, false, label);
        render();
      }
    }

    // ---- Servers other apps keep for this account: read only on the press.
    let found = [];
    const chosen = new Set();
    async function lookElsewhere() {
      importCard.hidden = false;
      importError.hidden = true;
      chosen.clear();
      importList.replaceChildren(el("p", "setup-help", t.importLooking));
      importGo.hidden = true;
      kit.busy(importOpen, true, t.importLooking);
      try {
        found = (await ctx.api("mcp/market", { apps: true })).found;
        renderFound();
      } catch (error) {
        importList.replaceChildren();
        kit.failed(importError, error, t);
      } finally {
        kit.busy(importOpen, false, t.importOpen);
      }
    }
    function renderFound() {
      importGo.hidden = !found.some((row) => row.key && !row.problem && !row.have);
      kit.relabel(importGo, t.importGo(0));
      if (!found.length) return importList.replaceChildren(el("p", "setup-help", t.importNone));
      importList.replaceChildren(...found.map((row, n) => {
        const line = kit.switchRow(`mcp-import-${n}`, row.original || row.app, row.where || row.path, (box) => {
          if (box.checked) chosen.add(row.key);
          else chosen.delete(row.key);
          kit.relabel(importGo, t.importGo(chosen.size));
        });
        // A tick each, not a switch: these are chosen, not turned on.
        line.box.className = "skm-check";
        line.box.removeAttribute("role");
        line.about.classList.add("skm-clamp", "skm-path");
        const facts = [row.app, row.values?.length ? t.importValues(row.values.length) : ""];
        if (row.off) facts.push(t.importOff);
        if (row.taken) facts.push(t.importTaken);
        line.words.append(el("p", "skm-meta", facts.filter(Boolean).join(" · ")));
        const why = row.problem ? t.importProblems[row.problem] || t.importProblems.tools_bad_snippet : row.have ? t.importHave : "";
        if (why) {
          line.box.disabled = true;
          line.words.append(el("p", row.problem ? "setup-error" : "skm-meta", why));
        }
        return line.row;
      }));
    }
    async function importChosen() {
      if (!chosen.size) return;
      importError.hidden = true;
      kit.busy(importGo, true, t.importing);
      try {
        const value = await ctx.api("mcp/market", { import: [...chosen] });
        took(value);
        importCard.hidden = true;
        said(t.addedNames(value.added));
      } catch (error) {
        kit.failed(importError, error, t);
      } finally {
        kit.busy(importGo, false, t.importGo(chosen.size));
      }
    }

    // ================================================================== market

    const controls = el("div", "skm-controls");
    const searchWrap = el("label", "skm-search");
    const search = kit.input("skm-search-input");
    search.type = "search";
    search.placeholder = t.search;
    search.setAttribute("aria-label", t.search);
    searchWrap.append(icon("search", "skm-search-icon"), search);
    const chips = el("div", "skm-chips");
    chips.setAttribute("role", "toolbar");
    const status = el("p", "skm-status");
    controls.append(searchWrap, chips, status);
    const marketError = kit.errorLine();
    const grid = el("div", "skm-grid");
    const registry = el("section", "skm-pane");
    const detail = el("div", "skm-detail");
    detail.hidden = true;
    marketPane.append(controls, marketError, grid, registry, detail);

    let typing = null;
    search.addEventListener("input", () => {
      clearTimeout(typing);
      query.text = search.value.trim();
      renderGrid();
      // The registry is asked once the typing stops.
      typing = setTimeout(searchRegistry, 450);
    });

    async function loadMarket() {
      marketError.hidden = true;
      try {
        market = await ctx.api("mcp/market");
        renderMarket();
      } catch (error) {
        kit.failed(marketError, error, t);
      }
    }

    function renderMarket() {
      if (detailOf) return renderDetail(market.servers.find((one) => one.id === detailOf.id) || detailOf);
      renderChips();
      renderGrid();
    }

    function renderChips() {
      // The categories skills use too, named in the locales.
      const names = kit.words("setup_skills").categories;
      const used = new Set(market.servers.map((one) => one.category));
      const keys = ["", ...Object.keys(market.categories || {}).filter((key) => used.has(key))];
      chips.replaceChildren(...keys.map((key) => {
        const chip = el("button", "skm-chip", key ? names[key] : t.allCategories);
        chip.type = "button";
        chip.setAttribute("aria-pressed", String(query.category === key));
        chip.addEventListener("click", () => {
          query.category = key;
          renderChips();
          renderGrid();
        });
        return chip;
      }));
    }

    // An entry fits when every word typed is in its names, uses, tags or publisher; a Chinese word not there
    // whole fits by any two characters of it ("查询地图" finds 地图).
    function fits(one, words) {
      const text = [one.name, one.id, one.title.zh, one.title.en, one.about.zh, one.about.en, one.publisher, ...one.tags]
        .join(" ").toLowerCase();
      return words.every((word) => text.includes(word)
        || (/[㐀-鿿]/.test(word) && [...word].some((_, i) => i + 1 < word.length && text.includes(word.slice(i, i + 2)))));
    }

    function listed() {
      const words = query.text.toLowerCase().split(/\s+/).filter(Boolean);
      return market.servers.filter((one) => (!query.category || one.category === query.category) && fits(one, words));
    }

    function badges(one) {
      const row = el("div", "skm-badges");
      const way = one.ways[0];
      if (one.sync) row.append(el("span", "skm-badge", t.badgeSync));
      else if (way) row.append(el("span", "skm-badge", way.kind === "remote" ? t.badgeRemote : t.badgeLocal));
      if (way?.signin) row.append(el("span", "skm-badge", t.badgeSignin));
      if (one.sync || way?.inputs.some((row) => row.secret && row.required)) row.append(el("span", "skm-badge", t.badgeKey));
      return row;
    }

    const publisherMark = (one, size) => kit.publisherMark(one.owner, "plug", size);

    function installedMark() {
      const done = el("span", "skm-installed");
      done.append(icon("check", "skm-installed-icon"), el("span", "", t.installed));
      return done;
    }

    function cardOf(one) {
      const card = kit.pressable(el("article", "skm-card"), both(one.title), () => openDetail(one));
      const top = el("div", "skm-card-top");
      const names = el("div", "skm-card-names");
      names.append(el("h4", "skm-card-title", both(one.title)), el("p", "skm-card-by", one.publisher));
      top.append(publisherMark(one, "sm"), names);
      const foot = el("div", "skm-card-foot");
      foot.append(badges(one));
      if (one.installed) foot.append(installedMark());
      card.append(top, el("p", "skm-card-about", both(one.about)), foot);
      return card;
    }

    function renderGrid() {
      detail.hidden = true;
      controls.hidden = grid.hidden = registry.hidden = false;
      const rows = listed();
      status.textContent = query.text ? "" : t.shippedLine(market.servers.length);
      if (!rows.length) {
        const empty = el("div", "skm-empty");
        empty.append(el("p", "", query.text ? kit.fill(t.noMatch, { q: query.text }) : t.noMatchCategory));
        if (query.text) {
          empty.append(kit.button("setup-button-link", t.clear, () => {
            search.value = query.text = "";
            renderGrid();
            searchRegistry();
          }));
        }
        return grid.replaceChildren(empty);
      }
      grid.replaceChildren(...rows.map(cardOf));
    }

    // Beyond the chosen list: the official registry, by name, for a Latin word of three letters or more (its least).
    let asked = "";
    async function searchRegistry() {
      const q = query.text;
      asked = q;
      if (q.trim().length < 3 || !/^[\x20-\x7e]+$/.test(q)) return registry.replaceChildren();
      registry.replaceChildren(el("h4", "skm-card-title", t.registryTitle), el("p", "setup-help", t.registryLoading));
      try {
        const rows = (await ctx.api(`mcp/market/search?q=${encodeURIComponent(q)}`)).servers;
        if (asked !== q) return;
        const box = el("div", "skm-grid");
        box.append(...rows.map(cardOf));
        registry.replaceChildren(el("h4", "skm-card-title", t.registryTitle),
          el("p", "setup-help", rows.length ? t.registryNote : kit.fill(t.registryNone, { q })), ...(rows.length ? [box] : []));
      } catch (error) {
        if (asked !== q) return;
        const line = kit.errorLine();
        kit.failed(line, error, t);
        registry.replaceChildren(el("h4", "skm-card-title", t.registryTitle), line);
      }
    }

    // ---- One entry, in full, with its form.
    function openDetail(one) {
      detailOf = one;
      renderDetail(one);
      node.closest(".setup-page")?.parentElement?.scrollTo({ top: 0 });
    }
    function closeDetail() {
      detailOf = null;
      renderGrid();
    }

    let wayAt = 0;
    function renderDetail(one) {
      controls.hidden = grid.hidden = registry.hidden = true;
      marketError.hidden = true;
      detail.hidden = false;
      if (wayAt >= one.ways.length) wayAt = 0;
      const back = el("button", "skm-back");
      back.type = "button";
      back.append(icon("back", "skm-back-icon"), el("span", "", t.back));
      back.addEventListener("click", closeDetail);

      const top = el("div", "skm-detail-top");
      const names = el("div", "skm-detail-names");
      names.append(el("h3", "skm-detail-title", both(one.title)));
      const by = el("p", "skm-detail-by");
      by.append(el("span", "", one.publisher), el("span", "", one.id));
      names.append(by);
      const act = el("div", "skm-detail-act");
      if (one.installed) act.append(installedMark());
      top.append(publisherMark(one, "lg"), names, act);

      const lead = el("div", "skm-detail-lead");
      if (!one.reviewed) lead.append(el("p", "skm-reason", t.registryNote));
      lead.append(el("p", "skm-detail-about", both(one.about)));

      const parts = [back, top, lead];
      if (one.sync) parts.push(...syncForm(one));
      else parts.push(...installForm(one));
      detail.replaceChildren(...parts);
    }

    function installForm(one) {
      const way = one.ways[wayAt];
      const dl = el("dl", "skm-facts");
      if (one.ways.length > 1) {
        const pickWay = kit.choices(t.way, one.ways.map((w, i) => [String(i), t.ways[w.kind]]), (value) => {
          wayAt = Number(value);
          renderDetail(one);
        });
        pickWay.set(String(wayAt));
        fact(dl, t.way, pickWay.group);
      } else {
        fact(dl, t.way, t.ways[way.kind]);
      }
      fact(dl, t.runs, el("code", "setup-command", way.where));
      const needs = [way.signin ? t.needsSignin : "", way.needs === "node" ? t.needsNode : way.needs === "uv" ? t.needsUv : "",
        way.inputs.some((row) => row.secret && row.required) ? t.needsKey : ""].filter(Boolean);
      fact(dl, t.needs, needs.length ? needs.join(zh ? "；" : "; ") : t.needsNothing);
      if (one.repo) fact(dl, t.source, link(one.repo.replace(/^https:\/\//, ""), one.repo));
      if (one.licence) fact(dl, t.licence, one.licence);
      const note = el("p", "setup-help", way.kind === "remote" ? t.remoteNote : t.localNote);

      // The form: one field per value the way asks for; secrets are typed and never shown again.
      const form = el("div", "skm-pane");
      const fields = way.inputs.map((row) => {
        const input = kit.input();
        if (row.secret) input.type = "password";
        if (row.default) input.placeholder = row.default;
        const help = [];
        const words = both(row.label);
        if (words && words !== row.name) help.push(el("span", "", words + " "));
        if (row.secret && one.get_key) help.push(link(t.getKey, one.get_key));
        const need = row.required ? t.required : t.optional;
        const field = kit.field(zh ? `${row.name}（${need}）` : `${row.name} (${need})`, input);
        if (help.length) field.help(help);
        return { row, field };
      });
      if (fields.length) {
        form.append(el("h4", "skm-card-title", t.form), ...fields.map((f) => f.field.wrap));
        if (way.inputs.some((row) => row.secret)) form.append(el("p", "setup-help", t.secretSaved));
      }
      const error = kit.errorLine();
      const go = kit.button("setup-button-primary", t.install, async () => {
        const values = {};
        for (const { row, field } of fields) {
          field.error("");
          values[row.id] = field.control.value;
          if (row.required && !field.control.value.trim()) field.error(t.errors.tools_required);
        }
        if (fields.some(({ row, field }) => row.required && !field.control.value.trim())) return;
        error.hidden = true;
        kit.busy(go, true, t.installing);
        try {
          const value = await ctx.api("mcp/market", { install: one.id, way: wayAt, values });
          detailOf = null;
          took(value);
          switchTo("installed");
          said(kit.fill(t.installedDone, { name: value.added[0] }));
        } catch (failure) {
          kit.busy(go, false, t.install);
          kit.failed(error, failure, t);
        }
      });
      const row = el("div", "skm-row");
      row.append(go);
      form.append(note, row, error);
      return [dl, form];
    }

    // ModelScope: its access token, and the services turned on there brought in.
    function syncForm(one) {
      const form = el("div", "skm-pane");
      const input = kit.input();
      input.type = "password";
      const help = [el("span", "", (market.synced ? t.syncSaved : "") + " ")];
      if (one.get_key) help.push(link(t.getKey, one.get_key));
      const field = kit.field(t.syncToken, input, help);
      const error = kit.errorLine();
      const done = el("p", "setup-help");
      done.hidden = true;
      const go = kit.button("setup-button-primary", t.syncGo, async () => {
        error.hidden = done.hidden = true;
        kit.busy(go, true, t.syncing);
        try {
          const value = await ctx.api("mcp/market", { modelscope: input.value });
          input.value = "";
          view = value.view;
          market = value.market;
          done.textContent = value.added.length ? t.synced(value.added.length) : t.syncNone;
          done.hidden = false;
        } catch (failure) {
          kit.failed(error, failure, t);
        } finally {
          kit.busy(go, false, t.syncGo);
        }
      });
      const row = el("div", "skm-row");
      row.append(go);
      form.append(el("h4", "skm-card-title", t.syncTitle), el("p", "setup-help", t.syncText), field.wrap,
        el("p", "setup-help", t.secretSaved), el("p", "setup-help", t.remoteNote), row, error, done);
      return [form];
    }

    // ---- The record.
    function saidRow(row) {
      const what = row.tool ? `${row.server} · ${row.tool}` : row.server;
      const how = row.how && t.how[row.how] ? ` (${t.how[row.how]})` : "";
      return `${t.outcome[row.outcome] || row.outcome}${how} · ${what}`;
    }

    async function loadLog() {
      try {
        const rows = (await ctx.api("mcp/log?n=60")).rows;
        record.summary.lastChild.textContent = t.logFold(rows.length);
        logError.hidden = true;
        clear.hidden = !rows.length;
        if (!rows.length) return logList.replaceChildren(el("p", "setup-help", t.logNone));
        logList.replaceChildren(...rows.map((row) => {
          const item = el("div", "setup-shell-entry");
          const at = row.at ? new Date(row.at * 1000).toLocaleString(zh ? "zh-CN" : "en") : "";
          item.append(el("p", "setup-option-name", saidRow(row)), el("p", "setup-help", at));
          if (row.args || row.out) {
            const more = kit.fold(t.output);
            more.body.append(el("pre", "setup-shell-pre", [row.args, row.out].filter(Boolean).join("\n\n")));
            item.append(more.node);
          }
          return item;
        }));
      } catch (error) {
        kit.failed(logError, error, t);
      }
    }

    async function clearLog() {
      const sure = await ctx.confirm({ title: t.logClearAsk, text: t.logClearText, ok: t.logClear });
      if (!sure) return;
      try {
        await ctx.api("mcp/log", { clear: true });
        loadLog();
      } catch (error) {
        kit.failed(logError, error, t);
      }
    }

    // ================================================================= views

    function switchTo(value) {
      shown = value;
      tabs.set(value);
      installedPane.hidden = value !== "installed";
      marketPane.hidden = value !== "market";
      if (value === "market" && !market) loadMarket();
      else if (value === "market") renderMarket();
    }

    // `place`: "market" or "market/<entry id>", as a link into this section names it.
    async function show(asked, place = "") {
      const [where, ...rest] = String(place || "").split("/");
      if (where === "market") {
        detailOf = null;
        if (!market) await loadMarket().catch(() => null);
        const one = market?.servers.find((entry) => entry.id === rest.join("/"));
        switchTo("market");
        if (one) openDetail(one);
      } else {
        switchTo(shown);
      }
      load();
      if (record.node.open) loadLog();
    }

    return { node, show };
  });
})();
