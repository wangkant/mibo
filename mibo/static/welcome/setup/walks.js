"use strict";
// Settings › Going out: the switch, walks a day and the time of the first, the sites walks keep off or favour, and
// the record of each walk (where it looked, what it read, what it skipped and why), as GET/POST /api/walks
// (panels/walks.py) gives them.
(() => {
  const WALKS = ["0", "1", "2", "3", "4", "5", "6"];
  const AT_DEFAULT = "08:00";
  // The search APIs a key can be brought for (search.py SEARCH_APIS), and where each hands out its keys.
  const SEARCH_APIS = {
    brave: { name: "Brave Search", keys: "https://api-dashboard.search.brave.com/app/keys" },
    tavily: { name: "Tavily", keys: "https://app.tavily.com/home" },
  };
  // How often the status and the record are read again while the section is open.
  const POLL_MS = 20000;

  window.paSetup.part("walks", (kit) => {
    const { el } = kit;
    const t = kit.words("setup_walks");
    const ctx = kit.ctx;
    let view = null;
    let posting = false;
    let timer = null;
    const node = kit.section("walks", t.hint);
    const error = kit.errorLine();

    // ---- On or off, how often, from when.
    const main = kit.card();
    main.classList.add("setup-options");
    const on = kit.switchRow("walks-on", t.onName, "", (box) => change({ on: box.checked }));
    on.about.classList.add("setup-walks-status");
    const walks = kit.choices(t.walksName, WALKS.map((n) => [n, n]), (n) => change({ walks: Number(n) }));
    const walksRow = kit.optionRow(t.walksName, t.walksText, walks.group);
    const timed = kit.switchRow("walks-at", t.atName, t.atOff, (box) => change({ at: box.checked ? view.at || AT_DEFAULT : "" }));
    const at = el("input", "setup-input setup-recs-time");
    at.type = "time";
    at.setAttribute("aria-label", t.atName);
    at.addEventListener("change", () => at.value && change({ at: at.value }));
    const atLine = el("div", "setup-recs-hours");
    atLine.append(at);
    timed.row.append(atLine);
    main.append(on.row, walksRow.row, timed.row);

    // ---- Sites to keep off and to favour.
    const sitesCard = kit.card(t.sitesTitle);
    sitesCard.append(el("p", "setup-help", t.sitesText));
    const hosts = el("datalist");
    hosts.id = "setup-walks-hosts";
    const avoid = siteBlock("avoid", t.avoid);
    const favour = siteBlock("favour", t.favour);
    sitesCard.append(hosts, avoid.box, favour.box);

    // ---- Web search: the keyless engines, or a search API whose key the person brings.
    const searchCard = kit.card(t.searchTitle);
    searchCard.append(el("p", "setup-help", t.searchText));
    const remove = kit.button("setup-button-secondary setup-button-sm", t.searchRemove, () =>
      send(() => ctx.api("walks", { search: "" })));
    const using = kit.optionRow(t.searchUsing, "", remove);
    let api = "brave";
    const apis = kit.choices(t.searchApi, Object.keys(SEARCH_APIS).map((id) => [id, SEARCH_APIS[id].name]), (id) => {
      api = id;
      render();
    });
    for (const item of apis.group.children) item.prepend(mark(item.dataset.value));
    const apiRow = kit.optionRow(t.searchApi, "", apis.group);
    const key = kit.input();
    key.type = "password";
    const keyField = kit.field(t.searchKey, key);
    const save = kit.button("setup-button-primary", t.searchSave, () => {
      if (!key.value.trim()) return;
      kit.busy(save, true, t.searchChecking);
      send(() => ctx.api("walks", { search: api, key: key.value })).then(() => {
        kit.busy(save, false, t.searchSave);
        if (error.hidden) key.value = "";
      });
    });
    key.addEventListener("keydown", (event) => event.key === "Enter" && !event.isComposing && save.click());
    const keyRow = el("div", "setup-inline");
    keyRow.append(keyField.wrap, save);
    searchCard.append(using.row, apiRow.row, keyRow);

    // ---- The record, newest first.
    const recordCard = kit.card(t.recordTitle);
    const entries = el("div", "setup-walks-entries");
    const empty = el("p", "setup-help", t.recordNone);
    recordCard.append(entries, empty);
    main.hidden = sitesCard.hidden = searchCard.hidden = recordCard.hidden = true;
    node.append(error, main, sitesCard, searchCard, recordCard);

    // The service's own mark (providermarks.js).
    function mark(id) {
      const box = el("span", "setup-walks-mark");
      box.setAttribute("aria-hidden", "true");
      box.innerHTML = window.paProviderMarks?.[id] || "";
      return box;
    }

    function renderSearch(v) {
      const chosen = SEARCH_APIS[v.search];
      using.about.hidden = false;
      using.about.replaceChildren(...(chosen ? [mark(v.search), el("span", "", chosen.name)] : [t.searchKeyless]));
      remove.hidden = !chosen;
      remove.disabled = posting;
      apiRow.row.hidden = keyRow.hidden = Boolean(chosen);
      apis.set(api, posting);
      const get = el("a", "setup-link", paI18n.t("setup_walks.searchGet", { name: SEARCH_APIS[api].name }));
      get.href = SEARCH_APIS[api].keys;
      get.target = "_blank";
      get.rel = "noopener noreferrer";
      keyField.help([get]);
      key.disabled = posting;
    }

    function siteBlock(how, title) {
      const box = el("div", "setup-recs-block");
      const list = el("div", "setup-words");
      const typed = kit.input("setup-word-input");
      typed.placeholder = t.addSite;
      typed.setAttribute("aria-label", `${title}: ${t.addSite}`);
      typed.setAttribute("list", hosts.id);
      typed.addEventListener("keydown", (event) => {
        const site = typed.value.trim();
        if (event.key !== "Enter" || event.isComposing || !site) return;
        event.preventDefault();
        change({ site, steer: how }).then(() => !error.hidden || (typed.value = ""));
      });
      box.append(el("p", "setup-option-name", title), list);
      return { box, list, typed };
    }

    function pill(key) {
      const chip = el("span", "setup-word");
      const cross = kit.iconButton("setup-word-off", "cross", paI18n.t("setup_walks.siteOff", { site: key }), () =>
        change({ site: key, steer: "" }));
      cross.disabled = posting;
      chip.append(el("span", "", key), cross);
      return chip;
    }

    const when = (seconds, options) => new Date(seconds * 1000).toLocaleString(paI18n.locale, { hourCycle: "h23", ...options });

    // What a walk of its own does next, or why none leaves.
    function status(v) {
      if (!v.on) return t.offText;
      if (v.why === "out") return v.where ? paI18n.t("setup_walks.state.outAt", { where: v.where }) : t.state.out;
      if (v.why === "limit") return paI18n.t("setup_walks.state.limit", { today: v.today });
      if (v.why) return t.state[v.why] || "";
      if (!v.next) return "";
      const soon = v.next - Date.now() / 1000 < 90;
      const sameDay = new Date(v.next * 1000).toDateString() === new Date().toDateString();
      const time = when(v.next, sameDay ? { hour: "2-digit", minute: "2-digit" } : { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
      return [soon ? t.state.soon : paI18n.t("setup_walks.state.next", { time }), paI18n.t("setup_walks.state.today", { today: v.today })].join(t.sep);
    }

    function render() {
      const v = view;
      main.hidden = sitesCard.hidden = searchCard.hidden = recordCard.hidden = false;
      renderSearch(v);
      on.box.checked = v.on;
      on.box.disabled = posting;
      on.about.textContent = status(v);
      on.about.hidden = !on.about.textContent;
      walks.set(String(v.walks), posting || !v.on);
      timed.box.checked = Boolean(v.at);
      timed.box.disabled = posting || !v.on;
      timed.about.textContent = v.at ? paI18n.t("setup_walks.atText", { time: v.at }) : t.atOff;
      atLine.hidden = !v.at;
      at.value = v.at;
      at.disabled = posting || !v.on;
      hosts.replaceChildren(...v.hosts.map((h) => Object.assign(el("option"), { value: h.key, label: h.name })));
      for (const [block, keys] of [[avoid, v.avoid], [favour, v.favour]]) {
        block.list.replaceChildren(...keys.map(pill), block.typed);
        block.typed.disabled = posting;
      }
      entries.replaceChildren(...v.record.map(entry));
      empty.hidden = Boolean(v.record.length);
    }

    // One walk: when, what for, how much it read and kept, and why some places could not be read; the pages
    // and the lists behind it unfold under it.
    function entry(walk) {
      const box = el("details", "setup-walks-entry");
      const head = el("summary", "setup-walks-head");
      const kept = walk.read.filter((page) => page.kept).length;
      const line = el("span", "setup-walks-line");
      line.append(
        el("span", "setup-walks-time", when(walk.at, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })),
        el("span", "setup-walks-topic", walk.topic ? paI18n.t(walk.asked ? "setup_walks.asked" : "setup_walks.topic", { topic: walk.topic }) : t.noTopic),
      );
      const sums = el("span", "setup-walks-sums", paI18n.t("setup_walks.sums", { lists: walk.lists.length, read: walk.read.length, kept }));
      head.append(kit.icon("chevron", "setup-icon setup-fold-chevron"), line, sums);
      box.append(head);
      const missed = [...walk.lists.filter((row) => row.why).map((row) => [row.site, row.why]), ...walk.skipped.map((row) => [row.site, row.why])];
      if (missed.length) {
        // The places, grouped by why each could not be read.
        const byWhy = new Map();
        for (const [site, why] of missed) {
          const key = t.why[why] ? why : "error";
          byWhy.set(key, new Set([...(byWhy.get(key) || []), site === "Web" ? t.web : site]));
        }
        const names = new Intl.ListFormat(paI18n.locale, { type: "conjunction" });
        const said = [...byWhy].map(([why, places]) => paI18n.t("setup_walks.missed", { site: names.format([...places]), why: reason(why) }));
        box.append(el("p", "setup-walks-missed", said.join(t.listSep)));
      }
      const body = el("div", "setup-walks-body");
      body.append(part(t.lists, walk.lists.map((list) =>
        place(list.site === "Web" ? t.web : list.site, t.intent[list.intent] || "", list.why ? reason(list.why) : paI18n.t("setup_walks.found", { count: list.found })))));
      body.append(part(t.read, walk.read.map((page) => link(page, page.kept ? t.kept : ""))));
      body.append(part(t.skipped, walk.skipped.map((page) => link(page, reason(page.why)))));
      box.append(body);
      return box;
    }

    function reason(why) {
      return t.why[why] || t.why.error;
    }
    function part(title, rows) {
      const box = el("div", "setup-walks-part");
      box.hidden = !rows.length;
      box.append(el("p", "setup-walks-part-title", title), ...rows);
      return box;
    }
    function place(name, kind, note) {
      const line = el("p", "setup-walks-row");
      line.append(el("span", "setup-walks-site", name), el("span", "setup-walks-note", [kind, note].filter(Boolean).join(t.sep)));
      return line;
    }
    function link(page, note) {
      const line = el("p", "setup-walks-row");
      const a = el("a", "setup-link setup-walks-page", page.title || page.url);
      a.href = page.url;
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      line.append(a, el("span", "setup-walks-note", [page.site, note].filter(Boolean).join(t.sep)));
      return line;
    }

    function change(body) {
      return send(() => ctx.api("walks", body));
    }

    async function send(call) {
      if (posting) return;
      posting = true;
      error.hidden = true;
      if (view) render();
      try {
        view = await call();
      } catch (failure) {
        kit.failed(error, failure, t);
      }
      posting = false;
      if (view) render();
    }

    async function show() {
      clearTimeout(timer);
      if (!node.isConnected || node.hidden) return;
      if (!posting) {
        try {
          view = await ctx.api("walks");
          render();
        } catch (failure) {
          kit.failed(error, failure, t);
        }
      }
      timer = setTimeout(show, POLL_MS);
    }

    return { node, show: () => (error.hidden = true, show()) };
  });
})();
