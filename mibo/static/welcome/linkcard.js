"use strict";
// Web addresses in a message, as cards: the page's own title, its site and icon, a line of description and its
// picture, read once by the app (panels/links.py). A video from a site whose player the app allows becomes the
// player card a find uses; links in a row form one stack; an address inside a sentence stays a link named by its
// site, its card below; a page that cannot be read is still a clean card with its host. Every card opens the
// way every link in the app opens. The app reads a page or an icon only for an address given in the chat
// (given.py): one the character composed after the chat read outside material stays its host, with no icon, and a
// click on it shows the whole address under its line, opened only on 打开 (`guard`), as a site's ask in the browser
// strip is answered (browsestrip.js).
window.paLinks = (() => {
  const { el, anchor, hostOf } = window.paKit;
  const URL_RE = /https?:\/\/[^\s<>"'，。！？；）】」　]+/g;
  const MARK = /^\s*(?:[-*•]|\d{1,2}[.)])\s+/;
  const MOST = 6;
  const previews = new Map();
  const icons = new Map();

  const clean = (url) => url.replace(/[.,;:!?)\]]+$/, "");
  // The address without its scheme, for a page that could not be read.
  const shortOf = (url) => url.replace(/^https?:\/\/(www\.)?/, "").replace(/\/$/, "");

  function urls(text, skip = []) {
    const found = [];
    for (const match of String(text || "").matchAll(URL_RE)) {
      const url = clean(match[0]);
      if (!found.includes(url) && !skip.includes(url)) found.push(url);
    }
    return found.slice(0, MOST);
  }
  // What a line says besides its addresses, its list mark and the colon before them.
  const besides = (line) => line.replace(MARK, "").replace(URL_RE, "").replace(/[\s:：\-–—]+$/, "").trim();
  const hasUrl = (line) => line.search(URL_RE) >= 0;
  // The words with what the cards say taken out: a line that is only an address, and a list that only names
  // links (each item an address with at most a short label); "" when nothing else was said.
  function bare(text) {
    const lines = String(text || "").split("\n");
    const gone = new Set();
    for (let at = 0; at < lines.length; ) {
      let end = at;
      while (end < lines.length && MARK.test(lines[end])) end += 1;
      const items = lines.slice(at, end);
      if (items.length && items.every((line) => hasUrl(line) && besides(line).length <= 24))
        for (let n = at; n < end; n += 1) gone.add(n);
      at = Math.max(end, at + 1);
    }
    lines.forEach((line, n) => hasUrl(line) && !besides(line) && gone.add(n));
    return lines.filter((_, n) => !gone.has(n)).join("\n").replace(/^\n+|\n+$/g, "");
  }

  // What the app said of an address or a host in this chat (opts.chat names it), kept by both.
  const keyOf = (opts, what) => `${opts.chat}
${what}`;
  function preview(url, opts) {
    const key = keyOf(opts, url);
    if (!previews.has(key)) {
      const asked = opts.api(`link/preview?url=${encodeURIComponent(url)}&chat=${encodeURIComponent(opts.chat)}`)
        .catch(() => ({ url, ok: false }));
      previews.set(key, asked);
      // One that failed to arrive, or one not given yet (their message on its way to the chat), is asked again next
      // time it is drawn.
      asked.then((value) => ((value.ok === false && !value.host) || value.given === false) && previews.delete(key));
    }
    return previews.get(key);
  }
  // A site's icon as a blob address, or "" when it has none; asked once per host.
  function icon(host, opts) {
    if (!host || !opts?.api) return Promise.resolve("");
    const key = keyOf(opts, host);
    if (!icons.has(key)) {
      const asked = opts.api(`link/icon?host=${encodeURIComponent(host)}&chat=${encodeURIComponent(opts.chat)}`);
      icons.set(key, asked.then((value) => (value.icon ? opts.picture(value.icon) : "")).catch(() => ""));
      asked.then((value) => value.given === false && icons.delete(key)).catch(() => {});
    }
    return icons.get(key);
  }
  // `asks` false: an address the app reads nothing for, its letter alone.
  function mark(host, opts, known = "", asks = true) {
    const box = el("span", "lk-fav");
    box.textContent = (host[0] || "·").toUpperCase();
    const show = (url) => {
      if (!url) return;
      const img = el("img");
      img.alt = "";
      img.src = url;
      box.textContent = "";
      box.classList.add("has-img");
      box.append(img);
    };
    if (known && !icons.has(keyOf(opts, host))) icons.set(keyOf(opts, host), opts.picture(known).catch(() => ""));
    if (asks) icon(host, opts).then(show);
    return box;
  }

  // An address inside the words: named by its site once the page is read, its host until then.
  function inline(url, opts) {
    const node = anchor(url, "say-link lk-inline");
    node.textContent = hostOf(url) || url;
    node.title = url;
    preview(url, opts).then((value) => {
      if (value.site) node.textContent = value.site;
    });
    return guard(node, url, opts);
  }

  // The address as the app reads it: its percent-encoding read, so the words it carries show.
  function whole(url) {
    const read = url.replace(/(?:%[0-9a-f]{2})+/gi, (run) => {
      try {
        return decodeURIComponent(run);
      } catch {
        return run;
      }
    });
    return read.split(/\s+/).join(" ");
  }
  // The address, what it is and 打开 / 取消, under the line or the cards the link stands in; one at a time.
  function ask(node, url) {
    document.querySelector(".lk-ask")?.remove();
    const t = paI18n.words("chat").linkAsk;
    const box = el("div", "browse-ask lk-ask");
    box.setAttribute("role", "group");
    box.setAttribute("aria-label", t.title);
    const words = el("div", "browse-ask-words");
    words.append(el("p", "browse-ask-title", t.title), el("p", "lk-ask-address", whole(url)), el("p", "browse-ask-meta", t.note));
    const row = el("div", "browse-ask-buttons");
    for (const [key, look] of [["open", "pa-btn-primary"], ["cancel", "pa-btn-secondary"]]) {
      const button = el("button", `pa-btn ${look} pa-btn-sm`, t[key]);
      button.type = "button";
      button.dataset.act = key;
      button.addEventListener("click", () => {
        box.remove();
        if (key === "open") go(node);
        else node.focus();
      });
      row.append(button);
    }
    box.append(words, row);
    const at = node.closest(".links") || node.closest("p, li, td, th, h3, h4, h5, h6, blockquote") || node;
    if (at.matches("li, td, th")) at.append(box);
    else at.after(box);
    // Clear of the box that floats over the foot of the chat, which a focus alone leaves it under.
    row.querySelector("button").focus({ preventScroll: true });
    box.scrollIntoView({ block: "center" });
  }
  // The link opened as every link in the app opens, past its guard.
  function go(node) {
    node.dataset.sure = "1";
    node.click();
  }
  // A click on `node` opens `url` at once when it is given in the chat, else shows it whole first.
  function guard(node, url, opts) {
    if (!opts?.api) return node;
    node.addEventListener("click", (event) => {
      if (node.dataset.sure) {
        delete node.dataset.sure;
        return;
      }
      event.preventDefault();
      opts.api(`link/given?url=${encodeURIComponent(url)}&chat=${encodeURIComponent(opts.chat)}`)
        .then((value) => value.given === true, () => false)
        .then((given) => (given ? go(node) : ask(node, url)));
    });
    return node;
  }

  function fillCard(card, url, value, opts) {
    const host = value.host || hostOf(url);
    const body = el("span", "lk-body");
    if (value.title) {
      const site = el("span", "lk-site");
      site.append(mark(host, opts, value.icon), el("span", "lk-site-name", value.site || host));
      body.append(site, el("span", "lk-title", value.title));
      if (value.description) body.append(el("span", "lk-desc", value.description));
    } else {
      // Not read: the host as its title, the address under it when it says more.
      const title = el("span", "lk-title lk-host");
      title.append(mark(host, opts, value.icon, value.given !== false), el("span", "", host));
      body.append(title);
      if (shortOf(url) !== host) body.append(el("span", "lk-desc", shortOf(url)));
    }
    card.replaceChildren(body);
    card.classList.remove("loading");
    card.classList.toggle("unread", !value.title);
    card.setAttribute("aria-label", value.title || host);
    if (value.picture) {
      const pic = el("span", "lk-pic pa-shimmer");
      const img = el("img");
      img.alt = "";
      img.decoding = "async";
      opts.picture(value.picture).then((src) => {
        img.src = src;
        pic.classList.remove("pa-shimmer");
      }).catch(() => pic.remove());
      pic.append(img);
      card.append(pic);
    }
  }

  // The cards for `list`, in their order; `opts.findCard` draws a video as a find is drawn.
  function cards(list, opts) {
    if (!list.length) return null;
    const box = el("div", "links");
    for (const url of list) {
      const card = guard(anchor(url, "lk loading"), url, opts);
      const body = el("span", "lk-body");
      const site = el("span", "lk-site");
      site.append(mark(hostOf(url), opts), el("span", "lk-site-name", hostOf(url)));
      body.append(site, el("span", "lk-title lk-wait pa-shimmer"));
      card.append(body);
      box.append(card);
      preview(url, opts).then((value) => {
        if (value.embed && opts.findCard) {
          const find = opts.findCard({ kind: "video", url, embed: value.embed, title: value.title || value.site || hostOf(url),
            site: value.site || hostOf(url), picture: value.picture || "", length: value.length || 0,
            excerpt: value.description || "" });
          find.classList.add("lk-find");
          card.replaceWith(find);
        } else fillCard(card, url, value, opts);
        opts.grew?.();
      });
    }
    return box;
  }

  return { urls, bare, inline, cards, icon, preview, guard };
})();
