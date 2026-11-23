// The pet in a person's hand (pet.js): pats where it is pressed, and being picked up, carried and set down.

// Past this many pixels a press is a drag, not a pat.
const DRAG_PX = 4;
// Three pats this close together and it shakes its head.
const PATS_MS = 2500;

// ---- what a person does to it. Only round the figure: elsewhere the
// pointer goes through its window (window.py). Where it is pressed says what
// it does: patted on the head, booped on the face, poked in the middle, its
// feet pressed; poked too often it shakes its head, then huffs. Never the same twice running.
let pats = [];
let lastPat = "";
function pat(at) {
  hideQuick();
  if (pose === "peek") return play("duck");
  if (pose !== "standing") return;
  if (asleep()) return play("startle");
  const now = performance.now();
  pats = [...pats.filter((t) => now - t < PATS_MS), now];
  if (pats.length >= 5) {
    pats = [];
    return play("huff");
  }
  if (pats.length === 3) return play("shakeHead");
  const y = at[1] - figureBox.getBoundingClientRect().top;
  let where = "body";
  if (rig?.kind === "mibo") where = y < 68 ? "head" : y < 111 ? "face" : y < 163 ? "body" : "feet";
  else if (rig?.kind === "painted") {
    const { face: spot, bottom } = rig.layout.shape;
    where = y < spot[1] ? "head" : y < spot[3] ? "face" : y > bottom - 16 ? "feet" : "body";
  }
  const choices = {
    head: { patHead: 5, antennaWobble: 1 },
    face: { boop: 4, wink: 1 },
    body: { giggle: 3, hop: 2, wave: 1, nod: 1 },
    feet: { shuffle: 3, hop: 2 },
  }[where];
  return play((lastPat = fresh(choices, lastPat)));
}
// ---- held in the hand: a small thing with some weight, not a picture on a
// string. Picked up, it squashes toward the hand and its feet leave the
// ground; carried, its body leans into the way it goes and its feet, arms and
// antenna come after, each late in its own way; let go, it drops onto its
// feet. Each of those is a damped spring, stepped each frame only while it is
// held and until it has landed and settled; then the parts go back to the drawing.
const LIFT_PX = 7;
const FALL = 2600;
const SHAKE = 520;
let carry = null;
let heldTimer = 0;
function grab(at) {
  still();
  room(true);
  const box = figureBox.getBoundingClientRect();
  const c = {
    at: [at[0] - box.left, at[1] - box.top],
    held: true,
    hand: [],
    v: [0, 0],
    last: 0,
    landed: 0,
    dizzy: 0,
    sign: 0,
    turns: [],
    gaze: "",
    lean: spring(),
    tall: spring(1),
    rise: spring(),
    lift: spring(),
    armL: spring(),
    armR: spring(),
    footL: spring(),
    footR: spring(),
    kickL: spring(),
    kickR: spring(),
    tuck: spring(),
    antenna: spring(),
    tip: spring(),
  };
  // The start: a little squash toward the hand, the arms flung up.
  c.tall.v = -1.4;
  c.armL.v = 260;
  c.armR.v = -220;
  carry = c;
  // A painted figure hangs from where it is held, in its held pose.
  rig.parts.root.style.transformOrigin =
    rig.kind === "mibo" ? "200px 290px" : rig.kind === "painted" ? `${c.at[0]}px ${c.at[1]}px` : "50% 60%";
  if (rig.kind === "painted") setPose(either("held"));
  setFace("round");
  setTimeout(() => carry === c && c.held && !c.dizzy && setFace("open"), 380);
  heldLater();
  requestAnimationFrame(carryStep);
}
function letGo() {
  if (!carry || !carry.held) return;
  carry.held = false;
  clearTimeout(heldTimer);
}
// Where it looks while held: at the hand, down at the ground, out at the person.
function gazeAt(where) {
  const c = carry;
  const facing = pet.classList.contains("left") ? -1 : 1;
  if (where === "hand") setLook(clamp((c.at[0] - BOX[0] / 2) / 12, -5, 5) * facing, clamp((c.at[1] - 90) / 18, -3, 4));
  else if (where === "ground") setLook(facing * 1.5, 4);
  else setLook(0, 0);
  c.gaze = where;
}
// Held still, now and then: a look at the hand, at the ground or out, a blink, a kick of its feet.
function heldLater() {
  clearTimeout(heldTimer);
  heldTimer = setTimeout(() => {
    const c = carry;
    if (!c || !c.held) return;
    if (!c.dizzy && Math.hypot(...c.v) < 60 && rig.kind === "painted") {
      // A painted figure changes how it hangs, now and then.
      if (has("held2") && Math.random() < 0.6) setPose(rig.pose === "held2" ? "held" : "held2", 200);
    } else if (!c.dizzy && Math.hypot(...c.v) < 60) {
      const next = pick({ hand: 3, ground: 2, person: 2, blink: 3, kick: 3 });
      if (next === "blink") {
        setFace("shut");
        setTimeout(() => carry === c && !c.dizzy && setFace("open"), BLINK_SHUT);
      } else if (next === "kick") {
        const left = Math.random() < 0.5;
        c[left ? "kickL" : "kickR"].v += left ? 420 : -420;
        setTimeout(() => carry === c && (c[left ? "kickR" : "kickL"].v += left ? -360 : 360), 150);
      } else if (next !== c.gaze) gazeAt(next);
    }
    heldLater();
  }, between(900, 2200));
}
function carryStep(now) {
  const c = carry;
  if (!c) return;
  const dt = c.last ? Math.min(0.034, (now - c.last) / 1000) : 1 / 60;
  c.last = now;
  const facing = rig.kind !== "painted" && pet.classList.contains("left") ? -1 : 1;
  if (c.held) {
    // The hand's speed, from where its window has been over the last tenth of a second.
    c.hand.push([now, screenX, screenY]);
    while (c.hand.length > 2 && now - c.hand[0][0] > 100) c.hand.shift();
    const [t0, x0, y0] = c.hand[0];
    const span = (now - t0) / 1000;
    c.v = span > 0.03 ? [(screenX - x0) / span, (screenY - y0) / span] : [0, 0];
  } else c.v = [0, 0];
  const vx = c.v[0] * facing;
  const vy = c.v[1];
  // Shaken hard, this way and that, it gets dizzy.
  if (c.held && Math.abs(c.v[0]) > SHAKE) {
    const sign = Math.sign(c.v[0]);
    if (c.sign && sign !== c.sign) c.turns.push(now);
    c.sign = sign;
    c.turns = c.turns.filter((at) => now - at < 1100);
    if (c.turns.length >= 3) {
      if (!c.dizzy) {
        setFace("dizzy");
        if (rig.kind === "painted") setPose(either("dizzy", "surprised"), 120);
      }
      c.dizzy = now;
    }
  }
  if (c.dizzy && c.held && now - c.dizzy > 1800) {
    c.dizzy = 0;
    c.turns = [];
    if (rig.kind === "painted") setPose(either("held"), 160);
    setFace("open");
  }
  if (c.held) {
    pull(c.lean, clamp(vx * 0.018, -10, 10), 15, 0.8, dt);
    pull(c.tall, 1.025 + clamp(-vy * 0.00005, -0.045, 0.05), 20, 0.45, dt);
    pull(c.rise, -LIFT_PX, 12, 0.9, dt);
    pull(c.lift, 1, 9, 1, dt);
    const trail = clamp(vx * 0.03, -32, 32);
    pull(c.armL, 34 + trail, 9.5, 0.45, dt);
    pull(c.armR, -30 + trail, 10.5, 0.5, dt);
    pull(c.tuck, -2.6, 11, 0.7, dt);
    pull(c.footL, clamp(-vx * 0.005, -4, 4), 8.5, 0.5, dt);
    pull(c.footR, clamp(-vx * 0.005, -4, 4), 10, 0.55, dt);
    pull(c.antenna, clamp(-vx * 0.022, -22, 22), 11, 0.32, dt);
    pull(c.tip, clamp(-vx * 0.0035, -3, 3), 14, 0.35, dt);
    // Its eyes go where it is carried, and back to the hand when it stops.
    if (Math.abs(vx) > 150 && !c.dizzy) {
      setLook(clamp(vx * 0.006, -5, 5), clamp(vy * 0.004, -3, 4));
      c.gaze = "";
    } else if (!c.gaze && !c.dizzy) gazeAt("hand");
  } else if (!c.landed) {
    // Falling the little way to the ground, its feet reaching for it.
    c.rise.v += FALL * dt;
    c.rise.x += c.rise.v * dt;
    if (c.rise.x >= 0) {
      // Down: a squash, and the antenna jolted.
      const hit = c.rise.v;
      c.rise.x = 0;
      c.rise.v = 0;
      c.landed = now;
      c.tall.v -= hit * 0.012;
      c.antenna.v += hit * 0.9 * (Math.random() < 0.5 ? 1 : -1);
      c.tip.v += hit * 0.05;
      if (rig.kind === "painted" && !c.dizzy) setPose(either("land"));
      if (!c.dizzy) setFace("shut");
    }
    pull(c.tuck, 0, 30, 0.9, dt);
    pull(c.footL, 0, 26, 0.9, dt);
    pull(c.footR, 0, 24, 0.9, dt);
    pull(c.armL, 50, 14, 0.7, dt);
    pull(c.armR, -50, 15, 0.7, dt);
    pull(c.tall, 0.97, 18, 0.6, dt);
    pull(c.lean, 0, 14, 0.8, dt);
  } else {
    // One small rebound, and the arms come down a beat after the body.
    const after = now - c.landed;
    if (after > 110 && face === "shut") setFace("open");
    if (rig.kind === "painted" && after > 140 && rig.pose === "land") setPose("rest");
    pull(c.tall, 1, 19, 0.32, dt);
    pull(c.tuck, 0, 30, 1, dt);
    pull(c.footL, 0, 26, 1, dt);
    pull(c.footR, 0, 24, 1, dt);
    if (after > 70) {
      pull(c.armL, 0, 7.5, 0.42, dt);
      pull(c.armR, 0, 8.2, 0.45, dt);
    }
    pull(c.antenna, 0, 11, 0.3, dt);
    pull(c.tip, 0, 14, 0.35, dt);
    pull(c.lean, 0, 14, 0.8, dt);
  }
  if (!c.held) pull(c.lift, 0, 22, 1, dt);
  pull(c.kickL, 0, 18, 0.35, dt);
  pull(c.kickR, 0, 18, 0.35, dt);
  const p = rig.parts;
  const set = (el, frame) => el && (el.style.transform = poseCss(frame, rig.k));
  set(p.root, [0, c.rise.x, c.lean.x]);
  set(p.body, [0, 0, 0, 1 + (1 - c.tall.x) * 0.75, c.tall.x]);
  set(p.armL, [0, 0, c.armL.x]);
  set(p.armR, [0, 0, c.armR.x]);
  set(p.footL, [c.footL.x, c.tuck.x, c.kickL.x]);
  set(p.footR, [c.footR.x, c.tuck.x, c.kickR.x]);
  set(p.antenna, [0, 0, c.antenna.x]);
  set(p.tip, [c.tip.x, 0]);
  set(p.gloss, [-c.lean.x * 0.5, 0]);
  if (p.shadow) {
    p.shadow.style.transform = `scale(${(1 - 0.3 * c.lift.x).toFixed(3)})`;
    p.shadow.style.opacity = (1 - 0.45 * c.lift.x).toFixed(3);
  }
  // Down and still: its parts go back to the drawing, and it looks round at the person.
  const quiet = ["lean", "armL", "armR", "antenna", "kickL", "kickR"].every(
    (name) => Math.abs(c[name].v) < 1.5 && Math.abs(c[name].x) < 0.3,
  );
  const after = c.landed ? now - c.landed : 0;
  if (c.landed && ((after > 350 && quiet && Math.abs(c.tall.x - 1) < 0.002) || after > 1800)) {
    for (const el of Object.values(p)) if (el) el.style.transform = el.style.transformOrigin = el.style.opacity = "";
    carry = null;
    setLook();
    play(c.dizzy ? "dizzy" : "landed").then(busyAgain);
    return;
  }
  requestAnimationFrame(carryStep);
}
async function drag() {
  dragging = true;
  pet.classList.add("held");
  grab(press.at);
  // The window follows the cursor until the button is let go (window.py),
  // holding the figure where it was pressed.
  await window.pywebview.api.drag(press.at[0], press.at[1]);
  dragging = false;
  pet.classList.remove("held");
  letGo();
}
pet.addEventListener("pointerdown", (event) => {
  if (event.button !== 0) return;
  // A press stops a walk at once, or the window would move between the two
  // clicks of a double-click and the page would see two single ones.
  if (walking) window.pywebview.api.rest();
  going?.end();
  press = { x: event.screenX, y: event.screenY, at: [event.clientX, event.clientY], moved: false };
  pet.setPointerCapture(event.pointerId);
});
pet.addEventListener("pointermove", (event) => {
  if (dragging) return;
  if (!press) return follow(event);
  if (press.moved) return;
  if (Math.hypot(event.screenX - press.x, event.screenY - press.y) <= DRAG_PX) return;
  press.moved = true;
  // Peeking, it stays on the window's edge.
  if (pose === "standing" && !opening) drag();
});
pet.addEventListener("pointerup", (event) => {
  if (!press || event.button !== 0) return;
  const { moved, at } = press;
  press = null;
  if (dragging) window.pywebview.api.drop();
  // A click brings its compact chat (petclick.js); a pat is a stroke of the pointer now.
  else if (!moved) petClick(at);
});
pet.addEventListener("pointercancel", () => {
  press = null;
  if (dragging) window.pywebview.api.drop();
});
