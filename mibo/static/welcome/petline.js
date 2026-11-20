"use strict";
// ---- the line over its head while the character works in a chat. window.py says when a reply starts and
// ends (petActivity); meanwhile the main chat's step is asked for (GET /api/chat/doing) and, when it is a
// search, a read, the browser, a program or a command, shown in the chat's own words (activity.js) with
// its icon. A press on the line opens the compact chat, at its end where the reply is; its Stop ends the
// turn as the chat's does. A step waiting on the person's press says "需要你确认" and opens the chat too.
// Thinking alone shows nothing. The line gives way to anything beside the pet (the compact chat, a card,
// the frame, the dial) and to a tucked pet.
(() => {
  const STEP_MS = 1200;
  const W = paI18n.words("petline");
  // Steps whose card waits on the person, and where that card is read.
  const CARDS = { operate: "/api/browser/confirm", shell: "/api/shell/card", desk: "/api/programs/card", mcp: "/api/mcp/card" };
  const QUIET = new Set(["write", "recall"]);
  const line = uxEl("div", "pet-line");
  const open = uxEl("button", "line-open");
  open.type = "button";
  open.append(uxEl("span", "doing"));
  const stop = uxEl("button", "line-stop");
  stop.type = "button";
  stop.title = W.stop;
  stop.setAttribute("aria-label", W.stop);
  stop.innerHTML = '<svg viewBox="0 0 10 10" aria-hidden="true"><rect width="10" height="10" rx="2"/></svg>';
  line.append(open, stop);
  line.setAttribute("role", "status");
  pet.append(line);
  for (const node of [line, open, stop]) {
    node.addEventListener("pointerdown", (event) => event.stopPropagation());
    node.addEventListener("dblclick", (event) => event.stopPropagation());
  }
  open.addEventListener("click", (event) => {
    event.stopPropagation();
    window.pywebview.api.chat("show");
  });
  stop.addEventListener("click", (event) => {
    event.stopPropagation();
    api("/api/chat/stop", { why: "stopped" }).catch(() => {});
    show(false);
  });

  let on = false;
  let shown = false;
  let words = "";
  let timer = 0;
  // Where the window takes the pointer for it, told again only when it changed.
  let told = "";
  function place() {
    const box = shown ? [petUx.boxOf(line, 12)] : null;
    if (JSON.stringify(box) === told) return;
    told = JSON.stringify(box);
    petUx.spot("line", box);
  }
  function show(yes) {
    yes = yes && Boolean(words) && pose === "standing" && !hushed && !card.open && !quick.classList.contains("on") && !petUx.busy() && !("off" in pet.dataset);
    if (yes) line.style.bottom = `${Math.max(0, 214 - (rig?.room ?? 24) + 6)}px`;
    if (yes === shown) return yes && setTimeout(place, 230);
    shown = yes;
    line.classList.toggle("on", yes);
    open.tabIndex = stop.tabIndex = yes ? 0 : -1;
    line.setAttribute("aria-hidden", String(!yes));
    // Placed once it has eased in, as wide as its words.
    setTimeout(place, yes ? 230 : 0);
  }
  async function waiting(tool) {
    try {
      const response = await api(CARDS[tool]);
      return response.ok && Boolean((await response.json()).card);
    } catch {
      return false;
    }
  }
  async function step() {
    let value = null;
    try {
      const response = await api("/api/chat/doing");
      if (response.ok) value = await response.json();
    } catch {
      // The service is not answering: asked again.
    }
    if (!on) return;
    // The turn is over, though window.py's word of it did not come.
    if (value && !value.busy) return end();
    const doing = value?.doing || null;
    const asked = Boolean(doing && CARDS[doing.tool] && (await waiting(doing.tool)));
    if (!on) return;
    // Tucked at a side, it leans out the moment a card waits on the person (petedge.js).
    if (asked && !line.classList.contains("asked") && "edge" in pet.dataset) petLook();
    line.classList.toggle("asked", asked);
    if (asked) {
      open.querySelector(".act-live-icon")?.remove();
      open.querySelector(".doing").replaceChildren(uxEl("span", "act-live-head", W.asked));
      words = W.asked;
    } else if (doing && !QUIET.has(doing.tool)) {
      words = paActivity.live(open, doing) || "";
    } else if (words === W.asked) {
      words = "";
    }
    // Thinking or writing between two steps keeps the last step, so the line does not go out and come back each time.
    open.title = words ? `${words} · ${W.open}` : "";
    open.setAttribute("aria-label", open.title);
    show(true);
    timer = setTimeout(step, STEP_MS);
  }
  function begin() {
    if (on) return;
    on = true;
    step();
  }
  function end() {
    on = false;
    clearTimeout(timer);
    words = "";
    delete open.dataset.stepped;
    show(false);
  }
  const before = petActivity;
  window.petActivity = (kind) => {
    before(kind);
    if (kind) begin();
    else end();
  };
  // Something else came beside the pet, or went: the line gives way, or comes back.
  const again = () => show(on);
  new MutationObserver(again).observe(cardBox, { attributes: true, attributeFilter: ["hidden"] });
  new MutationObserver(again).observe(quick, { attributes: true, attributeFilter: ["class"] });
  new MutationObserver(again).observe(pet, { attributes: true, attributeFilter: ["data-edge", "data-chat", "data-off", "class"] });
})();
