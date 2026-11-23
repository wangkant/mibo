// The first run, in five steps walked in order: the language, the character, the
// model it thinks with, what the person cares about, and a last look at them: where
// they seem to be (GET /api/situation) and a few lines in their own words.
// Where it looks is not asked: it reads the public internet and learns from what the person opens.
// Nothing has to be chosen: beside Next, a small button skips the step as it was,
// and everything can be set later in Settings.
// The shell shows it instead of the app while needed() says so.
(() => {
  "use strict";

  // The languages the character speaks, by their own names; the screens follow the one picked.
  const LANGS = paI18n.languages;
  const STEP_COUNT = 5;
  const [LANG, FIGURE, MODEL, TOPICS, ABOUT] = [0, 1, 2, 3, 4];

  // How long the goodbye stays in the bubble before the app comes in.
  const BYE_MS = 900;
  // The first start's reachability probe takes about this long: the situation is read again after it.
  const PROBE_WAIT_MS = 6000;
  const PROBE_READS = 3;
  const TELL_MAX = 1000;
  // Languages in their own words, as Settings shows them.
  const AUTONYMS = { zh: "中文", en: "English", ja: "日本語", ko: "한국어", ru: "Русский", pt: "Português", es: "Español",
                     fr: "Français", de: "Deutsch" };
  // The sites the "where" line checks, by their names in the catalog (onboard.platforms).
  const LINE_PLATFORMS = [["bilibili.com", "bilibili"], ["youtube.com", "youtube"]];
  const SVG = "http://www.w3.org/2000/svg";

  let ctx, t, done;
  let root, bubble, bar, body, backButton, nextButton, needLine, skipButton;
  let step = 0;
  // Step one: the language the character speaks.
  let speaks = "";
  // Step two: the character picker (characters.js), the characters as it last read them, and the one in
  // use as the tour opened.
  let picker = null;
  let character = null;
  let characterAtStart = "";
  // Step three: the services offered, and the model as saved.
  let catalog = null;
  let model = { configured: false, provider: "", model: "", name: "" };
  let modelForm = null;
  // The chooser, made once for the screens' language.
  let modelPick = null;
  // Step four: the topics offered and the ones picked (in the order picked).
  let suggested = [];
  let picked = [];
  let pickedAtStart = [];
  // The topics as last saved.
  let pickedSaved = [];
  // After the topics: the finds asked for while `looking` (the ask itself, so a late answer to an earlier one is
  // dropped), then shown one at a time while `finding`.
  let looking = null;
  let finding = false;
  let finds = [];
  let findAt = 0;
  let findPicture = "";
  // Step five: the situation as read (false when it could not be), and the person's own words.
  let where = null;
  let whereReads = 0;
  let whereTimer = 0;
  let whereBox = null;
  let tellBox = null;
  let draft = "";
  let sent = "";
  // null, "waiting", or the answer's { rewritten }.
  let told = null;
  let tellError = "";

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
  const TICK = "M5 12.5l4.2 4.2L19 7";
  const PLUS = "M12 5v14M5 12h14";
  const CROSS = "M7 7l10 10M17 7L7 17";
  const ASK = "M9.1 9a3 3 0 0 1 5.8 1c0 2-2.9 2.6-2.9 4M12 18h.01";

  const say = (error) => t.errors[error?.message] || t.errors.generic;
  // The language of the topics and names on offer for a spoken one: they are written in Chinese and English.
  const screens = (code) => (code.toLowerCase().startsWith("zh") ? "zh" : "en");

  // The language this computer asks for, as one of LANGS.
  function guessLang() {
    const asked = (navigator.languages || [navigator.language || "en"]).map((code) => code.toLowerCase());
    for (const code of asked) {
      if (/^zh-(tw|hk|mo)|hant/.test(code)) return "zh-TW";
      if (code.startsWith("zh")) return "zh";
      if (code.startsWith("pt")) return "pt-BR";
      const known = LANGS.find(([key]) => key === code.split("-")[0]);
      if (known) return known[0];
    }
    return "en";
  }

  // ------------------------------------------------------------- the frame --

  function mount(node, context, finished) {
    ctx = context;
    done = finished;
    speaks = LANGS.some(([key]) => key === ctx.state?.lang) ? ctx.state.lang : guessLang();
    t = paI18n.words("onboard");
    model = {
      configured: Boolean(ctx.state?.configured),
      provider: ctx.state?.provider || "",
      model: ctx.state?.model || "",
      baseUrl: ctx.state?.baseUrl || "",
      name: ctx.state?.name || "",
    };
    root = el("div", "onboard-root");

    const card = el("div", "onboard-card");
    const top = el("header", "onboard-top");
    bar = el("ol", "onboard-progress");
    for (let index = 0; index < STEP_COUNT; index++) {
      const item = el("li", "onboard-dot");
      item.append(el("span", "onboard-dot-number", String(index + 1)), el("span", "onboard-dot-name"));
      bar.append(item);
    }
    top.append(bar);

    const talk = el("div", "onboard-talk");
    bubble = el("p", "onboard-bubble");
    bubble.setAttribute("aria-live", "polite");
    talk.append(ctx.body("onboard-figure"), bubble);

    body = el("div", "onboard-body");

    const foot = el("footer", "onboard-foot");
    backButton = el("button", "onboard-back");
    backButton.type = "button";
    backButton.addEventListener("click", () => go(finding ? TOPICS : step - 1));
    needLine = el("p", "onboard-need");
    nextButton = el("button", "onboard-next");
    nextButton.type = "button";
    nextButton.addEventListener("click", () => {
      // The language is kept as it leaves its step, picked or as guessed.
      if (step === LANG) {
        ctx.setLang(speaks);
        ctx.api("look/lang", { lang: speaks }).catch(() => {});
      }
      // A character shown but never chosen (a new home's Mibo) is chosen as it leaves its step.
      if (step === FIGURE && character && !character.set) picker.choose(character.chosen);
      if (step === TOPICS) startFinds();
      else if (step < ABOUT) go(step + 1);
      else finish();
    });
    skipButton = el("button", "onboard-skip");
    skipButton.type = "button";
    skipButton.addEventListener("click", skipStep);
    foot.append(backButton, el("span", "onboard-gap"), skipButton, nextButton);

    card.append(top, talk, body, needLine, foot);
    root.append(card);
    node.replaceChildren(root);
    load();
    go(LANG);
    // The screens speak the language the character will.
    if (speaks !== paI18n.lang) ctx.setLang(speaks).then(() => go(step));
  }

  // What the screens say when the language changes.
  function words() {
    t = paI18n.words("onboard");
    root.lang = paI18n.locale;
    [...bar.children].forEach((dot, i) => (dot.querySelector(".onboard-dot-name").textContent = t.steps[i]));
    backButton.textContent = t.back;
    skipButton.textContent = t.skip;
  }

  function load() {
    // All asked at once; a step whose answer is late draws itself when it comes.
    const lang = screens(speaks);
    ctx
      .api("catalog")
      .then((value) => (catalog = value.providers))
      .catch(() => (catalog = []))
      .finally(() => step === MODEL && draw());
    ctx
      .api(`feed/interests?lang=${lang}`)
      .then((value) => {
        suggested = Array.isArray(value.suggested) ? value.suggested : [];
        picked = Array.isArray(value.topics) ? [...value.topics] : [];
        pickedAtStart = [...picked];
        pickedSaved = [...picked];
      })
      .catch(() => (suggested = []))
      .finally(() => step === TOPICS && draw());
  }

  function go(index) {
    step = Math.max(0, Math.min(ABOUT, index));
    // The wait for the finds holds Next back; a step shown again, the wait skipped too, lets it go.
    finding = nextButton.hidden = nextButton.disabled = false;
    looking = null;
    words();
    [...bar.children].forEach((dot, i) => {
      dot.classList.toggle("onboard-dot-done", i < step);
      dot.classList.toggle("onboard-dot-now", i === step);
      if (i === step) dot.setAttribute("aria-current", "step");
      else dot.removeAttribute("aria-current");
    });
    // With no model there is nowhere to write on the last step: only the situation is left to look at.
    speak(step === ABOUT && !model.configured ? t.sayingNoModel : t.saying[step]);
    backButton.hidden = step === 0;
    // The language always has an answer, the guess at least: Next is the only way on.
    skipButton.hidden = step === LANG;
    nextButton.textContent = step < ABOUT ? t.next : t.finish;
    // The situation is first read when its step is first shown, while the probe may still be out.
    if (step === ABOUT && where === null && !whereReads) loadWhere();
    draw();
    body.scrollTop = 0;
  }

  function speak(text) {
    bubble.textContent = text;
    bubble.classList.remove("onboard-bubble-in");
    // Read once so the class coming back starts the animation again.
    void bubble.offsetWidth;
    bubble.classList.add("onboard-bubble-in");
  }

  // Nothing holds the next step back; a step left as it is says what that means.
  function gate() {
    const empty = (step === MODEL && !model.configured) || (step === TOPICS && !finding && !looking && !picked.length);
    needLine.textContent = empty ? t.later[step] : "";
    needLine.hidden = !empty;
  }

  function draw() {
    const panes = [languages, figures, connect, topics, about];
    body.replaceChildren((finding ? findsPane : looking ? waitPane : panes[step])());
    gate();
  }

  // ------------------------------------------------------ step 1: language --

  function languages() {
    const pane = el("div", "onboard-pane");
    const grid = el("div", "onboard-langs");
    for (const [code, name] of LANGS) {
      const button = el("button", "onboard-lang");
      button.type = "button";
      button.lang = code;
      button.setAttribute("aria-pressed", String(code === speaks));
      button.append(icon(TICK, "onboard-lang-tick"), el("span", "", name));
      button.addEventListener("click", async () => {
        speaks = code;
        await ctx.setLang(code);
        // The topics on offer differ by language: asked again.
        load();
        go(LANG);
      });
      grid.append(button);
    }
    pane.append(el("p", "onboard-hint onboard-lang-hint", t.langHint), grid);
    return pane;
  }

  // ----------------------------------------------------- step 2: character --

  // The same picker as Settings': choosing one sets its personality, name and figure at once.
  function figures() {
    const pane = el("div", "onboard-pane");
    const box = el("div", "onboard-characters");
    const seen = (value) => {
      character = value;
      if (!characterAtStart) characterAtStart = value.chosen;
    };
    picker = window.paCharacters.mount(box, ctx, {
      speaks,
      onLoad: seen,
      onChange: seen,
    });
    pane.append(box);
    return pane;
  }

  // --------------------------------------------------------- step 3: model --

  const spec = (id) => catalog?.find((entry) => entry.id === id);

  function connect() {
    const pane = el("div", "onboard-pane");
    if (catalog === null) {
      pane.append(el("div", "onboard-loading"));
      return pane;
    }
    if (!catalog.length) {
      pane.append(el("p", "onboard-error", t.errors.offline));
      return pane;
    }
    if (model.configured && !modelForm) {
      const box = el("div", "onboard-connected");
      const words = el("span", "onboard-row-words");
      const known = spec(model.provider);
      words.append(
        el("span", "onboard-row-name", known ? known.name : model.provider),
        el("span", "onboard-row-about", model.model),
      );
      const mark = el("span", "onboard-connected-mark");
      mark.append(icon(TICK, "onboard-icon"), document.createTextNode(t.connected));
      const change = el("button", "onboard-back", t.change);
      change.type = "button";
      change.addEventListener("click", () => {
        modelForm = {};
        draw();
      });
      box.append(mark, words, change);
      pane.append(box);
      return pane;
    }
    // The same chooser as Settings › Model (setup/modelpick.js), so the two never drift.
    const lang = paI18n.lang;
    if (modelPick?.lang !== lang) {
      modelPick = {
        lang,
        ui: window.paModelPick.chooser({
          api: ctx.api,
          catalog,
          state: () => (model.configured ? { configured: true, ...model } : { configured: false }),
          // The character as chosen a step ago; a new home that skipped it is Mibo.
          who: () => ({
            lang: speaks,
            character: character?.chosen || "mibo",
            ...(character?.set && character.name ? { name: character.name } : {}),
          }),
          done: (state) => {
            model = { configured: true, provider: state.provider, model: state.model, baseUrl: state.baseUrl, name: state.name || "" };
            modelForm = null;
            go(TOPICS);
          },
          cancel: () => {
            modelForm = null;
            draw();
          },
        }),
      };
      modelPick.ui.open("");
    }
    pane.append(modelPick.ui.node);
    return pane;
  }

  // ----------------------------------------------------- step 4: interests --

  function topics() {
    const pane = el("div", "onboard-pane");
    const head = el("div", "onboard-pane-head");
    const count = el("span", "onboard-count", paI18n.t("onboard.chosenTopics", { count: picked.length }));
    head.append(count);
    const chips = el("div", "onboard-chips");
    const names = suggested.map((topic) => topic.name);
    // What the person typed earlier is shown with the offered ones, already picked.
    const all = [...names, ...picked.filter((name) => !names.includes(name))];
    const refresh = () => {
      count.textContent = paI18n.t("onboard.chosenTopics", { count: picked.length });
      gate();
    };
    for (const name of all) chips.append(chip(name, refresh));

    const form = el("form", "onboard-add");
    const field = el("input", "onboard-field");
    field.type = "text";
    field.maxLength = 40;
    field.placeholder = t.addTopic;
    field.setAttribute("aria-label", t.addTopic);
    const add = el("button", "onboard-add-button");
    add.type = "submit";
    add.append(icon(PLUS, "onboard-icon"), document.createTextNode(t.add));
    form.append(field, add);
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      const name = field.value.split(/\s+/).filter(Boolean).join(" ");
      field.value = "";
      if (!name) return;
      const known = [...chips.children].find((node) => node.dataset.name.toLowerCase() === name.toLowerCase());
      if (known) {
        if (known.getAttribute("aria-pressed") !== "true") known.click();
        return;
      }
      picked.push(name);
      const fresh = chip(name, refresh);
      fresh.classList.add("onboard-chip-new");
      chips.append(fresh);
      refresh();
    });
    pane.append(head, chips, form, el("p", "onboard-quiet", t.connectLater));
    return pane;
  }

  // ------------------------------------------- step 4, then: a few finds --

  // The topics are saved (which sends the sources out for them at once), then the finds are asked for
  // (GET /api/feed/first, which waits for that round on a fresh install, feedpage.FIRST_WAIT_S at most); the wait
  // says so, and Skip leaves it. With none even then the step goes straight on.
  async function startFinds() {
    const mine = {};
    looking = mine;
    nextButton.disabled = true;
    speak(t.findsLooking);
    draw();
    if (picked.join("\n") !== pickedSaved.join("\n")) {
      await ctx
        .api("feed/interests", { topics: picked, lang: screens(speaks) })
        .then(() => (pickedSaved = [...picked]))
        .catch(() => {});
    }
    let items = [];
    try {
      items = (await ctx.api("feed/first")).items || [];
    } catch {
      // Nothing to show: the step goes on.
    }
    if (looking !== mine) return;
    looking = null;
    nextButton.disabled = false;
    if (!items.length) return go(ABOUT);
    finds = items;
    findAt = 0;
    finding = nextButton.hidden = true;
    speak(t.findsSaying);
    draw();
  }

  // Each answer is kept as a like or a skip from the first run (surface "first").
  const reactFind = (find, action) =>
    ctx.api("feed/react", { id: find.id, action, surface: "first", rank: findAt }).catch(() => {});

  function answer(action) {
    reactFind(finds[findAt], action);
    findAt += 1;
    if (findAt < finds.length) draw();
    else go(ABOUT);
  }

  // While the finds are looked for: what it waits for and how long, over a card's outline.
  function waitPane() {
    const pane = el("div", "onboard-pane");
    pane.setAttribute("aria-busy", "true");
    const head = el("div", "onboard-pane-head");
    head.append(el("p", "onboard-hint", t.findsWait));
    pane.append(head, el("div", "onboard-loading"));
    return pane;
  }

  function findsPane() {
    const find = finds[findAt];
    const pane = el("div", "onboard-pane");
    const head = el("div", "onboard-pane-head");
    head.append(el("span", "onboard-count", `${findAt + 1} / ${finds.length}`));
    const card = el("article", "onboard-find");
    if (findPicture) URL.revokeObjectURL(findPicture);
    findPicture = "";
    if (find.picture) {
      const media = el("div", "onboard-find-media");
      ctx
        .picture(find.picture)
        .then((url) => {
          findPicture = url;
          media.append(Object.assign(el("img"), { src: url, alt: "" }));
        })
        .catch(() => media.remove());
      card.append(media);
    }
    const site = el("p", "onboard-find-site", find.site.replace(/^www\./, ""));
    if (find.kind === "video") site.append(el("span", "onboard-find-kind", t.video));
    card.append(site, el("h3", "onboard-find-title", find.title));
    const said = find.words || find.text;
    if (said) card.append(el("p", "onboard-find-text", said));
    const actions = el("div", "onboard-find-actions");
    const no = el("button", "onboard-back onboard-find-no", t.notWant);
    const yes = el("button", "onboard-add-button onboard-find-yes", t.want);
    no.type = yes.type = "button";
    no.addEventListener("click", () => answer("skip"));
    yes.addEventListener("click", () => answer("like"));
    actions.append(no, yes);
    pane.append(head, card, actions);
    reactFind(find, "seen");
    return pane;
  }

  function chip(name, changed) {
    const node = el("button", "onboard-chip");
    node.type = "button";
    node.dataset.name = name;
    node.append(icon(TICK, "onboard-chip-tick"), el("span", "", name));
    const paint = () => node.setAttribute("aria-pressed", String(picked.includes(name)));
    paint();
    node.addEventListener("click", () => {
      picked = picked.includes(name) ? picked.filter((p) => p !== name) : [...picked, name];
      paint();
      changed();
    });
    return node;
  }

  // --------------------------------------------------------- step 5: about --

  // The character's name as it is now, for the words that name it.
  const who = () => model.name || character?.name || t.it;

  function about() {
    const pane = el("div", "onboard-pane");
    whereBox = el("div", "onboard-where-part");
    paintWhere();
    tellBox = el("div", "onboard-tell-part");
    paintTell();
    pane.append(whereBox, tellBox);
    return pane;
  }

  // Only this part changes as the words are told, so the rest of the step stays still.
  function paintTell() {
    if (!model.configured) tellBox.replaceChildren(el("p", "onboard-quiet", t.tellLater));
    else tellBox.replaceChildren(told && told !== "waiting" ? toldBox() : tellForm());
  }

  // GET /api/situation, read again while the first start's probe is still out.
  function loadWhere() {
    whereReads += 1;
    ctx
      .api("situation")
      .then((value) => {
        where = value;
        if (!value.probed && whereReads < PROBE_READS) whereTimer = setTimeout(loadWhere, PROBE_WAIT_MS);
      })
      // A later read that fails keeps the line already shown, and reads no more.
      .catch(() => {
        if (where === null) where = false;
      })
      .finally(() => step === ABOUT && paintWhere());
  }

  // "Bilibili ✓ · YouTube ✗ · reads 中文", and the way to correct it. No place is shown.
  function paintWhere() {
    whereBox.hidden = where === false;
    const hint = el("p", "onboard-hint onboard-where-hint", t.whereHint);
    if (!where) {
      whereBox.replaceChildren(hint, el("div", "onboard-loading onboard-where-loading"));
      return;
    }
    const f = where.factors;
    const line = el("p", "onboard-where-line");
    const sep = () => el("span", "onboard-where-sep", "·");
    for (const [host, name] of LINE_PLATFORMS) {
      const state = where.platforms[host] || "unknown";
      const bit = el("span", `onboard-where-site onboard-where-${state}`);
      if (line.childElementCount) bit.append(sep());
      bit.append(el("span", "", paI18n.t(`onboard.platforms.${name}`)),
        icon(state === "up" ? TICK : state === "down" ? CROSS : ASK, "onboard-icon"));
      bit.title = t.platform[state];
      bit.append(el("span", "onboard-sr", t.platform[state]));
      line.append(bit);
    }
    if (f.readable.value.length) {
      const reads = el("span", "onboard-where-site");
      reads.append(sep(), el("span", "", paI18n.t("onboard.reads", { names: f.readable.value.map((c) => AUTONYMS[c] || c).join(t.listSep) })));
      line.append(reads);
    }
    const fix = el("button", "onboard-link onboard-where-fix", t.fixWhere);
    fix.type = "button";
    // Settings opens on its sites and languages once the first run is done; what was picked here is kept.
    fix.addEventListener("click", () => {
      fix.disabled = true;
      ctx.go("setup/where");
      finish();
    });
    const card = el("div", "onboard-where");
    card.append(line, fix);
    whereBox.replaceChildren(hint, card);
  }

  // A few lines in the person's own words: POST /api/profile/answer, one model call.
  function tellForm() {
    const form = el("form", "onboard-tell");
    const label = el("label", "onboard-form-label", paI18n.t("onboard.tellLabel", { name: who() }));
    const field = el("textarea", "onboard-field onboard-tell-field");
    field.id = label.htmlFor = "onboard-tell";
    field.rows = 4;
    field.maxLength = TELL_MAX;
    field.placeholder = t.tellPlaceholder;
    field.value = draft;
    const count = el("span", "onboard-tell-count");
    const error = el("p", "onboard-error", tellError);
    error.hidden = !tellError;
    const button = el("button", "onboard-add-button onboard-tell-button");
    button.type = "submit";
    const waiting = told === "waiting";
    field.readOnly = button.disabled = waiting;
    form.setAttribute("aria-busy", String(waiting));
    if (waiting) button.append(el("span", "onboard-spin"), document.createTextNode(paI18n.t("onboard.telling", { name: who() })));
    else button.textContent = paI18n.t("onboard.tell", { name: who() });
    const fit = () => {
      count.textContent = `${field.value.length} / ${TELL_MAX}`;
      if (!waiting) button.disabled = !field.value.trim();
    };
    field.addEventListener("input", () => {
      draft = field.value;
      tellError = "";
      error.hidden = true;
      fit();
    });
    fit();
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      told = "waiting";
      tellError = "";
      paintTell();
      try {
        const answer = await ctx.api("profile/answer", { text: draft.trim() });
        told = { rewritten: answer.rewritten };
        sent = draft;
        if (step === ABOUT) speak(t.heard);
      } catch (failure) {
        told = null;
        tellError = say(failure instanceof TypeError ? new Error("offline") : failure);
      }
      if (step === ABOUT) paintTell();
    });
    const foot = el("div", "onboard-tell-foot");
    foot.append(count, button);
    form.append(label, field, error, foot);
    return form;
  }

  // Told: the words as kept, and a way to change them.
  function toldBox() {
    const box = el("div", "onboard-connected onboard-told");
    const mark = el("span", "onboard-connected-mark");
    mark.append(icon(TICK, "onboard-icon"), document.createTextNode(t.told));
    const words = el("span", "onboard-row-words");
    words.append(el("span", "onboard-told-text", sent));
    if (!told.rewritten) words.append(el("span", "onboard-row-about", t.toldLater));
    const change = el("button", "onboard-back", t.tellAgain);
    change.type = "button";
    change.addEventListener("click", () => {
      told = null;
      paintTell();
      tellBox.querySelector(".onboard-tell-field").focus();
    });
    box.append(mark, words, change);
    return box;
  }

  // ---------------------------------------------------------------- finish --

  // Skipping a step leaves it as it was when the tour opened, then goes on.
  function skipStep() {
    if (step === FIGURE && character?.set && character.chosen !== characterAtStart) picker.choose(characterAtStart);
    // The round of finds, or the wait for it, is skipped whole; the topics go back to as they were.
    if (step === TOPICS && (finding || looking)) return go(ABOUT);
    if (step === TOPICS) {
      picked = [...pickedAtStart];
      return startFinds();
    }
    // Words written but not told are dropped.
    if (step === ABOUT) draft = sent;
    if (step < ABOUT) go(step + 1);
    else finish();
  }

  async function finish() {
    nextButton.disabled = backButton.disabled = skipButton.disabled = true;
    clearTimeout(whereTimer);
    bubble.textContent = t.bye;
    const said = new Promise((resolve) => setTimeout(resolve, BYE_MS));
    const lang = screens(speaks);
    const saves = [
      picked.join("\n") !== pickedSaved.join("\n") ? ctx.api("feed/interests", { topics: picked, lang }) : null,
      ctx.api("look/toured", {}),
    ];
    // Words written but not told yet go along without being waited for: the app comes in meanwhile.
    if (model.configured && told !== "waiting" && draft.trim() && draft !== sent)
      ctx.api("profile/answer", { text: draft }).catch(() => {});
    await Promise.allSettled(saves);
    await ctx.api("sources/refresh", {}).catch(() => {});
    await said;
    done();
  }

  // The first run lasts until it has been walked or skipped once.
  async function needed(context) {
    try {
      return !(await context.api("look")).toured;
    } catch {
      return false;
    }
  }

  window.paOnboard = { needed, mount };
})();
