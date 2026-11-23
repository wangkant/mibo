"use strict";
// Settings › Model. At the top, what is in use: the service, the model, its state, and the two things
// people do most, change the model (the service's own list) and test the connection.
// Under it the chooser (setup/modelpick.js; open while nothing is connected, else behind 更换服务), the
// measured abilities and the usage (modelbar.js), and a fold for the backup model
// and the models for other uses.
(() => {
  const POLL_MS = 2500;
  // How long "working" stays beside the state after a test.
  const TESTED_MS = 6000;
  // The backup model and the models for other uses, as /api/tuning names them.
  const MORE = [
    ["LLM_FALLBACK_MODEL", "fallback"],
    ["LLM_FALLBACK_BASE_URL", "fallbackBase"],
    ["LLM_FALLBACK_API_KEY", "fallbackKey"],
    ["LLM_JUDGE_MODEL", "judge"],
    ["LLM_DM_MODEL", "dm"],
    ["CONTEXT_WINDOW", "contextWindow"],
  ];
  // The help under the context window, by where the window in use when it is blank comes from (context.window).
  const WINDOW_HELP = { host: "contextWindowHost", catalogue: "contextWindowCatalog", error: "contextWindowLearned",
                        assumed: "contextWindowAssumed" };
  // A failed save or test, as a state of the top card.
  const STATE_OF = {
    key_rejected: "key", model_no_balance: "no_balance", model_not_found: "not_found", model_limited: "limited",
  };

  window.paSetup.part("model", (kit) => {
    const { ctx, el, icon, fill, button, busy, field, input, fold, link, errorCode } = kit;
    const t = paI18n.words("setup_model");
    const n = window.paModelPick.naming(kit.catalog.providers);
    const say = (code) => t.errors[code] || t.errors.generic;
    const view = {
      // This visit's last test: null before any, else {state, at}.
      tested: null,
      testing: false,
      switching: "",
      // Connected during this visit: the top card says so and offers the chat.
      done: false,
      choosing: false,
      bar: null,
      list: null,
      listOpen: false,
      query: "",
      problem: "",
    };
    let pollTimer = 0;
    let testedTimer = 0;
    const parts = {};
    const more = { loaded: false, saving: false };

    const node = kit.section("model");

    // ---- The model in use.
    const now = el("div", "setup-card mp mp-now");
    const top = el("div", "mp-now-top");
    const markSlot = el("span", "mp-now-mark");
    const words = el("div", "mp-now-words");
    const modelName = el("p", "mp-now-model");
    const line = el("p", "mp-now-line");
    const serviceName = el("span", "mp-now-service");
    const state = el("span", "mp-state");
    line.append(serviceName, state);
    const marks = el("div", "mp-abilities");
    words.append(modelName, line);
    const actions = el("div", "mp-now-actions");
    const pickWrap = el("div", "mp-pick");
    const pickButton = button("setup-button-secondary setup-button-sm mp-pick-button", t.changeModel, () => toggleList());
    pickButton.append(icon("down", "setup-icon setup-icon-sm"));
    pickButton.setAttribute("aria-haspopup", "listbox");
    pickButton.setAttribute("aria-expanded", "false");
    const listBox = el("div", "mp-list");
    listBox.hidden = true;
    pickWrap.append(pickButton, listBox);
    const testButton = button("setup-button-secondary setup-button-sm", t.test, runTest);
    const chatButton = button("setup-button-primary setup-button-sm", t.toChat, () => ctx.go("chat"));
    actions.append(chatButton, pickWrap, testButton);
    top.append(markSlot, words, actions, marks);

    // A failure: what happened, and what to do about it.
    const fix = el("div", "mp-fix");
    fix.setAttribute("role", "alert");
    const fixWords = el("p", "mp-fix-words");
    const fixActions = el("div", "mp-fix-actions");
    fix.append(fixWords, fixActions);
    const changeService = button("setup-button-link mp-change-service", t.changeService, () => openChooser());
    const nowFoot = el("div", "mp-now-foot");
    nowFoot.append(changeService);
    now.append(top, fix, nowFoot);

    // ---- The chooser, in a card of its own.
    const chooseCard = el("div", "setup-card mp-choose-card");
    const chooseTitle = el("h3", "setup-card-title");
    const picker = window.paModelPick.chooser({
      api: ctx.api,
      catalog: kit.catalog.providers,
      state: () => kit.state,
      who: () => {
        const s = kit.state;
        return { name: s.name || "", character: s.character || "custom", lang: (s.configured && s.lang) || paI18n.lang };
      },
      done: connected,
      cancel: () => {
        view.choosing = false;
        paint();
        changeService.focus();
      },
    });
    chooseCard.append(chooseTitle, picker.node);

    node.append(kit.item("service", now), chooseCard);
    // What the model can do, measured, and what it spent (modelbar.js).
    const info = window.paModelBar.settings(kit, node);
    node.append(kit.item("more", buildMore()));

    function openChooser(focusKey = false) {
      view.choosing = true;
      paint();
      picker.open(kit.state.configured ? kit.state.provider : "", focusKey);
      chooseCard.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }

    async function connected(fresh) {
      kit.state = fresh;
      view.done = true;
      view.choosing = false;
      view.tested = { state: "ok", at: Date.now() };
      view.list = null;
      more.loaded = false;
      ctx.changed();
      paint();
      await loadBar();
      info.show();
      now.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }

    // The state as best known: this visit's test, else the last ability check, else the agent's.
    function stateNow() {
      if (view.testing) return "testing";
      if (view.tested) return view.tested.state;
      const error = view.bar?.abilities?.error;
      if (error && ["key", "no_balance", "not_found", "limited"].includes(error)) return error;
      if (kit.state.modelUnreachable) return "unreachable";
      return "ok";
    }

    function paint() {
      const s = kit.state;
      const on = Boolean(s.configured);
      now.classList.toggle("mp-now-off", !on);
      markSlot.replaceChildren(on ? n.mark(s.provider, "mp-mark-lg") : n.mark("", "mp-mark-lg mp-mark-empty"));
      actions.hidden = !on;
      marks.hidden = !on;
      nowFoot.hidden = !on || view.choosing;
      if (!on) {
        modelName.textContent = t.noneTitle;
        serviceName.textContent = t.noneText;
        state.hidden = true;
        fix.hidden = true;
        view.choosing = true;
      } else {
        modelName.textContent = view.switching ? view.switching : s.model;
        modelName.title = s.model;
        serviceName.textContent = n.name(s.provider);
        const now_ = stateNow();
        state.hidden = false;
        state.className = `mp-state mp-state-${now_}`;
        const fresh = view.tested && view.tested.state === "ok" && Date.now() - view.tested.at < TESTED_MS && !view.done;
        state.textContent = view.switching ? t.switching : fresh ? t.tested : t.states[now_];
        paintFix(now_);
      }
      chatButton.hidden = !(on && view.done);
      busy(testButton, view.testing, view.testing ? t.testing : t.test);
      pickButton.disabled = Boolean(view.switching) || view.testing;
      paintMarks();
      chooseCard.hidden = !view.choosing;
      chooseTitle.textContent = on ? t.changeTitle : t.chooseTitle;
      parts.more.hidden = !on;
    }

    function paintFix(now_) {
      const problem = view.problem;
      const failing = !["ok", "testing"].includes(now_);
      fix.hidden = !failing && !problem;
      if (fix.hidden) return;
      fixWords.textContent = problem || t.fixes[now_];
      fixActions.replaceChildren();
      const spec = n.spec(kit.state.provider);
      if (now_ === "key") {
        fixActions.append(button("setup-button-secondary setup-button-sm", t.replaceKey, () => openChooser(true)));
        if (spec?.keyUrl) fixActions.append(link(t.getKey, spec.keyUrl, true));
      }
      if (now_ === "no_balance" && view.bar?.console) fixActions.append(link(t.topUp, view.bar.console, true));
      if (now_ === "not_found") fixActions.append(button("setup-button-secondary setup-button-sm", t.changeModel, () => toggleList(true)));
      fixActions.hidden = !fixActions.children.length;
    }

    // The measured abilities as small marks under the model's name.
    function paintMarks() {
      marks.replaceChildren();
      const bar = view.bar;
      if (!bar?.configured) return;
      if (bar.checking) {
        marks.append(el("span", "mp-ability mp-ability-wait", t.checkingAbilities));
        return;
      }
      const rec = bar.abilities;
      if (!rec) return;
      for (const name of ["tools", "pictures", "thinking"]) {
        // Only what works shows here; the card below says what is missing and why.
        if (rec[name] !== "yes") continue;
        const chip = el("span", "mp-ability");
        chip.append(icon(name, "setup-icon mp-ability-icon"), el("span", "", t.abilities[name]));
        marks.append(chip);
      }
    }

    async function loadBar() {
      clearTimeout(pollTimer);
      try {
        view.bar = await ctx.api("modelbar");
      } catch {
        return;
      }
      paint();
      if (view.bar.checking) pollTimer = setTimeout(loadBar, POLL_MS);
    }

    async function runTest() {
      if (view.testing) return;
      view.testing = true;
      view.problem = "";
      view.done = false;
      paint();
      let result = "ok";
      try {
        await ctx.api("look/check", {});
      } catch (failure) {
        // A failed test comes back as its error code (app.js throws on one).
        result = STATE_OF[errorCode(failure)] || "unreachable";
      }
      view.testing = false;
      view.tested = { state: result, at: Date.now() };
      paint();
      clearTimeout(testedTimer);
      if (result === "ok") testedTimer = setTimeout(paint, TESTED_MS);
    }

    // ---- The service's models: searchable, the current one ticked.
    async function toggleList(force) {
      const opening = force ?? listBox.hidden;
      if (!opening) return closeList();
      view.listOpen = true;
      view.query = "";
      listBox.hidden = false;
      pickButton.setAttribute("aria-expanded", "true");
      paintList();
      if (!view.list) {
        try {
          view.list = await ctx.api("modelbar/models");
        } catch {
          view.list = { current: kit.state.model, recent: [], models: [], free: [] };
        }
        if (view.listOpen) paintList();
      }
      listBox.querySelector("input")?.focus();
    }
    function closeList() {
      view.listOpen = false;
      listBox.hidden = true;
      pickButton.setAttribute("aria-expanded", "false");
    }
    const search = input("mp-search-input");
    search.placeholder = t.search;
    search.setAttribute("aria-label", t.search);
    const searchBox = el("label", "mp-search");
    searchBox.append(icon("search", "setup-icon setup-icon-sm"), search);
    const rows = el("div", "mp-rows");
    rows.setAttribute("role", "listbox");
    listBox.append(searchBox, rows);
    search.addEventListener("input", () => {
      view.query = search.value;
      paintRows();
    });
    search.addEventListener("keydown", (event) => {
      if (event.key === "ArrowDown") {
        event.preventDefault();
        rows.querySelector(".mp-row")?.focus();
      } else if (event.key === "Enter") {
        event.preventDefault();
        rows.querySelector(".mp-row")?.click();
      }
    });
    listBox.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        event.stopPropagation();
        closeList();
        pickButton.focus();
        return;
      }
      const all = [...rows.querySelectorAll(".mp-row")];
      const at = all.indexOf(document.activeElement);
      if (at < 0) return;
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        const next = at + (event.key === "ArrowDown" ? 1 : -1);
        (next < 0 ? search : all[Math.min(next, all.length - 1)]).focus();
      }
    });
    document.addEventListener("pointerdown", (event) => {
      if (view.listOpen && !pickWrap.contains(event.target)) closeList();
    }, true);

    function paintList() {
      search.value = view.query;
      paintRows();
    }
    function paintRows() {
      rows.replaceChildren();
      const list = view.list;
      if (!list) {
        rows.append(el("p", "mp-rows-note", t.loading));
        return;
      }
      const q = view.query.trim().toLowerCase();
      const match = (m) => !q || m.toLowerCase().includes(q);
      const free = new Set(list.free || []);
      const current = kit.state.model;
      const recent = (list.recent || []).filter((m) => m !== current && match(m));
      const rest = (list.models || []).filter((m) => m !== current && !recent.includes(m) && match(m));
      if (match(current)) rows.append(row(current, true, free));
      if (recent.length) rows.append(el("p", "mp-rows-head", t.recent), ...recent.map((m) => row(m, false, free)));
      if (rest.length) {
        if (recent.length) rows.append(el("p", "mp-rows-head", t.all));
        rows.append(...rest.slice(0, 300).map((m) => row(m, false, free)));
      }
      // A name the service does not list may still be one it runs.
      const typed = view.query.trim();
      const known = [current, ...(list.recent || []), ...(list.models || [])];
      if (typed && !known.includes(typed)) {
        const use = row(typed, false, free);
        use.querySelector(".mp-row-name").textContent = fill(t.useTyped, { name: typed });
        rows.append(use);
      }
      if (!rows.children.length) rows.append(el("p", "mp-rows-note", t.noMatch));
    }
    function row(model, current, free) {
      const item = el("button", "mp-row");
      item.type = "button";
      item.setAttribute("role", "option");
      item.setAttribute("aria-selected", String(current));
      item.append(el("span", "mp-row-name", model));
      if (free.has(model)) item.append(el("span", "mp-row-tag", t.free));
      if (current) item.append(icon("check", "setup-icon setup-icon-sm mp-row-tick"));
      item.addEventListener("click", () => (current ? closeList() : switchTo(model)));
      return item;
    }

    async function switchTo(model) {
      closeList();
      pickButton.focus();
      view.switching = model;
      view.problem = "";
      view.done = false;
      paint();
      try {
        view.bar = await ctx.api("modelbar/model", { model });
        kit.state = { ...kit.state, model };
        view.tested = { state: "ok", at: Date.now() };
        view.list = null;
        ctx.changed();
      } catch (failure) {
        const code = errorCode(failure);
        view.problem = fill(t.switchFailed, { name: model }) + say(code);
      }
      view.switching = "";
      paint();
      clearTimeout(testedTimer);
      testedTimer = setTimeout(paint, TESTED_MS);
      loadBar();
      info.show();
    }

    // ---- The backup model and the models for other uses (GET/POST /api/tuning).
    function buildMore() {
      const box = fold(t.more);
      box.node.classList.add("setup-card");
      const form = el("form", "mp-more-form");
      form.noValidate = true;
      const fields = {};
      const pair = el("div", "mp-more-pair");
      for (const [name, word] of MORE) {
        const control = input();
        if (name === "LLM_FALLBACK_API_KEY") {
          control.type = "password";
          control.classList.add("setup-secret-input");
        }
        if (name === "LLM_FALLBACK_BASE_URL") control.inputMode = "url";
        if (name === "CONTEXT_WINDOW") control.inputMode = "numeric";
        const one = field(t[word], control, t[`${word}Help`]);
        control.addEventListener("input", () => {
          one.error("");
          note.textContent = "";
        });
        fields[name] = one;
        if (name === "LLM_FALLBACK_BASE_URL") form.append(pair);
        (name.startsWith("LLM_FALLBACK_") && name !== "LLM_FALLBACK_MODEL" ? pair : form).append(one.wrap);
      }
      const footRow = el("div", "setup-foot");
      const save = button("setup-button-secondary", t.save);
      save.type = "submit";
      const note = el("p", "setup-foot-note");
      note.setAttribute("aria-live", "polite");
      footRow.append(save, note);
      const failLine = el("p", "setup-error");
      failLine.setAttribute("role", "alert");
      failLine.hidden = true;
      form.append(footRow, failLine);
      box.body.append(form);
      box.node.addEventListener("toggle", () => box.node.open && !more.loaded && loadMore());
      form.addEventListener("submit", (event) => {
        event.preventDefault();
        saveMore();
      });
      Object.assign(more, { fields, save, note, failLine });
      parts.more = box.node;
      return box.node;
    }
    async function loadMore() {
      try {
        const value = await ctx.api("tuning");
        for (const [name] of MORE) {
          const one = more.fields[name].control;
          if (name === "LLM_FALLBACK_API_KEY") {
            one.value = "";
            one.placeholder = value.secrets[name] ? t.fallbackKeyKeep : "";
          } else one.value = value.values[name] || "";
        }
        more.fields.LLM_FALLBACK_BASE_URL.control.placeholder = value.llmBaseUrl || "";
        const room = value.contextWindow;
        more.fields.CONTEXT_WINDOW.control.placeholder = String(room.tokens);
        more.fields.CONTEXT_WINDOW.help(fill(t[WINDOW_HELP[room.from]], { n: room.tokens.toLocaleString() }));
        more.loaded = true;
        more.failLine.hidden = true;
      } catch (failure) {
        more.failLine.textContent = say(errorCode(failure));
        more.failLine.hidden = false;
      }
    }
    async function saveMore() {
      if (more.saving) return;
      const values = {};
      for (const [name] of MORE) {
        const value = more.fields[name].control.value.trim();
        // An empty key field keeps the saved key.
        if (name === "LLM_FALLBACK_API_KEY" && !value) continue;
        values[name] = value;
      }
      more.saving = true;
      more.failLine.hidden = true;
      more.note.textContent = "";
      busy(more.save, true, t.saving);
      try {
        await ctx.api("tuning", { values });
        await loadMore();
        more.note.textContent = t.saved;
      } catch (failure) {
        const code = errorCode(failure);
        const [kind, name] = code.split(":");
        if (kind === "tuning_invalid" && more.fields[name]) more.fields[name].error(t.errors.tuning_invalid);
        else if (code === "tuning_key_needed") more.fields.LLM_FALLBACK_API_KEY.error(say(code));
        else if (code === "tuning_https") more.fields.LLM_FALLBACK_BASE_URL.error(say(code));
        else {
          more.failLine.textContent = say(code);
          more.failLine.hidden = false;
        }
      } finally {
        more.saving = false;
        busy(more.save, false, t.save);
      }
    }

    // ---- Shown.
    if (!kit.state.configured) picker.open("");
    paint();
    loadBar();

    // Opened again: the model may have been connected or changed elsewhere since.
    async function show(asked) {
      // Asked for by a link while a model works: the chooser opens.
      if (asked && kit.state.configured && !view.choosing) openChooser();
      if (picker.busy() || view.switching) return;
      try {
        const fresh = await ctx.api("state");
        const s = kit.state;
        if (fresh.configured !== s.configured || fresh.provider !== s.provider || fresh.model !== s.model) {
          view.tested = null;
          view.list = null;
          kit.state = fresh;
          if (!fresh.configured) picker.open("");
        } else kit.state = fresh;
      } catch {
        return;
      }
      paint();
      loadBar();
      info.show();
    }

    return { node, show };
  });
})();
