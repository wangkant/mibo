// The first run, in five steps walked in order: the language, the character, the
// model it thinks with, what the person cares about, and a last look at them: where
// they seem to be (GET /api/situation) and a few lines in their own words.
// Where it looks is not asked: it reads the public internet and learns from what the person opens.
// Nothing has to be chosen: beside Next, a small button skips the step as it was,
// and everything can be set later in Settings.
// The shell shows it instead of the app while needed() says so.
(() => {
  "use strict";

  // The languages the character speaks, by their own names. The screens are in
  // Chinese or English for now; the others are spoken by the character only.
  const LANGS = [
    ["zh", "简体中文"],
    ["en", "English"],
    ["zh-TW", "繁體中文"],
    ["ja", "日本語"],
    ["ko", "한국어"],
    ["es", "Español"],
    ["fr", "Français"],
    ["de", "Deutsch"],
    ["pt-BR", "Português (Brasil)"],
    ["ru", "Русский"],
  ];
  const STEP_COUNT = 5;
  const [LANG, FIGURE, MODEL, TOPICS, ABOUT] = [0, 1, 2, 3, 4];
  // The figures that are a written character of their own; the others take this one's ways.
  const WRITTEN = ["pico", "deepseek", "chatgpt", "claude"];
  // The app's own characters, not drawn after anyone's.
  const ORIGINAL = ["pico", "sprout"];
  const PLAIN_CHARACTER = "warm-listener";

  const WORDS = {
    zh: {
      steps: ["语言", "角色", "模型", "喜好", "关于你"],
      skip: "跳过",
      back: "上一步",
      next: "下一步",
      finish: "完成",
      saying: [
        "你好！先选一个语言吧，我之后都用它和你说话。",
        "这是我们几个。选一个陪着你的，之后在设置里也能换。",
        "我得接上一个模型才能陪你聊天。用你自己的 key，只存在这台电脑上。",
        "告诉我你平时爱看什么吧，我出门找东西的时候会照着挑。",
        "最后，说说你自己吧。不想写也没关系，直接出发就行。",
      ],
      sayingNoModel: "最后看一眼：我是这么理解你这边的，不对就改一下。",
      bye: "好嘞，我这就出门找找看！",
      langHint: "角色会用这个语言和你说话，也会优先找这个语言的内容。",
      langScreens: (name) => `界面目前只有简体中文和英文，将以简体中文显示；角色会用${name}和你说话。`,
      figureHint: "选择一个角色。",
      original: "原创",
      later: {
        [MODEL]: "可以稍后在设置中连接。连接前，角色找到的内容仍会发到对话中，但无法聊天。",
        [TOPICS]: "可以不选，角色会从你打开的内容中学习。",
      },
      service: "模型服务",
      key: "API 密钥",
      keyPlaceholder: "粘贴你的密钥",
      getKey: "获取密钥",
      base: "服务地址",
      basePlaceholder: "https://…/v1",
      model: "模型",
      connect: "连接",
      connecting: "正在连接…",
      connected: "已连接",
      change: "更换",
      noKey: "此服务在本机运行，无需密钥。",
      freeNote: "OpenRouter 提供免费模型：注册后即可免费获取密钥，每天约可使用 50 次。",
      keyStays: "密钥只保存在本机，不会发送给我们。",
      topicsHint: "选择你感兴趣的主题，数量不限。",
      addTopic: "添加其他主题，如摄影、咖啡",
      add: "添加",
      chosenTopics: (n) => (n ? `已选 ${n} 个` : "未选择"),
      connectLater: "角色会浏览公开网站，并从你打开的内容中学习。如需读取邮箱或 Discord 消息，可稍后在设置的「连接」中添加。",
      whereHint: "角色据此决定浏览哪些网站、查找哪些语言的内容。",
      reads: (names) => `阅读 ${names}`,
      listSep: "、",
      platform: { up: "可连接", down: "无法连接", unknown: "未检查" },
      fixWhere: "修改",
      tellLabel: (name) => `告诉${name}你喜欢什么、最近在忙什么`,
      tellPlaceholder: "比如：最近在学做饭，爱看科幻和纪录片，周末常去爬山。",
      tell: (name) => `告诉${name}`,
      telling: (name) => `${name}正在阅读…`,
      told: "已记录",
      toldLater: "已保存，将在下次整理时使用。",
      tellAgain: "修改",
      heard: "记住啦，谢谢你告诉我！",
      tellLater: "连接模型后，可在设置的「它对你的了解」中填写。",
      it: "它",
      errors: {
        profile_invalid: "请输入 1 到 1000 个字。",
        key_required: "请输入密钥。",
        key_again: "已更换服务，请输入该服务的密钥。",
        key_malformed: "密钥格式不正确。请确认只粘贴了密钥本身。",
        key_rejected: "服务未接受该密钥。请检查是否复制完整、是否仍然有效。",
        model_limited: "该服务当前限流。请稍后重试，或更换模型。",
        model_unreachable: "无法连接到该服务或模型。请检查地址、模型名称和网络。",
        model_required: "请输入模型名称。",
        invalid_provider: "请从列表中选择模型服务。",
        busy: "上一步仍在进行。请稍后重试。",
        offline: "无法连接到 personagent。请确认它仍在运行。",
        generic: "操作失败。请重试。",
      },
    },
    en: {
      steps: ["Language", "Character", "Model", "Interests", "You"],
      skip: "Skip this",
      back: "Back",
      next: "Next",
      finish: "Done, off you go",
      saying: [
        "Hi! Pick a language first. It's the one I'll talk to you in.",
        "Here we are. Pick the one who keeps you company; you can switch later in settings.",
        "I need a model to chat with. It uses your own key, kept on this computer only.",
        "Tell me what you like to read and watch, and I'll pick with that in mind.",
        "Last thing: tell me a little about you. Or don't, and we'll just head off.",
      ],
      sayingNoModel: "One last look: this is how I read where you are. Change it if it's wrong.",
      bye: "Right, I'm off to have a look!",
      langHint: "The character talks to you in this language and looks for things written in it first.",
      langScreens: (name) => `The screens are in Chinese or English for now, so they show in English; the character talks to you in ${name}.`,
      figureHint: "Tap one to pick it.",
      original: "Original",
      later: {
        [MODEL]: "You can leave this for now: what I find still arrives in the chat, and talking waits until a model is connected in Settings.",
        [TOPICS]: "Fine to leave empty; I'll learn from what you open.",
      },
      service: "Model service",
      key: "API key",
      keyPlaceholder: "Paste your key",
      getKey: "Get a key",
      base: "Service address",
      basePlaceholder: "https://…/v1",
      model: "Model",
      connect: "Connect",
      connecting: "Trying to connect…",
      connected: "Connected",
      change: "Change",
      noKey: "This service runs on your computer and needs no key.",
      freeNote: "OpenRouter has free models: sign up and you get a key at no cost, good for about 50 requests a day.",
      keyStays: "The key is kept on this computer only and never sent to us.",
      topicsHint: "Tap what you're into. As many or as few as you like.",
      addTopic: "Add your own, like photography or coffee",
      add: "Add",
      chosenTopics: (n) => (n ? `${n} picked` : "None yet"),
      connectLater: "I'll wander the public web on my own and learn from what you open. Want me to read your mail or Discord too? Connect them later under Settings › Connect.",
      whereHint: "I go by this to choose which sites to look on and which languages to bring.",
      reads: (names) => `reads ${names}`,
      listSep: ", ",
      platform: { up: "reachable", down: "unreachable", unknown: "not checked yet" },
      fixWhere: "Not right? Change it",
      tellLabel: (name) => `Tell ${name} what you like and what you're busy with lately`,
      tellPlaceholder: "For example: learning to cook lately, into sci-fi and documentaries, hiking most weekends.",
      tell: (name) => `Tell ${name}`,
      telling: (name) => `${name} is reading…`,
      told: "Noted",
      toldLater: "Kept for now; it gets used the next time I go over what I know.",
      tellAgain: "Edit",
      heard: "Got it, thanks for telling me!",
      tellLater: "Once a model is connected, you can tell it under Settings › What it knows about you.",
      it: "it",
      errors: {
        profile_invalid: "Write between 1 and 1000 characters.",
        key_required: "Enter a key.",
        key_again: "A new service needs its own key.",
        key_malformed: "That key does not look right. Paste the key alone.",
        key_rejected: "The service did not accept that key. Check it was copied whole and is still valid.",
        model_limited: "The service is limiting requests right now. Try again shortly, or pick another model.",
        model_unreachable: "The service or model cannot be reached. Check the address, the model name and the network.",
        model_required: "Enter a model name.",
        invalid_provider: "Choose a model service from the list.",
        busy: "The last step is still running. Try again in a moment.",
        offline: "The app itself cannot be reached. Check it is still open.",
        generic: "That did not work. Try once more.",
      },
    },
  };
  // How long the goodbye stays in the bubble before the app comes in.
  const BYE_MS = 900;
  // The first start's reachability probe takes about this long: the situation is read again after it.
  const PROBE_WAIT_MS = 6000;
  const PROBE_READS = 3;
  const TELL_MAX = 1000;
  // Languages in their own words, as Settings shows them.
  const AUTONYMS = { zh: "中文", en: "English", ja: "日本語", ko: "한국어", ru: "Русский", pt: "Português", es: "Español",
                     fr: "Français", de: "Deutsch" };
  const LINE_PLATFORMS = [["bilibili.com", ["Bilibili", "哔哩哔哩"]], ["youtube.com", ["YouTube", "YouTube"]]];
  const SVG = "http://www.w3.org/2000/svg";

  let ctx, t, done;
  let root, bubble, bar, body, backButton, nextButton, needLine, skipButton;
  let step = 0;
  // Step one: the language the character speaks.
  let speaks = "";
  // Step two: the figure picked, and the names the app gives the figures.
  let figure = "";
  let figureAtStart = "";
  let figureNames = {};
  // Step three: the services offered, and the model as saved.
  let catalog = null;
  let model = { configured: false, provider: "", model: "", name: "" };
  let modelForm = null;
  // Step four: the topics offered and the ones picked (in the order picked).
  let suggested = [];
  let picked = [];
  let pickedAtStart = [];
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
  const OUT = "M14 5h5v5M19 5l-8 8M10 7H6a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h10a1 1 0 0 0 1-1v-4";
  const CROSS = "M7 7l10 10M17 7L7 17";
  const ASK = "M9.1 9a3 3 0 0 1 5.8 1c0 2-2.9 2.6-2.9 4M12 18h.01";

  const say = (error) => t.errors[error?.message] || t.errors.generic;
  // The screens' language for a spoken one.
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
    t = WORDS[screens(speaks)];
    model = {
      configured: Boolean(ctx.state?.configured),
      provider: ctx.state?.provider || "",
      model: ctx.state?.model || "",
      name: ctx.state?.name || "",
    };
    // The figure as it is now stays unless another is picked.
    figure = figureAtStart = ctx.figure;
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
    backButton.addEventListener("click", () => go(step - 1));
    needLine = el("p", "onboard-need");
    nextButton = el("button", "onboard-next");
    nextButton.type = "button";
    nextButton.addEventListener("click", () => {
      // The language is kept as it leaves its step, picked or as guessed.
      if (step === LANG) {
        ctx.setLang(speaks);
        ctx.api("look/lang", { lang: speaks }).catch(() => {});
      }
      if (step < ABOUT) go(step + 1);
      else finish();
    });
    skipButton =el("button", "onboard-skip");
    skipButton.type = "button";
    skipButton.addEventListener("click", skipStep);
    foot.append(backButton, el("span", "onboard-gap"), skipButton, nextButton);

    card.append(top, talk, body, needLine, foot);
    root.append(card);
    node.replaceChildren(root);
    load();
    go(LANG);
  }

  // What the screens say when the language changes.
  function words() {
    t = WORDS[screens(speaks)];
    root.lang = screens(speaks) === "zh" ? "zh-CN" : "en";
    [...bar.children].forEach((dot, i) => (dot.querySelector(".onboard-dot-name").textContent = t.steps[i]));
    backButton.textContent = t.back;
    skipButton.textContent = t.skip;
  }

  function load() {
    // All asked at once; a step whose answer is late draws itself when it comes.
    const lang = screens(speaks);
    ctx
      .api(`look?lang=${speaks}`)
      .then((value) => {
        figureNames = Object.fromEntries(value.figures.map((entry) => [entry.key, entry.name]));
      })
      .catch(() => {})
      .finally(() => step === FIGURE && draw());
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
      })
      .catch(() => (suggested = []))
      .finally(() => step === TOPICS && draw());
  }

  function go(index) {
    step = Math.max(0, Math.min(ABOUT, index));
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
    const empty = (step === MODEL && !model.configured) || (step === TOPICS && !picked.length);
    needLine.textContent = empty ? t.later[step] : "";
    needLine.hidden = !empty;
  }

  function draw() {
    const panes = [languages, figures, connect, topics, about];
    body.replaceChildren(panes[step]());
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
      button.addEventListener("click", () => {
        speaks = code;
        ctx.setLang(code);
        // The topics on offer differ by language: asked again.
        load();
        go(LANG);
      });
      grid.append(button);
    }
    const name = LANGS.find(([code]) => code === speaks)[1];
    pane.append(el("p", "onboard-hint onboard-lang-hint", t.langHint), grid);
    if (!["zh", "en"].includes(speaks)) pane.append(el("p", "onboard-note", t.langScreens(name)));
    return pane;
  }

  // ----------------------------------------------------- step 2: character --

  function figures() {
    const pane = el("div", "onboard-pane");
    const grid = el("div", "onboard-figures");
    for (const key of ctx.figures) {
      const card = el("button", "onboard-pick");
      card.type = "button";
      card.setAttribute("aria-pressed", String(key === figure));
      const stage = el("span", "onboard-pick-stage");
      stage.append(ctx.bodyOf(key, "onboard-pick-figure"));
      const label = el("span", "onboard-pick-name", figureNames[key] || key);
      card.append(stage, label);
      if (ORIGINAL.includes(key)) card.append(el("span", "onboard-pick-tag", t.original));
      card.append(icon(TICK, "onboard-pick-tick"));
      card.addEventListener("click", () => {
        figure = key;
        ctx.setFigure(key);
        // The pet takes it now; the character's own words come with the model, next.
        ctx.api("look", { figure: key, lang: speaks }).catch(() => {});
        for (const other of grid.children) other.setAttribute("aria-pressed", String(other === card));
        gate();
      });
      grid.append(card);
    }
    pane.append(el("p", "onboard-hint", t.figureHint), grid);
    return pane;
  }

  // --------------------------------------------------------- step 3: model --

  const spec = (id) => catalog?.find((entry) => entry.id === id);
  const serviceName = (entry) => entry.name[screens(speaks) === "zh" ? 1 : 0];

  function connect() {
    const pane = el("div", "onboard-pane");
    if (catalog === null) {
      pane.append(el("div", "onboard-loading"));
      return pane;
    }
    if (model.configured && !modelForm) {
      const box = el("div", "onboard-connected");
      const words = el("span", "onboard-row-words");
      const known = spec(model.provider);
      words.append(
        el("span", "onboard-row-name", known ? serviceName(known) : model.provider),
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
    const form = el("form", "onboard-form");
    const service = el("select", "onboard-field onboard-select");
    for (const entry of catalog) service.append(new Option(serviceName(entry), entry.id));
    service.value = modelForm?.provider || (spec(model.provider) ? model.provider : catalog[0]?.id || "");
    const keyField = el("input", "onboard-field");
    keyField.type = "password";
    keyField.autocomplete = "off";
    keyField.spellcheck = false;
    keyField.placeholder = t.keyPlaceholder;
    const getKey = el("a", "onboard-link");
    getKey.target = "_blank";
    getKey.rel = "noopener noreferrer";
    getKey.append(document.createTextNode(t.getKey), icon(OUT, "onboard-icon"));
    const base = el("input", "onboard-field");
    base.type = "url";
    base.spellcheck = false;
    base.placeholder = t.basePlaceholder;
    const name = el("input", "onboard-field");
    name.type = "text";
    name.spellcheck = false;
    const note = el("p", "onboard-hint");
    const error = el("p", "onboard-error");
    error.hidden = true;
    const button = el("button", "onboard-add-button onboard-connect", t.connect);
    button.type = "submit";

    const row = (label, field, extra) => {
      const line = el("label", "onboard-form-row");
      const head = el("span", "onboard-form-label", label);
      line.append(head, field);
      if (extra) head.append(extra);
      return line;
    };
    const keyRow = row(t.key, keyField, getKey);
    const baseRow = row(t.base, base);
    form.append(row(t.service, service), keyRow, baseRow, row(t.model, name), note, error, button,
      el("p", "onboard-quiet", t.keyStays));

    const fit = () => {
      const entry = spec(service.value);
      keyRow.hidden = entry.id === "ollama";
      baseRow.hidden = entry.id !== "other";
      getKey.hidden = !entry.keyUrl;
      getKey.href = entry.keyUrl || "#";
      name.value = entry.model || "";
      name.placeholder = entry.model || "model-name";
      note.textContent = entry.id === "openrouter" ? t.freeNote : entry.id === "ollama" ? t.noKey : "";
      note.hidden = !note.textContent;
      error.hidden = true;
    };
    service.addEventListener("change", fit);
    fit();

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      error.hidden = true;
      button.disabled = true;
      button.textContent = t.connecting;
      const entry = spec(service.value);
      const written = WRITTEN.includes(figure);
      try {
        const state = await ctx.api("config", {
          provider: entry.id,
          apiKey: keyField.value.trim(),
          baseUrl: entry.id === "other" ? base.value.trim() : entry.baseUrl,
          model: name.value.trim(),
          lang: speaks,
          character: written ? figure : PLAIN_CHARACTER,
          avatar: written ? figure : "",
          ...(written ? {} : { name: figureNames[figure] || "" }),
        });
        model = { configured: true, provider: state.provider, model: state.model, name: state.name || "" };
        modelForm = null;
        keyField.value = "";
        go(TOPICS);
      } catch (failure) {
        error.textContent = say(failure instanceof TypeError ? new Error("offline") : failure);
        error.hidden = false;
      } finally {
        button.disabled = false;
        button.textContent = t.connect;
      }
    });
    pane.append(form);
    setTimeout(() => (keyRow.hidden ? name : keyField).focus(), 0);
    return pane;
  }

  // ----------------------------------------------------- step 4: interests --

  function topics() {
    const pane = el("div", "onboard-pane");
    const head = el("div", "onboard-pane-head");
    const count = el("span", "onboard-count", t.chosenTopics(picked.length));
    head.append(el("p", "onboard-hint", t.topicsHint), count);
    const chips = el("div", "onboard-chips");
    const names = suggested.map((topic) => topic.name);
    // What the person typed earlier is shown with the offered ones, already picked.
    const all = [...names, ...picked.filter((name) => !names.includes(name))];
    const refresh = () => {
      count.textContent = t.chosenTopics(picked.length);
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
  const who = () => model.name || figureNames[figure] || t.it;

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
    for (const [host, names] of LINE_PLATFORMS) {
      const state = where.platforms[host] || "unknown";
      const bit = el("span", `onboard-where-site onboard-where-${state}`);
      if (line.childElementCount) bit.append(sep());
      bit.append(el("span", "", names[screens(speaks) === "zh" ? 1 : 0]),
        icon(state === "up" ? TICK : state === "down" ? CROSS : ASK, "onboard-icon"));
      bit.title = t.platform[state];
      bit.append(el("span", "onboard-sr", t.platform[state]));
      line.append(bit);
    }
    if (f.readable.value.length) {
      const reads = el("span", "onboard-where-site");
      reads.append(sep(), el("span", "", t.reads(f.readable.value.map((c) => AUTONYMS[c] || c).join(t.listSep))));
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
    const label = el("label", "onboard-form-label", t.tellLabel(who()));
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
    if (waiting) button.append(el("span", "onboard-spin"), document.createTextNode(t.telling(who())));
    else button.textContent = t.tell(who());
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
    if (step === FIGURE && figure !== figureAtStart) {
      figure = figureAtStart;
      ctx.setFigure(figure);
      ctx.api("look", { figure, lang: speaks }).catch(() => {});
    }
    if (step === TOPICS) picked = [...pickedAtStart];
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
      picked.join("\n") !== pickedAtStart.join("\n") ? ctx.api("feed/interests", { topics: picked, lang }) : null,
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
