"use strict";
// The asking card in the chat that offers a skill from the market before the reply (skills/offer.py): the skill's
// name as the question, what it does in one faint line, then 安装 / 不安装. Only a press here answers it (POST
// /api/skills/offer); with 安装 the app installs it, every check of the market included, and the reply goes on with it.
(() => {
  const SVG = "http://www.w3.org/2000/svg";
  const ICON = "M5.5 4.5h9l4 4v11a1 1 0 0 1-1 1h-12a1 1 0 0 1-1-1v-14a1 1 0 0 1 1-1zM14.5 4.5v4h4M8.5 12.5h7M8.5 16h5";
  let shown = null;

  function el(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  }
  function fill(text, values) {
    return text.replace(/\{(\w+)\}/g, (_, key) => values[key] ?? "");
  }
  function head(title, meta) {
    const node = el("div", "op-card-head");
    const tile = el("span", "op-card-icon");
    const mark = document.createElementNS(SVG, "svg");
    mark.setAttribute("viewBox", "0 0 24 24");
    mark.setAttribute("aria-hidden", "true");
    mark.setAttribute("class", "i");
    const path = document.createElementNS(SVG, "path");
    path.setAttribute("d", ICON);
    mark.append(path);
    tile.append(mark);
    const words = el("div", "op-card-words");
    words.append(el("p", "op-card-title", title), el("p", "op-card-meta", meta));
    node.append(tile, words);
    return node;
  }

  // `card` from GET /api/skills/offer shown under the waiting row; null takes an unanswered one away.
  function show(waiting, card, keepEnd = () => {}) {
    const t = paI18n.words("skilloffer");
    if (shown && (!card || shown.dataset.id !== card.id)) {
      if (!shown.classList.contains("answered")) shown.remove();
      shown = null;
    }
    if (!card || shown || !waiting) return;
    const title = card.title[paI18n.lang] || card.title.en || card.name;
    // One line of facts joined by dots: the sentence's own full stop would sit before the first one.
    const about = (card.about[paI18n.lang] || card.about.en || "").replace(/[。.]$/, "");
    const meta = fill(t.meta, { about, publisher: card.publisher }) + (card.scripts ? ` · ${t.scripts}` : "");
    const node = el("div", "op-card skill-offer-card");
    node.dataset.id = card.id;
    node.append(head(fill(t.ask, { title }), meta));
    const answer = async (yes) => {
      for (const b of node.querySelectorAll("button")) b.disabled = true;
      node.classList.add("answered");
      const told = el("p", "op-card-told", yes ? t.installing : t.declined);
      node.append(told);
      try {
        const response = await fetch("/api/skills/offer", {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json",
            "X-Mibo-Setup-Token": sessionStorage.getItem("mibo-setup-token") || "",
            "X-Mibo-Window": sessionStorage.getItem("mibo-frame") || "" },
          body: JSON.stringify({ id: card.id, yes }),
        });
        const value = await response.json().catch(() => ({}));
        if (!value.ok) told.textContent = t.gone;
        else if (yes) told.textContent = value.installed ? fill(t.done, { title })
          : fill(t.failed, { why: t.errors[value.error] || t.errors.other });
      } catch {
        told.textContent = t.gone;
      }
      keepEnd();
    };
    const buttons = el("div", "op-card-buttons");
    for (const [cls, text, yes] of [["pa-btn-primary", t.yes, true], ["pa-btn-ghost", t.no, false]]) {
      const b = el("button", `pa-btn ${cls} pa-btn-sm`, text);
      b.type = "button";
      b.addEventListener("click", () => answer(yes));
      buttons.append(b);
    }
    node.append(buttons);
    waiting.after(node);
    shown = node;
    const label = waiting.querySelector(".doing");
    if (label) label.textContent = t.waiting;
    keepEnd();
  }

  window.paSkillOffer = { show };
})();
