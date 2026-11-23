// The pet's life at rest, where it is, whether it is hushed, what the character is doing, and which
// figure it is (pet.js).

// How often it asks what the character is doing, which figure it is, and
// whether there is something to bring: window.py tells it at once of a line to
// say or a find, and of a new figure (petLook, petFigure).
const LOOK_MS = 60000;
// Coming back into sight (pet.css).
const RISE_MS = 520;
// While it peeks: the room left above its head for the overshoot, and how far
// under its eyes the window's edge cuts it off (CSS px).
const PEEK_ROOM = 10;
const UNDER_EYES = 6;
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
