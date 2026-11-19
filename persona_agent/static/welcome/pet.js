// The pet: the character alone on the desktop. It walks about, is dragged by
// its figure, hops when patted, and now and then brings a card with something
// it found, or says a line of its own in a bubble. Double-clicked, it hands
// over the app window and peeks over that window's top edge until the window
// goes; window.py says when, through petPose.
const pet = document.getElementById("pet");
const figureBox = document.getElementById("figure");
const token = new URLSearchParams(location.hash.slice(1)).get("token") || "";
// How often it asks what the character is doing, which figure it is, and
// whether there is something to bring: window.py tells it at once of a line to
// say or a find, and of a new figure (petLook, petFigure). And how long it talks when it says something.
const LOOK_MS = 60000;
const SAY_MS = 1800;
// Past this many pixels a press is a drag, not a pat.
const DRAG_PX = 4;
// How far a walking step goes (CSS px).
const STEP_PX = 2;
// Its "here you go", and coming back into sight (pet.css).
const GIVE_MS = 600;
const RISE_MS = 520;
// While it peeks: the room left above its head for the overshoot, and how far
// under its eyes the window's edge cuts it off (CSS px).
const PEEK_ROOM = 10;
const UNDER_EYES = 6;
// The figure's box, and a sheet's frames side by side: rest, blink, talk, look.
const BOX = [160, 190];
const FRAMES = 4;
// Only the top of a sheet's figure is looked at for its eyes: a blink changes nothing lower.
const EYES_WITHIN = 0.6;
// Room beside the figure at rest for a wave and a sway, and below it for a
// squash; and from where to where across the dots and the z's go.
const ROOM_SIDE = 20;
const ROOM_BOTTOM = 4;
const OVERLAY = [100, 146];

const between = (low, high) => low + Math.random() * (high - low);
const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

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
let busy = false;
let opening = false;
// The things it has brought a card for since it started.
const told = new Set();
const resting = () =>
  hushed || pose !== "standing" || dragging || ["asleep", "out"].includes(pet.dataset.state) || card.open;

pet.style.setProperty("--blink", `${between(4.2, 5.4).toFixed(2)}s`);

async function act(name, ms) {
  pet.classList.add(name);
  await wait(ms);
  pet.classList.remove(name);
}

// ---- where it is, as window.py says: it ducks out of sight below its
// window's bottom, which is the taskbar's edge on the ground and the app
// window's top edge while it peeks, and comes back up. Called by window.py.
function petPose(name) {
  const was = pose;
  pose = name;
  if (name !== "standing") card.close("seen");
  pet.classList.remove("walk", "left", "wave", "look", "hop", "glad", "give", "sink", "pat", "rise");
  pet.classList.toggle("away", hushed || name === "leaving" || name === "returning");
  pet.classList.toggle("peek", name === "peek" || name === "returning");
  if (!hushed && (name === "peek" || (name === "standing" && was !== "standing"))) act("rise", RISE_MS);
}

// ---- out of sight while a game or something full screen is in front:
// window.py ducks it and hides its window (petQuiet), and brings it back up
// after. While hushed, or while its page is hidden, nothing runs: no timers,
// nothing asked of the service.
let hushed = false;
let started = false;
let timers = null;
let woken = null;
function settle() {
  const still = hushed || document.hidden;
  if (!started || still === !timers) return;
  if (still) {
    timers.forEach(clearInterval);
    timers = null;
    return;
  }
  timers = [setInterval(() => (showFigure(), loadHome().then(lookOut)), LOOK_MS)];
  loadHome();
  showFigure();
  if (woken) woken();
  woken = null;
}
// Once it may move again.
const awake = () => (timers ? Promise.resolve() : new Promise((resolve) => (woken = resolve)));
function petQuiet(on) {
  if (on === hushed) return;
  hushed = on;
  if (on) {
    card.close("seen");
    pet.classList.remove("walk", "left", "wave", "look", "hop", "glad", "give", "sink", "pat", "rise");
  }
  pet.classList.toggle("away", on || pose === "leaving" || pose === "returning");
  if (!pet.classList.contains("away")) act("rise", RISE_MS);
  settle();
}
document.addEventListener("visibilitychange", settle);

// ---- what the character is doing, as the service tells it
async function loadHome() {
  let state = "home";
  try {
    const response = await api("/api/home");
    if (response.ok) state = (await response.json())?.now?.state || "home";
  } catch {
    // The service is not answering: it stays as it is at home.
  }
  pet.dataset.state = state;
}

// ---- which figure it is: a sheet cut from a painting, else a drawing
let figure = "";
let sheetUrl = "";

// Where a sheet's figure is, and where its eyes end, in the box's px: the
// rows and columns with anything in them, and the last row that changes when
// it blinks.
function sheetShape(img) {
  const wide = img.naturalWidth / FRAMES;
  const high = img.naturalHeight;
  const canvas = document.createElement("canvas");
  canvas.width = wide * 2;
  canvas.height = high;
  const pen = canvas.getContext("2d", { willReadFrequently: true });
  pen.drawImage(img, 0, 0);
  const rest = pen.getImageData(0, 0, wide, high).data;
  const shut = pen.getImageData(wide, 0, wide, high).data;
  let [top, bottom, left, right] = [-1, 0, wide, 0];
  let eyes = -1;
  for (let y = 0; y < high; y++) {
    for (let x = 0; x < wide; x++) {
      const i = (y * wide + x) * 4;
      if (rest[i + 3]) {
        if (top < 0) top = y;
        bottom = y + 1;
        left = Math.min(left, x);
        right = Math.max(right, x + 1);
      }
      if (y >= high * EYES_WITHIN) continue;
      const change =
        Math.abs(rest[i] - shut[i]) + Math.abs(rest[i + 1] - shut[i + 1]) +
        Math.abs(rest[i + 2] - shut[i + 2]) + Math.abs(rest[i + 3] - shut[i + 3]);
      if (change > 60) eyes = y;
    }
  }
  top = Math.max(top, 0);
  // A sheet whose blink changes nothing: its eyes taken two fifths of the way down.
  if (eyes < 0) eyes = top + (high - top) * 0.4;
  const across = BOX[0] / wide;
  const down = BOX[1] / high;
  return { top: top * down, eyes: eyes * down, bottom: bottom * down, left: left * across, right: right * across };
}

async function sheet(key) {
  const response = await fetch(`/assets/figures/${encodeURIComponent(key)}.webp`);
  if (!response.ok) return null;
  const url = URL.createObjectURL(await response.blob());
  const img = new Image();
  img.src = url;
  img.alt = "";
  img.draggable = false;
  await img.decode();
  if (sheetUrl) URL.revokeObjectURL(sheetUrl);
  sheetUrl = url;
  const node = document.createElement("div");
  node.className = "sheet";
  node.append(img);
  return { node, shape: () => sheetShape(img) };
}

async function drawing(key) {
  const response = await fetch(`/assets/figures/${encodeURIComponent(key)}.svg`);
  if (!response.ok) throw new Error(String(response.status));
  const drawn = new DOMParser().parseFromString(await response.text(), "image/svg+xml");
  const node = document.importNode(drawn.documentElement, true);
  node.setAttribute("aria-hidden", "true");
  // Measured in place: the open eyes are shown for it whatever it is doing (pet.css).
  const shape = () => {
    pet.classList.add("measure");
    const eyes = node.querySelector(".eyes.open").getBBox();
    const body = node.querySelector(".figure").getBBox();
    pet.classList.remove("measure");
    return {
      top: body.y, eyes: eyes.y + eyes.height, bottom: body.y + body.height,
      left: body.x, right: body.x + body.width,
    };
  };
  return { node, shape };
}

// Called by window.py when the figure may have changed, and when it wakes.
function petFigure() {
  return showFigure();
}
async function showFigure() {
  const key = await window.pywebview.api.figure();
  if (!key || key === figure) return;
  figure = key;
  try {
    const drawn = (await sheet(key)) || (await drawing(key));
    figureBox.replaceChildren(drawn.node);
    figureBox.dataset.figure = key;
    pet.classList.toggle("painted", drawn.node.classList.contains("sheet"));
    // The strip that peeks over the app window: from just above the head to under the eyes.
    const shape = drawn.shape();
    const top = Math.max(0, Math.floor(shape.top) - PEEK_ROOM);
    const line = Math.min(BOX[1], Math.ceil(shape.eyes) + UNDER_EYES);
    pet.style.setProperty("--peek-top", `${-top}px`);
    // Its window shows anything, and takes the pointer, only round the figure:
    // the same on both sides, as walking left mirrors it, and from the box's
    // top, where the dots and the z's are.
    const side = Math.max(0, Math.floor(Math.min(shape.left, BOX[0] - shape.right)) - ROOM_SIDE);
    window.pywebview.api.measured(line - top, [
      Math.min(side, OVERLAY[0]),
      0,
      Math.max(BOX[0] - side, OVERLAY[1]),
      Math.min(BOX[1], Math.ceil(shape.bottom) + ROOM_BOTTOM),
    ]);
  } catch {
    // Asked again on the next look.
    figure = "";
  }
}

// ---- what it does on its own
// The window walks it, one step every 30 ms, until the time is up or a press or
// a card stops it (window.py); it faces the way it goes, and is turned at the
// screen's edge (petTurn).
let walking = false;
async function walk() {
  const left = Math.random() < 0.5;
  pet.classList.add("walk");
  pet.classList.toggle("left", left);
  walking = true;
  await window.pywebview.api.walk(left ? -STEP_PX : STEP_PX, between(1400, 3800));
  walking = false;
  pet.classList.remove("walk", "left");
}
function petTurn(left) {
  pet.classList.toggle("left", left);
}
async function live() {
  for (;;) {
    await awake();
    await wait(between(3500, 9000));
    if (press || busy || hushed) continue;
    busy = true;
    const roll = Math.random();
    if (pose === "peek") {
      // Over the window's edge: a blink of its own, and now and then it sinks a little.
      if (roll < 0.5) await act("sink", 1600);
    } else if (!resting()) {
      if (roll < 0.45) await walk();
      else if (roll < 0.65) await act("wave", 1600);
      else if (roll < 0.85) await act("look", 1800);
      else await act("hop", 600);
    }
    busy = false;
  }
}

// ---- something it found: it hops, and a card opens beside it
async function bringNews() {
  if (resting() || press || opening) return;
  let item = null;
  try {
    const response = await api(`/api/feed/next?lang=${encodeURIComponent(card.lang)}`);
    if (response.ok) item = (await response.json()).item;
  } catch {
    // The service is not answering: nothing to bring this time.
  }
  if (!item || told.has(item.id) || resting() || press || opening) return;
  told.add(item.id);
  if (await card.show(item)) cheer();
}

// ---- a line of its own about what the person is doing: a bubble beside it,
// and the line is in the main chat too (the service puts it there). True when
// it is out, or when a video plays in a window in front: then it brings
// nothing at all. A find waits until the bubble has gone, as for a card.
async function bringRemark() {
  // Over the app window the line is to be read in the chat: taken, and not shown.
  const peeking = pose === "peek";
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
  // It speaks with glad eyes, a sheet with its talking frame (pet.css).
  act("glad", SAY_MS);
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

// ---- what a person does to it. Only round the figure: elsewhere the
// pointer goes through its window (window.py).
async function cheer() {
  pet.classList.remove("hop");
  void pet.offsetWidth;
  pet.classList.add("hop", "glad");
  await wait(900);
  pet.classList.remove("hop", "glad");
}
function pat() {
  if (pose === "standing") return cheer();
  // Peeking: a quick duck behind the edge and up again.
  if (pose === "peek") return act("pat", 480);
}
async function drag() {
  dragging = true;
  pet.classList.add("held");
  // The window follows the cursor until the button is let go (window.py),
  // holding the figure where it was pressed.
  await window.pywebview.api.drag(press.at[0], press.at[1]);
  dragging = false;
  pet.classList.remove("held");
}
pet.addEventListener("pointerdown", (event) => {
  if (event.button !== 0) return;
  // A press stops a walk at once, or the window would move between the two
  // clicks of a double-click and the page would see two single ones.
  if (walking) window.pywebview.api.rest();
  press = { x: event.screenX, y: event.screenY, at: [event.clientX, event.clientY], moved: false };
  pet.setPointerCapture(event.pointerId);
});
pet.addEventListener("pointermove", (event) => {
  if (!press || press.moved) return;
  if (Math.hypot(event.screenX - press.x, event.screenY - press.y) <= DRAG_PX) return;
  press.moved = true;
  // Peeking, it stays on the window's edge.
  if (pose === "standing" && !opening) drag();
});
pet.addEventListener("pointerup", (event) => {
  if (!press || event.button !== 0) return;
  const moved = press.moved;
  press = null;
  if (dragging) window.pywebview.api.drop();
  else if (!moved) pat();
});
pet.addEventListener("pointercancel", () => {
  press = null;
  if (dragging) window.pywebview.api.drop();
});
// On the ground it hands the window over; peeking, it brings the window to the front.
pet.addEventListener("dblclick", async () => {
  if (opening || dragging) return;
  if (pose === "peek") return window.pywebview.api.open();
  if (pose !== "standing") return;
  opening = true;
  pet.classList.remove("hop", "glad");
  await act("give", GIVE_MS);
  await window.pywebview.api.open();
  opening = false;
});
window.addEventListener("contextmenu", (event) => {
  event.preventDefault();
  window.pywebview.api.menu();
});

window.addEventListener("pywebviewready", () => {
  started = true;
  settle();
  live();
});
