"use strict";
// Beside the pet besides its finds, in the card's frame (card.js panel): what to do with something dropped
// on it, and a line said for a moment. The compact chat beside it is a window of its own (petchat.py,
// petclick.js); what to do with a drop goes there, as a message with it attached.
//
// petUx is what pet.js and the other pieces ask of these: whether the pet is to rest (tucked, petedge.js;
// the chat out, petclick.js) and where its window takes the pointer besides the figure.
const UX_WORDS = paI18n.words("petbox");
// The room over the figure's head in its window (window.py PET_SIZE), in which the dial and the line show.
const HEAD_ROOM = 64;
const OFFER_MS = 20000;
const SAID_ONE_MS = 4000;
// As the chat attaches (chat.js ATTACH, TEXT_KINDS): what the service takes. Words this long or shorter go
// in the box as a quote, as the chat pastes them (plus.js QUOTE_MAX); longer, as a text file.
const DROP = { most: 4, picked: 20 * 1024 * 1024, picture: 1000000, side: 1600, file: 512 * 1024, quote: 2000 };
// The scripts of the languages not written in Latin letters.
const SCRIPTS = { zh: /[一-鿿]/, "zh-TW": /[一-鿿]/, ja: /[\u3040-\u30ff]/, ko: /[\uac00-\ud7af]/, ru: /[\u0400-\u04ff]/ };
const DROP_PICTURES = new Set(["image/png", "image/jpeg", "image/webp", "image/gif"]);
const DROP_TEXTS = new Set(
  ("txt text md markdown rst csv tsv json jsonl yaml yml toml ini cfg conf log xml html htm " +
    "css scss js mjs cjs ts tsx jsx vue py ipynb java kt kts scala go rs c h cc cpp hpp cs m mm " +
    "swift rb php pl lua r sql sh bash zsh ps1 bat cmd tex bib srt vtt diff patch").split(" "),
);
const UX_ICONS = {
  x: '<path d="M18 6 6 18M6 6l12 12"/>',
};

window.petUx = (() => {
  const spots = new Map();
  let bare = false;
  // Where the window takes the pointer besides the figure: each piece's boxes, CSS px of the pet's cell
  // (its 200 by 278, the room over its head included); `bare` while the figure itself takes none.
  function spot(key, boxes) {
    if (boxes?.length) spots.set(key, boxes);
    else spots.delete(key);
    window.pywebview.api.spots([...spots.values()].flat(), bare);
  }
  function setBare(on) {
    bare = on;
    spot("", null);
  }
  // A node's box in the pet's cell, a pixel more all round, its corners as round as `corner`.
  function boxOf(node, corner = 0) {
    const cell = pet.getBoundingClientRect();
    const r = node.getBoundingClientRect();
    return [Math.floor(r.left - cell.left) - 1, Math.floor(r.top - cell.top + HEAD_ROOM) - 1, Math.ceil(r.width) + 2, Math.ceil(r.height) + 2, corner];
  }
  return { words: UX_WORDS, spot, setBare, boxOf, busy: () => "edge" in pet.dataset };
})();

const uxEl = (tag, cls, text) => {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text) node.textContent = text;
  return node;
};
function uxButton(cls, label, icon, handler) {
  const node = uxEl("button", cls, icon ? "" : label);
  node.type = "button";
  node.setAttribute("aria-label", label);
  if (icon) {
    node.title = label;
    node.innerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true">${UX_ICONS[icon]}</svg>`;
  }
  node.addEventListener("click", (event) => {
    event.stopPropagation();
    handler();
  });
  return node;
}

// One line in the frame for a moment: what cannot be taken, a picture saved.
function sayOne(text, ms = SAID_ONE_MS) {
  const node = uxEl("div", "box");
  node.append(uxEl("p", "box-text", text));
  return card.panel(node, { ms });
}

// ---- something dropped on it: one file or several, a link, or words selected somewhere. As it comes
// near with the button held (window.py says so through petCursor), the whole of its window takes the
// drag, so it notices before the figure is reached; over it, it opens its arms. Let go, it offers what
// it can do with that kind of thing; the choice goes to the compact chat (petchat.py) as a message with
// it attached, as the chat's own drop attaches, sent at once or left for the person to write.
CLIPS.reach = async (c, until) => {
  c.face("round");
  c.wait(260).then(() => c.face("happy"));
  await Promise.all([
    arms(c, [R, [0, 0, 64]], [R, [0, 0, -64]], 320, { hold: true, ease: OUT }),
    c.go("body", [R, [0, -1.5, 0, 0.98, 1.03]], 320, { hold: true, ease: OUT }),
    c.go("antenna", [R, [0, 0, 8], [0, 0, -3], R], 600, { at: [0, 0.3, 0.7, 1], delay: 60 }),
  ]);
  await c.until(until);
};
PAINTED.reach = async (c, until) => {
  c.show(either("surprised"));
  await c.go("root", [R, [0, -4], R], 340, { at: [0, 0.45, 1], ease: [OUT, IN] });
  c.show(either("give", "wave1"));
  await c.until(until);
};
let reaching = null;
function reach(on) {
  if (on === Boolean(reaching)) return;
  if (!on) {
    reaching.end();
    reaching = null;
    return;
  }
  if (pose !== "standing" || hushed || petUx.busy()) return;
  const own = {};
  own.done = new Promise((resolve) => (own.end = resolve));
  reaching = own;
  hideQuick();
  play("reach", own.done);
}
let nearHeld = false;
const cursorBefore = petCursor;
window.petCursor = (at) => {
  cursorBefore(at);
  const held = Boolean(at?.[2]) && pose === "standing" && !hushed && !dragging && !petUx.busy() && !("off" in pet.dataset);
  if (held === nearHeld) return;
  nearHeld = held;
  petUx.spot("drop", held ? [[0, 0, 200, 214 + HEAD_ROOM, 0]] : null);
  if (!held) setTimeout(() => !nearHeld && reach(false), 400);
};
let over = 0;
document.addEventListener("dragenter", (event) => {
  event.preventDefault();
  if (over++ === 0) reach(true);
});
document.addEventListener("dragover", (event) => {
  event.preventDefault();
  event.dataTransfer.dropEffect = "copy";
});
document.addEventListener("dragleave", () => {
  if (--over <= 0) {
    over = 0;
    reach(false);
  }
});
document.addEventListener("drop", (event) => {
  event.preventDefault();
  over = 0;
  reach(false);
  nearHeld = false;
  petUx.spot("drop", null);
  take(event.dataTransfer);
});

const extOf = (name) => (/\.([^.]+)$/.exec(name)?.[1] || "").toLowerCase();
const base64Of = (blob) =>
  new Promise((done, fail) => {
    const reader = new FileReader();
    reader.onload = () => done(String(reader.result).split(",")[1] || "");
    reader.onerror = () => fail(reader.error);
    reader.readAsDataURL(blob);
  });
// A picture as the chat sends it: as dropped when small enough, else drawn smaller as WebP.
async function sendable(file) {
  const bitmap = await createImageBitmap(file);
  try {
    let scale = Math.min(1, DROP.side / Math.max(bitmap.width, bitmap.height));
    if (scale === 1 && file.size <= DROP.picture) return file;
    for (;;) {
      const canvas = document.createElement("canvas");
      canvas.width = Math.max(1, Math.round(bitmap.width * scale));
      canvas.height = Math.max(1, Math.round(bitmap.height * scale));
      canvas.getContext("2d").drawImage(bitmap, 0, 0, canvas.width, canvas.height);
      const blob = await new Promise((done) => canvas.toBlob(done, "image/webp", 0.85));
      if (blob.size <= DROP.picture) return blob;
      scale *= 0.75;
    }
  } finally {
    bitmap.close();
  }
}
const hostOf = (url) => {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
};

async function take(data) {
  if (pose !== "standing" || hushed) return;
  const files = [...data.files];
  if (files.length) {
    if (files.length > DROP.most) return sayOne(UX_WORDS.tooMany);
    const given = [];
    for (const file of files) {
      const kind = DROP_PICTURES.has(file.type) ? "picture" : DROP_TEXTS.has(extOf(file.name)) ? "file" : "";
      if (!kind) return sayOne(UX_WORDS.cannot);
      if (file.size > (kind === "picture" ? DROP.picked : DROP.file)) return sayOne(UX_WORDS.tooBig);
      try {
        const blob = kind === "picture" ? await sendable(file) : file;
        given.push({ kind, name: file.name || "image.png", type: blob.type || "text/plain", data: await base64Of(blob) });
      } catch {
        return sayOne(UX_WORDS.cannot);
      }
    }
    const pictures = given.every((item) => item.kind === "picture");
    const what = pictures ? paI18n.t("petbox.pictures", { count: given.length }) : given.map((item) => item.name).join("、");
    return offer({ files: given }, what, pictures ? ["describe", "ask"] : ["summary", "ask"]);
  }
  const text = data.getData("text/plain").trim();
  const link = data.getData("text/uri-list").split(/\r?\n/).find((line) => line && !line.startsWith("#")) || (/^https?:\/\/\S+$/.test(text) ? text : "");
  if (/^https?:\/\//.test(link)) return offer({ text: link, link }, hostOf(link), ["summary", "ask", "open"]);
  if (text) {
    const blob = new Blob([text], { type: "text/plain" });
    if (blob.size > DROP.file) return sayOne(UX_WORDS.tooBig);
    const given =
      text.length <= DROP.quote
        ? { text: text.split(/\r?\n/).map((line) => `> ${line}`).join("\n") + "\n" }
        : { files: [{ kind: "file", name: "selection.txt", type: "text/plain", data: await base64Of(blob) }] };
    // Translated only when it is not already in the person's language: written in its script, or in Latin letters.
    const script = SCRIPTS[paI18n.lang];
    const theirs = script ? script.test(text) : !/[^\u0000-ɏ -⁯]/.test(text);
    return offer(given, UX_WORDS.selection, theirs ? ["summary", "ask"] : ["summary", "translate", "ask"]);
  }
  sayOne(UX_WORDS.cannot);
}
async function offer(given, what, actions) {
  const node = uxEl("div", "box");
  node.setAttribute("role", "group");
  node.setAttribute("aria-label", UX_WORDS.choose);
  node.append(uxEl("p", "box-what", what));
  const row = uxEl("div", "box-actions");
  for (const action of actions)
    row.append(
      uxButton("box-act", UX_WORDS.actions[action], "", () => {
        card.close("seen");
        if (action === "open") return window.pywebview.api.browse(given.link);
        // A quote or a link goes before the question the person writes; with an action, after its words.
        const send = action === "ask" ? "" : UX_WORDS.asks[given.link && action === "summary" ? "page" : action];
        window.pywebview.api.chat("take", { ...given, send });
      }),
    );
  row.append(uxButton("box-shut", UX_WORDS.shut, "x", () => card.close("seen")));
  node.append(row);
  if (await card.panel(node, { ms: OFFER_MS })) {
    play("talk");
    row.querySelector(".box-act").focus({ preventScroll: true });
  }
}
