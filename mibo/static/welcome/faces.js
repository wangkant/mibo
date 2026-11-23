"use strict";
// The character's figure on the app page: its face in a circle, its head and shoulders, or its whole figure, as a
// painted sheet or a drawing, or the picture of its own a character may have. app.js mounts it with what it reads
// the figure from: the character's state and the figure the window names.
window.paFaces = ({ api, picture, state, windowFigure }) => {
  // As welcome.PET_FIGURES: the four characters' (one's own is Mibo too).
  const FIGURES = ["mibo", "chatgpt", "deepseek", "claude"];
  // A figure's frame is 320 by 380; its head sits in this square, as parts of the frame's width,
  // and its head and shoulders in this larger one.
  const FRAME_TALL = 380 / 320;
  const HEAD = { size: 0.62, left: 0.19, top: 0.12 };
  const BUST = { size: 0.8, left: 0.1, top: 0.07 };
  // A painted figure is a sheet of four frames: in a row, two by two, or in a column.
  const SHEETS = [4, 2, 1];

  // The figure: as just picked on this page, else as the window says, else the character's own, else the first.
  let picked = "";
  function figure() {
    if (FIGURES.includes(picked)) return picked;
    if (FIGURES.includes(windowFigure())) return windowFigure();
    return FIGURES.includes(state()?.avatar) ? state().avatar : FIGURES[0];
  }

  // Mibo is drawn in the colours chosen for it (panels/colors.py): asked for again when they change.
  let paint = "";
  // A figure is a painted sheet (<key>.webp) when there is one, else its drawing (<key>.svg).
  const sheets = new Map();
  function sheet(key) {
    if (!sheets.has(key))
      sheets.set(
        key,
        new Promise((resolve) => {
          const probe = new Image();
          probe.addEventListener("load", () => {
            // The grid whose shape is nearest the sheet's: four frames across, two by two, or one across.
            const shape = Math.log(probe.naturalWidth / probe.naturalHeight / (1 / FRAME_TALL));
            const cols = SHEETS.reduce((best, n) =>
              Math.abs(shape - Math.log(n / (4 / n))) < Math.abs(shape - Math.log(best / (4 / best))) ? n : best,
            );
            resolve({ src: probe.src, cols });
          });
          const drawing = () =>
            resolve({ src: `/assets/figures/${key}.svg${key === "mibo" && paint ? `?c=${paint}` : ""}`, cols: 1 });
          probe.addEventListener("error", drawing);
          // Mibo is only ever a drawing: no sheet is looked for.
          if (key === "mibo") drawing();
          else probe.src = `/assets/figures/${key}.webp`;
        }),
      );
    return sheets.get(key);
  }
  async function repaint() {
    try {
      const value = await api("look/colors");
      const now = `${value.accent}${value.shell}`.replaceAll("#", "");
      const changed = paint && now !== paint;
      paint = now;
      if (!changed) return;
      sheets.delete("mibo");
      for (const box of document.querySelectorAll('[data-figure="mibo"]')) draw(box);
    } catch {
      // Not let in yet: it stays as it was drawn.
    }
  }
  // A character with a picture of its own (PERSONA_AVATAR "own") has it for a face; the whole figure stays.
  const owned = new Map();
  function wanted(box) {
    // A box drawn for one named figure (a choice on the first run) keeps it.
    if (box.dataset.fixed) return box.dataset.fixed;
    const own = state()?.avatar === "own" && state().ownAvatar;
    return own && !box.classList.contains("pa-figure") ? `own:${state().ownAvatar}` : figure();
  }
  function ownSheet(key) {
    if (!owned.has(key))
      owned.set(
        key,
        picture("/api/avatar").then(
          (src) => ({ src, cols: 1, own: true }),
          () => sheet(figure()),
        ),
      );
    return owned.get(key);
  }
  // The figure's first frame in `box`: whole, or cropped to the head in a square.
  async function draw(box) {
    const key = wanted(box);
    box.dataset.figure = key;
    const { src, cols, own } = key.startsWith("own:") ? await ownSheet(key) : await sheet(key);
    if (box.dataset.figure !== key) return;
    const crop = own ? null : box.classList.contains("pa-face") ? HEAD : box.classList.contains("pa-bust") ? BUST : null;
    const width = crop ? 100 / crop.size : 100;
    let img = box.querySelector("img");
    if (!img) {
      img = document.createElement("img");
      img.alt = "";
      img.decoding = "async";
      img.addEventListener("load", () => img.classList.add("ready"));
      box.append(img);
    }
    img.style.width = `${cols * width}%`;
    img.style.height = own ? "100%" : "";
    img.style.objectFit = own ? "cover" : "";
    img.style.left = crop ? `${-crop.left * width}%` : "0";
    img.style.top = crop ? `${-crop.top * width * FRAME_TALL}%` : "0";
    if (img.getAttribute("src") !== src) {
      img.classList.remove("ready");
      img.src = src;
    }
  }
  // A box of `kind` (pa-face, pa-bust, pa-figure), sized by the caller's class; with `fixed`, one named figure.
  function node(kind, className = "", fixed = "") {
    const box = document.createElement("span");
    box.className = `${kind} ${className}`.trim();
    if (fixed) box.dataset.fixed = fixed;
    box.setAttribute("aria-hidden", "true");
    draw(box);
    return box;
  }
  // The figure changed: every face on the page follows, and the page takes its colour.
  function redraw() {
    document.documentElement.dataset.figure = figure();
    for (const box of document.querySelectorAll(".pa-face, .pa-figure, .pa-bust"))
      if (box.dataset.figure !== wanted(box)) draw(box);
  }
  // One picked on this page; "" gives the window's back.
  function pick(key) {
    picked = key;
    redraw();
  }

  return { keys: FIGURES, figure, node, redraw, repaint, pick };
};
