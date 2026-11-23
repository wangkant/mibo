"use strict";
// 推荐记录: every find the character put in front of the person (the pet's card, the main chat, the first
// run), newest first under a line for each day, and beside it the ones they liked. Each is drawn as the main
// chat draws a find (findcard.js), so liking, replying, playing and 不感兴趣 work as they do there; the
// list reads GET /api/feed a page at a time as it is scrolled.
window.paFinds = (() => {
  const { el, dayLabel } = window.paKit;
  const PAGE = 20;
  const TABS = ["all", "kept"];

  // `main`: card(find) draws a find as the main chat does; reply() opens the main chat, where a reply goes.
  function create(ctx, main) {
    const words = () => paI18n.words("finds");
    const say = (key) => String(words()[key]).replaceAll("{name}", ctx.name || words().someone);

    const root = el("div", "chat finds");
    const scroll = el("div", "chat-scroll");
    const col = el("div", "chat-col finds-col");
    const head = el("header", "finds-head");
    const title = el("h1", "finds-title");
    const tabs = el("div", "setup-segments finds-tabs");
    tabs.setAttribute("role", "radiogroup");
    const buttons = TABS.map((key) => {
      const button = el("button", "setup-segment");
      button.type = "button";
      button.dataset.tab = key;
      button.setAttribute("role", "radio");
      button.addEventListener("click", () => pick(key));
      return button;
    });
    tabs.append(...buttons);
    head.append(title, tabs);
    const list = el("div", "chat-messages finds-list");
    list.setAttribute("role", "feed");
    const note = el("div", "finds-note");
    note.hidden = true;
    // Coming into sight near the bottom, it asks for the next page.
    const end = el("div", "finds-end");
    col.append(head, list, note, end);
    scroll.append(col);
    root.append(scroll);

    let tab = "all";
    let next = "";
    let loading = false;
    let lastDay = "";
    // Each fresh load counts up, so a page asked for before a tab change is dropped when it comes.
    let turn = 0;

    const ahead = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting) && next && !loading) load(false);
      },
      { root: scroll, rootMargin: "600px 0px" },
    );
    ahead.observe(end);

    function pick(key) {
      if (key === tab) return;
      tab = key;
      paint();
      scroll.scrollTop = 0;
      load(true);
    }

    function paint() {
      title.textContent = say("title");
      tabs.setAttribute("aria-label", say("tabs"));
      for (const button of buttons) {
        button.textContent = say(button.dataset.tab);
        button.setAttribute("aria-checked", String(button.dataset.tab === tab));
      }
    }

    async function load(first) {
      const mine = first ? ++turn : turn;
      const before = first ? "" : next;
      loading = true;
      let value;
      try {
        value = await ctx.api(`feed?limit=${PAGE}&kept=${tab === "kept"}${before ? `&before=${encodeURIComponent(before)}` : ""}`);
      } catch {
        if (mine !== turn) return;
        loading = false;
        if (first) {
          list.replaceChildren();
          lastDay = "";
          tell("failed");
        }
        return;
      }
      if (mine !== turn) return;
      if (first) {
        list.replaceChildren();
        lastDay = "";
      }
      for (const card of value.items) add(card);
      next = value.next || "";
      loading = false;
      tell(first && !value.items.length ? (tab === "kept" ? "emptyKept" : "empty") : "");
      // The end may still be in sight after a short page: looked at again, it asks for the next one.
      ahead.unobserve(end);
      ahead.observe(end);
    }

    function add(card) {
      const day = new Date(card.at).toDateString();
      if (day !== lastDay) {
        lastDay = day;
        const line = el("div", "day", dayLabel(card.at, words()));
        line.setAttribute("role", "separator");
        list.append(line);
      }
      const line = el("div", "line has-find");
      line.append(main.card(card));
      list.append(line);
    }

    // Nothing to show, or the list could not be read: one quiet note in the column.
    function tell(what) {
      note.hidden = !what;
      if (!what) return note.replaceChildren();
      if (what === "failed") {
        const retry = el("button", "pa-btn pa-btn-secondary pa-btn-sm", say("retry"));
        retry.type = "button";
        retry.addEventListener("click", () => load(true));
        note.replaceChildren(el("p", "finds-note-text", say("failed")), retry);
        return;
      }
      note.replaceChildren(el("h2", "finds-note-title", say(what)), el("p", "finds-note-text", say(`${what}Text`)));
    }

    // A reply to a find is written in the main chat: its box takes the find, and the chat comes up.
    root.addEventListener("click", (event) => {
      if (event.target.closest(".reply-btn")) main.reply();
    });
    // A card's menu closes on a click elsewhere or on Escape, as in the chat.
    const shut = () => window.paFindCard.closeMenus(root);
    document.addEventListener("click", (event) => {
      if (!event.target.closest(".find-more-wrap")) shut();
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && root.querySelector(".find-more-wrap.open")) {
        event.stopPropagation();
        shut();
      }
    });
    scroll.addEventListener("scroll", shut);

    return {
      node: root,
      // Read afresh each time it is opened: what was shown since comes first.
      show() {
        paint();
        return load(true);
      },
    };
  }

  return { create };
})();
