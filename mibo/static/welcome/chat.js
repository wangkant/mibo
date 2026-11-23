"use strict";
// The chats with the character. The main chat is also where it brings what it found: its
// sentence about the thing, the thing's card under it. A plain chat is only talk. The shell
// makes one view per chat. The column reads quietly: the character's words without bubbles,
// its face, name and time once at the start of each run; the person's words in soft bubbles.
// This file is the view, the composer, sending and the questions a reply waits on; the thread is drawn
// by chatthread.js, a find by findcard.js, what rides on a message by attach.js.
window.paChat = (() => {
  const { I, el, button, svg, iconButton, motion } = window.paKit;
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
  // Where a step waits on the person's yes: a command (shell/panel.py), turning a switched-off ability on
  // (turnon.py), a task in another program (desk/panel.py), one of their MCP servers (mcp_hub.py, toolcard.js),
  // a setting (appmap.py), or the browser (web/gate.py).
  const ASK_ROUTES = { operate: "browser/confirm", shell: "shell/card", turn_on: "turnon/card",
    desk: "programs/card", mcp: "mcp/card", settings: "settings/card" };

  function create(id, ctx, hooks) {
    const main = id === MAIN;
    const words = () => paI18n.words("chat");
    // As the shell last read it, so a new chat can be typed in at once; read again on show.
    let state = ctx.state;
    let seen = 0,
      tag = "",
      sending = false,
      // The typing row of the reply being waited for.
      waiting = null,
      // Ends the wait for that reply (the stop button, or past TURN_MS), and the stop's own request.
      cut = null,
      stopping = null,
      // The wait's own limit, drawn out while the character works in the browser; the card it waits on.
      turnLimit = null,
      // The cards answered beside the page this chat has a line for.
      noted = new Set(),
      shellCard = null,
      deskCard = null,
      // The step waiting in the chat for the person's yes (cardwait.py): its id, which the next message answers;
      // a message that was not a yes, sent as an ordinary message once the reply has ended.
      awaitingYes = null,
      queued = null,
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
    // A reply under way keeps asking out of sight too: a card it waits on stays (cardwait.py) and is there when
    // they come back, and the wait for the reply goes on.
    const asking = () => root.isConnected && (sending || visible());
    const history = (after) =>
      ctx.api(`chat/history?chat=${encodeURIComponent(id)}${after === undefined ? "" : `&after=${after}`}`);
    const blob = (path) => {
      if (!blobs.has(path)) blobs.set(path, ctx.picture(path));
      return blobs.get(path);
    };
    const ask = (text) => !sending && send(text);
    // What the link cards and the steps above a reply take from the chat (linkcard.js, activity.js).
    const links = { api: ctx.api, picture: blob, findCard: (card) => finds.card(card), grew: () => keepEnd(), goOn: ask,
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
        parts.input.placeholder = text || say(parts.empty.hidden ? "placeholder" : "placeholderEmpty");
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
    parts.compose.append(parts.banner, parts.refused, parts.form, parts.hint);
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
      choices: (list) => plus.sent(list), ask, grew: () => keepEnd() });

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
    // Enter sends from the box itself: a submit here is the button, which stops a reply on its way, or answers the
    // step waiting for the person's yes when they typed something.
    parts.form.addEventListener("submit", (event) => {
      event.preventDefault();
      if (sending && !(awaitingYes && parts.input.value.trim())) stopReply("stopped");
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
      parts.input.placeholder = say(parts.empty.hidden ? "placeholder" : "placeholderEmpty");
      parts.input.setAttribute("aria-label", say("send"));
      parts.send.setAttribute("aria-label", say(sending ? "stop" : "send"));
      parts.send.title = say(sending ? "stop" : "send");
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
      parts.input.placeholder = held || say(empty ? "placeholderEmpty" : "placeholder");
      parts.banner.replaceChildren();
      parts.banner.hidden = !(configured && state.modelUnreachable);
      if (!parts.banner.hidden)
        parts.banner.append(svg(I.alert), el("span", "chat-banner-text", say("unreachable")),
          settingsButton("pa-btn pa-btn-link chat-banner-link"));
      syncSend();
    }
    // While a reply is on its way the send button is the stop button, unless a step waits for the person's yes
    // and they have typed their answer.
    function syncSend() {
      const stops = sending && !(awaitingYes && parts.input.value.trim());
      if (parts.send.classList.contains("stopping") !== stops || !parts.send.firstChild) {
        parts.send.classList.toggle("stopping", stops);
        parts.send.replaceChildren(svg(stops ? I.stop : I.up));
        parts.send.setAttribute("aria-label", say(stops ? "stop" : "send"));
        parts.send.title = say(stops ? "stop" : "send");
      }
      parts.send.disabled = !sending && (!state?.configured || !(parts.input.value.trim() || attached.count) ||
        !attached.ready());
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
      if (item.role === "user" && item.failed)
        failed(node, item.failed, item.text, item.seq, item.quote, item.attachments || [], item.choices || []);
      node.dataset.seq = item.seq || "";
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
    function failed(mine, code, text, retrySeq = null, quote = null, files = [], choices = []) {
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
          mine.remove();
          send(text, retrySeq, quote, files, choices);
        }),
      );
      if (SETTINGS_FIXES.has(code)) actions.append(settingsButton("pa-btn pa-btn-ghost pa-btn-sm"));
      note.append(actions);
      mine.after(note);
      toBottom();
    }
    // What came, shown at once and in order.
    function reveal(items) {
      for (const item of items) if (!(item.seq && item.seq <= seen)) showMessage(item, item.role !== "user");
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
      tag = value.chat || "";
      if (privateChat !== Boolean(value.private)) {
        privateChat = Boolean(value.private);
        renderText();
      }
      for (const item of value.messages) showMessage(item, false, true);
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
      if (sending && awaitingYes && parts.input.value.trim()) {
        answerAsk(parts.input.value);
        return;
      }
      if (sending) {
        // The text stays in the box: say why Enter did nothing.
        flash(say("wait"));
        return;
      }
      const text = parts.input.value;
      // A subject for its next walk goes there, not into the chat.
      if (plus.wonder(text)) {
        parts.input.value = "";
        grow();
        return;
      }
      if (!(text.trim() || attached.count) || !state?.configured || !attached.ready()) return;
      if (!bar.allow(submit)) return;
      const quote = replying;
      const files = attached.take();
      parts.input.value = "";
      setReply(null);
      grow();
      // Beside a page in the app's browser, the page it is about goes with it (browse.js).
      send(text, null, quote, files, [...plus.take(), ...(window.paBeside?.take() || [])]);
    }
    async function send(text, retrySeq = null, quote = null, files = [], choices = []) {
      sending = true;
      syncSend();
      // What the character was sending on its own comes back in order with the answer.
      stopReveal();
      const mine = showMessage({ role: "user", text, quote, attachments: files, choices, at: new Date().toISOString() });
      renderSetup();
      const typing = thread.typingRow();
      // The looks for what it sends on its own say meanwhile what it is looking up.
      waiting = typing;
      cut = new AbortController();
      turnLimit = setTimeout(() => stopReply("timeout"), TURN_MS);
      poll();
      // The first message of a plain chat names it: shown at once, and as kept once the list is read again.
      const naming = text.trim() || files.find((item) => item.kind === "file")?.file || "";
      if (!main && !title && naming) hooks.changed(id, Array.from(naming.replace(/\s+/g, " ")).slice(0, TITLE_CLIP).join(""));
      try {
        // A message sent again after a reload has only its stored attachments: the chat sends those again.
        const attachments = files.filter((item) => item.data).map(({ kind, file, data, url }) =>
          kind === "page" ? { kind, url, title: file } : { kind, name: file, data });
        const value = await ctx.api("chat", { text, after: seen, retry: retrySeq, chat: id, reply_to: quote?.id || "", attachments, choices },
          { signal: cut.signal });
        for (const item of files) if (item.url) URL.revokeObjectURL(item.url);
        // The chat as recorded: anything sent meanwhile, this message and the reply.
        mine.remove();
        thread.unline(typing);
        if (value.forgotLines || value.chat !== tag) showHistory(value.forgotLines ? value : await history());
        else {
          reveal(value.messages);
          thread.mark(value.summary);
        }
      } catch (error) {
        thread.unline(typing);
        if (lost(error)) return;
        const why = cut.signal.aborted ? String(cut.signal.reason) : "";
        // The service marks the message stopped once its reply has ended; a page process that hangs is not waited for.
        if (why) await Promise.race([stopping, new Promise((done) => setTimeout(done, 5000))]);
        // Stopped: the words go back in the box, to edit and send again.
        if (why === "stopped" && !parts.input.value) {
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
        const last = kept?.messages.at(-1);
        if (last && last.role === "user" && last.failed && last.text === text) showHistory(kept);
        else failed(mine, why || (error instanceof TypeError ? "network" : error.message), text, retrySeq, quote, files, choices);
        if (error.message === "chat_failed") refreshState();
      } finally {
        clearTimeout(turnLimit);
        showCard(null);
        showShellCard(null);
        showDeskCard(null);
        window.paToolCard.show(null, null);
        awaitingYes = null;
        cut = stopping = null;
        hooks.doing("");
        sending = false;
        waiting = null;
        syncSend();
        if (visible()) parts.input.focus();
        if (!main) hooks.changed();
        poll();
        bar.refresh();
        // What they typed while a step waited, which was not a yes, is the message it is.
        if (queued) {
          const next = queued;
          queued = null;
          send(next);
        }
      }
    }
    // The person's own words typed in the chat box, under the step waiting for their yes (cardwait.py): a plain yes
    // runs it; anything else is a no for that step, and the message is sent as it is once the reply has ended. Only
    // this window's page can pass it on (POST /api/confirm).
    async function answerAsk(text) {
      const ident = awaitingYes;
      awaitingYes = null;
      parts.input.value = "";
      grow();
      const told = el("p", "op-note", "");
      (shellCard || deskCard || waiting).after(told);
      keepEnd();
      try {
        const response = await fetch("/api/confirm", {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json",
            "X-Mibo-Setup-Token": sessionStorage.getItem("mibo-setup-token") || "",
            "X-Mibo-Window": sessionStorage.getItem("mibo-frame") || "" },
          body: JSON.stringify({ id: ident, text }),
        });
        const said = await response.json().catch(() => ({}));
        if (said.ok && said.yes) told.textContent = say("confirmYes").replace("{text}", text.trim());
        else {
          told.textContent = say(said.ok ? "confirmNo" : "opGone");
          queued = text;
        }
      } catch {
        told.textContent = say("opGone");
        queued = text;
      }
      for (const node of [shellCard, deskCard]) node?.classList.add("answered");
    }
    // Something with an effect outside (web/gate.py) is shown in the column beside the page (browse.js) and waits
    // for the person's yes typed in the chat (answerAsk): here the waiting row says so, and once it is answered one
    // line keeps what was decided.
    function showCard(card, answered = null) {
      if (!waiting) return;
      const label = waiting.querySelector(".doing");
      if (card && label) label.textContent = say("opWaitingPage");
      if (!answered || noted.has(answered.id)) return;
      noted.add(answered.id);
      waiting.before(el("p", "op-note", answered.said));
      keepEnd();
    }
    // A question card (askcards.js) under the waiting row, whose words now say it waits for the person.
    function hang(node) {
      waiting.after(node);
      const label = waiting.querySelector(".doing");
      if (label) label.textContent = say("opWaiting");
      keepEnd();
      return node;
    }
    // A step before a command runs on this computer, or turning an ability or a setting on; answered by the
    // person's yes typed in the chat box (answerAsk), never the model's words.
    function showShellCard(card) {
      if (shellCard && (!card || shellCard.dataset.id !== card.id)) {
        if (!shellCard.classList.contains("answered")) shellCard.remove();
        shellCard = null;
      }
      if (!card || shellCard || !waiting) return;
      shellCard = hang(window.paAskCards.shell(card, ctx.lang, say));
    }
    // A step of a task in another program with an effect outside; answered the same way.
    function showDeskCard(card) {
      if (deskCard && (!card || deskCard.dataset.id !== card.id)) {
        if (!deskCard.classList.contains("answered")) deskCard.remove();
        deskCard = null;
      }
      if (!card || deskCard || !waiting) return;
      deskCard = hang(window.paAskCards.desk(card, say, words().deskKinds));
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
    // While it works: the step under way, and the question it waits on, if any. Working in the browser takes its
    // time, and a step may wait on the person's yes.
    async function pollStep() {
      const step = (await history(seen)).doing;
      const line = window.paActivity.live(waiting, step);
      const place = ASK_ROUTES[step?.tool];
      if (place && sending) {
        clearTimeout(turnLimit);
        turnLimit = setTimeout(() => stopReply("timeout"), TURN_MS);
        const asked = await ctx.api(place);
        if (step.tool === "operate") showCard(asked.card, asked.answered);
        else if (step.tool === "desk") showDeskCard(asked.card);
        else if (step.tool === "mcp") window.paToolCard.show(waiting, asked.card, keepEnd);
        else showShellCard(asked.card);
        // A server's form is filled in on the page; every other step is answered in the chat box.
        const id = asked.card && asked.card.typed !== false ? asked.card.id : null;
        if (id !== awaitingYes && !(awaitingYes === null && id && noted.has(`asked:${id}`))) {
          awaitingYes = id;
          if (id) noted.add(`asked:${id}`);
          syncSend();
        }
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
      if (sending && waiting) {
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
      },
    };
  }

  return { create };
})();
