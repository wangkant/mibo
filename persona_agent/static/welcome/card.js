// The card the pet brings: one thing the character found, beside it in the
// pet's own window. The whole card opens the thing in the app, the heart likes
// it, the cross puts it away; left alone it goes by itself. The same frame,
// with only words in it, is a line the character says of its own: a click on
// it opens the main chat, where the line is too.
const CARD_WORDS = {
  en: { open: "Open in personagent", like: "Like", close: "Put away", play: "Play here", chat: "Talk in personagent" },
  zh: { open: "在 personagent 中打开", like: "喜欢", close: "收起", play: "在此播放", chat: "在 personagent 中聊天" },
  "zh-TW": { open: "在 personagent 裡打開", like: "喜歡", close: "收起", play: "在這裡播放", chat: "在 personagent 裡聊" },
  ja: { open: "personagent で開く", like: "いいね", close: "しまう", play: "ここで再生", chat: "personagent で話す" },
  ko: { open: "personagent에서 열기", like: "좋아요", close: "넣어 두기", play: "여기서 재생", chat: "personagent에서 이야기하기" },
  es: { open: "Abrir en personagent", like: "Me gusta", close: "Guardar", play: "Reproducir aquí", chat: "Hablar en personagent" },
  fr: { open: "Ouvrir dans personagent", like: "J'aime", close: "Ranger", play: "Lire ici", chat: "Parler dans personagent" },
  de: { open: "In personagent öffnen", like: "Gefällt mir", close: "Weglegen", play: "Hier abspielen", chat: "In personagent reden" },
  "pt-BR": { open: "Abrir no personagent", like: "Curtir", close: "Guardar", play: "Tocar aqui", chat: "Conversar no personagent" },
  ru: { open: "Открыть в personagent", like: "Нравится", close: "Убрать", play: "Смотреть здесь", chat: "Поговорить в personagent" },
};
// The room between the card and the figure, the figure's box, and how far
// above the window's bottom the card sits, its tail at the figure's head (CSS
// px); its width is card.css's.
const CARD_GAP = 12;
const CARD_FIGURE = [160, 190];
const CARD_LIFT = 80;
const CARD_MS = 45000;
const SAID_MS = 15000;
const YOUTUBE = ["www.youtube-nocookie.com", "www.youtube.com", "youtube.com", "youtube-nocookie.com"];
// Lucide-style strokes: the heart and the cross.
const CARD_ICONS = {
  heart:
    '<path d="M19 14c1.49-1.46 3-3.21 3-5.5A5.5 5.5 0 0 0 16.5 3c-1.76 0-3 .5-4.5 2-1.5-1.5-2.74-2-4.5-2A5.5 5.5 0 0 0 2 8.5c0 2.3 1.5 4.05 3 5.5l7 7z"/>',
  x: '<path d="M18 6 6 18M6 6l12 12"/>',
};

function pageLang() {
  // The app's own choice, where this window shares its storage; else the system's.
  let code = "";
  try {
    code = localStorage.getItem("personagent-page-language") || "";
  } catch {
    // Storage refused: the system's language decides.
  }
  if (!code) code = (navigator.languages || [navigator.language || ""])[0] || "";
  if (CARD_WORDS[code]) return code;
  const low = code.toLowerCase();
  if (low.startsWith("zh")) return /tw|hk|mo|hant/.test(low) ? "zh-TW" : "zh";
  if (low.startsWith("pt")) return "pt-BR";
  return CARD_WORDS[low.slice(0, 2)] ? low.slice(0, 2) : "en";
}

// `api(path, body)` fetches from the page with its token: GET without a body.
function makeCard(api) {
  const box = document.getElementById("card");
  const lang = pageLang();
  const words = CARD_WORDS[lang];
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

  function draw(found) {
    const body = el("div", "card-body");
    const head = el("div", "card-head");
    head.append(el("span", "card-site", found.site.replace(/^www\./, "")));
    let liked = found.liked;
    const heart = button("card-like", "", words.like, (node) => {
      liked = !liked;
      node.classList.toggle("on", liked);
      node.setAttribute("aria-pressed", String(liked));
      react(found, liked ? "like" : "unlike");
    });
    heart.append(icon("heart"));
    heart.classList.toggle("on", liked);
    heart.setAttribute("aria-pressed", String(liked));
    const cross = button("card-close", "", words.close, () => close("skip"));
    cross.append(icon("x"));
    head.append(heart, cross);
    body.append(head);
    // The character's own sentence on why this one is for its person leads the card.
    if (found.line) body.append(el("p", "card-words card-line", found.line));

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
          react(found, "open");
        }),
      );
      body.append(media);
    } else if (picture) {
      const media = el("div", "card-media");
      media.append(Object.assign(el("img"), { src: picture, alt: "" }));
      body.append(media);
    }
    body.classList.toggle("with-media", body.querySelector(".card-media") !== null);
    body.append(el("div", "card-title", found.title));
    // Without a sentence of the character's, the thing's own words.
    const said = !found.line && (found.words || found.text);
    if (said) body.append(el("p", "card-words", said));
    box.replaceChildren(el("div", "card-tail"), body);
    box.classList.remove("bubble");
    box.title = words.open;
  }

  // A line said: the words and the cross, nothing else.
  function drawSaid(remark) {
    const body = el("div", "card-body");
    const cross = button("card-close", "", words.close, () => close("skip"));
    cross.append(icon("x"));
    body.append(el("p", "card-words", remark.text), cross);
    box.replaceChildren(el("div", "card-tail"), body);
    box.classList.add("bubble");
    box.title = words.chat;
  }

  // Grows the window for what is drawn in the box, `ms` before it goes by
  // itself; true when it is out.
  async function put(what, ms) {
    // Measured unseen, so the window grows once to the size it needs.
    box.classList.add("measure");
    box.hidden = false;
    const wide = box.offsetWidth;
    const high = box.offsetHeight;
    const tall = Math.max(CARD_FIGURE[1], high + CARD_LIFT);
    // Where the card is, its tail included, so the window takes the pointer there too.
    const side = await window.pywebview.api.card(wide + CARD_GAP + CARD_FIGURE[0], tall, [
      0,
      tall - CARD_LIFT - high,
      wide + CARD_GAP,
      high,
    ]);
    asking = false;
    if (!side) {
      // The pet left the ground meanwhile.
      clear();
      return false;
    }
    document.body.classList.toggle("card-right", side === "right");
    box.classList.remove("measure");
    item = what;
    timer = setTimeout(() => close("seen"), ms);
    return true;
  }

  // True when the card is out.
  async function show(found) {
    if (item || asking) return false;
    asking = true;
    picture = await fetchPicture(found.picture);
    draw(found);
    if (!(await put(found, CARD_MS))) return false;
    react(found, "seen");
    return true;
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
    box.hidden = true;
    box.replaceChildren();
    box.classList.remove("bubble");
    if (picture) URL.revokeObjectURL(picture);
    picture = "";
  }

  async function close(action) {
    if (!item) return;
    const done = item;
    item = null;
    clearTimeout(timer);
    // A video played on it: how long, before the player goes.
    const played = done.said ? null : tellPlay(done);
    clear();
    // Only a find tells the feed what became of it.
    const sent = done.said ? null : react(done, action);
    await window.pywebview.api.card(0, 0);
    // Only once the window is the figure's size again, or the figure would jump inside it.
    document.body.classList.remove("card-right");
    await Promise.all([sent, played]);
  }

  async function openInApp() {
    if (!item) return;
    const target = item.said ? "chat" : `feed/${item.id}`;
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
    show,
    say,
    close,
  };
}
