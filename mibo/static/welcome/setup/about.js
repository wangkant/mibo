"use strict";
// Settings › About: the version and the licences.
(() => {
  const NOTICE = "https://github.com/wangkant/mibo/blob/main/NOTICE";

  window.paSetup.part("about", (kit) => {
    const { el } = kit;
    const t = kit.words("setup_about");
    const node = kit.section("about");
    const box = kit.card();
    box.classList.add("setup-options");
    const version = kit.optionRow(t.version, "", el("span", "setup-option-value"));
    const link = el("a", "setup-link");
    link.href = NOTICE;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.append(el("span", "", t.licenceLink), kit.icon("out", "setup-icon setup-icon-sm"));
    const licences = kit.optionRow(t.licences, t.licenceText);
    licences.words.append(link);
    box.append(version.row, licences.row);
    node.append(box);

    function show() {
      version.row.lastChild.textContent = kit.state.version;
    }

    return { node, show };
  });
})();
