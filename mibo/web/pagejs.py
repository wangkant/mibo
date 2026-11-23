"""The scripts a look and the page actions run in the page (pageops.Page and the modules beside it), each with
what it gives back. Ports of Playwright's injected checks are named as such (NOTICE)."""
from __future__ import annotations

import json

from .pagewords import SECRET_LABEL, SET_BY_VALUE

# URL, title, document identity, a count of DOM changes and form input; same-origin frames count as the page.
PROBE_JS = r"""() => {
  const w = window;
  const watch = (win, counted) => {
    const doc = win.document;
    if (doc.__paWatched) return;
    doc.__paWatched = true;
    if (counted) { w.__paLast = performance.now(); w.__paN++; }
    const styled = new WeakMap();
    new MutationObserver((records) => {
      const now = performance.now();
      let real = false;
      for (const r of records) {
        if (r.attributeName && r.oldValue === r.target.getAttributeNS(r.attributeNamespace, r.attributeName)) continue;
        // The ring the app draws to show where it acts is not the page changing.
        if ([...r.addedNodes, ...r.removedNodes].some((x) => x.dataset && 'paRing' in x.dataset)) continue;
        if (r.attributeName !== 'style') real = true;
        else if (now - (styled.get(r.target) ?? -1e9) > 200) real = true;
        if (r.attributeName === 'style') styled.set(r.target, now);
      }
      if (real) { w.__paLast = now; w.__paN++; }
    }).observe(doc, {subtree: true, childList: true, attributes: true, attributeOldValue: true, characterData: true});
    for (const type of ['input', 'change']) win.addEventListener(type, () => w.__paN++, true);
  };
  const first = !w.__paObs;
  if (first) { w.__paObs = true; w.__paLast = performance.now(); w.__paN = 0; w.__paDoc = Math.random(); watch(w, false); }
  const frames = (win) => {
    for (let i = 0; i < win.frames.length; i++) {
      let f;
      try { f = win.frames[i]; if (!f.document) continue; } catch { continue; }
      watch(f, !first);
      frames(f);
    }
  };
  frames(w);
  // Busy as the page says (aria-busy on something shown), for 10 s at most: some pages never say they are done.
  const busy = [...document.querySelectorAll('[aria-busy=true]')].some((e) => e.checkVisibility());
  if (!busy) w.__paBusy = null; else if (w.__paBusy == null) w.__paBusy = performance.now();
  const el = document.scrollingElement || document.documentElement;
  return {idle: performance.now() - w.__paLast, ready: document.readyState, url: location.href, title: document.title,
          n: w.__paN, doc: w.__paDoc, files: !!document.querySelector('input[type=file]'),
          busy: busy && performance.now() - w.__paBusy < 10000, sy: el.scrollTop, sh: el.scrollHeight, vh: innerHeight};
}"""

# Text actually shown, lowercased: the AX tree keeps opacity:0 text, which reads as a success that is not there.
VISIBLE_JS = r"""() => {
  const out = [];
  const shown = new Map();
  const roots = [document];
  for (let i = 0; i < roots.length; i++) {
    const walk = document.createTreeWalker(roots[i], NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT);
    for (let n = walk.nextNode(); n; n = walk.nextNode()) {
      if (n.nodeType === Node.ELEMENT_NODE) {
        if (n.shadowRoot) roots.push(n.shadowRoot);
        if (n.contentDocument) roots.push(n.contentDocument);
        continue;
      }
      let e = n.parentElement;
      if (!e || !n.textContent?.trim()) continue;
      while (e.parentElement && getComputedStyle(e).display === 'contents') e = e.parentElement;
      if (!shown.has(e)) shown.set(e, e.checkVisibility({checkOpacity: true, checkVisibilityCSS: true}));
      if (shown.get(e)) out.push(n.textContent);
    }
  }
  return out.join(' ').replace(/\s+/g, ' ').toLowerCase();
}"""

# Text on the screen now, lowercased: shown, inside the window and not scrolled out of the boxes it sits in (for
# `scroll ... until`, which stops once the words are where a person sees them).
SCREEN_JS = r"""() => {
  const out = [], roots = [document], clips = new Map();
  const clip = (e) => {
    if (!clips.has(e)) { const s = getComputedStyle(e); clips.set(e, s.overflowX !== 'visible' || s.overflowY !== 'visible'); }
    return clips.get(e);
  };
  for (let i = 0; i < roots.length; i++) {
    const walk = document.createTreeWalker(roots[i], NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT);
    for (let n = walk.nextNode(); n; n = walk.nextNode()) {
      if (n.nodeType === Node.ELEMENT_NODE) { if (n.shadowRoot) roots.push(n.shadowRoot); continue; }
      const e = n.parentElement;
      if (!e || !n.textContent.trim() || !e.checkVisibility({checkOpacity: true, checkVisibilityCSS: true})) continue;
      const range = document.createRange();
      range.selectNodeContents(n);
      let {top, bottom, left, right} = range.getBoundingClientRect();
      top = Math.max(top, 0); bottom = Math.min(bottom, innerHeight); left = Math.max(left, 0); right = Math.min(right, innerWidth);
      for (let a = e; a && top < bottom && left < right; a = a.parentElement) {
        if (a === document.body || a === document.documentElement || !clip(a)) continue;
        const r = a.getBoundingClientRect();
        top = Math.max(top, r.top); bottom = Math.min(bottom, r.bottom); left = Math.max(left, r.left); right = Math.min(right, r.right);
      }
      if (top < bottom && left < right) out.push(n.textContent);
    }
  }
  return out.join(' ').replace(/\s+/g, ' ').toLowerCase();
}"""

# The words of the whole document as plain lines, past what the window shows (browser-use's extract reads the page
# as markdown the same way): headings as `## `, list items as `- `, a table row by row with its cells between `|`
# and its header row marked, through open shadow roots and frames of the page's own site; what fields hold is left
# out, and so are the site's navigation and footer (nav, footer and their ARIA roles), as Readability and
# trafilatura drop them. With `this` an element, only what is in it.
TEXT_JS = r"""function(most) {
  const secretWords = new RegExp(""" + json.dumps(SECRET_LABEL.pattern) + r""", 'i');
  const root = this && this.nodeType === 1 ? this : document.body;
  const out = [];
  let line = [], size = 0;
  const end = () => { const t = line.join(' ').replace(/\s+/g, ' ').trim(); if (t) { out.push(t); size += t.length; } line = []; };
  const cell = (c) => (c.innerText || '').replace(/\s+/g, ' ').trim().replace(/\|/g, '/');
  // The words that name a field, as its accessible name takes them.
  const named = (x) => [x.getAttribute('aria-label'), x.getAttribute('placeholder'), x.title,
    ...(x.getAttribute('aria-labelledby') || '').split(/\s+/).map((i) => i && x.getRootNode().getElementById(i)).map((l) => l && l.innerText),
    ...[...(x.labels || [])].map((l) => l.innerText)].filter(Boolean).join(' ');
  const walk = (n) => {
    if (size > most) return;
    if (n.nodeType === 3) { if (n.textContent.trim()) line.push(n.textContent); return; }
    if (n.nodeType !== 1) return;
    const tag = n.tagName;
    // What a text area holds is its text, whole (a field's value is on its line of the state), unless the look
    // hides it as secret: by its autocomplete, or by the words that name it.
    if (tag === 'TEXTAREA' && n.value.trim() && n.checkVisibility() && !secretWords.test(named(n)) &&
        !/^(cc-|one-time-code|current-password|new-password)/i.test(n.getAttribute('autocomplete') || '')) {
      end();
      for (const t of n.value.split('\n')) if (t.trim()) { out.push(t.trim()); size += t.length; }
      return;
    }
    if (['SCRIPT', 'STYLE', 'NOSCRIPT', 'TEMPLATE', 'INPUT', 'TEXTAREA', 'SELECT', 'svg'].includes(tag)) return;
    if (tag === 'SLOT') { const given = n.assignedNodes({flatten: true}); for (const c of given.length ? given : n.childNodes) walk(c); return; }
    if (!n.checkVisibility({checkVisibilityCSS: true})) return;
    if (n !== root && (tag === 'NAV' || tag === 'FOOTER' || /^(navigation|contentinfo)$/.test(n.getAttribute('role') || ''))) return;
    if (tag === 'IFRAME') {
      try { const d = n.contentDocument; if (d && d.body) { end(); walk(d.body); end(); } } catch (_) {}
      return;
    }
    if (tag === 'BR') { end(); return; }
    if (tag === 'TABLE') {
      end();
      for (const row of n.rows) {
        const cells = [...row.cells].map(cell);
        if (!cells.some(Boolean)) continue;
        out.push(`| ${cells.join(' | ')} |`);
        size += out[out.length - 1].length;
        if (row.parentElement.tagName === 'THEAD' || [...row.cells].every((c) => c.tagName === 'TH')) out.push(`|${' --- |'.repeat(cells.length)}`);
      }
      return;
    }
    const heading = /^H[1-6]$/.test(tag);
    const block = heading || /^(block|flex|grid|list-item|table|flow-root)/.test(getComputedStyle(n).display);
    if (block) end();
    if (heading) line.push('##');
    else if (tag === 'LI') line.push('-');
    for (const c of (n.shadowRoot || n).childNodes) walk(c);
    if (block) end();
  };
  walk(root);
  end();
  return out.join('\n');
}"""

# A scroller (`this`, or the page when it is none) moved: "down" on most of a screen, "end" to its end, a number to
# that place, "where" nowhere; how far down it is, how tall, how much of it is below what it shows, and whether it
# moved.
SCROLL_JS = r"""function(to) {
  const e = this && this.nodeType === 1 ? this : (document.scrollingElement || document.documentElement);
  const was = e.scrollTop;
  if (to === 'down') e.scrollTop = was + Math.max(80, e.clientHeight * 0.85);
  else if (to === 'end') e.scrollTop = e.scrollHeight;
  else if (to !== 'where') e.scrollTop = to;
  return {top: e.scrollTop, height: e.scrollHeight, below: e.scrollHeight - e.scrollTop - e.clientHeight,
          moved: e.scrollTop !== was};
}"""

# A box that scrolls by itself (`this`): how much of it is below what it shows, how tall it is, and how far down its
# words reach (the lowest bottom of any text drawn in it, in its own height). A list that draws only the rows in
# view has words in a small part of its height.
DRAWN_JS = r"""function() {
  const top = this.getBoundingClientRect().top - this.scrollTop, walk = document.createTreeWalker(this, 4);
  const r = document.createRange();
  let words = 0;
  for (let n = walk.nextNode(), k = 0; n && k < 5000; n = walk.nextNode(), k++) {
    if (!n.data.trim()) continue;
    r.selectNodeContents(n);
    const b = r.getBoundingClientRect();
    if (b.height) words = Math.max(words, b.bottom - top);
  }
  return {below: this.scrollHeight - this.scrollTop - this.clientHeight, height: this.scrollHeight, words};
}"""

# The caret at the end of a field or an editable box, for typing that adds to what it holds.
END_JS = r"""function() {
  const e = this.nodeType === Node.ELEMENT_NODE ? this : this.parentElement;
  if (typeof e.setSelectionRange === 'function') {
    try { e.setSelectionRange(e.value.length, e.value.length); return; } catch (x) {}
  }
  const r = document.createRange();
  r.selectNodeContents(e);
  r.collapse(false);
  getSelection().removeAllRanges();
  getSelection().addRange(r);
}"""

# Where an element sits among its own: the words of the item before and after it (the element, or the nearest of
# its ancestors, up to five, with neighbours that have words), so a drag can say where it put something.
PLACE_JS = r"""function() {
  let e = this.nodeType === Node.ELEMENT_NODE ? this : this.parentElement;
  const words = (n) => n ? (n.innerText || n.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 40) : '';
  for (let up = 0; up < 5 && e.parentElement && e.parentElement !== document.body
       && !words(e.previousElementSibling) && !words(e.nextElementSibling); up++) e = e.parentElement;
  return {before: words(e.previousElementSibling), after: words(e.nextElementSibling)};
}"""

# Playwright's hit check for a click at a position: what the point {x, y} from the element's top left falls on is the
# element or a part of it (a shape of a drawing, the knob of a track).
HIT_JS = r"""function(at) {
  const e = this.nodeType === Node.ELEMENT_NODE ? this : this.parentElement;
  const r = e.getBoundingClientRect();
  const hit = e.getRootNode().elementFromPoint(r.x + at.x, r.y + at.y);
  return {on: !!hit && (hit === e || e.contains(hit)), hit: hit ? hit.tagName.toLowerCase() + (hit.id ? '#' + hit.id : '') : ''};
}"""

# An element and the elements over it, out through shadow roots, up to its document's body: where a press there is
# heard, and what a look lists of it.
UP_JS = r"""function() {
  const out = [];
  let e = this.nodeType === 1 ? this : (this.parentElement || (this.parentNode && this.parentNode.host));
  while (e && out.length < 30 && e !== e.ownerDocument.body && e !== e.ownerDocument.documentElement) {
    out.push(e);
    e = e.parentElement || (e.parentNode instanceof ShadowRoot ? e.parentNode.host : null);
  }
  return out;
}"""


# Playwright's selectText, with the words to select inside the element (spaces and case loosely): a field's text by
# setSelectionRange, else a Range over the text it shows. The text selected, or null when the words are not there.
SELECT_TEXT_JS = r"""function(want) {
  const e = this.nodeType === Node.ELEMENT_NODE ? this : this.parentElement;
  const squash = (s) => s.replace(/\s+/g, ' ').trim();
  const find = (flat, w) => { let i = flat.indexOf(w); if (i < 0) i = flat.toLowerCase().indexOf(w.toLowerCase()); return i; };
  want = squash(want || '');
  if (typeof e.setSelectionRange === 'function' && typeof e.value === 'string') {
    e.focus();
    let a = 0, b = e.value.length;
    if (want) {
      // Each character of the squashed value, at its place in the value.
      const at = [];
      let flat = '';
      for (let i = 0; i < e.value.length; i++) {
        const c = /\s/.test(e.value[i]) ? ' ' : e.value[i];
        if (c === ' ' && (flat.endsWith(' ') || !flat)) continue;
        flat += c; at.push(i);
      }
      const i = find(flat, want);
      if (i < 0) return null;
      a = at[i]; b = at[i + want.length - 1] + 1;
    }
    e.setSelectionRange(a, b);
    return e.value.slice(a, b);
  }
  const walk = document.createTreeWalker(e, NodeFilter.SHOW_TEXT);
  const at = [];
  let flat = '';
  for (let n = walk.nextNode(); n; n = walk.nextNode()) {
    if (!n.parentElement || !n.parentElement.checkVisibility()) continue;
    for (let i = 0; i < n.data.length; i++) {
      const c = /\s/.test(n.data[i]) ? ' ' : n.data[i];
      if (c === ' ' && (flat.endsWith(' ') || !flat)) continue;
      flat += c; at.push([n, i]);
    }
  }
  if (flat.endsWith(' ')) { flat = flat.slice(0, -1); at.pop(); }
  if (!at.length) return null;
  let a = 0, b = flat.length - 1;
  if (want) {
    const i = find(flat, want);
    if (i < 0) return null;
    a = i; b = i + want.length - 1;
  }
  const r = document.createRange();
  r.setStart(at[a][0], at[a][1]);
  r.setEnd(at[b][0], at[b][1] + 1);
  const s = getSelection();
  s.removeAllRanges();
  s.addRange(r);
  return s.toString();
}"""

POINT_JS = r"""function(editableCover) {
  const forms = """ + json.dumps(SET_BY_VALUE) + r""";
  const e = this.nodeType === Node.ELEMENT_NODE ? this : this.parentElement;
  if (!e || !e.isConnected) throw Error('Target detached');
  // Playwright's enabled: a native control's own disabled, a fieldset's, and aria-disabled on it or what holds it.
  if (e.matches(':disabled') || e.closest('[inert]') || e.closest('[aria-disabled=true]')) throw Error('Target disabled');
  if (e.tagName === 'INPUT' && forms[e.type]) throw Error(`a ${e.type} field opens a picker that cannot be seen; type ` +
    `the value into its id as ${e.type === 'range' ? `a number from ${e.min || 0} to ${e.max || 100}` : forms[e.type]}`);
  if (!e.checkVisibility({checkOpacity:true, checkVisibilityCSS:true})) throw Error('Target hidden');
  // Playwright's point: the middle of the first box of the element with area on screen (a link wrapped over two
  // lines has two), and a hit anywhere in the button or link the element is part of.
  const rects = [...e.getClientRects()].map((r) => {
    const left = Math.max(r.left, 0), top = Math.max(r.top, 0);
    return {x: left, y: top, w: Math.min(r.right, innerWidth) - left, h: Math.min(r.bottom, innerHeight) - top};
  }).filter((r) => r.w > 0 && r.h > 0 && r.w * r.h > 0.99);
  if (!rects.length) throw Error('Target outside viewport');
  const x = rects[0].x + rects[0].w/2, y = rects[0].y + rects[0].h/2;
  const t = e.matches('input,textarea,select') || e.isContentEditable ? e : e.closest('button,[role=button],a,[role=link]') || e;
  const hit = e.getRootNode().elementFromPoint(x, y);
  const textField = (n) => n && (['INPUT','TEXTAREA'].includes(n.tagName) || n.isContentEditable);
  const covered = !t.contains(hit) && !(hit && hit.contains(e) && getComputedStyle(hit).pointerEvents !== 'none' && hit.tagName === 'LABEL') && !(editableCover && textField(e) && textField(hit));
  // An option of a list where several can be chosen is clicked as a person adds one: with Ctrl.
  const multi = e.tagName === 'OPTION' && !!e.closest('select[multiple]');
  let px = x, py = y;
  for (let w = e.ownerDocument.defaultView; w && w.frameElement; w = w.parent) {
    const f = w.frameElement, fr = f.getBoundingClientRect(), cs = getComputedStyle(f);
    px += fr.x + f.clientLeft + parseFloat(cs.paddingLeft);
    py += fr.y + f.clientTop + parseFloat(cs.paddingTop);
  }
  return {x: px, y: py, covered, multi};
}"""

# Playwright's stable: the same box over two animation frames running (an element sliding in is waited for). A tab
# out of sight may get no frames, so a frame is also 50 ms at most.
STABLE_JS = r"""function() {
  const e = this.nodeType === Node.ELEMENT_NODE ? this : this.parentElement;
  const box = () => { const r = e.getBoundingClientRect(); return [r.x, r.y, r.width, r.height].join(); };
  const frame = () => new Promise((done) => { requestAnimationFrame(done); setTimeout(done, 50); });
  return (async () => {
    let last = box();
    for (let n = 0; n < 2; n++) {
      await frame();
      const now = box();
      if (now !== last) throw Error('Target not stable');
      last = now;
    }
    return true;
  })();
}"""

# Where a frame's own document starts inside its frame element, in the coordinates of the process's top page.
INNER_JS = r"""function() {
  const f = this, r = f.getBoundingClientRect(), cs = getComputedStyle(f);
  let x = r.x + f.clientLeft + parseFloat(cs.paddingLeft), y = r.y + f.clientTop + parseFloat(cs.paddingTop);
  for (let w = f.ownerDocument.defaultView; w && w.frameElement; w = w.parent) {
    const o = w.frameElement, or = o.getBoundingClientRect(), os = getComputedStyle(o);
    x += or.x + o.clientLeft + parseFloat(os.paddingLeft);
    y += or.y + o.clientTop + parseFloat(os.paddingTop);
  }
  return {x, y};
}"""

# Where an element is, in the top page's coordinates (for the ring and the marks).
BOX_JS = r"""function() {
  const e = this.nodeType === Node.ELEMENT_NODE ? this : this.parentElement;
  const r = e.getBoundingClientRect();
  let x = r.x, y = r.y;
  for (let w = e.ownerDocument.defaultView; w && w.frameElement; w = w.parent) {
    const f = w.frameElement.getBoundingClientRect();
    x += f.x + w.frameElement.clientLeft;
    y += f.y + w.frameElement.clientTop;
  }
  return {x, y, w: r.width, h: r.height};
}"""

# The ring held round a control while a card waits on it, drawn in a world of the app's own (the page's scripts
# cannot reach its script): it follows the control as the page scrolls or lays itself out again, until the next
# ring or UNRING_JS takes it away.
HOLD_JS = r"""function() {
  const e = this.nodeType === Node.ELEMENT_NODE ? this : this.parentElement, doc = e.ownerDocument;
  for (const old of doc.querySelectorAll('[data-pa-ring]')) old.remove();
  const d = doc.createElement('div');
  d.dataset.paRing = '';
  d.style.cssText = 'position:fixed;box-sizing:border-box;border:3px solid #1f1f22;border-radius:10px;' +
    'box-shadow:0 0 0 3px #fff,0 0 0 6px rgba(31,31,34,.25);pointer-events:none;z-index:2147483647;';
  doc.documentElement.appendChild(d);
  const follow = () => {
    if (!d.isConnected) return;
    const r = e.getBoundingClientRect();
    Object.assign(d.style, {left: `${r.x - 5}px`, top: `${r.y - 5}px`, width: `${r.width + 10}px`,
      height: `${r.height + 10}px`, display: e.isConnected ? '' : 'none'});
    requestAnimationFrame(follow);
  };
  follow();
}"""
UNRING_JS = "for (const old of document.querySelectorAll('[data-pa-ring]')) old.remove()"

# The element showing these words, the smallest and the one in view first; into shadow roots and same-origin
# frames. Text is searched, then the words a control keeps in its attributes.
LOCATE_JS = r"""(want) => {
  const norm = (s) => String(s || '').replace(/\s+/g, ' ').trim().toLowerCase();
  const w = norm(want);
  if (!w) return null;
  const roots = [document], found = [];
  for (let i = 0; i < roots.length; i++) {
    const walk = document.createTreeWalker(roots[i], NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT);
    for (let n = walk.nextNode(); n; n = walk.nextNode()) {
      if (n.nodeType === Node.ELEMENT_NODE) {
        if (n.shadowRoot) roots.push(n.shadowRoot);
        if (n.tagName === 'IFRAME') { try { if (n.contentDocument) roots.push(n.contentDocument); } catch (_) {} }
        const said = norm(n.getAttribute('aria-label') || n.getAttribute('title') || n.getAttribute('placeholder') ||
          n.getAttribute('alt') || n.getAttribute('data-tooltip') || '');
        if (said && said.includes(w)) found.push([n, said === w ? 0 : 2]);
        continue;
      }
      const e = n.parentElement;
      if (!e || ['SCRIPT', 'STYLE', 'NOSCRIPT'].includes(e.tagName) || !norm(n.textContent).includes(w)) continue;
      found.push([e, norm(e.innerText) === w ? 0 : 1]);
    }
  }
  const shown = found.filter(([e]) => e.checkVisibility({checkOpacity: true, checkVisibilityCSS: true}));
  const away = (e) => { const r = e.getBoundingClientRect(); return r.bottom > 0 && r.top < innerHeight ? 0 : 1; };
  shown.sort((a, b) => a[1] - b[1] || away(a[0]) - away(b[0]));
  return shown.length ? shown[0][0] : null;
}"""

# A control the page drew anew since it was found (a live board draws every row again each second): the one
# element now showing the same words after the same text (letters only, as `near` keeps it). With `press` it is
# pressed in the same moment by the page's own events, so no redraw comes between finding it and pressing it.
AGAIN_JS = r"""(name, near, press) => {
  const letters = (s) => String(s || '').replace(/[^\p{L}]/gu, '').toLowerCase();
  const want = letters(name), ctx = letters(near);
  if (!want) return null;
  const roots = [document], all = [];
  for (let i = 0; i < roots.length; i++) {
    for (const e of roots[i].querySelectorAll('*')) {
      if (e.shadowRoot) roots.push(e.shadowRoot);
      if (e.tagName === 'IFRAME') { try { if (e.contentDocument) roots.push(e.contentDocument); } catch (_) {} }
      if (letters(e.getAttribute('aria-label') || e.textContent || e.value) === want && e.checkVisibility()) all.push(e);
    }
  }
  // The outermost of nested matches (a button and the span in it).
  const tops = all.filter((e) => !all.some((o) => o !== e && o.contains(e)));
  const fits = tops.filter((e) => {
    if (!ctx) return true;
    for (let a = e.parentElement, i = 0; a && i < 6; a = a.parentElement, i++) {
      if (letters(a.textContent).includes(ctx)) return tops.filter((o) => a.contains(o)).length === 1;
    }
    return false;
  });
  if (fits.length !== 1) return null;
  const e = fits[0];
  if (press) {
    const r = e.getBoundingClientRect();
    const o = {bubbles: true, cancelable: true, composed: true, view: window, button: 0,
      clientX: r.x + r.width / 2, clientY: r.y + r.height / 2};
    e.dispatchEvent(new PointerEvent('pointerdown', {...o, pointerId: 1, isPrimary: true}));
    e.dispatchEvent(new MouseEvent('mousedown', o));
    if (e.focus) e.focus();
    e.dispatchEvent(new PointerEvent('pointerup', {...o, pointerId: 1, isPrimary: true}));
    e.dispatchEvent(new MouseEvent('mouseup', o));
    e.click();
  }
  return e;
}"""

# The nearest box around an element that scrolls by itself, else the page: how far down it is.
SCROLLER_JS = r"""function() {
  let e = this.nodeType === Node.ELEMENT_NODE ? this : this.parentElement;
  const up = (a) => a.parentElement || (a.getRootNode() instanceof ShadowRoot ? a.getRootNode().host : null);
  for (; e && e !== document.body && e !== document.documentElement; e = up(e)) {
    if (/(auto|scroll|overlay)/.test(getComputedStyle(e).overflowY) && e.scrollHeight > e.clientHeight + 8) break;
  }
  const el = !e || e === document.body || e === document.documentElement
    ? (document.scrollingElement || document.documentElement) : e;
  return {top: el.scrollTop, height: el.scrollHeight, client: el.clientHeight};
}"""

CENTER_JS = ("function(){const e=this.nodeType===1?this:this.parentElement;"
             "e.scrollIntoView({block:'center',inline:'center',behavior:'instant'});}")

KIND_JS = ("function(){const e=this.nodeType===1?this:this.parentElement;if(!e||!e.isConnected)throw Error('Target detached');"
           "if(e.matches(':disabled')||e.closest('[inert]'))throw Error('Target disabled');"
           "if(!e.checkVisibility({checkVisibilityCSS:true}))throw Error('Target hidden');"
           # The order a date field shows its parts in (mdy, dmy, ymd), as the browser's language writes a date.
           "const order=new Intl.DateTimeFormat(navigator.language).formatToParts(new Date(2001,10,22))"
           ".filter(p=>p.type!=='literal').map(p=>p.type[0]).join('');"
           "return {tag:e.tagName,type:(e.type||'').toLowerCase(),min:e.min||'',max:e.max||'',order};}")

# A value put into a date, time, colour or range field through the native setter, then input and change, as
# Playwright fills them; the field's own read-back, or null (and the old value back) when it did not take it.
SET_JS = r"""function(v) {
  const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set, old = this.value;
  this.focus();
  set.call(this, v);
  if (this.value !== v && this.type !== 'range') { set.call(this, old); return null; }
  this.dispatchEvent(new Event('input', {bubbles: true, composed: true}));
  this.dispatchEvent(new Event('change', {bubbles: true}));
  return this.value;
}"""

# Playwright's selectOption: one option, or for a list where several can be chosen, exactly the ones named
# (commas between).
SELECT_JS = r"""function(want){
  const n = s => String(s).replace(/\s+/g,' ').trim().toLowerCase(), opts = [...this.options].filter(o => !o.disabled);
  const pick = (w) => {
    const pre = opts.filter(o => n(o.label).startsWith(n(w)));
    const o = opts.find(o => n(o.label) === n(w) || n(o.value) === n(w)) ?? (pre.length === 1 ? pre[0] : undefined);
    if (!o) throw Error((pre.length > 1 ? 'several options start with ' : 'no option ') + JSON.stringify(w) + '. Options: ' + (pre.length > 1 ? pre : opts).slice(0, 40).map(o => o.label).join(' | '));
    return o;
  };
  let chosen;
  if (this.multiple) {
    const whole = opts.find(o => n(o.label) === n(want) || n(o.value) === n(want));
    chosen = whole ? [whole] : String(want).split(/\s*[,，;；|、\n]\s*/).filter(Boolean).map(pick);
    for (const o of this.options) o.selected = chosen.includes(o);
  } else {
    chosen = [pick(want)];
    this.value = chosen[0].value;
  }
  this.dispatchEvent(new Event('input',{bubbles:true,composed:true})); this.dispatchEvent(new Event('change',{bubbles:true}));
  return chosen.map(o => o.label).join(' | ');
}"""

MOVED_JS = ("function(){const e=this.nodeType===1?this:this.parentElement;let a=document.activeElement;"
            "while(a&&a.shadowRoot&&a.shadowRoot.activeElement)a=a.shadowRoot.activeElement;"
            "return !!a&&a!==e&&!e.contains(a)&&(['INPUT','TEXTAREA'].includes(a.tagName)||a.isContentEditable);}")

VALUE_JS = ("function(){const e=this.nodeType===1?this:this.parentElement;"
            "return e.isContentEditable?e.innerText:(e.value??'');}")

# The element with focus, as an object CDP can name (for Enter and Space), into shadow roots and same-origin frames.
ACTIVE_JS = ("(() => {let a = document.activeElement; for (;;) { if (a && a.shadowRoot && a.shadowRoot.activeElement) "
             "a = a.shadowRoot.activeElement; else if (a && a.contentDocument && a.contentDocument.activeElement) "
             "a = a.contentDocument.activeElement; else return a; }})()")

# The first empty secret field of the target's form, focused for the person; its label, or null.
SECRET_EMPTY_JS = """function (selector) {
  const form = this.form || this.closest('form');
  const field = form && [...form.querySelectorAll(selector)].find((e) => !e.value);
  if (!field) return null;
  field.focus();
  return ((field.labels && field.labels[0] && field.labels[0].innerText) || field.getAttribute('aria-label')
    || field.placeholder || field.name || '').trim().slice(0, 80);
}"""
# What the gate and the card need of a target, read off the page: its form (method, a search form, a password in
# it, the button Enter goes through), the text box it belongs to and what that holds, the heading over that box
# (to whom), a money amount by it, whether it is secret, and the filled fields a press sends, for the card.
FACTS_JS = r"""function() {
  const secretWords = new RegExp(""" + json.dumps(SECRET_LABEL.pattern) + r""", 'i');
  const e = this.nodeType === 1 ? this : this.parentElement;
  const tag = e.tagName.toLowerCase(), type = (e.type || '').toLowerCase(), role = e.getAttribute('role') || '';
  const ac = (e.getAttribute('autocomplete') || '').toLowerCase();
  const own = (n) => [n.getAttribute('aria-label'), n.getAttribute('name'), n.id, n.getAttribute('placeholder'),
    n.getAttribute('data-placeholder'), n.title, n.labels && n.labels[0] && n.labels[0].innerText].filter(Boolean).join(' ');
  // What an icon-only control says on hover or in its drawing.
  const svgTitle = e.querySelector('svg title'), img = e.querySelector('img[alt]');
  const tip = [e.getAttribute('data-tooltip'), e.getAttribute('data-tip'), e.getAttribute('data-title'),
    e.getAttribute('data-original-title'), e.getAttribute('aria-description'), e.title, svgTitle && svgTitle.textContent,
    img && img.alt].filter(Boolean).join(' ').trim().slice(0, 120);
  const label = own(e);
  const text = (e.innerText || e.value || '').trim().replace(/\s+/g, ' ').slice(0, 200);
  const isText = (n) => n && (n.tagName === 'TEXTAREA' || n.isContentEditable ||
    (n.tagName === 'INPUT' && ['text', 'search', 'email', 'url', 'tel', ''].includes((n.type || '').toLowerCase())));
  const searchy = (n) => (n.type || '').toLowerCase() === 'search' || ['searchbox', 'combobox'].includes(n.getAttribute('role') || '') ||
    !!n.closest('[role=search],search') || /search|搜索|查找|搜一搜/i.test(own(n));
  const form = e.form || e.closest('form');
  let f = null;
  if (form) {
    const els = [...form.elements];
    const fields = els.filter((x) => ['INPUT', 'SELECT', 'TEXTAREA'].includes(x.tagName) && !['hidden', 'submit', 'image', 'button', 'reset'].includes(x.type));
    const subs = els.filter((x) => (x.tagName === 'BUTTON' && (!x.getAttribute('type') || x.type === 'submit')) || (x.tagName === 'INPUT' && ['submit', 'image'].includes(x.type)));
    const method = (form.getAttribute('method') || 'get').toLowerCase();
    f = {method, action: form.action, fields: fields.length, submit: subs.length > 0,
      password: !!form.querySelector('input[type=password],input[autocomplete=current-password],input[autocomplete=new-password]'),
      search: form.getAttribute('role') === 'search' || !!form.closest('[role=search],search') || els.some((x) => x.type === 'search') ||
        // One field sent by GET is a search only when it says so: a page's script can post any form.
        (method === 'get' && fields.length === 1 && fields[0].tagName !== 'TEXTAREA' && (searchy(fields[0]) ||
          /^(?:q|query|keywords?|kw|wd|word|s|k|search|term)$/i.test(fields[0].name || '') ||
          /search|find|query|搜索/i.test(form.getAttribute('action') || ''))),
      button: subs[0] ? (subs[0].innerText || subs[0].value || subs[0].getAttribute('aria-label') || '').trim().slice(0, 80) : ''};
  }
  const submitter = !!form && ((tag === 'button' && (!e.getAttribute('type') || type === 'submit')) || (tag === 'input' && ['submit', 'image'].includes(type)));
  let composer = isText(e) && !searchy(e) ? e : null;
  // Up through a shadow root too: a button and its box may sit straight under one.
  const up = (n) => n.parentElement || (n.parentNode instanceof ShadowRoot ? n.parentNode : n instanceof ShadowRoot ? n.host : null);
  for (let a = up(e), i = 0; !composer && a && i < 5; a = up(a), i++) {
    const near = [...a.querySelectorAll('textarea,[contenteditable],input')].filter((x) => isText(x) && !searchy(x) && x.checkVisibility());
    if (near.length === 1) composer = near[0];
    else if (near.length > 1) break;
  }
  const said = composer ? (composer.isContentEditable ? composer.innerText : (composer.value || '')).trim() : '';
  const hint = composer ? own(composer) : '';
  let to = '';
  // `from` is the box, or the shadow host holding it once the walk has gone out of its shadow root.
  let from = composer || e, a = from.parentElement;
  if (!a && from.getRootNode().host) { from = from.getRootNode().host; a = from.parentElement; }
  // Ours: a chat's header is often no heading but a short bold line at the top of its pane.
  const before = (h) => h.checkVisibility() && !h.contains(from) && (h.compareDocumentPosition(from) & Node.DOCUMENT_POSITION_FOLLOWING);
  const bold = (h) => [...h.childNodes].some((c) => c.nodeType === 3 && /\p{L}/u.test(c.textContent)) && h.innerText.trim().length <= 40 &&
    parseInt(getComputedStyle(h).fontWeight) >= 600 && !h.closest('a,button,label,li,[role=button],[role=option],[role=listitem],[role=row]');
  while (a && !to) {
    // Ours: a pane's own short <header> holds whom a chat is with, even in plain type (a site's banner is longer).
    let heads = [...a.querySelectorAll('h1,h2,h3,h4,[role=heading],header')].filter((h) => before(h) &&
      (h.tagName !== 'HEADER' || h.innerText.trim().length <= 40));
    if (!heads.length) heads = [...a.querySelectorAll('div,span,b,strong,header,p')].slice(0, 800).filter((h) => before(h) && bold(h));
    if (heads.length) to = heads[heads.length - 1].innerText.trim().split('\n')[0].slice(0, 80);
    if (a === document.body) break;
    if (a.parentElement) { a = a.parentElement; continue; }
    const host = a.getRootNode().host;
    if (!host) break;
    from = host;
    a = host.parentElement;
  }
  const money = ((e.innerText || '') + ' ' + (e.parentElement ? e.parentElement.innerText : '')).match(
    /(?:[$€£¥￥₹₩]\s?\d[\d.,]*|\d[\d.,]*\s?(?:USD|EUR|GBP|JPY|CNY|RMB|元|円))/);
  const testIds = ['data-testid', 'data-test', 'data-qa'].map((a) => e.getAttribute(a) || '').join(' ');
  // Ours: where a link goes, when it goes to another page (not "#", not a script).
  const anchor = e.closest('a[href]');
  const away = anchor && /^https?:/.test(anchor.href) && anchor.href.split('#')[0] !== location.href.split('#')[0] ? anchor.href : '';
  // Ours: the item a control acts on (its post, its row), for a card with no words of its own to quote.
  let row = '';
  for (let a = e.parentElement, i = 0; a && i < 6 && !row; a = a.parentElement, i++) {
    const t = (a.innerText || '').replace(/\s+/g, ' ').trim();
    if (t.length > text.length + 4) row = t.slice(0, 160);
  }
  // The fields a press sends (its form's, or those in the nearest box that holds fields), filled and not secret,
  // as [caption, value]: 就诊日期 2026-12-05, 时段 14:00.
  const short = (t) => (t || '').replace(/\s+/g, ' ').trim();
  const secretOf = (x) => x.type === 'password' || /^(?:cc-|one-time-code|current-password|new-password)/i.test(
    x.getAttribute('autocomplete') || '') || secretWords.test(own(x));
  const captionOf = (x) => {
    const lab = x.labels && [...x.labels].find((l) => !l.contains(x));
    let c = short(lab && lab.innerText) || short(x.getAttribute('aria-label')) || short(x.placeholder) || short(x.title);
    let box = x;
    if (!c && (x.type === 'radio' || x.type === 'checkbox')) {
      const legend = x.closest('fieldset') && x.closest('fieldset').querySelector('legend');
      c = short(legend && legend.innerText) || short((x.closest('[role=radiogroup],[role=group]') || x).getAttribute('aria-label'));
      // The box that holds the whole group, whose words stand before it: 时段 over a row of radios.
      const group = x.name ? [...document.getElementsByName(x.name)] : [x];
      for (let i = 0; i < 5 && box.parentElement && !group.every((g) => box.contains(g)); i++) box = box.parentElement;
    }
    for (let b = box, i = 0; !c && b && i < 3; b = b.parentElement, i++) {
      const prev = b.previousElementSibling;
      if (prev && !prev.querySelector('input,select,textarea') && short(prev.innerText).length <= 24) c = short(prev.innerText);
    }
    return (c || x.name || x.id || '').slice(0, 24);
  };
  const valueOf = (x) => {
    if (x.tagName === 'SELECT') return [...x.selectedOptions].map((o) => short(o.text)).join('、');
    if (x.type === 'checkbox' || x.type === 'radio') return x.checked ? short(x.labels && x.labels[0] && x.labels[0].innerText) || x.value : '';
    if (x.type === 'file') return [...(x.files || [])].map((f) => f.name).join('、');
    return x.checkVisibility() ? short(x.value) : '';
  };
  let scope = form;
  for (let a = e.parentElement, i = 0; !scope && a && i < 6; a = a.parentElement, i++) {
    if (a.querySelector('input,select,textarea')) scope = a;
  }
  const fields = [];
  for (const x of scope ? [...(form ? form.elements : scope.querySelectorAll('input,select,textarea'))].slice(0, 60) : []) {
    if (!['INPUT', 'SELECT', 'TEXTAREA'].includes(x.tagName) || ['hidden', 'submit', 'image', 'button', 'reset'].includes(x.type)
      || x.disabled || secretOf(x)) continue;
    const value = valueOf(x).slice(0, 80), caption = captionOf(x);
    const same = caption && fields.find((f) => f[0] === caption);
    if (!value) continue;
    if (same) same[1] = `${same[1]}、${value}`.slice(0, 80);
    else if (fields.length < 10) fields.push([caption, value]);
  }
  return {tag, type, role, row, fields, label: label.slice(0, 200), text, tip, link: tag === 'a' || role === 'link', away: away.slice(0, 300),
    iconOnly: !text && !e.getAttribute('aria-label') && !!e.querySelector('svg,img,i'), form: f, submitter,
    switch: role === 'switch' || (tag === 'input' && type === 'checkbox' && e.getAttribute('role') === 'switch'),
    textEntry: isText(e), search: searchy(e), composer: !!composer, said: said.slice(0, 2000), hint: hint.slice(0, 120),
    to, money: money ? money[0] : '', classes: `${typeof e.className === 'string' ? e.className : ''} ${testIds} ${e.id}`.trim().slice(0, 200),
    secret: type === 'password' || /^cc-/.test(ac) || ['one-time-code', 'current-password', 'new-password'].includes(ac)};
}"""
