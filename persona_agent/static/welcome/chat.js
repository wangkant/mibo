"use strict";
// The chats with the character. The main chat is also where it brings what it found: its
// sentence about the thing, the thing's card under it. A plain chat is only talk. The shell
// makes one view per chat. The column reads quietly: the character's words without bubbles,
// its face, name and time once at the start of each run; the person's words in soft bubbles.
window.paChat = (() => {
  const WORDS = {
    zh: {
      someone: "你的角色",
      newChat: "新对话",
      placeholder: "回复 {name}…",
      placeholderEmpty: "和 {name} 说点什么…",
      send: "发送",
      hint: "Enter 发送 · Shift + Enter 换行",
      greet: {
        night: "夜深了，想聊点什么？",
        morning: "早上好，想聊点什么？",
        noon: "中午好，想聊点什么？",
        afternoon: "下午好，想聊点什么？",
        evening: "晚上好，想聊点什么？",
      },
      emptyText: "这里只用于聊天，角色带回的内容在主对话中。",
      emptyMain: "{name}外出发现你可能喜欢的内容时，会发到这里。你也可以直接聊天。",
      ideas: ["你今天出门看到了什么？", "帮我理一理明天要做的事", "给我推荐点轻松的东西"],
      ideasPlain: ["陪我随便聊聊", "帮我理一理明天要做的事", "有个问题想请教你"],
      offTitle: "还没有连接模型",
      offText: "设置模型密钥后，{name}就能和你聊天。",
      unreachable: "无法连接到模型服务。请检查密钥和网络。",
      settings: "打开设置",
      retry: "重新发送",
      unanswered: "未送达",
      typing: "{name}正在输入",
      picture: "{name}发来的图片",
      pictureGone: "图片已不存在",
      wait: "请等待当前回复完成后再发送。",
      loadFailed: "无法读取聊天记录。请稍后重试。",
      reload: "重试",
      trimmed: "更早的消息未保留",
      today: "今天",
      yesterday: "昨天",
      week: ["周日", "周一", "周二", "周三", "周四", "周五", "周六"],
      reply: "回复",
      replyTo: "回复：{title}",
      cancelReply: "取消回复",
      like: "喜欢",
      liked: "已喜欢",
      open: "在浏览器打开",
      more: "更多",
      skip: "不感兴趣",
      less: "少看此来源",
      play: "播放",
      collapse: "收起",
      skipped: "已收起，以后将减少此类内容。",
      lessDone: "以后将减少此来源的内容。",
      key_required: "还没有设置模型密钥。",
      chat_failed: "模型没有回应。可能是密钥失效、额度用完或网络不通。",
      agent_failed: "角色服务未能启动。请稍后重试。",
      invalid_message: "消息过长。请分几次发送。",
      network: "无法连接到本机的 personagent，它可能已退出。",
      generic: "发送失败。请重试。",
    },
    en: {
      someone: "your character",
      newChat: "New chat",
      placeholder: "Reply to {name}…",
      placeholderEmpty: "Say something to {name}…",
      send: "Send",
      hint: "Enter to send · Shift + Enter for a new line",
      greet: {
        night: "Up late? What's on your mind?",
        morning: "Good morning. What's on your mind?",
        noon: "Good afternoon. What's on your mind?",
        afternoon: "Good afternoon. What's on your mind?",
        evening: "Good evening. What's on your mind?",
      },
      emptyText: "Just talk here. What it brings back goes to the main chat.",
      emptyMain: "When {name} comes across something you might like, it sends it here. You can talk here too.",
      ideas: ["What did you see out today?", "Help me sort out tomorrow", "Show me something light"],
      ideasPlain: ["Just chat with me for a bit", "Help me sort out tomorrow", "I have a question for you"],
      offTitle: "No model connected yet",
      offText: "Set a model key and {name} can start talking with you.",
      unreachable: "The model service cannot be reached. Check the key and the network.",
      settings: "Open settings",
      retry: "Send again",
      unanswered: "Not delivered",
      typing: "{name} is typing",
      picture: "A picture from {name}",
      pictureGone: "This picture is no longer here",
      wait: "Wait for this reply to finish first.",
      loadFailed: "The chat could not be loaded. Try again in a moment.",
      reload: "Try again",
      trimmed: "Earlier messages were not kept",
      today: "Today",
      yesterday: "Yesterday",
      week: null,
      reply: "Reply",
      replyTo: "Replying to: {title}",
      cancelReply: "Cancel reply",
      like: "Like",
      liked: "Liked",
      open: "Open in browser",
      more: "More",
      skip: "Not interested",
      less: "Less from this source",
      play: "Play",
      collapse: "Collapse",
      skipped: "Folded away. It will bring back less like this.",
      lessDone: "Got it. Less from this source from now on.",
      key_required: "No model key is set yet.",
      chat_failed: "The model did not answer. The key may be invalid or out of credit, or the network is down.",
      agent_failed: "The character's service did not start. Try again in a moment.",
      invalid_message: "This message is too long. Send it in parts.",
      network: "personagent on this computer cannot be reached. It may have quit.",
      generic: "Not sent. Try again.",
    },
  };
  const MAIN = "main";
  // Failures that the settings page can fix get a way there.
  const SETTINGS_FIXES = new Set(["key_required", "chat_failed"]);
  // A reply arrives the way a person sends it: one message at a time, each after
  // about the time it takes to type, with the typing mark in between.
  const TYPING = { perChar: 120, pause: 350, most: 2400, whole: 8000 };
  // What the character sends on its own is looked for this often while the chat is on screen; in
  // the app's own window it is looked for when the window says a chat changed ("pa-chats"), and
  // only now and then besides.
  const POLL_MS = 3000;
  const TOLD_POLL_MS = 60000;
  // The box grows with the text up to this height, then scrolls.
  const INPUT_MAX = 220;
  // Closer to the end than this, the chat counts as read to the end and stays there as it grows.
  const END_PX = 80;
  // A plain chat is named after the first message sent in it, cut to this many characters.
  const TITLE_CLIP = 40;
  // The character's messages further apart than this start a new run, with its name and time again.
  const RUN_GAP_MS = 10 * 60 * 1000;
  const SVG = "http://www.w3.org/2000/svg";
  // Lucide-style strokes.
  const I = {
    up: '<path d="M12 19V5M5 12l7-7 7 7"/>',
    reply: '<path d="M9 17l-5-5 5-5"/><path d="M20 18v-2a4 4 0 0 0-4-4H4"/>',
    heart:
      '<path d="M19 14c1.49-1.46 3-3.21 3-5.5A5.5 5.5 0 0 0 16.5 3c-1.76 0-3 .5-4.5 2-1.5-1.5-2.74-2-4.5-2A5.5 5.5 0 0 0 2 8.5c0 2.3 1.5 4.05 3 5.5l7 7z"/>',
    open: '<path d="M15 3h6v6"/><path d="M10 14 21 3"/><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>',
    more: '<circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/><circle cx="5" cy="12" r="1"/>',
    tv: '<rect x="2" y="7" width="20" height="15" rx="2"/><path d="m17 2-5 5-5-5"/>',
    video: '<rect x="2" y="4" width="20" height="16" rx="4"/><path d="m10 9 5 3-5 3z"/>',
    file: '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M16 13H8M16 17H8M10 9H8"/>',
    branch: '<path d="M6 3v12"/><circle cx="18" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M18 9a9 9 0 0 1-9 9"/>',
    post: '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
    globe: '<circle cx="12" cy="12" r="10"/><path d="M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20"/><path d="M2 12h20"/>',
    shrink: '<path d="m14 10 7-7"/><path d="M20 10h-6V4"/><path d="m3 21 7-7"/><path d="M4 14h6v6"/>',
    x: '<path d="M18 6 6 18M6 6l12 12"/>',
    skip: '<circle cx="12" cy="12" r="10"/><path d="m15 9-6 6M9 9l6 6"/>',
    less: '<circle cx="12" cy="12" r="10"/><path d="M8 12h8"/>',
    alert: '<circle cx="12" cy="12" r="10"/><path d="M12 8v4M12 16h.01"/>',
    talk: '<path d="M7.9 20A9 9 0 1 0 4 16.1L2 22z"/>',
    calendar: '<rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/>',
    compass: '<circle cx="12" cy="12" r="10"/><path d="m16.24 7.76-2.12 6.36-6.36 2.12 2.12-6.36z"/>',
    help: '<circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><path d="M12 17h.01"/>',
  };
  const YOUTUBE = ["www.youtube-nocookie.com", "www.youtube.com", "youtube.com", "youtube-nocookie.com"];

  // Seconds a player has run: from YouTube's own state changes once it sends them
  // (asked to with "listening"), else the time it has been on the page.
  function playClock(frame, origin) {
    let total = 0;
    let since = performance.now();
    let heard = false;
    const hear = (event) => {
      if (event.source !== frame.contentWindow) return;
      let said;
      try {
        said = JSON.parse(event.data);
      } catch {
        return;
      }
      const state = said?.event === "onStateChange" ? said.info : said?.info?.playerState;
      if (typeof state !== "number") return;
      const now = performance.now();
      // From its first word on, only the time it says it plays counts.
      if (!heard) {
        heard = true;
        since = null;
      }
      if (state === 1) since ??= now;
      else if (since !== null) {
        total += now - since;
        since = null;
      }
    };
    if (origin) {
      addEventListener("message", hear);
      // Asked until it answers, as YouTube's own API does: its player is ready a little after its page.
      frame.addEventListener("load", () => {
        let tries = 0;
        const ask = setInterval(() => {
          if (heard || ++tries > 40 || !frame.isConnected) return clearInterval(ask);
          frame.contentWindow.postMessage(JSON.stringify({ event: "listening", id: 1, channel: "widget" }), origin);
        }, 250);
      });
    }
    return {
      seconds: () => Math.min(86400, (total + (since === null ? 0 : performance.now() - since)) / 1000),
      stop: () => removeEventListener("message", hear),
    };
  }
  // The videos playing in place in any chat, each with its way to tell the feed how long it has run.
  // Told when it is folded away, scrolled out of view or the page is put away; the feed keeps the longest.
  const players = new Map();
  const tellAll = () => players.forEach((tell) => tell());
  const offView = new IntersectionObserver((entries) => {
    for (const entry of entries) if (!entry.isIntersecting) players.get(entry.target)?.();
  });
  document.addEventListener("visibilitychange", () => document.hidden && tellAll());
  addEventListener("pagehide", tellAll);
  const IDEA_ICONS = { main: [I.compass, I.calendar, I.talk], plain: [I.talk, I.calendar, I.help] };
  const PLAY = '<path d="M7 4.5v15a1 1 0 0 0 1.5.86l12.5-7.5a1 1 0 0 0 0-1.72L8.5 3.64A1 1 0 0 0 7 4.5z"/>';

  function el(tag, className = "", text = "") {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text) node.textContent = text;
    return node;
  }
  function button(className, text, run) {
    const node = el("button", className, text);
    node.type = "button";
    node.addEventListener("click", run);
    return node;
  }
  function svg(paths, className = "i") {
    const node = document.createElementNS(SVG, "svg");
    node.setAttribute("viewBox", "0 0 24 24");
    node.setAttribute("aria-hidden", "true");
    node.setAttribute("class", className);
    node.innerHTML = paths;
    return node;
  }
  // A button holding only an icon, named for screen readers and on hover.
  function iconButton(className, paths, label, run) {
    const node = button(className, "", run);
    node.append(svg(paths));
    node.setAttribute("aria-label", label);
    node.title = label;
    return node;
  }
  const motion = () => (matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth");
  // An ISO time, or epoch seconds (remarks keep those) or milliseconds.
  const when = (at) => {
    const time = typeof at === "number" ? (at < 1e12 ? at * 1000 : at) : at ? new Date(at).getTime() : NaN;
    return Number.isFinite(time) && time > 0 ? time : 0;
  };
  const dayKey = (time) => {
    const d = new Date(time);
    return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
  };
  const hostOf = (url) => {
    try {
      return new URL(url).hostname.replace(/^www\./, "");
    } catch {
      return "";
    }
  };
  // A video's length as a player shows it.
  function clock(seconds) {
    const s = Math.round(seconds);
    const two = (n) => String(n).padStart(2, "0");
    const h = Math.floor(s / 3600);
    return h ? `${h}:${two(Math.floor((s % 3600) / 60))}:${two(s % 60)}` : `${Math.floor(s / 60)}:${two(s % 60)}`;
  }
  // One quiet icon for where a thing is from; only the cover carries colour.
  function siteIcon(card) {
    const host = hostOf(card.url);
    if (/(^|\.)(github\.com|gitlab\.com|gitee\.com|codeberg\.org)$/.test(host)) return I.branch;
    if (card.kind === "video") return /bilibili|b23\.tv/.test(host) ? I.tv : I.video;
    if (card.kind === "article") return I.file;
    if (card.kind === "post") return I.post;
    return I.globe;
  }

  function create(id, ctx, hooks) {
    const main = id === MAIN;
    const words = () => WORDS[ctx.lang];
    const locale = () => (ctx.lang === "zh" ? "zh-CN" : "en");
    // As the shell last read it, so a new chat can be typed in at once; read again on show.
    let state = ctx.state;
    let seen = 0,
      tag = "",
      sending = false,
      polling = false,
      pollTimer = null,
      epoch = 0,
      loaded = false,
      atEnd = true,
      title = "",
      replying = null;
    // Where the thread was last drawn to: the day, and the character's open run of messages.
    let lastDay = "",
      run = null;
    // Pictures behind the page's token, fetched once per view.
    const blobs = new Map();
    const parts = {};

    const displayName = () => state?.name || ctx.name || words().someone;
    const say = (key, name = displayName()) => String(words()[key] ?? words().generic).replaceAll("{name}", name);
    const settingsButton = (className = "pa-btn pa-btn-secondary pa-btn-sm") =>
      button(className, say("settings"), () => ctx.go("setup/model"));
    const visible = () => root.isConnected && !root.closest("[hidden]") && !document.hidden;
    const history = (after) =>
      ctx.api(`chat/history?chat=${encodeURIComponent(id)}${after === undefined ? "" : `&after=${after}`}`);
    const blob = (path) => {
      if (!blobs.has(path)) blobs.set(path, ctx.picture(path));
      return blobs.get(path);
    };

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
      closeMenus();
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
    emptyCol.append(hello, parts.emptySlot, parts.ideas);
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
    parts.form = el("form", "chat-composer");
    parts.quote = el("div", "chat-composer-quote");
    parts.quote.hidden = true;
    parts.input = el("textarea", "chat-input");
    parts.input.rows = 2;
    const tools = el("div", "chat-tools");
    parts.send = el("button", "chat-send");
    parts.send.type = "submit";
    parts.send.append(svg(I.up));
    tools.append(parts.send);
    parts.form.append(parts.quote, parts.input, tools);
    parts.hint = el("p", "chat-hint");
    parts.compose.append(parts.banner, parts.form, parts.hint);
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
    root.append(parts.scroll, parts.empty, parts.off, parts.dock);

    parts.input.addEventListener("input", grow);
    parts.input.addEventListener("keydown", (event) => {
      // Enter while an input method is composing picks the word, it does not send.
      if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
        event.preventDefault();
        submit();
      } else if (event.key === "Escape" && replying) {
        event.stopPropagation();
        setReply(null);
      }
    });
    parts.form.addEventListener("submit", (event) => {
      event.preventDefault();
      submit();
    });
    // The page's own listeners, taken off again when the chat is deleted.
    const listeners = {
      visibilitychange: () => {
        if (document.hidden) clearTimeout(pollTimer);
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
        if (!event.target.closest(".find-more-wrap")) closeMenus();
      },
      keydown: (event) => {
        if (event.key === "Escape" && root.querySelector(".find-more-wrap.open")) {
          event.stopPropagation();
          closeMenus();
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
      root.lang = locale();
      parts.greet.textContent = greeting();
      parts.emptyText.textContent = say(main ? "emptyMain" : "emptyText");
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
      parts.send.setAttribute("aria-label", say("send"));
      parts.send.title = say("send");
      for (const name of parts.messages.querySelectorAll(".ai-name")) name.textContent = displayName();
      if (!parts.hint.classList.contains("flash")) parts.hint.textContent = say("hint");
      paintQuote();
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
      parts.input.placeholder = say(empty ? "placeholderEmpty" : "placeholder");
      parts.banner.replaceChildren();
      parts.banner.hidden = !(configured && state.modelUnreachable);
      if (!parts.banner.hidden)
        parts.banner.append(svg(I.alert), el("span", "chat-banner-text", say("unreachable")),
          settingsButton("pa-btn pa-btn-link chat-banner-link"));
      syncSend();
    }
    function syncSend() {
      parts.send.disabled = !state?.configured || sending || !parts.input.value.trim();
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

    // ---- The thread's frame: days, and the character's runs
    function dayLabel(time) {
      const date = new Date(time);
      const start = (d) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
      const back = Math.round((start(new Date()) - start(date)) / 86400000);
      const year = date.getFullYear() !== new Date().getFullYear();
      const day = words().week
        ? `${year ? `${date.getFullYear()}年` : ""}${date.getMonth() + 1}月${date.getDate()}日 ${words().week[date.getDay()]}`
        : date.toLocaleDateString("en", { weekday: "short", month: "short", day: "numeric", ...(year ? { year: "numeric" } : {}) });
      const near = back === 0 ? words().today : back === 1 ? words().yesterday : "";
      return near ? `${near} · ${day}` : day;
    }
    const timeOf = (time) =>
      new Date(time).toLocaleTimeString(locale(), ctx.lang === "zh" ? { hour: "2-digit", minute: "2-digit", hourCycle: "h23" } : { hour: "numeric", minute: "2-digit" });
    // A new day gets its line before its first message.
    function separate(time) {
      if (!time || dayKey(time) === lastDay) return;
      lastDay = dayKey(time);
      const line = el("div", "day", dayLabel(time));
      line.setAttribute("role", "separator");
      parts.messages.append(line);
    }
    // The open run of the character's messages, or a new one with its face, name and time.
    function botRun(time) {
      const open =
        run && run.node === parts.messages.lastElementChild &&
        (!time || !run.last || (dayKey(time) === dayKey(run.last) && time - run.last < RUN_GAP_MS));
      if (open) {
        if (time) run.last = time;
        return run.body;
      }
      const node = el("section", "ai");
      const body = el("div", "ai-body");
      const meta = el("div", "ai-meta");
      meta.append(el("span", "ai-name", displayName()));
      if (time) {
        const stamp = el("time", "ai-time", timeOf(time));
        stamp.dateTime = new Date(time).toISOString();
        meta.append(stamp);
      }
      body.append(meta);
      node.append(ctx.face("ai-face"), body);
      parts.messages.append(node);
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

    // ---- Messages
    const isRemark = (item) => item.remark === true || item.kind === "remark";
    async function showPicture(holder, name) {
      try {
        const url = await blob(`/api/chat/picture/${encodeURIComponent(name)}`);
        const image = el("img");
        image.alt = say("picture");
        image.addEventListener("load", keepEnd, { once: true });
        image.src = url;
        holder.classList.remove("loading", "pa-shimmer");
        holder.replaceChildren(image);
      } catch {
        holder.classList.remove("loading", "pa-shimmer");
        holder.classList.add("gone");
        holder.textContent = say("pictureGone");
      }
    }
    function pictureNode(item) {
      const holder = el("div", "pic loading pa-shimmer");
      if (item.picture) showPicture(holder, item.picture);
      else {
        holder.classList.remove("loading", "pa-shimmer");
        holder.classList.add("gone");
        holder.textContent = say("pictureGone");
      }
      return holder;
    }
    // A thing brought with no sentence of its own is said by its title: not twice.
    function saysTitle(text, card) {
      const words = String(text || "").replace(/[…\s.]+$/, "");
      return !words || (card.title || "").startsWith(words) || text === card.url;
    }
    // `loading`: drawn as part of a whole history, which reports to the shell once at its end.
    function showMessage(item, arrived = false, loading = false) {
      const time = when(item.at);
      separate(time);
      let node;
      if (item.role === "user") {
        node = el("section", "me");
        const bubble = el("div", "bubble");
        if (item.quote) {
          bubble.classList.add("has-quote");
          bubble.append(quoteNode(item.quote));
        }
        if (item.picture !== undefined) bubble.append(pictureNode(item));
        else bubble.append(el("span", "bubble-text", item.text));
        node.append(bubble);
        parts.messages.append(node);
        if (item.failed) failed(node, item.failed, item.text, item.seq, item.quote);
      } else if (isRemark(item)) {
        // A passing remark: no face, quieter, on the text's edge.
        node = el("p", "aside");
        node.append(el("span", "", item.text));
        if (time) {
          const stamp = el("time", "", timeOf(time));
          stamp.dateTime = new Date(time).toISOString();
          node.append(stamp);
        }
        parts.messages.append(node);
      } else {
        const body = botRun(time);
        node = el("div", "line");
        if (item.picture !== undefined) node.append(pictureNode(item));
        else if (!(item.card && saysTitle(item.text, item.card))) node.append(el("p", "say", item.text));
        if (item.card) {
          node.classList.add("has-find");
          node.append(findCard(item.card));
          if (item.card.id) node.dataset.item = item.card.id;
        }
        body.append(node);
      }
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
    // A find quoted at the head of the person's bubble: a rule, its picture, its title.
    function quoteNode(quote) {
      const node = el("div", "quote");
      if (quote.picture) {
        const thumb = el("span", "quote-thumb");
        const img = el("img");
        img.alt = "";
        blob(quote.picture)
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
    // Under a message that went unanswered: why, and a way to send it again.
    function failed(mine, code, text, retrySeq = null, quote = null) {
      mine.classList.add("unanswered");
      const mark = el("small", "msg-mark");
      mark.append(svg(I.alert), el("span", "", say("unanswered")));
      mine.append(mark);
      const note = el("div", "notice");
      note.append(el("p", "", say(code)));
      const actions = el("div", "notice-actions");
      actions.append(
        button("pa-btn pa-btn-secondary pa-btn-sm", say("retry"), () => {
          if (sending) return;
          note.remove();
          mine.remove();
          send(text, retrySeq, quote);
        }),
      );
      if (SETTINGS_FIXES.has(code)) actions.append(settingsButton("pa-btn pa-btn-ghost pa-btn-sm"));
      note.append(actions);
      mine.after(note);
      toBottom();
    }
    function typingRow() {
      const body = botRun(Date.now());
      const node = el("div", "line typing");
      const dots = el("span", "dots");
      dots.setAttribute("role", "status");
      dots.setAttribute("aria-label", say("typing"));
      dots.append(el("i"), el("i"), el("i"));
      node.append(dots);
      body.append(node);
      keepEnd();
      return node;
    }
    function typingTime(item) {
      if (item.picture !== undefined) return 700;
      if (isRemark(item)) return 0;
      const length = Array.from(item.text || "").length;
      return Math.min(TYPING.most, length * TYPING.perChar + TYPING.pause);
    }
    // `spent`: how long the first message has already been waited for.
    async function reveal(items, spent = 0) {
      const mine = epoch;
      let left = TYPING.whole;
      for (const item of items) {
        if (item.seq && item.seq <= seen) continue;
        if (item.role === "user") {
          showMessage(item);
          continue;
        }
        // A memory command's answer is a record, not talk: it comes whole at once.
        const time = item.command ? 0 : Math.min(left, Math.max(0, typingTime(item) - spent));
        spent = 0;
        if (time > 0) {
          const typing = typingRow();
          await new Promise((done) => setTimeout(done, time));
          unline(typing);
          left -= time;
          if (mine !== epoch) return;
          if (item.seq && item.seq <= seen) continue;
        }
        showMessage(item, true);
      }
    }
    // A reply still arriving stops; what it had not shown comes with the next look.
    function stopReveal() {
      epoch += 1;
      for (const node of parts.messages.querySelectorAll(".line.typing")) unline(node);
    }
    function showHistory(value) {
      stopReveal();
      // A video playing in the thread drawn before stops with it, and how long it ran is told.
      for (const node of parts.messages.querySelectorAll(".find.is-playing")) {
        node.querySelector(".player").remove();
        players.get(node)?.();
      }
      parts.messages.replaceChildren();
      lastDay = "";
      run = null;
      seen = 0;
      tag = value.chat || "";
      if (value.trimmed && value.messages.length) parts.messages.append(el("p", "chat-trimmed", say("trimmed")));
      for (const item of value.messages) showMessage(item, false, true);
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

    // ---- A thing it brought: a 16:10 cover beside a body laid to its height, a fixed foot
    function findCard(card) {
      const node = el("article", "find");
      if (card.skipped) return folded(node, card.skipped === "hide_source" ? "lessDone" : "skipped");
      const site = String(card.site || "").replace(/^www\./, "") || hostOf(card.url);
      const video = card.kind === "video" && card.embed;
      const cover = video ? el("div", "cover") : original(card, "cover");
      if (!video) {
        cover.tabIndex = -1;
        cover.setAttribute("aria-hidden", "true");
      }
      if (card.picture) {
        const img = el("img");
        img.alt = "";
        img.decoding = "async";
        cover.classList.add("pa-shimmer");
        img.addEventListener("load", () => cover.classList.remove("pa-shimmer"), { once: true });
        blob(card.picture)
          .then((url) => {
            img.src = url;
          })
          .catch(() => {
            // A picture that does not arrive leaves the quiet cover, not a broken frame.
            img.remove();
            cover.classList.remove("pa-shimmer");
            cover.classList.add("blank");
            cover.append(svg(siteIcon(card), "i cover-mark"));
          });
        cover.append(img);
      } else {
        cover.classList.add("blank");
        cover.append(svg(siteIcon(card), "i cover-mark"));
      }
      if (video) {
        const play = button("play", "", () => playIn(node, card));
        play.setAttribute("aria-label", `${say("play")}: ${card.title || site}`);
        play.append(svg(PLAY, "play-mark"));
        cover.append(play);
        if (card.length) cover.append(el("span", "dur", clock(card.length)));
      }

      const body = el("div", "find-body");
      const top = el("div", "find-top");
      const icon = el("span", "site");
      icon.append(svg(siteIcon(card)));
      top.append(icon, el("span", "src", site));
      if (card.author && card.author !== site) top.append(el("span", "dot", "·"), el("span", "by", card.author));
      const heading = el("h3");
      const link = original(card, "find-title");
      link.textContent = card.title || site;
      heading.append(link);
      body.append(top, heading);
      if (card.excerpt) body.append(el("p", "find-text", card.excerpt));

      // The cover and the site's icon already say what kind it is: the foot says only how old.
      const foot = el("div", "find-foot");
      if (card.at) {
        const stamp = el("time", "", ago(card.at));
        stamp.dateTime = card.at;
        stamp.title = new Date(card.at).toLocaleString(locale());
        foot.append(stamp);
      }
      foot.append(actions(card, node));
      body.append(foot);
      node.append(cover, body);
      return node;
    }
    // The player is put in place only when asked: an embedded player is heavy
    // and would start talking to its site as soon as it loads.
    function playIn(node, card) {
      const player = el("div", "player");
      const frame = el("iframe");
      const src = new URL(card.embed);
      src.searchParams.set("autoplay", "1");
      // YouTube's player says when it plays and pauses, once asked to.
      const youtube = YOUTUBE.includes(src.hostname);
      // The origin tells the player where to send its replies, as YouTube's own API does.
      if (youtube) {
        src.searchParams.set("enablejsapi", "1");
        src.searchParams.set("origin", location.origin);
      }
      const ran = playClock(frame, youtube ? src.origin : "");
      frame.src = src.href;
      frame.title = card.title || "";
      frame.allow = "autoplay; encrypted-media; picture-in-picture; fullscreen";
      // The page itself sends no referrer; without one YouTube refuses to play (its error 153).
      frame.referrerPolicy = "strict-origin-when-cross-origin";
      // Each telling carries the whole time so far, so only a second more than last time is told;
      // once the player is gone (收起, folded, the chat redrawn) it is told for the last time.
      let told = 0;
      players.set(node, () => {
        const seconds = ran.seconds();
        // Kept alive: the last telling may come as the window closes.
        if (seconds - told >= 1) react(card, "play", { play_s: Math.round(seconds * 10) / 10 }, { keepalive: true });
        told = Math.max(told, seconds);
        if (frame.isConnected) return;
        ran.stop();
        players.delete(node);
        offView.unobserve(node);
      });
      offView.observe(node);
      // 收起 sits on the card's own line under the video, never over the site's player.
      const close = button("player-close", "", () => {
        player.remove();
        close.remove();
        players.get(node)?.();
        node.classList.remove("is-playing");
        node.querySelector(".play")?.focus();
      });
      close.append(svg(I.shrink), el("span", "", say("collapse")));
      player.append(frame);
      node.prepend(player);
      node.querySelector(".find-top").append(close);
      node.classList.add("is-playing");
      keepEnd();
      // Watching it in place is the video's way of opening it.
      react(card, "open");
    }
    function original(card, className) {
      const link = el("a", className);
      link.href = card.url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.addEventListener("click", () => react(card, "open"));
      return link;
    }
    function actions(card, node) {
      const row = el("span", "acts");
      // Only a thing from the library can be answered or reacted to; anything can be opened.
      if (card.id) {
        const reply = button("reply-btn", "", () => setReply(card));
        reply.append(svg(I.reply), el("span", "", say("reply")));
        const like = iconButton("icon-btn like", I.heart, say("like"), async () => {
          const liked = !card.liked;
          setLiked(like, card, liked);
          if (liked) {
            like.classList.remove("pop");
            void like.offsetWidth;
            like.classList.add("pop");
          }
          try {
            await ctx.api("feed/react", reaction(card, liked ? "like" : "unlike"));
          } catch {
            setLiked(like, card, !liked);
          }
        });
        setLiked(like, card, Boolean(card.liked));
        row.append(reply, like);
      }
      const open = original(card, "icon-btn");
      open.append(svg(I.open));
      open.setAttribute("aria-label", say("open"));
      open.title = say("open");
      row.append(open);
      if (card.id) row.append(moreMenu(card, node));
      return row;
    }
    // Not interested, less from the source: kept a click away behind ⋯.
    function moreMenu(card, node) {
      const wrap = el("span", "find-more-wrap");
      const menu = el("div", "find-menu");
      menu.setAttribute("role", "menu");
      const item = (paths, text, kind) => {
        const choice = button("", "", () => {
          closeMenus();
          fold(card, node, kind);
        });
        choice.setAttribute("role", "menuitem");
        choice.append(svg(paths), el("span", "", text));
        return choice;
      };
      menu.append(item(I.skip, say("skip"), "skip"));
      if (card.source) menu.append(item(I.less, say("less"), "hide_source"));
      const more = iconButton("icon-btn", I.more, say("more"), () => {
        const open = !wrap.classList.contains("open");
        closeMenus();
        wrap.classList.toggle("open", open);
        more.setAttribute("aria-expanded", String(open));
        if (open) menu.querySelector("button").focus();
      });
      more.setAttribute("aria-haspopup", "menu");
      more.setAttribute("aria-expanded", "false");
      wrap.append(more, menu);
      return wrap;
    }
    function closeMenus() {
      for (const wrap of root.querySelectorAll(".find-more-wrap.open")) {
        wrap.classList.remove("open");
        wrap.firstChild.setAttribute("aria-expanded", "false");
      }
    }
    function setLiked(like, card, liked) {
      card.liked = liked;
      like.setAttribute("aria-pressed", String(liked));
      like.classList.toggle("loved", liked);
      like.setAttribute("aria-label", say(liked ? "liked" : "like"));
      like.title = say(liked ? "liked" : "like");
    }
    function folded(node, key) {
      const note = el("div", "find-folded-line");
      note.append(svg(I.skip), el("span", "", say(key)));
      node.className = "find folded";
      node.style.height = "";
      node.replaceChildren(note);
      return node;
    }
    // Not for me, or less from where it came: the card folds down to one quiet line,
    // so the chat below it does not jump.
    async function fold(card, node, kind) {
      // A video playing on it stops here, and how long it ran is told.
      node.querySelector(".player")?.remove();
      players.get(node)?.();
      node.style.height = `${node.offsetHeight}px`;
      void node.offsetHeight;
      node.classList.add("folding");
      node.style.height = "44px";
      setTimeout(() => folded(node, kind === "skip" ? "skipped" : "lessDone"), motion() === "auto" ? 0 : 260);
      try {
        await ctx.api("feed/react", reaction(card, kind));
      } catch {
        // Not recorded: the card comes back as it was.
        setTimeout(() => node.replaceWith(findCard(card)), 300);
      }
    }
    // What the feed learns from: where the card is (its place in the batch it came in) and the ranking's slot.
    function reaction(card, action, more = {}) {
      return { id: card.id, action, surface: "chat", rank: card.rank ?? 0, slot: card.slot || "", ...more };
    }
    function react(card, kind, more, how) {
      // Opening still works when the note does not arrive; nothing to undo.
      if (card.id) ctx.api("feed/react", reaction(card, kind, more), how).catch(() => {});
    }
    function ago(at) {
      const then = new Date(at);
      const seconds = (then.getTime() - Date.now()) / 1000;
      const format = new Intl.RelativeTimeFormat(locale(), { numeric: "auto" });
      const steps = [
        [60, 1, "second"],
        [3600, 60, "minute"],
        [86400, 3600, "hour"],
        [604800, 86400, "day"],
      ];
      if (Math.abs(seconds) < 45) return format.format(0, "second");
      for (const [limit, size, unit] of steps) {
        if (Math.abs(seconds) < limit) return format.format(Math.round(seconds / size), unit);
      }
      return then.toLocaleDateString(locale(), { month: "short", day: "numeric" });
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
      const line = quoteNode(replying);
      line.setAttribute("aria-label", say("replyTo").replace("{title}", replying.title));
      parts.quote.replaceChildren(line, iconButton("chat-quote-x", I.x, say("cancelReply"), () => {
        setReply(null);
        parts.input.focus();
      }));
    }

    // ---- Sending
    function submit() {
      if (sending) {
        // The text stays in the box: say why Enter did nothing.
        flash(say("wait"));
        return;
      }
      const text = parts.input.value;
      if (!text.trim() || !state?.configured) return;
      const quote = replying;
      parts.input.value = "";
      setReply(null);
      grow();
      send(text, null, quote);
    }
    async function send(text, retrySeq = null, quote = null) {
      sending = true;
      syncSend();
      // What the character was sending on its own comes back in order with the answer.
      stopReveal();
      const mine = showMessage({ role: "user", text, quote, at: new Date().toISOString() });
      renderSetup();
      const typing = typingRow();
      const asked = performance.now();
      // The first message of a plain chat names it: shown at once, and as kept once the list is read again.
      if (!main && !title) hooks.changed(id, Array.from(text.trim().replace(/\s+/g, " ")).slice(0, TITLE_CLIP).join(""));
      try {
        const value = await ctx.api("chat", { text, after: seen, retry: retrySeq, chat: id, reply_to: quote?.id || "" });
        // The chat as recorded: anything sent meanwhile, this message and the reply.
        mine.remove();
        unline(typing);
        if (value.forgotLines || value.chat !== tag) showHistory(value.forgotLines ? value : await history());
        else await reveal(value.messages, performance.now() - asked);
      } catch (error) {
        unline(typing);
        if (lost(error)) return;
        // A message the chat kept unanswered shows as kept, so it can be sent again after a reload too.
        let kept = null;
        try {
          kept = await history();
        } catch {
          // Not reachable: the notice below still offers to send it again.
        }
        const last = kept?.messages.at(-1);
        if (last && last.role === "user" && last.failed && last.text === text) showHistory(kept);
        else failed(mine, error instanceof TypeError ? "network" : error.message, text, retrySeq, quote);
        if (error.message === "chat_failed") refreshState();
      } finally {
        sending = false;
        syncSend();
        if (visible()) parts.input.focus();
        if (!main) hooks.changed();
        poll();
      }
    }
    let flashTimer = null;
    function flash(text) {
      parts.hint.textContent = text;
      parts.hint.classList.add("flash");
      clearTimeout(flashTimer);
      flashTimer = setTimeout(() => {
        parts.hint.classList.remove("flash");
        parts.hint.textContent = say("hint");
      }, 2500);
    }

    // ---- Looking for what the character sent on its own
    async function poll() {
      clearTimeout(pollTimer);
      if (!visible() || !state?.configured) return;
      if (!sending && !polling) {
        polling = true;
        try {
          const value = await history(seen);
          // A reply that started meanwhile brings these messages itself.
          if (!sending) {
            const was = parts.empty.hidden;
            if (value.chat !== tag) showHistory(await history());
            else await reveal(value.messages.filter((item) => item.seq > seen));
            if (was !== parts.empty.hidden || !parts.empty.hidden) renderSetup();
          }
        } catch (error) {
          // The next look tries again; a lasting problem shows when a message is sent.
          if (lost(error)) return;
        } finally {
          polling = false;
        }
      }
      clearTimeout(pollTimer);
      if (visible()) pollTimer = setTimeout(poll, ctx.told ? TOLD_POLL_MS : POLL_MS);
    }

    async function refreshState() {
      try {
        state = await ctx.api("state");
      } catch {
        // Kept as it was: a failed send says what went wrong.
      }
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
      drop() {
        clearTimeout(pollTimer);
        for (const [type, run] of Object.entries(listeners)) document.removeEventListener(type, run);
        root.remove();
        for (const url of blobs.values()) url.then((value) => URL.revokeObjectURL(value)).catch(() => {});
      },
    };
  }

  return { create };
})();
