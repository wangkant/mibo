"use strict";
// Settings › Other programs: whether the character may operate other programs' windows on this computer
// (/api/programs {on}) and how much it does there by itself ({mode}: read only or automatic review), the programs granted
// always with each one's tier ({tier}, {revoke}), what is never operated with the person's own words ({block},
// {unblock}), and the record of what was done in which program (/api/programs/log). Everything about it is
// decided by the app (mibo/desk, mibo/acting.py), not the model.
(() => {

  // Windows only: elsewhere the section is not there (mibo/desk is Windows UI Automation).
  if (!/Windows/.test(navigator.userAgent)) return;
  window.paSetup.part("programs", (kit) => {
    const { el } = kit;
    const t = kit.words("setup_programs");
    const ctx = kit.ctx;
    const zh = kit.lang === "zh";
    const node = kit.section("programs", t.hint);
    let view = null;

    // ---- The switch, and the sentence on what it means.
    const main = kit.card();
    main.classList.add("setup-options");
    const sw = kit.switchRow("programs-on", "", "", (box) => setOn(box.checked));
    const onError = kit.errorLine();
    sw.about.after(onError);
    sw.box.disabled = true;
    // ---- Pictures of a window only a picture can work: sent with no question while on; off, the chat asks first.
    const pic = kit.switchRow("programs-pictures", t.pictures, "", (box) => setPictures(box.checked));
    pic.box.disabled = true;
    // ---- How much it does by itself once on.
    const modeSelect = el("select", "setup-input setup-select setup-input-sm");
    for (const value of ["read", "auto"]) modeSelect.append(new Option(t.modes[value], value));
    modeSelect.disabled = true;
    modeSelect.addEventListener("change", () => change({ mode: modeSelect.value }, onError));
    const modeRow = kit.optionRow(t.modeName, t.modeText, modeSelect);
    main.append(sw.row, kit.item("programs-mode", modeRow.row), pic.row);

    // ---- The programs granted always.
    const granted = kit.item("grants", kit.card(t.grantsTitle));
    const list = el("div", "setup-options");
    const grantError = kit.errorLine();
    granted.append(el("p", "setup-help", t.grantsText), list, grantError);

    // ---- Never operated, and the record.
    const never = kit.fold(t.neverFold);
    kit.item("never", never.node);
    const blockInput = kit.input("setup-input-sm");
    blockInput.placeholder = t.blockHint;
    blockInput.setAttribute("aria-label", t.blockHint);
    const blockError = kit.errorLine();
    const blockAdd = kit.button("setup-button-secondary setup-button-sm", t.blockAdd, () => {
      const word = blockInput.value.trim();
      if (word) change({ block: word }, blockError).then(() => { blockInput.value = ""; });
    });
    const blockList = el("div", "setup-options");
    const record = kit.fold(paI18n.t("setup_programs.logFold", { count: 0 }));
    kit.item("record", record.node);
    const logList = el("div", "setup-shell-log");
    const clear = kit.button("setup-button-secondary setup-button-sm", t.logClear, clearLog);
    const logError = kit.errorLine();
    record.body.append(logList, clear, logError);
    record.node.addEventListener("toggle", () => {
      if (record.node.open) loadLog();
    });
    node.append(main, granted, never.node, record.node);

    function render() {
      const words = view.switch[zh ? "zh" : "en"];
      sw.row.querySelector(".setup-option-name").textContent = words.label;
      sw.about.textContent = words.sentence;
      sw.about.hidden = false;
      sw.box.checked = view.on;
      sw.box.disabled = false;
      pic.about.textContent = view.pictures.sentence[zh ? "zh" : "en"];
      pic.about.hidden = false;
      pic.box.checked = view.pictures.on;
      pic.box.disabled = !view.on;
      modeSelect.value = view.mode === "off" ? "auto" : view.mode;
      modeSelect.disabled = !view.on;
      granted.hidden = never.node.hidden = record.node.hidden = false;
      if (!view.grants.length) list.replaceChildren(el("p", "setup-help", t.grantsNone));
      else {
        list.replaceChildren(...view.grants.map((row) => {
          const controls = el("div", "setup-programs-controls");
          const tier = el("select", "setup-input setup-select setup-input-sm");
          for (const value of ["full", "click", "view"]) tier.append(new Option(t.tiers[value], value));
          tier.value = row.tier;
          tier.setAttribute("aria-label", paI18n.t("setup_programs.tierOf", { name: row.name }));
          tier.addEventListener("change", () => change({ tier: { key: row.key, tier: tier.value } }));
          controls.append(tier,
            kit.iconButton("setup-word-off", "cross", paI18n.t("setup_programs.revoke", { name: row.name }), () => change({ revoke: row.key })));
          const line = kit.optionRow(row.name, `${row.exe}${row.since ? ` · ${paI18n.t("setup_programs.since", { s: row.since })}` : ""}`, controls);
          line.about.title = row.exe;
          return line.row;
        }));
      }
      const items = el("ul", "setup-shell-never");
      for (const row of view.never) items.append(el("li", "", zh ? row.zh : row.en));
      blockList.replaceChildren(...view.block.map((word) => kit.optionRow(word, "",
        kit.iconButton("setup-word-off", "cross", paI18n.t("setup_programs.unblock", { word }),
          () => change({ unblock: word }, blockError))).row));
      const adding = el("div", "setup-programs-controls");
      adding.append(blockInput, blockAdd);
      never.body.replaceChildren(el("p", "setup-help", t.neverText), items, el("p", "setup-help", t.blockText),
        blockList, adding, blockError);
    }

    async function load() {
      try {
        view = await ctx.api("programs");
        onError.hidden = true;
        render();
      } catch (error) {
        kit.failed(onError, error, t);
      }
    }

    async function setOn(on) {
      if (on) {
        sw.box.checked = false;
        const words = view.switch[zh ? "zh" : "en"];
        const sure = await ctx.confirm({ title: t.onAsk, text: words.sentence, ok: t.onYes });
        if (!sure) return;
      }
      await change({ on }, onError);
    }

    async function setPictures(on) {
      if (on) {
        pic.box.checked = false;
        const sure = await ctx.confirm({ title: t.picturesAsk, text: view.pictures.sentence[zh ? "zh" : "en"], ok: t.onYes });
        if (!sure) return;
      }
      await change({ pictures: on }, onError);
    }

    async function change(what, line = grantError) {
      line.hidden = true;
      sw.box.disabled = true;
      try {
        view = await ctx.api("programs", what);
        render();
      } catch (error) {
        kit.failed(line, error, t);
        sw.box.disabled = false;
        if (view) sw.box.checked = view.on;
      }
    }

    function said(row) {
      if (row.do === "switch") return t.switchLine[row.line] || row.line || "";
      const does = t.does[row.do] || row.do || "";
      const target = row.target ? ` ${row.target}` : "";
      const kind = row.kind ? ` · ${t.kinds[row.kind] || row.kind}` : "";
      const status = row.status ? ` · ${t.statuses[row.status] || row.status}` : "";
      return `${does}${target}${kind}${status}`;
    }

    async function loadLog() {
      try {
        const rows = (await ctx.api("programs/log?n=60")).rows;
        record.summary.lastChild.textContent = paI18n.t("setup_programs.logFold", { count: rows.length });
        logError.hidden = true;
        clear.hidden = !rows.length;
        if (!rows.length) return logList.replaceChildren(el("p", "setup-help", t.logNone));
        logList.replaceChildren(...rows.map((row) => {
          const item = el("div", "setup-shell-entry");
          const where = [row.program, row.window].filter(Boolean).join(" · ");
          item.append(el("p", "setup-option-name", said(row)),
            el("p", "setup-help", [row.t, where].filter(Boolean).join(" · ")));
          if (row.text) {
            const more = kit.fold(t.typed);
            more.body.append(el("pre", "setup-shell-pre", row.text));
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
        await ctx.api("programs/log", { clear: true });
        loadLog();
      } catch (error) {
        kit.failed(logError, error, t);
      }
    }

    granted.hidden = never.node.hidden = record.node.hidden = true;

    function show() {
      load();
      if (record.node.open) loadLog();
    }

    return { node, show };
  });
})();
