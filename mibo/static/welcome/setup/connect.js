"use strict";
// Settings › Connections: the sites signed in to in Mibo's own browser, drawn by sites.js with this page's kit.
(() => {
  window.paSetup.part("connect", (kit) => {
    const node = kit.section("connect");
    const root = kit.item("sites", kit.el("div", "setup-connect places-root"));
    root.lang = paI18n.locale;
    node.append(root);
    window.paSites.mount(root, kit);
    return { node, show: () => window.paSites.show() };
  });
})();
