"use strict";
// The run while the character operates the page for the person (web/operate.py), as browser.py last told it
// ({task, held, end, why, note, steps, card}): in the chat's box while it is under way or waits on the person (its
// state, a card waiting on their yes, the steps, how it ended and what they may press), and in the bar while the
// chat is out of sight. browse.js mounts it, sets `op` as it is told and draws it with the rest of the pane.
window.paBrowseRun = ({ pane, post, chatNow, beside, goOn }) => {
  const ICONS = {
    stop: '<rect x="6.5" y="6.5" width="11" height="11" rx="1.5" />',
    // A step's mark: done, failed, stopped or cancelled.
    done: '<path d="M5 12.5l4.5 4.5L19 7.5" />',
    failed: '<path d="M7 7l10 10M17 7 7 17" />',
    stopped: '<path d="M7 12h10" />',
  };
  // The asking cards' one look (chat.js cardHead): an icon, the question, one faint line.
  const CARD_ICONS = {
    out: '<path d="M4 12l16-8-6 16-2.5-6.5z" /><path d="M11.5 13.5 20 4" />',
    like: '<path d="M12 20s-7-4.4-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 10c0 5.6-7 10-7 10z" />',
    ask: '<circle cx="12" cy="12" r="8.5" /><path d="M12 7.5v5.5M12 16.2v.3" />',
    key: '<circle cx="8" cy="15" r="4" /><path d="M10.8 12.2 20 3M16 7l3 3M14 9l2 2" />',
  };
  // The ends after which the page is the person's until they say to go on (browser.THEIRS).
  const THEIRS = ["handover", "asked", "paused", "cap", "waiting"];
  const col = () => paI18n.words("browse").col;
  const svg = (name) => `<svg viewBox="0 0 24 24" aria-hidden="true">${ICONS[name]}</svg>`;
  function el(tag, className = "", text = "") {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text) node.textContent = text;
    return node;
  }
  function button(className, text, run, title = "") {
    const node = el("button", className, text);
    node.type = "button";
    if (title) node.title = title;
    node.addEventListener("click", run);
    return node;
  }

  // With the chat out of sight, a run under way is said in the bar: its state and the step it is on (a press
  // brings the chat), and 停止.
  const pill = el("div", "browse-run-pill");
  pill.hidden = true;
  const pillOpen = button("browse-run-open", "", () => beside(true));
  const pillMode = el("span", "browse-run-mode");
  const pillStep = el("span", "browse-run-step");
  pillOpen.append(el("span", "browse-run-dot"), pillMode, pillStep);
  const pillStop = button("browse-btn browse-run-stop", "", () => post("browser/do", { action: "op_stop" }));
  pillStop.innerHTML = svg("stop");
  pill.append(pillOpen, pillStop);

  // In the chat's box: its state, a card waiting on the person, the steps, how it ended.
  const panel = el("div", "browse-run");
  const cardBox = el("div", "browse-run-card");
  const runBox = el("div", "browse-run-box");
  const head = el("div", "browse-run-head");
  const mode = el("span", "browse-run-mode");
  head.append(el("span", "browse-run-dot"), mode);
  const scroller = el("div", "browse-run-scroll");
  const list = el("ol", "browse-steps");
  scroller.append(list);
  // The foot: how the run ended and what the person may press.
  const foot = el("div", "browse-run-foot");
  const endLine = el("p", "browse-run-end");
  const actions = el("div", "browse-run-actions");
  foot.append(endLine, actions);
  runBox.append(head, scroller, foot);
  panel.append(cardBox, runBox);

  let op = null;
  let shownCard = "";
  const running = () => Boolean(op && !op.end);
  // The run ended waiting on the person: what they type or press next goes on with it.
  const waits = () => Boolean(op) && THEIRS.includes(op.end);
  // A run that needs the person: a card, a sign-in, or an end that leaves the page theirs.
  const needs = (run) => Boolean(run) && Boolean(run.card || run.wait || THEIRS.includes(run.end));
  function modeOf() {
    if (!op.end) {
      if (op.held === "stopped") return "stopping";
      if (op.wait) return "theirs";
      if (op.held) return "theirs";
      return op.card ? "waiting" : "acting";
    }
    if (op.end === "done") return "done";
    if (op.end === "failed") return "failed";
    if (THEIRS.includes(op.end)) return "theirs";
    return "stopped";
  }
  // The steps as the list shows them: those taken for one purpose (the loop's note, kept with each step by
  // browser.py) stand together under it; a step with no note stands by its own words.
  function stepRows(steps) {
    const rows = [];
    for (const step of steps) {
      const last = rows.at(-1);
      if (step.note && last?.acts && last.note === step.note) last.acts.push(step);
      else rows.push(step.note ? { note: step.note, acts: [step] } : step);
    }
    return rows;
  }
  // One row: what it is for as its title, each action beneath in the person's words, and under an action that did
  // not work, why. Its mark is how its last action stands.
  function stepNode(row) {
    const acts = row.acts || [row];
    const state = acts.at(-1).state;
    const node = el("li", `browse-step is-${state}`);
    const mark = el("span", "browse-step-mark");
    if (ICONS[state]) mark.innerHTML = svg(state);
    if (state === "cancelled") mark.innerHTML = svg("stopped");
    const words = el("div", "browse-step-words");
    if (row.acts) words.append(el("span", "", row.note));
    for (const act of acts) {
      words.append(el("span", row.acts ? "browse-step-act" : "", act.text + (act.n > 1 ? col().times.replace("{n}", act.n) : "")));
      if (act.why) words.append(el("span", `browse-step-why${act.state === "failed" ? " is-failed" : ""}`, act.why));
    }
    node.append(mark, words);
    return node;
  }
  function cardHead(icon, title, meta) {
    const head = el("div", "op-card-head");
    const tile = el("span", "op-card-icon");
    tile.innerHTML = `<svg class="i" viewBox="0 0 24 24" aria-hidden="true">${CARD_ICONS[icon]}</svg>`;
    const text = el("div", "op-card-words");
    text.append(el("p", "op-card-title", title));
    if (meta) text.append(el("p", "op-card-meta", meta));
    head.append(tile, text);
    return head;
  }
  // Something with an effect outside (web/gate.py), waiting for the person's yes typed in the chat (chat.js,
  // cardwait.py): its act as the question, then only what matters, each once; the control it presses is ringed on
  // the page itself. Drawn once per question.
  function drawCard(card) {
    if ((card?.id || "") === shownCard) return;
    shownCard = card?.id || "";
    cardBox.replaceChildren();
    if (!card) return;
    if (card.kind === "auto_sign_in") return drawAutoCard(card);
    if (card.kind === "wait") return drawWaitCard(card);
    const words = col().card;
    const node = el("div", "op-card browse-card");
    const where = [card.to ? (card.kind === "send" ? words.to.replace("{to}", card.to) : card.to) : card.kind === "send" ? words.noTo : "", card.site]
      .filter(Boolean).join(" · ");
    const icon = card.skippable ? (card.kind === "like" ? "like" : "out") : "ask";
    node.append(cardHead(icon, words.titles[card.kind] || words.titles.submit, where));
    // The step's own line of what it does (surface.py's act), as the character wrote it.
    if (card.what) node.append(el("p", "op-card-why", card.what));
    if (card.text) node.append(el("blockquote", "browse-card-quote", card.text));
    if (card.button && card.ringed) node.append(el("p", "browse-card-ring", words.ring.replace("{button}", card.button)));
    else if (card.button) node.append(el("p", "browse-card-ring", card.button));
    node.append(el("p", "op-card-ask", words.ask));
    cardBox.append(node);
  }
  // The 自动登录 card: the same look, with the three answers.
  function drawAutoCard(card) {
    const words = col().signin;
    const node = el("div", "op-card browse-card");
    const head = cardHead("key", words.autoTitle.replace("{site}", card.site), words.autoMeta);
    const row = el("div", "op-card-buttons");
    const choices = [["once", "pa-btn-primary"], ["always", "pa-btn-secondary"], ["no", "pa-btn-ghost"]];
    for (const [said, look] of choices) {
      row.append(button(`pa-btn ${look} pa-btn-sm`, words[said], async () => {
        for (const other of row.querySelectorAll("button")) other.disabled = true;
        const response = await post("signins/card", { id: card.id, answer: said });
        const ok = response && (await response.json().catch(() => ({}))).ok;
        if (!ok && shownCard === card.id) node.append(el("p", "op-card-told", words.gone));
      }));
    }
    node.append(head, row);
    cardBox.append(node);
  }
  // The wait for the person's sign-in or check: what the site asks, in one sentence, the site's own sign-in (where
  // the page is not one already) and going on without the site. Its words come with it (panels/signins.py).
  function drawWaitCard(card) {
    const node = el("div", "op-card browse-card");
    const row = el("div", "op-card-buttons");
    const choices = [...(card.to ? [["go", "pa-btn-primary"]] : []), ["skip", card.to ? "pa-btn-secondary" : "pa-btn-primary"]];
    for (const [action, look] of choices) {
      row.append(button(`pa-btn ${look} pa-btn-sm`, card[action === "go" ? "go" : "pass"], () => {
        if (action === "skip") for (const other of row.querySelectorAll("button")) other.disabled = true;
        post("signins/wait", { action });
      }));
    }
    node.append(cardHead(card.wall === "verification" ? "ask" : "key", card.say, card.site), row);
    cardBox.append(node);
  }
  function endWords() {
    const words = col();
    if (op.end === "handover") {
      const [kind, field] = (op.why || "stuck").split(/:(.*)/);
      const said = words.handover[kind === "sign_in_overlay" ? "sign_in" : kind] || words.handover.stuck;
      return said.replace("{field}", field || "");
    }
    // Waiting on a card: the act it waits on, as its step says it.
    if (op.end === "waiting") return op.steps.findLast((step) => step.state === "waiting")?.text || words.modes.waiting;
    const said = words.ends[op.end] || words.ends.failed;
    // The character's own one sentence of how it went, where it wrote one for the person; at the step limit,
    // what is left.
    const note = String(op.note || "").trim();
    if (["asked", "cap"].includes(op.end) || (["done", "failed"].includes(op.end) && note && !note.startsWith("["))) {
      return ["asked", "cap"].includes(op.end) ? `${said}${note}` : note;
    }
    return said;
  }
  function drawFoot() {
    const words = col();
    const buttons = [];
    const stop = () => {
      const node = button("pa-btn pa-btn-secondary pa-btn-sm", words.stop, () => post("browser/do", { action: "op_stop" }));
      node.append(el("kbd", "browse-key", "Esc"));
      return node;
    };
    foot.classList.toggle("ended", !running() || Boolean(op.wait));
    endLine.hidden = false;
    if (running() && op.wait) {
      // Signing in is theirs, in the page: the card above says what the site asks; here only Stop.
      endLine.hidden = true;
      buttons.push(stop());
    } else if (running()) {
      endLine.hidden = true;
      buttons.push(button("pa-btn pa-btn-ghost pa-btn-sm", words.take,
        () => post("browser/do", { action: "op_take" }), words.takeTitle), stop());
    } else {
      endLine.textContent = endWords();
      // 继续: the page is theirs for a moment and they say when they are done (not where the page cannot be
      // worked, nor where it asked something or a card waits: their answer is typed in the chat's box or pressed
      // on the card).
      if (!["asked", "waiting"].includes(op.end) && op.why !== "drawn" && op.why !== "empty") {
        const text = ["paused", "cap"].includes(op.end) ? words.goOnPaused : words.goOn;
        buttons.push(button("pa-btn pa-btn-primary pa-btn-sm", text, () => goOn(text)));
      }
    }
    actions.replaceChildren(...buttons);
  }
  // The run where the chat is: in its box while the run is under way or waits on the person (once it has ended
  // otherwise, the chat's reply carries its steps), and in the bar while the chat is out of sight (`besideNow`
  // false).
  function draw(besideNow) {
    const live = !pane.hidden && Boolean(op) && (running() || waits());
    const now = live ? modeOf() : "";
    for (const name of ["acting", "waiting", "theirs", "stopping"]) {
      for (const node of [pane, panel, pill]) node.classList.toggle(`op-${name}`, now === name);
    }
    pane.classList.toggle("op-live", live);
    const words = col();
    const said = !live ? "" : running() && op.wait
      ? words.signin.modes[op.wait.wall === "verification" ? "verification" : "sign_in"] : words.modes[now];
    pill.hidden = !live || besideNow;
    if (!pill.hidden) {
      pillMode.textContent = said;
      // What the step under way is for (the loop's note), else its own words.
      const step = op.steps.at(-1);
      pillStep.textContent = running() ? step?.note || step?.text || words.thinking : endWords();
      pillOpen.title = `${said}\n${pillStep.textContent}\n${words.open}`;
      pillStop.hidden = !running();
      pillStop.title = `${words.stop} (Esc)`;
      pillStop.setAttribute("aria-label", words.stop);
    }
    const form = live && besideNow ? chatNow()?.querySelector(".chat-composer") : null;
    if (!form) return panel.remove();
    if (panel.nextElementSibling !== form) form.before(panel);
    mode.textContent = said;
    // Kept at the end as it grows, unless the person scrolled back to read.
    const atEnd = scroller.scrollTop + scroller.clientHeight >= scroller.scrollHeight - 12;
    list.replaceChildren(...stepRows(op.steps).map(stepNode));
    const last = op.steps.at(-1);
    if (running() && !op.card && !op.held && !op.wait && last?.state !== "doing") {
      list.append(stepNode({ text: words.thinking, state: "doing" }));
    }
    drawCard(running() ? op.card || (op.wait && { ...op.wait, id: `wait:${op.wait.site}:${op.wait.say}`, kind: "wait" })
      : op.end === "waiting" ? op.card : null);
    drawFoot();
    if (atEnd && !op.card) scroller.scrollTop = scroller.scrollHeight;
  }

  return {
    pill,
    draw,
    running,
    waits,
    needs,
    get op() {
      return op;
    },
    set op(next) {
      op = next;
    },
  };
};
