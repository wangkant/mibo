"use strict";
// Settings › Files and commands: whether the character may do things on this computer by command (/api/shell
// {on}), the folders it may use (/api/shell {add} / {remove}), what is never run, and the record of every
// command (/api/shell/log). Everything about a command is decided by the app (persona_agent/shell), not the model.
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
    main.append(sw.row);

    // ---- The folders.
    const folders = kit.card(t.foldersTitle);
    const foldersText = el("p", "setup-help", t.foldersText);
    const list = el("div", "setup-shell-folders");
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

    // ---- Never run, and the record.
    const never = kit.fold(t.neverFold);
    const record = kit.fold(paI18n.t("setup_shell.logFold", { count: 0 }));
    const logList = el("div", "setup-shell-log");
    const clear = kit.button("setup-button-secondary setup-button-sm", t.logClear, clearLog);
    const logError = kit.errorLine();
    record.body.append(logList, clear, logError);
    record.node.addEventListener("toggle", () => {
      if (record.node.open) loadLog();
    });
    node.append(main, folders, never.node, record.node);

    function render() {
      sw.box.checked = view.on;
      sw.box.disabled = false;
      elevated.hidden = !view.elevated;
      folders.hidden = never.node.hidden = record.node.hidden = false;
      if (!view.folders.length) list.replaceChildren(el("p", "setup-help", t.foldersNone));
      else {
        list.replaceChildren(...view.folders.map((row) => {
          const chip = el("span", "setup-word");
          chip.title = row.path;
          const name = zh ? row.zh : row.en;
          chip.append(el("span", "", `${name}${row.read_only ? `  ·  ${t.readOnly}` : ""}  ·  ${row.path}`));
          if (row.read_only) chip.append(kit.button("setup-button-secondary setup-button-sm", t.sortToo, () => change({ add: row.path })));
          chip.append(kit.iconButton("setup-word-off", "cross", paI18n.t("setup_shell.remove", { name }), () => change({ remove: row.path })));
          return chip;
        }));
      }
      never.body.replaceChildren(el("p", "setup-help", t.neverText),
        (() => {
          const items = el("ul", "setup-shell-never");
          for (const row of view.never) items.append(el("li", "", zh ? row.zh : row.en));
          return items;
        })());
    }

    async function load() {
      try {
        view = await ctx.api("shell");
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
      try {
        view = await ctx.api(path, what ?? {});
        if (what?.add) input.value = "";
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
          const outcome = (t.outcomes[row.outcome] || row.outcome || "") + (row.outcome === "ran" ? paI18n.t("setup_shell.code", { count: row.code }) : "");
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

    folders.hidden = never.node.hidden = record.node.hidden = true;

    function show() {
      load();
      if (record.node.open) loadLog();
    }

    return { node, show };
  });
})();
