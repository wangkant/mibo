"use strict";
// The words of a chat message drawn: the person's with their web addresses as links, the character's from their
// Markdown. `links` is what the link cards take from the chat (linkcard.js); `say` names the chat's own words.
window.paChatText = (() => {
  const { el, button } = window.paKit;
  // The character's words are Markdown, read by markdown-it (markdown-it.umd.min.js, vendored): CommonMark with
  // GitHub's tables and struck text. No HTML in a reply is drawn; only web addresses become links, bare ones
  // too (README.md and mail addresses stay words); a picture is a link to it and is never loaded. Lines indented
  // four spaces are not code, and dashes under a paragraph are a rule, not a heading. Underscores never mark
  // emphasis (__init__); an asterisk or tilde run marks it only with no letter or digit outside it and no space
  // inside (2 * 3, x**2 + y**2 stay as written), so bold that ends in Chinese punctuation closes (**注意：**明天).
  const MD = (() => {
    const md = window.markdownit({ html: false, linkify: true });
    md.linkify.set({ fuzzyLink: false, fuzzyEmail: false });
    md.disable(["code", "lheading"]);
    md.validateLink = (url) => /^https?:\/\//i.test(url);
    const word = /[A-Za-z0-9]/;
    const space = /\s/;
    md.inline.State = class extends md.inline.State {
      scanDelims(start) {
        const marker = this.src[start];
        let end = start;
        while (end < this.posMax && this.src[end] === marker) end += 1;
        const before = this.src[start - 1] || " ";
        const after = end < this.posMax ? this.src[end] : " ";
        const marks = marker !== "_";
        return { can_open: marks && !space.test(after) && !word.test(before),
          can_close: marks && !space.test(before) && !word.test(after), length: end - start };
      }
    };
    md.renderer.rules.image = (tokens, n, options, env, self) => {
      const src = md.utils.escapeHtml(tokens[n].attrGet("src"));
      return `<a href="${src}">${md.utils.escapeHtml(self.renderInlineAsText(tokens[n].children, options, env)) || src}</a>`;
    };
    // Headings start at h3 under the chat's own; a column's side is a data attribute (no inline styles here);
    // a bare address is marked to be named by its site.
    md.core.ruler.push("chat", (state) => {
      for (const token of state.tokens) {
        if (token.type === "heading_open" || token.type === "heading_close") token.tag = `h${Math.min(6, +token.tag[1] + 2)}`;
        else if ((token.type === "th_open" || token.type === "td_open") && token.attrGet("style"))
          token.attrs = [["data-align", token.attrGet("style").split(":")[1]]];
        else if (token.type === "inline")
          for (const child of token.children) if (child.type === "link_open" && child.markup in { linkify: 1, autolink: 1 }) child.attrSet("data-bare", "");
      }
    });
    return md;
  })();
  // Block elements: the line breaks markdown-it writes beside them are its own, not the reply's.
  const BLOCK = /^(P|UL|OL|LI|BLOCKQUOTE|TABLE|THEAD|TBODY|TR|TH|TD|PRE|HR|H[1-6]|DIV)$/;
  const URL_RE = /https?:\/\/[^\s<>"'，。！？；）】」]+/g;

  // `text` into `node`, its web addresses as links.
  function linked(node, text, links) {
    let at = 0;
    for (const match of text.matchAll(URL_RE)) {
      const url = match[0].replace(/[.,;:!?)\]]+$/, "");
      node.append(text.slice(at, match.index), window.paLinks.inline(url, links));
      at = match.index + url.length;
    }
    node.append(text.slice(at));
    return node;
  }
  // A fenced code block, drawn as code with a button that copies it.
  function codeNode(lang, code, say) {
    const box = el("div", "code");
    const head = el("div", "code-head");
    const copy = button("code-copy", say("copy"), async () => {
      try {
        await navigator.clipboard.writeText(code);
        copy.textContent = say("copied");
        setTimeout(() => (copy.textContent = say("copy")), 1500);
      } catch {
        // The code is still there to select by hand.
      }
    });
    head.append(el("span", "code-lang", lang), copy);
    const pre = el("pre");
    pre.append(el("code", "", code));
    box.append(head, pre);
    return box;
  }
  // The character's words, drawn from their Markdown: markdown-it's blocks without the line breaks it writes
  // between them (the words keep their own), code with its copy button, a table in a box that scrolls, each link
  // opened as every link in the app opens and a bare address named by its site.
  function sayNode(text, links, say) {
    const node = el("div", "say rich");
    node.innerHTML = MD.render(String(text || ""));
    const walk = document.createTreeWalker(node, NodeFilter.SHOW_TEXT);
    const texts = [];
    while (walk.nextNode()) if (!walk.currentNode.parentNode.closest("pre")) texts.push(walk.currentNode);
    for (const words of texts) {
      if (BLOCK.test(words.nextSibling?.tagName || "")) words.data = words.data.replace(/\n$/, "");
      if (BLOCK.test(words.previousSibling?.tagName || "")) words.data = words.data.replace(/^\n/, "");
      if (!words.data) words.remove();
    }
    for (const pre of node.querySelectorAll("pre")) {
      const code = pre.firstChild;
      pre.replaceWith(codeNode(code.className.replace(/^language-/, ""), code.textContent.replace(/\n$/, ""), say));
    }
    for (const table of node.querySelectorAll("table")) {
      const box = el("div", "say-table");
      table.replaceWith(box);
      box.append(table);
    }
    for (const link of node.querySelectorAll("a")) {
      if (link.hasAttribute("data-bare")) link.replaceWith(window.paLinks.inline(link.textContent, links));
      else {
        link.className = "say-link";
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        link.title = link.getAttribute("href");
      }
    }
    return node;
  }
  // The words with the lines their link cards say taken out; fenced code keeps every line.
  function wordsOf(text) {
    return String(text || "")
      .split(/^([ \t]*```[^\n]*\n[\s\S]*?(?:\n[ \t]*```[ \t]*$|(?![\s\S])))/m)
      .map((part, n) => (n % 2 ? part : window.paLinks.bare(part)))
      .filter(Boolean)
      .join("\n");
  }

  return { linked, sayNode, wordsOf };
})();
