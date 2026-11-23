// The pet's actions (pet.js): short clips played by `play`, and what it does on its own.

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

// Which way it went out of its window, to come back from there.
let went = null;

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
