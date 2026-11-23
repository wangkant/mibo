// The card the pet brings: one thing the character found, beside it in the
// pet's own window. The whole card opens the thing in the app. Under its site
// a chip says why it is here, and a press on it asks for more or less of
// that. At its foot: like, not interested (which asks what about it was not
// wanted, and can be taken back for a few seconds), and another one at once.
// Left alone it goes by itself, and a click on the pet puts it away. However
// it goes, the feed is told how and after how long ("end"). The same frame,
// with only words in it, is a line the character says of its own: a click on
// it opens the main chat, where the line is too.
// The room between the card and the figure's window (less than none: the card
// reaches a little into the room kept round the figure, pet.js PAD), that
// window, and how far above the window's bottom the card sits, its tail at the
// figure's head (CSS px); its width is card.css's.
const CARD_GAP = -8;
// How far its tail reaches past its side, for the window to take the pointer there too.
const CARD_TAIL = 8;
// The pet's own window, the room over the figure's head included (window.py PET_SIZE).
const CARD_FIGURE = [200, 278];
const CARD_LIFT = 80;
const CARD_MS = 45000;
const SAID_MS = 15000;
// "Not interested": how long the reasons wait for a choice (then it is this one alone), and how long
// the no can be taken back (ms).
const ASK_MS = 8000;
const UNDO_MS = 5000;
// A find that came before its sentence: the sentence is asked for this often, this many times (ms).
const LINE_EVERY = 1000;
const LINE_TRIES = 15;
// How long the chip says what a press on it did (ms).
const LEANED_MS = 1800;
const YOUTUBE = ["www.youtube-nocookie.com", "www.youtube.com", "youtube.com", "youtube-nocookie.com"];
// Lucide-style strokes.
const CARD_ICONS = {
  heart:
    '<path d="M19 14c1.49-1.46 3-3.21 3-5.5A5.5 5.5 0 0 0 16.5 3c-1.76 0-3 .5-4.5 2-1.5-1.5-2.74-2-4.5-2A5.5 5.5 0 0 0 2 8.5c0 2.3 1.5 4.05 3 5.5l7 7z"/>',
  x: '<path d="M18 6 6 18M6 6l12 12"/>',
  next: '<path d="M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/><path d="M3 12a9 9 0 0 0 9 9 9.75 9.75 0 0 0 6.74-2.74L21 16"/><path d="M16 16h5v5"/>',
  nope: '<circle cx="12" cy="12" r="9"/><path d="m5.6 5.6 12.8 12.8"/>',
  down: '<path d="m6 9 6 6 6-6"/>',
};

// `api(path, body)` fetches from the page with its token: GET without a body.
function makeCard(api) {
  const box = document.getElementById("card");
  const lang = paI18n.lang;
  const words = paI18n.words("card");
  // The thing on the card, or the line said ({ said: remark }); `asking` while
  // the window is still making room for it.
  let item = null;
  let asking = false;
  let timer = 0;
  let picture = "";
  // The player playing on the card, or null; and how long it has run: from
  // YouTube's own state changes once it sends them, else the time it is shown.
  let playing = null;
  let ran = 0;
  let since = null;
  let heard = false;
  let told = 0;
  // When the card came out, and whether it was opened (played) or liked while out.
  let shownAt = 0;
  let opened = false;
  let likedHere = false;
  // "Not interested" was pressed and its reasons are out: put away now, it is a no to this one.
  let asked = false;

  const el = (tag, cls, text) => {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text) node.textContent = text;
    return node;
  };
  const icon = (name) => {
    const node = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    node.setAttribute("viewBox", "0 0 24 24");
    node.setAttribute("aria-hidden", "true");
    node.innerHTML = CARD_ICONS[name];
    return node;
  };
  const button = (cls, text, label, handler) => {
    const node = el("button", cls, text);
    node.type = "button";
    node.title = label;
    node.setAttribute("aria-label", label);
    node.addEventListener("click", (event) => {
      event.stopPropagation();
      handler(node);
    });
    return node;
  };
  // The card is always the first and only thing shown; the ranking's slot goes back with it.
  const react = (found, action, more = {}) =>
    api("/api/feed/react", { id: found.id, action, surface: "card", rank: 0, slot: found.slot || "", ...more }).catch(() => {
      // The service is not answering: the reaction is lost, the card still goes.
    });
  // Seconds the card has been out, to a tenth, as the feed takes them.
  const shownFor = () => Math.min(86400, Math.round((performance.now() - shownAt) / 100) / 10);
  const seconds = () => Math.min(86400, (ran + (since === null ? 0 : performance.now() - since)) / 1000);
  // Each telling carries the whole time so far; the feed keeps the longest.
  function tellPlay(found) {
    const now = seconds();
    if (!playing || now - told < 1) return null;
    told = now;
    return react(found, "play", { play_s: Math.round(now * 10) / 10 });
  }

  // A picture is behind the page's token, so it comes as a blob.
  async function fetchPicture(path) {
    if (!path) return "";
    try {
      const response = await api(path);
      return response.ok ? URL.createObjectURL(await response.blob()) : "";
    } catch {
      return "";
    }
  }

  // The chip under the site: why this one. A press swaps the row for "more" and "less" of what it names;
  // a press on either sets the lean (again: back to neither), says so for a moment, and the row is back.
  function whyChip(found, head) {
    const why = found.why;
    const chip = button("card-why card-still", why.text, why.text, () => {
      const row = el("div", "card-head card-lean");
      const choice = (to, text) => {
        const node = button("card-chip card-still", text, text, async () => {
          const now = why.lean === to ? null : to;
          why.lean = now;
          api("/api/feed/lean", { key: why.key, to: now }).catch(() => {});
          row.replaceWith(head);
          chip.firstChild.textContent = words.leaned[now ?? 0];
          await new Promise((resolve) => setTimeout(resolve, LEANED_MS));
          chip.firstChild.textContent = why.text;
        });
        node.setAttribute("aria-pressed", String(why.lean === to));
        return node;
      };
      row.append(choice(1, words.more), choice(-1, words.less));
      head.replaceWith(row);
    });
    // "New find" names nothing to have more or less of.
    if (why.key) chip.append(icon("down"));
    else chip.disabled = true;
    return chip;
  }

  function draw(found) {
    const body = el("div", "card-body");
    const head = el("div", "card-head");
    head.append(el("span", "card-site", found.site.replace(/^www\./, "")));
    if (found.why) head.append(whyChip(found, head));
    body.append(head);
    // The character's own sentence on why this one is for its person leads the card; while it is still
    // being written its room is kept, so the window is sized once.
    if (found.line || found.more) body.append(el("p", `card-words card-line${found.more ? " card-wait" : ""}`, found.line));

    if (found.kind === "video" && found.player) {
      const media = el("div", "card-media");
      if (picture) media.append(Object.assign(el("img"), { src: picture, alt: "" }));
      media.append(
        button("card-play", "", words.play, () => {
          const frame = el("iframe");
          const src = new URL(found.player);
          src.searchParams.set("autoplay", "1");
          if (YOUTUBE.includes(src.hostname)) {
            // YouTube's player says, once asked to, when it cannot play here:
            // the video's owner keeps it off other sites.
            src.searchParams.set("enablejsapi", "1");
            // Where its replies go, as YouTube's own API says.
            src.searchParams.set("origin", location.origin);
            // Asked until it answers, as YouTube's own API does: its player is ready a little after its page.
            frame.addEventListener("load", () => {
              let tries = 0;
              const ask = setInterval(() => {
                if (heard || playing !== frame || ++tries > 40) return clearInterval(ask);
                frame.contentWindow.postMessage(JSON.stringify({ event: "listening", id: found.id, channel: "widget" }), src.origin);
              }, 250);
            });
          }
          playing = frame;
          ran = told = 0;
          since = performance.now();
          heard = false;
          frame.src = src.href;
          frame.title = found.title;
          frame.allow = "autoplay; encrypted-media; picture-in-picture";
          frame.referrerPolicy = "strict-origin-when-cross-origin";
          // The player's own clicks open the site in the browser; on the card only the
          // play button plays, a click anywhere else opens the thing in the app.
          media.replaceChildren(frame, el("div", "card-shield"));
          // It stays while it plays; watching it is opening it.
          clearTimeout(timer);
          opened = true;
          react(found, "open");
        }),
      );
      body.append(media);
    } else if (picture) {
      const media = el("div", "card-media");
      media.append(Object.assign(el("img"), { src: picture, alt: "" }));
      body.append(media);
    }
    // Without a sentence of the character's the title stands alone: the page's own words may be in a
    // language the person does not read.
    body.append(el("div", "card-title", found.title));

    const foot = el("div", "card-foot");
    const labelled = (cls, name, text, handler) => {
      const node = button(cls, "", text, handler);
      node.append(icon(name), el("span", "", text));
      return node;
    };
    let liked = found.liked;
    const heart = labelled("card-like", "heart", words.like, (node) => {
      liked = likedHere = !liked;
      node.classList.toggle("on", liked);
      node.setAttribute("aria-pressed", String(liked));
      react(found, liked ? "like" : "unlike");
    });
    heart.classList.toggle("on", liked);
    heart.setAttribute("aria-pressed", String(liked));
    foot.append(
      heart,
      labelled("card-nope", "nope", words.nope, () => ask(found)),
      labelled("card-next", "next", words.next, () => another()),
    );
    body.append(foot);
    box.replaceChildren(el("div", "card-tail"), body);
    box.classList.remove("bubble", "panel");
    box.setAttribute("role", "button");
    box.title = words.open;
  }

  // Words in the find's frame at the height it had, so the frame does not jump: the reasons, the undo line.
  function swapBody(...nodes) {
    const high = box.querySelector(".card-body").offsetHeight;
    const body = el("div", "card-body card-note");
    body.style.minHeight = `${high}px`;
    body.append(...nodes);
    box.replaceChildren(el("div", "card-tail"), body);
    box.title = "";
    return size();
  }

  // "Not interested": what about it, each a different no. Left unanswered it is a no to this one alone.
  function ask(found) {
    clearTimeout(timer);
    // A video playing on it stops here, and how long it ran is told.
    tellPlay(found);
    playing = null;
    asked = true;
    const reasons = el("div", "card-reasons");
    const reason = (about, text) => reasons.append(button("card-chip card-nope", text, text, () => no(found, about)));
    reason("thing", words.thing);
    if (found.topic) reason("topic", words.topic.replace("{name}", found.topic.name));
    if (found.source) reason("source", words.source);
    reason("seen", words.seen);
    swapBody(el("p", "card-ask", words.ask), reasons);
    timer = setTimeout(() => no(found, "thing"), ASK_MS);
  }

  // The no is told at once, and the frame offers to take it back for UNDO_MS before it goes.
  function no(found, about) {
    clearTimeout(timer);
    asked = false;
    // Seen already says nothing of their taste; any other is the card closed, with what the no was about.
    const sent = Promise.all([
      react(found, "end", { end: opened ? "open" : about === "seen" ? "known" : "close", shown_s: shownFor() }),
      about === "source"
        ? react(found, "hide_source")
        : about !== "seen" && react(found, "skip", { said: about === "topic" ? { about, key: found.topic.key } : { about } }),
    ]);
    item = { panel: true, target: "", no: true };
    const undo = button("card-undo card-still", words.undo, words.undo, async () => {
      clearTimeout(timer);
      // The no has reached the feed before it is taken back.
      await sent;
      await api("/api/feed/undo", { id: found.id }).catch(() => {});
      item = null;
      asking = true;
      draw(found);
      if ((await put(found, CARD_MS)) && found.more) sentence(found);
    });
    swapBody(el("p", "card-words", words.said[about].replace("{name}", found.topic?.name)), undo);
    timer = setTimeout(() => close("seen"), UNDO_MS);
  }

  // A line said: the words and the cross, nothing else.
  function drawSaid(remark) {
    const body = el("div", "card-body");
    const cross = button("card-close", "", words.close, () => close("skip"));
    cross.append(icon("x"));
    body.append(el("p", "card-words", remark.text), cross);
    box.replaceChildren(el("div", "card-tail"), body);
    box.classList.remove("panel");
    box.classList.add("bubble");
    box.setAttribute("role", "button");
    box.title = words.chat;
  }

  // Grows the window for what is drawn in the box, `ms` before it goes by
  // itself (0: not by itself); true when it is out. `room`: the height kept
  // above the window's bottom for what comes next in the same frame, so the
  // window need not grow again for it (window.py grows it only for a new size).
  // Tells the window how much room what is in the box needs; the side the card is on, "" when the
  // pet is off the ground.
  function size(room = 0) {
    const wide = box.offsetWidth;
    const high = box.offsetHeight;
    const tall = Math.max(CARD_FIGURE[1], Math.max(high, room) + CARD_LIFT);
    // Where the card is, its tail included, so the window takes the pointer there too.
    return window.pywebview.api.card(wide + CARD_GAP + CARD_FIGURE[0], tall, [0, tall - CARD_LIFT - high, wide + CARD_TAIL, high]);
  }

  async function put(what, ms, room = 0) {
    // Measured unseen, so the window grows once to the size it needs.
    box.classList.add("measure");
    box.hidden = false;
    // Where the three names do not fit in a row (German), the heart goes without its name.
    const foot = box.querySelector(".card-foot");
    if (foot) foot.classList.toggle("tight", foot.scrollWidth > foot.clientWidth);
    const side = await size(room);
    asking = false;
    if (!side) {
      // The pet left the ground meanwhile.
      clear();
      return false;
    }
    document.body.classList.toggle("card-right", side === "right");
    box.classList.remove("measure");
    item = what;
    shownAt = performance.now();
    opened = likedHere = false;
    timer = ms ? setTimeout(() => close("timeout"), ms) : 0;
    return true;
  }

  // "Another": this one passed over (a mild no) and the next put in its frame at once: the choice that
  // waits, or the ranking's next with its sentence following; a word that there is none when nothing is left.
  async function another() {
    if (!item || item.said || item.panel) return;
    const done = item;
    clearTimeout(timer);
    const played = tellPlay(done);
    playing = null;
    react(done, "end", { end: "next", shown_s: shownFor() });
    const mine = (item = { panel: true, target: "" });
    // The card passed over fades until the next is in.
    box.classList.add("picking");
    box.title = "";
    await played;
    let found = null;
    try {
      const response = await api(`/api/feed/next?now=true&lang=${encodeURIComponent(lang)}`);
      if (response.ok) found = (await response.json()).item;
    } catch {
      // The service is not answering: as if nothing were left.
    }
    if (item !== mine) return;
    box.classList.remove("picking");
    if (!found) {
      const none = el("div", "card-body");
      none.append(el("p", "card-words", words.none));
      box.replaceChildren(el("div", "card-tail"), none);
      return put(mine, 4000);
    }
    if (picture) URL.revokeObjectURL(picture);
    picture = await fetchPicture(found.picture);
    if (item !== mine) return;
    item = null;
    asking = true;
    await bring(found);
    box.dispatchEvent(new CustomEvent("card-next"));
  }

  // A find put in the frame and told as seen; true when it is out. One that came before its sentence
  // ("more") gets it in the room kept for it when it is written; the frame is fitted again only for a
  // sentence longer than that room, or when none comes.
  async function bring(found) {
    draw(found);
    if (!(await put(found, CARD_MS))) return false;
    react(found, "seen");
    if (found.more) sentence(found);
    return true;
  }
  async function sentence(found) {
    for (let tries = 0; tries < LINE_TRIES; tries += 1) {
      await new Promise((resolve) => setTimeout(resolve, LINE_EVERY));
      if (item !== found || asked) return;
      let late = null;
      try {
        const response = await api(`/api/feed/line?id=${encodeURIComponent(found.id)}`);
        if (response.ok) late = await response.json();
      } catch {
        // The service is not answering: asked again.
      }
      if (item !== found || asked) return;
      if (late && !late.wait) {
        found.line = late.line;
        break;
      }
    }
    found.more = false;
    const room = box.querySelector(".card-wait");
    if (found.line) room.textContent = found.line;
    else room.remove();
    await size();
  }

  // Something else beside the figure in the same frame (petbox.js: a line to
  // type in, a reply, what to do with something dropped): `node` in it, out
  // `ms` (0: until put away), opening the app at `target` when clicked, if
  // anywhere; `room` as for put. A find or a line out is put away for it.
  // True when it is out.
  async function panel(node, { ms = 0, target = "", room = 0 } = {}) {
    if (asking) return false;
    if (item && !item.panel) await close("seen");
    clearTimeout(timer);
    asking = true;
    box.replaceChildren(el("div", "card-tail"), node);
    box.classList.remove("bubble");
    box.classList.add("panel");
    box.removeAttribute("role");
    box.title = "";
    return put({ panel: true, target }, ms, room);
  }

  // True when the card is out.
  async function show(found) {
    if (item || asking) return false;
    asking = true;
    picture = await fetchPicture(found.picture);
    return bring(found);
  }

  // The line said in a bubble; true when it is out.
  async function say(remark) {
    if (item || asking) return false;
    asking = true;
    drawSaid(remark);
    return put({ said: remark }, SAID_MS);
  }

  function clear() {
    playing = null;
    asked = false;
    box.hidden = true;
    box.replaceChildren();
    box.classList.remove("bubble", "panel");
    if (picture) URL.revokeObjectURL(picture);
    picture = "";
  }

  // `action`: "open", "skip" (a said line's cross), "timeout" (gone by itself), or "seen" (put away with
  // the pet, or for something else in the frame). A find put away while its reasons were out is a no to it.
  async function close(action) {
    if (!item) return;
    const nope = asked && action !== "open";
    const done = item;
    item = null;
    clearTimeout(timer);
    const quiet = done.said || done.panel;
    // A video played on it: how long, before the player goes.
    const played = quiet ? null : tellPlay(done);
    const shown_s = shownFor();
    // The pet droops at a find put away or turned down, not at a frame of its own going (pet.js).
    box.dataset.went = done.panel && !done.no ? "panel" : "";
    box.classList.remove("picking");
    clear();
    // Only a find tells the feed what became of it: how the card ended, and what the person did.
    const end =
      action === "open" || opened
        ? "open"
        : likedHere
          ? "like"
          : nope
            ? "close"
            : action === "timeout"
              ? "timeout"
              : "hushed";
    const sent = quiet
      ? null
      : Promise.all([
          react(done, "end", { end, shown_s }),
          action === "open" ? react(done, action) : null,
          // A no that says so counts as more than a plain skip (taste.py SAID_NO).
          nope ? react(done, "skip", { said: { about: "thing" } }) : null,
        ]);
    await window.pywebview.api.card(0, 0);
    // Only once the window is the figure's size again, or the figure would jump inside it.
    document.body.classList.remove("card-right");
    await Promise.all([sent, played]);
  }

  async function openInApp() {
    if (!item || asked || (item.panel && !item.target)) return;
    const target = item.panel ? item.target : item.said ? "chat" : `feed/${item.id}`;
    await close("open");
    window.pywebview.api.open_at(target);
  }
  box.addEventListener("click", openInApp);
  // A video that cannot play on the card is opened in the app instead. Its
  // player says when it plays, pauses and ends: the time it ran is counted from
  // that, and told when it ends.
  window.addEventListener("message", (event) => {
    if (!playing || event.source !== playing.contentWindow) return;
    let said = null;
    try {
      said = JSON.parse(event.data);
    } catch {
      return;
    }
    if (said?.event === "onError") {
      // It never played: no play time is told.
      playing = null;
      return openInApp();
    }
    const state = said?.event === "onStateChange" ? said.info : said?.info?.playerState;
    if (typeof state !== "number") return;
    const now = performance.now();
    if (!heard) {
      heard = true;
      since = null;
    }
    if (state === 1) since ??= now;
    else if (since !== null) {
      ran += now - since;
      since = null;
    }
    if (state === 0) tellPlay(item);
  });

  return {
    lang,
    get open() {
      return item !== null || asking;
    },
    // What is out: "find", "said", "panel", or "" for nothing.
    get kind() {
      return !item ? "" : item.panel ? "panel" : item.said ? "said" : "find";
    },
    show,
    say,
    panel,
    close,
  };
}
