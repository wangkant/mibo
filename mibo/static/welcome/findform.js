"use strict";
// Which of its two forms a find takes, one answer for every place a find is drawn (the chat and 推荐记录 in
// findcard.js, the pet's card, the first run): the picture card while it has a picture to show, else the text
// card. `bare` is set on a find whose picture was kept but would not arrive.
window.paFindForm = {
  of: (find) => (find.picture && !find.bare ? "picture" : "text"),
};
