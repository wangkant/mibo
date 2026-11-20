"use strict";
// ---- 显示桌宠 off (petoff.py): no figure and nothing it does by itself. Its window waits at the screen's
// corner, takes the pointer over a card alone, and a find still comes as its card there; what it would
// say goes to the chat only (pet.js bringRemark).
(() => {
  let edge = false;
  const bareBefore = petUx.setBare;
  petUx.setBare = (on) => {
    edge = on;
    bareBefore(on || "off" in pet.dataset);
  };

  window.petOff = (on) => {
    if (on) {
      petUx.untuck();
      hideQuick();
      if (card.kind === "said") card.close("seen");
      pet.dataset.off = "";
    } else delete pet.dataset.off;
    bareBefore(edge || on);
  };
})();
