// The pointer near the pet and over it (pet.js), its small actions, what is shown on it, and its start.

// ---- the pointer. Near it (window.py says where, petCursor), its eyes follow
// it; over it, it notices; a quick rub back and forth tickles it; and left
// there a while, its small actions come up beside its head and it does
// something for the person. All of it only as the pointer moves: nothing at rest.
const watching = () => rig && rig.kind !== "whole" && !scene && !carry && !asleep() && !dragging && ["standing", "peek"].includes(pose);
function lookToward(x, y, across, down) {
  if (rig.kind === "painted") return glance(x - BOX[0] / 2);
  const facing = pet.classList.contains("left") ? -1 : 1;
  const half = (v) => Math.round(v * 2) / 2;
  setLook(half(clamp((x - BOX[0] / 2) / across, -6, 6) * facing), half(clamp((y - 90) / down, -3, 4)));
}
let hovering = false;
function follow(event) {
  if (!watching()) return;
  const box = figureBox.getBoundingClientRect();
  lookToward(event.clientX - box.left, event.clientY - box.top, 14, 22);
}
// Where the cursor is, in its window's px, while it is near; null when it has gone.
function petCursor(at) {
  if (hovering || !watching()) return;
  if (!at) return setLook();
  const box = figureBox.getBoundingClientRect();
  lookToward(at[0] - box.left, at[1] - box.top, 40, 50);
}
const tickle = { x: 0, sign: 0, turns: [], at: 0 };
function tickled(event) {
  const dx = event.screenX - tickle.x;
  tickle.x = event.screenX;
  if (Math.abs(dx) < 2) return false;
  const now = performance.now();
  const sign = Math.sign(dx);
  if (tickle.sign && sign !== tickle.sign) tickle.turns.push(now);
  tickle.sign = sign;
  tickle.turns = tickle.turns.filter((t) => now - t < 900);
  if (tickle.turns.length < 5 || now - tickle.at < 2500) return false;
  tickle.turns = [];
  tickle.at = now;
  return true;
}
let hoverTimers = [];
let lastHover = "";
pet.addEventListener("pointerenter", (event) => {
  hovering = true;
  tickle.x = event.screenX;
  if (!watching() || press) return;
  follow(event);
  play("notice");
  hoverTimers.forEach(clearTimeout);
  hoverTimers = [
    setTimeout(showQuick, 700),
    setTimeout(() => {
      if (hovering && !press && !scene && pose === "standing" && !asleep() && !card.open)
        play((lastHover = fresh({ tiltHead: 2, wave: 2, wink: 1, antennaWobble: 1 }, lastHover)));
    }, 2600),
  ];
});
pet.addEventListener("pointermove", (event) => {
  if (press || dragging || !hovering) return;
  if (tickled(event) && pose === "standing" && !asleep() && !carry) play("giggle");
});
pet.addEventListener("pointerleave", () => {
  hovering = false;
  hoverTimers.forEach(clearTimeout);
  hoverTimers = [setTimeout(hideQuick, 600)];
  if (!scene) setLook();
});

// ---- its small actions, beside its head while the pointer stays on it: the
// chat, something found now, and "do not disturb". The right-click menu has them too.
const quick = document.getElementById("quick");
function showQuick() {
  if (!hovering || press || carry || pose !== "standing" || card.open || hushed) return;
  const quiet = quick.querySelector(".quick-quiet");
  const on = petSnoozed();
  quiet.classList.toggle("on", on);
  quiet.title = quiet.ariaLabel = on ? said.unsnooze || "" : said.snooze || "";
  quick.classList.add("on");
}
function hideQuick() {
  quick.classList.remove("on");
}
let said = {};
quick.addEventListener("pointerdown", (event) => event.stopPropagation());
quick.addEventListener("dblclick", (event) => event.stopPropagation());
quick.addEventListener("click", (event) => {
  const button = event.target.closest("button");
  if (!button) return;
  event.stopPropagation();
  if (button.classList.contains("quick-quiet")) {
    petSnooze(!petSnoozed());
    return showQuick();
  }
  hideQuick();
  if (button.classList.contains("quick-find")) return petBring();
  if (!opening) handOver();
});
// "Here you go": the app window handed over.
async function handOver() {
  opening = true;
  await play("give");
  await window.pywebview.api.open();
  opening = false;
}
function labelQuick() {
  window.pywebview.api
    .words()
    .then((words) => {
      said = words || {};
      for (const [button, text] of [[".quick-chat", said.open], [".quick-find", said.bring]]) {
        const el = quick.querySelector(button);
        el.title = el.ariaLabel = text || "";
      }
    })
    .catch(() => {});
}

// ---- what is true round it, shown on it. The person back after a while
// away (window.py): a wave. Do not disturb: headphones on. Busy in a chat
// (window.py, as the chat says): thinking, searching or reading until the turn is over.
function petBack() {
  if (pose !== "standing" || hushed || asleep() || scene || carry || !timers) return;
  play("wave");
}
let quietTimer = 0;
function showQuiet(on, moved = true) {
  clearTimeout(quietTimer);
  if (on) quietTimer = setTimeout(() => showQuiet(false), Math.max(0, snoozed - Date.now()));
  if (on === "dnd" in pet.dataset) return;
  if (!moved || pose !== "standing" || hushed || carry) {
    if (on) pet.dataset.dnd = "";
    else delete pet.dataset.dnd;
    return;
  }
  play(on ? "quietOn" : "quietOff");
}
function petActivity(kind) {
  kind = ["thinking", "searching", "reading"].includes(kind) ? kind : "";
  if (kind === activity) return;
  activity = kind;
  activityEnd?.();
  activityEnd = activityDone = null;
  if (!kind) return;
  activityDone = new Promise((resolve) => (activityEnd = resolve));
  busyAgain();
}
function busyAgain() {
  if (activity && pose === "standing" && !hushed && !carry && !asleep()) play("busy", activity, activityDone);
}

// On the ground it hands the window over; peeking, it brings the window to the front.
pet.addEventListener("dblclick", () => {
  if (opening || dragging) return;
  if (pose === "peek") return window.pywebview.api.open();
  if (pose !== "standing") return;
  hideQuick();
  // On the ground it hands over the whole window; the compact chat a first click began goes (petclick.js).
  petDoubleClick();
  handOver();
});
window.addEventListener("contextmenu", (event) => {
  event.preventDefault();
  hideQuick();
  window.pywebview.api.menu();
});

window.addEventListener("pywebviewready", () => {
  started = true;
  settle();
  labelQuick();
  // A page loaded again keeps the "do not disturb" the service still holds.
  api("/api/feed/snooze")
    .then((response) => response.json())
    .then((value) => (snoozed = value.left ? Date.now() + value.left * 1000 : 0))
    .then(() => showQuiet(petSnoozed(), false))
    .catch(() => {});
});
