"use strict";
// Settings › About: the version, updates and the licences. Whether a new release is out and how this copy is
// updated (GET /api/runtime, POST /api/runtime/check), the update itself on a press (POST /api/runtime/update,
// mibo/updates.py), and what became of the one the last run began.
(() => {
  const NOTICE = "https://github.com/wangkant/mibo/blob/main/NOTICE";
  // While an update downloads, is checked or installs, the page asks how it goes this often.
  const POLL_MS = 500;
  const BUSY = new Set(["downloading", "verifying", "installing"]);
  // The ways of running that update from here, and the words of the others.
  const OWN = new Set(["installer", "macos"]);
  const HOW = { installer: "installerText", macos: "macText", zip: "zipText", pip: "pipText", checkout: "checkoutText" };

  window.paSetup.part("about", (kit) => {
    const { el, fill } = kit;
    const t = kit.words("setup_about");
    const ctx = kit.ctx;
    const node = kit.section("about");
    const box = kit.card();
    box.classList.add("setup-options");
    const version = kit.optionRow(t.version, "", el("span", "setup-option-value"));
    const up = buildUpdates();
    const licences = kit.optionRow(t.licences, t.licenceText);
    licences.words.append(kit.link(t.licenceLink, NOTICE, true));
    box.append(kit.item("version", version.row), kit.item("updates", up.row), kit.item("licences", licences.row));
    node.append(box);
    let info = null;
    let checking = false;
    let starting = false;
    let timer = null;

    function buildUpdates() {
      const go = kit.button("setup-button-primary setup-button-sm", "", update);
      const check = kit.button("setup-button-secondary setup-button-sm", t.check, checkNow);
      const buttons = el("div", "setup-option-actions");
      buttons.append(go, check);
      const { row, about } = kit.optionRow(t.updateTitle, "", buttons);
      row.hidden = true;
      const meter = el("div", "setup-meter");
      meter.setAttribute("role", "progressbar");
      meter.setAttribute("aria-valuemin", "0");
      meter.setAttribute("aria-valuemax", "100");
      const detail = el("p", "setup-option-text");
      const command = el("code", "setup-command");
      const notes = kit.link(t.notes, "", true);
      const error = kit.errorLine();
      about.after(meter, detail, command, notes, error);
      return { row, about, meter, detail, command, notes, go, check, error };
    }

    const megabytes = (bytes) => (bytes / 1048576).toFixed(1);

    function render() {
      const job = info.job;
      const busy = Boolean(job && BUSY.has(job.state));
      const opened = job?.state === "opened";
      const found = info.update;
      const lines = [];
      if (busy || opened)
        lines.push(fill(t[job.state], { v: job.version, done: megabytes(job.done), total: megabytes(job.total) }));
      else {
        const was = info.updated;
        if (was) lines.push(fill(was.ok ? t.updated : t.updateFailed, { v: was.version, current: info.version }));
        if (found) lines.push(fill(t.newer, { v: found.version }));
        else if (info.checkFailed) lines.push(t.unknown);
        else if (!was) lines.push(info.checked ? t.latest : t.never);
      }
      up.about.textContent = lines.join(t.join);
      up.about.hidden = false;
      // The bar while the file comes in.
      const share = job?.total ? Math.round((job.done / job.total) * 100) : 0;
      up.meter.hidden = job?.state !== "downloading";
      up.meter.style.setProperty("--done", `${share}%`);
      up.meter.setAttribute("aria-valuenow", String(share));
      // What a press does, or how this copy is updated instead.
      const offer = Boolean(found) && !busy && !opened;
      up.detail.textContent = offer && HOW[info.how] ? t[HOW[info.how]] : offer ? t.otherText : "";
      up.detail.hidden = !up.detail.textContent;
      up.command.textContent = offer ? info.command : "";
      up.command.hidden = !up.command.textContent;
      // The release page: its notes, or the installer by hand when the update did not go through.
      const failedJob = job?.state === "failed";
      const page = found?.url || (info.updated && !info.updated.ok ? info.updated.url : "");
      up.notes.href = page;
      up.notes.hidden = !page || busy;
      up.notes.firstChild.textContent = failedJob || (info.updated && !info.updated.ok) ? t.release : t.notes;
      if (failedJob) {
        up.error.textContent = t.errors[job.error] || t.errors.generic;
        up.error.hidden = false;
      }
      up.go.hidden = !(offer && OWN.has(info.how));
      if (found) kit.busy(up.go, starting, fill(info.how === "macos" ? t.download : t.update, { v: found.version }));
      kit.busy(up.check, checking, checking ? t.checking : t.check);
      up.check.disabled = checking || busy;
      up.row.hidden = false;
    }

    function follow() {
      clearTimeout(timer);
      if (info?.job && BUSY.has(info.job.state) && node.isConnected) timer = setTimeout(load, POLL_MS);
    }

    async function load() {
      try {
        info = await ctx.api("runtime");
      } catch (error) {
        // Installing: the app has closed for the installer, and its window goes with it.
        if (info?.job?.state === "installing") return;
        up.row.hidden = false;
        kit.failed(up.error, error, t);
        return;
      }
      render();
      follow();
    }

    async function checkNow() {
      checking = true;
      up.error.hidden = true;
      if (info) render();
      try {
        info = await ctx.api("runtime/check", {});
      } catch (error) {
        kit.failed(up.error, error, t);
      } finally {
        checking = false;
        if (info) render();
      }
    }

    // A press is the person's decision: the app takes the version its own check found, nothing from here.
    async function update() {
      starting = true;
      up.error.hidden = true;
      render();
      try {
        info = await ctx.api("runtime/update", {});
      } catch (error) {
        kit.failed(up.error, error, t);
      } finally {
        starting = false;
        render();
        follow();
      }
    }

    function show() {
      version.row.lastChild.textContent = kit.state.version;
      up.error.hidden = true;
      load();
    }

    return { node, show };
  });
})();
