// A painted figure (pet.js): its poses drawn from a packed picture, and its own ways of some actions.

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
