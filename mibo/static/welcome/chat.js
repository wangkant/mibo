"use strict";
// The chats with the character. The main chat is also where it brings what it found: its
// sentence about the thing, the thing's card under it. A plain chat is only talk. The shell
// makes one view per chat. The column reads quietly: the character's words without bubbles,
// its face, name and time once at the start of each run; the person's words in soft bubbles.
// This file is the view, the composer, sending and the answers to the questions a reply waits on; the thread
// (the questions among it) is drawn by chatthread.js, a find by findcard.js, what rides on a message by attach.js.
window.paChat = (() => {
  const { I, el, button, svg, iconButton, anchor, fill, motion, pressHeaders } = window.paKit;
  const MAIN = "main";
  // Failures that the settings page can fix get a way there.
  const SETTINGS_FIXES = new Set(["key_required", "chat_failed", "model_no_balance", "model_window_small"]);
  // What the character sends on its own is looked for this often while the chat is on screen; in
  // the app's own window it is looked for when the window says a chat changed ("pa-chats"), and
  // only now and then besides.
  const POLL_MS = 3000;
  const TOLD_POLL_MS = 60000;
  // Past the service's own turn budget (three minutes) a reply is not coming: the wait ends.
  const TURN_MS = 200000;
  // The box grows with the text up to this height, then scrolls.
  const INPUT_MAX = 220;
  // Closer to the end than this, the chat counts as read to the end and stays there as it grows.
  const END_PX = 80;
  // A plain chat is named after the first message sent in it, cut to this many characters.
  const TITLE_CLIP = 40;
  const IDEA_ICONS = { main: [I.compass, I.calendar, I.talk], plain: [I.talk, I.calendar, I.help] };
  // Steps that may wait on the person's answer, the reply's own limit drawn out meanwhile: the browser (web/gate.py),
  // a command (shell/panel.py), turning a switched-off ability on (turnon.py), a task in another program
  // (desk/panel.py), one of their MCP servers (mcp_hub.py) and a setting (appmap.py).
  const ASKING_TOOLS = new Set(["operate", "shell", "turn_on", "desk", "mcp", "settings"]);

  function create(id, ctx, hooks) {
    const main = id === MAIN;
    const words = () => paI18n.words("chat");
    // As the shell last read it, so a new chat can be typed in at once; read again on show.
    let state = ctx.state;
    let seen = 0,
      tag = "",
      sending = false,
      // The typing row of the reply being waited for, none while a question waits on the person; their message
      // the reply answers, as drawn.
      waiting = null,
      mine = null,
      // Ends the wait for that reply (the stop button, or past TURN_MS), and the stop's own request.
      cut = null,
      stopping = null,
      // The wait's own limit, drawn out while a step may wait on the person.
      turnLimit = null,
      // The question in the chat waiting on the person (cardwait.py): its ask, with its sentence as `text`. Their
      // next message answers it (answer).
      question = null,
      // The person's answers drawn before the chat kept them, by the question's id.
      answers = new Map(),
      // Messages waiting for the reply on its way to end, in order: {text, quote, files, choices} typed meanwhile, each
      // a row above the box; or their words under a question that were not a yes, drawn already as `node` (with the
      // chat's `seq`), which go first and have no row.
      queue = [],
      // The last reply was stopped or failed: the rows wait for the person, and a message they send goes first.
      paused = false,
      // 立即发送 stopped the reply: the stop does not hold the queue, and the stopped words stay out of the box.
      jumping = false,
      polling = false,
      pollTimer = null,
      loaded = false,
      atEnd = true,
      title = "",
      replying = null,
      dragDepth = 0,
      // A 无痕对话: it reads no memory and leaves none (welcome.py PageChat.private).
      privateChat = false;
    // Pictures behind the page's token, fetched once per view.
    const blobs = new Map();
    const parts = {};

    const displayName = () => state?.name || ctx.name || words().someone;
    const say = (key, name = displayName()) => String(words()[key] ?? words().generic).replaceAll("{name}", name);
    const settingsButton = (className = "pa-btn pa-btn-secondary pa-btn-sm") =>
      button(className, say("settings"), () => ctx.go("setup/model"));
    const visible = () => root.isConnected && !root.closest("[hidden]") && !document.hidden;
    // A reply under way keeps asking out of sight too: a question it waits on stays (cardwait.py) and is there
    // when they come back, and the wait for the reply goes on.
    const asking = () => root.isConnected && (sending || visible());
    const history = (after) =>
      ctx.api(`chat/history?chat=${encodeURIComponent(id)}${after === undefined ? "" : `&after=${after}`}`);
    const blob = (path) => {
      if (!blobs.has(path)) {
        // A picture that failed is not kept as failed: the next ask goes to the server again.
        blobs.set(path, ctx.picture(path).catch((error) => {
          blobs.delete(path);
          throw error;
        }));
      }
      return blobs.get(path);
    };
    const ask = (text) => !sending && send(text);
    // What the link cards and the steps above a reply take from the chat (linkcard.js, activity.js), and the chat
    // they are in, which the app reads their pages for (panels/links.py).
    const links = { chat: id, api: ctx.api, picture: blob, findCard: (card) => finds.card(card), grew: () => keepEnd(), goOn: ask,
      go: ctx.go, confirm: ctx.confirm };

    // ---- The page: the thread, or the empty and not-set-up states, and the composer
    const root = el("div", `chat ${main ? "chat-main" : "chat-plain"}`);
    parts.scroll = el("div", "chat-scroll");
    const column = el("div", "chat-col chat-thread");
    parts.messages = el("div", "chat-messages");
    parts.messages.setAttribute("role", "log");
    column.append(parts.messages);
    parts.scroll.append(column);
    parts.scroll.addEventListener("scroll", () => {
      const box = parts.scroll;
      atEnd = box.scrollHeight - box.scrollTop - box.clientHeight < END_PX;
      finds.closeMenus();
    });

    // No messages yet: the character's bust fading out, a greeting, the composer, three ideas.
    parts.empty = el("div", "chat-empty");
    const emptyCol = el("div", "chat-col");
    const hello = el("div", "chat-hello");
    parts.greet = el("h1");
    parts.emptyText = el("p");
    hello.append(ctx.bust("chat-bust"), parts.greet, parts.emptyText);
    parts.ideas = el("div", "chat-ideas");
    parts.emptySlot = el("div", "chat-empty-slot");
    // A new plain chat can be made a 无痕对话 before its first message; its mark heads the chat.
    parts.privateToggle = button("chat-private-toggle", "", () => setPrivate(!privateChat));
    parts.mark = el("div", "chat-private");
    parts.mark.hidden = true;
    emptyCol.append(hello, parts.emptySlot, parts.ideas, parts.privateToggle);
    parts.empty.append(emptyCol);
    parts.empty.hidden = true;

    // No model yet: said in the middle of the page, with the way to set it up.
    parts.off = el("div", "chat-off");
    parts.off.hidden = true;

    // The composer: two rows at rest, growing with the text; + and send on a row below.
    parts.compose = el("div", "chat-compose");
    parts.banner = el("div", "chat-banner");
    parts.banner.setAttribute("role", "status");
    parts.banner.hidden = true;
    // A file that could not be added, and why: until the next thing is added or it is closed.
    parts.refused = el("div", "chat-refused");
    parts.refused.setAttribute("role", "alert");
    parts.refused.hidden = true;
    // What waits for the reply on its way, a row each.
    parts.queue = el("div", "chat-queue");
    parts.queue.setAttribute("role", "list");
    parts.queue.hidden = true;
    parts.form = el("form", "chat-composer");
    parts.quote = el("div", "chat-composer-quote");
    parts.quote.hidden = true;
    // What is attached, above the text.
    parts.tray = el("div", "chat-tray");
    parts.tray.hidden = true;
    parts.input = el("textarea", "chat-input");
    parts.input.rows = 2;
    const tools = el("div", "chat-tools");
    const attached = window.paAttach.create({ tray: parts.tray, form: parts.form, refused: parts.refused, input: parts.input,
      say, configured: () => Boolean(state?.configured), changed: () => syncSend() });
    parts.picker = el("input");
    parts.picker.type = "file";
    parts.picker.multiple = true;
    parts.picker.hidden = true;
    parts.picker.accept = window.paAttach.ACCEPT;
    parts.picker.addEventListener("change", () => {
      attached.add([...parts.picker.files]);
      parts.picker.value = "";
    });
    // "+": a menu of what can go with a message and what to ask for (plus.js).
    let held = "";
    const plus = window.paPlus.create({
      ctx, main, input: parts.input,
      name: () => displayName(),
      configured: () => Boolean(state?.configured),
      pick: () => parts.picker.click(),
      attach: attached.add, refuse: attached.refuse, flash, attachItem: attached.addItem,
      refresh: () => poll(),
      private: () => privateChat,
      setPrivate,
      quote(text) {
        const block = `${text.trim().split(/\r?\n/).map((line) => `> ${line}`).join("\n")}\n\n`;
        const at = parts.input.selectionStart ?? parts.input.value.length;
        parts.input.setRangeText(block, at, parts.input.selectionEnd ?? at, "end");
        grow();
        parts.input.focus();
      },
      placeholder(text) {
        held = text;
        paintPlaceholder(!parts.empty.hidden);
      },
    });
    parts.plus = plus.button;
    // Beside it, the model's short name, its thinking level and the usage (modelbar.js).
    const bar = window.paModelBar.create({
      ctx, flash,
      pictures: () => Boolean(parts.messages.querySelector(".me-att .pic")),
      tools: () => Boolean(parts.messages.querySelector(".act, .me-choice")),
      // Its context gauge, 立即归纳 and 清空上下文 act on this chat; what they changed shows in the thread.
      chat: id,
      changed: async () => thread.mark((await history(seen)).summary),
    });
    parts.send = el("button", "chat-send");
    parts.send.type = "submit";
    tools.append(parts.plus, bar.node, plus.chips, parts.picker, parts.send);
    parts.form.append(parts.quote, parts.tray, parts.input, tools);
    parts.hint = el("p", "chat-hint");
    parts.compose.append(parts.banner, parts.refused, parts.queue, parts.form, parts.hint);
    // A click on the box's padding still puts the caret in the text.
    parts.form.addEventListener("mousedown", (event) => {
      if (event.target === parts.form || event.target === tools) {
        event.preventDefault();
        parts.input.focus();
      }
    });
    parts.dock = el("div", "chat-dock");
    const dockCol = el("div", "chat-col");
    parts.dock.append(dockCol);
    dockCol.append(parts.compose);
    // Files dragged over the chat: a frame saying they can be let go here.
    parts.dropZone = el("div", "chat-drop");
    root.append(parts.scroll, parts.empty, parts.off, parts.dock, parts.dropZone);

    // A find as this chat draws one (findcard.js); its reply rides on this chat's composer.
    const finds = window.paFindCard.create({ api: ctx.api, picture: blob, say, reply: (card) => setReply(card),
      grew: () => keepEnd(), root });
    const thread = window.paThread.create({ messages: parts.messages, id, say, words, displayName, face: ctx.face,
      picture: blob, attachedText: ctx.attachedText, go: ctx.go, links, findCard: finds.card,
      choices: (list) => plus.sent(list), ask, grew: () => keepEnd(),
      answer: (ident, choice) => question?.id === ident && answer("", choice) });

    const carriesFiles = (event) => Boolean(state?.configured) && [...(event.dataTransfer?.types || [])].includes("Files");
    root.addEventListener("dragenter", (event) => {
      if (!carriesFiles(event)) return;
      event.preventDefault();
      dragDepth += 1;
      root.classList.add("dropping");
    });
    root.addEventListener("dragover", (event) => {
      if (!carriesFiles(event)) return;
      event.preventDefault();
      event.dataTransfer.dropEffect = "copy";
    });
    root.addEventListener("dragleave", (event) => {
      if (!carriesFiles(event)) return;
      dragDepth = Math.max(0, dragDepth - 1);
      if (!dragDepth) root.classList.remove("dropping");
    });
    root.addEventListener("drop", (event) => {
      if (!carriesFiles(event)) return;
      event.preventDefault();
      dragDepth = 0;
      root.classList.remove("dropping");
      attached.add([...event.dataTransfer.files]);
    });
    // A picture pasted from the clipboard; text that comes with it is pasted as text instead.
    parts.input.addEventListener("paste", (event) => {
      const files = [...event.clipboardData.files];
      if (!files.length || event.clipboardData.types.includes("text/plain")) return;
      event.preventDefault();
      attached.add(files);
    });

    parts.input.addEventListener("input", grow);
    parts.input.addEventListener("keydown", (event) => {
      // Enter while an input method is composing picks the word, it does not send.
      if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
        event.preventDefault();
        submit();
      } else if (event.key === "Escape" && sending) {
        event.stopPropagation();
        stopReply("stopped");
      } else if (event.key === "Escape" && replying) {
        event.stopPropagation();
        setReply(null);
      }
    });
    // Enter sends from the box itself: a submit here is the button, which stops a reply on its way when the box is
    // empty, and otherwise sends, queues or answers as Enter does.
    parts.form.addEventListener("submit", (event) => {
      event.preventDefault();
      if (stops()) stopReply("stopped");
      else submit();
    });
    // The page's own listeners, taken off again when the chat is deleted.
    const listeners = {
      visibilitychange: () => {
        if (!asking()) clearTimeout(pollTimer);
        else if (visible()) poll();
      },
      // A look under way may have asked before this change: one more once it is done.
      "pa-chats": function told() {
        if (!visible()) return;
        if (polling || sending) setTimeout(told, 500);
        else poll();
      },
      // A card's own menu closes on any click elsewhere.
      click: (event) => {
        if (!event.target.closest(".find-more-wrap")) finds.closeMenus();
      },
      keydown: (event) => {
        if (event.key === "Escape" && root.querySelector(".find-more-wrap.open")) {
          event.stopPropagation();
          finds.closeMenus();
        }
      },
    };
    for (const [type, run] of Object.entries(listeners)) document.addEventListener(type, run);

    function greeting() {
      const hour = new Date().getHours();
      const part = hour < 5 ? "night" : hour < 11 ? "morning" : hour < 13 ? "noon" : hour < 18 ? "afternoon" : hour < 23 ? "evening" : "night";
      return words().greet[part];
    }

    function renderText() {
      root.lang = paI18n.locale;
      parts.greet.textContent = greeting();
      // A plain chat needs no words of its own: the greeting and the ideas say it.
      parts.emptyText.hidden = !main;
      parts.emptyText.textContent = main ? say("emptyMain") : "";
      // The main chat's ideas may point at its outings; a plain chat's do not.
      const icons = IDEA_ICONS[main ? "main" : "plain"];
      parts.ideas.replaceChildren(
        ...words()[main ? "ideas" : "ideasPlain"].map((idea, index) => {
          const chip = button("chat-idea", "", () => {
            parts.input.value = idea;
            grow();
            parts.input.focus();
          });
          chip.append(svg(icons[index % icons.length]), el("span", "", idea));
          return chip;
        }),
      );
      paintPlaceholder(!parts.empty.hidden);
      parts.input.setAttribute("aria-label", say("send"));
      parts.queue.setAttribute("aria-label", say("queuedList"));
      syncSend();
      paintQueue();
      plus.render();
      bar.render();
      parts.dropZone.textContent = say("dropHere");
      attached.paint();
      for (const name of parts.messages.querySelectorAll(".ai-name")) name.textContent = displayName();
      paintQuote();
      parts.mark.replaceChildren(svg(I.ghost), el("strong", "", say("privateMark")), el("span", "", say("privateNote")));
      parts.privateToggle.replaceChildren(svg(I.ghost), el("span", "", say(privateChat ? "privateLeave" : "privateStart")));
    }

    // Which of the three the page shows: the thread, the empty start, or the way to set a model up.
    function renderSetup() {
      const configured = Boolean(state?.configured);
      parts.off.hidden = configured || !state;
      parts.off.replaceChildren();
      if (!configured && state) {
        const box = el("div", "chat-col chat-off-inner");
        box.append(ctx.bust("chat-bust"), el("h1", "", say("offTitle")), el("p", "", say("offText")),
          settingsButton("pa-btn pa-btn-primary"));
        parts.off.append(box);
      }
      const empty = configured && loaded && !parts.messages.querySelector(".me, .ai, .aside, .chat-error");
      parts.empty.hidden = !empty;
      parts.scroll.hidden = !parts.off.hidden || empty;
      // The one composer moves between the empty start and the dock, text and all.
      // Moved only when it changes place: moving a node takes the focus out of its box.
      const place = empty ? parts.emptySlot : parts.dock.firstChild;
      if (parts.compose.parentNode !== place) place.append(parts.compose);
      parts.dock.hidden = !configured || empty;
      parts.compose.classList.toggle("in-empty", empty);
      // The mark heads the empty start or the thread; the toggle is a plain chat's, before its first message.
      parts.mark.hidden = !privateChat;
      const marked = empty ? emptyCol : column;
      if (parts.mark.parentNode !== marked) marked.prepend(parts.mark);
      parts.privateToggle.hidden = main;
      parts.privateToggle.setAttribute("aria-pressed", String(privateChat));
      paintPlaceholder(empty);
      parts.banner.replaceChildren();
      // The model out of reach; else, in the start after an update, what became of it (updates.outcome).
      const updated = state?.updated;
      parts.banner.hidden = !((configured && state.modelUnreachable) || updated);
      if (configured && state.modelUnreachable)
        parts.banner.append(svg(I.alert), el("span", "chat-banner-text", say("unreachable")),
          settingsButton("pa-btn pa-btn-link chat-banner-link"));
      else if (updated) parts.banner.append(...updateLine(updated));
      parts.banner.classList.toggle("chat-banner-done", Boolean(updated?.ok) && !(configured && state.modelUnreachable));
      syncSend();
    }
    // One line: the version it is now, or that the update did not finish and where the installer is; closed once read.
    function updateLine(updated) {
      const text = fill(updated.ok ? words().updated : words().updateFailed,
        { v: updated.version, current: state.version });
      const line = [svg(updated.ok ? I.seen : I.alert), el("span", "chat-banner-text", text)];
      if (!updated.ok) {
        const page = anchor(updated.url, "pa-btn pa-btn-link chat-banner-link");
        page.textContent = words().releasePage;
        line.push(page);
      }
      line.push(iconButton("chat-banner-close", I.x, words().dismiss, async () => {
        parts.banner.hidden = true;
        await ctx.api("runtime/updated", {}).catch(() => null);
        await refreshState();
      }));
      return line;
    }
    // The box's words at rest: while a question waits on the person, that their reply answers it.
    function paintPlaceholder(empty) {
      parts.input.placeholder = question ? say("confirmAsk") : held || say(empty ? "placeholderEmpty" : "placeholder");
    }
    // While a reply is on its way the send button is the stop button with nothing in the box; with a message in it,
    // it queues the message, or sends the answer to a question waiting on the person.
    const typed = () => Boolean(parts.input.value.trim() || attached.count);
    const stops = () => sending && !(question ? parts.input.value.trim() : typed());
    function syncSend() {
      const stopping = stops();
      if (parts.send.classList.contains("stopping") !== stopping || !parts.send.firstChild) {
        parts.send.classList.toggle("stopping", stopping);
        parts.send.replaceChildren(svg(stopping ? I.stop : I.up));
      }
      const label = say(stopping ? "stop" : sending && !question ? "queue" : "send");
      parts.send.setAttribute("aria-label", label);
      parts.send.title = label;
      parts.send.disabled = !stopping && !question && (!state?.configured || !typed() || !attached.ready());
    }
    function grow() {
      parts.input.style.height = "auto";
      parts.input.style.height = `${Math.min(parts.input.scrollHeight, INPUT_MAX)}px`;
      parts.input.classList.toggle("scrolls", parts.input.scrollHeight > INPUT_MAX);
      syncSend();
    }
    function toBottom() {
      parts.scroll.scrollTop = parts.scroll.scrollHeight;
      atEnd = true;
    }
    // Something above grew after it was drawn: the end stays in sight only if it was.
    const keepEnd = () => atEnd && toBottom();
    // The same when the thread's own box changes size: the window, the chat set beside a page, the box growing.
    new ResizeObserver(keepEnd).observe(parts.scroll);

    // ---- Messages
    // `loading`: drawn as part of a whole history, which reports to the shell once at its end.
    function showMessage(item, arrived = false, loading = false) {
      const node = thread.draw(item);
      // An answer that was not a yes and got no reply (the app restarted, or the page closed before it was sent on) is
      // answered where it stands when sent again.
      const lapsed = item.failed || (loading && !sending && item.answers && item.pending && "interrupted");
      if (item.role === "user" && lapsed)
        failed(node, lapsed, item.text, item.answers ? null : item.seq, item.quote, item.attachments || [],
          item.choices || [], item.answers ? { seq: item.seq, node } : {});
      node.dataset.seq = item.seq || "";
      if (item.ask) asked({ ...item.ask, text: item.text }, true);
      if (arrived) node.classList.add("arrived");
      seen = Math.max(seen, item.seq || 0);
      parts.empty.hidden = true;
      if (loading) return node;
      // The main chat's last words from the character stand in when what it is doing is not known.
      if (main && item.role !== "user" && item.text) hooks.said?.(id, item.text);
      // What arrives on its own does not pull someone reading further up down to it.
      if (arrived) keepEnd();
      else toBottom();
      if (visible()) hooks.seen(id, seen);
      return node;
    }
    // Under a message that went unanswered: why, and a way to send it again.
    // `held`: an answer that was not a yes ({seq, node}), sent again where it stands.
    function failed(mine, code, text, retrySeq = null, quote = null, files = [], choices = [], held = {}) {
      // Stopped by the person: said quietly, with only the way to send it again.
      const quiet = code === "stopped";
      mine.classList.add("unanswered");
      mine.classList.toggle("stopped", quiet);
      const mark = el("small", "msg-mark");
      if (quiet) mark.append(el("span", "", say("stopped")));
      else mark.append(svg(I.alert), el("span", "", say("unanswered")));
      mine.append(mark);
      const note = el("div", quiet ? "notice quiet" : "notice");
      if (!quiet) note.append(bar.problem(code) || el("p", "", say(code)));
      const actions = el("div", "notice-actions");
      actions.append(
        button("pa-btn pa-btn-secondary pa-btn-sm", say("retry"), () => {
          if (sending) return;
          note.remove();
          if (held.seq) {
            mark.remove();
            mine.classList.remove("unanswered", "stopped");
          } else mine.remove();
          send(text, retrySeq, quote, files, choices, held);
        }),
      );
      if (SETTINGS_FIXES.has(code)) actions.append(settingsButton("pa-btn pa-btn-ghost pa-btn-sm"));
      note.append(actions);
      mine.after(note);
      toBottom();
    }
    // What came, shown at once and in order; a question drawn before shows how it now stands.
    function reveal(items) {
      for (const item of items) {
        if (!(item.seq && item.seq <= seen)) {
          if (!adopt(item)) showMessage(item, item.role !== "user");
        } else if (item.ask) asked({ ...item.ask, text: item.text });
      }
    }
    // The marks of a reply being waited for go.
    function stopReveal() {
      for (const node of parts.messages.querySelectorAll(".line.typing")) thread.unline(node);
    }
    function showHistory(value) {
      stopReveal();
      // A video playing in the thread drawn before stops with it, and how long it ran is told.
      for (const node of parts.messages.querySelectorAll(".find.is-playing")) window.paFindCard.stop(node);
      thread.reset();
      seen = 0;
      question = null;
      tag = value.chat || "";
      if (privateChat !== Boolean(value.private)) {
        privateChat = Boolean(value.private);
        renderText();
      }
      for (const item of value.messages) showMessage(item, false, true);
      syncAsk();
      thread.mark(value.summary);
      const said = value.messages.findLast((item) => item.role !== "user" && item.text);
      if (main && said) hooks.said?.(id, said.text);
      seen = Math.max(seen, value.last || 0);
      if (visible()) hooks.seen(id, seen);
      toBottom();
    }
    // A plain chat deleted from another window: the shell lets it go.
    function lost(error) {
      if (error?.message !== "invalid_chat") return false;
      hooks.gone(id);
      return true;
    }

    // ---- Answering one thing it brought: the thing rides on the composer until sent
    function setReply(card) {
      replying = card ? { id: card.id, title: card.title || "", kind: card.kind || "", site: card.site || "", picture: card.picture || "" } : null;
      paintQuote();
      if (card) {
        parts.input.focus();
        keepEnd();
      }
    }
    function paintQuote() {
      parts.quote.hidden = !replying;
      parts.form.classList.toggle("has-quote", Boolean(replying));
      if (!replying) return parts.quote.replaceChildren();
      const line = thread.quoteNode(replying);
      line.setAttribute("aria-label", say("replyTo").replace("{title}", replying.title));
      parts.quote.replaceChildren(line, iconButton("chat-quote-x", I.x, say("cancelReply"), () => {
        setReply(null);
        parts.input.focus();
      }));
    }

    // A 无痕对话, or back to a plain chat: a new chat of that kind opens in its place (app.js).
    function setPrivate(on) {
      ctx.newChat(on);
    }

    // ---- Sending
    function submit() {
      if (question && parts.input.value.trim()) {
        answer(parts.input.value);
        return;
      }
      const text = parts.input.value;
      // A subject for its next walk goes there, not into the chat.
      if (plus.wonder(text)) {
        parts.input.value = "";
        grow();
        return;
      }
      if (!typed() || !state?.configured || !attached.ready()) return;
      if (!bar.allow(submit)) return;
      // Beside a page in the app's browser, the page it is about goes with it (browse.js).
      const message = { text, quote: replying, files: attached.take(),
        choices: [...plus.take(), ...(window.paBeside?.take() || [])] };
      parts.input.value = "";
      setReply(null);
      grow();
      // While a reply is on its way it waits in a row above the box.
      if (sending) {
        queue.push(message);
        paintQueue();
        parts.queue.scrollTop = parts.queue.scrollHeight;
      } else send(message.text, null, message.quote, message.files, message.choices);
    }
    // Their queued messages, a row each: the words on one line, how many attachments go with them, 立即发送 and 移除.
    function paintQueue() {
      const rows = queue.filter((entry) => !entry.node);
      parts.queue.hidden = !rows.length;
      parts.queue.replaceChildren(...rows.map((entry) => {
        const row = el("div", "chat-queue-row");
        row.setAttribute("role", "listitem");
        row.append(el("span", "chat-queue-mark", say("queued")),
          el("span", "chat-queue-text", entry.text.replace(/\s+/g, " ").trim()));
        if (entry.files.length) {
          const files = el("span", "chat-queue-files");
          files.append(svg(I.file), el("span", "", say("queuedFiles").replace("{n}", entry.files.length)));
          row.append(files);
        }
        row.append(button("pa-btn pa-btn-ghost pa-btn-sm chat-queue-now", say("sendNow"), () => sendNow(entry)),
          iconButton("chat-quote-x", I.x, say("unqueue"), () => unqueue(entry)));
        return row;
      }));
    }
    // 立即发送: the reply on its way stops as the stop button stops it, and this message goes next, the rest behind it.
    function sendNow(entry) {
      queue = [entry, ...queue.filter((other) => other !== entry)];
      parts.input.focus();
      if (sending) {
        jumping = true;
        stopReply("stopped");
      } else {
        paused = false;
        sendQueued();
      }
    }
    // A row taken away: its words go back to an empty box, its pictures are let go.
    function unqueue(entry) {
      queue = queue.filter((other) => other !== entry);
      for (const item of entry.files) if (item.url && item.kind !== "page") URL.revokeObjectURL(item.url);
      if (!parts.input.value) {
        parts.input.value = entry.text;
        grow();
      }
      paintQueue();
      parts.input.focus();
    }
    // `held`: words drawn already, {node}; with `seq`, an answer that was not a yes, answered where it stands
    // (workspace.chat `answering`).
    async function send(text, retrySeq = null, quote = null, files = [], choices = [], held = {}) {
      sending = true;
      syncSend();
      // What the character was sending on its own comes back in order with the answer.
      stopReveal();
      mine = held.node || showMessage({ role: "user", text, quote, attachments: files, choices, at: new Date().toISOString() });
      renderSetup();
      // The looks for what it sends on its own say meanwhile what it is looking up.
      waiting = thread.typingRow();
      cut = new AbortController();
      turnLimit = setTimeout(() => stopReply("timeout"), TURN_MS);
      poll();
      // The first message of a plain chat names it: shown at once, and as kept once the list is read again.
      const naming = text.trim() || files.find((item) => item.kind === "file")?.file || "";
      if (!main && !title && naming) hooks.changed(id, Array.from(naming.replace(/\s+/g, " ")).slice(0, TITLE_CLIP).join(""));
      // The reply came: only then does the queue go on by itself.
      let ended = false;
      try {
        // A message sent again after a reload has only its stored attachments: the chat sends those again.
        const attachments = files.filter((item) => item.data).map(({ kind, file, data, url }) =>
          kind === "page" ? { kind, url, title: file } : { kind, name: file, data });
        const value = await ctx.api("chat", { text, after: seen, retry: retrySeq, chat: id, reply_to: quote?.id || "", attachments, choices,
          ...(held.seq ? { answering: held.seq } : {}) }, { signal: cut.signal });
        ended = true;
        for (const item of files) if (item.url) URL.revokeObjectURL(item.url);
        // The chat as recorded: anything sent meanwhile, this message and the reply. Words the chat numbered
        // already stay where they are.
        if (!mine.dataset.seq) mine.remove();
        if (waiting) thread.unline(waiting);
        if (value.forgotLines || value.chat !== tag) showHistory(value.forgotLines ? value : await history());
        else {
          reveal(value.messages);
          thread.mark(value.summary);
        }
      } catch (error) {
        if (waiting) thread.unline(waiting);
        if (lost(error)) return;
        const why = cut.signal.aborted ? String(cut.signal.reason) : "";
        // The service marks the message stopped once its reply has ended; a page process that hangs is not waited for.
        if (why) await Promise.race([stopping, new Promise((done) => setTimeout(done, 5000))]);
        // Stopped: the words go back in the box, to edit and send again.
        if (why === "stopped" && !parts.input.value && !held.seq && !jumping) {
          parts.input.value = text;
          grow();
        }
        // A message the chat kept unanswered shows as kept, so it can be sent again after a reload too.
        let kept = null;
        try {
          kept = await history();
        } catch {
          // Not reachable: the notice below still offers to send it again.
        }
        const last = kept?.messages.findLast((item) => item.role === "user");
        if (last?.failed && last.text === text) showHistory(kept);
        else {
          if (kept) reveal(kept.messages);
          failed(mine, why || (error instanceof TypeError ? "network" : error.message), text, retrySeq, quote, files,
            choices, held);
        }
        if (error.message === "chat_failed") refreshState();
      } finally {
        clearTimeout(turnLimit);
        window.paToolCard.show(null, null);
        // A question of this reply no longer waits once the reply has ended.
        if (question) asked({ ...question, state: "unanswered" });
        cut = stopping = null;
        hooks.doing("");
        sending = false;
        waiting = mine = null;
        paused = !ended && !jumping;
        jumping = false;
        syncSend();
        if (visible()) parts.input.focus();
        if (!main) hooks.changed();
        poll();
        bar.refresh();
        sendQueued();
      }
    }
    // Once a reply has ended: words under its question that were not a yes, answered as the message they are; else,
    // unless the reply was stopped or failed, the first queued message.
    function sendQueued() {
      if (sending) return;
      const next = queue.find((entry) => entry.node) || (!paused && queue[0]);
      if (!next) return;
      queue = queue.filter((entry) => entry !== next);
      paintQueue();
      send(next.text, null, next.quote, next.files, next.choices, next);
    }

    // ---- Answering the question a step waits on (cardwait.py): the person's own words typed in the box, or on a
    // card a press of its buttons, drawn at once as their message. A plain yes runs the step and the reply goes on
    // after it; anything else is a no for that step, and their words are then answered as the message they are. Only
    // this window's page can pass it on (POST /api/confirm, the window's key), by the question's id.
    async function answer(text, choice = null) {
      const asking = question;
      const words = choice ? asking[choice === "yes" ? "act" : "decline"] : text;
      if (!choice) {
        parts.input.value = "";
        grow();
      }
      asked({ ...asking, state: "answering" });
      const said = showMessage({ role: "user", text: words, at: new Date().toISOString() });
      answers.set(asking.id, said);
      let told = {};
      try {
        const response = await fetch("/api/confirm", { method: "POST", credentials: "same-origin", headers: pressHeaders(),
          body: JSON.stringify(choice ? { id: asking.id, choice } : { id: asking.id, text }) });
        told = await response.json();
      } catch {
        // Not reachable: as a question that no longer waits.
      }
      if (told.ok) {
        if (told.seq) adopt({ answers: asking.id, seq: told.seq });
        asked({ ...asking, state: told.yes ? "yes" : "no", at: new Date().toISOString() });
        // The reply goes on after their words.
        if (sending && !waiting && !question) {
          waiting = thread.typingRow();
          keepEnd();
        }
        // Typed words that were not a yes are a message of their own; a press of 不执行 is only the answer.
        // Beside a page, the page it is about goes with it, as with any message.
        if (!told.yes && !choice)
          queue.unshift({ text: words, node: said, seq: told.seq, choices: [...plus.take(), ...(window.paBeside?.take() || [])] });
      } else {
        // The question no longer waits: typed words are the ordinary message they are; a press goes.
        answers.delete(asking.id);
        asked({ ...asking, state: "unanswered" });
        if (choice) said.remove();
        else queue.unshift({ text: words, node: said, choices: [...plus.take(), ...(window.paBeside?.take() || [])] });
      }
      sendQueued();
    }
    // A question as it now stands, drawn so unless `drawn` just now: one waiting on the person is what their next
    // message answers.
    function asked(ask, drawn = false) {
      if (!drawn) thread.settle(ask.text, ask);
      if (ask.state === "waiting") question = ask;
      else if (question?.id === ask.id) question = null;
      syncAsk();
    }
    function syncAsk() {
      paintPlaceholder(!parts.empty.hidden);
      syncSend();
    }
    // Their answer drawn at once is the one the chat kept as number `seq`: drawn once.
    function adopt(item) {
      const node = item.answers && answers.get(item.answers);
      if (!node) return false;
      answers.delete(item.answers);
      node.dataset.seq = item.seq;
      seen = Math.max(seen, item.seq);
      return true;
    }
    // Mid-reply, a question a step waits on and the person's answer join the chat as it keeps them: their request
    // takes its kept place, the question follows it, and the typing row goes until the question is answered.
    function during(items) {
      const fresh = items.filter((item) => item.seq > seen);
      if (!fresh.some((item) => (item.ask && item.ask.state === "waiting") || item.answers)) return;
      if (waiting) thread.unline(waiting);
      waiting = null;
      for (const item of fresh) {
        if (adopt(item)) continue;
        const request = item.role === "user" && !item.answers && item.pending;
        if (request && mine && !mine.dataset.seq) mine.remove();
        const node = showMessage(item);
        if (request) mine = node;
      }
      if (!question) waiting = thread.typingRow();
    }
    // The stop button, Esc, or the wait running past TURN_MS: the service cancels the reply, the page stops waiting.
    function stopReply(why) {
      if (!cut || cut.signal.aborted) return;
      stopping = ctx.api("chat/stop", { chat: id, why }).catch(() => null);
      cut.abort(why);
    }
    let flashTimer = null;
    function flash(text) {
      parts.hint.textContent = text;
      parts.hint.classList.add("flash");
      clearTimeout(flashTimer);
      flashTimer = setTimeout(() => {
        parts.hint.classList.remove("flash");
        parts.hint.textContent = "";
      }, 2500);
    }

    // ---- Looking for what the character sent on its own, and while a reply is on its way, what it is doing
    // While it works: the step under way, and a question it waits on, which joins the chat. Working in the browser
    // takes its time, and a question waits on the person for as long as cardwait.py lets it.
    async function pollStep() {
      const value = await history(seen);
      if (!sending) return;
      during(value.messages);
      const step = value.doing;
      const line = window.paActivity.live(waiting, step);
      if (question || ASKING_TOOLS.has(step?.tool)) {
        clearTimeout(turnLimit);
        turnLimit = setTimeout(() => stopReply("timeout"), TURN_MS);
      }
      // A form one of their MCP servers asks them to fill in is filled in under the typing row (toolcard.js).
      if (step?.tool === "mcp") {
        const card = (await ctx.api("mcp/card")).card;
        window.paToolCard.show(waiting, card?.typed === false ? card : null, keepEnd);
      }
      // The sidebar's line under the character's name says it too (app.js).
      if (sending) hooks.doing(line);
    }
    // Otherwise: what the character sent on its own.
    async function pollMessages() {
      polling = true;
      try {
        const value = await history(seen);
        // A reply that started meanwhile brings these messages itself.
        if (!sending) {
          const was = parts.empty.hidden;
          if (value.chat !== tag) showHistory(await history());
          else {
            reveal(value.messages.filter((item) => item.seq > seen));
            thread.mark(value.summary);
          }
          if (was !== parts.empty.hidden || !parts.empty.hidden) renderSetup();
        }
      } finally {
        polling = false;
      }
    }
    async function poll() {
      clearTimeout(pollTimer);
      if (!asking() || !state?.configured) return;
      if (sending) {
        try {
          await pollStep();
        } catch {
          // The waiting row keeps its dots.
        }
      } else if (!sending && !polling) {
        try {
          await pollMessages();
        } catch (error) {
          // The next look tries again; a lasting problem shows when a message is sent.
          if (lost(error)) return;
        }
      }
      clearTimeout(pollTimer);
      if (asking()) pollTimer = setTimeout(poll, ctx.told && !sending ? TOLD_POLL_MS : POLL_MS);
    }

    async function refreshState() {
      try {
        state = await ctx.api("state");
      } catch {
        // Kept as it was: a failed send says what went wrong.
      }
      bar.refresh();
      // A notice above the composer takes room: the newest message stays in sight.
      const end = atEnd;
      renderText();
      renderSetup();
      if (end) toBottom();
    }

    async function loadHistory() {
      try {
        showHistory(await history());
        loaded = true;
      } catch (error) {
        if (lost(error)) return;
        const note = el("div", "chat-error");
        note.append(el("p", "", say("loadFailed")),
          button("pa-btn pa-btn-secondary pa-btn-sm", say("reload"), async () => {
            note.remove();
            await loadHistory();
            renderSetup();
            poll();
          }));
        parts.messages.replaceChildren(note);
      }
    }

    // ---- Bringing one thing into view, as the pet's card asks
    function flashOn(node) {
      node.scrollIntoView({ block: "center", behavior: motion() });
      atEnd = false;
      // Restart the mark when the same thing is asked for twice in a row.
      node.classList.remove("msg-flash");
      void node.offsetWidth;
      node.classList.add("msg-flash");
      setTimeout(() => node.classList.remove("msg-flash"), 2400);
    }
    const byItem = (item) => [...parts.messages.querySelectorAll(".line[data-item]")].find((n) => n.dataset.item === item);

    renderText();
    renderSetup();
    let showing = null;
    return {
      node: root,
      show() {
        showing = (async () => {
          await refreshState();
          if (!loaded) {
            await loadHistory();
            renderSetup();
          }
          toBottom();
          if (visible()) hooks.seen(id, seen);
          // A new chat waits for words, so its box takes the focus; a thread opens at rest,
          // and the first key typed puts the caret in the box (app.js).
          if (state?.configured && visible() && !parts.empty.hidden) parts.input.focus();
          poll();
        })();
        return showing;
      },
      // The main chat's message carrying library item `item`: the one there, or one the character sends now.
      async bring(item, shown = showing) {
        await shown;
        let node = byItem(item);
        if (!node) {
          let seq;
          try {
            ({ seq } = await ctx.api("chat/bring", { id: item }));
          } catch {
            // Gone from the library: the chat stays as it is.
            return;
          }
          // Shown at once, not typed out: the person asked for it.
          stopReveal();
          try {
            const value = await history(seen);
            if (value.chat !== tag) showHistory(await history());
            else for (const message of value.messages) if (message.seq > seen) showMessage(message);
          } catch {
            return;
          }
          renderSetup();
          node = parts.messages.querySelector(`[data-seq="${seq}"]`) || byItem(item);
        }
        if (node) flashOn(node);
      },
      title(text) {
        title = text;
      },
      // A suggestion or a goto may fill the box from outside.
      focus() {
        if (state?.configured) parts.input.focus();
      },
      // A find drawn as this chat draws one, for the 推荐记录 list (finds.js): its reply goes to this chat.
      findCard: (card) => finds.card(card),
      drop() {
        clearTimeout(pollTimer);
        for (const [type, run] of Object.entries(listeners)) document.removeEventListener(type, run);
        plus.drop();
        bar.drop();
        root.remove();
        for (const url of blobs.values()) url.then((value) => URL.revokeObjectURL(value)).catch(() => {});
        attached.drop();
        // Queued messages go with the view, unsent.
        for (const entry of queue) for (const item of entry.files || []) if (item.url) URL.revokeObjectURL(item.url);
      },
    };
  }

  return { create };
})();
