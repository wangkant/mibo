"use strict";
// The sidebar's plain chats under 今天 / 前 7 天 / 更早, and each one's menu: rename in place, delete after one
// question. app.js mounts it with the list it keeps and draws it with the rest of the sidebar.
window.paSideChats = ({ api, confirm, chats, open, reload, rerender }) => {
  const $ = (id) => document.getElementById(id);
  const say = (key) => paI18n.t(`app.${key}`);
  const TITLE_MAX = 60;
  const DAY_MS = 86400000;
  const GROUPS = ["today", "week", "earlier"];
  const titleOf = (chat) => chat.title || say("newChat");
  const find = (id) => chats().find((chat) => chat.id === id);

  // By when each was last written in.
  function groupOf(chat) {
    const at = new Date(chat.at || 0);
    if (Number.isNaN(at.getTime())) return "earlier";
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    if (at >= today) return "today";
    return at >= today.getTime() - 7 * DAY_MS ? "week" : "earlier";
  }
  // Rows are kept by id, so one being renamed or with its menu open is not rebuilt under the pointer.
  const rows = new Map();
  const groups = new Map();
  function groupNode(key) {
    if (!groups.has(key)) {
      const box = document.createElement("section");
      box.className = "side-group";
      const label = document.createElement("h2");
      label.className = "side-group-label";
      label.id = `side-group-${key}`;
      const list = document.createElement("ul");
      list.setAttribute("aria-labelledby", label.id);
      box.append(label, list);
      groups.set(key, box);
    }
    return groups.get(key);
  }

  // The chats with a title, `current` marked as the one on screen.
  function draw(current) {
    const list = $("side-chats");
    const placed = new Set();
    for (const key of GROUPS) {
      const members = chats().filter((chat) => chat.title && groupOf(chat) === key);
      const box = groupNode(key);
      box.querySelector(".side-group-label").textContent = say(key);
      const ul = box.querySelector("ul");
      members.forEach((chat, index) => {
        const row = rows.get(chat.id) || chatRow(chat.id);
        rows.set(chat.id, row);
        placed.add(chat.id);
        paintRow(row, chat, current === chat.id);
        if (ul.children[index] !== row) ul.insertBefore(row, ul.children[index] || null);
      });
      if (members.length && box.parentElement !== list) list.append(box);
      if (!members.length) box.remove();
    }
    for (const [id, row] of rows)
      if (!placed.has(id)) {
        row.remove();
        rows.delete(id);
      }
    // Today first, then the week, then earlier.
    for (const key of GROUPS) if (groups.get(key)?.parentElement === list) list.append(groups.get(key));
  }

  function chatRow(id) {
    const row = document.createElement("li");
    row.className = "side-chat";
    row.dataset.id = id;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "side-chat-open";
    button.append(document.createElement("span"));
    button.firstChild.className = "side-chat-title";
    button.addEventListener("click", () => open(id));
    const more = document.createElement("button");
    more.type = "button";
    more.className = "side-chat-more";
    more.setAttribute("aria-haspopup", "menu");
    more.setAttribute("aria-expanded", "false");
    more.innerHTML =
      '<svg class="i" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/><circle cx="5" cy="12" r="1"/></svg>';
    more.addEventListener("click", (event) => {
      event.stopPropagation();
      if (menu.id === id) closeMenu();
      else openMenu(id, more);
    });
    row.append(button, more);
    return row;
  }

  function paintRow(row, chat, on) {
    if (row.classList.contains("renaming")) return;
    const title = titleOf(chat);
    const button = row.querySelector(".side-chat-open");
    row.querySelector(".side-chat-title").textContent = title;
    button.title = title;
    row.classList.toggle("active", on);
    row.classList.toggle("untitled", !chat.title);
    // A 无痕对话 wears its mark in the list too (app.css).
    row.classList.toggle("private", Boolean(chat.private));
    if (chat.private) button.title = `${title} · ${say("privateChat")}`;
    if (on) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
    row.querySelector(".side-chat-more").setAttribute("aria-label", say("more").replace("{title}", title));
  }

  // ---- A chat's menu: rename, delete
  const menu = { id: "", from: null };
  function openMenu(id, from) {
    closeMenu();
    menu.id = id;
    menu.from = from;
    from.setAttribute("aria-expanded", "true");
    from.closest(".side-chat").classList.add("menu-open");
    $("side-delete").querySelector("span").textContent = say("delete");
    const box = $("side-menu");
    box.hidden = false;
    // Under the button, its right edge on the button's, so it stays over the sidebar.
    const at = from.getBoundingClientRect();
    const left = at.right - box.offsetWidth;
    const below = at.bottom + 4 + box.offsetHeight < innerHeight - 8;
    box.style.left = `${Math.max(8, left)}px`;
    box.style.top = `${below ? at.bottom + 4 : at.top - 4 - box.offsetHeight}px`;
    $("side-rename").focus();
  }
  function closeMenu(focusBack = false) {
    if (!menu.id) return;
    $("side-menu").hidden = true;
    menu.from.setAttribute("aria-expanded", "false");
    menu.from.closest(".side-chat")?.classList.remove("menu-open");
    if (focusBack) menu.from.focus();
    menu.id = "";
    menu.from = null;
  }

  // Delete asks once, in the middle of the window, then goes.
  async function deleteChat() {
    const id = menu.id;
    closeMenu();
    if (!(await confirm({ title: say("deleteAsk"), text: say("deleteNote"), ok: say("delete") }))) return;
    try {
      await api("chats/delete", { id });
    } catch {
      // Not deleted: the list shows it as it is.
    }
    await reload();
  }

  // Rename in place, in the sidebar's row or in the bar: Enter or leaving the field keeps it,
  // Escape leaves it as it was.
  function rename(id = menu.id, where = "side") {
    closeMenu();
    const row = rows.get(id);
    const chat = find(id);
    if (!chat || !row) return;
    const field = document.createElement("input");
    field.className = where === "bar" ? "titlebar-input" : "side-chat-input";
    field.maxLength = TITLE_MAX;
    field.value = chat.title;
    field.placeholder = say("newChat");
    field.setAttribute("aria-label", say("renameLabel"));
    if (where === "bar") $("page-title").replaceChildren(field);
    else {
      row.classList.add("renaming");
      row.prepend(field);
    }
    field.focus();
    field.select();
    let done = false;
    const finish = async (keep) => {
      if (done) return;
      done = true;
      const title = field.value.trim();
      field.remove();
      row.classList.remove("renaming");
      if (keep && title && title !== chat.title) {
        // Shown at once; the list read after says what was kept.
        chat.title = title;
        rerender();
        try {
          await api("chats/rename", { id, title });
        } catch {
          // Refused: the list read below puts the old name back.
        }
        await reload();
      } else rerender();
      if (document.activeElement === document.body)
        (where === "bar" ? $("page-title").querySelector("button") : row.querySelector(".side-chat-open"))?.focus();
    };
    field.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.isComposing) {
        event.preventDefault();
        finish(true);
      } else if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        finish(false);
      }
    });
    field.addEventListener("blur", () => finish(true));
  }

  $("side-rename").addEventListener("click", () => rename());
  $("side-delete").addEventListener("click", deleteChat);
  $("side-menu").addEventListener("keydown", (event) => {
    const items = [$("side-rename"), $("side-delete")];
    const step = { ArrowDown: 1, ArrowUp: -1 }[event.key];
    if (!step) return;
    event.preventDefault();
    items[(items.indexOf(document.activeElement) + step + items.length) % items.length].focus();
  });
  document.addEventListener("click", (event) => {
    if (menu.id && !event.target.closest("#side-menu")) closeMenu();
  });
  $("side-chats").addEventListener("scroll", () => closeMenu());
  window.addEventListener("resize", () => closeMenu());

  return { draw, rename, closeMenu, menuOpen: () => Boolean(menu.id), titleOf };
};
