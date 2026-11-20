"use strict";
// Settings › Language: the language of the screens, menus and messages (POST /api/look/ui; this window and
// every other open one start again in it), and the languages the person reads, as the situation keeps them
// (GET/POST /api/situation, factor "readable"). The character finds content in these.
(() => {
  // Each language in its own words, so the list reads the same in any page language.
  const AUTONYMS = { zh: "中文", en: "English", ja: "日本語", ko: "한국어", ru: "Русский", pt: "Português", es: "Español",
                     fr: "Français", de: "Deutsch" };

  window.paSetup.part("language", (kit) => {
    const { el } = kit;
    const t = kit.words("setup_language");
    const ctx = kit.ctx;
    const where = { view: null };
    const node = kit.section("language");

    const shown = kit.card();
    const pick = el("select", "setup-input setup-select setup-input-sm");
    for (const [code, name] of paI18n.languages) {
      const option = el("option", "", name);
      option.value = code;
      option.lang = code;
      pick.append(option);
    }
    pick.value = paI18n.lang;
    pick.setAttribute("aria-label", t.display);
    const shownError = kit.errorLine();
    shown.append(kit.optionRow(t.display, t.displayText, pick).row, shownError);
    node.append(shown);
    pick.addEventListener("change", async () => {
      pick.disabled = true;
      shownError.hidden = true;
      try {
        await ctx.api("look/ui", { lang: pick.value });
      } catch (failure) {
        pick.value = paI18n.lang;
        pick.disabled = false;
        kit.failed(shownError, failure, t);
        return;
      }
      ctx.relang();
    });

    const box = kit.card();
    const title = el("p", "setup-label", t.canRead);
    title.id = "setup-langs-readable";
    const chips = el("div", "setup-chips");
    chips.setAttribute("role", "group");
    chips.setAttribute("aria-labelledby", title.id);
    for (const code of Object.keys(AUTONYMS)) {
      const chip = el("button", "setup-chip", AUTONYMS[code]);
      chip.type = "button";
      chip.lang = code;
      chip.dataset.code = code;
      chip.setAttribute("aria-pressed", "false");
      chip.disabled = true;
      chip.addEventListener("click", () => toggleLang(code, chip));
      chips.append(chip);
    }
    const error = kit.errorLine();
    box.append(title, chips, error);
    node.append(box);

    // Changes go out one at a time, each worked out from the view the one before it left, so quick clicks add up.
    let queue = Promise.resolve();
    let pending = 0;
    function queued(work) {
      pending += 1;
      chips.setAttribute("aria-busy", "true");
      queue = queue.then(work).finally(() => {
        pending -= 1;
        if (!pending) chips.removeAttribute("aria-busy");
      });
      return queue;
    }

    function toggleLang(code, chip) {
      chip.setAttribute("aria-pressed", String(chip.getAttribute("aria-pressed") !== "true"));
      return queued(async () => {
        const list = where.view.factors.readable.value;
        error.hidden = true;
        try {
          where.view = await ctx.api("situation", {
            name: "readable",
            value: list.includes(code) ? list.filter((c) => c !== code) : [...list, code],
          });
        } catch (failure) {
          kit.failed(error, failure, t);
        }
        render();
      });
    }

    function render() {
      const reads = where.view.factors.readable.value;
      for (const chip of chips.children) {
        chip.disabled = false;
        chip.setAttribute("aria-pressed", String(reads.includes(chip.dataset.code)));
      }
    }

    async function show() {
      if (pending) return;
      try {
        where.view = await ctx.api("situation");
        error.hidden = true;
      } catch (failure) {
        kit.failed(error, failure, t);
        return;
      }
      render();
    }

    return { node, show };
  });
})();
