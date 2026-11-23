// The pet: the character alone on the desktop. It walks about, is dragged by
// its figure, hops when patted, and now and then brings a card with something
// it found, or says a line of its own in a bubble. Double-clicked, it hands
// over the app window and peeks over that window's top edge until the window
// goes; window.py says when, through petPose.
//
// It moves by its motion engine below: named actions, each a short clip of
// Web Animations that starts and ends in the rest pose, played when something
// happens and, now and then, on its own. At rest nothing animates: a blink is
// a timer that changes the eyes for a tenth of a second, and asleep it is
// stepped a few times a minute. Hushed or hidden, nothing runs at all.
//
// Mibo is drawn in parts that move each on its own. The painted characters
// are poses cut from paintings, swapped (cut, or faded where two differ only
// a little) and moved as a whole: a bob, a lean, a squash.
//
// The pet is one page's scripts sharing their top-level names, loaded in this
// order by pet.html: this one (the page, its state and the motion engine),
// petclips.js (the actions), petwalk.js (getting about), petpaint.js (a painted
// figure), petlife.js (its life at rest, where it is, which figure),
// petbring.js (what it brings), pethand.js (pats and being carried) and
// petpointer.js (the pointer, its small actions, its start).

const pet = document.getElementById("pet");
const actor = pet.querySelector(".actor");
const figureBox = document.getElementById("figure");
const cardBox = document.getElementById("card");
const token = new URLSearchParams(location.hash.slice(1)).get("token") || "";
// How fast it walks, and trots: CSS px every 30 ms (window.py).
const STEP_PX = 1.1;
const TROT_PX = 2.2;
// The figure's box.
const BOX = [160, 190];
// Room round the figure's box in its window, at the sides and above, so that
// nothing it does (a hop, arms up, a lean while carried, what it holds) is
// cut at the window's edge; the window takes the pointer there only while it
// moves (room). The figure's 200 by 214 is at the window's bottom; 64 more above it hold
// its dial and the line of what it is doing (PET_SIZE in window.py, petdial.js, petline.js).
const PAD = [20, 24];

const between = (low, high) => low + Math.random() * (high - low);
const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const pick = (weights) => {
  const total = Object.values(weights).reduce((sum, weight) => sum + weight, 0);
  let roll = Math.random() * total;
  for (const [name, weight] of Object.entries(weights)) if ((roll -= weight) < 0) return name;
  return Object.keys(weights)[0];
};
// One of `weights`, never `last` again when there is another.
const fresh = (weights, last) => {
  const rest = { ...weights };
  if (Object.keys(rest).length > 1) delete rest[last];
  return pick(rest);
};
const clamp = (v, low, high) => Math.max(low, Math.min(high, v));
// A damped spring, stepped each frame: pulled toward `to`, `w` how quick (rad/s), `z` how damped (1: no
// overshoot).
const spring = (x = 0) => ({ x, v: 0 });
function pull(s, to, w, z, dt) {
  s.v += (w * w * (to - s.x) - 2 * z * w * s.v) * dt;
  s.x += s.v * dt;
}

function api(path, body) {
  const headers = { "X-Mibo-Setup-Token": token };
  if (body === undefined) return fetch(path, { headers });
  headers["Content-Type"] = "application/json";
  return fetch(path, { method: "POST", headers, body: JSON.stringify(body) });
}
const card = makeCard(api);

// Where it is: standing on the ground; leaving it, peeking over the app window, or returning.
let pose = "standing";
// The press in progress, or null; and whether the window is following the cursor.
let press = null;
let dragging = false;
let opening = false;
let walking = false;
// What it is busy with in a chat (thinking, searching, reading), or ""; and how that ends.
let activity = "";
let activityEnd = null;
let activityDone = null;
// Until when it brings nothing of its own (its menu's "do not disturb"), as Date.now(); and
// whether its menu asked for something while nothing was ready.
let snoozed = 0;
let asked = false;
// The things it has brought a card for since it started.
const told = new Set();
const asleep = () => pet.dataset.state === "asleep";
const resting = () =>
  hushed || pose !== "standing" || dragging || ["asleep", "out"].includes(pet.dataset.state) || card.open || Boolean(activity) ||
  Boolean(window.petUx?.busy());

// ---- the motion engine. The figure's parts as they are drawn: Mibo has
// joints of its own; any other drawing moves only as a whole, and a painted
// figure (paintedFigure) as a whole too, its poses swapped.
let rig = null;
function rigOf(node) {
  const mibo = node.querySelector('[data-rig="mibo"]');
  if (mibo) {
    const part = (selector) => mibo.querySelector(selector);
    return {
      kind: "mibo",
      // Its drawing's units in one CSS px.
      k: node.viewBox.baseVal.width / BOX[0],
      face: mibo,
      parts: {
        root: mibo,
        body: part(".body"),
        armL: part(".arm.left"),
        armR: part(".arm.right"),
        footL: part(".foot.left"),
        footR: part(".foot.right"),
        antenna: part(".antenna"),
        tip: part(".tip"),
        earL: part(".ear.left"),
        earR: part(".ear.right"),
        visor: part(".visor"),
        eyes: part(".eyes"),
        chest: part(".chest"),
        gloss: part(".gloss"),
        magnifier: part(".magnifier"),
        book: part(".book"),
        found: part(".found"),
        phones: part(".headphones"),
        shadow: node.querySelector(".shadow"),
      },
    };
  }
  const body = node.querySelector(".figure") || node;
  return { kind: "whole", k: 1, face: node, parts: { root: node, body } };
}

// One pose of a part: moved (CSS px, `k` units each), turned (degrees) and stretched.
const poseCss = ([x = 0, y = 0, turn = 0, wide = 1, tall = wide] = [], k = 1) =>
  `translate(${(x * k).toFixed(2)}px, ${(y * k).toFixed(2)}px) rotate(${turn}deg) scale(${wide}, ${tall})`;

// Eases: quick away and settling slowly (most moves), speeding up (a fall), and slow at both ends.
const OUT = "cubic-bezier(0.2, 0.7, 0.3, 1)";
const IN = "cubic-bezier(0.55, 0, 0.85, 0.45)";
const SOFT = "cubic-bezier(0.45, 0, 0.25, 1)";
// The parts whose swing may differ a little from one time to the next; the
// arms, feet and what they hold keep to their poses.
const LOOSE = new Set(["body", "antenna", "tip", "earL", "earR", "visor"]);
// The animations a clip has running, so another can take over smoothly.
const running = new Set();
function animate(el, frames, ms, how = {}) {
  const k = how.px ? 1 : rig.k;
  const keys = frames.map((frame, i) => ({
    transform: poseCss(frame, k),
    ...(frame && frame[5] !== undefined ? { opacity: frame[5] } : {}),
    easing: (Array.isArray(how.ease) ? how.ease[i] : how.ease) || "ease-in-out",
    ...(how.at ? { offset: how.at[i] } : {}),
  }));
  const motion = el.animate(keys, {
    duration: ms,
    delay: how.delay || 0,
    iterations: how.loop || 1,
    iterationStart: how.phase || 0,
    fill: how.hold ? "forwards" : "none",
    composite: how.add ? "add" : "replace",
  });
  running.add(motion);
  // A held pose stays on after it ends, until the clip calms it.
  const done = () => how.hold || running.delete(motion);
  return motion.finished.then(done, done);
}
// Whatever is moving goes back to rest from where it is, quickly.
function calm(ms = 160, keep = []) {
  const moving = [...running].filter((motion) => !keep.includes(motion.effect?.target));
  moving.forEach((motion) => running.delete(motion));
  const from = new Map();
  for (const motion of moving) {
    const el = motion.effect?.target;
    if (el && !from.has(el)) from.set(el, getComputedStyle(el).transform);
  }
  moving.forEach((motion) => motion.cancel());
  return Promise.all(
    [...from].map(([el, was]) =>
      !ms || !was || was === "none"
        ? null
        : el.animate([{ transform: was }, { transform: "none" }], { duration: ms, easing: "ease-out" }).finished.catch(() => {}),
    ),
  );
}

// Its eyes (data-face, pet.css), and where they look (CSS px off centre).
let face = "open";
function setFace(name, fade = 0) {
  face = name;
  if (rig?.kind === "painted") setPose(rig.pose, fade);
  else if (rig) rig.face.dataset.face = name;
}
const restFace = () => (asleep() ? "sleep" : pet.dataset.state === "answering" ? "think" : "open");
// Back at rest: the face it has at rest, its eyes ahead, a painted figure in its rest pose.
function rested(fade = 0) {
  if (rig?.kind === "painted") rig.pose = restPose();
  setFace(restFace(), fade);
  setLook();
}
function setLook(x = 0, y = 0) {
  if (!x && !y) clearTimeout(glanceTimer);
  // A painted figure's eyes are painted: it looks back from a turn of its head.
  if (rig?.kind === "painted" && !x && !y && rig.pose.startsWith("look_")) {
    glanced = performance.now();
    setPose("rest", 180);
  }
  if (rig?.kind !== "mibo") return;
  const moved = (share) => (x || y ? `translate(${x * rig.k * share}px, ${y * rig.k * share}px)` : "");
  rig.parts.eyes.style.transform = moved(1);
  rig.parts.visor.style.transform = moved(0.3);
}

// The clip playing, if any: another one, or something that happens, ends it.
let scene = null;
// Its window takes the pointer round the whole room while it moves, and only
// round the figure at rest; off a moment after the last move, so two in a row keep it.
let roomy = false;
let roomTimer = 0;
function room(on) {
  clearTimeout(roomTimer);
  if (on === roomy) return;
  if (!on) {
    roomTimer = setTimeout(() => {
      if (scene || carry) return;
      roomy = false;
      window.pywebview.api.room(false);
    }, 500);
    return;
  }
  roomy = true;
  window.pywebview.api.room(true);
}
async function play(name, ...args) {
  const clip = (rig?.kind === "painted" && PAINTED[name]) || CLIPS[name];
  if (!rig || !clip || carry) return;
  room(true);
  const own = { name };
  const over = new Promise((resolve) => (own.end = resolve));
  scene?.end();
  scene = own;
  await calm();
  // A painted figure starts from its rest pose, not from a head turned to the pointer.
  if (rig.kind === "painted" && scene === own && rig.pose.startsWith("look_")) setPose("rest", 110);
  const alive = () => scene === own;
  const tempo = between(0.93, 1.07);
  const amp = between(0.88, 1.12);
  const loose = (frames) =>
    frames.map(([x = 0, y = 0, turn = 0, wide = 1, tall = wide, ...rest] = []) => [
      x * amp, y * amp, turn * amp, 1 + (wide - 1) * amp, 1 + (tall - 1) * amp, ...rest,
    ]);
  const c = {
    mibo: rig.kind === "mibo",
    go: (part, frames, ms, how = {}) =>
      alive() && rig.parts[part]
        ? animate(rig.parts[part], LOOSE.has(part) ? loose(frames) : frames, ms * tempo, {
            ...how,
            delay: (how.delay || 0) * tempo,
          })
        : Promise.resolve(),
    face: (name) => alive() && setFace(name),
    look: (x, y) => alive() && setLook(x, y),
    show: (name, fade) => alive() && setPose(name, fade),
    wait: (ms) => Promise.race([wait(ms), over]),
    until: (promise) => Promise.race([promise, over]),
    alive,
  };
  try {
    if (alive()) await clip(c, ...args);
  } finally {
    if (alive()) {
      scene = null;
      await calm();
      rested(160);
      if (!scene && !carry) room(false);
    }
  }
}
// Stop whatever plays, at once.
function still() {
  scene?.end();
  scene = null;
  calm(0);
  if (rig) rested();
}
// Turned to face left or right. Mibo is drawn from the front, the same either
// way round: its eyes go over to the new side, a foot steps that way and the
// other follows, and between the two steps it is mirrored, unseen. Another
// drawing is squeezed thin, mirrored, and out again.
async function flip(left) {
  if (pet.classList.contains("left") === left) return;
  // A painted figure faces the person at rest; it turns as it sets off (stride).
  if (rig?.kind === "painted") {
    pet.classList.toggle("left", left);
    if (SIDEWAYS.has(rig.shown)) setPose(rig.pose);
    return;
  }
  if (rig?.kind === "mibo") {
    const p = rig.parts;
    const at = (el, frames, ms, how = {}) => animate(el, frames, ms, { ease: OUT, ...how });
    setLook(-5, 0);
    at(p.earL, [R, [-1.2, 0], R], 420, { at: [0, 0.4, 1] });
    at(p.earR, [R, [-1.6, 0, 0, 0.85, 1], R], 420, { at: [0, 0.4, 1] });
    await Promise.all([
      at(p.body, [R, [0, 0.6, -2, 1.02, 0.98], R], 260, { delay: 40 }),
      at(p.footL, [R, [-2, -3, -6], [-1.5, 0], R], 240, { delay: 70, at: [0, 0.45, 0.8, 1] }),
    ]);
    // Mirrored while everything is at rest, its eyes put back on the same side at once.
    for (const el of [p.eyes, p.visor]) el.style.transition = "none";
    setLook(5, 0);
    pet.classList.toggle("left", left);
    void pet.offsetWidth;
    for (const el of [p.eyes, p.visor]) el.style.transition = "";
    await Promise.all([
      at(p.footL, [R, [1.5, -2.5, 6], R], 200, { at: [0, 0.5, 1] }),
      at(p.body, [R, [0, -0.6, 1.2, 0.99, 1.01], R], 260),
    ]);
    setLook(3, 0);
    return;
  }
  const from = left ? 1 : -1;
  const squeeze = (a, b, ease) =>
    figureBox
      .animate([{ transform: `scaleX(${a})` }, { transform: `scaleX(${b})` }], { duration: 110, easing: ease })
      .finished.catch(() => {});
  await squeeze(from, from * 0.08, "ease-in");
  pet.classList.toggle("left", left);
  await squeeze(-from * 0.08, -from, "ease-out");
}
