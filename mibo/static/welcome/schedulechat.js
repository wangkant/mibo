"use strict";
// Scheduled tasks in the chat (panels/schedule.py). Over a message a task's run brought: a small clock mark with the
// task's name, and when it came late, when it was due. Under a reply that made or changed tasks: one line each with
// its rhythm and next time and a button that takes it back, or, for a task that may act or runs often, the card it
// waits on (POST /api/schedule/offer). Under a run's result: what the run did not do because nobody was watching,
// each with a button that asks for it now in the chat, where the usual cards apply.
window.paScheduleChat = (() => {
  const SVG = "http://www.w3.org/2000/svg";
  const CLOCK = '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>';

  function el(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  }
  function clock(cls = "i") {
    const mark = document.createElementNS(SVG, "svg");
    mark.setAttribute("viewBox", "0 0 24 24");
    mark.setAttribute("aria-hidden", "true");
    mark.setAttribute("class", cls);
    mark.innerHTML = CLOCK;
    return mark;
  }
  const fill = (text, values) => text.replace(/\{(\w+)\}/g, (_, key) => values[key] ?? "");
  async function post(path, body) {
    const response = await fetch(`/api/${path}`, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json",
        "X-Mibo-Setup-Token": sessionStorage.getItem("mibo-setup-token") || "" },
      body: JSON.stringify(body),
    });
    if (!response.ok) throw new Error("failed");
    return response.json();
  }
  // The tasks as kept now, read once for every card drawn together, so an answered card shows as answered.
  let kept = null;
  function tasks() {
    if (!kept) {
      kept = fetch("/api/schedule", { credentials: "same-origin",
        headers: { "X-Mibo-Setup-Token": sessionStorage.getItem("mibo-setup-token") || "" } })
        .then((r) => r.json()).then((v) => v.tasks || []).catch(() => []);
      setTimeout(() => (kept = null), 3000);
    }
    return kept;
  }
  // A time in the person's zone, `offset` minutes from UTC, which may not be the computer's.
  function when(seconds, offset) {
    const at = new Date((seconds + offset * 60) * 1000);
    const pad = (n) => String(n).padStart(2, "0");
    const time = `${pad(at.getUTCHours())}:${pad(at.getUTCMinutes())}`;
    return `${at.toLocaleDateString(paI18n.lang === "en" ? "en-GB" : paI18n.locale,
      { day: "numeric", month: "short", timeZone: "UTC" })} ${time}`;
  }

  // Over a run's message: the clock, the task's name and kind, and when it came late.
  function mark(task, t) {
    const node = el("div", "task-mark");
    if (task.failed || task.notice) node.classList.add("task-mark-off");
    node.append(clock("i task-mark-icon"), el("span", "task-mark-title", task.title),
      el("span", "task-mark-kind", task.failed ? t.failed : task.notice ? t.notice : t.kinds[task.kind] || ""));
    if (task.late) {
      const late = el("p", "task-mark-late", fill(t.late, { due: when(task.due, task.offset) })
        + (task.missed ? fill(t.missed, { n: task.missed }) : ""));
      const wrap = el("div", "task-mark-wrap");
      wrap.append(node, late);
      return wrap;
    }
    return node;
  }

  // A task made or changed by the reply: one line, and its undo.
  function noteLine(note, t) {
    const line = el("div", "task-note");
    const words = [`${t.states[note.state] || ""}「${note.title}」`, note.rhythm, note.next && fill(t.next, note)]
      .filter(Boolean).join(" · ");
    line.append(clock("i task-note-icon"), el("span", "task-note-text", words));
    const undo = el("button", "pa-btn pa-btn-link pa-btn-sm task-note-undo", t.undo);
    undo.type = "button";
    undo.addEventListener("click", async () => {
      undo.disabled = true;
      try {
        await post("schedule/undo", { id: note.id });
        undo.replaceWith(el("span", "task-note-done", t.undone));
      } catch {
        undo.replaceWith(el("span", "task-note-done", t.undoGone));
      }
    });
    line.append(undo);
    return line;
  }

  // A task that may act or runs often: the card it waits on.
  function offerCard(note, t) {
    const node = el("div", "op-card task-offer");
    const head = el("div", "op-card-head");
    const tile = el("span", "op-card-icon");
    tile.append(clock());
    const words = el("div", "op-card-words");
    words.append(el("p", "op-card-title", fill(t.offerTitle, note)), el("p", "op-card-meta", t.kinds[note.kind] || ""));
    head.append(tile, words);
    const facts = el("dl", "op-card-facts");
    const fact = (name, value) => facts.append(el("dt", "", name), el("dd", "", value));
    fact(t.offerRhythm, [note.rhythm, note.next && fill(t.next, note)].filter(Boolean).join(" · "));
    if (note.perDay) fact(t.offerRuns, fill(t.offerRunsText, { n: note.perDay }));
    fact(t.offerActs, (note.acts || []).includes("browser") ? t.browser : t.readOnly);
    node.append(head, facts);
    const buttons = el("div", "op-card-buttons");
    const told = (text) => {
      node.classList.add("answered");
      buttons.remove();
      node.append(el("p", "op-card-told", text));
    };
    const answer = async (yes) => {
      for (const b of buttons.querySelectorAll("button")) b.disabled = true;
      try {
        const value = await post("schedule/offer", { id: note.id, yes });
        told(value.active ? t.made : t.notMade);
      } catch {
        told(t.gone);
      }
    };
    for (const [cls, text, yes] of [["pa-btn-primary", t.yes, true], ["pa-btn-ghost", t.no, false]]) {
      const b = el("button", `pa-btn ${cls} pa-btn-sm`, text);
      b.type = "button";
      b.addEventListener("click", () => answer(yes));
      buttons.append(b);
    }
    node.append(buttons);
    // Answered before (another window, a reload): said as it stands.
    tasks().then((list) => {
      if (node.classList.contains("answered")) return;
      const now = list.find((one) => one.id === note.id);
      if (!now) told(t.notMade);
      else if (!now.offer) told(t.made);
    });
    return node;
  }

  // What the run did not do, each with a button that asks for it now in the chat.
  function proposals(list, t, ask) {
    const node = el("div", "task-proposals");
    node.append(el("p", "task-proposals-head", t.proposals));
    for (const what of list) {
      const row = el("div", "task-proposal");
      const b = el("button", "pa-btn pa-btn-secondary pa-btn-sm", t.doIt);
      b.type = "button";
      b.addEventListener("click", () => {
        if (ask(fill(t.askText, { what })) === false) return;
        b.replaceWith(el("span", "task-note-done", t.asked));
      });
      row.append(el("p", "task-proposal-text", what), b);
      node.append(row);
    }
    return node;
  }

  function decorate(node, item, ask) {
    const t = paI18n.words("schedulechat");
    if (item.task) {
      node.classList.add("from-task");
      node.prepend(mark(item.task, t));
    }
    for (const note of item.schedule || []) node.append(note.state === "offer" ? offerCard(note, t) : noteLine(note, t));
    if (item.proposals?.length) node.append(proposals(item.proposals, t, ask));
  }

  return { decorate };
})();
