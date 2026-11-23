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
    const licences = kit.optionRow(t.licences, t.licenceText);
    licences.words.append(kit.link(t.licenceLink, NOTICE, true));
    box.append(kit.item("version", version.row), kit.item("licences", licences.row));
    node.append(box);

    function show() {
      version.row.lastChild.textContent = kit.state.version;
    }

    return { node, show };
  });
})();
