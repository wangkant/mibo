"use strict";
// What the chat's scripts draw with: elements, buttons, Lucide-style icons, a link opened the way every link in the
// app opens, a day's line, and the headers a press from the app's own page carries.
window.paKit = (() => {
  const SVG = "http://www.w3.org/2000/svg";
  // Lucide-style strokes.
  const I = {
    up: '<path d="M12 19V5M5 12l7-7 7 7"/>',
    stop: '<rect x="5" y="5" width="14" height="14" rx="2.5"/>',
    reply: '<path d="M9 17l-5-5 5-5"/><path d="M20 18v-2a4 4 0 0 0-4-4H4"/>',
    heart:
      '<path d="M19 14c1.49-1.46 3-3.21 3-5.5A5.5 5.5 0 0 0 16.5 3c-1.76 0-3 .5-4.5 2-1.5-1.5-2.74-2-4.5-2A5.5 5.5 0 0 0 2 8.5c0 2.3 1.5 4.05 3 5.5l7 7z"/>',
    open: '<path d="M15 3h6v6"/><path d="M10 14 21 3"/><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>',
    more: '<circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/><circle cx="5" cy="12" r="1"/>',
    tv: '<rect x="2" y="7" width="20" height="15" rx="2"/><path d="m17 2-5 5-5-5"/>',
    video: '<rect x="2" y="4" width="20" height="16" rx="4"/><path d="m10 9 5 3-5 3z"/>',
    file: '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M16 13H8M16 17H8M10 9H8"/>',
    branch: '<path d="M6 3v12"/><circle cx="18" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M18 9a9 9 0 0 1-9 9"/>',
    post: '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
    globe: '<circle cx="12" cy="12" r="10"/><path d="M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20"/><path d="M2 12h20"/>',
    shrink: '<path d="m14 10 7-7"/><path d="M20 10h-6V4"/><path d="m3 21 7-7"/><path d="M4 14h6v6"/>',
    x: '<path d="M18 6 6 18M6 6l12 12"/>',
    skip: '<circle cx="12" cy="12" r="10"/><path d="m15 9-6 6M9 9l6 6"/>',
    less: '<circle cx="12" cy="12" r="10"/><path d="M8 12h8"/>',
    raise: '<circle cx="12" cy="12" r="10"/><path d="M8 12h8M12 8v8"/>',
    seen: '<path d="M20 6 9 17l-5-5"/>',
    alert: '<circle cx="12" cy="12" r="10"/><path d="M12 8v4M12 16h.01"/>',
    talk: '<path d="M7.9 20A9 9 0 1 0 4 16.1L2 22z"/>',
    calendar: '<rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/>',
    compass: '<circle cx="12" cy="12" r="10"/><path d="m16.24 7.76-2.12 6.36-6.36 2.12 2.12-6.36z"/>',
    help: '<circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><path d="M12 17h.01"/>',
    // A ghost: the 无痕对话.
    ghost: '<path d="M9 10h.01M15 10h.01M12 2a8 8 0 0 0-8 8v12l3-3 2.5 2.5L12 19l2.5 2.5L17 19l3 3V10a8 8 0 0 0-8-8z"/>',
  };

  function el(tag, className = "", text = "") {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text) node.textContent = text;
    return node;
  }
  function button(className, text, run) {
    const node = el("button", className, text);
    node.type = "button";
    node.addEventListener("click", run);
    return node;
  }
  function svg(paths, className = "i") {
    const node = document.createElementNS(SVG, "svg");
    node.setAttribute("viewBox", "0 0 24 24");
    node.setAttribute("aria-hidden", "true");
    node.setAttribute("class", className);
    node.innerHTML = paths;
    return node;
  }
  // A button holding only an icon, named for screen readers and on hover.
  function iconButton(className, paths, label, run) {
    const node = button(className, "", run);
    node.append(svg(paths));
    node.setAttribute("aria-label", label);
    node.title = label;
    return node;
  }
  // A link opened the way every link in the app opens.
  function anchor(url, className = "") {
    const node = el("a", className);
    node.href = url;
    node.target = "_blank";
    node.rel = "noopener noreferrer";
    return node;
  }
  const hostOf = (url) => {
    try {
      return new URL(url).hostname.replace(/^www\./, "");
    } catch {
      return "";
    }
  };
  const fill = (text, values) => text.replace(/\{(\w+)\}/g, (_, key) => values[key] ?? "");
  const motion = () => (matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth");
  // A press from the app's own page: its token and its window's key.
  const pressHeaders = () => ({ "Content-Type": "application/json",
    "X-Mibo-Setup-Token": sessionStorage.getItem("mibo-setup-token") || "",
    "X-Mibo-Window": sessionStorage.getItem("mibo-frame") || "" });

  // 今天 · 11月20日 周五: `w` holds the section's week, today and yesterday.
  function dayLabel(time, w) {
    const date = new Date(time);
    const start = (d) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
    const back = Math.round((start(new Date()) - start(date)) / 86400000);
    const year = date.getFullYear() !== new Date().getFullYear();
    const day = w.week
      ? `${year ? `${date.getFullYear()}年` : ""}${date.getMonth() + 1}月${date.getDate()}日 ${w.week[date.getDay()]}`
      : date.toLocaleDateString(paI18n.locale, { weekday: "short", month: "short", day: "numeric", ...(year ? { year: "numeric" } : {}) });
    const near = back === 0 ? w.today : back === 1 ? w.yesterday : "";
    return near ? `${near} · ${day}` : day;
  }

  return { I, el, button, svg, iconButton, anchor, hostOf, fill, motion, pressHeaders, dayLabel };
})();
