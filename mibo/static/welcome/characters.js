"use strict";
// The character picker, the same on the first run and in Settings: Mibo, GPT, DeepSeek and
// Claude, and a fifth of the person's own. A character is its name, its personality and its
// figure at once: choosing one sets all three (POST /api/character) and the sidebar follows.
// The fifth opens a small form: a name, the personality in the person's own words, and a
// picture that is its face in the chat; on the desktop it is Mibo, in Mibo's colours.
//
//   const picker = paCharacters.mount(node, ctx, { speaks, onLoad(value) {}, onChange(value) {} });
//   speaks: the character's language, for the names (the saved one by default); both callbacks get the
//   GET /api/characters answer ({ chosen, set, name, figure, characters, custom, ... }).
//   picker.value     that answer as last read
//   picker.choose(key)   choose one from code (the first run's skip goes back with it)
// It needs characters.css, and app.js's ctx (api, bodyOf, picture, setFigure, changed).
window.paCharacters = (() => {
  const CUSTOM = "custom";
  const SVG = "http://www.w3.org/2000/svg";
  const TICK = "M5 12.5l4.2 4.2L19 7";
  const PLUS = "M12 5v14M5 12h14";
  const PENCIL = "M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z";

  function el(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  }
  function icon(d, cls) {
    const svg = document.createElementNS(SVG, "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("class", cls);
    const path = document.createElementNS(SVG, "path");
    path.setAttribute("d", d);
    svg.append(path);
    return svg;
  }

  function mount(node, ctx, options = {}) {
    const t = paI18n.words("characters");
    const say = (error) => t.errors[error?.message] || t.errors.generic;
    const root = el("div", "pac");
    const grid = el("div", "pac-grid");
    const error = el("p", "pac-error");
    error.hidden = true;
    const formBox = el("div", "pac-form-box");
    root.append(grid, formBox, error);
    node.replaceChildren(root);

    let value = null;
    let busy = "";
    // The form while open: what is typed, and a picture picked but not yet sent
    // (a File), or "remove" for the one there to go.
    let form = null;
    let pictureUrl = "";

    const query = () => (options.speaks ? `?lang=${encodeURIComponent(options.speaks)}` : "");

    async function load() {
      try {
        value = await ctx.api(`characters${query()}`);
      } catch (failure) {
        return fail(failure);
      }
      await loadPicture();
      draw();
      options.onLoad?.(value);
    }

    // The picture there is, as a blob: it is behind the page's token.
    async function loadPicture() {
      if (pictureUrl) URL.revokeObjectURL(pictureUrl);
      pictureUrl = "";
      if (value?.picture) pictureUrl = await ctx.picture("/api/avatar").catch(() => "");
    }

    function fail(failure) {
      error.textContent = say(failure);
      error.hidden = false;
    }

    // The answer of a change: the sidebar and the pet follow, then whoever mounted this.
    async function changed(answer) {
      value = answer;
      ctx.setFigure?.(answer.figure);
      await ctx.changed?.();
      options.onChange?.(answer);
    }

    async function choose(key) {
      if (busy) return;
      error.hidden = true;
      busy = key;
      draw();
      try {
        await changed(await ctx.api("character", { key, lang: options.speaks || "" }));
        form = null;
      } catch (failure) {
        fail(failure);
      } finally {
        busy = "";
        draw();
      }
    }

    function card(key, figureKey, name, line, extra) {
      const chosen = value.chosen === key;
      const button = el("button", "pac-card");
      button.type = "button";
      button.setAttribute("aria-pressed", String(chosen));
      if (busy === key) button.setAttribute("aria-busy", "true");
      button.disabled = Boolean(busy);
      const stage = el("span", "pac-stage");
      if (figureKey) stage.append(ctx.bodyOf(figureKey, "pac-figure"));
      else if (extra) stage.append(extra);
      else stage.append(icon(PLUS, "pac-plus"));
      button.append(stage, el("span", "pac-name", name), el("span", "pac-line", busy === key ? t.choosing : line));
      button.append(icon(TICK, "pac-tick"));
      return button;
    }

    function draw() {
      grid.replaceChildren();
      if (!value) return;
      for (const row of value.characters) {
        const button = card(row.key, row.figure, row.name, row.line);
        button.addEventListener("click", () => {
          if (value.chosen !== row.key || !value.set) choose(row.key);
        });
        grid.append(button);
      }
      const own = value.custom;
      // One's own character shows its own face: the picture it was given, else the first letter of
      // its name, else a plus before there is one. Never a built-in figure, which would read as that one.
      const face = own
        ? pictureUrl
          ? Object.assign(el("img", "pac-face"), { src: pictureUrl, alt: "" })
          : el("span", "pac-face pac-initial", [...own.name][0] || "")
        : null;
      const line = own?.about ? own.about.replace(/\s+/g, " ") : t.ownLine;
      const button = card(CUSTOM, "", own?.name || t.own, line, face);
      button.classList.add("pac-own");
      if (form) button.setAttribute("aria-expanded", "true");
      // A press chooses it like any other; with none yet, or on the one in use, it opens the form.
      button.addEventListener("click", () => {
        if (own && value.chosen !== CUSTOM) choose(CUSTOM);
        else if (!form) open();
      });
      const wrap = el("div", "pac-wrap");
      wrap.append(button);
      if (own && !form) {
        const pencil = el("button", "pac-edit");
        pencil.type = "button";
        pencil.title = t.edit;
        pencil.setAttribute("aria-label", t.edit);
        pencil.disabled = Boolean(busy);
        pencil.append(icon(PENCIL, "pac-edit-icon"));
        pencil.addEventListener("click", open);
        wrap.append(pencil);
      }
      grid.append(wrap);
      drawForm();
    }

    function open() {
      const own = value.custom;
      form = { name: own?.name || "", about: own?.about || "", picture: null };
      error.hidden = true;
      draw();
      formBox.querySelector(".pac-input")?.focus();
    }

    function drawForm() {
      if (!form) return formBox.replaceChildren();
      const box = el("form", "pac-form");
      const row = (label, field, help) => {
        const line = el("label", "pac-row");
        line.append(el("span", "pac-label", label), field);
        if (help) line.append(el("span", "pac-help", help));
        return line;
      };
      const name = el("input", "pac-input");
      name.maxLength = value.limits.name;
      name.placeholder = t.namePlaceholder;
      name.value = form.name;
      name.addEventListener("input", () => (form.name = name.value));
      const about = el("textarea", "pac-input pac-about");
      about.rows = 5;
      about.maxLength = value.limits.about;
      about.placeholder = t.aboutPlaceholder;
      about.value = form.about;
      about.addEventListener("input", () => (form.about = about.value));

      const pictureRow = el("div", "pac-row");
      const pictureLine = el("div", "pac-picture-line");
      const shown = form.picture === "remove" ? "" : form.picture ? URL.createObjectURL(form.picture) : pictureUrl;
      const thumb = el("span", "pac-thumb");
      if (shown) thumb.append(Object.assign(el("img"), { src: shown, alt: "" }));
      const file = el("input");
      file.type = "file";
      file.accept = "image/png,image/jpeg,image/webp";
      file.hidden = true;
      file.addEventListener("change", () => {
        const picked = file.files[0];
        if (!picked) return;
        if (picked.size > value.limits.picture) return fail(new Error("avatar_too_large"));
        error.hidden = true;
        form.picture = picked;
        drawForm();
      });
      const pick = el("button", "pac-button", t.pickPicture);
      pick.type = "button";
      pick.addEventListener("click", () => file.click());
      pictureLine.append(thumb, pick, file);
      if (shown) {
        const remove = el("button", "pac-button pac-quiet", t.removePicture);
        remove.type = "button";
        remove.addEventListener("click", () => {
          form.picture = pictureUrl ? "remove" : null;
          drawForm();
        });
        pictureLine.append(remove);
      }
      pictureRow.append(el("span", "pac-label", t.picture), pictureLine, el("span", "pac-help", t.pictureHelp));

      const foot = el("div", "pac-foot");
      const cancel = el("button", "pac-button pac-quiet", t.cancel);
      cancel.type = "button";
      cancel.addEventListener("click", () => {
        form = null;
        error.hidden = true;
        draw();
      });
      const save = el("button", "pac-button pac-primary", t.save);
      save.type = "submit";
      foot.append(cancel, save);
      box.append(row(t.name, name), row(t.about, about), pictureRow, foot);
      box.addEventListener("submit", async (event) => {
        event.preventDefault();
        if (busy) return;
        if (!form.name.trim() && !form.about.trim()) return fail(new Error("custom_empty"));
        error.hidden = true;
        busy = CUSTOM;
        save.disabled = cancel.disabled = true;
        save.textContent = t.saving;
        try {
          let answer = await ctx.api("character", {
            key: CUSTOM, name: form.name.trim(), about: form.about.trim(), lang: options.speaks || "",
          });
          // The picture after: it is the face of the character now in use.
          if (form.picture === "remove") await ctx.api("avatar/remove", {});
          else if (form.picture) await ctx.api("avatar", form.picture);
          if (form.picture) answer = await ctx.api(`characters${query()}`);
          form = null;
          value = answer;
          await loadPicture();
          await changed(answer);
        } catch (failure) {
          fail(failure);
        } finally {
          busy = "";
          draw();
        }
      });
      formBox.replaceChildren(box);
    }

    load();
    return {
      get value() {
        return value;
      },
      choose,
      reload: load,
    };
  }

  return { mount };
})();
