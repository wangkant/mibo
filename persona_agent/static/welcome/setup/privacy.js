"use strict";
// Settings › Privacy: whether the character notices what is in front (/api/remarks/settings)
// and the programs it never looks at, hiding in full screen (/api/quiet/settings),
// and what the app's own browser read (/api/browser {shared}, /api/browser/clear), and per site what it may
// do there (/api/browser/sites, /api/browser/allowed): kinds let through without asking, the person's feed
// read in the background, the ways kept from confirmed tasks.
(() => {
  // As many programs as the server keeps.
  const IGNORE_MAX = 50;

  window.paSetup.part("privacy", (kit) => {
    const { el } = kit;
    const t = kit.words("setup_privacy");
    const ctx = kit.ctx;
    const remarks = { on: true, ignore: [], saving: false, known: false };
    const quiet = { saving: false };
    const browsing = {};
    const places = {};
    const node = kit.section("privacy");
    const box = kit.card();
    box.classList.add("setup-options");
    box.append(buildRemarks(), buildQuiet(), ...buildBrowsing(), buildSites());
    node.append(box);

    // ---- Remarks on what is in front, and the programs it never looks at.
    function buildRemarks() {
      const { row, box: on, about } = kit.switchRow("remarks", t.remarksTitle, t.remarksText,
        (node) => saveRemarks({ on: node.checked }));
      const error = kit.errorLine();
      about.after(error);
      // Folded under the switch, across the whole row; shown only while the switch is on.
      const fold = kit.fold(paI18n.t("setup_privacy.ignoreFold", { count: 0 }));
      fold.node.classList.add("setup-ignore");
      const list = el("div", "setup-words");
      const help = el("p", "setup-help", t.ignoreHelp);
      help.id = "setup-ignore-help";
      const add = kit.input("setup-word-input");
      add.placeholder = t.ignoreAdd;
      add.maxLength = 64;
      add.setAttribute("aria-label", t.ignoreAdd);
      add.setAttribute("aria-describedby", help.id);
      add.addEventListener("keydown", (event) => {
        const name = add.value.trim().replace(/\s+/g, " ");
        if (event.key !== "Enter" || event.isComposing || !name) return;
        event.preventDefault();
        // One already there takes no second place.
        if (remarks.ignore.some((n) => n.toLowerCase() === name.toLowerCase())) {
          add.value = "";
          return;
        }
        saveRemarks({ ignore: [...remarks.ignore, name] }).then((done) => {
          if (done) add.value = "";
          add.focus();
        });
      });
      fold.body.append(list, help);
      row.append(fold.node);
      Object.assign(remarks, { box: on, error, fold, list, add });
      return row;
    }

    function renderRemarks() {
      const { box: on, fold, list, add, ignore, saving, known } = remarks;
      on.checked = remarks.on;
      on.disabled = saving || !known;
      fold.node.hidden = !remarks.on;
      fold.summary.lastChild.textContent = paI18n.t("setup_privacy.ignoreFold", { count: ignore.length });
      list.replaceChildren(
        ...ignore.map((name) => {
          const chip = el("span", "setup-word");
          const off = kit.iconButton("setup-word-off", "cross", paI18n.t("setup_privacy.ignoreRemove", { name }), () => unignore(name));
          off.disabled = saving;
          chip.append(el("span", "", name), off);
          return chip;
        }),
      );
      if (ignore.length < IGNORE_MAX) list.append(add);
      add.disabled = saving || !known;
    }

    async function unignore(name) {
      const sure = await ctx.confirm({ title: paI18n.t("setup_privacy.ignoreAsk", { name }), text: t.ignoreAskText, ok: t.remove });
      if (!sure) return;
      await saveRemarks({ ignore: remarks.ignore.filter((n) => n !== name) });
      remarks.add.focus();
    }

    async function loadRemarks() {
      if (remarks.saving) return;
      try {
        const value = await ctx.api("remarks/settings");
        if (remarks.saving) return;
        Object.assign(remarks, { on: value.on, ignore: value.ignore, known: true });
        remarks.error.hidden = true;
      } catch (error) {
        kit.failed(remarks.error, error, t);
      }
      renderRemarks();
    }

    // The server answers with the cleaned whole: names trimmed, no doubles.
    async function saveRemarks(change) {
      remarks.saving = true;
      remarks.error.hidden = true;
      renderRemarks();
      try {
        const value = await ctx.api("remarks/settings", change);
        Object.assign(remarks, { on: value.on, ignore: value.ignore });
        return true;
      } catch (error) {
        kit.failed(remarks.error, error, t);
        return false;
      } finally {
        remarks.saving = false;
        renderRemarks();
      }
    }

    // ---- Hiding in full screen and games.
    function buildQuiet() {
      const { row, box: on, about } = kit.switchRow("quiet", t.quietTitle, t.quietText, (node) => setQuiet(node.checked));
      const now = el("p", "setup-option-now");
      now.hidden = true;
      const error = kit.errorLine();
      about.after(now, error);
      on.disabled = true;
      Object.assign(quiet, { box: on, now, error });
      return row;
    }

    // Hidden right now is only ever seen from another device: this window in front never counts.
    async function loadQuiet() {
      if (quiet.saving) return;
      try {
        const [value, now] = await Promise.all([ctx.api("quiet/settings"), ctx.api("quiet")]);
        if (quiet.saving) return;
        quiet.box.checked = value.on;
        quiet.box.disabled = false;
        quiet.now.textContent = t.quietNow[now.why] || "";
        quiet.now.hidden = !(value.on && now.quiet);
        quiet.error.hidden = true;
      } catch (error) {
        kit.failed(quiet.error, error, t);
      }
    }

    async function setQuiet(on) {
      quiet.saving = true;
      quiet.box.disabled = true;
      quiet.error.hidden = true;
      try {
        quiet.box.checked = (await ctx.api("quiet/settings", { on })).on;
        if (!on) quiet.now.hidden = true;
      } catch (error) {
        quiet.box.checked = !on;
        kit.failed(quiet.error, error, t);
      } finally {
        quiet.saving = false;
        quiet.box.disabled = false;
      }
      // Back on: whether it is hiding right now is read again.
      if (quiet.box.checked) loadQuiet();
    }

    // ---- The app's own browser: whether the character may use what was read there, and clearing it.
    function buildBrowsing() {
      const { row, box: on, about } = kit.switchRow("browsing", t.browsingTitle, t.browsingText,
        (node) => saveBrowsing(node.checked));
      const error = kit.errorLine();
      about.after(error);
      on.disabled = true;
      const clear = kit.button("setup-button-secondary setup-button-sm", t.clear, clearBrowsing);
      const wipe = kit.optionRow(t.clearTitle, t.clearText, clear);
      const done = el("p", "setup-option-now", t.cleared);
      done.hidden = true;
      wipe.about.after(done);
      row.hidden = wipe.row.hidden = true;
      Object.assign(browsing, { row, box: on, error, clear, wipeRow: wipe.row, done });
      return [row, wipe.row];
    }

    async function loadBrowsing() {
      try {
        const value = await ctx.api("browser");
        browsing.row.hidden = browsing.wipeRow.hidden = !value.builtin;
        browsing.box.checked = value.shared;
        browsing.box.disabled = false;
        browsing.error.hidden = true;
      } catch (error) {
        kit.failed(browsing.error, error, t);
      }
    }

    async function saveBrowsing(on) {
      browsing.box.disabled = true;
      browsing.error.hidden = true;
      try {
        browsing.box.checked = (await ctx.api("browser", { shared: on })).shared;
      } catch (error) {
        browsing.box.checked = !on;
        kit.failed(browsing.error, error, t);
      } finally {
        browsing.box.disabled = false;
      }
    }

    async function clearBrowsing() {
      const sure = await ctx.confirm({ title: t.clearAsk, text: t.clearAskText, ok: t.clear });
      if (!sure) return;
      kit.busy(browsing.clear, true);
      browsing.done.hidden = true;
      try {
        await ctx.api("browser/clear", {});
        browsing.done.hidden = false;
      } catch (error) {
        kit.failed(browsing.error, error, t);
      } finally {
        kit.busy(browsing.clear, false);
      }
    }

    // ---- Per site: what the character may do there without asking, the feed read in the background, the ways kept.
    function buildSites() {
      const fold = kit.fold(paI18n.t("setup_privacy.sitesFold", { count: 0 }));
      fold.node.classList.add("setup-sites");
      const list = el("div", "setup-sites-list");
      const error = kit.errorLine();
      fold.body.append(list, error);
      fold.node.hidden = true;
      Object.assign(places, { fold, list, error });
      return fold.node;
    }

    function renderSites(rows) {
      places.fold.summary.lastChild.textContent = paI18n.t("setup_privacy.sitesFold", { count: rows.length });
      if (!rows.length) return places.list.replaceChildren(el("p", "setup-help", t.sitesNone));
      places.list.replaceChildren(...rows.map((row) => {
        const item = el("div", "setup-site");
        item.append(el("p", "setup-option-name", row.site));
        for (const { site, kind } of row.allowed) {
          const what = t.allowedKind[kind] || kind;
          const chip = el("span", "setup-word");
          chip.append(el("span", "", what), kit.iconButton("setup-word-off", "cross", paI18n.t("setup_privacy.allowedOff", { what }),
            () => changeSites("browser/allowed", { site, kind, on: false })));
          item.append(chip);
        }
        const id = `feed-${row.site.replace(/[^a-z0-9]/gi, "-")}`;
        const feed = kit.switchRow(id, t.feedTitle, row.feed.stopped ? `${t.feedWarn} ${t.feedStopped}` : t.feedWarn,
          async (node) => {
            if (node.checked) {
              node.checked = false;
              const sure = await ctx.confirm({ title: t.feedAsk, text: t.feedWarn, ok: t.feedYes });
              if (!sure) return;
            }
            changeSites("browser/sites", { site: row.site, feed: !row.feed.on });
          });
        feed.box.checked = row.feed.on;
        item.append(feed.row);
        const tools = el("div", "setup-site-tools");
        if (row.procedures) {
          tools.append(el("span", "setup-help", paI18n.t("setup_privacy.ways", { count: row.procedures })),
            kit.button("setup-button-secondary setup-button-sm", t.waysOff,
              () => changeSites("browser/sites", { site: row.site, forget: "procedures" })));
        }
        if (row.learned || row.allowed.length || row.feed.on) {
          tools.append(kit.button("setup-button-secondary setup-button-sm", t.forget, async () => {
            const sure = await ctx.confirm({ title: paI18n.t("setup_privacy.forgetAsk", { site: row.site }), text: t.forgetText, ok: t.forget });
            if (sure) changeSites("browser/sites", { site: row.site, forget: "all" });
          }));
        }
        if (tools.childElementCount) item.append(tools);
        return item;
      }));
    }

    async function loadSites() {
      try {
        const value = await ctx.api("browser/sites");
        places.fold.node.hidden = browsing.row.hidden;
        places.error.hidden = true;
        renderSites(value.sites);
      } catch (error) {
        kit.failed(places.error, error, t);
      }
    }

    async function changeSites(path, change) {
      places.error.hidden = true;
      try {
        await ctx.api(path, change);
      } catch (error) {
        kit.failed(places.error, error, t);
      }
      loadSites();
    }

    renderRemarks();

    function show() {
      loadRemarks();
      loadQuiet();
      loadBrowsing().then(loadSites);
    }

    return { node, show };
  });
})();
