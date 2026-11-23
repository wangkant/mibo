"use strict";
// Settings › Character: the picker characters.js draws (window.paCharacters), and
// under it, while Mibo is the one chosen, its two colours (GET/POST /api/look/colors {accent, shell}): cool
// colours only, a few ready ones and a free pick inside the hues the server allows
// (panels/colors.py: 165-265 degrees).
(() => {
  // Ready colours for each part, each inside what the server takes: a strong one for the accent, a pale one for the shell.
  const PRESETS = {
    accent: { sky: "#3e9ce0", cyan: "#23b2c7", mint: "#39c6ae", indigo: "#5e6ed4", grey: "#6689b7" },
    shell: { sky: "#dbecfa", cyan: "#d7f0f4", mint: "#def2ee", indigo: "#e3e6f7", grey: "#e4e7ec" },
  };
  // The hues the server takes (panels/colors.py COOL), a degree in from each end so rounding stays inside.
  const HUES = [166, 264];

  // "#rrggbb" to [hue 0-360, saturation 0-1, lightness 0-1], and back.
  function hsl(hex) {
    const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);
    const high = Math.max(r, g, b);
    const low = Math.min(r, g, b);
    const l = (high + low) / 2;
    const d = high - low;
    if (!d) return [0, 0, l];
    const s = d / (1 - Math.abs(2 * l - 1));
    const h = high === r ? ((g - b) / d) % 6 : high === g ? (b - r) / d + 2 : (r - g) / d + 4;
    return [(h * 60 + 360) % 360, s, l];
  }
  function hex(h, s, l) {
    const a = s * Math.min(l, 1 - l);
    const part = (n) => {
      const k = (n + h / 30) % 12;
      const v = l - a * Math.max(-1, Math.min(k - 3, 9 - k, 1));
      return Math.round(v * 255).toString(16).padStart(2, "0");
    };
    return `#${part(0)}${part(8)}${part(4)}`;
  }

  window.paSetup.part("character", (kit) => {
    const { el } = kit;
    const t = kit.words("setup_character");
    const ctx = kit.ctx;
    const node = kit.section("character");

    const colors = { value: null, saving: "", mibo: false };
    // The picker is the characters part's own; Settings only gives it room.
    const room = kit.item("characters", el("div", "setup-characters"));
    const follow = (value) => {
      colors.mibo = value.figure === "mibo";
      box.hidden = !(colors.mibo && colors.value);
    };
    const picker = window.paCharacters ? window.paCharacters.mount(room, ctx, { onLoad: follow, onChange: follow }) : null;
    node.append(room);

    const box = kit.card(t.colors);
    box.hidden = true;
    const rows = {};
    for (const part of ["accent", "shell"]) rows[part] = colorRow(part);
    const error = kit.errorLine();
    box.append(rows.accent.row, rows.shell.row, error);
    node.append(box);

    function colorRow(part) {
      const swatches = el("div", "setup-swatches");
      swatches.setAttribute("role", "radiogroup");
      swatches.setAttribute("aria-label", t[part]);
      const ready = {};
      for (const [name, value] of Object.entries(PRESETS[part])) {
        const swatch = el("button", "setup-swatch");
        swatch.type = "button";
        swatch.setAttribute("role", "radio");
        swatch.title = t.presets[name];
        swatch.setAttribute("aria-label", t.presets[name]);
        swatch.style.setProperty("--swatch", value);
        swatch.dataset.value = value;
        swatch.addEventListener("click", () => save(part, value));
        ready[name] = swatch;
        swatches.append(swatch);
      }
      const own = el("button", "setup-swatch setup-swatch-own");
      own.type = "button";
      own.setAttribute("role", "radio");
      own.title = t.own;
      own.setAttribute("aria-label", t.own);
      swatches.append(own);
      // The free pick moves the hue only; saturation and lightness stay as the colour has them.
      const slider = el("input", "setup-hue");
      slider.type = "range";
      slider.step = "1";
      slider.setAttribute("aria-label", t.ownHue[part]);
      slider.hidden = true;
      own.addEventListener("click", () => {
        slider.hidden = !slider.hidden;
        if (!slider.hidden) slider.focus();
      });
      slider.addEventListener("input", () => {
        const [, s, l] = hsl(colors.value[part]);
        own.style.setProperty("--swatch", hex(Number(slider.value), s, l));
      });
      slider.addEventListener("change", () => {
        const [, s, l] = hsl(colors.value[part]);
        save(part, hex(Number(slider.value), s, l));
      });
      const row = kit.item(part, kit.optionRow(t[part], "", swatches).row);
      row.classList.add("setup-color-row");
      row.append(slider);
      return { row, swatches, ready, own, slider };
    }

    function render() {
      for (const [part, row] of Object.entries(rows)) {
        const now = colors.value[part].toLowerCase();
        let matched = false;
        for (const swatch of Object.values(row.ready)) {
          const on = swatch.dataset.value === now;
          matched ||= on;
          swatch.setAttribute("aria-checked", String(on));
          swatch.disabled = Boolean(colors.saving);
          swatch.classList.toggle("setup-busy", colors.saving === `${part}:${swatch.dataset.value}`);
        }
        row.own.setAttribute("aria-checked", String(!matched));
        row.own.disabled = Boolean(colors.saving);
        row.own.style.setProperty("--swatch", matched ? "" : now);
        row.slider.min = String(HUES[0]);
        row.slider.max = String(HUES[1]);
        row.slider.value = String(Math.round(hsl(now)[0]));
        row.slider.disabled = Boolean(colors.saving);
      }
    }

    async function load() {
      try {
        const value = await ctx.api("look/colors");
        colors.value = { accent: value.accent, shell: value.shell };
        error.hidden = true;
      } catch (failure) {
        // Never read: the card stays hidden; read before, what was read stays, with what went wrong.
        if (colors.value) kit.failed(error, failure, t);
        return;
      }
      box.hidden = !colors.mibo;
      render();
    }

    async function save(part, value) {
      if (colors.saving || value.toLowerCase() === colors.value[part].toLowerCase()) return;
      colors.saving = `${part}:${value}`;
      error.hidden = true;
      render();
      try {
        // The server takes both at once; the other stays as it is.
        const answer = await ctx.api("look/colors", { ...colors.value, [part]: value });
        colors.value = { accent: answer.accent, shell: answer.shell };
      } catch (failure) {
        kit.failed(error, failure, t);
      } finally {
        colors.saving = "";
        render();
      }
    }

    // The picker reads its list as it mounts; opened again, it reads it afresh.
    let opened = false;
    function show() {
      if (opened) picker?.reload();
      opened = true;
      load();
    }

    return { node, show };
  });
})();
