"use strict";
// Settings › Recommendations: how often and when (the pace and quiet hours pacing.py reads), the person's taste
// (GET/POST /api/profile/taste) as chips for the topics and the platforms they follow, the ranking's memory of
// what they did and said folded under them, a reset, and the week in numbers (GET /api/feed/numbers). Topics
// and platforms are kept with POST /api/feed/interests, as the first run does, and so is the person's yes on the
// notice the first platform read only signed in brings: its own feed read there (feed.agreed).
(() => {
  const PACES = ["less", "normal", "more"];
  const QUIET_DEFAULT = { from: "22:00", to: "08:00" };
  const TOPIC_LEN = 40;
  // The platforms shown before "more": the list comes in the order a reader would look for them.
  const PLATFORMS_SHOWN = 12;

  window.paSetup.part("recs", (kit) => {
    const { el } = kit;
    const t = kit.words("setup_recs");
    const ctx = kit.ctx;
    let view = null;
    let posting = false;
    let moreShown = false;
    // The notice on reading a platform's own feed, open under the platforms.
    let asking = false;
    const node = kit.section("recs");
    const error = kit.errorLine();

    // ---- How often and when.
    const paceCard = kit.card();
    paceCard.classList.add("setup-options");
    const pace = kit.choices(t.paceName, PACES.map((key) => [key, t.pace[key]]), (key) => change({ pace: key }));
    const paceRow = kit.optionRow(t.paceName, "", pace.group);
    kit.item("pace", paceRow.row);
    const quiet = kit.switchRow("recs-quiet", t.quietName, "", (box) =>
      change({ quiet_hours: box.checked ? view.quiet_hours || QUIET_DEFAULT : null }));
    const hours = el("div", "setup-recs-hours");
    const from = clock(t.quietFrom);
    const to = clock(t.quietTo);
    hours.append(from, el("span", "setup-recs-dash", "–"), to);
    quiet.row.append(hours);
    paceCard.append(paceRow.row, quiet.row);

    // ---- Preferences: topics and platforms as chips, what was learned folded under them.
    const tasteCard = kit.item("taste", kit.card(t.tasteTitle));
    const topicChips = el("div", "setup-chips");
    const typed = kit.input("setup-word-input");
    typed.placeholder = t.addTopic;
    typed.maxLength = TOPIC_LEN;
    typed.setAttribute("aria-label", t.addTopic);
    typed.addEventListener("keydown", (event) => {
      const name = typed.value.trim().replace(/\s+/g, " ");
      if (event.key !== "Enter" || event.isComposing || !name) return;
      event.preventDefault();
      addTopic(name).then(() => (typed.value = ""));
    });
    const platformChips = el("div", "setup-chips");
    // A chosen platform that is read once the person is signed in says so, with the way to Connections.
    const note = el("div", "setup-recs-note");
    note.append(el("span", "setup-help", t.platformNote), kit.button("setup-button-link", t.platformGo, () => ctx.go("setup/connect")));
    const notice = feedNotice();
    const remembered = kit.fold("");
    const rememberedName = remembered.summary.lastChild;
    const memory = el("div", "setup-words");
    const memoryNone = el("p", "setup-help", t.rememberedNone);
    const reset = kit.button("setup-recs-reset", t.reset, askReset);
    remembered.body.append(memory, memoryNone, reset);
    const rememberedBlock = el("div", "setup-recs-block");
    rememberedBlock.append(remembered.node);
    tasteCard.append(block(t.topics, topicChips), kit.item("platforms", block(t.platforms, platformChips, note, notice.node)),
      rememberedBlock);

    // ---- The week. Nothing shows before the first view has come.
    const week = el("p", "setup-help setup-recs-week");
    paceCard.hidden = tasteCard.hidden = true;
    node.append(error, paceCard, tasteCard, week);

    function clock(label) {
      const input = el("input", "setup-input setup-recs-time");
      input.type = "time";
      input.setAttribute("aria-label", label);
      input.addEventListener("change", () => {
        if (!from.value || !to.value || from.value === to.value) return;
        change({ quiet_hours: { from: from.value, to: to.value } });
      });
      return input;
    }
    function block(title, ...parts) {
      const box = el("div", "setup-recs-block");
      box.append(el("p", "setup-option-name", title), ...parts);
      return box;
    }
    // A chip that is on or off, with a tick while on; a platform read only once signed in carries a lock.
    function chip(text, on, toggle, locked = false) {
      const button = el("button", "setup-chip");
      button.type = "button";
      button.setAttribute("aria-pressed", String(on));
      button.disabled = posting;
      button.append(kit.icon("check", "setup-icon setup-chip-tick"), el("span", "", text));
      if (locked) {
        button.title = t.platformLocked;
        button.append(kit.icon("lock", "setup-icon setup-chip-lock"));
      }
      button.addEventListener("click", toggle);
      return button;
    }
    // What reading a platform's own feed does, its risk and how to stop it, with the person's answer: a yes is kept
    // once, a no leaves the pick a preference until the next one. It names the picked platforms it covers.
    function feedNotice() {
      const words = t.feedNotice;
      const node = el("div", "setup-recs-feed");
      node.setAttribute("role", "group");
      node.setAttribute("aria-label", words.title);
      const actions = el("div", "setup-recs-feed-actions");
      const no = kit.button("setup-button-ghost setup-button-sm", words.decline, () => {
        asking = false;
        render();
      });
      const yes = kit.button("setup-button-primary setup-button-sm", words.agree, () =>
        choose({ topics: view.topics.map((row) => row.name), agree: true }));
      actions.append(no, yes);
      const names = el("p", "setup-help setup-recs-feed-names");
      node.append(el("p", "setup-option-name", words.title), names, el("p", "setup-help", words.text),
        el("p", "setup-help setup-recs-feed-warn", words.warn), el("p", "setup-help", words.stop), actions);
      return { node, names, buttons: [no, yes] };
    }
    // The chip that shows the platforms left out.
    function more() {
      const button = el("button", "setup-chip setup-chip-quiet", t.more);
      button.type = "button";
      button.addEventListener("click", () => {
        moreShown = true;
        render();
      });
      return button;
    }
    // A name in a pill with a cross that takes it out.
    function pill(text, label, off) {
      const chip = el("span", "setup-word");
      const cross = kit.iconButton("setup-word-off", "cross", label, off);
      cross.disabled = posting;
      chip.append(el("span", "", text), cross);
      return chip;
    }
    function named(row) {
      return row.key.startsWith("kind:") ? t.kind[row.name] || row.name : row.name;
    }

    function render() {
      const v = view;
      paceCard.hidden = tasteCard.hidden = false;
      pace.set(v.pace, posting);
      paceRow.about.textContent = paI18n.t("setup_recs.paceText", { count: v.caps[v.pace] });
      paceRow.about.hidden = false;
      quiet.box.checked = Boolean(v.quiet_hours);
      quiet.box.disabled = posting;
      hours.hidden = !v.quiet_hours;
      for (const [input, key] of [[from, "from"], [to, "to"]]) {
        input.value = v.quiet_hours ? v.quiet_hours[key] : "";
        input.disabled = posting;
      }

      // The topics offered, then the ones typed; each is on when followed.
      const followed = v.topics.map((row) => row.name);
      const lower = (name) => name.toLowerCase();
      const offered = v.offered.map((row) => row.name);
      const names = [...offered, ...followed.filter((name) => !offered.some((one) => lower(one) === lower(name)))];
      topicChips.replaceChildren(
        ...names.map((name) => {
          const on = followed.some((one) => lower(one) === lower(name));
          return chip(name, on, () => setTopics(on ? followed.filter((one) => lower(one) !== lower(name)) : [...followed, name]));
        }),
        typed,
      );
      typed.disabled = posting;

      const chosen = new Set(v.platforms);
      const shown = v.platformsOffered.filter((row, i) => moreShown || i < PLATFORMS_SHOWN || chosen.has(row.key));
      const unread = (row) => row.reach === "signin" && !row.connected;
      const pick = (row) => {
        if (chosen.has(row.key)) return setPlatforms(v.platforms.filter((key) => key !== row.key));
        asking = asking || row.reach === "signin";
        return setPlatforms([...v.platforms, row.key]);
      };
      platformChips.replaceChildren(
        ...shown.map((row) => chip(row.name, chosen.has(row.key), () => pick(row), unread(row))),
        ...(shown.length < v.platformsOffered.length ? [more()] : []),
      );
      // Open while a platform read only signed in is chosen and nothing was agreed yet.
      notice.node.hidden = !(asking && !v.agreed && v.platformsOffered.some((row) => chosen.has(row.key) && row.reach === "signin"));
      notice.names.textContent = v.platformsOffered.filter((row) => chosen.has(row.key) && row.reach === "signin")
        .map((row) => row.name).join(t.listSep);
      for (const button of notice.buttons) button.disabled = posting;
      note.hidden = !notice.node.hidden || !v.platformsOffered.some((row) => chosen.has(row.key) && unread(row));

      // What the ranking remembers, one flat list: each pill says what it is, and its cross takes it out.
      const learned = (word, row) => pill(paI18n.t(`setup_recs.${word}`, { name: named(row) }), paI18n.t("setup_recs.learnedOff", { name: named(row) }), () => change({ leans: { [row.key]: 0 } }));
      const leaned = (row) => {
        const text = paI18n.t(`setup_recs.leanedRow.${row.lean}`, { name: named(row) });
        return pill(text, paI18n.t("setup_recs.saidOff", { what: text }), () => change({ leans: { [row.key]: null } }));
      };
      const said = [
        ...v.likes.map((x) => [paI18n.t("setup_recs.like", { topic: x.topic }), () => change({ likes: keepLikes(x) })]),
        ...v.rules.map((r) => [
          r.kind === "topic" ? paI18n.t("setup_recs.avoid", { topic: r.topic }) : paI18n.t("setup_recs.hidden", { name: r.name }),
          () => change({ rules: v.rules.filter((other) => other !== r).map(({ kind, key, topic }) => ({ kind, key, topic })) }),
        ]),
        ...v.wishes.map((x) => {
          const day = new Date(x.until * 1000).toLocaleDateString(paI18n.locale, { month: "short", day: "numeric" });
          return [paI18n.t("setup_recs.wish", { topic: x.topic, day }), () => change({ likes: keepLikes(x) })];
        }),
      ];
      if (v.form) {
        const parts = [
          v.form.short === true ? t.form.short : v.form.short === false ? t.form.long : "",
          t.form[v.form.kind] || "",
        ].filter(Boolean);
        said.push([paI18n.t("setup_recs.formRow", { parts: parts.join(t.listSep) }), () => change({ form: null })]);
      }
      const pills = [
        ...v.takes.map((row) => learned("takesRow", row)),
        ...v.passes.map((row) => learned("passesRow", row)),
        ...[...v.topics.filter((row) => row.lean != null), ...v.leans].map(leaned),
        ...said.map(([text, off]) => pill(text, paI18n.t("setup_recs.saidOff", { what: text }), off)),
      ];
      memory.replaceChildren(...pills);
      memoryNone.hidden = Boolean(pills.length);
      rememberedName.textContent = paI18n.t("setup_recs.remembered", { count: pills.length });
      reset.disabled = posting;
    }

    // Every like and wish but `gone`, as POST /api/profile/taste {likes} takes them.
    const keepLikes = (gone) => [...view.likes, ...view.wishes].filter((x) => x !== gone).map((x) => x.topic);

    function addTopic(name) {
      const followed = view.topics.map((row) => row.name);
      if (followed.some((one) => one.toLowerCase() === name.toLowerCase())) return Promise.resolve();
      return setTopics([...followed, name]);
    }

    // The topics and the platforms are kept by one call, as the first run's; platforms left out stay as they were.
    const setTopics = (topics) => choose({ topics });
    const setPlatforms = (platforms) => choose({ topics: view.topics.map((row) => row.name), platforms });

    async function choose(body) {
      await send(async () => {
        await ctx.api("feed/interests", { ...body, lang: kit.lang });
        return ctx.api(`profile/taste?lang=${kit.lang}`);
      });
    }

    function change(body) {
      return send(() => ctx.api("profile/taste", { ...body, lang: kit.lang }));
    }

    async function send(call) {
      if (posting) return;
      posting = true;
      error.hidden = true;
      render();
      try {
        view = await call();
      } catch (failure) {
        kit.failed(error, failure, t);
      }
      posting = false;
      render();
    }

    async function askReset() {
      const sure = await ctx.confirm({ title: t.resetAsk, text: t.resetText, ok: t.resetOk });
      if (sure) await change({ reset: true });
    }

    async function loadWeek() {
      try {
        const n = await ctx.api("feed/numbers");
        const shown = Object.values(n.surfaces).reduce((sum, row) => sum + row.shown, 0);
        const opened = Object.values(n.surfaces).reduce((sum, row) => sum + row.open, 0);
        week.textContent = shown ? paI18n.t("setup_recs.week", { shown, opened }) : t.weekNone;
      } catch (failure) {
        kit.failed(error, failure, t);
      }
    }

    async function show() {
      if (posting) return;
      error.hidden = true;
      try {
        view = await ctx.api(`profile/taste?lang=${kit.lang}`);
        render();
      } catch (failure) {
        kit.failed(error, failure, t);
      }
      loadWeek();
    }

    return { node, show };
  });
})();
