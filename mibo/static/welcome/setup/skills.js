"use strict";
// Settings › Skills, two views. Installed: the skills the character may load when a request fits one (/api/skills),
// a switch each, where each came from and its version, updates from the market, removing one, adding one from a
// folder, a zip or an address on a public git host, and copying in the ones other agents keep in this profile.
// Market: the catalog of public skills (/api/skills/market), searched and sorted here, a detail view with what a
// skill needs, its licence, its source and the scan's result, and its SKILL.md read from the source at that moment.
// The catalog is data from the network: every string goes on the page as text, never as markup. What a skill may
// do is decided by the app (mibo/skills): it is guidance only, and every action still asks on its card.
(() => {
  const MAX_UPLOAD = 64 * 1024 * 1024;
  const SVG = "http://www.w3.org/2000/svg";
  const MARKS = {
    search: "M10.5 4a6.5 6.5 0 1 0 0 13 6.5 6.5 0 0 0 0-13zM15.3 15.3L20 20",
    back: "M15 6l-6 6 6 6",
    star: "M12 4.5l2.2 4.6 5 .7-3.6 3.5.9 5-4.5-2.4-4.5 2.4.9-5-3.6-3.5 5-.7z",
    skill: "M5.5 4.5h9l4 4v11a1 1 0 0 1-1 1h-12a1 1 0 0 1-1-1v-14a1 1 0 0 1 1-1zM14.5 4.5v4h4M8.5 12.5h7M8.5 16h5",
    check: "M5 12.5l4.2 4.2L19 7",
  };

  // A zip of the chosen folder's files, stored without compression, for /api/skills/upload.
  const CRC = (() => {
    const table = new Uint32Array(256);
    for (let n = 0; n < 256; n++) {
      let c = n;
      for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
      table[n] = c >>> 0;
    }
    return (bytes) => {
      let c = 0xffffffff;
      for (let i = 0; i < bytes.length; i++) c = table[(c ^ bytes[i]) & 0xff] ^ (c >>> 8);
      return (c ^ 0xffffffff) >>> 0;
    };
  })();
  async function zipOf(files) {
    const parts = [];
    const central = [];
    let offset = 0;
    const encoder = new TextEncoder();
    for (const file of files) {
      const name = encoder.encode(file.webkitRelativePath || file.name);
      const data = new Uint8Array(await file.arrayBuffer());
      const crc = CRC(data);
      const head = new DataView(new ArrayBuffer(30));
      head.setUint32(0, 0x04034b50, true);
      head.setUint16(4, 20, true);
      head.setUint16(6, 0x0800, true);
      head.setUint32(14, crc, true);
      head.setUint32(18, data.length, true);
      head.setUint32(22, data.length, true);
      head.setUint16(26, name.length, true);
      parts.push(head, name, data);
      const entry = new DataView(new ArrayBuffer(46));
      entry.setUint32(0, 0x02014b50, true);
      entry.setUint16(4, 20, true);
      entry.setUint16(6, 20, true);
      entry.setUint16(8, 0x0800, true);
      entry.setUint32(16, crc, true);
      entry.setUint32(20, data.length, true);
      entry.setUint32(24, data.length, true);
      entry.setUint16(28, name.length, true);
      entry.setUint32(42, offset, true);
      central.push(entry, name);
      offset += 30 + name.length + data.length;
    }
    const size = central.reduce((sum, part) => sum + part.byteLength, 0);
    const end = new DataView(new ArrayBuffer(22));
    end.setUint32(0, 0x06054b50, true);
    end.setUint16(8, files.length, true);
    end.setUint16(10, files.length, true);
    end.setUint32(12, size, true);
    end.setUint32(16, offset, true);
    return new Blob([...parts, ...central, end], { type: "application/zip" });
  }

  window.paSetup.part("skills", (kit) => {
    const { el } = kit;
    const t = kit.words("setup_skills");
    const ctx = kit.ctx;
    const zh = kit.lang === "zh";
    const node = kit.section("skills", t.hint);
    let view = null;
    let market = null;
    let shown = "installed";
    const query = { text: "", category: "", sort: "popular" };
    let detailId = "";

    function mark(name, cls) {
      const svg = document.createElementNS(SVG, "svg");
      svg.setAttribute("viewBox", "0 0 24 24");
      svg.setAttribute("aria-hidden", "true");
      svg.setAttribute("class", cls);
      const path = document.createElementNS(SVG, "path");
      path.setAttribute("d", MARKS[name]);
      svg.append(path);
      return svg;
    }
    function link(text, href) {
      const a = el("a", "setup-link", text);
      a.href = href;
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      return a;
    }
    const short = (sha) => String(sha || "").slice(0, 7);
    function count(n) {
      if (zh) return n >= 10000 ? `${(n / 10000).toFixed(n >= 100000 ? 0 : 1).replace(/\.0$/, "")} 万` : String(n);
      return n >= 1000 ? `${(n / 1000).toFixed(n >= 10000 ? 0 : 1).replace(/\.0$/, "")}k` : String(n);
    }
    const title = (one) => (zh ? one.title.zh : one.title.en) || one.title.en || one.title.zh || one.name;
    const about = (one) => (zh ? one.about.zh : one.about.en) || one.about.en || one.about.zh || "";

    // ---- The two views
    const head = el("div", "skm-head");
    const tabs = kit.choices(t.views, [["installed", t.installedTab], ["market", t.marketTab]], (value) => switchTo(value));
    head.append(tabs.group);
    const installedPane = el("div", "skm-pane");
    const marketPane = el("div", "skm-pane");
    node.append(head, installedPane, marketPane);

    // ================================================================ installed

    const toolbar = el("div", "skm-toolbar");
    const countLine = el("p", "skm-count");
    const updateAll = kit.button("setup-button-primary setup-button-sm", "", () => updateEvery());
    updateAll.hidden = true;
    const importOpen = kit.button("setup-button-secondary setup-button-sm", t.importOpen, () => lookElsewhere());
    const open = kit.button("setup-button-secondary setup-button-sm", t.openFolder, () => change({ open: true }));
    const tools = el("div", "skm-toolbar-actions");
    tools.append(updateAll, importOpen, open);
    toolbar.append(countLine, tools);
    const installedNote = el("p", "setup-help skm-done");
    installedNote.setAttribute("role", "status");
    installedNote.hidden = true;

    const importCard = kit.card(t.importTitle);
    importCard.hidden = true;
    const importHelp = el("p", "setup-help", t.importHelp);
    const importList = el("div", "setup-options");
    const importError = kit.errorLine();
    const importGo = kit.button("setup-button-primary setup-button-sm", paI18n.t("setup_skills.importGo", { count: 0 }), () => importChosen());
    const importClose = kit.button("setup-button-ghost setup-button-sm", t.importCancel, () => {
      importCard.hidden = true;
    });
    const importButtons = el("div", "skm-row");
    importButtons.append(importGo, importClose);
    importCard.append(importHelp, importList, importError, importButtons);

    const listCard = kit.card(t.listTitle);
    const list = el("div", "setup-options");
    const listError = kit.errorLine();
    listCard.append(list, listError);

    const addFold = kit.fold(t.addTitle);
    addFold.node.classList.add("skm-add");
    const addText = el("p", "setup-help", t.addText);
    const folderPicker = el("input");
    folderPicker.type = "file";
    folderPicker.hidden = true;
    folderPicker.webkitdirectory = true;
    folderPicker.multiple = true;
    const zipPicker = el("input");
    zipPicker.type = "file";
    zipPicker.hidden = true;
    zipPicker.accept = ".zip,application/zip";
    const pickFolder = kit.button("setup-button-secondary setup-button-sm", t.pickFolder, () => folderPicker.click());
    const pickZip = kit.button("setup-button-secondary setup-button-sm", t.pickZip, () => zipPicker.click());
    const picks = el("div", "setup-shell-add");
    picks.append(pickFolder, pickZip, folderPicker, zipPicker);
    const address = kit.input();
    address.placeholder = t.addressPlaceholder;
    const addAddress = kit.button("setup-button-secondary setup-button-sm", t.addAddress, () => fetchAddress());
    address.addEventListener("keydown", (event) => {
      if (event.key === "Enter") fetchAddress();
    });
    const addressRow = el("div", "setup-shell-add");
    addressRow.append(address, addAddress);
    const addError = kit.errorLine();
    const addDone = el("p", "setup-help");
    addDone.hidden = true;
    addFold.body.append(addText, picks, addressRow, addError, addDone);
    installedPane.append(toolbar, installedNote, importCard, listCard, addFold.node);

    function marketOf(row) {
      return row.market && market ? market.skills.find((one) => one.id === row.market) : null;
    }

    function originOf(row) {
      if (row.builtin) return t.builtin;
      if (row.origin === "market") {
        const one = marketOf(row);
        return kit.fill(t.fromMarket, { publisher: one ? one.publisher : String(row.market).split("/")[0] });
      }
      if (row.origin === "address") {
        const where = String(row.source || "").replace(/^https?:\/\//, "").replace(/\/$/, "");
        return kit.fill(t.fromAddress, { where });
      }
      if (row.origin === "import") return kit.fill(t.fromImport, { host: String(row.source || "").split(":")[0] });
      return row.origin === "zip" ? t.fromZip : t.fromFolder;
    }

    function renderInstalled() {
      const waiting = market ? market.skills.filter((one) => one.update) : [];
      countLine.textContent = paI18n.t("setup_skills.count", { count: view.skills.length });
      updateAll.hidden = !waiting.length;
      kit.relabel(updateAll, paI18n.t("setup_skills.updateAll", { count: waiting.length }));
      if (!view.skills.length) return list.replaceChildren(el("p", "setup-help", t.none));
      list.replaceChildren(...view.skills.map((row) => {
        const usable = !row.problems.length;
        const name = (zh && row.title_zh) || row.name;
        const what = (zh && row.description_zh) || row.description;
        const line = kit.switchRow(`skill-${row.folder}`, name, what, (box) => change({ name: row.name, on: box.checked }));
        line.box.checked = row.on && usable;
        line.box.disabled = !usable;
        line.about.classList.add("skm-clamp");
        const meta = el("div", "skm-meta");
        meta.append(el("span", "", [originOf(row), row.name !== name ? row.name : ""].filter(Boolean).join(" · ")));
        if (/^[0-9a-f]{7,}$/.test(row.ref)) meta.append(el("span", "", kit.fill(t.version, { ref: short(row.ref) })));
        const one = marketOf(row);
        if (one?.update) {
          meta.append(el("span", "skm-badge skm-badge-new", t.updateReady));
          const go = kit.button("setup-button-link", t.update, () => updateOne(one, go));
          meta.append(go);
        }
        line.words.append(meta);
        if (!usable) {
          const why = row.problems.map((code) => t.problems[code] || code).join(zh ? "；" : "; ");
          line.words.append(el("p", "setup-error", kit.fill(t.unusable, { why })));
        } else if (row.warnings.length) {
          line.words.append(el("p", "setup-help", row.warnings.map((code) => t.warnings[code] || code).join(zh ? "；" : "; ")));
        }
        // Built-in ones have no remove button; the space keeps every switch in one column.
        const off = row.builtin ? el("span", "skm-off-space") : kit.iconButton("setup-word-off", "cross", paI18n.t("setup_skills.remove", { name }), () => removeSkill(row, name));
        line.row.append(off);
        return line.row;
      }));
    }

    async function loadInstalled() {
      try {
        view = await ctx.api("skills");
        listError.hidden = true;
        renderInstalled();
      } catch (error) {
        kit.failed(listError, error, t);
      }
    }

    async function change(what, line = listError) {
      line.hidden = true;
      try {
        view = await ctx.api("skills", what);
        if (market && what.remove) market = await ctx.api("skills/market");
        renderInstalled();
      } catch (error) {
        kit.failed(line, error, t);
        if (view) renderInstalled();
      }
    }

    async function removeSkill(row, name) {
      const sure = await ctx.confirm({ title: kit.fill(t.removeAsk, { name }), text: t.removeText, ok: t.removeOk });
      if (sure) change({ remove: row.folder });
    }

    function said(text) {
      installedNote.textContent = text;
      installedNote.hidden = !text;
    }

    async function updateOne(one, button) {
      said("");
      listError.hidden = true;
      kit.busy(button, true, t.updating);
      try {
        took(await ctx.api("skills/market", { install: one.id }));
        said(t.updated);
      } catch (error) {
        kit.failed(listError, error, t);
        kit.busy(button, false, t.update);
      }
    }

    async function updateEvery() {
      said("");
      listError.hidden = true;
      const label = updateAll.querySelector(".setup-button-label").textContent;
      kit.busy(updateAll, true, t.updating);
      try {
        took(await ctx.api("skills/market", { update_all: true }));
        said(t.updated);
      } catch (error) {
        kit.failed(listError, error, t);
      } finally {
        kit.busy(updateAll, false, label);
        if (view) renderInstalled();
      }
    }

    // The market's answer carries both views as they now are.
    function took(value) {
      view = value.installed_view;
      market = value;
      renderInstalled();
      if (shown === "market") renderMarket();
    }

    // ---- Skills other agents keep in this profile: looked for only on the press.
    let found = [];
    const chosen = new Set();
    async function lookElsewhere() {
      importCard.hidden = false;
      importError.hidden = true;
      chosen.clear();
      importList.replaceChildren(el("p", "setup-help", t.importLooking));
      importGo.hidden = true;
      kit.busy(importOpen, true, t.importLooking);
      try {
        found = (await ctx.api("skills/hosts", { list: true })).found;
        renderFound();
      } catch (error) {
        importList.replaceChildren();
        kit.failed(importError, error, t);
      } finally {
        kit.busy(importOpen, false, t.importOpen);
      }
    }
    function renderFound() {
      const have = new Set(view.skills.map((row) => row.name));
      const usable = found.filter((row) => !row.problems.length);
      importGo.hidden = !usable.length;
      kit.relabel(importGo, paI18n.t("setup_skills.importGo", { count: 0 }));
      if (!usable.length) return importList.replaceChildren(el("p", "setup-help", t.importNone));
      importList.replaceChildren(...usable.map((row, n) => {
        const line = kit.switchRow(`import-${n}`, row.name, row.description, (box) => {
          if (box.checked) chosen.add(row.path);
          else chosen.delete(row.path);
          kit.relabel(importGo, paI18n.t("setup_skills.importGo", { count: chosen.size }));
        });
        // A tick each, not a switch: these are chosen, not turned on.
        line.box.className = "skm-check";
        line.box.removeAttribute("role");
        line.about.classList.add("skm-clamp");
        line.words.append(el("p", "skm-meta skm-path", `${row.host} · ${row.path}`));
        if (have.has(row.name)) {
          line.box.disabled = true;
          line.words.append(el("p", "skm-meta", t.importHave));
        }
        return line.row;
      }));
    }
    async function importChosen() {
      if (!chosen.size) return;
      importError.hidden = true;
      kit.busy(importGo, true, t.importing);
      try {
        const value = await ctx.api("skills/hosts", { import: [...chosen] });
        view = value;
        renderInstalled();
        importCard.hidden = true;
        said(paI18n.t("setup_skills.added", { names: (value.added || []).join(t.listSep) }));
      } catch (error) {
        kit.failed(importError, error, t);
      } finally {
        kit.busy(importGo, false, paI18n.t("setup_skills.importGo", { count: chosen.size }));
      }
    }

    // ---- Adding from this computer or an address
    async function adding(button, work) {
      addError.hidden = addDone.hidden = true;
      for (const b of [pickFolder, pickZip, addAddress]) b.disabled = true;
      const label = button.querySelector(".setup-button-label").textContent;
      kit.busy(button, true, t.adding);
      try {
        const value = await work();
        view = value;
        renderInstalled();
        addDone.textContent = paI18n.t("setup_skills.added", { names: (value.added || []).join(t.listSep) });
        addDone.hidden = false;
      } catch (error) {
        kit.failed(addError, error, t);
      } finally {
        kit.busy(button, false, label);
        for (const b of [pickFolder, pickZip, addAddress]) b.disabled = false;
      }
    }
    function upload(blob, origin, label) {
      if (blob.size > MAX_UPLOAD) throw new Error("skill_too_large");
      return ctx.api(`skills/upload?origin=${origin}&label=${encodeURIComponent(label)}`, blob);
    }
    folderPicker.addEventListener("change", () => {
      const files = [...folderPicker.files];
      folderPicker.value = "";
      if (!files.length) {
        addError.textContent = t.errors.skill_folder_empty;
        addError.hidden = false;
        return;
      }
      const label = (files[0].webkitRelativePath || files[0].name).split("/")[0];
      adding(pickFolder, async () => upload(await zipOf(files), "folder", label));
    });
    zipPicker.addEventListener("change", () => {
      const file = zipPicker.files[0];
      zipPicker.value = "";
      if (file) adding(pickZip, () => upload(file, "zip", file.name));
    });
    function fetchAddress() {
      const text = address.value.trim();
      if (!text) return;
      adding(addAddress, async () => {
        const value = await ctx.api("skills/fetch", { address: text });
        address.value = "";
        return value;
      });
    }

    // ================================================================== market

    const controls = el("div", "skm-controls");
    const searchWrap = el("label", "skm-search");
    const search = kit.input("skm-search-input");
    search.type = "search";
    search.placeholder = t.search;
    search.setAttribute("aria-label", t.search);
    searchWrap.append(mark("search", "skm-search-icon"), search);
    const sort = el("select", "setup-input setup-select setup-input-sm skm-sort");
    sort.setAttribute("aria-label", t.sort);
    for (const [value, text] of [["popular", t.sortPopular], ["recent", t.sortRecent]]) {
      const option = el("option", "", text);
      option.value = value;
      sort.append(option);
    }
    const chips = el("div", "skm-chips");
    chips.setAttribute("role", "toolbar");
    // The catalog's date on the left, the order on the right, under the categories.
    const status = el("p", "skm-status");
    const statusRow = el("div", "skm-filters");
    statusRow.append(status, sort);
    controls.append(searchWrap, chips, statusRow);
    const marketError = kit.errorLine();
    const retry = kit.button("setup-button-secondary setup-button-sm skm-retry", t.retry, () => loadMarket(true));
    retry.hidden = true;
    const grid = el("div", "skm-grid");
    const detail = el("div", "skm-detail");
    detail.hidden = true;
    const flashLine = el("p", "skm-flash");
    flashLine.setAttribute("role", "status");
    marketPane.append(controls, marketError, retry, grid, detail, flashLine);

    let typing = null;
    search.addEventListener("input", () => {
      clearTimeout(typing);
      typing = setTimeout(() => {
        query.text = search.value.trim();
        renderGrid();
      }, 120);
    });
    sort.addEventListener("change", () => {
      query.sort = sort.value;
      renderGrid();
    });

    let flashTimer = null;
    function flash(text) {
      flashLine.textContent = text;
      flashLine.classList.add("on");
      clearTimeout(flashTimer);
      flashTimer = setTimeout(() => flashLine.classList.remove("on"), 2600);
    }

    function loadingGrid() {
      const blocks = [];
      for (let i = 0; i < 6; i++) blocks.push(el("div", "skm-card skm-card-loading"));
      grid.replaceChildren(...blocks);
      status.textContent = t.loading;
    }

    async function loadMarket(again = false) {
      marketError.hidden = retry.hidden = true;
      if (!market || again) loadingGrid();
      try {
        // 重试 fetches the catalog again now; otherwise it is fetched at most once a day.
        market = await ctx.api(again ? "skills/market?again=true" : "skills/market");
        if (view) renderInstalled();
        renderMarket();
      } catch (error) {
        grid.replaceChildren();
        status.textContent = "";
        kit.failed(marketError, error, t);
        retry.hidden = false;
      }
    }

    function renderMarket() {
      const date = String(market.built_at || "").slice(0, 10);
      const offline = market.from !== "live" && market.refresh_failed;
      status.textContent = !market.skills.length ? t.catalogNone
        : market.from === "live" ? kit.fill(t.catalogLive, { date })
          : kit.fill(offline ? t.catalogOffline : t.catalogSnapshot, { date });
      status.classList.toggle("skm-status-offline", offline || !market.skills.length);
      retry.hidden = Boolean(market.skills.length);
      // No catalog at all: the line and 重试, without a search or filters for nothing.
      searchWrap.hidden = chips.hidden = sort.hidden = !market.skills.length;
      if (!market.skills.length) {
        grid.replaceChildren();
        return;
      }
      renderChips();
      const one = market.skills.find((entry) => entry.id === detailId);
      if (one) renderDetail(one);
      else renderGrid();
    }

    function renderChips() {
      const names = market.categories || {};
      const used = new Set(market.skills.map((one) => one.category));
      const keys = ["", ...Object.keys(names).filter((key) => used.has(key))];
      chips.replaceChildren(...keys.map((key) => {
        const chip = el("button", "skm-chip", key ? (zh ? names[key].zh : names[key].en) : t.allCategories);
        chip.type = "button";
        chip.setAttribute("aria-pressed", String(query.category === key));
        chip.addEventListener("click", () => {
          query.category = key;
          renderChips();
          renderGrid();
        });
        return chip;
      }));
    }

    // How well an entry fits what was typed, from its names, what it does, its tags and its publisher; 0 is no fit.
    // A Latin word must be there. Chinese is written without spaces ("整理表格", "查文献"), so a Chinese word that
    // is not there whole counts by its two-character pieces, the rarer ones more ("表格" says more than "整理"), and
    // a lone character ("做") may be missing.
    const CJK = /[㐀-鿿]/;
    const texts = new WeakMap();
    function textOf(one) {
      if (!texts.has(one)) {
        const names = market.categories?.[one.category] || {};
        texts.set(one, [one.name, one.id, one.title.zh, one.title.en, one.about.zh, one.about.en, one.publisher,
          ...one.tags, names.zh, names.en].join(" ").toLowerCase());
      }
      return texts.get(one);
    }
    function piecesOf(word) {
      const pairs = [];
      for (let i = 0; i + 1 < word.length; i++) pairs.push(word.slice(i, i + 2));
      return pairs;
    }
    function fitOf(text, words, weight) {
      let total = 0;
      for (const word of words) {
        if (text.includes(word)) {
          total += 10;
          continue;
        }
        if (!CJK.test(word)) return 0;
        const pairs = piecesOf(word);
        const hit = pairs.filter((pair) => text.includes(pair));
        if (pairs.length && !hit.length) return 0;
        total += hit.reduce((sum, pair) => sum + weight.get(pair), 0);
      }
      return words.length ? total : 1;
    }
    const popularity = (one) => one.popularity.installs ?? one.popularity.stars ?? -1;
    const USABLE = ["ready", "partial", "no"];
    // A need said as a request ("查文献", "帮我整理表格") is looked up by its object.
    const ASKING = /^(?:帮我|请|我想|我要|想要|需要|如何|怎么|怎样|给我|做个|做|写|查|找|搜|整理|生成|制作|处理|分析)+/; // copy: voice
    function listed() {
      const words = query.text.toLowerCase().split(/\s+/).filter(Boolean)
        .map((word) => (CJK.test(word) && word.replace(ASKING, "").length >= 2 ? word.replace(ASKING, "") : word));
      const weight = new Map();
      for (const word of words) if (CJK.test(word)) for (const pair of piecesOf(word)) weight.set(pair, 0);
      if (weight.size) {
        for (const one of market.skills) for (const pair of weight.keys()) if (textOf(one).includes(pair)) weight.set(pair, weight.get(pair) + 1);
        for (const [pair, seen] of weight) weight.set(pair, Math.log((market.skills.length + 1) / (seen + 1)));
      }
      const rows = [];
      for (const one of market.skills) {
        const fit = !query.category || one.category === query.category ? fitOf(textOf(one), words, weight) : 0;
        if (fit > 0) rows.push({ one, fit: Math.round(fit), use: words.length ? USABLE.indexOf(one.fit) : 0 });
      }
      // The closer fits first and, for a search, the ones that work in Mibo as they are; then the chosen order.
      return rows.sort((a, b) => b.fit - a.fit || a.use - b.use || (query.sort === "recent"
        ? String(b.one.updated).localeCompare(String(a.one.updated)) || popularity(b.one) - popularity(a.one)
        : popularity(b.one) - popularity(a.one) || String(b.one.updated).localeCompare(String(a.one.updated))))
        .map((row) => row.one);
    }

    // What an entry is from here: installable as it is, after a word on its licence, or only to be looked at.
    // The app says which (market.can_install); a repository with no stated licence is asked about first.
    function stateOf(one) {
      if (one.blocked) return "view";
      return String(one.licence.spdx).toUpperCase() === "NONE" ? "unlicensed" : "ok";
    }
    function badges(one) {
      const row = el("div", "skm-badges");
      const state = stateOf(one);
      if (state === "view") row.append(el("span", "skm-badge", t.viewOnly));
      if (state === "unlicensed") row.append(el("span", "skm-badge", t.badgeUnlicensed));
      if (one.needs.scripts && state !== "view") row.append(el("span", "skm-badge", t.badgeScripts));
      if (one.fit === "partial") row.append(el("span", "skm-badge", t.badgePartial));
      if (one.fit === "no") row.append(el("span", "skm-badge", t.badgeNoFit));
      return row;
    }

    // Publishers' own pictures from their GitHub accounts, fetched once by the app; a plain mark until then.
    const pictures = new Map();
    function publisherMark(one, size) {
      const box = el("span", `skm-mark skm-mark-${size}`);
      box.append(mark("skill", "skm-mark-icon"));
      const owner = one.source.host === "github.com" ? one.source.repo.split("/")[0] : "";
      if (!owner) return box;
      if (!pictures.has(owner)) pictures.set(owner, ctx.picture(`/api/skills/market/mark/${encodeURIComponent(owner)}`).catch(() => ""));
      pictures.get(owner).then((url) => {
        if (!url) return;
        const img = el("img");
        img.alt = "";
        img.src = url;
        box.replaceChildren(img);
      });
      return box;
    }

    function actionFor(one, small) {
      const size = small ? "setup-button-sm" : "";
      if (one.installed && one.update) {
        const go = kit.button(`setup-button-primary ${size}`, t.update, (event) => {
          event.stopPropagation();
          installOne(one, go, t.update);
        });
        return go;
      }
      if (one.installed) {
        const done = el("span", "skm-installed");
        done.append(mark("check", "skm-installed-icon"), el("span", "", t.installed));
        return done;
      }
      if (stateOf(one) === "view") return null;
      const go = kit.button(`${small ? "setup-button-secondary" : "setup-button-primary"} ${size}`, t.install, (event) => {
        event.stopPropagation();
        installOne(one, go, t.install);
      });
      return go;
    }

    function renderGrid() {
      detail.hidden = true;
      controls.hidden = status.hidden = grid.hidden = false;
      const rows = listed();
      if (!rows.length) {
        const empty = el("div", "skm-empty");
        empty.append(el("p", "", query.text ? kit.fill(t.noMatch, { q: query.text }) : t.noMatchCategory));
        if (query.text) {
          empty.append(kit.button("setup-button-link", t.clear, () => {
            search.value = query.text = "";
            renderGrid();
          }));
        }
        return grid.replaceChildren(empty);
      }
      grid.replaceChildren(...rows.map((one) => {
        const card = el("article", "skm-card");
        card.tabIndex = 0;
        card.setAttribute("role", "button");
        card.setAttribute("aria-label", title(one));
        const top = el("div", "skm-card-top");
        const names = el("div", "skm-card-names");
        names.append(el("h4", "skm-card-title", title(one)), el("p", "skm-card-by", one.publisher));
        top.append(publisherMark(one, "sm"), names);
        const foot = el("div", "skm-card-foot");
        const left = badges(one);
        if (popularity(one) >= 0) {
          const pop = el("span", "skm-pop");
          pop.append(mark("star", "skm-pop-icon"), el("span", "", count(popularity(one))));
          left.prepend(pop);
        }
        foot.append(left);
        const action = actionFor(one, true);
        if (action) foot.append(action);
        card.append(top, el("p", "skm-card-about", about(one)), foot);
        card.addEventListener("click", () => openDetail(one.id));
        card.addEventListener("keydown", (event) => {
          if ((event.key === "Enter" || event.key === " ") && event.target === card) {
            event.preventDefault();
            openDetail(one.id);
          }
        });
        return card;
      }));
    }

    let detailError = kit.errorLine();
    async function installOne(one, button, label) {
      marketError.hidden = detailError.hidden = true;
      let unlicensedOk = false;
      if (!one.installed && stateOf(one) === "unlicensed") {
        unlicensedOk = await ctx.confirm({ title: t.unlicensedAsk, text: kit.fill(t.unlicensedText, { name: title(one) }), ok: t.unlicensedOk });
        if (!unlicensedOk) return;
      }
      kit.busy(button, true, one.installed ? t.updating : t.installing);
      try {
        took(await ctx.api("skills/market", { install: one.id, unlicensed_ok: unlicensedOk }));
        flash(one.installed ? t.updated : kit.fill(t.installedDone, { name: title(one) }));
      } catch (error) {
        kit.busy(button, false, label);
        kit.failed(detail.hidden ? marketError : detailError, error, t);
      }
    }

    // ---- One entry, in full
    function openDetail(id) {
      detailId = id;
      renderDetail(market.skills.find((one) => one.id === id));
      node.closest(".setup-page")?.parentElement?.scrollTo({ top: 0 });
    }
    function closeDetail() {
      detailId = "";
      renderGrid();
    }

    function fact(dl, name, ...values) {
      const dd = el("dd");
      for (const value of values) if (value) dd.append(typeof value === "string" ? el("p", "", value) : value);
      dl.append(el("dt", "", name), dd);
    }

    // A skill that needs an MCP server offers the connector the connector market lists for it (setup/tools.js).
    let connectors = [];
    function connectorOf(one) {
      if (!one.needs.tools.some((name) => name.toLowerCase() === "mcp")) return null;
      const text = [one.id, one.name, one.publisher, ...one.tags].join(" ").toLowerCase();
      return connectors.find((server) => server.match.some((word) => text.includes(word))) || null;
    }

    function cardsFor(one) {
      const used = one.needs.tools.map((name) => name.toLowerCase());
      const out = [];
      if (one.needs.scripts || used.some((name) => ["bash", "shell", "use_computer"].includes(name))) out.push(t.cardCommand);
      if (used.some((name) => ["write", "edit", "multiedit", "write_file", "edit_file"].includes(name))) out.push(t.cardFiles);
      return out;
    }

    function scanWords(one) {
      const box = el("div", "skm-scan");
      const level = one.scan.risk;
      box.append(el("p", `skm-scan-head skm-risk-${level}`, level === "high" ? t.scanHigh : level === "low" ? t.scanLow : t.scanNone));
      const notes = el("ul", "skm-scan-notes");
      for (const note of one.scan.notes) {
        const [code, ...rest] = String(note).split(":");
        const file = rest.join(":");
        notes.append(el("li", "", t.notes[code] ? t.notes[code] + (file ? kit.fill(t.noteIn, { file }) : "") : note));
      }
      if (notes.childElementCount) box.append(notes);
      return box;
    }

    function renderDetail(one) {
      controls.hidden = status.hidden = grid.hidden = true;
      marketError.hidden = true;
      detail.hidden = false;
      detailError = kit.errorLine();
      const back = el("button", "skm-back");
      back.type = "button";
      back.append(mark("back", "skm-back-icon"), el("span", "", t.back));
      back.addEventListener("click", closeDetail);

      const top = el("div", "skm-detail-top");
      const names = el("div", "skm-detail-names");
      names.append(el("h3", "skm-detail-title", title(one)));
      const by = el("p", "skm-detail-by");
      by.append(el("span", "", one.publisher), el("span", "", one.name));
      if (one.popularity.stars != null) by.append(el("span", "", paI18n.t("setup_skills.stars", { count: count(one.popularity.stars) })));
      names.append(by);
      const act = el("div", "skm-detail-act");
      const action = actionFor(one, false);
      if (action) act.append(action);
      if (one.installed) {
        const off = kit.button("setup-button-secondary", t.removeOk, async () => {
          const sure = await ctx.confirm({ title: kit.fill(t.removeAsk, { name: title(one) }), text: t.removeText, ok: t.removeOk });
          if (!sure) return;
          kit.busy(off, true);
          try {
            took(await ctx.api("skills/market", { remove: one.id }));
          } catch (error) {
            kit.busy(off, false);
            kit.failed(detailError, error, t);
          }
        });
        act.append(off);
      }
      if (!action && !one.installed) act.append(el("span", "skm-view-only", t.viewOnly));
      top.append(publisherMark(one, "lg"), names, act);

      // Why it cannot be installed, or what will be asked before it is, said once right under the button.
      const state = stateOf(one);
      const reason = one.scan.risk === "high" ? t.reasonHigh : state === "view" ? t.reasonLicence
        : state === "unlicensed" && !one.installed ? t.unlicensedBefore : one.fit === "no" ? t.reasonNoFit : "";
      const lead = el("div", "skm-detail-lead");
      if (reason) lead.append(el("p", `skm-reason${state === "view" ? " skm-reason-strong" : ""}`, reason));
      lead.append(el("p", "skm-detail-about", about(one)));
      const own = el("p", "skm-own");
      own.hidden = true;
      lead.append(own);

      const dl = el("dl", "skm-facts");
      const runtimes = one.needs.runtimes.map((name) => t.runtimes[name] || name);
      fact(dl, t.needs, runtimes.length ? runtimes.join(zh ? "、" : ", ") : t.needsNothing);
      const cards = cardsFor(one);
      fact(dl, t.cards, cards.length ? cards.join(zh ? "；" : "; ") : t.cardsNone);
      fact(dl, t.fit, one.fit === "ready" ? t.fitReady : one.fit_note || t.badgePartial);
      const server = connectorOf(one);
      if (server) {
        const name = zh ? server.title.zh : server.title.en;
        const line = el("p", "skm-inline");
        line.append(server.installed ? el("span", "", kit.fill(t.connectorHave, { name }))
          : kit.button("setup-button-secondary setup-button-sm", kit.fill(t.connectorGet, { name }), () => ctx.go(`setup/tools/market/${server.id}`)));
        fact(dl, t.connector, line);
      }
      const spdx = String(one.licence.spdx);
      const licenceName = spdx.toUpperCase() === "NONE" ? t.licenceNone : spdx.toUpperCase() === "CUSTOM" ? t.licenceCustom : spdx;
      const licenceLine = el("p", "skm-inline");
      licenceLine.append(el("span", "", licenceName));
      if (one.licence.url) licenceLine.append(link(t.licenceLink, one.licence.url));
      fact(dl, t.licence, licenceLine, one.licence.note);
      const sourceLine = el("p", "skm-inline");
      sourceLine.append(link(`${one.source.repo}${one.source.path ? `/${one.source.path}` : ""}`, one.source.url));
      fact(dl, t.source, sourceLine);
      const moved = el("p", "skm-moved");
      moved.hidden = true;
      fact(dl, t.reviewed, kit.fill(t.reviewedLine, { commit: short(one.source.commit), date: one.updated || "" }), moved);
      fact(dl, t.scan, scanWords(one));

      const previewCard = el("section", "skm-preview");
      const previewHead = el("div", "skm-preview-head");
      previewHead.append(el("h4", "", t.preview), el("span", "", t.previewNote));
      const pre = el("pre", "skm-preview-text", t.previewLoading);
      previewCard.append(previewHead, pre);

      detail.replaceChildren(back, top, detailError, lead, dl, previewCard);
      fillPreview(one, pre, moved, own);
    }

    // The SKILL.md and whether the source moved, asked once an entry while the page is open.
    const previews = new Map();
    async function fillPreview(one, pre, moved, own) {
      if (!previews.has(one.id)) {
        previews.set(one.id, ctx.api(`skills/market/detail?id=${encodeURIComponent(one.id)}`).catch(() => null));
      }
      const value = await previews.get(one.id);
      if (!pre.isConnected) return;
      if (!value?.fetched) {
        pre.textContent = t.previewFailed;
        pre.classList.add("skm-preview-failed");
        previews.delete(one.id);
        return;
      }
      // Shown as text: whatever the file holds, it never becomes part of the page.
      pre.textContent = value.skill_md;
      const description = /^description:\s*(.+)$/m.exec(value.skill_md)?.[1]?.replace(/^["'>|-]+\s*|["']$/g, "");
      if (description && description.length > 3) {
        own.replaceChildren(el("span", "skm-own-label", t.descriptionOwn), el("span", "", description));
        own.hidden = false;
      }
      if (value.changed != null) {
        moved.textContent = value.changed ? t.changed : t.unchanged;
        moved.classList.toggle("skm-moved-yes", value.changed);
        moved.hidden = false;
      }
    }

    // ================================================================= views

    function switchTo(value) {
      shown = value;
      tabs.set(value);
      installedPane.hidden = value !== "installed";
      marketPane.hidden = value !== "market";
      if (value === "market") loadMarket();
    }

    function show() {
      switchTo(shown);
      loadInstalled();
      ctx.api("mcp/market").then((value) => {
        connectors = value.servers;
      }).catch(() => null);
      // The installed view says which skills have updates, which the market's catalog knows.
      if (shown === "installed") {
        ctx.api("skills/market").then((value) => {
          market = value;
          if (view) renderInstalled();
        }).catch(() => null);
      }
    }

    return { node, show };
  });
})();
