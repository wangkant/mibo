// What the pet brings by itself (pet.js): a find on a card, a line in a bubble, and its "do not disturb".

// "Do not disturb for an hour", from its menu.
const SNOOZE_MS = 3600000;

// ---- something it found: a card opens beside it, it turns to it, holds it
// up, points at it and looks hopeful. Liked, it cheers; put away, it droops.
async function bringNews(now = false) {
  // Asked for from the menu while nothing was ready: brought when it is, pacing or not.
  now = now || asked;
  if (resting() || press || opening || (!now && Date.now() < snoozed)) return false;
  let item = null;
  try {
    const response = await api(`/api/feed/next?lang=${encodeURIComponent(card.lang)}${now ? "&now=true" : ""}`);
    if (response.ok) item = (await response.json()).item;
  } catch {
    // The service is not answering: nothing to bring this time.
  }
  if (!item || told.has(item.id) || resting() || press || opening) return false;
  told.add(item.id);
  asked = false;
  if (!(await card.show(item))) return false;
  await flip(!document.body.classList.contains("card-right"));
  play("present");
  return true;
}
// How the card went: by its cross, by a click on it, or by itself. Its heart
// turns on after this listener, in the card's own handler.
let cardWent = "";
let liked = false;
cardBox.addEventListener(
  "click",
  (event) => {
    const heart = event.target.closest(".card-like");
    if (heart) {
      if (!heart.classList.contains("on")) {
        liked = true;
        play("cheer");
      }
      return;
    }
    cardWent = event.target.closest(".card-close, .card-nope") ? "closed" : event.target.closest(".card-play, .card-next, .card-still") ? "" : "opened";
  },
  true,
);
new MutationObserver(() => {
  if (!cardBox.hidden) return;
  const how = cardWent;
  const glad = liked;
  cardWent = "";
  liked = false;
  if (how === "opened" || pose !== "standing" || hushed || cardBox.dataset.went === "panel") return;
  if (!glad) play("droop");
  // Its find liked, Mibo is pleased: now and then it hops off a little way.
  else if (rig?.kind === "mibo" && hopping() && !("off" in pet.dataset)) walk(false, true);
}).observe(cardBox, { attributes: true, attributeFilter: ["hidden"] });

// ---- a line of its own about what the person is doing: a bubble beside it,
// and the line is in the main chat too (the service puts it there). True when
// it is out, or when a video plays in a window in front, or while it is not
// to disturb: then it brings nothing at all. A find waits until the bubble
// has gone, as for a card.
async function bringRemark() {
  // Over the app window, or with the figure turned off (petoff.js), the line is to be read in the chat:
  // taken, and not shown.
  const peeking = pose === "peek" || "off" in pet.dataset;
  if (Date.now() < snoozed) return true;
  if (!peeking && (resting() || press || opening)) return false;
  let remark = null;
  try {
    const response = await api("/api/remark/next");
    if (response.ok) {
      const value = await response.json();
      if (value.video_front) return true;
      remark = value.remark;
    }
  } catch {
    // The service is not answering: nothing to say this time.
  }
  if (!remark || peeking || resting() || press || opening) return false;
  if (!(await card.say(remark))) return false;
  await flip(!document.body.classList.contains("card-right"));
  play("talk");
  return true;
}
async function lookOut() {
  if (!(await bringRemark())) await bringNews();
}
// Called by window.py when a line or something found is waiting. What the pet cannot bring now is
// asked for at its next look.
function petLook() {
  if (timers) lookOut();
}
// From its menu: something found, now, even while not to disturb; with
// nothing to bring it shakes its head. "Do not disturb for an hour", on or
// off, kept here; and whether it is on, for the menu's label.
async function petBring() {
  if (!timers || pose !== "standing") return;
  if (await bringNews(true)) return;
  // Nothing ready yet: one is being chosen, and comes at the next look (petLook).
  asked = true;
  if (!card.open) play("shakeHead");
}
// The pacing keeps it too (POST /api/feed/snooze), so the chat shares nothing meanwhile either.
function petSnooze(on) {
  snoozed = on ? Date.now() + SNOOZE_MS : 0;
  if (on) {
    asked = false;
    card.close("seen");
  }
  api("/api/feed/snooze", { on }).catch(() => {});
  showQuiet(on);
}
function petSnoozed() {
  return Date.now() < snoozed;
}
