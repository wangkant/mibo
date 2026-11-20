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
const pet = document.getElementById("pet");
const actor = pet.querySelector(".actor");
const figureBox = document.getElementById("figure");
const cardBox = document.getElementById("card");
const token = new URLSearchParams(location.hash.slice(1)).get("token") || "";
// How often it asks what the character is doing, which figure it is, and
// whether there is something to bring: window.py tells it at once of a line to
// say or a find, and of a new figure (petLook, petFigure).
const LOOK_MS = 60000;
// Past this many pixels a press is a drag, not a pat.
const DRAG_PX = 4;
// How fast it walks, and trots: CSS px every 30 ms (window.py).
const STEP_PX = 1.1;
const TROT_PX = 2.2;
// Coming back into sight (pet.css).
const RISE_MS = 520;
// While it peeks: the room left above its head for the overshoot, and how far
// under its eyes the window's edge cuts it off (CSS px).
const PEEK_ROOM = 10;
const UNDER_EYES = 6;
// The figure's box.
const BOX = [160, 190];
// Room round the figure's box in its window, at the sides and above, so that
// nothing it does (a hop, arms up, a lean while carried, what it holds) is
// cut at the window's edge; the window takes the pointer there only while it
// moves (room). The figure's 200 by 214 is at the window's bottom; 64 more above it hold
// its dial and the line of what it is doing (PET_SIZE in window.py, petdial.js, petline.js).
const PAD = [20, 24];
// Room beside the figure at rest for a wave and a sway, and below it for a
// squash; and from where to where across the dots and the z's go.
const ROOM_SIDE = 20;
const ROOM_BOTTOM = 4;
const OVERLAY = [100, 146];
// Its life at rest: a small action this long after the last (ms), a blink
// this often and this long, and asleep, a breath and a z this often.
const IDLE_MS = [15000, 45000];
const BLINK_MS = [2600, 6800];
const BLINK_SHUT = 100;
const SLEEP_STEP_MS = 20000;
// "Do not disturb for an hour", from its menu.
const SNOOZE_MS = 3600000;
// Three pats this close together and it shakes its head.
const PATS_MS = 2500;

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

function api(path, body) {
  const headers = { "X-Personagent-Setup-Token": token };
  if (body === undefined) return fetch(path, { headers });
  headers["Content-Type"] = "application/json";
  return fetch(path, { method: "POST", headers, body: JSON.stringify(body) });
}
const card = makeCard(api);

// standing on the ground; leaving it, peeking over the app window, or returning.
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

// ---- the actions. Each takes the clip's handle; parts a figure lacks are
// passed over, so another figure does the whole-body part of each (and a
// painted one has its own ways of some, PAINTED). A pose is
// [x, y, turn, wide, tall], x and y in CSS px; [] is rest. Mibo faces right:
// an arm turned out from its side is a positive turn on the left, negative on the right.
// Nothing loops in place: what repeats is written out, a little different each time,
// and the parts start one after another, the body first, the light ones after.
const R = [];
const arms = (c, left, right, ms, how = {}) =>
  Promise.all([c.go("armL", left, ms, how), c.go("armR", right, ms, { ...how, delay: (how.delay || 0) + 50 })]);
const mirror = (frames) => frames.map(([x = 0, y = 0, turn = 0, wide, tall] = []) => [-x, y, -turn, wide, tall]);
// Times for n keyframes, a little uneven, so no beat is quite like the one before.
const uneven = (n, spread = 0.25) => {
  const gaps = Array.from({ length: n - 1 }, () => 1 + (Math.random() * 2 - 1) * spread);
  const sum = gaps.reduce((a, b) => a + b, 0);
  let t = 0;
  return [0, ...gaps.map((g) => (t += g / sum))].map((v, i) => (i === n - 1 ? 1 : v));
};
// The antenna springing after a jolt: it swings `size` degrees and settles, its dot trailing.
const boing = (c, size = 10, delay = 0) => {
  const side = Math.random() < 0.5 ? 1 : -1;
  const s = size * side;
  return Promise.all([
    c.go("antenna", [R, [0, 0, s], [0, 0, -s * 0.55], [0, 0, s * 0.25], [0, 0, -s * 0.08], R], 950, {
      delay,
      at: [0, 0.14, 0.38, 0.6, 0.8, 1],
      ease: OUT,
    }),
    c.go("tip", [R, [-s * 0.12, 0], [s * 0.07, 0], [-s * 0.02, 0], R], 950, { delay: delay + 70, ease: OUT }),
  ]);
};
// Its head turned to one side (-1 or 1): the eyes and visor go over, the ears
// come round after them, the far one narrower; the antenna leans the other way.
function turnHead(c, side, ms = 360) {
  c.look(side * 6, 0);
  return Promise.all([
    c.go("earL", [[side * 1.4, 0, 0, side > 0 ? 1 : 0.85, 1]], ms, { hold: true, delay: 60, ease: OUT }),
    c.go("earR", [[side * 1.4, 0, 0, side < 0 ? 1 : 0.85, 1]], ms, { hold: true, delay: 60, ease: OUT }),
    c.go("antenna", [[0, 0, -side * 4]], ms + 200, { hold: true, delay: 100, ease: OUT }),
  ]);
}
// ---- getting about. Mibo turns three-quarters toward where it goes, its eyes
// first and its body after: the visor and eyes over to that side, the far ear
// round behind its head, the near arm in front of the body and the far one
// behind, the far foot a little higher and smaller. Then it walks on its two
// stub feet: each step lifts a foot in an arc and puts it down ahead of the
// body, while the other stands still on the ground as the figure moves (read
// from where it is each frame, so it never slides); the body is lowest just
// after a foot comes down and highest as it passes over it, and rocks over the
// planted foot; the arms swing against the feet, the antenna trails. Stopping,
// a last step, the back foot brought up beside it, the weight settling, and it
// turns back to face the person. Or it hops: a crouch, a push, a short low
// arc with its window moving only while it is in the air (`leap` moves
// something else instead), a landing. It hops when in a hurry or pleased,
// now and then, never twice running (hopping).
// One clock for every part, each frame, only while it goes.
let hopped = false;
const hopping = () => !hopped && Math.random() < 0.6;
// Each part in the three-quarter view, `k` of the way there.
const quarter = (k) => ({
  visor: [14 * k, 0, 0, 1 - 0.18 * k, 1],
  eyes: [2 * k, 0, 0, 1 - 0.04 * k, 1],
  chest: [13 * k, 0, 0, 1 - 0.2 * k, 1],
  earL: [5 * k, 0, 0, 1 + 0.1 * k, 1],
  earR: [-6 * k, 0, 0, 1 - 0.3 * k, 1],
  armL: [5 * k, 0.5 * k, 0],
  armR: [-6 * k, -1 * k, 0],
  footL: [2 * k, 1.5 * k, 0, 1 + 0.04 * k, 1 + 0.04 * k],
  footR: [-2 * k, -2.5 * k, 0, 1 - 0.08 * k, 1 - 0.08 * k],
  body: [0, 0, 0, 1 - 0.02 * k, 1],
});
const smooth = (t) => (t <= 0 ? 0 : t >= 1 ? 1 : t * t * (3 - 2 * t));
const plus = ([x = 0, y = 0, t = 0, w = 1, h = w] = [], [x2 = 0, y2 = 0, t2 = 0, w2 = 1, h2 = w2] = []) => [x + x2, y + y2, t + t2, w * w2, h * h2];
// Where the ground under its middle is on the screen, and how big it is: its window, and the figure moved within it.
function ground() {
  const m = new DOMMatrix(getComputedStyle(actor).transform);
  return { x: screenX + m.e, s: m.a || 1 };
}
// Going, if it is: a press, a card or the screen's edge ends it with a last step.
let going = null;
// Its window to `x` CSS px on the screen, moved by the page as it walks
// (window.py place): only when that is another device pixel, and in the
// frame its feet are drawn for it. Told where the walk began too: on a scaled
// monitor screenX is in whole CSS px, so the window goes on from where it was.
function placeWindow(s, x) {
  s.x = x;
  s.startAt ??= s.at;
  const at = Math.round(x * devicePixelRatio) / devicePixelRatio;
  if (at !== s.at) window.pywebview.api.place((s.at = at), s.startAt);
}
// It turns, then goes once its window is set walking (for `ms`), or once
// `start()` has set the figure moving within it, until that is over (and,
// with `stop` false, gone the moment it is: out of sight). A painted figure
// walks on its poses (stride).
function travel(c, how) {
  if (rig.kind === "painted" && rig.walks) return stride(c, how);
  const { fast = false, ms = 0, start, stop = true, hop = false, leap } = how;
  if (rig.kind !== "mibo") return bounce(c, fast, ms, start);
  hopped = hop;
  return new Promise((resolve) => {
    const p = rig.parts;
    const dir = pet.classList.contains("left") ? -1 : 1;
    const px = fast ? TROT_PX : STEP_PX;
    const P = hop ? (fast ? 460 : 560) : fast ? 260 : 340;
    const lift = fast ? 5 : 4;
    const drive = ms && !hop;
    const g = { L: spring(), R: spring(), antenna: spring(), tip: spring() };
    const s = {
      t0: performance.now(),
      phase: "in",
      start: 0,
      step: -1,
      swing: "R",
      from: 0,
      to: 0,
      plant: { L: 0, R: 0 },
      rel: { L: 0, R: 0 },
      closing: 0,
      rested: false,
      last: 0,
      was: null,
      // Its speed, CSS px a ms: as the window is set to go, then as measured.
      v: px / 30,
      top: px / 30,
      speed: 0,
      x: screenX,
      at: screenX,
    };
    going = s;
    p.body.querySelector(".shell").after(p.armL);
    for (const el of [p.visor, p.eyes]) el.style.transition = "none";
    const set = (el, frame) => el && (el.style.transform = poseCss(frame, rig.k));
    const rest = () => {
      if (!s.rested && ms) window.pywebview.api.rest();
      s.rested = true;
      walking = false;
    };
    const finish = () => {
      going = null;
      rest();
      p.armR.before(p.armL);
      for (const el of [p.visor, p.eyes]) el.style.transition = "";
      if (!carry)
        for (const name of ["root", "body", "armL", "armR", "footL", "footR", "antenna", "tip", "earL", "earR", "chest", "eyes", "visor", "shadow"])
          if (p[name]) p[name].style.transform = "";
      setLook();
      resolve();
    };
    s.end = () => s.closing || (s.closing = 1);
    const frame = (now) => {
      if (!c.alive() || s.phase === "gone") return finish();
      const t = now - s.t0;
      const dt = s.last ? Math.min(0.034, (now - s.last) / 1000) : 1 / 60;
      s.last = now;
      // Walking, it moves its window itself, each frame as it draws the feet
      // for it, speeding up over the first step and slowing over the last two.
      if (drive && s.phase === "go") {
        const target = s.closing >= 2 ? 0 : s.closing ? s.top * 0.6 : s.top;
        s.speed += (target - s.speed) * Math.min(1, (dt * 1000) / (P * 0.6));
        placeWindow(s, s.x + dir * s.speed * dt * 1000);
      }
      const here = drive ? { x: s.at, s: 1 } : ground();
      if (s.was && now > s.was.t) s.v += (Math.abs(here.x - s.was.x) / (now - s.was.t) - s.v) * Math.min(1, dt * 4);
      s.was = { x: here.x, t: now };
      let k = 1;
      let kEyes = 1;
      let bob = 0;
      let air = 0;
      let rock = 0;
      let tall = 1;
      const pose = { armL: [], armR: [], footL: [], footR: [], shadow: [] };
      if (s.phase === "in") {
        // Its eyes go first, its body turns after them, its weight onto the near foot.
        kEyes = smooth(t / 200);
        k = smooth((t - 90) / 290);
        rock = -1.2 * smooth((t - 240) / 180);
        tall = 1 - 0.02 * smooth((t - 240) / 180);
        if (t >= 420) {
          s.phase = "go";
          s.start = now;
          s.was = null;
          s.plant.L = s.plant.R = here.x;
          walking = true;
          const moving = ms ? null : start();
          moving?.then(() => {
            if (!stop) s.phase = "gone";
            if (!ms) s.v = 0;
            s.rested = true;
            s.end();
          });
        }
      } else if (s.phase === "go") {
        const n = Math.floor((now - s.start) / P);
        const u = (now - s.start) / P - n;
        if (n !== s.step) {
          // A step begins: the foot that swung is down where it is, and the other lifts.
          if (s.step >= 0) s.plant[s.swing] = here.x + s.rel[s.swing] * dir * here.s;
          if (ms && !s.closing && now - s.start > ms - P) s.end();
          if (s.closing === 3) {
            s.phase = "home";
            s.t0 = now;
          } else {
            if (s.closing) s.closing++;
            s.step = n;
            s.swing = n % 2 ? "L" : "R";
            s.from = s.rel[s.swing];
            // Ahead of the body by half what it goes in a step; the last two beside each other under it.
            s.to = s.closing ? 0 : ((drive ? s.top : s.v) * P) / 2 / here.s;
            // A hop moves the window, or what `leap` moves, only while it is off the ground.
            if (hop && !s.closing)
              setTimeout(
                () => c.alive() && !s.closing && (leap ? leap(P * 0.36) : window.pywebview.api.walk(dir * px * 2.4, P * 0.36)),
                P * 0.27,
              );
          }
        }
        if (s.phase === "go") {
          const planted = s.swing === "L" ? "R" : "L";
          if (hop && s.closing < 2) {
            // Crouch, push, the air, a landing that squashes and comes back.
            const up = u > 0.26 && u < 0.72 ? Math.sin(((u - 0.26) / 0.46) * Math.PI) : 0;
            const crouch = u < 0.26 ? Math.sin((u / 0.26) * Math.PI * 0.5) * (1 - smooth((u - 0.2) / 0.06)) : 0;
            const land = u >= 0.72 ? Math.sin(((u - 0.72) / 0.28) * Math.PI) : 0;
            air = -(fast ? 7 : 6) * Math.pow(up, 0.8);
            tall = 1 - 0.06 * crouch - 0.06 * land + 0.04 * up;
            bob = 1.2 * (crouch + land);
            rock = 3 * up - 1.5 * crouch + land;
            pose.footL = [1.2 * up, 0, 10 * up];
            pose.footR = [1.2 * up, -1 * up, 12 * up];
            pose.armL = [0, 0, 34 * up - 12 * crouch];
            pose.armR = [0, 0, 28 * up - 10 * crouch];
            pose.shadow = [0, 0, 0, 1 - 0.3 * up, 1 - 0.3 * up];
          } else if (!hop) {
            // The planted foot holds still on the ground; the other swings over in an arc.
            s.rel[planted] = ((s.plant[planted] - here.x) * dir) / here.s;
            s.rel[s.swing] = s.from + (s.to - s.from) * smooth(u);
            const arc = Math.sin(Math.PI * Math.min(1, u * 1.1));
            const small = Math.min(1, Math.abs(s.to - s.from) / 3 + 0.4);
            pose["foot" + s.swing] = [0, -lift * arc * small, -10 * arc * small];
            bob = -(fast ? 2.2 : 1.6) * Math.sin(Math.PI * u) * small + 0.9 * Math.exp(-u * 10);
            tall = 1 - 0.03 * Math.exp(-u * 9) + 0.012 * Math.sin(Math.PI * u);
            rock = (planted === "L" ? -1 : 1) * 1.6 * Math.sin(Math.PI * u) + (s.closing ? 1 : fast ? 3 : 2);
            pose.shadow = [(s.rel.L + s.rel.R) * 0.25 + s.rel[planted] * 0.25, 0, 0, 1 - 0.04 * Math.sin(Math.PI * u), 1];
          }
        }
      } else {
        // Home: its weight settles, then it turns back, eyes first.
        tall = 1 - 0.03 * Math.sin(Math.PI * Math.min(1, t / 260));
        bob = 0.6 * Math.sin(Math.PI * Math.min(1, t / 260));
        kEyes = 1 - smooth((t - 200) / 200);
        k = 1 - smooth((t - 280) / 300);
        if (t > 620) return finish();
      }
      // Arms against the feet, a little late; the antenna and its dot trailing the bob.
      const swing = hop ? 0 : 18 / Math.max(3, (s.v * P) / 2);
      pull(g.L, -s.rel.R * swing, 16, 0.55, dt);
      pull(g.R, -s.rel.L * swing, 15, 0.55, dt);
      pull(g.antenna, s.phase === "go" && !s.closing ? -5 + (bob + air) * 1.4 : 0, 13, 0.32, dt);
      pull(g.tip, s.phase === "go" && !s.closing ? -1 - (bob + air) * 0.25 : 0, 16, 0.4, dt);
      const q = quarter(k);
      const qe = quarter(kEyes);
      set(p.visor, qe.visor);
      set(p.eyes, qe.eyes);
      set(p.chest, q.chest);
      set(p.earL, q.earL);
      set(p.earR, q.earR);
      set(p.root, [0, air]);
      set(p.body, plus(q.body, [0, bob, rock, 1 + (1 - tall) * 0.7, tall]));
      set(p.armL, plus(plus(q.armL, [0, 0, g.L.x]), pose.armL));
      set(p.armR, plus(plus(q.armR, [0, 0, g.R.x]), pose.armR));
      set(p.footL, plus(plus(q.footL, [s.rel.L, 0]), pose.footL));
      set(p.footR, plus(plus(q.footR, [s.rel.R, 0]), pose.footR));
      set(p.antenna, [0, 0, g.antenna.x]);
      set(p.tip, [g.tip.x, 0]);
      set(p.shadow, plus([0, -air], pose.shadow));
      requestAnimationFrame(frame);
    };
    requestAnimationFrame(frame);
  });
}
// A drawing with no joints bounces along as a whole, leaning the way it goes.
async function bounce(c, fast, ms, start) {
  c.go("body", [R, [0, fast ? -4 : -3, 2, 0.98, 1.03], R], fast ? 260 : 340, { loop: Infinity, ease: [OUT, IN] });
  walking = true;
  const px = (fast ? TROT_PX : STEP_PX) * (pet.classList.contains("left") ? -1 : 1);
  await c.until(ms ? window.pywebview.api.walk(px, ms) : start());
  walking = false;
}
// Up and down again: a crouch first, the push, time in the air, and a landing
// that squashes and comes back up once. No higher than the room above its head.
async function jump(c, height = 22, armsUp = 40, ms = 860) {
  height = Math.min(height, rig.room);
  const at = [0, 0.26, 0.4, 0.55, 0.69, 0.79, 0.9, 1];
  const later = at.map((t, i) => (i && i < at.length - 1 ? Math.min(0.99, t + 0.04) : t));
  const air = [R, R, [0, -height * 0.72], [0, -height], R, R, R, R];
  const arm = [R, [0, 0, -10], [-armsUp / 50, 0, armsUp * 0.8], [-armsUp / 50, 0, armsUp], [0, 0, armsUp * 0.5], [0, 0, -6], [0, 0, 3], R];
  await Promise.all([
    c.go("root", air, ms, { at, ease: [SOFT, OUT, "cubic-bezier(.3,.5,.5,1)", "cubic-bezier(.55,0,.9,.5)", "linear", "linear", "linear"] }),
    c.go(
      "body",
      [R, [0, 1.8, 0, 1.12, 0.86], [0, -2, 0, 0.92, 1.1], [0, -0.5, 0, 0.98, 1.03], [0, -1, 0, 0.95, 1.06], [0, 1.4, 0, 1.13, 0.86], [0, -0.6, 0, 0.97, 1.03], R],
      ms,
      { at, ease: [SOFT, OUT, OUT, IN, OUT, OUT, SOFT] },
    ),
    c.go(
      "shadow",
      [[0, 0, 0, 1, 1, 1], [0, 0, 0, 1.05, 1.05, 1], [0, 0, 0, 0.78, 0.78, 0.7], [0, 0, 0, 0.66, 0.66, 0.55], [0, 0, 0, 1, 1, 1], [0, 0, 0, 1.08, 1.08, 1], [0, 0, 0, 1, 1, 1], [0, 0, 0, 1, 1, 1]],
      ms,
      { at, ease: [SOFT, OUT, "cubic-bezier(.3,.5,.5,1)", "cubic-bezier(.55,0,.9,.5)", OUT, SOFT, "linear"] },
    ),
    c.go("footL", [R, R, [0, -0.5, 9], [0, -2.5, 6], [0, 0, -3], R, R, R], ms, { at: later }),
    c.go("footR", [R, R, [0, -0.5, -9], [0, -2.5, -6], [0, 0, 3], R, R, R], ms, { at: later }),
    arms(c, arm, mirror(arm), ms, { at: later }),
    c.go("tip", [R, [0, 1.2], [0, 2], [0, -1.2], [0, -1.5], [0, 2.2], [0, -0.5], R], ms, { at: later }),
    boing(c, 7, ms * 0.69),
  ]);
}

const CLIPS = {
  // Patted on the head: it sinks under the hand, eyes shut happy, the antenna
  // pressed over to one side and springing back after the hand has gone.
  async patHead(c) {
    c.face("happy");
    const at = [0, 0.18, 0.5, 0.72, 1];
    const s = Math.random() < 0.5 ? 1 : -1;
    await Promise.all([
      c.go("body", [R, [0, 1.6, 0, 1.05, 0.93], [0, 1.3, 0, 1.04, 0.94], [0, -0.6, 0, 0.98, 1.03], R], 1000, { at, ease: [OUT, SOFT, OUT, SOFT] }),
      c.go("antenna", [R, [0, 0, 28 * s], [0, 0, 24 * s], [0, 0, -9 * s], [0, 0, 3 * s], R], 1200, { at: [0, 0.15, 0.48, 0.66, 0.84, 1], delay: 20 }),
      c.go("earL", [R, [0, 1.2], [0, 1], R], 1000, { at: [0, 0.2, 0.6, 1], delay: 60 }),
      c.go("earR", [R, [0, 1.2], [0, 1], R], 1000, { at: [0, 0.2, 0.6, 1], delay: 100 }),
      arms(c, [R, [0, 0, 14], [0, 0, 12], R], [R, [0, 0, -14], [0, 0, -12], R], 1000, { at: [0, 0.22, 0.6, 1], delay: 80 }),
    ]);
  },
  // Booped on the face: eyes screwed shut, its face pushed back a little, a surprised look, and glad.
  async boop(c) {
    c.face("shut");
    c.wait(260).then(() => c.face("round"));
    c.wait(640).then(() => c.face("happy"));
    await Promise.all([
      c.go("visor", [R, [0, 0.5, 0, 0.93, 0.93], [0, -0.3, 0, 1.02, 1.02], R], 700, { at: [0, 0.15, 0.45, 1], ease: OUT }),
      c.go("body", [R, [0, 0.4, 0, 1.02, 0.98], R], 600, { at: [0, 0.2, 1], ease: OUT, delay: 30 }),
      boing(c, 7, 80),
      c.wait(1000),
    ]);
  },
  // Its feet pressed: a little shuffle, one foot and then the other, not quite in time.
  async shuffle(c) {
    c.face("happy");
    const at = uneven(6, 0.3);
    await Promise.all([
      c.go("footL", [R, [0, -3, -8], R, R, [0, -2.5, -6], R], 900, { at, ease: OUT }),
      c.go("footR", [R, R, [0, -3, 8], R, R, R], 900, { at, ease: OUT }),
      c.go("body", [R, [0, -1, -2], [0, -1, 2], [0, 0.4], [0, -0.8, -1.5], R], 920, { at, delay: 30 }),
      arms(c, [R, [0, 0, 18], [0, 0, 6], [0, 0, 14], [0, 0, 4], R], [R, [0, 0, -6], [0, 0, -18], [0, 0, -5], [0, 0, -12], R], 960, { at, delay: 70 }),
    ]);
  },
  // Poked once too often: it puffs up, stamps a foot, and looks away for a moment.
  async huff(c) {
    c.face("shut");
    const at = [0, 0.25, 0.7, 1];
    await Promise.all([
      c.go("body", [R, [0, -1, 0, 1.06, 1.03], [0, -1, 0, 1.06, 1.03], R], 700, { at, ease: OUT }),
      arms(c, [R, [0, 0, -10], [0, 0, -10], R], [R, [0, 0, 10], [0, 0, 10], R], 700, { at }),
      c.go("footR", [R, [0, -4, -6], [0, 0.5], R], 500, { at: [0, 0.4, 0.6, 1], ease: [OUT, IN, OUT], delay: 200 }),
      c.go("shadow", [R, R, [0, 0, 0, 1.04, 1.04], R], 500, { at: [0, 0.6, 0.7, 1], delay: 200 }),
    ]);
    if (!c.alive()) return;
    c.face("sleepy");
    await turnHead(c, Math.random() < 0.5 ? -1 : 1, 420);
    await c.wait(1500);
    if (!c.alive()) return;
    c.face("open");
    c.look(0, 0);
    await Promise.all([
      c.go("earL", [R], 300, { hold: true, ease: OUT }),
      c.go("earR", [R], 300, { hold: true, ease: OUT, delay: 40 }),
      c.go("antenna", [R], 500, { hold: true, ease: OUT, delay: 80 }),
    ]);
  },
  // Busy in a chat until `done`: thinking, a hand to its chin; searching, a
  // magnifier held out and swept now and then; reading, a page in both hands,
  // its eyes going along the lines. Still between those small moves.
  async busy(c, kind, done) {
    const hold = (part, frame, ms = 420, delay = 0) => c.go(part, [frame], ms, { hold: true, ease: OUT, delay });
    const prop = { searching: "magnifier", reading: "book" }[kind];
    try {
      if (prop) {
        pet.dataset.holding = prop;
        c.go(prop, [[0, 2, 0, 0.4, 0.4], R], 420, { ease: OUT, delay: 140 });
      }
      if (kind === "thinking") {
        c.face("think");
        c.look(3, -3);
        hold("body", [0, 0, -2], 520);
        hold("armR", [0, 0, -55], 460, 80);
      } else if (kind === "searching") {
        c.look(5, 0);
        hold("armR", [0, 0, -60], 420);
        hold("body", [0, 0, 2], 520, 40);
      } else {
        c.look(0, 4);
        hold("armL", [0, 0, -12], 420);
        hold("armR", [0, 0, 12], 420, 60);
        hold("body", [0, 0.6, 0, 1.01, 0.99], 520);
      }
      let n = 0;
      while (c.alive()) {
        const over = await Promise.race([done.then(() => true), c.wait(between(2600, 6000)).then(() => false)]);
        if (over || !c.alive()) break;
        n += 1;
        if (kind === "thinking") {
          if (n % 2) {
            c.face("shut");
            await c.wait(BLINK_SHUT);
            c.face("think");
          } else c.look(between(2, 4.5), between(-4, -2));
        } else if (kind === "searching") {
          const at = uneven(4, 0.2);
          c.look(6, -1);
          c.wait(700).then(() => c.alive() && c.look(4, 1));
          c.wait(1300).then(() => c.alive() && c.look(5, 0));
          c.go("armR", [[0, 0, -60], [0, 0, -72], [0, 0, -52], [0, 0, -60]], 1600, { at, ease: SOFT });
          await c.go("magnifier", [R, [0, 0, -12], [0, 0, 8], R], 1600, { at, ease: SOFT });
        } else {
          c.look(-2, 4);
          await c.wait(800);
          c.look(2, 4.5);
          await c.wait(800);
          if (n % 2 === 0) {
            c.face("shut");
            await Promise.all([c.go("book", [R, [0, 0, 0, 0.9, 1], R], 420, { ease: SOFT }), c.wait(BLINK_SHUT)]);
            c.face("open");
          }
          c.look(-1.5, 4);
        }
      }
    } finally {
      if (prop && c.alive()) await c.go(prop, [R, [0, 2, 0, 0.3, 0.3]], 260, { hold: true, ease: IN });
      delete pet.dataset.holding;
    }
    if (!c.alive()) return;
    c.face("open");
    c.look(0, 0);
    await calm(320);
    await CLIPS.nod(c);
  },
  // Out on a walk, as the service says: it turns and walks out of its window, and a small sign stays.
  async leave(c) {
    const left = Math.random() < 0.5;
    went = left;
    // Mibo is the same either way round at rest: it turns as it sets off.
    if (c.mibo) pet.classList.toggle("left", left);
    else await flip(left);
    // Off into the distance, not through its window's edge: smaller and fainter as it goes.
    const off = (left ? -1 : 1) * 40;
    await travel(c, {
      stop: false,
      start: () =>
        animate(actor, [[0, 0, 0, 1, 1, 1], [off * 0.12, 0, 0, 1, 1, 1], [off, 8, 0, 0.45, 0.45, 0]], 2400, {
          px: true,
          hold: true,
          at: [0, 0.18, 1],
          ease: [IN, "cubic-bezier(.3,0,.7,1)"],
        }),
    });
    if (c.alive()) pet.dataset.state = "out";
  },
  // Back from its walk: in from the side it went, its find held up over its
  // head, and shown to the person before it is put away.
  async back(c) {
    const from = went ?? Math.random() < 0.5;
    const off = (from ? -1 : 1) * 40;
    pet.classList.toggle("left", !from);
    actor.style.transform = "";
    actor.style.opacity = "0";
    // Pleased to be back with something, now and then it hops in: four hops
    // from out of sight, nearer with each one, still while it is down.
    const way = (p) => [off * (1 - p), 8 * (1 - p), 0, 0.45 + 0.55 * p, 0.45 + 0.55 * p, Math.min(1, p * 1.6)];
    let near = 0;
    let arrived = null;
    const there = new Promise((resolve) => (arrived = resolve));
    const hopIn = {
      hop: true,
      start: () => {
        actor.style.opacity = "";
        animate(actor, [way(0)], 1, { px: true, hold: true });
        return there;
      },
      leap: (ms) => {
        const from = near;
        near = Math.min(1, near + 0.25);
        animate(actor, [way(from), way(near)], ms, { px: true, hold: true, ease: SOFT });
        if (near === 1) wait(ms).then(arrived);
      },
    };
    // Turned toward the person before it is seen, and walked in.
    const coming = travel(
      c,
      hopping()
        ? hopIn
        : {
            start: () =>
              (actor.style.opacity = "") ||
              animate(actor, [[off, 8, 0, 0.45, 0.45, 0], [off * 0.1, 0, 0, 1, 1, 1], [0, 0, 0, 1, 1, 1]], 2400, {
                px: true,
                at: [0, 0.85, 1],
                ease: ["cubic-bezier(.3,0,.7,1)", OUT],
              }),
          },
    );
    c.wait(940).then(() => {
      if (!c.alive()) return;
      pet.dataset.holding = "found";
      c.go("armR", [[0, 0, -150]], 300, { hold: true, ease: OUT });
      c.go("found", [[0, 0, 150, 0.3, 0.3], R], 300, { ease: OUT, delay: 80 });
    });
    try {
      await coming;
      if (!c.alive()) return;
      c.face("happy");
      c.look(1, -2);
      await Promise.all([
        c.go("body", [R, [0, -2, 0, 0.96, 1.05], R], 700, { at: [0, 0.3, 1], ease: OUT }),
        c.go("found", [R, [0, -1, 0, 1.15, 1.15], R], 600, { at: [0, 0.35, 1], ease: OUT, delay: 80 }),
        boing(c, 8, 200),
      ]);
      await c.wait(900);
      if (!c.alive()) return;
      const at = [0, 0.7, 1];
      await Promise.all([
        c.go("armR", [[0, 0, -150], [0, 0, 6], R], 620, { at, ease: [IN, OUT], hold: true }),
        c.go("found", [R, [0, 0, 156, 0.3, 0.3]], 460, { hold: true, ease: IN }),
      ]);
    } finally {
      delete pet.dataset.holding;
    }
  },
  // "Do not disturb": headphones on, pulled down over its ears, and a contented blink.
  async quietOn(c) {
    pet.dataset.dnd = "";
    c.face("happy");
    await Promise.all([
      c.go("phones", [[0, -16, 0, 1.06, 1.06], [0, 1, 0, 1, 1], R], 620, { at: [0, 0.62, 1], ease: [IN, OUT] }),
      c.go("body", [R, R, [0, 0.8, 0, 1.03, 0.97], R], 700, { at: [0, 0.52, 0.7, 1], ease: OUT }),
      c.go("antenna", [R, R, [0, 0, -6], [0, 0, 2], R], 900, { at: [0, 0.5, 0.65, 0.85, 1] }),
    ]);
    if (!c.alive()) return;
    c.face("shut");
    await c.wait(260);
  },
  async quietOff(c) {
    await Promise.all([
      c.go("phones", [R, [0, -16, 0, 1.06, 1.06]], 360, { hold: true, ease: OUT }),
      c.go("body", [R, [0, -0.8, 0, 0.98, 1.02], R], 500, { at: [0, 0.4, 1], ease: OUT }),
    ]);
    delete pet.dataset.dnd;
    if (!c.alive()) return;
    c.face("open");
    await boing(c, 6);
  },
  // One slow breath: in quicker than out, the arms and antenna a little behind.
  async breathe(c) {
    const at = [0, 0.38, 1];
    await Promise.all([
      c.go("body", [R, [0, -1, 0, 1.015, 1.014], R], 2600, { at }),
      arms(c, [R, [0, 0, 3], R], [R, [0, 0, -2.5], R], 2600, { at, delay: 180 }),
      c.go("antenna", [R, [0, 0, -2], R], 2600, { at, delay: 320 }),
    ]);
  },
  async blink(c) {
    c.face("shut");
    await c.wait(BLINK_SHUT);
  },
  async doubleBlink(c) {
    c.face("shut");
    await c.wait(90);
    c.face("open");
    await c.wait(140);
    c.face("shut");
    await c.wait(80);
  },
  // Its head turns one way, a blink, and the other way; the body shifts its weight a little late.
  async lookAround(c) {
    const first = Math.random() < 0.5 ? -1 : 1;
    c.go("body", [R, [0, 0, first * 1.5], [0, 0, first * 1.5], [0, 0, -first * 1.2], [0, 0, -first * 1.2], R], 2800, {
      delay: 160,
      at: [0, 0.18, 0.4, 0.55, 0.85, 1],
    });
    await turnHead(c, first);
    await c.wait(between(600, 900));
    c.face("shut");
    await c.wait(BLINK_SHUT);
    c.face("open");
    await turnHead(c, -first, 420);
    await c.wait(between(700, 1000));
    c.look(1, -1);
    await Promise.all([
      c.go("earL", [R], 300, { hold: true, ease: OUT }),
      c.go("earR", [R], 300, { hold: true, ease: OUT, delay: 40 }),
      c.go("antenna", [R], 500, { hold: true, ease: OUT, delay: 80 }),
      c.wait(300),
    ]);
    calm(0);
    c.look(0, 0);
    await c.wait(200);
  },
  async antennaWobble(c) {
    await Promise.all([
      c.go("body", [R, [0, 0.6, 0, 1.012, 0.988], R], 360, { at: [0, 0.3, 1], ease: OUT }),
      boing(c, 14, 60),
      c.go("earL", [R, [0, -1.2], R], 420, { delay: 90, ease: OUT }),
      c.go("earR", [R, [0, -1], R], 400, { delay: 150, ease: OUT }),
    ]);
  },
  // Arms up, up on its toes, eyes shut; and down, the arms last, with a little bounce.
  async stretch(c) {
    const at = [0, 0.18, 0.45, 0.7, 0.86, 1];
    const arm = [R, [0, 0, 10], [-3, -2, 165], [-3, -2, 158], [0, 0, -6], R];
    c.wait(450).then(() => c.face("shut"));
    c.wait(1900).then(() => c.face("happy"));
    await Promise.all([
      c.go("body", [R, [0, 1, 0, 1.04, 0.95], [0, -3, 0, 0.95, 1.08], [0, -3, 0, 0.96, 1.07], [0, 0.5, 0, 1.02, 0.98], R], 2600, { at }),
      arms(c, arm, mirror(arm), 2700, { at: [0, 0.2, 0.47, 0.72, 0.9, 1], delay: 120 }),
      c.go("footL", [R, R, [0, 0, -6], [0, 0, -5], R, R], 2600, { at }),
      c.go("footR", [R, R, [0, 0, 6], [0, 0, 5], R, R], 2600, { at }),
      c.go("antenna", [R, [0, 0, -8], [0, 0, 5], [0, 0, -2], [0, 0, 6], R], 2800, { at, delay: 200 }),
    ]);
  },
  async yawn(c) {
    c.face("sleepy");
    const at = [0, 0.25, 0.55, 0.8, 1];
    c.wait(600).then(() => c.face("shut"));
    c.wait(1900).then(() => c.face("sleepy"));
    await Promise.all([
      c.go("body", [R, [0, -1.5, -2, 0.97, 1.05], [0, -2, -3, 0.96, 1.06], [0, 0.5, 0, 1.01, 0.99], R], 2800, { at }),
      arms(c, [R, [0, 0, 35], [0, 0, 50], [0, 0, 8], R], [R, [0, 0, -30], [0, 0, -46], [0, 0, -6], R], 2900, { at, delay: 140 }),
      c.go("antenna", [R, [0, 0, -10], [0, 0, -14], [0, 0, 4], R], 3000, { at, delay: 260 }),
      c.go("visor", [R, [0, -1.5], [0, -2], R, R], 2800, { at }),
    ]);
    c.face("shut");
    await c.wait(BLINK_SHUT);
  },
  // A hand up to the side of its head, a few scratches, none quite the same, while it thinks.
  async scratchHead(c) {
    c.face("think");
    c.look(-3, -3);
    const up = [5, -1, -146];
    const n = 4 + Math.floor(Math.random() * 3);
    const scratches = [up];
    for (let i = 0; i < n; i++) scratches.push([5, -1, -146 + between(8, 15)], [5 + between(-0.5, 0.5), -1, -146 - between(0, 3)]);
    await Promise.all([
      c.go("body", [R, [0, 0, -4], [0, 0, -3.5], R], 2600, { at: [0, 0.15, 0.85, 1] }),
      c.go("antenna", [R, [0, 0, -6], [0, 0, -5], R], 2800, { at: [0, 0.2, 0.85, 1], delay: 120 }),
      (async () => {
        await c.go("armR", [R, up], 420, { hold: true, ease: OUT, delay: 80 });
        await c.go("armR", scratches, 230 * n, { at: uneven(scratches.length) });
        await c.go("armR", [up, [0, 0, 8], R], 520, { at: [0, 0.7, 1], ease: [IN, OUT] });
      })(),
    ]);
  },
  // Tapping one foot, eyes to the side: taps at uneven times, the body nodding on each.
  async tapFoot(c) {
    c.look(5, 2);
    const n = 4 + Math.floor(Math.random() * 3);
    const foot = [R];
    const body = [R];
    for (let i = 0; i < n; i++) {
      const toe = -between(20, 28);
      foot.push([0, -1, toe], R);
      body.push([0, 0.5, 0, 1.01, 0.99], R);
    }
    const at = uneven(foot.length, 0.3);
    const ms = 290 * n;
    await Promise.all([
      c.go("footR", foot, ms, { at, ease: OUT }),
      c.go("body", body, ms, { at: at.map((t, i) => (i && i < at.length - 1 ? Math.min(0.99, t + 0.02) : t)) }),
      arms(c, [R, [0, 0, -10], [0, 0, -9], R], [R, [0, 0, 10], [0, 0, 11], R], ms, { at: [0, 0.15, 0.85, 1] }),
    ]);
    c.look(0, 0);
    await c.wait(200);
  },
  walk: (c, ms, hop = false) => travel(c, { ms, hop }),
  trot: (c, ms, hop = false) => travel(c, { ms, fast: true, hop }),
  async turn() {
    await flip(!pet.classList.contains("left"));
  },
  hop: (c) => jump(c),
  // Set down after being carried: it looks at the person, a blink, and its eyes come back to rest.
  async landed(c) {
    c.look(0, -1);
    await c.go("body", [R, [0, -0.6, 0, 0.99, 1.012], R], 420, { at: [0, 0.35, 1], ease: OUT });
    c.face("shut");
    await c.wait(BLINK_SHUT);
    c.face("open");
    await c.wait(500);
  },
  // Set down dizzy from being shaken: it sways round in a slowing circle, then shakes it off.
  async dizzy(c) {
    c.face("dizzy");
    const at = [0, 0.2, 0.42, 0.62, 0.8, 1];
    await Promise.all([
      c.go("body", [R, [0, 0, -5], [0, 0.6, 4], [0, 0, -2.5], [0, 0.3, 1.2], R], 1700, { at, ease: SOFT }),
      arms(c, [R, [0, 0, 30], [0, 0, 12], [0, 0, 22], [0, 0, 6], R], [R, [0, 0, -10], [0, 0, -28], [0, 0, -8], [0, 0, -16], R], 1800, { at, delay: 120 }),
      c.go("antenna", [R, [0, 0, 10], [0, 0, -9], [0, 0, 6], [0, 0, -3], R], 1900, { at, delay: 200 }),
      c.go("footL", [R, R, [0, -2, -6], R, R, R], 1700, { at }),
    ]);
    if (!c.alive()) return;
    c.face("shut");
    await Promise.all([
      c.go("visor", [R, [-4, 0], [4, 0], [-2, 0], R], 600, { ease: OUT }),
      c.go("body", [R, [0, 0, -2], [0, 0, 2], [0, 0, -1], R], 620, { delay: 40 }),
      boing(c, 8, 120),
    ]);
    c.face("open");
    await c.wait(300);
  },
  // A wave: the hand up, three waves, each a little smaller, and down with an overshoot.
  async wave(c) {
    c.face("happy");
    c.look(2, -1);
    const up = [3, 0, -150];
    const waves = [up];
    for (const size of [34, 28, 22]) waves.push([3, 0, -150 + size + between(-3, 3)], up);
    await Promise.all([
      c.go("body", [R, [0, 0, -3], [0, 0, -2.5], R], 1900, { at: [0, 0.15, 0.85, 1] }),
      (async () => {
        await c.go("armR", [R, up], 320, { hold: true, ease: OUT, delay: 60 });
        await c.go("armR", waves, 1000, { at: uneven(waves.length, 0.15) });
        await c.go("armR", [up, [0, 0, 7], R], 560, { at: [0, 0.65, 1], ease: [IN, OUT] });
      })(),
      boing(c, 6, 340),
    ]);
  },
  async nod(c) {
    const at = [0, 0.22, 0.45, 0.66, 1];
    await Promise.all([
      c.go("visor", [R, [0, 4], [0, -0.8], [0, 2.4], R], 1000, { at, ease: OUT }),
      c.go("body", [R, [0, 1, 1.5, 1.02, 0.985], [0, -0.2], [0, 0.6, 0.8, 1.01, 0.99], R], 1050, { at, delay: 30 }),
      c.go("tip", [R, [0, 1.5], [0, -1], [0, 1], R], 1100, { at, delay: 110 }),
    ]);
  },
  async shakeHead(c) {
    c.face("shut");
    c.wait(250).then(() => c.face("open"));
    const at = [0, 0.16, 0.38, 0.6, 0.8, 1];
    await Promise.all([
      c.go("visor", [R, [-5, 0], [5, 0], [-3.5, 0], [2, 0], R], 1000, { at }),
      c.go("body", [R, [0, 0, -2], [0, 0, 2], [0, 0, -1.2], [0, 0, 0.6], R], 1000, { at, delay: 40 }),
      c.go("antenna", [R, [0, 0, 8], [0, 0, -8], [0, 0, 5], [0, 0, -2], R], 1100, { at, delay: 110 }),
    ]);
  },
  // Head on one side, curious: over quickly, held, back slowly.
  async tiltHead(c) {
    c.look(0, -2);
    const at = [0, 0.18, 0.72, 1];
    await Promise.all([
      c.go("body", [R, [0, 0, 7], [0, 0, 6.5], R], 1900, { at, ease: [OUT, SOFT, SOFT] }),
      c.go("antenna", [R, [0, 0, -6], [0, 0, 3], [0, 0, -4], R], 2000, { at: [0, 0.22, 0.42, 0.8, 1], delay: 90 }),
      c.go("earL", [R, [0, -1.5], [0, -1.4], R], 1900, { at, delay: 60 }),
    ]);
  },
  // Leaning in to look at something just ahead: the body bends over the front
  // foot, the back foot comes up to balance it, an arm goes out behind.
  async peekLean(c) {
    const at = [0, 0.3, 0.72, 1];
    c.wait(500).then(() => c.face("round"));
    c.wait(1300).then(() => c.face("open"));
    c.look(6, 1);
    await Promise.all([
      c.go("body", [R, [1.5, 0.5, 9, 1.01, 0.99], [1.5, 0.5, 8, 1.01, 0.99], R], 2200, { at, ease: [OUT, SOFT, SOFT] }),
      c.go("footL", [R, [-1, -3, -12], [-1, -3, -10], R], 2200, { at: [0, 0.34, 0.7, 1], ease: OUT }),
      c.go("armL", [R, [0, 0, 28], [0, 0, 24], R], 2300, { at, delay: 100 }),
      c.go("armR", [R, [0, 0, -14], [0, 0, -12], R], 2300, { at, delay: 140 }),
      c.go("antenna", [R, [0, 0, -7], [0, 0, 2], R], 2400, { at, delay: 180 }),
    ]);
  },
  // A card: held up on its toes, pointed at, and a hopeful look at the person.
  async holdCard(c) {
    c.face("happy");
    const at = [0, 0.3, 0.75, 1];
    await Promise.all([
      c.go("body", [R, [0, -2.5, 0, 0.96, 1.05], [0, -2.5, 0, 0.965, 1.045], R], 1000, { at, ease: [OUT, SOFT, SOFT] }),
      arms(c, [R, [0, 0, 60], [0, 0, 58], R], [R, [2, 0, -130], [2, 0, -126], R], 1050, { at, delay: 60 }),
      c.go("footL", [R, [0, 0, -5], [0, 0, -5], R], 1000, { at }),
      c.go("footR", [R, [0, 0, 5], [0, 0, 5], R], 1000, { at }),
      boing(c, 6, 250),
    ]);
  },
  async pointCard(c) {
    c.look(7, -1);
    const out = [0, 0, -88];
    await Promise.all([
      c.go("body", [R, [0, 0, 3], [0, 0, 2.5], R], 1400, { at: [0, 0.2, 0.8, 1] }),
      (async () => {
        await c.go("armR", [R, out], 320, { hold: true, ease: OUT, delay: 60 });
        await c.go("armR", [out, [0, 0, -99], out, [0, 0, -94], out], 520, { at: [0, 0.22, 0.5, 0.72, 1] });
        await c.wait(240);
        await c.go("armR", [out, [0, 0, 6], R], 420, { at: [0, 0.7, 1], ease: [IN, OUT] });
      })(),
    ]);
  },
  async hopeful(c) {
    c.face("round");
    c.look(4, -3);
    const at = [0, 0.25, 0.8, 1];
    await Promise.all([
      c.go("body", [R, [0.5, -2, 2, 0.98, 1.03], [0.5, -2, 2, 0.98, 1.03], R], 1800, { at, ease: [OUT, SOFT, SOFT] }),
      arms(c, [R, [0, 0, -12], [0, 0, -11], R], [R, [0, 0, 12], [0, 0, 11], R], 1800, { at, delay: 80 }),
      c.go("antenna", [R, [0, 0, 6], [0, 0, 4], R], 1900, { at, delay: 140 }),
      c.go("earL", [R, [0, -1.5], [0, -1.5], R], 1800, { at, delay: 60 }),
      c.go("earR", [R, [0, -1.5], [0, -1.5], R], 1800, { at, delay: 100 }),
    ]);
  },
  async present(c) {
    await CLIPS.holdCard(c);
    if (c.alive()) await CLIPS.pointCard(c);
    if (c.alive()) await CLIPS.hopeful(c);
  },
  // Liked: a big hop, both arms up, and a smaller one after.
  async cheer(c) {
    c.face("happy");
    await jump(c, 28, 155);
    if (c.alive()) await jump(c, 9, 60, 620);
  },
  // Its card put away: the eyes go down first, then the antenna, the arms last; slowly back.
  async droop(c) {
    c.face("sleepy");
    c.look(0, 3);
    const at = [0, 0.3, 0.75, 1];
    await Promise.all([
      c.go("body", [R, [0, 2, 0, 1.03, 0.96], [0, 2, 0, 1.03, 0.96], R], 2400, { at, delay: 120 }),
      c.go("antenna", [R, [0, 0, -24], [0, 0, -20], R], 2500, { at, delay: 260, ease: [IN, SOFT, OUT] }),
      c.go("tip", [R, [0, 2], [0, 2], R], 2500, { at, delay: 300 }),
      arms(c, [R, [0, 0, -6], [0, 0, -6], R], [R, [0, 0, 6], [0, 0, 6], R], 2500, { at, delay: 360 }),
    ]);
  },
  // Woken with a start: a jolt up off its feet, arms out, and down again.
  async startle(c) {
    c.face("round");
    await jump(c, 12, 60, 640);
    if (c.alive()) await c.wait(300);
  },
  // Nodding off: heavy eyes, the head drops twice, and they close.
  async dozeOff(c) {
    c.face("sleepy");
    c.look(0, 2);
    const at = [0, 0.3, 0.42, 0.8, 1];
    await Promise.all([
      c.go("body", [R, [0, 1, 3], [0, 0.2, 0.5], [0, 1.5, 5], R], 3600, { at, ease: [IN, OUT, IN, SOFT] }),
      c.go("antenna", [R, [0, 0, -10], [0, 0, -4], [0, 0, -16], R], 3700, { at, delay: 150 }),
      c.wait(2600).then(() => c.face("sleep")),
    ]);
  },
  async wake(c) {
    c.face("round");
    await c.wait(260);
    c.face("shut");
    await c.wait(BLINK_SHUT);
    c.face("open");
    const arm = [R, [0, 0, 70], [0, 0, -6], R];
    await Promise.all([
      c.go("body", [R, [0, -2, 0, 0.96, 1.06], [0, 0.4, 0, 1.01, 0.99], R], 900, { at: [0, 0.3, 0.7, 1], ease: OUT }),
      arms(c, arm, mirror(arm), 950, { at: [0, 0.32, 0.75, 1], delay: 80 }),
      boing(c, 12, 300),
    ]);
  },
  // Over the app window: it ducks behind the edge and comes up for another look.
  async peekDuck(c) {
    c.wait(1000).then(() => c.look(-5, 3));
    await animate(actor, [R, [0, 18], [0, 18], [0, -3], R], 1700, { at: [0, 0.22, 0.6, 0.8, 1], px: true, ease: [IN, SOFT, OUT, SOFT] });
    await c.wait(500);
    c.look(5, 3);
    await c.wait(700);
  },
  // Up over the window's edge: eyes down to the page, a blink.
  async peekArrive(c) {
    c.look(0, 3);
    await boing(c, 6);
    c.face("shut");
    await c.wait(BLINK_SHUT);
  },
  // Patted while it peeks: a quick duck behind the edge and up again.
  async duck() {
    await animate(actor, [R, [0, 70], [0, -5], R], 520, { at: [0, 0.36, 0.76, 1], px: true, ease: [IN, OUT, SOFT] });
  },
  // "Here you go", handing over the app window: a crouch, an arm held out, and up.
  async give(c) {
    c.face("happy");
    const at = [0, 0.35, 0.75, 1];
    await Promise.all([
      c.go("body", [R, [0, 1, -6, 1.08, 0.88], [0, -3, 4, 0.95, 1.07], R], 600, { at, ease: [SOFT, OUT, SOFT] }),
      c.go("armR", [R, [0, 0, 30], [0, 0, -120], R], 650, { at, delay: 40 }),
    ]);
  },
  // Saying a line: glad eyes, a few bounces of different sizes, a hand that talks along.
  async talk(c) {
    c.face("happy");
    const body = [R];
    for (let i = 0; i < 3 + Math.floor(Math.random() * 2); i++) {
      const s = between(0.6, 1.2);
      body.push([0, -1 * s, 0, 1 - 0.02 * s, 1 + 0.025 * s], R);
    }
    await Promise.all([
      c.go("body", body, 1700, { at: uneven(body.length, 0.3), ease: OUT }),
      c.go("armR", [R, [0, 0, -35], [0, 0, -22], [0, 0, -30], R], 1800, { at: [0, 0.2, 0.5, 0.75, 1], delay: 100 }),
      boing(c, 5, 200),
    ]);
  },
  async think(c) {
    c.face("think");
    c.look(3, -3);
    const at = [0, 0.2, 0.8, 1];
    await Promise.all([
      c.go("body", [R, [0, 0, -2], [0, 0, -2], R], 1800, { at }),
      c.go("armR", [R, [0, 0, -55], [0, 0, -52], R], 1850, { at, delay: 90 }),
    ]);
  },
  // The pointer came over it: ears and antenna up, quickly, and slowly down.
  async notice(c) {
    await Promise.all([
      c.go("body", [R, [0, -1, 0, 0.99, 1.02], R], 460, { at: [0, 0.25, 1], ease: OUT }),
      c.go("antenna", [R, [0, 0, 6], [0, 0, -3], R], 650, { at: [0, 0.2, 0.55, 1], delay: 60 }),
      c.go("earL", [R, [0, -2], R], 420, { at: [0, 0.25, 1], delay: 30 }),
      c.go("earR", [R, [0, -2], R], 420, { at: [0, 0.25, 1], delay: 90 }),
    ]);
  },
  // A wink, its head on one side.
  async wink(c) {
    c.look(2, -1);
    c.wait(150).then(() => c.face("wink"));
    await Promise.all([
      c.go("body", [R, [0, 0, -5], [0, 0, -4.5], R], 1100, { at: [0, 0.22, 0.75, 1], ease: [OUT, SOFT, SOFT] }),
      boing(c, 5, 150),
      c.wait(800),
    ]);
  },
  // Tickled or patted: a happy wriggle, squeezing up, uneven and dying away.
  async giggle(c) {
    c.face("happy");
    const s = Math.random() < 0.5 ? 1 : -1;
    const at = uneven(6, 0.3);
    await Promise.all([
      c.go("body", [R, [0, 0.5, -4 * s, 1.03, 0.97], [0, 0, 3.5 * s, 0.98, 1.02], [0, 0.4, -2.5 * s, 1.02, 0.98], [0, 0, 1.2 * s], R], 950, { at }),
      arms(c, [R, [0, 0, -18], [0, 0, -8], [0, 0, -16], [0, 0, -4], R], [R, [0, 0, 18], [0, 0, 8], [0, 0, 15], [0, 0, 4], R], 1000, { at, delay: 60 }),
      boing(c, 6, 180),
    ]);
  },
};
// What it does on its own, and how likely each is.
const IDLE = {
  mibo: {
    walk: 22, trot: 5, breathe: 8, lookAround: 10, antennaWobble: 7, stretch: 6, yawn: 3, scratchHead: 5,
    tapFoot: 5, hop: 4, wave: 3, nod: 3, tiltHead: 6, peekLean: 5, doubleBlink: 4, turn: 4, think: 3, wink: 2,
  },
  whole: { walk: 30, trot: 5, breathe: 12, hop: 8, tiltHead: 10, peekLean: 8, giggle: 6, turn: 6, doubleBlink: 6, lookAround: 8 },
  painted: { walk: 26, trot: 4, breathe: 14, lookAround: 12, doubleBlink: 8, tiltHead: 6, wave: 3, hop: 4, think: 3, nod: 3 },
  peek: { peekDuck: 40, lookAround: 30, doubleBlink: 30 },
};

// ---- a painted figure: its poses cut from paintings and packed into one
// picture by tools/figure_sheet.py, <key>.pet.webp, laid out in
// <key>.pet.json. It is drawn on two canvases the size of its window, one
// over the other. A pose is drawn on the lower one; one that differs only a
// little from the pose before (a turn of the head, a breath, held another
// way) fades in on the upper one, so the two paintings never boil; a real
// change of pose is a cut. Faces are painted over the rest pose and the peek:
// shut, smiling, a round mouth, eyes down. Nothing is drawn between changes.
const FACE_OF = {
  rest: { shut: "blink", sleep: "blink", wink: "blink", happy: "talk", talk: "talk", round: "talk2", talk2: "talk2", think: "look", sleepy: "look" },
  peek: { shut: "peek_blink", sleep: "peek_blink", wink: "peek_blink", happy: "peek_talk", talk: "peek_talk", round: "peek_talk", talk2: "peek_talk", think: "peek_look", sleepy: "peek_look" },
};
// Turned toward where it goes, painted going right: mirrored going left.
const SIDEWAYS = new Set(["walk1", "walk2", "walk3", "walk4", "turn"]);
// Contact, passing, contact on the other foot, passing.
const WALK = ["walk1", "walk2", "walk3", "walk4"];
// How long each walking pose holds (ms), two steps a second; in a hurry, this share of it.
const HOLD_MS = 260;
const HURRY = 0.6;
// While a walking pose holds, it leans on over the foot it stands on, at most this far (degrees).
const LEAN_MAX = 3;
// Where the feet are in the figure's box: the packer and Mibo's drawing both stand there.
const FEET_Y = 180;

async function paintedFigure(key) {
  const get = (kind) => fetch(`/assets/figures/${encodeURIComponent(key)}.${kind}`);
  const [laid, packed] = await Promise.all([get("pet.json"), get("pet.webp")]);
  if (!laid.ok || !packed.ok) return null;
  const layout = await laid.json();
  const atlas = await createImageBitmap(await packed.blob());
  const node = document.createElement("div");
  node.className = "sheet";
  const body = document.createElement("div");
  body.className = "sheet-body";
  const [under, over] = [0, 1].map(() => document.createElement("canvas"));
  body.append(under, over);
  node.append(body);
  // Where a pose is put together, at the packed picture's size.
  const scratch = document.createElement("canvas");
  scratch.width = layout.cell[0] * layout.scale;
  scratch.height = layout.cell[1] * layout.scale;
  const walks = WALK.every((name) => layout.frames[name]);
  const step = walks ? WALK.reduce((sum, name) => sum + layout.frames[name].advance, 0) / WALK.length : 0;
  return {
    node,
    shape: () => layout.shape,
    rig: {
      kind: "painted",
      k: 1,
      face: node,
      parts: { root: node, body },
      layout,
      atlas,
      under,
      over,
      scratch,
      walks,
      // How far it goes walking, CSS px a ms.
      speed: step / HOLD_MS,
      pose: "rest",
      shown: "",
      mirror: false,
      fading: null,
    },
  };
}
const has = (name) => Boolean(rig?.layout?.frames[name]);
// The first of these poses it has, else its rest.
const either = (...names) => names.find(has) || "rest";
const restPose = () =>
  pose === "peek" || pose === "returning" || "edge" in pet.dataset ? either("peek") : asleep() ? either("asleep", "doze") : "rest";

// A pose on a canvas: put together at the packed picture's size, a face over
// the pose under it, and drawn down to the canvas.
function drawPose(canvas, name, mirror) {
  const { layout, atlas, scratch } = rig;
  const mix = scratch.getContext("2d");
  mix.clearRect(0, 0, scratch.width, scratch.height);
  const put = (part) => {
    const f = layout.frames[part];
    if (f.on) {
      put(f.on);
      mix.clearRect(f.to[0], f.to[1], f.at[2], f.at[3]);
    }
    mix.drawImage(atlas, ...f.at, f.to[0], f.to[1], f.at[2], f.at[3]);
  };
  put(name);
  // As many pixels as the screen it is on has (a window moved to another screen may have more).
  const wide = Math.round(layout.cell[0] * devicePixelRatio);
  if (canvas.width !== wide) {
    canvas.width = wide;
    canvas.height = Math.round(layout.cell[1] * devicePixelRatio);
  }
  const pen = canvas.getContext("2d");
  pen.setTransform(1, 0, 0, 1, 0, 0);
  pen.clearRect(0, 0, canvas.width, canvas.height);
  if (mirror) pen.setTransform(-1, 0, 0, 1, canvas.width, 0);
  pen.imageSmoothingQuality = "high";
  pen.drawImage(scratch, 0, 0, canvas.width, canvas.height);
}
// Whether two poses are near enough alike to fade one into the other: the
// figure in much the same place, within this many CSS px at each edge.
const ALIKE_PX = 8;
function alike(a, b) {
  const { frames, scale } = rig.layout;
  const box = (name) => {
    const f = frames[frames[name].on || name];
    return [f.to[0], f.to[1], f.to[0] + f.at[2], f.to[1] + f.at[3]];
  };
  const [p, q] = [box(a), box(b)];
  return p.every((v, i) => Math.abs(v - q[i]) <= ALIKE_PX * scale);
}
// Poses painted from one another, so the rest of the picture is the same
// pixels: a slow fade between them shows only what moves. Any other two are
// separate paintings, whose hair and folds show twice midway through a slow
// fade: between those a fade is kept short.
const KIN = new Set(["idle2 rest", "held held2", "wave1 wave2"]);
const REPAINT_FADE = 110;
function kin(a, b) {
  const { frames } = rig.layout;
  const [p, q] = [frames[a].on || a, frames[b].on || b].sort();
  return p === q || KIN.has(`${p} ${q}`);
}
// Shown at once, or faded in over `fade` ms when the two are alike: a real
// change of pose is always a cut. The pose before goes only in the fade's
// second half, so the figure never thins as the two cross.
function showPose(name, fade = 0) {
  const r = rig;
  if (fade && r.shown && !kin(r.shown, name)) fade = Math.min(fade, REPAINT_FADE);
  const mirror = SIDEWAYS.has(name) && pet.classList.contains("left");
  if (r.fading) {
    r.fading.forEach((motion) => motion.cancel());
    r.fading = null;
    drawPose(r.under, r.shown, r.mirror);
  }
  if (name === r.shown && mirror === r.mirror) return;
  const cut = !fade || !r.shown || mirror !== r.mirror || !alike(r.shown, name);
  r.shown = name;
  r.mirror = mirror;
  if (cut) return drawPose(r.under, name, mirror);
  drawPose(r.over, name, mirror);
  const fading = [
    r.over.animate([{ opacity: 0 }, { opacity: 1 }], { duration: fade, easing: "ease-in-out" }),
    r.under.animate([{ opacity: 1 }, { opacity: 1 }, { opacity: 0 }], { duration: fade }),
  ];
  r.fading = fading;
  fading[0].finished.then(
    () => {
      if (r.fading !== fading) return;
      drawPose(r.under, name, mirror);
      fading.forEach((motion) => motion.cancel());
      r.fading = null;
    },
    () => {},
  );
}
// On a screen with more or fewer pixels, drawn again.
function redrawn() {
  matchMedia(`(resolution: ${devicePixelRatio}dppx)`).addEventListener("change", redrawn, { once: true });
  if (rig?.kind === "painted" && rig.shown) drawPose(rig.under, rig.shown, rig.mirror);
}
redrawn();
// A pose, with the face it has on where that pose has the face painted.
function setPose(name, fade = 0) {
  const r = rig;
  r.pose = has(name) ? name : "rest";
  const faced = FACE_OF[r.pose]?.[face];
  showPose(has(faced) ? faced : r.pose, fade);
}
// A painted figure turns its head to the pointer when it is well off to one side.
// Each turn holds a moment, so a pointer going by does not make it flicker;
// a turn asked for sooner comes when that moment is over.
const GLANCE_MS = 400;
let glanced = 0;
let glanceTimer = 0;
function glance(dx) {
  clearTimeout(glanceTimer);
  if (!["rest", "look_left", "look_right"].includes(rig.pose)) return;
  const to = dx < -70 ? "look_left" : dx > 70 ? "look_right" : Math.abs(dx) < 35 ? "rest" : rig.pose;
  if (to === rig.pose || !has(to)) return;
  const left = glanced + GLANCE_MS - performance.now();
  if (left > 0) return (glanceTimer = setTimeout(() => watching() && glance(dx), left));
  glanced = performance.now();
  setPose(to, 160);
}

// Walking, a painted figure goes on its four walking poses: as each comes on,
// its window steps on by what the packer measured, in the same frame, so the
// foot it stands on stays where it was on the screen. While a pose holds,
// the figure leans on over that foot a little, and the next pose stands it up
// again. It turns toward where it goes first (its turning pose, else a cut),
// and stops with a last step onto both feet and a turn back to the person.
// In a hurry the same poses hold shorter. `move`, when given, takes each
// step instead of its window (out of sight and back).
function stride(c, { fast = false, ms = 0, start, stop = true, move }) {
  return new Promise((resolve) => {
    const f = rig.layout.frames;
    const body = rig.parts.body;
    const dir = pet.classList.contains("left") ? -1 : 1;
    const hold = HOLD_MS * (fast ? HURRY : 1);
    const turn = has("turn");
    const s = { phase: "in", closing: 0, n: -1, since: 0, begun: 0, x: screenX, at: screenX, gone: false };
    s.end = () => s.closing || (s.closing = 1);
    going = s;
    const step = (dx) => (move ? move(dx) : ms && placeWindow(s, s.x + dx));
    const lean = (name, k) => {
      if (!name) return (body.style.transform = "");
      // Far enough to take its head on by about a third of the next step.
      const next = f[WALK[(WALK.indexOf(name) + 1) % 4]].advance;
      const most = Math.min(LEAN_MAX, (Math.atan((next * 0.35) / 150) * 180) / Math.PI);
      body.style.transformOrigin = `${dir > 0 ? f[name].plant : BOX[0] - f[name].plant}px ${FEET_Y}px`;
      body.style.transform = `rotate(${(dir * most * k * k).toFixed(2)}deg)`;
    };
    const finish = () => {
      going = null;
      walking = false;
      if (ms) window.pywebview.api.rest();
      body.style.transform = body.style.transformOrigin = "";
      resolve();
    };
    const frame = (now) => {
      if (!c.alive() || s.gone) return finish();
      if (s.phase === "in") {
        if (s.n < 0) {
          s.n = 0;
          s.since = now;
          if (turn) setPose("turn", 90);
        } else if (now - s.since >= (turn ? hold * 0.6 : 0)) {
          s.phase = "go";
          s.since = s.begun = now;
          setPose("walk1");
          walking = true;
          const moving = ms ? null : start?.();
          moving?.then(() => {
            if (!stop) s.gone = true;
            s.end();
          });
        }
      } else if (s.phase === "go") {
        if (now - s.since >= hold) {
          const was = WALK[s.n % 4];
          if (ms && !s.closing && now - s.begun > ms - hold * 2) s.end();
          s.since = now;
          if (s.closing && f[was].stop !== undefined) {
            s.phase = "home";
            setPose(either("turn"));
            step(dir * f[was].stop);
          } else {
            s.n += 1;
            const name = WALK[s.n % 4];
            setPose(name);
            step(dir * f[name].advance);
          }
        }
        lean(s.phase === "go" && WALK[s.n % 4], Math.min(1, (now - s.since) / hold));
      } else if (now - s.since >= hold * 0.7) {
        setPose("rest", turn ? 120 : 0);
        return finish();
      }
      requestAnimationFrame(frame);
    };
    requestAnimationFrame(frame);
  });
}
// The way out of sight beside its window, for a painted figure going out and
// coming back: smaller and fainter the further it goes, out of sight after
// six of its steps. `go` takes it a step on; `there` is when it is at the end.
function distance(side, coming = false) {
  const far = 6 * rig.speed * HOLD_MS;
  let gone = 0;
  let arrived = null;
  const there = new Promise((resolve) => (arrived = resolve));
  const put = (p) => {
    actor.style.transform = `translate(${(side * 40 * p).toFixed(1)}px, ${(8 * p).toFixed(1)}px) scale(${(1 - 0.55 * p).toFixed(3)})`;
    actor.style.opacity = String(1 - p * p);
  };
  put(coming ? 1 : 0);
  return {
    there,
    go(dx) {
      gone = Math.min(far, gone + Math.abs(dx));
      put(coming ? 1 - gone / far : gone / far);
      if (gone >= far) arrived();
    },
  };
}
// A painted jump: crouched, up in the air with its arms up, down onto its
// feet and up again, the whole figure going up and down with the poses.
async function bound(c, height = 8, ms = 780) {
  height = Math.min(height, rig.room);
  c.show(either("crouch"));
  await c.go("body", [R, [0, 0, 0, 1.03, 0.96]], ms * 0.18, { ease: OUT });
  if (!c.alive()) return;
  c.show(either("air"));
  await c.go("root", [R, [0, -height], R], ms * 0.5, { at: [0, 0.5, 1], ease: [OUT, IN] });
  if (!c.alive()) return;
  c.show(either("land", "crouch"));
  await c.go("body", [[0, 0, 0, 1.04, 0.95], R], ms * 0.14, { ease: OUT });
  if (!c.alive()) return;
  c.show("rest");
  await c.go("body", [[0, 0, 0, 0.98, 1.025], R], ms * 0.18, { ease: SOFT });
}
// What a painted figure does its own way; anything else it does as a whole
// (CLIPS), with its faces painted on.
const PAINTED = {
  hop: (c) => bound(c),
  shuffle: (c) => bound(c, 5, 680),
  async cheer(c) {
    await bound(c, 14, 860);
    if (c.alive()) await bound(c, 4, 640);
  },
  async startle(c) {
    c.show(either("surprised"));
    await c.go("root", [R, [0, -8], R], 460, { at: [0, 0.4, 1], ease: [OUT, IN] });
    await c.wait(500);
    c.show("rest", 140);
    await c.wait(160);
  },
  async wake(c) {
    c.show(either("surprised"));
    await c.go("body", [R, [0, -2, 0, 0.97, 1.04], R], 700, { at: [0, 0.3, 1], ease: OUT });
    await c.wait(300);
    c.show("rest", 160);
    await c.wait(400);
    c.face("shut");
    await c.wait(BLINK_SHUT);
    c.face("open");
  },
  // Nodding off: drowsy, its head going down twice, sinking, and asleep.
  async dozeOff(c) {
    c.show(either("doze"), 700);
    await c.go("body", [R, [0, 1, 2], [0, 0.3, 0.5], [0, 1.5, 3], [0, 3, 1, 1.03, 0.94]], 3400, { at: [0, 0.28, 0.4, 0.75, 1], ease: [IN, OUT, IN, SOFT] });
    c.show(either("asleep", "doze"), 600);
    await c.go("body", [[0, 1, 0, 1.02, 0.97], R], 500, { ease: OUT });
  },
  async yawn(c) {
    c.show(either("doze"), 400);
    await c.go("body", [R, [0, -1.5, 0, 0.97, 1.04], [0, -1.5, 0, 0.97, 1.04], R], 1600, { at: [0, 0.3, 0.7, 1] });
    c.show("rest", 500);
    await c.wait(500);
  },
  // One slow breath, its painted one: up a little and down again.
  async breathe(c) {
    if (!has("idle2")) return CLIPS.breathe(c);
    c.show("idle2", 900);
    await c.wait(1300);
    c.show("rest", 1100);
    await c.wait(1100);
  },
  // Its head to one side, then the other. Over the app window, only its eyes move.
  async lookAround(c) {
    if (pose === "peek") return CLIPS.doubleBlink(c);
    const sides = Math.random() < 0.5 ? ["look_left", "look_right"] : ["look_right", "look_left"];
    for (const side of sides) {
      c.show(side, 180);
      await c.wait(between(900, 1400));
      c.show("rest", 160);
      await c.wait(between(200, 500));
    }
  },
  // A head shake: turned one way and the other, quicker each time.
  async shakeHead(c) {
    c.face("shut");
    await c.wait(200);
    c.face("open");
    for (const [side, ms] of [["look_left", 170], ["look_right", 160], ["look_left", 140], ["look_right", 130]]) {
      c.show(side);
      await c.wait(ms);
    }
    c.show("rest", 120);
    await c.wait(200);
  },
  async patHead(c) {
    c.face("shut");
    const at = [0, 0.18, 0.5, 0.72, 1];
    await c.go("body", [R, [0, 1.6, 0, 1.04, 0.94], [0, 1.3, 0, 1.035, 0.95], [0, -0.6, 0, 0.99, 1.02], R], 1000, { at, ease: [OUT, SOFT, OUT, SOFT] });
    c.face("happy");
    await c.wait(600);
  },
  async giggle(c) {
    const s = Math.random() < 0.5 ? 1 : -1;
    const wriggle = c.go("body", [R, [0, 0.5, -3 * s, 1.02, 0.98], [0, 0, 2.5 * s, 0.99, 1.01], [0, 0.4, -1.8 * s, 1.01, 0.99], [0, 0, 0.8 * s], R], 950, { at: uneven(6, 0.3) });
    for (const mouth of ["happy", "round", "happy", "round", "happy"]) {
      c.face(mouth);
      await c.wait(between(120, 200));
    }
    await wriggle;
  },
  // Poked once too often: it puffs up and looks away for a moment.
  async huff(c) {
    c.face("shut");
    await c.go("body", [R, [0, -1, 0, 1.05, 1.03], [0, -1, 0, 1.05, 1.03], R], 700, { at: [0, 0.25, 0.7, 1], ease: OUT });
    if (!c.alive()) return;
    c.face("open");
    c.show(Math.random() < 0.5 ? "look_left" : "look_right", 200);
    await c.wait(1500);
    c.show("rest", 220);
    await c.wait(240);
  },
  async wave(c) {
    if (!has("wave1")) return CLIPS.wave(c);
    c.show("wave1");
    c.go("body", [[0, 0.8, 0, 1.02, 0.98], [0, -0.8, 0, 0.99, 1.02], R], 360, { ease: OUT });
    // Each swing a quick fade, so the hand moves and the painting does not flicker.
    for (let i = 0; i < 3 && c.alive(); i++) {
      await c.wait(between(190, 250));
      c.show(either("wave2", "wave1"), 90);
      await c.wait(between(190, 250));
      c.show("wave1", 90);
    }
    await c.wait(200);
    c.show("rest");
    await c.go("body", [[0, 0.6, 0, 1.015, 0.985], R], 300, { ease: OUT });
  },
  async nod(c) {
    c.wait(80).then(() => c.face("think"));
    c.wait(420).then(() => c.face("open"));
    c.wait(560).then(() => c.face("think"));
    c.wait(820).then(() => c.face("open"));
    await c.go("body", [R, [0, 1.2, 0, 1.02, 0.98], [0, -0.2], [0, 0.8, 0, 1.01, 0.99], R], 1050, { at: [0, 0.22, 0.45, 0.66, 1] });
  },
  // Saying a line: its mouth going, never quite in a beat, and a few small bounces.
  async talk(c) {
    const body = [R];
    for (let i = 0; i < 3 + Math.floor(Math.random() * 2); i++) {
      const s = between(0.6, 1.2);
      body.push([0, -1 * s, 0, 1 - 0.015 * s, 1 + 0.02 * s], R);
    }
    const bounce = c.go("body", body, 1700, { at: uneven(body.length, 0.3), ease: OUT });
    let said = 0;
    let mouth = "";
    while (said < 1600 && c.alive()) {
      mouth = fresh({ talk: 3, talk2: 2, open: 1 }, mouth);
      c.face(mouth);
      const ms = between(110, 190);
      await c.wait(ms);
      said += ms;
    }
    c.face("happy");
    await bounce;
  },
  async think(c) {
    c.face("think");
    await c.go("body", [R, [0, 0, -2], [0, 0, -2], R], 1800, { at: [0, 0.2, 0.8, 1] });
  },
  async notice(c) {
    c.face("round");
    c.wait(300).then(() => c.face("open"));
    await c.go("body", [R, [0, -1, 0, 0.99, 1.02], R], 460, { at: [0, 0.25, 1], ease: OUT });
  },
  antennaWobble: (c) => PAINTED.notice(c),
  // Handing over the app window: something held out, and back.
  async give(c) {
    c.show(either("give"));
    await c.go("body", [R, [0, -1.5, 0, 0.98, 1.03], R], 600, { at: [0, 0.35, 1], ease: OUT });
    c.show("rest");
  },
  // A card comes: surprised, a little jump, it holds something out, and looks at the card and back.
  async present(c) {
    c.show(either("surprised"));
    await c.go("root", [R, [0, -5], R], 380, { at: [0, 0.4, 1], ease: [OUT, IN] });
    await c.wait(250);
    if (!c.alive()) return;
    c.show(either("give"));
    await c.go("body", [R, [0, -1.5, 0, 0.98, 1.03], [0, -1, 0, 0.985, 1.02], R], 2200, { at: [0, 0.2, 0.8, 1], ease: [OUT, SOFT, SOFT] });
    if (!c.alive()) return;
    c.show(document.body.classList.contains("card-right") ? "look_right" : "look_left", 200);
    await c.wait(1300);
    c.show("rest", 200);
    await c.wait(220);
  },
  async droop(c) {
    c.face("sleepy");
    await c.go("body", [R, [0, 1.5, 0, 1.02, 0.97], [0, 1.5, 0, 1.02, 0.97], R], 2400, { at: [0, 0.3, 0.75, 1], delay: 120 });
  },
  // Busy in a chat until `done`: thinking, its head turned away and eyes down
  // by turns; searching, looking one way and the other; reading, eyes down, a blink now and then.
  async busy(c, kind, done) {
    const away = { thinking: either("look_right"), searching: either("look_left"), reading: "rest" }[kind];
    c.face(kind === "reading" ? "think" : "open");
    c.show(away, 240);
    let n = 0;
    while (c.alive()) {
      const over = await Promise.race([done.then(() => true), c.wait(between(2600, 6000)).then(() => false)]);
      if (over || !c.alive()) break;
      n += 1;
      if (kind === "thinking") {
        c.face(n % 2 ? "think" : "open");
        c.show(n % 2 ? "rest" : away, 220);
      } else if (kind === "searching") {
        c.show("rest", 160);
        await c.wait(220);
        c.show(either(n % 2 ? "look_right" : "look_left"), 180);
      } else {
        c.face("shut");
        await c.wait(BLINK_SHUT);
        c.face("think");
      }
    }
    if (!c.alive()) return;
    c.face("open");
    c.show("rest", 200);
    await c.wait(220);
    await PAINTED.nod(c);
  },
  async landed(c) {
    await c.go("body", [R, [0, -0.6, 0, 0.99, 1.012], R], 420, { at: [0, 0.35, 1], ease: OUT });
    c.face("shut");
    await c.wait(BLINK_SHUT);
    c.face("open");
    await c.wait(400);
  },
  // Set down dizzy from being shaken: it sways round in a slowing circle, then shakes it off.
  async dizzy(c) {
    c.show(either("dizzy", "surprised"));
    await c.go("body", [R, [0, 0, -4], [0, 0.6, 3.5], [0, 0, -2], [0, 0.3, 1], R], 1700, { at: [0, 0.2, 0.42, 0.62, 0.8, 1], ease: SOFT });
    if (!c.alive()) return;
    c.show("rest", 160);
    await PAINTED.shakeHead(c);
  },
  async peekArrive(c) {
    c.face("think");
    await c.wait(900);
    c.face("shut");
    await c.wait(BLINK_SHUT);
  },
  async turn() {},
  // Out on a walk: it walks off out of sight, and a small sign stays.
  async leave(c) {
    const left = Math.random() < 0.5;
    went = left;
    pet.classList.toggle("left", left);
    const way = distance(left ? -1 : 1);
    await travel(c, { stop: false, start: () => way.there, move: way.go });
    if (c.alive()) pet.dataset.state = "out";
  },
  // Back from its walk: in from the side it went, and what it found held out to the person.
  async back(c) {
    const from = went ?? Math.random() < 0.5;
    pet.classList.toggle("left", !from);
    const way = distance(from ? -1 : 1, true);
    try {
      await travel(c, { start: () => way.there, move: way.go });
      if (!c.alive()) return;
      c.face("happy");
      c.show(either("give"));
      await c.go("body", [R, [0, -2, 0, 0.97, 1.04], R], 700, { at: [0, 0.3, 1], ease: OUT });
      await c.wait(900);
      c.show("rest");
      await c.go("body", [[0, 0.6, 0, 1.015, 0.985], R], 300, { ease: OUT });
    } finally {
      actor.style.transform = actor.style.opacity = "";
    }
  },
};

// ---- its life at rest: a blink now and then, a small action at long gaps,
// and asleep, a breath and a z a few times a minute. Timers only.
let blinkTimer = 0;
let idleTimer = 0;
let sleepTimer = 0;
const lively = () => Boolean(timers) && rig && !["leaving", "returning"].includes(pose);
function blinkLater() {
  clearTimeout(blinkTimer);
  if (!lively() || asleep()) return;
  blinkTimer = setTimeout(() => {
    if (!scene && face === "open" && !dragging) {
      setFace("shut");
      setTimeout(() => face === "shut" && !scene && setFace(restFace()), BLINK_SHUT);
    }
    blinkLater();
  }, between(...BLINK_MS));
}
function idleLater() {
  clearTimeout(idleTimer);
  if (!lively()) return;
  idleTimer = setTimeout(idle, between(...IDLE_MS));
}
async function idle() {
  if (!scene && !press && !opening && !hushed && !asleep()) {
    if (pose === "peek") await play(pick(IDLE.peek));
    else if (!resting() && !("off" in pet.dataset)) {
      const name = idlePick();
      if (name === "walk" || name === "trot") await walk(name === "trot");
      else await play(name);
    }
  }
  idleLater();
}
// A stretch the first time it is about in the morning, and yawns late at night.
let lastIdle = "";
let stretchedOn = "";
function idlePick() {
  const now = new Date();
  const hour = now.getHours();
  if (rig.kind === "mibo" && hour >= 6 && hour < 11 && stretchedOn !== now.toDateString()) {
    stretchedOn = now.toDateString();
    return (lastIdle = "stretch");
  }
  const weights = { ...IDLE[rig.kind] };
  if (rig.kind !== "whole" && (hour >= 23 || hour < 5)) Object.assign(weights, { yawn: 16, hop: 1, trot: 1, wave: 1 });
  return (lastIdle = fresh(weights, lastIdle));
}
function sleepLater() {
  clearTimeout(sleepTimer);
  if (!lively() || !asleep()) {
    pet.classList.remove("breath");
    delete pet.dataset.z;
    return;
  }
  sleepTimer = setTimeout(() => {
    pet.classList.toggle("breath");
    pet.dataset.z = String(((Number(pet.dataset.z) || 0) + 1) % 4);
    sleepLater();
  }, SLEEP_STEP_MS);
}
function liveOn() {
  blinkLater();
  idleLater();
  sleepLater();
}
function liveOff() {
  [blinkTimer, idleTimer, sleepTimer].forEach(clearTimeout);
  still();
}

// ---- where it is, as window.py says: it ducks out of sight below its
// window's bottom, which is the taskbar's edge on the ground and the app
// window's top edge while it peeks, and comes back up. Called by window.py,
// which waits for nothing here.
async function rise() {
  pet.classList.remove("rise");
  void pet.offsetWidth;
  pet.classList.add("rise");
  await wait(RISE_MS);
  pet.classList.remove("rise");
}
function petPose(name) {
  const was = pose;
  pose = name;
  if (name !== "standing") card.close("seen");
  if (name !== "standing" && name !== "peek") still();
  pet.classList.toggle("away", hushed || name === "leaving" || name === "returning");
  pet.classList.toggle("peek", name === "peek" || name === "returning");
  // A painted figure has a pose of its own over the window's edge.
  if (rig?.kind === "painted" && !scene && !carry) rested();
  liveOn();
  if (!hushed && (name === "peek" || (name === "standing" && was !== "standing")))
    rise().then(() => pose === name && play(name === "peek" ? "peekArrive" : "lookAround"));
}

// ---- out of sight while a game or something full screen is in front:
// window.py ducks it and hides its window (petQuiet), and brings it back up
// after. While hushed, or while its page is hidden, nothing runs: no timers,
// nothing asked of the service, nothing moving.
let hushed = false;
let started = false;
let timers = null;
function settle() {
  const off = hushed || document.hidden;
  if (!started || off === !timers) return;
  if (off) {
    timers.forEach(clearInterval);
    timers = null;
    liveOff();
    return;
  }
  timers = [setInterval(() => (showFigure(), loadHome().then(lookOut)), LOOK_MS)];
  loadHome();
  showFigure();
  liveOn();
}
function petQuiet(on) {
  if (on === hushed) return;
  hushed = on;
  if (on) {
    card.close("seen");
    still();
  }
  pet.classList.toggle("away", on || pose === "leaving" || pose === "returning");
  if (!pet.classList.contains("away")) rise();
  settle();
}
document.addEventListener("visibilitychange", settle);

// ---- what the character is doing, as the service tells it: falling asleep
// and waking are acted out.
async function loadHome() {
  let state = "home";
  try {
    const response = await api("/api/home");
    if (response.ok) state = (await response.json())?.now?.state || "home";
  } catch {
    // The service is not answering: it stays as it is at home.
  }
  const was = pet.dataset.state;
  if (state === was) return;
  const here = pose === "standing" && !hushed && !carry;
  if (state === "out" && here) await play("leave");
  const back = was === "out" && here;
  // Back from a walk, it comes in from outside its window; back while it was not to be seen, it is just there.
  if (back) actor.style.opacity = "0";
  else if (was === "out") actor.style.transform = actor.style.opacity = "";
  pet.dataset.state = state;
  if (back) play("back");
  else if (state === "asleep") {
    if (pose === "standing" && !hushed) await play("dozeOff");
  } else if (was === "asleep" && pose === "standing" && !hushed) {
    play("wake");
  }
  if (!scene) rested(400);
  liveOn();
}

// Which way it went out of its window, to come back from there.
let went = null;

// ---- which figure it is: a painted one, else a drawing
let figure = "";

async function drawing(key) {
  const response = await fetch(`/assets/figures/${encodeURIComponent(key)}.svg`);
  if (!response.ok) throw new Error(String(response.status));
  const drawn = new DOMParser().parseFromString(await response.text(), "image/svg+xml");
  const node = document.importNode(drawn.documentElement, true);
  node.setAttribute("aria-hidden", "true");
  // Measured in place, in the box's px, with its eyes open: the figure, its
  // shadow under it, and the bottom of its eyes.
  const shape = () => {
    const scale = BOX[0] / node.viewBox.baseVal.width;
    const body = node.querySelector(".figure").getBBox();
    const eyes = (node.querySelector(".eyes") || node.querySelector(".figure")).getBBox();
    const ground = node.querySelector(".shadow")?.getBBox() || body;
    return {
      top: body.y * scale,
      eyes: (eyes.y + eyes.height) * scale,
      bottom: Math.max(body.y + body.height, ground.y + ground.height) * scale,
      left: body.x * scale,
      right: (body.x + body.width) * scale,
    };
  };
  return { node, shape };
}

// Called by window.py when the figure or its colours may have changed, and when it wakes.
function petFigure() {
  figure = "";
  return showFigure();
}
async function showFigure() {
  const key = await window.pywebview.api.figure();
  if (!key || key === figure) return;
  figure = key;
  try {
    // Mibo is only ever a drawing, painted in its colours.
    const drawn = (key !== "mibo" && (await paintedFigure(key))) || (await drawing(key));
    still();
    const was = rig;
    figureBox.replaceChildren(drawn.node);
    figureBox.dataset.figure = key;
    figureBox.classList.toggle("painted", Boolean(drawn.rig));
    rig = drawn.rig || rigOf(drawn.node);
    was?.atlas?.close();
    rested();
    // The strip that peeks over the app window: from just above the head to
    // under the eyes, or for a painted figure's peek, to the arms on the edge.
    const shape = drawn.shape();
    const peek = rig.layout?.peek;
    rig.room = Math.max(0, shape.top - 1) + PAD[1];
    const top = Math.max(0, Math.floor(peek ? peek.top : shape.top) - PEEK_ROOM);
    const line = Math.min(BOX[1], Math.ceil(peek ? peek.line : shape.eyes + UNDER_EYES));
    pet.style.setProperty("--peek-top", `${-top - PAD[1]}px`);
    // Its window shows anything, and takes the pointer, only round the figure:
    // the same on both sides, as facing left mirrors it, and from the box's
    // top, where the dots and the z's are and where it hops to.
    const side = Math.max(0, Math.floor(Math.min(shape.left, BOX[0] - shape.right)) - ROOM_SIDE);
    window.pywebview.api.measured(line - top, [
      Math.min(side, OVERLAY[0]) + PAD[0],
      PAD[1],
      Math.max(BOX[0] - side, OVERLAY[1]) + PAD[0],
      Math.min(BOX[1], Math.ceil(shape.bottom) + ROOM_BOTTOM) + PAD[1],
    ]);
    liveOn();
  } catch {
    // Asked again on the next look.
    figure = "";
  }
}

// ---- walking (travel): Mibo moves its window as it steps; a drawing with no
// joints is walked by the window (window.py). A press or a card stops it; at
// the screen's edge Mibo stops, and a drawing turns round (petTurn).
// Pleased (a find liked), Mibo hops a short way.
async function walk(fast = false, pleased = false) {
  // Toward the side with room, and no further than the screen goes.
  const room = [screenX - screen.availLeft, screen.availLeft + screen.availWidth - screenX - outerWidth];
  const left = room[0] > room[1] ? Math.random() < 0.7 : Math.random() < 0.3;
  const speed = rig?.kind === "painted" && rig.walks ? rig.speed / (fast ? HURRY : 1) : (fast ? TROT_PX : STEP_PX) / 30;
  const ms = Math.min(fast || pleased ? between(1200, 2600) : between(1800, 4200), room[left ? 0 : 1] / speed - 600);
  if (ms < 700) return;
  if (rig?.kind === "whole") await flip(left);
  else pet.classList.toggle("left", left);
  await play(fast ? "trot" : "walk", ms, rig?.kind === "mibo" && (pleased || (fast && hopping())));
}
// At the screen's edge: it stops there.
function petTurn(left) {
  if (going) going.end();
  else flip(left);
}

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
const spring = (x = 0) => ({ x, v: 0 });
// Pulled toward `to`: `w` how quick (rad/s), `z` how damped (1: no overshoot).
function pull(s, to, w, z, dt) {
  s.v += (w * w * (to - s.x) - 2 * z * w * s.v) * dt;
  s.x += s.v * dt;
}
const clamp = (v, low, high) => Math.max(low, Math.min(high, v));
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
quick.addEventListener("click", async (event) => {
  const button = event.target.closest("button");
  if (!button) return;
  event.stopPropagation();
  if (button.classList.contains("quick-quiet")) {
    petSnooze(!petSnoozed());
    return showQuick();
  }
  hideQuick();
  if (button.classList.contains("quick-find")) return petBring();
  if (opening) return;
  opening = true;
  await play("give");
  await window.pywebview.api.open();
  opening = false;
});
function labelQuick() {
  window.pywebview.api
    .words()
    .then((words) => {
      said = words || {};
      quick.querySelector(".quick-chat").title = quick.querySelector(".quick-chat").ariaLabel = said.open || "";
      quick.querySelector(".quick-find").title = quick.querySelector(".quick-find").ariaLabel = said.bring || "";
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
pet.addEventListener("dblclick", async () => {
  if (opening || dragging) return;
  if (pose === "peek") return window.pywebview.api.open();
  if (pose !== "standing") return;
  hideQuick();
  // On the ground it hands over the whole window; the compact chat a first click began goes (petclick.js).
  petDoubleClick();
  opening = true;
  await play("give");
  await window.pywebview.api.open();
  opening = false;
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
