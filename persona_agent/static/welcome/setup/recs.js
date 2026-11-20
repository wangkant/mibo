"use strict";
// Settings › Recommendations: how often and when (the pace and quiet hours pacing.py reads), the person's taste
// as the ranking holds it (GET/POST /api/profile/taste: picked topics with a lean each, what their reactions
// taught, every other lean, what they said in the chat, wishes for the next few days, a reset), and the week in numbers
// (GET /api/feed/numbers). Topics are added and taken out with POST /api/feed/interests, as the first run does.
(() => {
  const PACES = ["less", "normal", "more"];
  const LEANS = ["-1", "", "1"];
  const QUIET_DEFAULT = { from: "22:00", to: "08:00" };
  const TOPIC_LEN = 40;

  window.paSetup.part("recs", (kit) => {
    const { el } = kit;
    const t = kit.words("setup_recs");
    const ctx = kit.ctx;
    let view = null;
    let posting = false;
    const node = kit.section("recs");
    const error = kit.errorLine();

    // ---- How often and when.
    const paceCard = kit.card();
    paceCard.classList.add("setup-options");
    const pace = kit.choices(t.paceName, PACES.map((key) => [key, t.pace[key]]), (key) => change({ pace: key }));
    const paceRow = kit.optionRow(t.paceName, "", pace.group);
    const quiet = kit.switchRow("recs-quiet", t.quietName, t.quietOff, (box) =>
      change({ quiet_hours: box.checked ? view.quiet_hours || QUIET_DEFAULT : null }));
    const hours = el("div", "setup-recs-hours");
    const from = clock(t.quietFrom);
    const to = clock(t.quietTo);
    hours.append(from, el("span", "setup-recs-dash", "–"), to);
    quiet.row.append(hours);
    paceCard.append(paceRow.row, quiet.row);

    // ---- Taste.
    const tasteCard = kit.card(t.tasteTitle);
    tasteCard.append(el("p", "setup-help", t.tasteText));
    const topicList = el("div", "setup-recs-topics");
    const offered = el("div", "setup-chips setup-recs-offered");
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
    offered.append(typed);
    const takes = labelled(t.takes);
    const passes = labelled(t.passes);
    const learnedNone = el("p", "setup-help", t.learnedNone);
    // Leans set from a card (its chip, its no) or a taught row, each with a cross that clears it.
    const leaned = words();
    const leanBlock = block(t.leaned, leaned);
    const said = words();
    const saidNone = el("p", "setup-help", t.saidNone);
    const wishBlock = el("div", "setup-recs-block");
    const wishes = words();
    wishBlock.append(el("p", "setup-option-name", t.wishes), el("p", "setup-help", t.wishText), wishes);
    const reset = kit.button("setup-recs-reset", t.reset, askReset);
    tasteCard.append(
      block(t.topics, topicList, offered),
      block(t.learned, takes.line, passes.line, learnedNone),
      leanBlock,
      block(t.said, said, saidNone),
      wishBlock,
      reset,
    );

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
    function words() {
      return el("div", "setup-words");
    }
    // A short label, then pills on the same line.
    function labelled(label) {
      const line = el("div", "setup-recs-line");
      const list = words();
      line.append(el("span", "setup-recs-label", label), list);
      return { line, list };
    }
    function block(title, ...parts) {
      const box = el("div", "setup-recs-block");
      box.append(el("p", "setup-option-name", title), ...parts);
      return box;
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
      quiet.about.textContent = v.quiet_hours ? paI18n.t("setup_recs.quietText", { from: v.quiet_hours.from, to: v.quiet_hours.to }) : t.quietOff;
      hours.hidden = !v.quiet_hours;
      for (const [input, key] of [[from, "from"], [to, "to"]]) {
        input.value = v.quiet_hours ? v.quiet_hours[key] : "";
        input.disabled = posting;
      }

      topicList.replaceChildren(
        ...(v.topics.length ? v.topics.map(topicRow) : [el("p", "setup-help", t.topicsNone)]),
      );
      const picked = new Set(v.topics.map((row) => row.name.toLowerCase()));
      offered.replaceChildren(
        ...v.offered.filter((row) => !picked.has(row.name.toLowerCase())).map((row) => {
          const chip = el("button", "setup-chip", `+ ${row.name}`);
          chip.type = "button";
          chip.disabled = posting;
          chip.addEventListener("click", () => addTopic(row.name));
          return chip;
        }),
        typed,
      );
      typed.disabled = posting;

      const learned = (row) => pill(named(row), paI18n.t("setup_recs.learnedOff", { name: named(row) }), () => change({ leans: { [row.key]: 0 } }));
      for (const [side, rows] of [[takes, v.takes], [passes, v.passes]]) {
        side.list.replaceChildren(...rows.map(learned));
        side.line.hidden = !rows.length;
      }
      learnedNone.hidden = Boolean(v.takes.length || v.passes.length);
      leaned.replaceChildren(
        ...v.leans.map((row) => {
          const text = paI18n.t(`setup_recs.leanedRow.${row.lean}`, { name: named(row) });
          return pill(text, paI18n.t("setup_recs.saidOff", { what: text }), () => change({ leans: { [row.key]: null } }));
        }),
      );
      leanBlock.hidden = !v.leans.length;

      const rows = [
        ...v.likes.map((x) => [paI18n.t("setup_recs.like", { topic: x.topic }), () => change({ likes: keepLikes(x) })]),
        ...v.rules.map((r) => [
          r.kind === "topic" ? paI18n.t("setup_recs.avoid", { topic: r.topic }) : paI18n.t("setup_recs.hidden", { name: r.name }),
          () => change({ rules: v.rules.filter((other) => other !== r).map(({ kind, key, topic }) => ({ kind, key, topic })) }),
        ]),
      ];
      if (v.form) {
        const parts = [
          v.form.short === true ? t.form.short : v.form.short === false ? t.form.long : "",
          t.form[v.form.kind] || "",
        ].filter(Boolean);
        rows.push([paI18n.t("setup_recs.formRow", { parts: parts.join(t.listSep) }), () => change({ form: null })]);
      }
      said.replaceChildren(...rows.map(([text, off]) => pill(text, paI18n.t("setup_recs.saidOff", { what: text }), off)));
      saidNone.hidden = Boolean(rows.length);

      wishes.replaceChildren(
        ...v.wishes.map((x) => {
          const day = new Date(x.until * 1000).toLocaleDateString(paI18n.locale, { month: "short", day: "numeric" });
          const text = paI18n.t("setup_recs.wish", { topic: x.topic, day });
          return pill(text, paI18n.t("setup_recs.saidOff", { what: x.topic }), () => change({ likes: keepLikes(x) }));
        }),
      );
      wishBlock.hidden = !v.wishes.length;
      reset.disabled = posting;
    }

    // Each picked topic: its name, less / usual / more, and a cross to stop following it.
    function topicRow(row) {
      const line = el("div", "setup-recs-topic");
      const lean = kit.choices(paI18n.t("setup_recs.leanLabel", { name: row.name }), LEANS.map((key) => [key, t.lean[key]]), (key) =>
        change({ leans: { [row.key]: key === "" ? null : Number(key) } }));
      lean.set(row.lean == null ? "" : String(row.lean), posting);
      const cross = kit.iconButton("setup-word-off", "cross", paI18n.t("setup_recs.removeTopic", { name: row.name }), () =>
        setTopics(view.topics.map((one) => one.name).filter((name) => name !== row.name)));
      cross.disabled = posting;
      line.append(el("span", "setup-recs-topic-name", row.name), lean.group, cross);
      return line;
    }

    // Every like and wish but `gone`, as POST /api/profile/taste {likes} takes them.
    const keepLikes = (gone) => [...view.likes, ...view.wishes].filter((x) => x !== gone).map((x) => x.topic);

    function addTopic(name) {
      if (view.topics.some((row) => row.name.toLowerCase() === name.toLowerCase())) return Promise.resolve();
      return setTopics([...view.topics.map((row) => row.name), name]);
    }

    async function setTopics(topics) {
      await send(async () => {
        await ctx.api("feed/interests", { topics, lang: kit.lang });
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
