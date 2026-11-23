"use strict";
// The model service chooser, shared by Settings › Model (setup/model.js) and the first run (onboard.js): a
// service, then only what it needs (a program on this computer, a sign-in, a key), saved through /api/config,
// which tests first. Its controls are Settings' own (setup.js kit).
(() => {
  const { el, icon, fill, button, busy, field, input, fold, link, errorCode } = window.paSetup.kit;
  // Each service's mark where it has no picture of its own: two letters on a plain tile.
  const MARKS = {
    deepseek: "DS", bailian: "QW", zhipu: "GL", moonshot: "Ki", ark: "DB", siliconflow: "SF", minimax: "MM",
    qianfan: "QF", hunyuan: "HY", openrouter: "OR", openai: "AI", anthropic: "Cl", gemini: "Ge", xai: "X",
    mistral: "Mi", groq: "Gq",
  };
  // Where to get a program that runs models on this computer.
  const LOCAL_GET = { ollama: "https://ollama.com/download", lmstudio: "https://lmstudio.ai/download" };
  // Tiles shown before "more services".
  const TILES = 8;
  const SIGNIN_POLL_MS = 1500;

  // A service by id, named for the page's language: its short name for the tiles and the top card, and a
  // second line where it helps (setup_model.services in the catalog).
  function naming(catalog) {
    const services = paI18n.words("setup_model").services;
    const spec = (id) => catalog.find((p) => p.id === id);
    return {
      spec,
      name: (id) => (services[id] ? services[id].name : spec(id) ? spec(id).name : id),
      sub: (id) => services[id]?.sub || "",
      mark(id, cls = "") {
        const box = el("span", `mp-mark ${cls}`.trim());
        box.setAttribute("aria-hidden", "true");
        // The service's own mark (providermarks.js); else two letters; else a server for one's own, a chip for the rest.
        const own = window.paProviderMarks?.[id];
        if (own) {
          box.classList.add("mp-mark-own");
          box.innerHTML = own;
        } else if (MARKS[id]) box.textContent = MARKS[id];
        else box.append(icon(id === "other" ? "server" : "model", "setup-icon mp-mark-icon"));
        return box;
      },
    };
  }

  // ---- The chooser: a service, then only what it needs. Settings and the first run share it.
  // env: {api, catalog (providers), state() {configured, provider, baseUrl, model},
  //       who() {name, character, lang}, done(state), cancel() (offered once a model is connected)}
  function chooser(env) {
    const t = paI18n.words("setup_model");
    const n = naming(env.catalog);
    const say = (code) => t.errors[code] || t.errors.generic;
    const root = el("div", "mp mp-chooser");
    let selected = "";
    let expanded = false;
    let working = false;
    let found = null;
    let replacing = false;
    const signin = { phase: "idle", error: "", url: "", timer: 0 };

    // What this computer already has, one press away.
    const foundBox = el("div", "mp-found");
    // The tiles.
    const grid = el("div", "mp-grid");
    grid.setAttribute("role", "radiogroup");
    grid.setAttribute("aria-label", t.chooseTitle);
    const moreTile = el("button", "mp-tile mp-tile-more");
    moreTile.type = "button";
    moreTile.addEventListener("click", () => {
      expanded = !expanded;
      paintGrid();
    });

    // What the chosen service needs.
    const details = el("form", "mp-details");
    details.noValidate = true;

    // (a) A program on this computer.
    const local = el("div", "mp-local");
    const localLine = el("p", "mp-local-line");
    const localModel = el("select", "setup-input setup-select");
    const localModelField = field(t.localModel, localModel);
    const localActions = el("div", "mp-inline-actions");
    const localRetry = button("setup-button-secondary setup-button-sm", t.localRetry, detect);
    const localGet = el("span");
    localActions.append(localRetry, localGet);
    local.append(localLine, localModelField.wrap, localActions);

    // (b) Signing in with OpenRouter.
    const signinBox = el("div", "mp-signin");
    const signinGo = button("setup-button-secondary mp-signin-button", t.signin, signinStart);
    signinGo.prepend(icon("spark"));
    const signinCancel = button("setup-button-ghost setup-button-sm", t.cancel, signinStop);
    const signinRow = el("div", "mp-inline-actions");
    signinRow.append(signinGo, signinCancel);
    const signinLine = el("p", "setup-help");
    signinLine.setAttribute("aria-live", "polite");
    const signinOpen = link(t.signinOpenPage, "#", true);
    const signinError = el("p", "setup-error");
    signinError.setAttribute("role", "alert");
    const signinOr = el("div", "mp-or");
    signinOr.append(el("span", "", t.signinOr));
    signinBox.append(signinRow, signinLine, signinOpen, signinError, signinOr);

    // (c) A key.
    const keyBox = el("div", "setup-secret");
    const key = input("setup-secret-input");
    key.type = "password";
    key.placeholder = t.keyPlaceholder;
    const reveal = el("button", "setup-reveal");
    reveal.type = "button";
    const paintReveal = () => {
      const shown = key.type === "text";
      reveal.replaceChildren(icon(shown ? "eyeOff" : "eye"));
      reveal.setAttribute("aria-label", shown ? t.hideKey : t.showKey);
      reveal.title = shown ? t.hideKey : t.showKey;
    };
    reveal.addEventListener("click", () => {
      key.type = key.type === "password" ? "text" : "password";
      paintReveal();
      key.focus();
    });
    paintReveal();
    keyBox.append(key, reveal);
    const keyField = field(t.key, keyBox);
    const getKey = link(t.getKey, "#", true);
    getKey.classList.add("setup-link-head");
    keyField.head.append(getKey);
    // A key already saved for this service: never shown again, only replaced.
    const savedRow = el("div", "mp-saved");
    savedRow.append(el("span", "mp-saved-dots", "••••••••••••"), el("span", "mp-saved-word", t.keySaved));
    const replace = button("setup-button-link", t.keyReplace, () => {
      replacing = true;
      paintDetails();
      key.focus();
    });
    savedRow.append(replace);
    keyField.wrap.insertBefore(savedRow, keyBox);
    const envLine = el("div", "mp-env");
    const envWords = el("p", "setup-help");
    const envUse = button("setup-button-secondary setup-button-sm", t.envUse);
    envLine.append(envWords, envUse);
    keyField.wrap.append(envLine);
    key.addEventListener("input", () => keyField.error(""));

    // The address and the model: open for a custom service, folded for the rest.
    const base = input();
    base.inputMode = "url";
    base.placeholder = "https://…/v1";
    const baseField = field(t.address, base, t.addressHelp);
    const modelInput = input();
    const modelField = field(t.model, modelInput, t.modelHelp);
    const open = el("div", "mp-open");
    const adv = fold(t.advanced);
    adv.node.classList.add("mp-advanced");
    const noteLine = el("p", "setup-help");
    adv.body.append(noteLine);
    base.addEventListener("input", () => {
      baseField.error("");
      paintSends();
    });
    modelInput.addEventListener("input", () => modelField.error(""));

    const foot = el("div", "setup-foot mp-foot");
    const go = button("setup-button-primary", t.connect);
    go.type = "submit";
    const cancel = button("setup-button-ghost", t.cancel, () => env.cancel());
    const progress = el("p", "setup-progress");
    progress.setAttribute("aria-live", "polite");
    foot.append(go, cancel, progress);
    const error = el("p", "setup-error mp-error");
    error.setAttribute("role", "alert");
    error.hidden = true;
    const stays = el("p", "setup-fine", t.keyStays);
    // Where page text, window pictures and file text go: said once for each service's host (see/when.py), never
    // asked per action. The host last told comes from /api/model/notice; a save tells the new one.
    const sends = el("p", "setup-fine mp-sends");
    sends.hidden = true;
    let told = null;
    env.api("model/notice").then((value) => {
      told = value.host;
      if (selected) paintSends();
    }).catch(() => {});

    details.append(local, signinBox, keyField.wrap, open, adv.node, foot, error, stays, sends);
    root.append(foundBox, grid, details);
    details.addEventListener("submit", (event) => {
      event.preventDefault();
      submit();
    });

    function paintGrid() {
      const ids = env.catalog.map((p) => p.id);
      const shown = expanded ? ids : ids.slice(0, TILES);
      // The chosen one stays in sight.
      if (selected && !shown.includes(selected)) shown.push(selected);
      grid.replaceChildren();
      for (const id of shown) {
        const tile = el("button", "mp-tile");
        tile.type = "button";
        tile.setAttribute("role", "radio");
        tile.setAttribute("aria-checked", String(id === selected));
        tile.title = n.spec(id).name;
        const words = el("span", "mp-tile-words");
        words.append(el("span", "mp-tile-name", n.name(id)));
        const sub = n.sub(id);
        if (sub) words.append(el("span", "mp-tile-sub", sub));
        tile.append(n.mark(id), words);
        if (id === selected) tile.append(icon("check", "setup-icon mp-tile-tick"));
        tile.disabled = working;
        tile.addEventListener("click", () => choose(id));
        grid.append(tile);
      }
      if (ids.length > TILES) {
        moreTile.replaceChildren(el("span", "mp-tile-name", expanded ? t.fewerServices : `${t.moreServices} (${ids.length - TILES})`),
                                 icon("down", `setup-icon mp-more-icon${expanded ? " mp-more-up" : ""}`));
        moreTile.setAttribute("aria-expanded", String(expanded));
        grid.append(moreTile);
      }
    }

    function choose(id, focusKey = true) {
      selected = id;
      replacing = false;
      const s = env.state();
      const spec = n.spec(id);
      const mine = s.configured && s.provider === id;
      base.value = (mine && s.baseUrl) || spec.baseUrl;
      modelInput.value = (mine && s.model) || spec.model;
      key.value = "";
      for (const f of [keyField, baseField, modelField, localModelField]) f.error("");
      error.hidden = true;
      paintGrid();
      paintFound();
      paintDetails();
      if (focusKey && !keyField.wrap.hidden && !keyBox.hidden) key.focus();
    }

    function paintFound() {
      foundBox.replaceChildren();
      const rows = [
        ...(found?.local || []).map((row) => [row.provider, fill(t.foundLocal, { name: n.name(row.provider) })]),
        ...(found?.keys || []).map((row) => [row.provider, fill(t.foundEnv, { name: n.name(row.provider), variable: row.variable })]),
      ];
      for (const [id, text] of rows) {
        if (id === selected) continue;
        const line = el("div", "mp-found-row");
        line.append(n.mark(id), el("p", "mp-found-words", text),
                    button("setup-button-secondary setup-button-sm", t.foundPick, () => choose(id)));
        foundBox.append(line);
      }
      foundBox.hidden = !foundBox.children.length;
    }

    function localFound() {
      return found?.local.find((row) => row.provider === selected) || null;
    }

    function paintDetails() {
      const s = env.state();
      const spec = n.spec(selected);
      const isLocal = spec.local;
      const custom = selected === "other";
      const mine = s.configured && s.provider === selected;
      const running = isLocal ? localFound() : null;
      details.hidden = !selected;

      local.hidden = !isLocal;
      if (isLocal) {
        const name = n.name(selected);
        localLine.textContent = fill(running ? t.localRunning : t.localMissing, { name });
        localModel.replaceChildren(...(running?.models || []).map((m) => new Option(m, m)));
        if (running && mine && running.models.includes(s.model)) localModel.value = s.model;
        localModelField.wrap.hidden = !running || running.models.length < 2;
        localRetry.hidden = Boolean(running);
        localGet.replaceChildren(...(LOCAL_GET[selected] && !running ? [link(fill(t.localGet, { name }), LOCAL_GET[selected], true)] : []));
      }

      signinBox.hidden = selected !== "openrouter";
      paintSignin();

      keyField.wrap.hidden = isLocal;
      const keepSaved = mine && !replacing;
      savedRow.hidden = !keepSaved;
      keyBox.hidden = keepSaved;
      getKey.hidden = !spec.keyUrl;
      if (spec.keyUrl) getKey.href = spec.keyUrl;
      const env_ = found?.keys.find((row) => row.provider === selected);
      envLine.hidden = !env_ || keepSaved;
      if (env_) {
        envWords.textContent = fill(t.envFound, { variable: env_.variable });
        envUse.onclick = () => save({ provider: selected, apiKey: "", apiKeyFrom: env_.variable, baseUrl: spec.baseUrl, model: spec.model });
      }

      // A custom service needs its address and model in sight; the rest keep them folded.
      noteLine.textContent = spec.note;
      noteLine.hidden = !noteLine.textContent;
      modelField.help(custom ? "" : t.modelHelp);
      if (custom) {
        open.append(baseField.wrap, modelField.wrap);
        adv.node.hidden = true;
      } else {
        adv.body.prepend(baseField.wrap, modelField.wrap);
        adv.node.hidden = false;
        // A local program not found running may live at another address.
        if (isLocal && !running) adv.node.open = true;
      }
      open.hidden = !custom;
      // Nothing to go back to before a first connection.
      cancel.hidden = !s.configured;
      stays.hidden = isLocal;
      paintSends();
      paintWorking();
    }

    // A program on this computer keeps everything here; a service at a host not yet told about is named.
    function paintSends() {
      const spec = n.spec(selected);
      let host = "";
      try {
        host = new URL(base.value.trim() || spec.baseUrl).hostname;
      } catch {
        host = "";
      }
      sends.textContent = fill(t.sendsTo, { host });
      sends.hidden = told === null || !host || spec.local || host === told;
    }

    function paintWorking() {
      busy(go, working, working ? t.connecting : t.connect);
      progress.textContent = working ? fill(t.connectingLine, { name: n.name(selected) }) : "";
      for (const one of [key, base, modelInput]) one.readOnly = working;
      cancel.disabled = working;
      envUse.disabled = working;
      for (const tile of grid.querySelectorAll(".mp-tile")) tile.disabled = working;
      if (working) signinGo.disabled = true;
    }

    function submit() {
      const s = env.state();
      const spec = n.spec(selected);
      const mine = s.configured && s.provider === selected;
      const typed = key.value.trim();
      if (!spec.local && !typed && !(mine && !replacing)) {
        keyField.error(t.errors.key_required);
        key.focus();
        return;
      }
      const running = spec.local ? localFound() : null;
      save({
        provider: selected,
        apiKey: typed,
        baseUrl: running && !adv.node.open ? running.baseUrl : base.value.trim(),
        model: running && !adv.node.open ? localModel.value || running.models[0] : modelInput.value.trim(),
      });
    }

    async function save(payload) {
      if (working) return;
      working = true;
      error.hidden = true;
      for (const f of [keyField, baseField, modelField]) f.error("");
      paintWorking();
      try {
        const state = await env.api("config", { ...env.who(), ...payload });
        // The save told the person about this service's host.
        told = (await env.api("model/notice")).host;
        key.value = "";
        replacing = false;
        working = false;
        env.done(state);
      } catch (failure) {
        working = false;
        place(errorCode(failure));
      } finally {
        paintWorking();
        paintSignin();
      }
    }

    // A code from the save: under its field, else one line under the button.
    function place(code) {
      const text = say(code);
      if (["key_required", "key_again", "key_rejected", "key_malformed"].includes(code) && !keyField.wrap.hidden) {
        replacing = true;
        paintDetails();
        keyField.error(text);
        key.focus();
        return;
      }
      if (["model_required", "model_not_found", "invalid_url", "https_required"].includes(code)) {
        if (selected !== "other") adv.node.open = true;
        const f = code.startsWith("model") ? modelField : baseField;
        f.error(text);
        f.control.focus();
        return;
      }
      error.textContent = text;
      error.hidden = false;
    }

    // ---- Signing in: the browser approves, the server keeps the key.
    function paintSignin() {
      const waiting = signin.phase === "waiting";
      const verifying = signin.phase === "verifying";
      const opening = signin.phase === "opening";
      busy(signinGo, opening || waiting || verifying,
        opening ? t.signinOpening : waiting || verifying ? t.signinPending : t.signin);
      if (working) signinGo.disabled = true;
      signinCancel.hidden = !waiting;
      signinLine.hidden = !(waiting || verifying);
      signinLine.textContent = verifying ? t.signinVerifying : t.signinWaiting;
      signinOpen.hidden = !(waiting && signin.url);
      if (waiting && signin.url) signinOpen.href = signin.url;
      signinError.hidden = signin.phase !== "failed";
      signinError.textContent = signin.phase === "failed" ? say(signin.error) : "";
    }
    function signinFollow(value) {
      signin.phase = value.state === "idle" ? (signin.phase === "opening" ? "opening" : "idle") : value.state;
      signin.error = value.error || "";
      signin.url = value.url || "";
      const polling = signin.phase === "waiting" || signin.phase === "verifying";
      if (polling && !signin.timer) signin.timer = setInterval(signinPoll, SIGNIN_POLL_MS);
      if (!polling && signin.timer) {
        clearInterval(signin.timer);
        signin.timer = 0;
      }
      // The server keeps a finished attempt until the page has seen it.
      if (signin.phase === "done" || signin.phase === "failed") env.api("signin/cancel", {}).catch(() => {});
      if (signin.phase === "done") return signinDone();
      paintSignin();
    }
    async function signinPoll() {
      try {
        signinFollow(await env.api("signin"));
      } catch {
        // The next tick asks again.
      }
    }
    async function signinStart() {
      signin.phase = "opening";
      signin.error = "";
      paintSignin();
      const form = env.who();
      const s = env.state();
      // The model already chosen at OpenRouter stays; otherwise the service's own default.
      if (s.provider === "openrouter" && s.configured && s.model) form.model = s.model;
      try {
        signinFollow(await env.api("signin/start", { provider: "openrouter", form, pageLang: paI18n.lang }));
      } catch (failure) {
        signin.phase = "failed";
        signin.error = errorCode(failure);
        paintSignin();
      }
    }
    async function signinStop() {
      busy(signinCancel, true);
      try {
        signinFollow(await env.api("signin/cancel", {}));
      } catch {
        // Still waiting: the next poll says so.
      } finally {
        busy(signinCancel, false);
      }
    }
    async function signinDone() {
      signin.phase = "idle";
      paintSignin();
      try {
        env.done(await env.api("state"));
      } catch {
        // The next look at the page reads it again.
      }
    }

    // What this computer has: a local program running, a key in the environment.
    async function detect() {
      busy(localRetry, true);
      try {
        found = await env.api("detect");
      } catch {
        found = found || { local: [], keys: [] };
      }
      busy(localRetry, false);
      paintFound();
      if (selected) paintDetails();
    }

    detect();
    env.api("signin")
      .then((value) => (value.state === "waiting" || value.state === "verifying") && signinFollow(value))
      .catch(() => {});

    return {
      node: root,
      // Opened on a service: the saved one, else the first for the page's language.
      open(id, focusKey = false) {
        const s = env.state();
        choose(id || (s.configured ? s.provider : env.catalog[0].id), focusKey);
        if (focusKey) {
          replacing = true;
          paintDetails();
          key.focus();
        }
      },
      busy: () => working || signin.phase === "waiting" || signin.phase === "verifying",
    };
  }

  window.paModelPick = { chooser, naming };
})();
