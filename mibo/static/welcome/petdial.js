"use strict";
// ---- its dial: while the pointer stays on it (pet.js showQuick), eight round buttons on an arc over
// its head, all as far from it, always in the same places, the name of the one pointed at or focused in a
// pill above them: 聊天, 推荐一条, 勿扰, 截图提问, 外出浏览, 打开浏览器, 推荐记录, 设置. 推荐一条 and 勿扰 are pet.js's;
// the rest are handled here, 聊天, 截图提问 and 外出浏览 in the compact chat (petchat.py). The window takes the
// pointer over the buttons while the dial is out.
(() => {
  const W = paI18n.words("petdial");
  // Lucide-style strokes, 16 px.
  const ICONS = {
    shot: '<path d="M3 7V5a2 2 0 0 1 2-2h2M17 3h2a2 2 0 0 1 2 2v2M21 17v2a2 2 0 0 1-2 2h-2M7 21H5a2 2 0 0 1-2-2v-2"/><circle cx="12" cy="12" r="3.5"/>',
    wonder: '<circle cx="12" cy="12" r="9"/><path d="m15.5 8.5-2 5-5 2 2-5z"/>',
    browser: '<rect x="3" y="4" width="18" height="16" rx="2.5"/><path d="M3 9h18M6.5 6.5h.01M9.5 6.5h.01"/>',
    today: '<path d="M3 12a9 9 0 1 0 2.6-6.4L3 8"/><path d="M3 3.5V8h4.5M12 7.5V12l3 2"/>',
    settings: '<path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0"/><circle cx="16" cy="6" r="2"/><circle cx="10" cy="12" r="2"/><circle cx="18" cy="18" r="2"/>',
  };
  const ORDER = ["chat", "find", "quiet", "shot", "wonder", "browser", "today", "settings"];
  const ACCENTS = { mibo: "#2f8fc4", chatgpt: "#10a37f", claude: "#c96442", deepseek: "#4d6bfe" };
  for (const name of ORDER.slice(3)) {
    const node = uxEl("button", `quick-${name}`);
    node.type = "button";
    node.innerHTML = `<svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true">${ICONS[name]}</svg>`;
    quick.append(node);
  }
  const buttons = ORDER.map((name) => quick.querySelector(`.quick-${name}`));
  const pill = uxEl("div", "dial-name");
  pill.setAttribute("aria-hidden", "true");
  quick.append(pill);
  const nameOf = (button) => button.getAttribute("aria-label") || "";
  for (const [i, button] of buttons.entries()) {
    const name = ORDER[i];
    if (i > 2) button.setAttribute("aria-label", W[name]);
    button.addEventListener("pointerenter", () => named(button));
    button.addEventListener("focus", () => named(button));
    button.addEventListener("pointerleave", () => named(null));
    button.addEventListener("blur", () => named(null));
  }
  // pet.js labels its three from the menu's words; the dial's own names win, so all eight read alike.
  const labels = () => {
    buttons[0].setAttribute("aria-label", W.chat);
    buttons[1].setAttribute("aria-label", W.find);
    buttons[2].setAttribute("aria-label", petSnoozed() ? W.unquiet : W.quiet);
    for (const button of buttons) button.removeAttribute("title");
  };
  function named(button) {
    pill.textContent = button ? nameOf(button) : "";
    pill.classList.toggle("on", Boolean(button));
  }

  // On an arc of eight over its head, centred on the head, all inside the window.
  const RADIUS = 78;
  const SIZE = 26;
  // Round a button for its focus ring (petux.css: 2 px, 1 px off).
  const RING = 3;
  // A node's box at its full size, about where it stands now: the buttons come out small and grow
  // (petux.css), so the box measured as the dial comes out is the small one and would cut their sides.
  const full = (node) => {
    const [x, y, w, h] = petUx.boxOf(node);
    const wide = node.offsetWidth + 2 + 2 * RING;
    const high = node.offsetHeight + 2 + 2 * RING;
    return [Math.floor(x - (wide - w) / 2), Math.floor(y - (high - h) / 2), wide, high];
  };
  function place() {
    const top = (rig?.room ?? PAD[1]) - PAD[1];
    // The head's middle in the pet's 200 by 214, low enough that the arc and the pill stay in the window.
    const cy = Math.max(RADIUS + 42 - HEAD_ROOM, top + PAD[1] + 46);
    for (const [i, button] of buttons.entries()) {
      const a = Math.PI - (i * Math.PI) / (buttons.length - 1);
      button.style.left = `${Math.round(100 + RADIUS * Math.cos(a) - SIZE / 2)}px`;
      button.style.top = `${Math.round(cy - RADIUS * Math.sin(a) - SIZE / 2)}px`;
    }
    pill.style.top = `${Math.round(cy - RADIUS - SIZE / 2 - 24)}px`;
    pet.style.setProperty("--pet-accent", ACCENTS[figureBox.dataset.figure] || ACCENTS.mibo);
  }
  // Out and in with pet.js's own: placed as it comes out, and where the window takes the pointer.
  new MutationObserver(() => {
    const on = quick.classList.contains("on");
    if (on) {
      place();
      labels();
    } else named(null);
    // All of the arc and its pill, so the pointer going from the figure to a button never leaves the window.
    const boxes = [...buttons, pill].map(full);
    const x0 = Math.min(...boxes.map((b) => b[0]));
    const y0 = Math.min(...boxes.map((b) => b[1]));
    const x1 = Math.max(...boxes.map((b) => b[0] + b[2]));
    const y1 = Math.max(...boxes.map((b) => b[1] + b[3]));
    petUx.spot("dial", on ? [[x0, y0, x1 - x0, y1 - y0, 0]] : null);
  }).observe(quick, { attributes: true, attributeFilter: ["class"] });

  // The six handled here; pet.js's listener on the dial sees none of them.
  quick.addEventListener(
    "click",
    (event) => {
      const button = event.target.closest("button");
      const name = button && Object.keys(ACTIONS).find((key) => button.classList.contains(`quick-${key}`));
      if (!name) return;
      event.stopImmediatePropagation();
      hideQuick();
      ACTIONS[name]();
    },
    true,
  );
  const ACTIONS = {
    chat: () => window.pywebview.api.chat("show"),
    // The person picks a part of the screen (compose.py snip); it goes into the compact chat's box as a
    // picture, for the person to ask about.
    async shot() {
      try {
        const response = await api("/api/compose/capture", { lang: paI18n.lang });
        const picture = response.ok ? (await response.json()).picture : "";
        const name = W.shotName;
        if (picture) window.pywebview.api.chat("take", { files: [{ name, type: "image/png", data: picture }] });
      } catch {
        // Nothing taken.
      }
    },
    // "+"'s own 外出浏览 in the compact chat, its subject to be written there; where walks are off, a word that it is not on.
    async wonder() {
      let walks = false;
      try {
        const response = await api("/api/compose");
        walks = response.ok && Boolean((await response.json()).walks);
      } catch {
        // The service is not answering: as off.
      }
      if (walks) window.pywebview.api.chat("take", { wonder: true });
      else sayOne(W.noWonder);
    },
    // The app window, its browser on the last page read there, else on a search page.
    async browser() {
      let address = "";
      try {
        const response = await api("/api/compose/recent");
        if (response.ok) address = (await response.json()).pages?.[0]?.url || "";
      } catch {
        // None known: the search page.
      }
      window.pywebview.api.browse(address || (paI18n.lang === "zh" ? "https://cn.bing.com/" : "https://www.bing.com/"));
    },
    // What it recommended, today's first, and what the person liked: the app window's 推荐记录.
    today: () => window.pywebview.api.open_at("finds"),
    settings: () => window.pywebview.api.open_at("settings"),
  };
})();
