"use strict";
// The app page as the small chat beside the pet (petchat.py loads it at /compact): the main conversation
// alone, under a head of its own with the way to the whole window and a button to put it away. Everything
// else is the chat itself (chat.js), so it changes as the chat does. In the whole window this only takes
// up the place the small chat was at (arrive).
window.paCompact = (() => {
  const say = (key) => paI18n.t(`compact.${key}`);
  const pause = (ms) => new Promise((done) => setTimeout(done, ms));
  // A menu or a dialog that shows: a card's menu is kept in the page undrawn, not hidden.
  const menuOut = () => [...document.querySelectorAll('[role="menu"], dialog[open]')].some((node) => node.getClientRects().length);

  // The main chat once its box is there.
  async function mainChat(ms = 6000) {
    for (let t = 0; ; t += 100) {
      const root = document.querySelector("#chat-view .chat-main");
      if (root && !root.hidden && root.querySelector(".chat-input")) return root;
      if (t >= ms) return null;
      await pause(100);
    }
  }

  // ---- In the whole window: the place in the conversation and the draft the small chat had.
  async function arrive(place) {
    const root = await mainChat();
    if (!root) return;
    const input = root.querySelector(".chat-input");
    if (place.draft && !input.value) {
      input.value = place.draft;
      input.dispatchEvent(new Event("input"));
    }
    if (place.bottom || !place.seq) return input.focus();
    // After the chat has laid out its history and gone to its end.
    for (let t = 0; t < 3000; t += 150) {
      const node = root.querySelector(`[data-seq="${place.seq}"]`);
      if (node) {
        await pause(200);
        node.scrollIntoView({ block: "start" });
        return;
      }
      await pause(150);
    }
  }
  if (location.pathname !== "/compact") return { arrive };

  document.body.classList.add("compact");
  const head = document.createElement("header");
  head.className = "compact-head";
  const name = document.createElement("span");
  name.className = "compact-name";
  const button = (cls, icon, run) => {
    const node = document.createElement("button");
    node.type = "button";
    node.className = `compact-button ${cls}`;
    node.innerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true">${icon}</svg>`;
    node.addEventListener("click", run);
    return node;
  };
  const full = button("compact-full", '<path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7"/>', () => openFull());
  const away = button("compact-away", '<path d="M18 6 6 18M6 6l12 12"/>', () => window.pywebview.api.away());
  head.append(name, full, away);
  document.body.prepend(head);

  function label() {
    name.textContent = document.getElementById("side-main-name")?.textContent || "";
    for (const [node, key] of [[full, "full"], [away, "away"]]) {
      node.title = say(key);
      node.setAttribute("aria-label", say(key));
    }
  }
  new MutationObserver(label).observe(document.getElementById("side-main-name"), { childList: true, characterData: true, subtree: true });

  // Where it is in the conversation: the first message in view, or at the end; and the unsent words,
  // which go along and leave the small chat.
  async function openFull() {
    const root = await mainChat(0);
    const place = { seq: 0, bottom: true, draft: "" };
    if (root) {
      const scroll = root.querySelector(".chat-scroll");
      const top = scroll.getBoundingClientRect().top;
      place.bottom = scroll.scrollHeight - scroll.scrollTop - scroll.clientHeight < 24;
      const first = [...root.querySelectorAll("[data-seq]")].find((node) => node.getBoundingClientRect().bottom > top + 8);
      place.seq = Number(first?.dataset.seq) || 0;
      const input = root.querySelector(".chat-input");
      place.draft = input.value;
      input.value = "";
      input.dispatchEvent(new Event("input"));
    }
    window.pywebview.api.full(place);
  }

  // Esc puts it away, unless it closes a menu or a dialog, or picks an input method's word. Taken before the
  // box sees it: there it would stop a reply on its way (chat.js), which goes on and is said by the pet.
  document.addEventListener(
    "keydown",
    (event) => {
      if (event.key !== "Escape" || event.isComposing) return;
      if (menuOut()) return;
      event.stopPropagation();
      window.pywebview.api.away();
    },
    true,
  );

  // Settings are not for a window this small: they open in the whole one, and this one stays on the chat.
  new MutationObserver(() => {
    if (document.getElementById("setup-view").hidden) return;
    window.pywebview.api.full({ goto: "settings" });
    document.getElementById("side-main").click();
  }).observe(document.getElementById("setup-view"), { attributes: true, attributeFilter: ["hidden"] });

  // Brought out (petchat.py): the box takes the keyboard.
  async function shown() {
    label();
    const root = await mainChat();
    if (root && !menuOut()) root.querySelector(".chat-input").focus();
  }

  // Something given to the pet to go with a message (petbox.js): files dropped on the chat as a person drops
  // them, a link or words in the box; sent at once when `send` holds the words to send with it, else left
  // for the person to write. `wonder`: "+"'s 外出浏览, its subject still to be written.
  async function take(given) {
    const root = await mainChat();
    if (!root) return;
    const input = root.querySelector(".chat-input");
    const files = given.files || [];
    if (files.length) {
      const moved = new DataTransfer();
      for (const file of files)
        moved.items.add(new File([Uint8Array.from(atob(file.data), (c) => c.charCodeAt(0))], file.name, { type: file.type }));
      const before = root.querySelectorAll(".chat-tray > *").length;
      root.dispatchEvent(new DragEvent("drop", { dataTransfer: moved, bubbles: true, cancelable: true }));
      for (let t = 0; t < 4000 && root.querySelectorAll(".chat-tray > *").length < before + files.length; t += 100) await pause(100);
    }
    const words = [given.text, given.send].filter(Boolean).join("\n");
    if (words) {
      input.value = input.value.trim() ? `${input.value}\n${words}` : words;
      input.dispatchEvent(new Event("input"));
    }
    // Sent as Enter in the box sends: the form's own submit would stop a reply on its way instead.
    if (given.send)
      return input.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true }));
    if (given.wonder) {
      root.querySelector(".chat-attach").click();
      for (let t = 0; t < 2000; t += 100) {
        const entry = [...root.querySelectorAll(".plus-item")].find((node) => node.querySelector(".plus-label")?.textContent === paI18n.t("plus.wonder"));
        if (entry) {
          entry.click();
          break;
        }
        await pause(100);
      }
      // Not offered (no model yet, or no walks): the menu goes again.
      if (menuOut()) root.querySelector(".chat-attach").click();
    }
    input.focus();
    input.setSelectionRange(input.value.length, input.value.length);
  }

  return { arrive, shown, take };
})();
