"use strict";
// A chat's thread as it is drawn: a line for each new day, the character's words in runs with its face, name and
// time once at the start of each, the questions a step waits on among them, the person's words in soft bubbles with
// what they attached, the quiet remarks, the line where older turns became a checkpoint, and the typing row while a
// reply is on its way. The chat (chat.js) makes one of these per chat view and keeps what was sent and seen.
window.paThread = (() => {
  const { el, button, fill } = window.paKit;
  // The character's messages further apart than this start a new run, with its name and time again.
  const RUN_GAP_MS = 10 * 60 * 1000;
  // A card shows this many of its step's lines in sight; the rest are under its fold.
  const CARD_LINES = 5;

  // An ISO time, or epoch seconds (remarks keep those) or milliseconds.
  const when = (at) => {
    const time = typeof at === "number" ? (at < 1e12 ? at * 1000 : at) : at ? new Date(at).getTime() : NaN;
    return Number.isFinite(time) && time > 0 ? time : 0;
  };
  const dayKey = (time) => {
    const d = new Date(time);
    return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
  };
  const timeOf = (time) =>
    new Date(time).toLocaleTimeString(paI18n.locale, paI18n.lang === "en" ? { hour: "numeric", minute: "2-digit" } : { hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
  const stamp = (time, className = "") => {
    const node = el("time", className, timeOf(time));
    node.dateTime = new Date(time).toISOString();
    return node;
  };
  const isRemark = (item) => item.remark === true || item.kind === "remark";
  // A thing brought with no sentence of its own is said by its title: not twice.
  function saysTitle(text, card) {
    const words = String(text || "").replace(/[…\s.]+$/, "");
    return !words || (card.title || "").startsWith(words) || text === card.url;
  }

  // `env`: messages (the thread's box), id (the chat's), say(key), words() (the chat's words), displayName(), face(),
  // picture(path) giving a blob address, attachedText(path), go(place), links (what the link cards and the steps
  // take from the chat), findCard(card), choices(list) for a message's choices, ask(text) to send a message from
  // under a reply, answer(id, choice) for a card's button, grew() when something grew after it was drawn.
  function create(env) {
    const { messages, say, links } = env;
    // Where the thread was last drawn to: the day, and the character's open run of messages; and when the
    // checkpoint or the cleared mark the thread shows was written (welcome.py PageChat.summary).
    let lastDay = "",
      run = null,
      marked = 0;
    const linkCards = (text, skip = "") => window.paLinks.cards(window.paLinks.urls(text, [skip]), links);

    function reset() {
      messages.replaceChildren();
      lastDay = "";
      run = null;
      marked = 0;
    }
    // A new day gets its line before its first message.
    function separate(time) {
      if (!time || dayKey(time) === lastDay) return;
      lastDay = dayKey(time);
      const line = el("div", "day", window.paKit.dayLabel(time, env.words()));
      line.setAttribute("role", "separator");
      messages.append(line);
    }
    // The open run of the character's messages, or a new one with its face, name and time.
    function botRun(time) {
      const open =
        run && run.node === messages.lastElementChild &&
        (!time || !run.last || (dayKey(time) === dayKey(run.last) && time - run.last < RUN_GAP_MS));
      if (open) {
        if (time) run.last = time;
        return run.body;
      }
      const node = el("section", "ai");
      const body = el("div", "ai-body");
      const meta = el("div", "ai-meta");
      meta.append(el("span", "ai-name", env.displayName()));
      if (time) meta.append(stamp(time, "ai-time"));
      body.append(meta);
      node.append(env.face("ai-face"), body);
      messages.append(node);
      run = { node, body, last: time };
      return body;
    }
    // A line taken out of a run: a run left with nothing in it goes too.
    function unline(node) {
      const section = node.closest(".ai");
      node.remove();
      if (section && !section.querySelector(".line")) {
        section.remove();
        if (run?.node === section) run = null;
      }
    }

    function pictureGone(holder) {
      holder.classList.remove("loading", "pa-shimmer");
      holder.classList.add("gone");
      holder.textContent = say("pictureGone");
    }
    async function showPicture(holder, name, alt = say("picture")) {
      try {
        const url = name.startsWith("blob:") ? name : await env.picture(`/api/chat/picture/${encodeURIComponent(name)}`);
        const image = el("img");
        image.alt = alt;
        image.addEventListener("load", env.grew, { once: true });
        image.src = url;
        holder.classList.remove("loading", "pa-shimmer");
        holder.replaceChildren(image);
      } catch {
        pictureGone(holder);
      }
    }
    function pictureNode(item) {
      const holder = el("div", "pic loading pa-shimmer");
      if (item.picture) showPicture(holder, item.picture);
      else pictureGone(holder);
      return holder;
    }
    // What the person attached, above their words: pictures as they are, files as chips that open.
    function attachedNode(list) {
      const box = el("div", "me-att");
      for (const item of list) {
        if (item.kind === "picture") {
          const holder = el("div", "pic loading pa-shimmer");
          showPicture(holder, item.url || item.name, say("myPicture"));
          box.append(holder);
          continue;
        }
        // A page from the app's browser opens the way every link opens.
        if (item.kind === "page") {
          const link = window.paPlus.pageChip(item, "a");
          link.href = item.url;
          link.target = "_blank";
          link.rel = "noopener noreferrer";
          box.append(link);
          continue;
        }
        const node = el("div", "att-sent");
        // Stored ones open: those of a message still on its way have no name yet.
        const head = item.name ? button("att att-file", "", () => showFile(node, head, item.name)) : el("div", "att att-file");
        head.append(window.paAttach.fileWords(item, say));
        if (item.name) {
          head.setAttribute("aria-expanded", "false");
          head.setAttribute("aria-label", `${say("showFile")}: ${item.file}`);
        }
        node.append(head);
        box.append(node);
      }
      return box;
    }
    async function showFile(node, head, name) {
      const open = head.getAttribute("aria-expanded") !== "true";
      head.setAttribute("aria-expanded", String(open));
      node.querySelector(".att-text")?.remove();
      if (!open) return;
      const text = el("pre", "att-text pa-shimmer");
      node.append(text);
      try {
        text.textContent = await env.attachedText(`/api/chat/file/${encodeURIComponent(name)}`);
      } catch {
        text.classList.add("gone");
        text.textContent = say("fileGone");
      }
      text.classList.remove("pa-shimmer");
    }
    // A find quoted at the head of the person's bubble: a rule, its picture, its title.
    function quoteNode(quote) {
      const node = el("div", "quote");
      if (quote.picture) {
        const thumb = el("span", "quote-thumb");
        const img = el("img");
        img.alt = "";
        env.picture(quote.picture)
          .then((url) => {
            img.src = url;
          })
          .catch(() => thumb.remove());
        thumb.append(img);
        node.append(thumb);
      }
      node.append(el("span", "quote-title", quote.title || quote.site || ""));
      return node;
    }

    function userNode(item) {
      const node = el("section", "me");
      if (item.attachments?.length) node.append(attachedNode(item.attachments));
      const bubble = el("div", "bubble");
      if (item.quote) {
        bubble.classList.add("has-quote");
        bubble.append(quoteNode(item.quote));
      }
      if (item.picture !== undefined) bubble.append(pictureNode(item));
      else if (item.text) bubble.append(window.paChatText.linked(el("span", "bubble-text"), item.text, links));
      // Attachments alone need no empty bubble under them.
      if (bubble.firstChild) node.append(bubble);
      const sent = item.picture === undefined && linkCards(item.text);
      if (sent) node.append(sent);
      if (item.choices?.length) node.append(env.choices(item.choices));
      // Longer than the model reads at once: it read the head and the tail (dm._cut_message).
      if (item.cut) node.append(el("small", "msg-mark msg-cut", say("cut")));
      node.dataset.at = item.at || "";
      return node;
    }
    // A very important step's question (cardwait.ALONE): its sentence with the decisive facts, its first lines in
    // sight and the rest under a fold, and two buttons, the act in the app's words and the one that declines. Once
    // answered it keeps what was decided and when, with no buttons.
    function askCard(item) {
      const ask = item.ask;
      const w = paI18n.words("ask");
      const node = el("div", "ask-card");
      node.append(el("p", "ask-card-text", item.text));
      const lines = ask.detail?.lines || [];
      if (lines.length) {
        const list = el("ul", "ask-card-lines");
        for (const line of lines.slice(0, CARD_LINES)) list.append(el("li", "", line));
        node.append(list);
      }
      const fold = window.paActivity.asked({ ...ask, detail: { ...ask.detail, lines: lines.slice(CARD_LINES) } },
        { picture: (name) => pictureNode({ picture: name }), grew: env.grew });
      if (fold) node.append(fold);
      if (ask.state === "waiting" || ask.state === "answering") {
        const row = el("div", "ask-card-buttons");
        row.append(button("pa-btn pa-btn-primary pa-btn-sm", ask.act, () => env.answer(ask.id, "yes")),
          button("pa-btn pa-btn-secondary pa-btn-sm", ask.decline, () => env.answer(ask.id, "no")));
        for (const press of row.children) press.disabled = ask.state === "answering";
        node.append(row);
      } else if (ask.state !== "left") {
        // A browser act left waiting may still be answered by the next message beside the page: no line yet.
        node.classList.add("answered");
        const time = when(ask.at);
        node.append(el("p", "ask-card-told", fill(w[ask.state] || w.unanswered, { time: time ? timeOf(time) : "" })));
      }
      return node;
    }
    // A question as it now stands (state "answering" while the answer is on its way): its card drawn again.
    function settle(text, ask) {
      const card = messages.querySelector(`.line[data-ask="${CSS.escape(ask.id)}"] > .ask-card`);
      if (card) card.replaceWith(askCard({ text, ask }));
    }

    // One of the character's messages, a line in `body` (its run).
    function replyLine(item, body) {
      const node = el("div", "line");
      // What it did for the reply, above its words (activity.js): above the first of them when it said several.
      const did = window.paActivity.summary(item, links);
      const first = did && body.querySelector(":scope > .line:not(.typing)");
      if (first) first.before(did);
      else if (did) node.append(did);
      // A question a step waits on is the app's own sentence, as plain text; a very important one is a card.
      if (item.ask) {
        node.dataset.ask = item.ask.id;
        if (item.ask.tier === "card") node.append(askCard(item));
        else {
          node.append(el("p", "say", item.text));
          if (item.ask.detail?.picture) node.append(pictureNode({ picture: item.ask.detail.picture }));
          const fold = window.paActivity.asked(item.ask, { grew: env.grew });
          if (fold) node.append(fold);
        }
        body.append(node);
        return node;
      }
      // A line that is only an address is said by its card.
      const words = window.paChatText.wordsOf(item.text);
      if (item.picture !== undefined) node.append(pictureNode(item));
      else if (!(item.card && saysTitle(item.text, item.card)) && words) node.append(window.paChatText.sayNode(words, links, say));
      const cards = item.picture === undefined && linkCards(item.text, item.card?.url);
      if (cards) node.append(cards);
      const from = window.paActivity.sources(item.sources, links);
      if (from) node.append(from);
      // The memories the reply drew on, each with edit and forget (activity.js).
      const recalled = window.paActivity.recalled(item, links);
      if (recalled) node.append(recalled);
      // The files the reply changed, with 撤销这次的改动 (activity.js).
      const changed = window.paActivity.changes(item, links);
      if (changed) node.append(changed);
      // Under the answer to a memory command, the way to Settings › Memory (welcome.py marks its last line).
      if (item.manage) node.append(button("pa-btn pa-btn-link chat-manage", say("manageMemory"), () => env.go("setup/memory")));
      if (item.card) {
        node.classList.add("has-find");
        node.append(env.findCard(item.card));
        if (item.card.id) node.dataset.item = item.card.id;
      }
      // A scheduled task's mark, what the reply did to tasks, and what a run left for them (schedulechat.js).
      window.paScheduleChat.decorate(node, item, env.ask);
      body.append(node);
      return node;
    }
    // A message drawn at the thread's end, after its day's line if it starts a day; the node drawn.
    function draw(item) {
      const time = when(item.at);
      separate(time);
      if (item.role === "user") {
        const node = userNode(item);
        messages.append(node);
        return node;
      }
      if (item.role === "memory") {
        // What the background memory kept from this chat: one quiet line under the last reply (activity.js).
        const node = window.paActivity.saved(item, links);
        const last = messages.lastElementChild;
        (last?.classList.contains("ai") ? last.querySelector(".ai-body") : messages).append(node);
        return node;
      }
      if (isRemark(item)) {
        // A passing remark: no face, quieter, on the text's edge.
        const node = el("p", "aside");
        node.append(el("span", "", item.text));
        if (time) node.append(stamp(time));
        messages.append(node);
        return node;
      }
      return replyLine(item, botRun(time));
    }

    function typingRow() {
      const body = botRun(Date.now());
      const node = el("div", "line typing");
      const dots = el("span", "dots");
      dots.setAttribute("role", "status");
      dots.setAttribute("aria-label", say("typing"));
      dots.append(el("i"), el("i"), el("i"));
      // While a reply is on its way: what the character is looking up for it.
      node.append(dots, el("span", "doing"));
      body.append(node);
      env.grew();
      return node;
    }

    // Where the chat's older turns became its checkpoint, one quiet line before the first message the model still
    // reads whole, with the checkpoint's text under it on request; where its context was cleared, the line it left.
    // Drawn again only when a new one was written.
    function mark(summary) {
      if ((summary?.at || 0) === marked) return;
      marked = summary?.at || 0;
      messages.querySelector(":scope > .chat-compacted")?.remove();
      if (!summary) return;
      const node = el("div", "chat-compacted");
      const line = el("p", "chat-compacted-line");
      line.append(el("span", "", say(summary.cleared ? "contextCleared" : "compacted")));
      node.append(line);
      if (!summary.cleared) {
        const text = el("div", "chat-summary", summary.text);
        text.hidden = true;
        text.id = `chat-summary-${env.id}`;
        const open = button("pa-btn pa-btn-link", say("showSummary"), () => {
          text.hidden = !text.hidden;
          open.textContent = say(text.hidden ? "showSummary" : "collapse");
          open.setAttribute("aria-expanded", String(!text.hidden));
          if (!text.hidden) env.grew();
        });
        open.setAttribute("aria-expanded", "false");
        open.setAttribute("aria-controls", text.id);
        line.append(open);
        node.append(text);
      }
      // The first turn the model still reads whole was heard at "from" (dm.py), and the page keeps its messages'
      // times to the second: after a checkpoint, the last of their messages sent by then; after a clear, the first
      // sent after it.
      const mine = [...messages.querySelectorAll(":scope > .me[data-at]")];
      const from = summary.from * 1000;
      const first = summary.cleared ? mine.find((one) => Date.parse(one.dataset.at) > from)
        : mine.findLast((one) => Date.parse(one.dataset.at) <= from);
      if (first) first.before(node);
      else {
        messages.append(node);
        env.grew();
      }
    }

    return { reset, draw, unline, typingRow, quoteNode, mark, settle };
  }

  return { create };
})();
