// The pet getting about (pet.js): walking, trotting and hopping, with its window or within it.

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
