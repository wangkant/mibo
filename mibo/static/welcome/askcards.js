"use strict";
// The questions a step waits on, drawn in the chat under the waiting row (chat.js hangs them there and keeps the
// question's state). Each says what will happen in the app's own words and ends by asking for the person's yes,
// typed in the chat box (chat.js answerAsk, POST /api/confirm), never the model's words.
window.paAskCards = (() => {
  const { I, el, cardHead } = window.paKit;

  function shot(picture) {
    const node = el("img", "op-card-shot");
    node.src = `data:image/jpeg;base64,${picture}`;
    node.alt = "";
    return node;
  }

  // A step before a command runs on this computer (shell/panel.py): what it will do, the real list of files for a
  // delete, the exact command under a fold; or a folder to grant. The question that turns a switched-off ability on
  // (turnon.py) and a setting that widens what it may do (appmap.py) are drawn here too. `lang`: the page's language.
  function shell(card, lang, say) {
    const said = card[lang] || card.en;
    const folder = card.type === "folder";
    const own = card.type === "turn_on" || card.type === "setting";
    const node = el("div", "op-card shell-card");
    node.dataset.id = card.id;
    node.append(folder ? cardHead(I.folder, said.title, card.folder)
      : own ? cardHead(card.feature === "programs" ? I.window : I.terminal, said.title)
      : cardHead(I.terminal, said.title));
    // Why the automatic review did not pass it, in one line (shell/panel.py).
    if (said.review) node.append(el("p", "op-card-why", said.review));
    const lines = el("ul", "shell-card-lines");
    for (const line of said.lines || []) lines.append(el("li", "", line));
    if (lines.childElementCount) node.append(lines);
    // An edit's whole difference, indentation kept (activity.js).
    if (card.diff) node.append(window.paActivity.diff(card.diff));
    if (!folder && !own) {
      const facts = el("dl", "op-card-facts");
      facts.append(el("dt", "", say("shellWhere")), el("dd", "", card.cwd));
      node.append(facts);
      const fold = el("details", "shell-card-command");
      fold.append(el("summary", "", say("shellCommand")), el("pre", "", card.command));
      node.append(fold);
    }
    node.append(el("p", "op-card-ask", say("confirmAsk")));
    return node;
  }

  // A step of a task in another program (desk/panel.py) with an effect outside: the program, the window, the
  // control, the exact text or the files, and the window's picture. `kinds`: the chat's names of the steps.
  function desk(card, say, kinds) {
    const node = el("div", "op-card desk-card");
    node.dataset.id = card.id;
    if (String(card.type).startsWith("see_") && (card.text || card.said)) {
      // Working the window by its picture (see/): the app's own sentence, and the picture with the spot ringed.
      node.append(cardHead(I.window, card.said || card.text, card.window));
      // Why the automatic review did not pass it, in one line (desk/panel.py, see/act.py).
      if (card.review) node.append(el("p", "op-card-why", card.review));
      if (card.said && card.text) node.append(el("p", "op-card-quote", card.text));
    } else {
      const kind = kinds[card.kind] || card.kind;
      node.append(cardHead(I.window, say("deskAsk").replace("{program}", card.program).replace("{kind}", kind), card.window));
      if (card.review) node.append(el("p", "op-card-why", card.review));
      const facts = el("dl", "op-card-facts");
      const fact = (key, value, className = "") => {
        if (value) facts.append(el("dt", "", say(key)), el("dd", className, value));
      };
      fact("deskTarget", card.target);
      fact(card.kind === "file" && card.files?.length ? "deskNewName" : "deskText", card.text, "op-card-text");
      fact("deskFiles", (card.files || []).join("\n"), "op-card-text");
      node.append(facts);
    }
    if (card.picture) node.append(shot(card.picture));
    node.append(el("p", "op-card-ask", say("confirmAsk")));
    return node;
  }

  return { shell, desk };
})();
