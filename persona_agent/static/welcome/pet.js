// The pet: the character alone on the desktop. It moves on its own, is
// dragged by the window around it, hops when patted, and opens personagent
// when double-clicked.
const pet = document.getElementById("pet");
const token = new URLSearchParams(location.hash.slice(1)).get("token") || "";
const HOME_MS = 8000;
// Past this many pixels a press is a drag, not a pat.
const DRAG_PX = 4;
const STEP_PX = 2;
const STEP_MS = 30;

const POSE_MS = 150;
const PULL_MS = 550;

const between = (low, high) => low + Math.random() * (high - low);
const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
// standing on the ground, jumping, or lying on the window's edge: the window says which.
let pose = "standing";
const resting = () => pose !== "standing" || ["asleep", "out"].includes(pet.dataset.state);
// The press in progress, or null.
let press = null;
let busy = false;
let opening = false;

pet.style.setProperty("--blink", `${between(4.2, 5.4).toFixed(2)}s`);

// ---- what the character is doing, as the service tells it
async function loadHome() {
  let state = "home";
  try {
    const response = await fetch("/api/home", {
      headers: { "X-Personagent-Setup-Token": token },
    });
    if (response.ok) state = (await response.json())?.now?.state || "home";
  } catch {
    // The service is not answering: it stays as it is at home.
  }
  pet.dataset.state = state;
}

// ---- what it does on its own
async function act(name, ms) {
  pet.classList.add(name);
  await wait(ms);
  pet.classList.remove(name);
}
async function walk() {
  let direction = Math.random() < 0.5 ? -1 : 1;
  const until = performance.now() + between(1400, 3800);
  pet.classList.add("walk");
  while (performance.now() < until && !press && !resting()) {
    pet.classList.toggle("left", direction < 0);
    // False at the edge of the screen: it turns round.
    if (!(await window.pywebview.api.walk(direction * STEP_PX))) direction = -direction;
    await wait(STEP_MS);
  }
  pet.classList.remove("walk", "left");
}
async function live() {
  for (;;) {
    await wait(between(3500, 9000));
    if (press || busy || resting()) continue;
    busy = true;
    const roll = Math.random();
    if (roll < 0.45) await walk();
    else if (roll < 0.65) await act("wave", 1600);
    else if (roll < 0.85) await act("look", 1800);
    else await act("hop", 600);
    busy = false;
  }
}

async function watchPose() {
  for (;;) {
    pose = await window.pywebview.api.pose();
    pet.classList.toggle("lying", pose === "lying");
    pet.classList.toggle("jump", pose === "jumping");
    await wait(POSE_MS);
  }
}

// ---- what a person does to it
async function pat() {
  if (pose !== "standing") return act("glad", 900);
  pet.classList.remove("hop");
  void pet.offsetWidth;
  pet.classList.add("hop", "glad");
  await wait(900);
  pet.classList.remove("hop", "glad");
}
window.addEventListener("mousedown", (event) => {
  if (event.button === 0) press = { x: event.screenX, y: event.screenY, moved: false };
});
window.addEventListener("mousemove", (event) => {
  if (!press || press.moved) return;
  if (Math.hypot(event.screenX - press.x, event.screenY - press.y) > DRAG_PX) {
    press.moved = true;
    pet.classList.add("held");
  }
});
window.addEventListener("mouseup", (event) => {
  if (!press || event.button !== 0) return;
  const moved = press.moved;
  press = null;
  pet.classList.remove("held");
  if (!moved) pat();
});
// It takes the window out, and the window says when the pet goes to lie on it.
window.addEventListener("dblclick", async () => {
  if (opening) return;
  opening = true;
  pet.classList.remove("hop", "glad");
  if (pose === "standing") await act("pull", PULL_MS);
  await window.pywebview.api.open();
  opening = false;
});
window.addEventListener("contextmenu", (event) => {
  event.preventDefault();
  window.pywebview.api.menu();
});

loadHome();
setInterval(loadHome, HOME_MS);
window.addEventListener("pywebviewready", () => {
  watchPose();
  live();
});
