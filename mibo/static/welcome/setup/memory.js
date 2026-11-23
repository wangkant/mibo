"use strict";
// Settings › Memory: what the character keeps about the one person (person.json). Two switches (use and update
// memory; keep health details), an add field, the items by kind with the day each was kept, the chat lines it came
// from, rewrite and forget, what can be brought back, export as JSON or Markdown, another assistant's list pasted
// and kept item by item once ticked, and forget all (GET /api/person, POST /api/person/<action>,
// GET /api/person/said/<id>, /api/person/export).
(() => {
  // A fact's kind to its group, as person.py's listing heads them; plans are group 4.
  const GROUP = { who: 0, people: 0, health: 0, like: 1, dislike: 2, life: 3, other: 3, manner: 5, form: 5 };
  const PLANS = 4;
  // An item takes at most what the store keeps of one (person.TEXT_MAX); a pasted list what the page reads.
  const TEXT_MAX = 60;
  const PASTE_MAX = 8000;

  window.paSetup.part("memory", (kit) => {
    const { el } = kit;
    const t = kit.words("setup_memory");
    const ctx = kit.ctx;
    const mem = { view: null, busy: false, editing: "", open: "", said: {}, pasted: null };
    const node = kit.section("memory");
    const error = kit.errorLine();

    // ---- The two switches.
    const switches = kit.card();
    switches.classList.add("setup-options");
    const use = kit.switchRow("memory-on", t.onTitle, t.onText, (box) => write("settings", { on: box.checked }));
    const health = kit.switchRow("memory-health", t.healthTitle, t.healthText, (box) => write("settings", { health: box.checked }));
    switches.append(use.row, health.row);

    // ---- Add one.
    const adding = kit.card();
    adding.classList.add("setup-memory-add");
    const addField = kit.input("setup-memory-input");
    addField.placeholder = t.addPlaceholder;
    addField.maxLength = TEXT_MAX;
    addField.setAttribute("aria-label", t.addLabel);
    const addButton = kit.button("setup-button-secondary setup-button-sm", t.add, add);
    addField.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.isComposing) add();
    });
    const addRow = el("div", "setup-memory-add-row");
    addRow.append(addField, addButton);
    adding.append(addRow);

    const empty = kit.card();
    empty.append(el("p", "setup-help", t.none));
    const groups = kit.item("items", el("div", "setup-memory-groups"));

    // ---- Export and import, folded.
    const more = kit.fold(t.moreTitle);
    kit.item("transfer", more.node);
    const exportRow = kit.optionRow(t.exportTitle, t.exportText, (() => {
      const buttons = el("div", "setup-memory-tools setup-memory-export");
      buttons.append(
        kit.button("setup-button-secondary setup-button-sm", "JSON", () => save("json")),
        kit.button("setup-button-secondary setup-button-sm", "Markdown", () => save("md")),
      );
      return buttons;
    })());
    const exportNote = el("p", "setup-help");
    exportNote.hidden = true;
    exportRow.words.append(exportNote);
    const importBox = el("div", "setup-memory-import");
    const paste = el("textarea", "setup-input setup-textarea setup-memory-paste");
    paste.rows = 5;
    paste.maxLength = PASTE_MAX;
    paste.setAttribute("aria-label", t.importLabel);
    const read = kit.button("setup-button-secondary setup-button-sm", t.importRead, readPaste);
    const offered = el("div", "setup-memory-offered");
    const keep = kit.button("setup-button-primary setup-button-sm", "", keepPasted);
    const importNote = el("p", "setup-help");
    importNote.hidden = true;
    importBox.append(el("p", "setup-option-name", t.importTitle), el("p", "setup-option-text", t.importText), paste, read, offered, keep, importNote);
    more.body.append(exportRow.row, importBox);

    const all = kit.item("all", kit.card());
    const allButton = kit.button("setup-button-secondary setup-button-sm", t.allTitle, forgetAll);
    all.append(kit.optionRow(t.allTitle, t.allText, allButton).row);
    switches.hidden = adding.hidden = empty.hidden = more.node.hidden = all.hidden = true;
    node.append(error, switches, adding, empty, groups, more.node, all);

    function day(iso) {
      const when = new Date(`${iso}T00:00:00`);
      if (Number.isNaN(when.getTime())) return iso;
      return when.toLocaleDateString(paI18n.locale, { month: "short", day: "numeric" });
    }
    function plainDate(epoch) {
      return new Date(epoch * 1000).toLocaleDateString(paI18n.locale, { month: "short", day: "numeric" });
    }

    // One kept item: its words, the day it was kept and the way to its source, then rewrite and forget; or the
    // field while it is being rewritten.
    function itemRow(item, when) {
      const row = el("div", "setup-memory-item");
      if (mem.editing === item.id) {
        const field = kit.input("setup-memory-input");
        field.value = item.text;
        field.maxLength = TEXT_MAX;
        field.setAttribute("aria-label", t.editLabel);
        const save = kit.button("setup-button-primary setup-button-sm", t.save, () => write("edit", { id: item.id, text: field.value }, save));
        const cancel = kit.button("setup-button-secondary setup-button-sm", t.cancel, () => {
          mem.editing = "";
          render();
        });
        field.addEventListener("keydown", (event) => {
          if (event.key === "Enter" && field.value.trim()) save.click();
          if (event.key === "Escape") cancel.click();
        });
        const tools = el("div", "setup-memory-tools");
        tools.append(save, cancel);
        row.append(field, tools);
        requestAnimationFrame(() => field.focus());
        return row;
      }
      const words = el("div", "setup-memory-words");
      words.append(el("p", "setup-memory-text", item.text));
      const meta = el("p", "setup-help setup-memory-meta");
      meta.append([when, item.at ? paI18n.t("setup_memory.kept", { day: plainDate(item.at) }) : ""].filter(Boolean).join(" · "));
      if (item.said) {
        const opened = mem.open === item.id;
        const link = el("button", "setup-memory-said-open", opened ? t.saidClose : t.saidOpen);
        link.type = "button";
        link.setAttribute("aria-expanded", String(opened));
        link.addEventListener("click", () => showSaid(item.id));
        meta.append(" · ", link);
      }
      words.append(meta);
      if (mem.open === item.id && mem.said[item.id]) words.append(quotes(mem.said[item.id]));
      const tools = el("div", "setup-memory-tools");
      tools.append(
        kit.iconButton("setup-memory-icon", "pencil", t.edit, () => {
          mem.editing = item.id;
          render();
        }),
        kit.iconButton("setup-memory-icon setup-memory-forget", "cross", t.forget, async () => {
          // The chats keep their words unless the person ticks the second choice.
          const sure = await ctx.confirm({ title: t.forgetAsk, text: t.forgetText, ok: t.forget, also: t.forgetChats });
          if (sure) write(sure.also ? "forget_chats" : "forget", { id: item.id });
        }),
      );
      row.append(words, tools);
      return row;
    }

    // The chat lines an item came from, each with its day.
    function quotes(lines) {
      const box = el("div", "setup-memory-quotes");
      if (!lines.length) box.append(el("p", "setup-help", t.saidNone));
      for (const line of lines) {
        const quote = el("blockquote", "setup-memory-quote");
        quote.append(el("span", "setup-memory-quote-day", plainDate(line.at)), el("span", "", line.text));
        box.append(quote);
      }
      return box;
    }

    async function showSaid(id) {
      if (mem.open === id) {
        mem.open = "";
        return render();
      }
      try {
        mem.said[id] = (await ctx.api(`person/said/${encodeURIComponent(id)}`)).lines;
        mem.open = id;
      } catch (failure) {
        kit.failed(error, failure, t);
      }
      render();
    }

    function deletedRow(row) {
      const line = el("div", "setup-memory-item");
      const words = el("div", "setup-memory-words");
      words.append(el("p", "setup-memory-text setup-memory-gone", row.text),
        el("p", "setup-help", [t.why[row.why], row.at ? plainDate(row.at) : ""].filter(Boolean).join(" · ")));
      const back = kit.button("setup-button-secondary setup-button-sm", t.restore, () => write("restore", { id: row.tid }, back));
      line.append(words, back);
      return line;
    }

    function group(title, rows) {
      const box = kit.card(title);
      box.classList.add("setup-memory-group");
      box.append(...rows);
      return box;
    }

    // What a pasted list offers: a tick for each item that may be kept, the reason beside each that may not.
    function renderPasted() {
      const lines = mem.pasted;
      offered.replaceChildren();
      keep.hidden = true;
      if (!lines) return;
      if (!lines.length) return offered.append(el("p", "setup-help", t.importNone));
      for (const line of lines) {
        const row = el("label", "setup-memory-offer");
        const tick = el("input");
        tick.type = "checkbox";
        tick.checked = line.ok && line.pick !== false;
        tick.disabled = !line.ok || mem.busy;
        tick.addEventListener("change", () => {
          line.pick = tick.checked;
          renderPasted();
        });
        const words = el("span", "setup-memory-offer-words");
        words.append(el("span", line.ok ? "" : "setup-memory-gone", line.text));
        if (!line.ok) words.append(el("span", "setup-help", t.refused[line.why] || ""));
        row.append(tick, words);
        offered.append(row);
      }
      const count = lines.filter((line) => line.ok && line.pick !== false).length;
      kit.relabel(keep, paI18n.t("setup_memory.importKeep", { count }));
      keep.hidden = !lines.some((line) => line.ok);
      keep.disabled = !count || mem.busy;
    }

    function render() {
      const view = mem.view;
      if (!view) return;
      const on = view.settings.on;
      use.box.checked = on;
      health.box.checked = view.settings.health;
      const sorted = t.groups.map(() => []);
      for (const fact of view.facts) sorted[GROUP[fact.kind] ?? 3].push(itemRow(fact, ""));
      for (const plan of view.plans) {
        // A plan's day is in its words once they carry the date; otherwise it is said under them.
        const when = plan.dated ? "" : plan.until && plan.until !== plan.due ? paI18n.t("setup_memory.until", { from: day(plan.due), to: day(plan.until) }) : day(plan.due);
        sorted[PLANS].push(itemRow(plan, when));
      }
      const cards = sorted.map((rows, i) => (rows.length ? group(t.groups[i], rows) : null)).filter(Boolean);
      if (view.trash.length) {
        const box = group(t.deleted, view.trash.map(deletedRow));
        box.classList.add("setup-memory-trash");
        box.querySelector(".setup-card-title").after(el("p", "setup-help", t.deletedHint));
        cards.push(box);
      }
      groups.replaceChildren(...cards);
      const kept = view.facts.length + view.plans.length;
      switches.hidden = more.node.hidden = false;
      adding.hidden = !on;
      importBox.hidden = !on;
      empty.hidden = Boolean(kept || view.trash.length);
      all.hidden = !(kept || view.trash.length);
      for (const control of node.querySelectorAll("button, input, textarea")) control.disabled = mem.busy;
      // Health details are a part of memory: their switch waits while memory is off.
      health.box.disabled = mem.busy || !on;
      renderPasted();
    }

    async function write(action, body, spinner) {
      if (mem.busy) return;
      mem.busy = true;
      error.hidden = true;
      if (spinner) kit.busy(spinner, true);
      for (const control of node.querySelectorAll("button, input, textarea")) control.disabled = true;
      try {
        mem.view = await ctx.api(`person/${action}`, body);
        mem.editing = "";
        return true;
      } catch (failure) {
        kit.failed(error, failure, t);
        if (failure.message === "activity_changed") {
          mem.editing = "";
          await load();
        }
        return false;
      } finally {
        if (spinner) kit.busy(spinner, false);
        mem.busy = false;
        render();
      }
    }

    async function add() {
      const text = addField.value.trim();
      if (!text || mem.busy) return;
      if (await write("add", { text }, addButton)) addField.value = "";
    }

    // In the app window the system's Save dialog; in a browser the browser's own download.
    async function save(format) {
      exportNote.hidden = error.hidden = true;
      try {
        if (ctx.told) {
          if ((await ctx.api("person/export", { format })).saved) {
            exportNote.textContent = t.exportSaved;
            exportNote.hidden = false;
          }
          return;
        }
        const file = await ctx.api(`person/export?format=${format}`);
        const link = el("a");
        link.href = URL.createObjectURL(new Blob([file.text], { type: format === "json" ? "application/json" : "text/markdown" }));
        link.download = file.file;
        link.click();
        URL.revokeObjectURL(link.href);
      } catch (failure) {
        kit.failed(error, failure, t);
      }
    }

    async function readPaste() {
      const text = paste.value.trim();
      importNote.hidden = true;
      if (!text || mem.busy) return;
      mem.busy = true;
      kit.busy(read, true);
      try {
        mem.pasted = (await ctx.api("person/import_preview", { text })).lines;
      } catch (failure) {
        kit.failed(error, failure, t);
      } finally {
        kit.busy(read, false);
        mem.busy = false;
        render();
      }
    }

    async function keepPasted() {
      const lines = mem.pasted.filter((line) => line.ok && line.pick !== false).map((line) => line.text);
      if (!lines.length) return;
      if (await write("import", { lines }, keep)) {
        importNote.textContent = paI18n.t("setup_memory.importDone", { count: mem.view.imported });
        importNote.hidden = false;
        mem.pasted = null;
        paste.value = "";
        render();
      }
    }

    async function forgetAll() {
      const sure = await ctx.confirm({ title: t.allAsk, text: t.allAskText, ok: t.allTitle });
      if (sure) write("forget_all", {}, allButton);
    }

    async function load() {
      try {
        mem.view = await ctx.api("person");
      } catch (failure) {
        kit.failed(error, failure, t);
      }
    }

    async function show() {
      if (mem.busy) return;
      error.hidden = true;
      mem.editing = "";
      mem.open = "";
      await load();
      render();
    }

    return { node, show };
  });
})();
