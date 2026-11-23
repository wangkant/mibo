"use strict";
// Settings › Scheduled tasks: every task kept (GET /api/schedule), with what it does, its rhythm, its next and last
// run; a switch each; run now, edit and delete; and under each its run record with what every run cost. A task is
// made here with a form whose time is read by the app as it is typed (GET /api/schedule/parse), or in the chat.
(() => {

  window.paSetup.part("schedule", (kit) => {
    const { el, fill } = kit;
    const t = kit.words("setup_schedule");
    const ctx = kit.ctx;
    const node = kit.section("schedule", t.hint);
    let view = null;
    let editing = null;

    const top = el("div", "setup-schedule-top");
    const add = kit.button("setup-button-primary setup-button-sm", t.add, () => openForm(null));
    top.append(add);
    const listError = kit.errorLine();
    const list = el("div", "setup-schedule-list");
    const form = kit.card();
    form.classList.add("setup-schedule-form");
    form.hidden = true;
    const rules = kit.fold(t.limitsTitle);
    node.append(top, form, listError, list, rules.node);

    // ---- The form: name, kind, what, the condition for a check, the time as words, and the browser allowance.
    const nameField = kit.field(t.name, kit.input());
    nameField.control.placeholder = t.namePlaceholder;
    nameField.control.maxLength = 40;
    let kind = "task";
    const kindChoice = kit.choices(t.kind, Object.entries(t.kinds), (value) => setKind(value));
    const kindField = el("div", "setup-field");
    const kindHelp = el("p", "setup-help");
    kindField.append(el("p", "setup-label", t.kind), kindChoice.group, kindHelp);
    const requestBox = el("textarea", "setup-input setup-textarea");
    requestBox.rows = 2;
    requestBox.maxLength = 600;
    const requestField = kit.field(t.request.task, requestBox);
    const conditionField = kit.field(t.condition, kit.input());
    conditionField.control.placeholder = t.conditionPlaceholder;
    const whenField = kit.field(t.when, kit.input());
    whenField.control.placeholder = t.whenPlaceholder;
    const acts = kit.switchRow("schedule-acts", t.acts, t.actsText, () => {});
    const formError = kit.errorLine();
    const buttons = el("div", "setup-schedule-buttons");
    const save = kit.button("setup-button-primary setup-button-sm", t.save, submit);
    const cancel = kit.button("setup-button-secondary setup-button-sm", t.cancel, () => (form.hidden = true));
    buttons.append(save, cancel);
    form.append(nameField.wrap, kindField, requestField.wrap, conditionField.wrap, whenField.wrap, acts.row, formError, buttons);

    function setKind(value) {
      kind = value;
      kindChoice.set(value);
      kindHelp.textContent = t.kindHelp[value];
      requestField.label.textContent = t.request[value];
      requestBox.placeholder = t.requestPlaceholder[value];
      conditionField.wrap.hidden = value !== "watch";
      acts.row.hidden = value === "remind";
    }

    // The time as the app reads it, said back under the field as it is typed.
    let reading = 0;
    whenField.control.addEventListener("input", () => {
      const asked = ++reading;
      clearTimeout(whenField.wait);
      whenField.wait = setTimeout(async () => {
        const words = whenField.control.value.trim();
        if (!words) return whenField.help("");
        try {
          const read = await ctx.api(`schedule/parse?when=${encodeURIComponent(words)}`);
          if (asked !== reading) return;
          if (read.error) {
            whenField.help("");
            whenField.error(t.errors[read.error] || t.whenUnread);
          } else {
            whenField.error("");
            whenField.help([read.rhythm, read.nextText && fill(t.next, { next: read.nextText })].filter(Boolean).join(" · "));
          }
        } catch (error) {
          whenField.error(kit.say(error, t));
        }
      }, 250);
    });

    function openForm(task) {
      editing = task;
      form.hidden = false;
      formError.hidden = true;
      nameField.control.value = task?.title || "";
      requestBox.value = task?.request || "";
      conditionField.control.value = task?.condition || "";
      whenField.control.value = "";
      whenField.control.placeholder = task ? task.rhythm : t.whenPlaceholder;
      whenField.help(task ? fill(t.next, { next: task.nextText || "—" }) : "");
      whenField.error("");
      acts.box.checked = Boolean(task?.acts?.includes("browser"));
      setKind(task?.kind || "task");
      for (const item of kindChoice.group.children) item.disabled = Boolean(task);
      nameField.control.focus();
    }

    async function submit() {
      formError.hidden = true;
      const fields = { title: nameField.control.value, kind, request: requestBox.value,
        condition: conditionField.control.value, acts: acts.box.checked && kind !== "remind" ? ["browser"] : [] };
      const when = whenField.control.value.trim();
      if (when || !editing) fields.when = when;
      kit.busy(save, true);
      try {
        view = await ctx.api("schedule", editing ? { action: "update", id: editing.id, fields } : { action: "create", fields });
        form.hidden = true;
        render();
      } catch (error) {
        kit.failed(formError, error, t);
      } finally {
        kit.busy(save, false);
      }
    }

    // ---- One task: what, when, the switch; its last run; its buttons; its record under a fold.
    function costOf(run) {
      const parts = [];
      if (run.tokens) parts.push(fill(t.tokens, { n: run.tokens.toLocaleString() }));
      if (run.cost === null || run.cost === undefined) {
        if (run.tokens) parts.push(t.costUnknown);
      } else if (run.tokens) parts.push(fill(t.cost, { c: run.cost < 0.01 ? run.cost.toFixed(4) : run.cost.toFixed(2) }));
      return parts.join(" · ");
    }
    function runLine(run) {
      const item = el("div", "setup-shell-entry setup-schedule-run");
      const head = [run.atText, t.states[run.state] || run.state, costOf(run)].filter(Boolean).join(" · ");
      item.append(el("p", "setup-option-name", head));
      const notes = [run.by === "hand" && t.byHand, run.late && fill(t.due, { due: run.dueText }),
        run.missed && fill(t.missed, { n: run.missed }), run.proposals && fill(t.proposals, { n: run.proposals })].filter(Boolean);
      if (notes.length) item.append(el("p", "setup-help", notes.join(" · ")));
      if (run.text && run.state !== "failed" && run.state !== "retry") item.append(el("p", "setup-schedule-said", run.text));
      return item;
    }
    function row(task) {
      const card = el("div", "setup-card setup-schedule-task");
      card.dataset.id = task.id;
      const headRow = el("div", "setup-schedule-head");
      const words = el("div", "setup-option-words");
      const title = el("p", "setup-option-name");
      title.append(el("span", "", task.title), el("span", "setup-schedule-kind", t.kinds[task.kind]));
      if (task.acts?.length) title.append(el("span", "setup-schedule-kind setup-schedule-acts", t.browserBadge));
      const state = task.running ? t.running : task.offer ? t.offer : task.retry ? fill(t.retry, { at: task.retry })
        : task.active ? fill(t.next, { next: task.nextText }) : task.nextText ? t.paused : t.finished;
      words.append(title, el("p", "setup-option-text", `${task.rhythm} · ${state}`));
      const scope = task.scope || {};
      if (scope.act) {
        const what = [scope.site, t.scopeActs[scope.act], scope.to, scope.text || scope.about].filter(Boolean).join(" · ");
        words.append(el("p", "setup-option-text", fill(t.scopeLine, { what })));
      }
      const sw = el("input", "setup-switch");
      sw.type = "checkbox";
      sw.setAttribute("role", "switch");
      sw.setAttribute("aria-label", fill(t.on, task));
      sw.checked = task.active;
      sw.disabled = task.offer || (!task.nextText && !task.active);
      sw.addEventListener("change", () => act({ action: sw.checked ? "resume" : "pause", id: task.id }, sw));
      headRow.append(words, sw);
      card.append(headRow, el("p", "setup-schedule-request", task.kind === "watch" && task.condition
        ? `${task.request} · ${task.condition}` : task.request));
      const last = task.runs[0];
      card.append(el("p", "setup-help", last ? fill(t.last, { at: last.atText, state: [t.states[last.state] || last.state,
        costOf(last)].filter(Boolean).join(" · ") }) : t.never));
      const tools = el("div", "setup-option-actions setup-schedule-tools");
      const runNow = kit.button("setup-button-secondary setup-button-sm", t.runNow, () => act({ action: "run", id: task.id }, runNow));
      runNow.disabled = task.running || task.offer;
      tools.append(runNow,
        kit.button("setup-button-ghost setup-button-sm", t.edit, () => openForm(task)),
        kit.button("setup-button-ghost setup-button-sm setup-schedule-remove", t.remove, () => remove(task)));
      const error = kit.errorLine();
      card.append(tools, error);
      const record = kit.fold(paI18n.t("setup_schedule.record", { count: task.runs.length }));
      if (task.runs.length) record.body.append(...task.runs.map(runLine));
      else record.body.append(el("p", "setup-help", t.recordNone));
      card.append(record.node);
      card.errorLine = error;
      return card;
    }

    function render() {
      list.replaceChildren(...(view.tasks.length ? view.tasks.map(row) : [el("p", "setup-help setup-schedule-empty", t.empty)]));
      rules.body.replaceChildren(
        el("p", "setup-help", fill(t.limits, { active: view.limits.active, floor: view.limits.floor, day: view.limits.dayRuns,
          now: view.dayRuns })),
        el("p", "setup-help", fill(t.zone, view)));
    }

    async function act(body, control) {
      listError.hidden = true;
      control.disabled = true;
      try {
        view = await ctx.api("schedule", body);
        render();
      } catch (error) {
        kit.failed(control.closest(".setup-schedule-task")?.errorLine || listError, error, t);
        control.disabled = false;
        if (control.type === "checkbox") control.checked = !control.checked;
      }
    }

    async function remove(task) {
      const sure = await ctx.confirm({ title: fill(t.removeAsk, task), text: t.removeText, ok: t.remove });
      if (sure) act({ action: "delete", id: task.id }, list);
    }

    async function load() {
      try {
        view = await ctx.api("schedule");
        listError.hidden = true;
        render();
      } catch (error) {
        kit.failed(listError, error, t);
      }
    }

    return { node, show: load };
  });
})();
