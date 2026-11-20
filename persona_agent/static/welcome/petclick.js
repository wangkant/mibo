"use strict";
// ---- a click, a stroke, a double-click. One click on the figure brings its compact chat out beside it
// (petchat.py, the app's own chat in a small window) or puts it away; acted on a moment after the press, so
// the second click of a double-click, which hands over the whole window (pet.js), can still take it back.
// The pointer drawn across its head or its feet pats it, as a hand would (pet.js pat).
//
// What is beside the pet, one thing at a time; the first of these has the room and the rest give way or
// wait: the compact chat, what to do with something dropped (petbox.js), the dial (petdial.js), then what
// the pet brings itself, a find or a line said. The line of what it is doing (petline.js) shows over its
// head only while none of them does. While the chat is out the pet stays where it is and brings nothing;
// a reply that comes in after it was put away shows in a bubble, and a press on that bubble brings it back.
(() => {
  const CLICK_MS = 230;
  // A stroke: this far across the head or the feet within a moment (CSS px), less when it goes back and forth.
  const STROKE_PX = 80;
  const STROKE_BACK_PX = 50;
  const STROKE_GAP_MS = 250;
  const STROKE_EVERY_MS = 1400;
  let clickTimer = 0;
  let out = false;

  const busyBefore = petUx.busy;
  petUx.busy = () => out || busyBefore();

  // Whether the chat was out as the press began: the press itself can take its focus and put it away.
  let outAtPress = false;
  pet.addEventListener("pointerdown", () => (outAtPress = out), true);
  window.petClick = (at) => {
    if (pose !== "standing" || asleep() || petUx.justOut?.()) return pat(at);
    clearTimeout(clickTimer);
    clickTimer = setTimeout(async () => {
      if (pose !== "standing" || dragging || carry) return;
      hideQuick();
      if (!outAtPress && card.open && card.kind !== "said") await card.close("seen");
      window.pywebview.api.chat(outAtPress ? "away" : "show");
    }, CLICK_MS);
  };
  window.petDoubleClick = () => {
    clearTimeout(clickTimer);
    if (out) window.pywebview.api.chat("away");
  };

  // Out or put away (petchat.py says). Put away while a reply is on its way, the reply is said in a bubble.
  let after = null;
  window.petChat = async (on) => {
    out = on;
    // For the line over its head (petline.js), which gives way to the chat.
    if (on) pet.dataset.chat = "";
    else delete pet.dataset.chat;
    if (on) {
      after = null;
      hideQuick();
      if (card.kind === "said") card.close("seen");
      play("notice");
      return;
    }
    if (!activity) return;
    try {
      after = (await (await api("/api/chat/doing")).json()).last;
    } catch {
      // The service is not answering: the reply is in the chat alone.
    }
  };
  const activityBefore = petActivity;
  window.petActivity = async (kind) => {
    activityBefore(kind);
    if (kind || after === null || out) return;
    const since = after;
    after = null;
    let said = "";
    try {
      said = (await (await api(`/api/chat/doing?after=${since}`)).json()).said;
    } catch {
      return;
    }
    // Tucked at a side, it leans out instead (petedge.js); a press brings it out to the chat.
    if (said && "edge" in pet.dataset) return petLook();
    if (said && !out && pose === "standing" && !hushed && (await card.say({ text: said, reply: true }))) {
      await flip(!document.body.classList.contains("card-right"));
      play("talk");
    }
  };
  // A press on a reply's bubble brings the chat back where it was; its cross only puts it away.
  let replying = false;
  const sayBefore = card.say;
  card.say = (remark) => {
    replying = Boolean(remark.reply);
    return sayBefore(remark);
  };
  cardBox.addEventListener(
    "click",
    (event) => {
      if (card.kind !== "said" || !cardBox.querySelector(".card-words") || event.target.closest(".card-close") || !replying) return;
      event.stopImmediatePropagation();
      card.close("seen");
      window.pywebview.api.chat("show");
    },
    true,
  );

  // Picked up, gone over the app window or out of sight: the chat goes.
  new MutationObserver(() => out && pet.classList.contains("held") && window.pywebview.api.chat("away")).observe(pet, {
    attributes: true,
    attributeFilter: ["class"],
  });
  for (const name of ["petPose", "petQuiet"]) {
    const before = window[name];
    window[name] = (value) => {
      before(value);
      if (out && (pose !== "standing" || hushed)) window.pywebview.api.chat("away");
    };
  }

  // ---- stroked: where on the figure the pointer is, as pat() tells head from feet.
  function zoneOf(y) {
    const top = y - figureBox.getBoundingClientRect().top;
    if (rig?.kind === "mibo") return top < 68 ? "head" : top >= 163 ? "feet" : "";
    if (rig?.kind !== "painted") return "";
    const { face, bottom } = rig.layout.shape;
    return top < face[1] ? "head" : top > bottom - 16 ? "feet" : "";
  }
  const stroke = { zone: "", x: 0, t: 0, path: 0, sign: 0, back: false, last: 0 };
  pet.addEventListener("pointermove", (event) => {
    if (press || dragging || carry || pose !== "standing" || asleep() || "edge" in pet.dataset) return;
    const zone = zoneOf(event.clientY);
    const now = performance.now();
    if (!zone || zone !== stroke.zone || now - stroke.t > STROKE_GAP_MS)
      Object.assign(stroke, { zone, x: event.clientX, path: 0, sign: 0, back: false });
    const dx = event.clientX - stroke.x;
    stroke.x = event.clientX;
    stroke.t = now;
    if (!zone || Math.abs(dx) < 1) return;
    if (stroke.sign && Math.sign(dx) !== stroke.sign) stroke.back = true;
    stroke.sign = Math.sign(dx);
    stroke.path += Math.abs(dx);
    if (stroke.path < (stroke.back ? STROKE_BACK_PX : STROKE_PX) || now - stroke.last < STROKE_EVERY_MS) return;
    stroke.last = now;
    stroke.path = 0;
    pat([event.clientX, event.clientY]);
  });
})();
