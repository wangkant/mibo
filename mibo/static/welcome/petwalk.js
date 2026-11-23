// The pet getting about (pet.js): walking, trotting and hopping, with its window or within it.

// ---- getting about. Mibo turns three-quarters toward where it goes, its eyes
// first and its body after, sinking a little and leaning back as it gathers
// itself: the visor and eyes over to that side, the far ear round behind its
// head, the near arm in front of the body and the far one behind, the far foot
// a little higher and smaller. Then it walks on its two stub feet: each step
// rolls a foot up onto its toe and lifts it in an arc, quick up and slower
// down, to a place on the ground ahead of the body, where it comes down heel
// first and flattens, squashing a little; the other stands still on the ground
// as the figure moves (read from where it is each frame, so it never slides).
// The body is lowest just after a foot comes down, squashed a little, and
// highest and a little stretched as it passes over it; it goes a little slower
// as the weight lands and quicker as it passes, rocks over the planted foot,
// and leans into the way it goes as it gathers speed. No two steps are quite
// the same in time, length or height. The visor and ears lag the body's rise
// and fall and settle after it, the arms swing against the feet a little late,
// the antenna trails. Its window moves in whole device pixels, and the figure
// within it by what is left, so it glides. Stopping, a last step, the back
// foot brought up beside it, the weight settling with one small give, and it
// turns back to face the person. Or it hops: a crouch, a push, a short low
// arc with its window moving only while it is in the air (`leap` moves
// something else instead), a landing. It hops when in a hurry or pleased,
// now and then, never twice running (hopping). With reduced motion it walks
// without the give, the lag, the roll, the surge and the differences.
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
// Slow at both ends with no jolt: how a foot flattens on the ground.
const smoother = (t) => (t <= 0 ? 0 : t >= 1 ? 1 : t * t * t * (t * (6 * t - 15) + 10));
const plus = ([x = 0, y = 0, t = 0, w = 1, h = w] = [], [x2 = 0, y2 = 0, t2 = 0, w2 = 1, h2 = w2] = []) => [x + x2, y + y2, t + t2, w * w2, h * h2];
// A number in -1..1, the same for the same walk, step and use.
const jitter = (seed, step, i) => {
  const v = Math.sin(seed + step * 12.9898 + i * 78.233) * 43758.5453;
  return (v - Math.floor(v)) * 2 - 1;
};
// The walk's feel. The body is lowest this share into a step, just after a foot is down.
const DIP = 0.12;
// Its rise and fall (CSS px), and how much it squashes at the bottom and stretches at the top.
const BOB = { walk: 1.6, trot: 2.2 };
const SQUASH = { walk: 0.014, trot: 0.02 };
// Its rock over the planted foot, and its lean into the way it goes at full speed (degrees).
const ROCK = 1.3;
const LEAN = { walk: 2, trot: 3 };
// Slower as the weight lands, quicker as it passes: this share of its speed either way.
const SURGE = 0.1;
// A lifting foot's heel up as it leaves, and its toe up as it comes down (degrees);
// the foot flattens over this share of the next step. A foot's pivot is under its
// middle (pet.css): its heel and toe are this far from it (CSS px).
const ROLL = [4, 6];
const FLATTEN = 0.35;
const REACH = { L: [12, 12], R: [4, 20] };
// How much one step may differ from the next in time, height and length.
const VARY = [0.04, 0.15, 0.06];
// Home: the weight settles over this long, and it is done once every part is still.
const SETTLE_MS = 460;
const HOME_MS = 640;
const plain = matchMedia("(prefers-reduced-motion: reduce)");
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
    const gait = fast ? "trot" : "walk";
    const drive = ms && !hop;
    // The give, the lag, the roll, the surge and the differences, unless motion is to be kept down.
    const soft = plain.matches ? 0 : 1;
    // Springs: the arms, the antenna and its dot; the body's rise, height and turn
    // (stiff, so it moves as drawn but never jumps); its lean, its speed and how
    // far into its stride it is; the visor and the ears, lighter, lagging the body.
    const g = {
      L: spring(), R: spring(), antenna: spring(), tip: spring(),
      bob: spring(), tall: spring(1), rock: spring(), lean: spring(), speed: spring(), stride: spring(),
      visor: spring(), ears: spring(),
    };
    const s = {
      t0: performance.now(),
      phase: "in",
      start: 0,
      step: -1,
      begin: 0,
      len: P,
      high: lift,
      swing: "R",
      liftX: 0,
      landX: 0,
      flat: 0,
      roll: 0,
      plant: { L: 0, R: 0 },
      rel: { L: 0, R: 0 },
      home: { L: 0, R: 0 },
      closing: 0,
      rested: false,
      last: 0,
      was: null,
      seed: Math.random() * 1000,
      // Its speed, CSS px a ms: as the window is set to go, then as measured.
      v: px / 30,
      top: px / 30,
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
    // How far a foot's heel or toe goes under the ground at `turn` degrees about its pivot: it is lifted that much.
    const under = (foot, turn) => Math.abs(Math.sin((turn * Math.PI) / 180)) * REACH[foot][turn > 0 ? 1 : 0];
    const frame = (now) => {
      if (!c.alive() || s.phase === "gone") return finish();
      const t = now - s.t0;
      const dt = s.last ? Math.min(0.034, (now - s.last) / 1000) : 1 / 60;
      s.last = now;
      // Where it is in a step: 0 as a foot lifts, 1 as it is down.
      const u = s.phase === "go" ? Math.min(1, (now - s.begin) / s.len) : 0;
      // 1 just after a foot is down (lowest, slowest), -1 as the body passes over it.
      const beat = Math.cos(2 * Math.PI * (u - DIP));
      // Walking, it moves its window itself, each frame as it draws the feet
      // for it, gathering speed over the first steps and losing it over the
      // last two, a little slower as each foot lands.
      if (drive && s.phase === "go") {
        pull(g.speed, s.closing >= 2 ? 0 : s.closing ? s.top * 0.6 : s.top, fast ? 10 : 8, 1, dt);
        const v = Math.max(0, g.speed.x) * (1 - soft * SURGE * g.stride.x * beat);
        placeWindow(s, s.x + dir * v * dt * 1000);
      }
      // The window is in whole device pixels; the figure is moved within it by the rest.
      const here = drive ? { x: s.x, s: 1 } : ground();
      const sub = drive ? (s.x - s.at) * dir * (s.phase === "home" ? 1 - smooth(t / SETTLE_MS) : 1) : 0;
      if (s.was && now > s.was.t) s.v += (Math.abs(here.x - s.was.x) / (now - s.was.t) - s.v) * Math.min(1, dt * 4);
      s.was = { x: here.x, t: now };
      const share = Math.min(1, (drive ? g.speed.x : s.v) / s.top);
      let k = 1;
      let kEyes = 1;
      let bob = 0;
      let air = 0;
      let rock = 0;
      let lean = 0;
      let tall = 1;
      let into = 0;
      // How much of the crouch it gathered itself in is still to come out of, over its first step.
      let crouch = 0;
      const pose = { armL: [], armR: [], footL: [], footR: [], shadow: [] };
      if (s.phase === "in") {
        // Its eyes go first, its body turns after them, it sinks a little and leans back onto the near foot.
        kEyes = smooth(t / 200);
        k = smooth((t - 90) / 290);
        lean = -1.2 * smooth((t - 240) / 180);
        crouch = smooth((t - 240) / 180);
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
        if (s.step < 0 || now - s.begin >= s.len) {
          // A step begins: the foot that swung is down where it is, and the other lifts.
          if (s.step >= 0) {
            s.plant[s.swing] = hop ? here.x + s.rel[s.swing] * dir * here.s : s.landX;
            s.flat = s.roll;
            s.begin += s.len;
          } else s.begin = now;
          if (ms && !s.closing && now - s.start > ms - P) s.end();
          if (s.closing === 3) {
            s.phase = "home";
            s.t0 = now;
            s.home = { ...s.rel };
          } else {
            if (s.closing) s.closing++;
            s.step++;
            s.swing = s.step % 2 ? "L" : "R";
            const vary = (i) => (hop ? 0 : soft * VARY[i] * jitter(s.seed, s.step, i));
            s.len = P * (1 + vary(0));
            s.high = lift * (1 + vary(1));
            // Lifted from where it is, put down where the body will be at the step's end and, but for the
            // last two, ahead of it by half what it goes in a step; the last two beside each other under it.
            const v = drive ? (g.speed.x + (s.closing >= 2 ? 0 : s.top)) / 2 : s.v;
            const ahead = s.closing ? 0 : (((drive ? s.top : s.v) * P) / 2) * (1 + vary(2));
            s.liftX = s.plant[s.swing];
            s.landX = here.x + dir * (v * s.len * (s.closing >= 2 ? 0.5 : 1) + ahead);
            // A hop moves the window, or what `leap` moves, only while it is off the ground.
            if (hop && !s.closing)
              setTimeout(
                () => c.alive() && !s.closing && (leap ? leap(P * 0.36) : window.pywebview.api.walk(dir * px * 2.4, P * 0.36)),
                P * 0.27,
              );
          }
        }
        if (s.phase === "go") {
          const u = Math.min(1, (now - s.begin) / s.len);
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
            // The planted foot holds still on the ground, flattening from its heel and squashing a little as
            // the weight comes onto it; the other rolls onto its toe and swings over to where it goes down.
            s.rel[planted] = ((s.plant[planted] - here.x) * dir) / here.s;
            s.rel[s.swing] = ((s.liftX + (s.landX - s.liftX) * smooth(u) - here.x) * dir) / here.s;
            const small = Math.min(1, Math.abs(s.landX - s.liftX) / here.s / 10 + 0.3);
            // Up quicker than down: the arc's top a little before the step's middle.
            const arc = Math.sin(Math.PI * (u + 0.07 * Math.sin(Math.PI * u))) ** 2;
            const roll = soft * small * (u < 0.5 ? ROLL[0] * Math.sin(2 * Math.PI * u) ** 2 : -ROLL[1] * Math.sin(Math.PI * (u - 0.5)) ** 2);
            s.roll = roll;
            pose["foot" + s.swing] = [0, -s.high * arc * small - under(s.swing, roll), roll];
            const flat = s.flat * (1 - smoother(u / FLATTEN));
            const press = soft * 0.05 * Math.sin(Math.PI * Math.min(1, u / 0.3));
            pose["foot" + planted] = [0, -under(planted, flat), flat, 1 + press * 0.8, 1 - press];
            // The body lowest and squashed just after the foot is down, highest and stretched as it passes
            // over it, rocking over the planted foot a little after the weight is on it.
            into = s.closing >= 2 ? 0.5 : 1;
            crouch = 1 - smooth((now - s.start) / (P * 0.8));
            bob = BOB[gait] * (0.75 * beat - 0.35);
            tall = 1 - soft * SQUASH[gait] * Math.cos(2 * Math.PI * (u - DIP - 0.05));
            rock = (planted === "L" ? -1 : 1) * ROCK * Math.sin(Math.PI * (u - 0.1));
            lean = (LEAN[gait] * share) / (s.closing ? 2 : 1);
          }
        }
      }
      if (s.phase === "home") {
        // Home: the back foot brought up beside the other, the weight settling with one small give, then it
        // turns back, eyes first.
        const t = now - s.t0;
        const x = t / SETTLE_MS;
        const give = x < 1 ? Math.sin(1.5 * Math.PI * x) * (1 - x) ** 2 : 0;
        bob = 0.9 * give;
        tall = 1 - soft * 0.03 * give;
        for (const foot of ["L", "R"]) {
          const back = Math.abs(s.home[foot]) >= Math.abs(s.home[foot === "L" ? "R" : "L"]);
          const f = smoother((t - (back ? 0 : 160)) / 280);
          const flat = foot === s.swing ? s.flat * (1 - smoother(t / (FLATTEN * P))) : 0;
          s.rel[foot] = s.home[foot] * (1 - f);
          pose["foot" + foot] = [0, -Math.min(2, Math.abs(s.home[foot]) * 0.8) * Math.sin(Math.PI * f) ** 2 - under(foot, flat), flat];
        }
        kEyes = 1 - smooth((t - 200) / 200);
        k = 1 - smooth((t - 280) / 300);
        const still =
          [g.L, g.R, g.antenna, g.tip].every((sp) => Math.abs(sp.x) < 0.1 && Math.abs(sp.v) < 2) &&
          [g.bob, g.rock, g.lean, g.visor, g.ears].every((sp) => Math.abs(sp.x) < 0.05) &&
          Math.abs(g.tall.x - 1) < 0.002;
        if ((t > HOME_MS && still) || t > HOME_MS * 2) return finish();
      }
      // Its shadow under its feet, a little smaller as it rises.
      if (!hop) pose.shadow = [(s.rel.L + s.rel.R) * 0.4, 0, 0, 1 - 0.02 * g.stride.x * (1 - beat), 1];
      // The oscillations come in and go out with the stride; the body follows them stiffly, never jumping.
      pull(g.stride, into, 7, 1, dt);
      const st = hop ? 1 : g.stride.x;
      const swayed = (v, rest) => rest + (v - rest) * (hop || s.phase !== "go" ? 1 : st);
      pull(g.bob, swayed(bob, 0) + 0.4 * crouch, 34, 1, dt);
      pull(g.tall, swayed(tall, 1) - 0.02 * crouch, 34, 1, dt);
      pull(g.rock, swayed(rock, 0), 34, 1, dt);
      pull(g.lean, lean, 9, 0.7, dt);
      // The visor and ears are carried by the body and lag its rise and fall, the ears more.
      pull(g.visor, g.bob.x, 26, 0.5, dt);
      pull(g.ears, g.bob.x, 22, 0.4, dt);
      // Arms against the feet, a little late, hanging back as it leans; the antenna and its dot trailing.
      // As far as the feet go at full speed, not as it slows: its arms swing less as its steps get shorter.
      const swing = hop ? 0 : 18 / Math.max(3, ((drive ? s.top : s.v) * P) / 2);
      const hang = -0.6 * g.lean.x;
      pull(g.L, -s.rel.R * swing + hang, 16, 0.55, dt);
      pull(g.R, -s.rel.L * swing + hang, 15, 0.55, dt);
      const trail = s.phase === "go" && !s.closing ? share : 0;
      pull(g.antenna, -5 * trail + (g.bob.x + air) * 1.4 * st - 0.5 * g.rock.x, 13, 0.32, dt);
      pull(g.tip, -trail - (g.bob.x + air) * 0.25 * st, 16, 0.4, dt);
      const q = quarter(k);
      const qe = quarter(kEyes);
      const lag = (sp, most) => (soft * most * (sp.x - g.bob.x)) / (1 + Math.abs(sp.x - g.bob.x));
      set(p.visor, plus(qe.visor, [0, lag(g.visor, 0.3)]));
      set(p.eyes, qe.eyes);
      set(p.chest, q.chest);
      set(p.earL, plus(q.earL, [0, lag(g.ears, 0.5)]));
      set(p.earR, plus(q.earR, [0, lag(g.ears, 0.5)]));
      set(p.root, [sub, air]);
      const high = g.tall.x;
      set(p.body, plus(q.body, [0, g.bob.x, g.rock.x + g.lean.x, 1 + (1 - high) * 0.7, high]));
      set(p.armL, plus(plus(q.armL, [0, 0, g.L.x]), pose.armL));
      set(p.armR, plus(plus(q.armR, [0, 0, g.R.x]), pose.armR));
      set(p.footL, plus(plus(q.footL, [s.rel.L, 0]), pose.footL));
      set(p.footR, plus(plus(q.footR, [s.rel.R, 0]), pose.footR));
      set(p.antenna, [0, 0, g.antenna.x]);
      set(p.tip, [g.tip.x, 0]);
      set(p.shadow, plus([sub, -air], pose.shadow));
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
