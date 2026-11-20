"use strict";
// Settings › Connections: the sites signed in to in Mibo's own browser, drawn by sites.js.
(() => {
  window.paSetup.part("connect", (kit) => {
    const node = kit.section("connect");
    const root = kit.el("div", "setup-connect places-root");
    root.lang = paI18n.locale;
    node.append(root);
    window.paSites.mount(root, kit.ctx);
    return { node, show: () => window.paSites.show() };
  });
})();
