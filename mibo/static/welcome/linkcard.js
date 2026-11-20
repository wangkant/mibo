"use strict";
// Web addresses in a message, as cards: the page's own title, its site and icon, a line of description and its
// picture, read once by the app (panels/links.py). A video from a site whose player the app allows becomes the
// player card a find uses; links in a row form one stack; an address inside a sentence stays a link named by its
// site, its card below; a page that cannot be read is still a clean card with its host. Every card opens the
// way every link in the app opens.
window.paLinks = (() => {
  const URL_RE = /https?:\/\/[^\s<>"'，。！？；）】」　]+/g;
  const MARK = /^\s*(?:[-*•]|\d{1,2}[.)])\s+/;
  const MOST = 6;
  const previews = new Map();
  const icons = new Map();

  const el = (tag, className = "", text = "") => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text) node.textContent = text;
    return node;
  };
  const clean = (url) => url.replace(/[.,;:!?)\]]+$/, "");
  const hostOf = (url) => {
    try {
      return new URL(url).hostname.replace(/^www\./, "");
    } catch {
      return "";
    }
  };
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

  function preview(url, opts) {
    if (!previews.has(url)) {
      const asked = opts.api(`link/preview?url=${encodeURIComponent(url)}`).catch(() => ({ url, ok: false }));
      previews.set(url, asked);
      // One that failed to arrive is asked again next time it is drawn.
      asked.then((value) => value.ok === false && !value.host && previews.delete(url));
    }
    return previews.get(url);
  }
  // A site's icon as a blob address, or "" when it has none; asked once per host.
  function icon(host, opts) {
    if (!host || !opts?.api) return Promise.resolve("");
    if (!icons.has(host))
      icons.set(host, opts.api(`link/icon?host=${encodeURIComponent(host)}`)
        .then((value) => (value.icon ? opts.picture(value.icon) : ""))
        .catch(() => ""));
    return icons.get(host);
  }
  function mark(host, opts, known = "") {
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
    if (known) {
      if (!icons.has(host)) icons.set(host, opts.picture(known).catch(() => ""));
    }
    icon(host, opts).then(show);
    return box;
  }
  function anchor(url, className) {
    const node = el("a", className);
    node.href = url;
    node.target = "_blank";
    node.rel = "noopener noreferrer";
    return node;
  }

  // An address inside the words: named by its site once the page is read, its host until then.
  function inline(url, opts) {
    const node = anchor(url, "say-link lk-inline");
    node.textContent = hostOf(url) || url;
    node.title = url;
    preview(url, opts).then((value) => {
      if (value.site) node.textContent = value.site;
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
      title.append(mark(host, opts, value.icon), el("span", "", host));
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
      const card = anchor(url, "lk loading");
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

  return { urls, bare, inline, cards, icon, preview };
})();
