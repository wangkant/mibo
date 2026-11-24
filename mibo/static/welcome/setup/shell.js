"use strict";
// Settings › Files and commands: whether the character may do things on this computer by command (/api/shell
// {on}) and how much by itself ({mode}), the folders it may use (/api/shell {add} / {remove}), the programs always
// allowed in a folder ({forget}), what is never run, and the record of every command (/api/shell/log). Everything
// about a command is decided by the app (mibo/shell, mibo/acting.py), not the model.
(() => {

  window.paSetup.part("shell", (kit) => {
    const { el } = kit;
    const t = kit.words("setup_shell");
    const ctx = kit.ctx;
    const zh = kit.lang === "zh";
    const node = kit.section("shell", t.hint);
    let view = null;

    // ---- The switch.
    const main = kit.card();
    main.classList.add("setup-options");
    const sw = kit.switchRow("shell-on", t.onTitle, t.onText, (box) => setOn(box.checked));
    const elevated = el("p", "setup-error", t.elevated);
    elevated.hidden = true;
    const onError = kit.errorLine();
    sw.about.after(elevated, onError);
    sw.box.disabled = true;
    // How much it does by itself ({mode}, acting.py): read only, or automatic review (read-only commands and changes
    // in the granted folders without a card, each turn's checkpoint able to put them back; the reviewer looks at the rest).
    const modeSelect = el("select", "setup-input setup-select setup-input-sm");
    for (const value of ["read", "auto"]) modeSelect.append(new Option(t.modes[value], value));
    modeSelect.disabled = true;
    modeSelect.addEventListener("change", () => change({ mode: modeSelect.value }, onError));
    const modeRow = kit.optionRow(t.modeName, t.modeText, modeSelect);
    main.append(sw.row, kit.item("shell-mode", modeRow.row));

    // ---- The folders.
    const folders = kit.item("folders", kit.card(t.foldersTitle));
    const foldersText = el("p", "setup-help", t.foldersText);
    const list = el("div", "setup-shell-list");
    const input = kit.input();
    input.placeholder = t.addPlaceholder;
    const add = kit.button("setup-button-secondary setup-button-sm", t.add, () => addFolder(input.value));
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter") addFolder(input.value);
    });
    const addRow = el("div", "setup-shell-add");
    addRow.append(input, add);
    // In the app window: the system's own folder dialog (pywebview), and the folder picked is granted.
    if (ctx.told) addRow.prepend(kit.button("setup-button-secondary setup-button-sm", t.pick, () => change(null, folderError, "shell/pick")));
    const folderError = kit.errorLine();
    folders.append(foldersText, list, addRow, folderError);

    // ---- The programs always allowed in a folder, from the card's 对此程序在此文件夹始终允许 ({forget} takes one back).
    const rules = kit.item("rules", kit.card(t.rulesTitle));
    const rulesList = el("div", "setup-shell-list");
    rules.append(el("p", "setup-help", t.rulesText), rulesList);

    // ---- Windows' limits (Windows only, view.limits): the guards placed on places outside the app's home
    // (shell/guards.py), taken out with {guards: false} and placed again with {guards: true}, and the optional
    // hardening set up once through the system's administrator prompt ({hardening}, shell/netguard.py).
    const limits = kit.item("limits", kit.card(t.limitsTitle));
    const guardsRow = kit.optionRow(t.guardsName, t.guardsText, null);
    const guardsBox = el("input", "setup-switch");
    guardsBox.type = "checkbox";
    guardsBox.setAttribute("role", "switch");
    guardsBox.setAttribute("aria-label", t.guardsName);
    guardsBox.addEventListener("change", () => setGuards(guardsBox.checked));
    guardsRow.row.append(guardsBox);
    const placesFold = kit.fold(t.placesFold);
    const hardRow = kit.optionRow(t.hardeningName, t.hardeningText, null);
    const hardBox = el("input", "setup-switch");
    hardBox.type = "checkbox";
    hardBox.setAttribute("role", "switch");
    hardBox.setAttribute("aria-label", t.hardeningName);
    hardBox.addEventListener("change", () => setHardening(hardBox.checked));
    hardRow.row.append(hardBox);
    const limitsError = kit.errorLine();
    limits.append(el("p", "setup-help", t.limitsText), guardsRow.row, placesFold.node, hardRow.row, limitsError);

    // ---- Never run, and the record.
    const never = kit.fold(t.neverFold);
    const record = kit.fold(paI18n.t("setup_shell.logFold", { count: 0 }));
    kit.item("record", record.node);
    const logList = el("div", "setup-shell-log");
    const clear = kit.button("setup-button-secondary setup-button-sm", t.logClear, clearLog);
    const logError = kit.errorLine();
    record.body.append(logList, clear, logError);
    record.node.addEventListener("toggle", () => {
      if (record.node.open) loadLog();
    });
    node.append(main, folders, rules, limits, never.node, record.node);

    // A row of a list: a name with its line under it (cut short, the whole in the tooltip), what is set for it, and the way to take it out.
    function row(name, line, tip, control, label, removal) {
      const item = el("div", "setup-shell-row");
      const words = el("div", "setup-option-words");
      words.append(el("p", "setup-option-name", name), el("p", "setup-option-text", line));
      words.title = tip;
      const end = el("div", "setup-shell-row-end");
      if (control) end.append(control);
      end.append(kit.iconButton("setup-word-off", "cross", label, () => change(removal)));
      item.append(words, end);
      return item;
    }

    function render() {
      sw.box.checked = view.on;
      sw.box.disabled = false;
      modeSelect.value = view.mode === "off" ? "auto" : view.mode;
      modeSelect.disabled = !view.on;
      elevated.hidden = !view.elevated;
      folders.hidden = never.node.hidden = record.node.hidden = false;
      rules.hidden = !view.rules.length;
      rulesList.replaceChildren(...view.rules.map((rule) => {
        const where = zh ? rule.zh : rule.en;
        return row(rule.shown, where, rule.program, null,
          paI18n.t("setup_shell.ruleRemove", { name: rule.shown, folder: where }), { forget: { program: rule.program, folder: rule.folder } });
      }));
      if (!view.folders.length) list.replaceChildren(el("p", "setup-help", t.foldersNone));
      else {
        list.replaceChildren(...view.folders.map((folder) => {
          const name = zh ? folder.zh : folder.en;
          // What it may do there: look only, or sort too ({add} grants with write, {read_only} sets it back).
          const access = el("select", "setup-input setup-select setup-input-sm");
          access.setAttribute("aria-label", name);
          access.append(new Option(t.readOnly, "read"), new Option(t.sortToo, "sort"));
          access.value = folder.read_only ? "read" : "sort";
          access.addEventListener("change", () => change(access.value === "read" ? { add: folder.path, read_only: true } : { add: folder.path }));
          return row(name, folder.path, folder.path, access, paI18n.t("setup_shell.remove", { name }), { remove: folder.path });
        }));
      }
      renderLimits();
      never.body.replaceChildren(el("p", "setup-help", t.neverText),
        (() => {
          const items = el("ul", "setup-shell-never");
          for (const row of view.never) items.append(el("li", "", zh ? row.zh : row.en));
          return items;
        })());
    }

    // Each guarded place: why, and its path; one that could not be guarded says so.
    function renderLimits() {
      const kept = view.limits;
      limits.hidden = !kept;
      if (!kept) return;
      guardsBox.checked = kept.guards;
      guardsBox.disabled = hardBox.disabled = false;
      hardBox.checked = kept.hardening.on;
      const failed = new Set(kept.failed);
      placesFold.summary.lastChild.textContent = paI18n.t("setup_shell.placesFold", { count: kept.places.length });
      placesFold.node.hidden = !kept.guards;
      placesFold.body.replaceChildren(...kept.places.map((place) => {
        const item = el("div", "setup-shell-row");
        const words = el("div", "setup-option-words");
        words.append(el("p", "setup-option-name", t.why[place.why] || place.why),
          el("p", "setup-option-text", failed.has(place.path) ? paI18n.t("setup_shell.placeFailed", { path: place.path }) : place.path));
        words.title = place.path;
        item.append(words);
        return item;
      }));
      if (kept.hardening.error) {
        limitsError.textContent = t.errors.hardening_failed;
        limitsError.hidden = false;
      }
    }

    async function setGuards(on) {
      if (!on) {
        guardsBox.checked = true;
        const sure = await ctx.confirm({ title: t.guardsOffAsk, text: t.guardsOffText, ok: t.guardsOff });
        if (!sure) return;
        guardsBox.checked = false;
      }
      guardsBox.disabled = true;
      await change({ guards: on }, limitsError);
      if (view) renderLimits();
    }

    async function setHardening(on) {
      hardBox.checked = !on;
      const sure = await ctx.confirm({ title: on ? t.hardeningOnAsk : t.hardeningOffAsk,
        text: on ? t.hardeningOnText : t.hardeningOffText, ok: on ? t.hardeningOn : t.hardeningOff });
      if (!sure) return;
      hardBox.disabled = true;
      await change({ hardening: on }, limitsError);
      if (view) renderLimits();
    }

    // An answer is drawn only while it is the latest asked for: one that comes back late is not drawn over a newer one.
    let asked = 0;

    async function load() {
      const mine = ++asked;
      try {
        const got = await ctx.api("shell");
        if (mine !== asked) return;
        view = got;
        onError.hidden = true;
        render();
      } catch (error) {
        kit.failed(onError, error, t);
      }
    }

    async function setOn(on) {
      if (on) {
        sw.box.checked = false;
        const sure = await ctx.confirm({ title: t.onAsk, text: t.onAskText, ok: t.onYes });
        if (!sure) return;
      }
      await change({ on }, onError);
    }

    // `path` "shell/pick": the folder dialog in place of a change sent.
    async function change(what, line = folderError, path = "shell") {
      line.hidden = true;
      sw.box.disabled = true;
      const mine = ++asked;
      try {
        const got = await ctx.api(path, what ?? {});
        if (mine !== asked) return;
        view = got;
        if (what?.add === input.value.trim()) input.value = "";
        render();
      } catch (error) {
        kit.failed(line, error, t);
        sw.box.disabled = false;
        if (view) sw.box.checked = view.on;
      }
    }

    function addFolder(text) {
      if (text.trim()) change({ add: text.trim() });
    }

    function when(seconds) {
      return new Date(seconds * 1000).toLocaleString(paI18n.locale, { month: "numeric", day: "numeric",
        hour: "2-digit", minute: "2-digit" });
    }

    async function loadLog() {
      try {
        const rows = (await ctx.api("shell/log?n=40")).rows;
        record.summary.lastChild.textContent = paI18n.t("setup_shell.logFold", { count: rows.length });
        logError.hidden = true;
        clear.hidden = !rows.length;
        if (!rows.length) return logList.replaceChildren(el("p", "setup-help", t.logNone));
        logList.replaceChildren(...rows.map((row) => {
          const item = el("div", "setup-shell-entry");
          const said = (row.said && (zh ? row.said.zh : row.said.en)) || row.granted || row.command || "";
          const outcome = (t.outcomes[row.outcome] || row.outcome || "") + (row.outcome === "ran" ? paI18n.t("setup_shell.code", { count: row.code }) : "")
            + (t.hows[row.how] ? ` · ${t.hows[row.how]}` : "");
          item.append(el("p", "setup-option-name", said), el("p", "setup-help", `${when(row.at)} · ${outcome}`));
          if (row.command) {
            const more = kit.fold(t.command);
            more.body.append(el("pre", "setup-shell-pre", row.command));
            if (row.out) more.body.append(el("p", "setup-help", t.result), el("pre", "setup-shell-pre", row.out));
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
        await ctx.api("shell/log", { clear: true });
        loadLog();
      } catch (error) {
        kit.failed(logError, error, t);
      }
    }

    folders.hidden = rules.hidden = limits.hidden = never.node.hidden = record.node.hidden = true;

    function show() {
      load();
      if (record.node.open) loadLog();
    }

    return { node, show };
  });
})();
