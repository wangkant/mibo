"use strict";
// A thing the character brought, as a chat draws it: a 16:10 cover beside a body laid to its height, a fixed foot
// with reply, like, open and 不感兴趣; a video plays in place. What the person does with it is told to the feed
// (POST /api/feed/react), and how long a video ran when it is folded away, scrolled out of view or the page is put
// away. The chat (chat.js) makes one of these per chat view; 推荐记录 (finds.js) draws the main chat's.
window.paFindCard = (() => {
  const { I, el, button, svg, iconButton, anchor, hostOf, motion } = window.paKit;
  const YOUTUBE = ["www.youtube-nocookie.com", "www.youtube.com", "youtube.com", "youtube-nocookie.com"];
  const PLAY = '<path d="M7 4.5v15a1 1 0 0 0 1.5.86l12.5-7.5a1 1 0 0 0 0-1.72L8.5 3.64A1 1 0 0 0 7 4.5z"/>';

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
  // A video playing on find `node` stops, and how long it ran is told.
  function stop(node) {
    node.querySelector(".player")?.remove();
    players.get(node)?.();
  }

  // The open menus of the finds in `root` close.
  function closeMenusIn(root) {
    for (const wrap of root.querySelectorAll(".find-more-wrap.open")) {
      wrap.classList.remove("open");
      wrap.firstChild.setAttribute("aria-expanded", "false");
    }
  }

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
  function ago(at) {
    const then = new Date(at);
    const seconds = (then.getTime() - Date.now()) / 1000;
    const format = new Intl.RelativeTimeFormat(paI18n.locale, { numeric: "auto" });
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
    return then.toLocaleDateString(paI18n.locale, { month: "short", day: "numeric" });
  }
  // What the feed learns from: where the card is (its place in the batch it came in) and the ranking's slot.
  function reaction(card, action, more = {}) {
    return { id: card.id, action, surface: card.surface || "chat", rank: card.rank ?? 0, slot: card.slot || "", ...more };
  }

  // `env`: api(path, body, how), picture(path) giving a blob address, say(key, name), reply(card) to answer it,
  // grew() when it grew after it was drawn, root (the chat, whose open menus close together).
  function create(env) {
    const { say } = env;
    function react(card, kind, more, how) {
      // Opening still works when the note does not arrive; nothing to undo.
      if (card.id) env.api("feed/react", reaction(card, kind, more), how).catch(() => {});
    }

    function findCard(card) {
      const node = el("article", "find");
      if (card.skipped) return folded(node, card);
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
        env.picture(card.picture)
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
      if (card.why) top.append(whyChip(card));
      const heading = el("h3");
      const link = original(card, "find-title");
      link.textContent = card.title || site;
      heading.append(link);
      body.append(top, heading);
      // Why it was shown, in words (panels/feedpage.py page): the 推荐记录 list's rows carry it.
      if (card.reason) body.append(el("p", "find-reason", card.reason));
      if (card.excerpt) body.append(el("p", "find-text", card.excerpt));

      // The cover and the site's icon already say what kind it is: the foot says only how old.
      const foot = el("div", "find-foot");
      if (card.at) {
        const stamp = el("time", "", ago(card.at));
        stamp.dateTime = card.at;
        stamp.title = new Date(card.at).toLocaleString(paI18n.locale);
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
      env.grew();
      // Watching it in place is the video's way of opening it.
      react(card, "open");
    }
    function original(card, className) {
      const link = anchor(card.url, className);
      link.addEventListener("click", () => react(card, "open"));
      return link;
    }
    function actions(card, node) {
      const row = el("span", "acts");
      // Only a thing from the library can be answered or reacted to; anything can be opened.
      if (card.id) {
        const reply = button("reply-btn", "", () => env.reply(card));
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
            await env.api("feed/react", reaction(card, liked ? "like" : "unlike"));
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
    // A chip or ⋯ that opens `menu` under it, closing any other menu of the chat.
    function opener(press, menu) {
      const wrap = press.parentNode;
      press.addEventListener("click", () => {
        const open = !wrap.classList.contains("open");
        closeMenus();
        wrap.classList.toggle("open", open);
        press.setAttribute("aria-expanded", String(open));
        if (open) menu.querySelector("button").focus();
      });
      press.setAttribute("aria-haspopup", "menu");
      press.setAttribute("aria-expanded", "false");
    }
    function menuOf(className) {
      const wrap = el("span", className);
      const menu = el("div", "find-menu");
      menu.setAttribute("role", "menu");
      return [wrap, menu];
    }
    // Why this one (recommend.Why), beside the site: a press offers more or less of what it names, the
    // lean Settings shows too; a press on the one already set takes it back.
    function whyChip(card) {
      const why = card.why;
      if (!why.key) return el("span", "find-why", why.text);
      const [wrap, menu] = menuOf("find-more-wrap find-why-wrap");
      const chip = el("button", "find-why", why.text);
      chip.type = "button";
      const choice = (to, paths, text) => {
        const node = button("", "", () => {
          closeMenus();
          why.lean = why.lean === to ? null : to;
          for (const other of menu.children) other.setAttribute("aria-checked", String(other === node && why.lean === to));
          env.api("feed/lean", { key: why.key, to: why.lean }).catch(() => {});
        });
        node.setAttribute("role", "menuitemradio");
        node.setAttribute("aria-checked", String(why.lean === to));
        node.append(svg(paths), el("span", "", text));
        return node;
      };
      menu.append(choice(1, I.raise, say("leanMore")), choice(-1, I.less, say("leanLess")));
      wrap.append(chip, menu);
      opener(chip, menu);
      return wrap;
    }
    // Not interested, behind ⋯, with what it was about: this one, its kind of topic, its source, or
    // seen already (which says nothing of their taste).
    function moreMenu(card, node) {
      const [wrap, menu] = menuOf("find-more-wrap");
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
      if (card.topic) menu.append(item(I.less, say("lessTopic", card.topic.name), "topic"));
      if (card.source) menu.append(item(I.less, say("less"), "hide_source"));
      menu.append(item(I.seen, say("known"), "known"));
      const more = el("button", "icon-btn");
      more.type = "button";
      more.append(svg(I.more));
      more.setAttribute("aria-label", say("more"));
      more.title = say("more");
      wrap.append(more, menu);
      opener(more, menu);
      return wrap;
    }
    const closeMenus = () => closeMenusIn(env.root);
    function setLiked(like, card, liked) {
      card.liked = liked;
      like.setAttribute("aria-pressed", String(liked));
      like.classList.toggle("loved", liked);
      like.setAttribute("aria-label", say(liked ? "liked" : "like"));
      like.title = say(liked ? "liked" : "like");
    }
    // The one line a card turned down folds to: what the no was, and the way to take it back.
    function folded(node, card) {
      const key = { topic: "topicDone", hide_source: "lessDone", known: "knownDone" }[card.skipped] || "skipped";
      const note = el("div", "find-folded-line");
      const undo = button("find-undo", say("undo"), async () => {
        undo.disabled = true;
        try {
          await env.api("feed/undo", { id: card.id });
        } catch {
          // Not taken back: the line stays, to be tried again.
          undo.disabled = false;
          return;
        }
        card.skipped = "";
        node.replaceWith(findCard(card));
      });
      note.append(svg(I.skip), el("span", "", say(key, card.topic?.name)), undo);
      node.className = "find folded";
      node.style.height = "";
      node.replaceChildren(note);
      return node;
    }
    // Not for me, in the way `kind` says (skip: this one; topic; hide_source; known: seen already): the
    // card folds down to one quiet line, so the chat below it does not jump.
    async function fold(card, node, kind) {
      stop(node);
      node.style.height = `${node.offsetHeight}px`;
      void node.offsetHeight;
      node.classList.add("folding");
      node.style.height = "44px";
      card.skipped = kind;
      setTimeout(() => card.skipped && folded(node, card), motion() === "auto" ? 0 : 260);
      const sent =
        kind === "known"
          ? reaction(card, "end", { end: "known" })
          : kind === "hide_source"
            ? reaction(card, kind)
            : reaction(card, "skip", { said: kind === "topic" ? { about: "topic", key: card.topic.key } : { about: "thing" } });
      try {
        await env.api("feed/react", sent);
      } catch {
        // Not recorded: the card comes back as it was.
        card.skipped = "";
        setTimeout(() => node.replaceWith(findCard(card)), 300);
      }
    }

    return { card: findCard, closeMenus };
  }

  return { create, stop, closeMenus: closeMenusIn };
})();
