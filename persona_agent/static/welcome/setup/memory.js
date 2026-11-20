"use strict";
// Settings › Memory: what the character keeps about the one person (person.json),
// by kind, with forget, edit and restore for each item and forget all (GET /api/person,
// POST /api/person/<action>).
(() => {
  // A fact's kind to its group, as person.py's listing heads them; plans are group 4.
  const GROUP = { who: 0, people: 0, health: 0, like: 1, dislike: 2, life: 3, other: 3, manner: 5, form: 5 };
  const PLANS = 4;
  // An edit takes at most what the store keeps of one item (person.TEXT_MAX).
  const TEXT_MAX = 60;

  window.paSetup.part("memory", (kit) => {
    const { el } = kit;
    const t = kit.words("setup_memory");
    const ctx = kit.ctx;
    const mem = { view: null, busy: false, editing: "" };
    const node = kit.section("memory");

    const error = kit.errorLine();
    const empty = kit.card();
    empty.append(el("p", "setup-help", t.none));
    empty.hidden = true;
    const groups = el("div", "setup-memory-groups");
    const all = kit.card();
    const allButton = kit.button("setup-button-secondary setup-button-sm", t.allTitle, forgetAll);
    all.append(kit.optionRow(t.allTitle, t.allText, allButton).row);
    all.hidden = true;
    node.append(error, empty, groups, all);

    function day(iso) {
      const when = new Date(`${iso}T00:00:00`);
      if (Number.isNaN(when.getTime())) return iso;
      return when.toLocaleDateString(paI18n.locale, { month: "short", day: "numeric" });
    }
    function plainDate(epoch) {
      return new Date(epoch * 1000).toLocaleDateString(paI18n.locale, { month: "short", day: "numeric" });
    }

    // One kept item: its words and when, then rewrite and forget; or the field while it is being rewritten.
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
      if (when) words.append(el("p", "setup-help", when));
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

    function render() {
      const view = mem.view;
      if (!view) return;
      const sorted = t.groups.map(() => []);
      for (const fact of view.facts) sorted[GROUP[fact.kind] ?? 3].push(itemRow(fact, ""));
      for (const plan of view.plans) {
        const when = plan.until && plan.until !== plan.due ? paI18n.t("setup_memory.until", { from: day(plan.due), to: day(plan.until) }) : day(plan.due);
        sorted[PLANS].push(itemRow(plan, when));
      }
      const cards = sorted.map((rows, i) => (rows.length ? group(t.groups[i], rows) : null)).filter(Boolean);
      if (view.trash.length) {
        const box = group(t.deleted, view.trash.map(deletedRow));
        box.querySelector(".setup-card-title").after(el("p", "setup-help", t.deletedHint));
        cards.push(box);
      }
      groups.replaceChildren(...cards);
      const kept = view.facts.length + view.plans.length;
      empty.hidden = Boolean(kept || view.trash.length);
      all.hidden = !(kept || view.trash.length);
      for (const control of node.querySelectorAll("button, input")) control.disabled = mem.busy;
    }

    async function write(action, body, spinner) {
      if (mem.busy) return;
      mem.busy = true;
      error.hidden = true;
      if (spinner) kit.busy(spinner, true);
      for (const control of node.querySelectorAll("button, input")) control.disabled = true;
      try {
        mem.view = await ctx.api(`person/${action}`, body);
        mem.editing = "";
      } catch (failure) {
        kit.failed(error, failure, t);
        if (failure.message === "activity_changed") {
          mem.editing = "";
          await load();
        }
      } finally {
        mem.busy = false;
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
      await load();
      render();
    }

    return { node, show };
  });
})();
