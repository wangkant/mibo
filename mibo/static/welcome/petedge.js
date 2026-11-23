"use strict";
// ---- tucked at a side of the screen. Let go near one (window.py tuck puts its window flush there), the
// figure turns on its side into the edge until only the strip it peeks over a window with shows: its
// head down to under the eyes, holding the edge (a painted figure in its peek pose, Mibo with its hands
// over it). Tucked it is not to be disturbed: it walks nowhere and brings nothing (pet.js resting), and
// its lines go to the chat alone. It leans out further while the pointer is near, and when something is
// waiting for it (petLook: a find, a line said, a question waiting on the person), with a word on its face; a
// press brings it out, with what was waiting, and a drag takes it away from the edge.
(() => {
  // How much further out it leans (CSS px), and how long the turn takes (petux.css).
  const LEAN_PX = 22;
  const TURN_MS = 420;
  let side = "";
  let leaning = false;
  let waiting = false;
  let outAt = 0;

  // The point it turns about, in the pet's 200 by 214: the middle of the figure on the line it peeks
  // over (a painted figure's own, else just under its eyes), and how far above that its head goes.
  function pivot() {
    const peek = rig.layout?.peek;
    if (peek) {
      const { left, right } = rig.layout.shape;
      return { x: PAD[0] + (left + right) / 2, y: PAD[1] + peek.line, head: peek.line - peek.top };
    }
    const svg = figureBox.querySelector("svg");
    const scale = BOX[0] / svg.viewBox.baseVal.width;
    const eyes = (svg.querySelector(".eyes") || svg.querySelector(".figure")).getBBox();
    const body = svg.querySelector(".figure").getBBox();
    const line = (eyes.y + eyes.height) * scale + UNDER_EYES;
    return { x: PAD[0] + BOX[0] / 2, y: PAD[1] + line, head: line - body.y * scale };
  }
  // The actor turned a quarter about its own origin (its bottom middle, pet.css), and moved so the
  // pivot sits on the window's side: there only its head is inside the window.
  function turn(lean) {
    const p = pivot();
    const o = [100, 214];
    const deg = side === "right" ? -90 : 90;
    const v = [p.x - o[0], p.y - o[1]];
    const r = side === "right" ? [v[1], -v[0]] : [-v[1], v[0]];
    const edge = side === "right" ? 200 - (lean ? LEAN_PX : 0) : lean ? LEAN_PX : 0;
    actor.style.translate = `${edge - o[0] - r[0]}px ${p.y - o[1] - r[1]}px`;
    actor.style.rotate = `${deg}deg`;
    return p;
  }
  // The window takes the pointer over the head alone, once it is there.
  function hold(p) {
    const depth = Math.ceil(p.head + (leaning ? LEAN_PX : 0)) + 4;
    const wide = Math.ceil(rig.layout ? rig.layout.shape.right - rig.layout.shape.left : BOX[0] * 0.75) + 8;
    const y = Math.round(p.y + HEAD_ROOM - wide / 2);
    setTimeout(() => side && petUx.spot("edge", [[side === "right" ? 200 - depth : 0, y, depth, wide, 0]]), TURN_MS);
  }

  async function tuckIn(moved) {
    still();
    hideQuick();
    // The window has just jumped to the edge: the figure starts where it was on the screen.
    actor.style.transition = "none";
    actor.style.translate = `${-moved}px 0px`;
    void actor.offsetWidth;
    actor.style.transition = "";
    pet.dataset.edge = side;
    rested();
    petUx.setBare(true);
    hold(turn(false));
  }
  function lean(on, word = false) {
    if (!side || on === leaning) return;
    leaning = on;
    hold(turn(on));
    if (rig.kind === "painted") setFace(on && word ? "talk" : "open");
    else setFace(on && word ? "happy" : "open");
  }
  function comeOut() {
    if (!side) return;
    side = "";
    leaning = false;
    outAt = performance.now();
    delete pet.dataset.edge;
    actor.style.translate = actor.style.rotate = "";
    petUx.spot("edge", null);
    petUx.setBare(false);
    rested();
    if (waiting) {
      waiting = false;
      setTimeout(() => petLook(), TURN_MS);
    }
  }

  // Let go after a drag: tucked when it was let go near a side. Pressed and carried: out at once.
  let wasHeld = false;
  new MutationObserver(async () => {
    const held = pet.classList.contains("held");
    if (held === wasHeld) return;
    wasHeld = held;
    if (held) return comeOut();
    if (pose !== "standing" || hushed) return;
    const before = screenX;
    const to = await window.pywebview.api.tuck();
    if (!to || pet.classList.contains("held")) return;
    side = to;
    tuckIn(screenX - before);
  }).observe(pet, { attributes: true, attributeFilter: ["class"] });

  // A press on the tucked head (not a drag) brings it out; pethand.js's pat that follows is stopped.
  let down = null;
  pet.addEventListener("pointerdown", (event) => (down = side ? [event.screenX, event.screenY] : null), true);
  pet.addEventListener("pointerup", (event) => {
    if (!down || Math.hypot(event.screenX - down[0], event.screenY - down[1]) > 4) return;
    down = null;
    setTimeout(() => {
      still();
      comeOut();
    });
  }, true);
  // Brought out by a press: that click is not one for the compact chat (petclick.js).
  petUx.justOut = () => performance.now() - outAt < 600;
  // Out at once when the figure is turned off (petoff.js).
  petUx.untuck = comeOut;

  const cursorBefore = petCursor;
  window.petCursor = (at) => {
    if (!side) return cursorBefore(at);
    lean(Boolean(at) || waiting, waiting);
  };
  const lookBefore = petLook;
  window.petLook = () => {
    if (!side) return lookBefore();
    waiting = true;
    leaning = false;
    lean(true, true);
  };
})();
