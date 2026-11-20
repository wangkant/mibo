// Settings › 连接: the sites signed in to in Mibo's own browser, one way for every site, mail too
// (panels/signins.py). Only the sites signed in to are rows: each is the site's icon and name, when it was last
// used, and 退出登录; the row opens the site's choices, and the first time a site is signed in they open by
// themselves with one line of what can now be asked there. 登录网站 opens a picker of the well-known sites and a
// field for any other address; the row comes once the person has signed in, in the pane, however long it took.
// Below, what the browser keeps on this computer. The app never reads a cookie or a password; setup/connect.js
// mounts this inside its own root.
(() => {
  "use strict";

  const SVG = "http://www.w3.org/2000/svg";
  const CROSS = ["M7 7l10 10", "M17 7L7 17"];
  const PLUS = ["M12 5v14", "M5 12h14"];
  // While a sign-in waits in the pane, the list is asked again this often, for at most this long.
  const POLL_MS = 2000;
  const POLL_MAX_MS = 11 * 60 * 1000;

  let ctx, t, list, kept, said, waitLine;
  let data = null;
  let polling = null;
  const token = () => sessionStorage.getItem("personagent-setup-token") || "";
  const frame = () => sessionStorage.getItem("personagent-frame") || "";

  async function call(path, body) {
    const response = await fetch(`/api/${path}`, {
      method: body === undefined ? "GET" : "POST",
      headers: { "Content-Type": "application/json", "X-Personagent-Setup-Token": token(), "X-Personagent-Window": frame() },
      body: body === undefined ? undefined : JSON.stringify(body),
      credentials: "same-origin",
    });
    const value = await response.json().catch(() => ({}));
    if (!response.ok || value.error) throw new Error(value.error || "generic");
    return value;
  }

  function el(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  }
  function icon(paths, cls = "places-icon") {
    const svg = document.createElementNS(SVG, "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("class", cls);
    for (const d of paths) {
      const path = document.createElementNS(SVG, "path");
      path.setAttribute("d", d);
      svg.append(path);
    }
    return svg;
  }
  function button(cls, text, run, paths) {
    const node = el("button", `places-btn ${cls}`);
    node.type = "button";
    if (paths) node.append(icon(paths));
    node.append(el("span", "", text));
    node.addEventListener("click", run);
    return node;
  }
  function ago(seconds) {
    if (!seconds) return "";
    const minutes = Math.max(0, Math.round((Date.now() / 1000 - seconds) / 60));
    if (minutes < 1) return t.ago.now;
    if (minutes < 60) return paI18n.t("sites.ago.m", { count: minutes });
    if (minutes < 1440) return paI18n.t("sites.ago.h", { count: Math.round(minutes / 60) });
    return paI18n.t("sites.ago.d", { count: Math.round(minutes / 1440) });
  }
  // The site's own icon (as the browser kept it, or its mark), else its first letter.
  function mark(row) {
    const badge = el("span", "places-mark sites-mark");
    badge.setAttribute("aria-hidden", "true");
    const src = row.icon || row.mark;
    if (src) {
      const img = el("img", "sites-icon");
      img.src = src;
      img.alt = "";
      badge.append(img);
    } else {
      badge.append(el("span", "places-mark-text", [...row.name][0].toUpperCase()));
    }
    return badge;
  }
  function line(row) {
    if (row.state === "unsure") return t.unsureLine;
    if (row.used) return paI18n.t("sites.used", { when: ago(row.used) });
    if (row.at) return paI18n.t("sites.signedAt", { when: ago(row.at) });
    return new URL(row.home).hostname.replace(/^www\./, "");
  }
  // A button that is disabled and says so while `work` runs.
  async function busy(node, work) {
    const label = node.querySelector("span");
    const was = label.textContent;
    node.disabled = true;
    label.textContent = t.working;
    try {
      return await work();
    } catch (error) {
      say(error.message === "signin_window" ? t.noWindow : error.message === "signin_invalid" ? t.addFailed : t.failed);
      return null;
    } finally {
      if (node.isConnected) {
        node.disabled = false;
        label.textContent = was;
      }
    }
  }
  function say(words) {
    said.replaceChildren(el("span", "places-alert-mark", "!"), el("span", "", words));
    said.hidden = !words;
  }

  // ---- the list
  function paint() {
    if (!data) return;
    list.replaceChildren(...data.sites.map(rowOf));
    if (!data.sites.length) list.append(el("p", "places-empty sites-empty", t.empty));
    const name = data.waiting && (data.picks.find((p) => p.site === data.waiting)?.name || data.waiting);
    waitLine.hidden = !data.waiting;
    waitLine.textContent = data.waiting ? paI18n.t("sites.waiting", { name }) : "";
    paintKept();
    if (sheet.site) sheet.draw();
    // The first time a site is signed in, its choices open by themselves, once.
    // Not while the page is still open over Settings: the sheet waits for it to close.
    const fresh = freshRow();
    if (fresh && !sheet.site && !picker.dialog?.open && !paneOpen()) {
      sheet.open(fresh.site, true);
      call("signins", { op: "seen", site: fresh.site }).catch(() => {});
    }
  }
  function freshRow() {
    return data?.sites.find((row) => row.fresh && row.state === "in");
  }
  function paneOpen() {
    return document.querySelector("section.browse")?.hidden === false;
  }
  function rowOf(row) {
    const node = el("div", "places-service sites-row");
    node.dataset.state = row.state === "in" ? "on" : "off";
    const main = el("button", "places-service-main");
    main.type = "button";
    const words = el("span", "places-service-words");
    words.append(el("span", "places-service-name", row.name), el("span", "places-service-line", line(row)));
    const pill = el("span", "places-pill", t.state[row.state]);
    main.append(mark(row), words, pill);
    main.addEventListener("click", () => sheet.open(row.site));
    const action = row.state === "in"
      ? button("places-btn-secondary places-btn-quiet places-btn-sm", t.signOut, () => signOut(row, action))
      : button("places-btn-secondary places-btn-sm", t.signIn, () => signIn({ url: row.home }, action));
    node.append(main, action);
    return node;
  }
  // 登录: the site's sign-in comes up in the pane; the list is asked again until the wait there ends.
  async function signIn(what, node) {
    const answer = await busy(node, () => call("signins", { op: "signin", ...what }));
    if (!answer) return false;
    if (answer.status === "busy") {
      say(t.busy);
      return false;
    }
    watch();
    return true;
  }
  function watch() {
    const began = Date.now();
    let quiet = 0;
    clearInterval(polling);
    load();
    polling = setInterval(async () => {
      await load();
      // Two more looks after the wait ends, then stop.
      quiet = data?.waiting || (freshRow() && paneOpen()) ? 0 : quiet + 1;
      if (quiet > 2 || Date.now() - began > POLL_MAX_MS) clearInterval(polling);
    }, POLL_MS);
  }
  async function signOut(row, node) {
    const sure = await ctx.confirm({ ...t.sureOut, title: paI18n.t("sites.sureOut.title", { name: row.name }) });
    if (!sure) return;
    const next = await busy(node, () => call("signins", { op: "signout", site: row.site }));
    if (next) {
      data = next;
      sheet.close();
      paint();
    }
  }
  async function change(body, node) {
    const next = node ? await busy(node, () => call("signins", body)) : await call("signins", body).catch((error) => {
      say(error.message === "signin_window" ? t.noWindow : t.failed);
      return null;
    });
    if (next) {
      data = next;
      paint();
    }
    return next;
  }

  // ---- what the browser keeps on this computer
  function paintKept() {
    kept.replaceChildren();
    const head = el("div", "sites-kept-head");
    head.append(el("h3", "sites-title", t.keptTitle), el("p", "sites-about", t.keptAbout));
    kept.append(head);
    const rows = el("div", "places-services sites-kept-list");
    for (const row of data.kept) {
      const node = el("div", "places-service sites-kept-row");
      const words = el("div", "places-service-words sites-kept-words");
      const tags = [row.session ? t.session : "", row.saved ? t.saved : ""].filter(Boolean).join(" · ");
      words.append(el("span", "places-service-name", row.name), el("span", "places-service-line", tags));
      node.append(words);
      if (row.session) {
        const out = button("places-btn-secondary places-btn-quiet places-btn-sm", t.signOut, () => signOut(row, out));
        node.append(out);
      }
      rows.append(node);
    }
    if (data.kept.length) kept.append(rows);
    else kept.append(el("p", "places-empty sites-kept-none", t.keptNone));
    if (data.others) kept.append(el("p", "sites-faint", paI18n.t("sites.others", { count: data.others })));
    const all = button("places-btn-secondary places-btn-sm", t.clearSessions, async () => {
      if (await ctx.confirm(t.sureSessions)) change({ op: "clear", what: "sessions" }, all);
    });
    const passwords = button("places-btn-secondary places-btn-sm", t.clearPasswords, async () => {
      if (await ctx.confirm(t.surePasswords)) change({ op: "clear", what: "passwords" }, passwords);
    });
    const row = el("div", "places-actions sites-kept-actions");
    row.append(all, passwords);
    kept.append(row, el("p", "sites-faint", t.passwordsNote));
  }

  // A panel in the look every place in 连接 opens: a head with a badge, a title and ×, a body, a foot.
  function panel(cls, onClose) {
    const dialog = el("dialog", `places-root places-sheet ${cls}`);
    dialog.lang = document.documentElement.lang;
    const head = el("header", "places-sheet-head");
    const badge = el("span", "");
    const title = el("h2", "places-sheet-title");
    const close = el("button", "places-sheet-close");
    close.type = "button";
    close.title = t.close;
    close.setAttribute("aria-label", t.close);
    close.append(icon(CROSS));
    close.addEventListener("click", onClose);
    head.append(badge, title, close);
    const body = el("div", "places-sheet-body");
    const foot = el("footer", "places-sheet-foot");
    dialog.append(head, body, foot);
    dialog.addEventListener("cancel", (event) => {
      event.preventDefault();
      onClose();
    });
    dialog.addEventListener("click", (event) => event.target === dialog && onClose());
    document.body.append(dialog);
    return { dialog, badge, title, body, foot };
  }

  // ---- 登录网站: the well-known sites by their own marks, mail after, and any other address
  const picker = {
    open() {
      if (!this.dialog) Object.assign(this, panel("sites-picker", () => this.close()));
      this.badge.replaceWith((this.badge = el("span", "places-mark sites-mark")));
      this.badge.append(icon(PLUS));
      this.title.textContent = t.pickTitle;
      const groups = [[t.pickSites, data.picks.filter((p) => !p.mail)], [t.pickMail, data.picks.filter((p) => p.mail)]];
      const nodes = [el("p", "sites-about", t.pickAbout)];
      for (const [label, picks] of groups) {
        const grid = el("div", "sites-pick-grid");
        for (const pick of picks) {
          const item = el("button", "sites-pick");
          item.type = "button";
          item.append(mark(pick), el("span", "sites-pick-name", pick.name));
          item.addEventListener("click", async () => {
            for (const b of grid.querySelectorAll("button")) b.disabled = true;
            if (await signIn({ id: pick.id }, item)) this.close();
            for (const b of grid.querySelectorAll("button")) b.disabled = false;
          });
          grid.append(item);
        }
        nodes.push(el("p", "sites-choices-title sites-pick-label", label), grid);
      }
      const form = el("form", "sites-add");
      const input = el("input", "places-input");
      input.type = "text";
      input.spellcheck = false;
      input.autocomplete = "off";
      input.placeholder = t.otherHint;
      input.setAttribute("aria-label", t.otherHint);
      const go = el("button", "places-btn places-btn-secondary places-btn-sm");
      go.type = "submit";
      go.append(el("span", "", t.other));
      form.append(input, go);
      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        if (input.value.trim() && (await signIn({ url: input.value.trim() }, go))) this.close();
      });
      nodes.push(form);
      this.body.replaceChildren(...nodes);
      this.foot.replaceChildren(el("span", "places-gap"), button("places-btn-secondary", t.close, () => this.close()));
      if (!this.dialog.open) this.dialog.showModal();
    },
    close() {
      if (this.dialog?.open) this.dialog.close();
    },
  };

  // ---- one site's choices
  const sheet = {
    site: "",
    fresh: false,
    open(site, fresh = false) {
      if (!this.dialog) Object.assign(this, panel("sites-sheet", () => this.close()));
      this.body.classList.add("sites-sheet-body");
      this.site = site;
      this.fresh = fresh;
      this.draw();
      if (!this.dialog.open) this.dialog.showModal();
    },
    draw() {
      const row = data.sites.find((r) => r.site === this.site);
      if (!row) return this.close();
      this.badge.replaceWith((this.badge = mark(row)));
      this.title.textContent = row.name;
      const nodes = [];
      const state = el("div", "sites-sheet-state");
      state.dataset.state = row.state;
      state.append(el("span", "places-pill", t.state[row.state]), el("span", "sites-faint", line(row)));
      nodes.push(state);
      if (this.fresh) nodes.push(el("p", "sites-fresh", paI18n.t("sites.fresh", { name: row.name, example: row.example })));
      const group = el("div", "sites-choices");
      group.append(el("p", "sites-choices-title", t.allowTitle));
      for (const name of ["here", "task", "background", "auto"]) {
        const [label, help] = t.choices[name];
        const on = name === "auto" ? row.auto === "always" : row[name];
        const item = el("label", "sites-choice");
        const words = el("span", "sites-choice-words");
        words.append(el("span", "sites-choice-name", label), el("span", "sites-choice-help", help));
        if (name === "background" && row.stopped) words.append(el("span", "sites-choice-help sites-choice-warn", t.stopped));
        const box = el("input", "places-switch");
        box.type = "checkbox";
        box.setAttribute("role", "switch");
        box.checked = on;
        box.addEventListener("change", async () => {
          const next = await change({ op: "choose", site: row.site, name, on: box.checked });
          if (!next) box.checked = !box.checked;
        });
        item.append(words, box);
        group.append(item);
      }
      nodes.push(group);
      // What the person chose 始终允许 for on this site, each taken back here.
      if (row.allowed.length) {
        const allowed = el("div", "sites-choices");
        allowed.append(el("p", "sites-choices-title", t.allowedTitle));
        for (const kind of row.allowed) {
          const item = el("div", "sites-choice");
          const words = el("span", "sites-choice-words");
          words.append(el("span", "sites-choice-name", t.allowedKind[kind] || kind));
          const off = button("places-btn-secondary places-btn-quiet places-btn-sm", t.allowedOff, async () => {
            const done = await busy(off, () => call("browser/allowed", { site: row.site, kind, on: false }));
            if (done) load();
          });
          item.append(words, off);
          allowed.append(item);
        }
        nodes.push(allowed, el("p", "sites-faint", t.allowedNote));
      }
      this.body.replaceChildren(...nodes);
      const act = row.state === "in"
        ? button("places-btn-secondary places-btn-sm", t.signOut, () => signOut(row, act))
        : button("places-btn-secondary places-btn-sm", t.signIn, () => {
          this.close();
          signIn({ url: row.home }, act);
        });
      this.foot.replaceChildren(act, el("span", "places-gap"), button("places-btn-primary", t.done, () => this.close()));
    },
    close() {
      this.site = "";
      this.fresh = false;
      if (this.dialog?.open) this.dialog.close();
    },
  };

  async function load() {
    try {
      data = await call("signins");
      say("");
      paint();
    } catch {
      say(t.unavailable);
    }
  }

  function mount(root, context) {
    ctx = context;
    t = paI18n.words("sites");
    const box = el("section", "sites");
    const head = el("div", "sites-head");
    const titles = el("div", "sites-head-words");
    titles.append(el("h3", "sites-title", t.title), el("p", "sites-about", t.about));
    const add = button("places-btn-secondary places-btn-sm", t.add, () => data && picker.open(), PLUS);
    head.append(titles, add);
    said = el("div", "places-alert");
    said.setAttribute("role", "alert");
    said.hidden = true;
    waitLine = el("p", "sites-wait");
    waitLine.hidden = true;
    list = el("div", "places-services sites-list");
    kept = el("div", "sites-kept");
    box.append(head, said, waitLine, list, kept);
    root.append(box);
    // Back to the window after signing in elsewhere in it: the list as it is now.
    document.addEventListener("visibilitychange", () => !document.hidden && data && load());
  }

  window.paSites = { mount, show: load };
})();
