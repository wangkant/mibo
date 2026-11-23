// Generic page reader: the main list of a page as rows, and the main content of an item page.
// One synchronous function expression with no site names in it, called as `(<this file>)(opts, Readability)`
// with Mozilla's Readability in scope (read.py's READER puts the two together): WebView2 ExecuteScriptAsync
// (which does not await promises) or playwright page.evaluate. Returns plain JSON.
// opts: {maxRows: 120, maxText: 20000, article: false, debug: false}; `article` reads an item's article
// whatever lists sit beside it.
//   kind   'list' | 'item' | 'page'
//   wall   {kind: '' | 'verification' | 'sign_in' | 'sign_in_overlay' | 'dead' | 'error' | 'empty', evidence}
//   rows   [{link, title, picture?, author?, avatar?, time?, duration?, counts?: {label: value}, text?}]
//   main   {title, author, published, picture, video, duration, counts, site, type, lang, description, text}
//   facts  JSON-LD types, top-level microdata, canonical / oEmbed / RSS links
//   meta, ld, title, canonical, oembed, text: the page's own description of itself, as roam.facts_from reads it
//   discovery  where the site's search and hot lists are: OpenSearch links, a WebSite SearchAction template,
//          searchable forms, feed links and links named like a hot list
// Endless scroll and virtual lists: call again after each scroll and merge rows by link.
// How it finds the list (no model, no site rules): sibling blocks with one signature (tag + classes) or one
// tag are candidates, also when cut into columns or dated groups; scored by count, visible area, links, pictures
// and words, with penalties for page chrome, menus, prose, skeletons and lists of lists. Fields are columns:
// leaves at the same relative path across blocks (MDR/DEPTA-style alignment, simplified), named by content
// (time and count patterns), size (largest picture, square avatar, biggest type for the title) and nesting
// (the link round the picture or title, the name beside the avatar).
// An item's text is Readability's article when it holds at least 30% of the page's visible text (Jina Reader's
// rule), else the block scorer's below.
(opts, Readability) => {
  opts = opts || {};
  const MAX_ROWS = opts.maxRows || 120, MAX_TEXT = opts.maxText || 20000, BUDGET = 60000;
  const VW = innerWidth || 1280, VH = innerHeight || 800;
  const here = location.href;
  const CHROME = 'nav,header,footer,aside,[role=navigation],[role=banner],[role=contentinfo],[role=menu],' +
                 '[role=menubar],[role=tablist],[role=dialog],[aria-modal=true]';
  const SKIP = new Set(['SCRIPT', 'STYLE', 'NOSCRIPT', 'TEMPLATE', 'SVG', 'PATH', 'IFRAME', 'OBJECT', 'CANVAS',
                        'SELECT', 'OPTION', 'INPUT', 'TEXTAREA', 'BUTTON', 'HEAD', 'LINK', 'META', 'BR', 'HR']);
  // Icon-font glyphs sit in the Private Use Area and mean nothing as text.
  const clean = (s) => String(s == null ? '' : s).replace(/[\uE000-\uF8FF]/g, '').replace(/\s+/g, ' ').trim();
  const abs = (u) => { try { return u ? new URL(u, document.baseURI).href : ''; } catch (e) { return ''; } };
  const realHref = (a) => {
    const raw = a.getAttribute('href') || '';
    if (!raw || raw[0] === '#' || /^(javascript|mailto|tel|data):/i.test(raw)) return '';
    const u = abs(raw);
    return u && u.split('#')[0] !== here.split('#')[0] ? u : '';
  };
  const box = (el) => {
    try {
      const b = el.getBoundingClientRect();
      if ((b.width || b.height) || getComputedStyle(el).display !== 'contents') return b;
      // display: contents draws no box of its own; its children's boxes are where it is.
      let l = Infinity, t = Infinity, r = -Infinity, d = -Infinity;
      for (const c of el.children) { const x = box(c); if (!x.width && !x.height) continue; l = Math.min(l, x.left); t = Math.min(t, x.top); r = Math.max(r, x.left + x.width); d = Math.max(d, x.top + x.height); }
      return r > l ? {left: l, top: t, width: r - l, height: d - t} : b;
    } catch (e) { return {width: 0, height: 0, top: 0, left: 0}; }
  };
  const shown = (el) => {
    const b = box(el);
    if (b.width < 2 || b.height < 2) return false;
    const st = getComputedStyle(el);
    if (st.display === 'contents') return true;
    // Opacity is left out: feeds fade blocks in as they scroll into view.
    return st.visibility !== 'hidden' && st.display !== 'none';
  };
  // Element children, including an open shadow root's.
  const kids = (el) => {
    const out = [];
    const add = (p) => { for (const c of p.children) if (!SKIP.has(c.tagName.toUpperCase())) out.push(c); };
    if (el.shadowRoot) add(el.shadowRoot);
    add(el);
    return out;
  };
  const walk = (root, fn) => {
    const stack = [root]; let n = 0;
    while (stack.length && n < BUDGET) {
      const el = stack.pop(); n++;
      if (fn(el) === false) continue;
      const k = kids(el);
      for (let i = k.length - 1; i >= 0; i--) stack.push(k[i]);
    }
    return n;
  };
  const textOf = (el) => clean(el.innerText !== undefined ? el.innerText : el.textContent);
  const ownText = (el) => {
    let s = '';
    for (const n of el.childNodes) if (n.nodeType === 3) s += n.nodeValue;
    return clean(s);
  };
  const STATE = /^(active|selected|current|hover|focus|first|last|odd|even|show|shown|hide|hidden|open|on|off|is-.*|has-.*|js-.*)$/i;
  const classSig = (el, n) => {
    const raw = typeof el.className === 'string' ? el.className : (el.getAttribute('class') || '');
    return raw.split(/\s+/).filter(c => c && !STATE.test(c)).map(c => c.replace(/\d+/g, '0')).sort().slice(0, n || 4).join('.');
  };
  const sig = (el) => el.tagName.toLowerCase() + (classSig(el) ? '.' + classSig(el) : '');
  const inChrome = (el) => { try { return !!el.closest(CHROME); } catch (e) { return false; } };

  // ---------- page facts: meta, JSON-LD, microdata, oEmbed and feed links ----------
  const meta = {};
  for (const m of document.querySelectorAll('meta[content]')) {
    const k = (m.getAttribute('property') || m.getAttribute('name') || m.getAttribute('itemprop') || '').trim().toLowerCase();
    const v = clean(m.getAttribute('content'));
    if (k && v && !(k in meta)) meta[k] = v.slice(0, 2000);
  }
  const ld = [];
  const flat = (o) => {
    if (Array.isArray(o)) { o.forEach(flat); return; }
    if (!o || typeof o !== 'object') return;
    if (o['@graph']) flat(o['@graph']);
    if (o['@type']) ld.push(o);
    if (o.mainEntity && typeof o.mainEntity === 'object') flat(o.mainEntity);
    if (o.itemListElement) flat(o.itemListElement);
  };
  for (const s of document.querySelectorAll('script[type="application/ld+json"]')) {
    try { flat(JSON.parse(s.textContent)); } catch (e) {}
  }
  const types = (o) => [].concat(o && o['@type'] || []).map(String);
  const microdata = [];
  for (const scope of [...document.querySelectorAll('[itemscope]')].filter(e => !e.parentElement || !e.parentElement.closest('[itemscope]')).slice(0, 20)) {
    const item = {type: (scope.getAttribute('itemtype') || '').split('/').pop()};
    for (const p of scope.querySelectorAll('[itemprop]')) {
      const k = p.getAttribute('itemprop');
      if (k in item) continue;
      item[k] = clean(p.getAttribute('content') || p.getAttribute('datetime') || p.getAttribute('href') ||
                      p.getAttribute('src') || textOf(p)).slice(0, 300);
    }
    microdata.push(item);
  }
  const links = {};
  for (const l of document.querySelectorAll('link[rel][href]')) {
    const rel = (l.getAttribute('rel') || '').toLowerCase(), type = (l.getAttribute('type') || '').toLowerCase();
    if (rel === 'canonical') links.canonical = abs(l.getAttribute('href'));
    if (rel.includes('alternate') && /oembed/.test(type)) (links.oembed = links.oembed || []).push(abs(l.getAttribute('href')));
    if (rel.includes('alternate') && /rss|atom/.test(type)) (links.feeds = links.feeds || []).push(abs(l.getAttribute('href')));
  }

  // ---------- walls and empty shells ----------
  const allText = textOf(document.body || document.documentElement);
  const bodyText = allText.slice(0, 20000);
  const title = clean(document.title);
  const VERIFY = /(verify (that )?you are (a )?human|are you a robot|confirm (that )?you.re not a (ro)?bot|just a moment|checking your browser|security (check|verification)|performing security verification|unusual traffic|confirm (that )?you.re (a )?human|checking if the site connection is secure|captcha|人机验证|安全验证|环境异常|滑动.{0,6}验证|拖动.{0,6}滑块|请完成验证|验证码|ロボットではありません|画像認証|보안 문자|자동입력 방지|проверка.{0,10}(робот|браузер)|подтвердите, что вы не робот)/i;
  const SIGNIN = /(sign in|log in|login|sign up|join now|create (an )?account|continue with (google|apple|email)|登录|登陆|注册|扫码|ログイン|新規登録|로그인|회원가입|войти|вход|регистрац)/i;
  const GATE = /(to (see|view|continue|read|watch)|for (full|more) access|to keep (reading|watching)|后(查看|继续|观看|浏览)|查看更多|継続|続きを|계속|чтобы (продолжить|посмотреть|увидеть))/i;
  // A page that says it is gone marks that one address dead; any other error page is a wall on the site.
  const GONE = /^(404|410)\b|not found|page (isn.t|is not) available|页面不存在|找不到|ページが見つかりません|페이지를 찾을 수 없|страница не найдена/i;
  const ERR = /^(403|429|5\d\d)\b|too many requests|access denied|forbidden/i;
  const wall = {kind: '', evidence: ''};
  // Invisible score-only widgets sit on many open pages; only a challenge a person can see is a wall.
  const frames = [...document.querySelectorAll('iframe[src]')].filter(f => { const b = f.getBoundingClientRect(); return b.width >= 100 && b.height >= 60 && getComputedStyle(f).visibility !== 'hidden'; })
    .map(f => f.src).filter(s => /captcha|challenge|turnstile|geetest|arkoselabs|verify/i.test(s));
  const pw = [...document.querySelectorAll('input[type=password]')].some(shown);
  // A sign-in box in front of the page: what sits at the middle of the screen belongs to a fixed layer that asks
  // to sign in (a player's own "sign in for HD" strip is not in front of the page).
  let overlay = null, overlayEl = null;
  for (const [x, y] of [[0.5, 0.5], [0.5, 0.35], [0.5, 0.65]]) {
    let el = document.elementFromPoint(VW * x, VH * y);
    for (; el && el !== document.body; el = el.parentElement) {
      const st = getComputedStyle(el);
      if (st.position !== 'fixed') continue;
      const b = box(el), t = textOf(el).slice(0, 2000);
      if (b.width * b.height >= VW * VH * 0.08 && SIGNIN.test(t) && t.length < 1500 && !el.querySelector('video')) { overlay = t.slice(0, 160); overlayEl = el; break; }
    }
    if (overlay) break;
  }
  // A sign-in box over a page whose own words are still there is a prompt a visitor may read past, not a wall;
  // a password field inside it is the box's.
  if (overlay && bodyText.length - textOf(overlayEl).length > 1500) {
    wall.prompt = overlay;
    overlay = null;
  }
  const pwOutside = [...document.querySelectorAll('input[type=password]')].some(p => shown(p) && !(wall.prompt && overlayEl.contains(p)));
  const firstScreen = bodyText.slice(0, 1500);
  if (frames.length || (VERIFY.test(title) || (VERIFY.test(firstScreen) && bodyText.length < 3000))) {
    wall.kind = 'verification'; wall.evidence = frames[0] || (title.match(VERIFY) || firstScreen.match(VERIFY))[0];
  } else if (pw && pwOutside && bodyText.length < 4000) {
    wall.kind = 'sign_in'; wall.evidence = 'password field';
  } else if (GONE.test(title) || (bodyText.length < 600 && GONE.test(bodyText))) {
    wall.kind = 'dead'; wall.evidence = (title.match(GONE) || bodyText.match(GONE))[0];
  } else if (ERR.test(title) || (bodyText.length < 600 && ERR.test(bodyText))) {
    wall.kind = 'error'; wall.evidence = (title.match(ERR) || bodyText.match(ERR))[0];
  } else if (overlay) {
    wall.kind = 'sign_in_overlay'; wall.evidence = overlay;
  } else if (SIGNIN.test(firstScreen) && GATE.test(firstScreen) && bodyText.length < 2500) {
    wall.kind = 'sign_in'; wall.evidence = (firstScreen.match(GATE) || [''])[0];
  }

  // ---------- the main list: repeated sibling blocks ----------
  const candidates = [];
  const count = walk(document.body || document.documentElement, (el) => {
    const tag = el.tagName.toUpperCase();
    if (SKIP.has(tag)) return false;
    const ch = kids(el);
    if (ch.length < 3) return;
    const groups = new Map();
    for (const c of ch) {
      const k = sig(c);
      if (!groups.has(k)) groups.set(k, []);
      groups.get(k).push(c);
    }
    // Same tag with drifting classes (variants, state) counts as one group when it dominates.
    const byTag = new Map();
    for (const c of ch) { const t = c.tagName; byTag.set(t, (byTag.get(t) || []).concat([c])); }
    for (const [t, list] of byTag) if (list.length >= 3 && list.length >= ch.length * 0.7 && !groups.has(t)) groups.set('~' + t, list);
    for (const [k, list] of groups) if (list.length >= 3) candidates.push({parent: el, key: k, items: list});
  });

  const hasPicture = (el) => {
    if (el.tagName === 'IMG' || el.tagName === 'PICTURE' || el.tagName === 'VIDEO') return true;
    if (el.querySelector('img,picture,video')) return true;
    let found = false;
    walk(el, (e) => { if (found) return false; const bg = e.style && e.style.backgroundImage; if (bg && bg.includes('url(')) found = true; });
    return found;
  };
  const firstLink = (el) => {
    if (el.tagName === 'A' && realHref(el)) return realHref(el);
    const up = el.closest && el.closest('a[href]');
    if (up && realHref(up)) return realHref(up);
    for (const a of el.querySelectorAll('a[href]')) { const h = realHref(a); if (h) return h; }
    return '';
  };
  const scoreOf = (c) => {
    const items = c.items.filter(shown);
    if (items.length < 3) return 0;
    let area = 0, txt = 0, linked = 0, pics = 0;
    const texts = new Set(), hrefs = new Set();
    for (const it of items) {
      const b = box(it);
      area += Math.min(b.width, VW) * Math.min(b.height, VH);
      const t = textOf(it); txt += Math.min(t.length, 300); texts.add(t.slice(0, 80));
      const h = firstLink(it); if (h) { linked++; hrefs.add(h); }
      if (hasPicture(it)) pics++;
    }
    const n = items.length, avg = txt / n;
    let s = Math.sqrt(n) * Math.sqrt(area) * (0.3 + linked / n) * (0.6 + 0.4 * pics / n) * (Math.min(avg, 120) / 120 + 0.15);
    if (avg < 12 && pics / n < 0.3) s *= 0.15;             // menus, tag clouds, pagers
    if (texts.size < n * 0.6) s *= 0.3;                   // skeletons and placeholders repeat the same text
    if (linked && hrefs.size < linked * 0.6) s *= 0.4;    // every block pointing at one place is chrome
    if (inChrome(c.parent)) s *= 0.15;
    // The page's own layout (header, body, footer as siblings) is not a list.
    if (c.parent === document.body || c.parent === document.documentElement) s *= 0.1;
    if (n <= 5 && area / n > VW * VH * 0.6) s *= 0.3;
    // Blocks that are themselves lists (a front page's sections) are a level too high.
    const nested = items.filter(it => listParents.some(p => p !== it && it.contains(p))).length;
    if (nested >= n * 0.4) s *= 0.05;
    c.nested = nested;
    if (/^(P|BLOCKQUOTE|H[1-6]|BR|SPAN)$/.test(items[0].tagName) || (linked / n < 0.5 && pics / n < 0.3)) s *= 0.2;   // prose, not a list
    c.n = n; c.avgText = Math.round(avg); c.linkFrac = +(linked / n).toFixed(2); c.picFrac = +(pics / n).toFixed(2);
    c.area = Math.round(area); c.shownItems = items;
    return s;
  };
  // Masonry columns, grids cut into rows, and feeds cut into dated groups: containers of one kind holding the
  // same blocks, side by side (one level up) or in sibling groups (two levels up), are one list.
  const merged = new Map();
  const base = candidates.length;
  for (let ci = 0; ci < base; ci++) {
    const c = candidates[ci];
    let up = c.parent, path = c.key;
    for (let lvl = 1; lvl <= 2; lvl++) {
      path += '|' + sig(up);
      up = up.parentElement;
      if (!up) break;
      if (!merged.has(up)) merged.set(up, new Map());
      const m = merged.get(up);
      if (!m.has(path)) m.set(path, []);
      m.get(path).push(c);
    }
  }
  for (const [up, m] of merged) for (const group of m.values()) {
    if (group.length < 2) continue;
    candidates.push({parent: up, key: group[0].key, items: [].concat(...group.map(g => g.items)), split: group.length});
  }
  // Groups that look like a list of things (each a link with a few words or a picture), to spot lists of lists.
  const listParents = [...new Set(candidates.filter(c => {
    if (c.items.length < 3 || c.split || c.key[0] === '~') return false;
    let linked = 0, words = 0, pics = 0;
    const seen = c.items.filter(shown);
    if (seen.length < 3) return false;   // a hidden menu or pop-up is not part of what the block shows
    for (const it of seen) { if (firstLink(it)) linked++; words += Math.min(textOf(it).length, 100); if (it.querySelector('img,picture,video')) pics++; }
    return linked >= seen.length * 0.8 && words / seen.length >= 15;
  }).map(c => c.parent))];
  for (const c of candidates) c.score = scoreOf(c);
  candidates.sort((a, b) => b.score - a.score);
  const best = candidates[0] && candidates[0].score > 0 ? candidates[0] : null;
  let listItems = [];
  if (best) {
    listItems = best.shownItems.slice();
    // Columns read top to bottom one after another; put the blocks back in reading order.
    if (best.split) listItems.sort((x, y) => (box(x).top - box(y).top) || (box(x).left - box(y).left));
  }

  // ---------- fields of each block: align leaves across blocks by their relative path ----------
  const TIME = /(\d+\s*(秒|分钟|分鐘|小时|小時|天|周|週|个月|個月|月|年)前|刚刚|剛剛|昨天|前天|今天|\d+\s*(s|m|min|mins|h|hr|hrs|d|w|mo|y)\b( ago)?|\d+\s*(seconds?|minutes?|hours?|days?|weeks?|months?|years?) ago|(just now|yesterday|today)|\d+\s*(秒|分|時間|日|週間|か月|ヶ月|年)前|\d+\s*(초|분|시간|일|주|개월|년)\s*전|\d+\s*(сек|мин|час|дн|нед|мес|год|лет)[а-яё.]*\s*назад|\b\d{4}[-/.年]\d{1,2}[-/.月]\d{1,2}|\b\d{1,2}[-/月]\d{1,2}日?\b|\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.? \d{1,2}(, \d{4})?)/i;
  const INLINE = /^(A|B|I|EM|STRONG|SPAN|BR|CODE|SMALL|MARK|U|S|SUB|SUP|IMG|ABBR|Q|CITE|WBR|FONT|TIME)$/;
  const DURATION = /^\d{1,2}:\d{2}(:\d{2})?$/;
  const COUNT = /^([\d][\d.,]*)\s*([万萬亿億千kKmMbB]|万\+|w|W)?\+?\s*([^\d\s].{0,8})?$/;
  const HINT_AUTHOR = /author|user|owner|uploader|creator|channel|nick|byline|name|up[-_]?name|by\b|profile|account|blog/i;
  const HINT_COUNT = /view|play|like|digg|heart|fav|star|comment|reply|repl|danmaku|dm|share|coin|vote|point|score|watch|popular|hot|count|stat|num/i;
  const picOf = (el) => {
    if (el.tagName === 'IMG') return abs(el.currentSrc || el.getAttribute('src') || el.getAttribute('data-src') || el.getAttribute('data-original') || (el.getAttribute('srcset') || '').split(/\s+/)[0]);
    if (el.tagName === 'VIDEO') return abs(el.getAttribute('poster'));
    const bg = (el.style && el.style.backgroundImage) || '';
    const m = bg.match(/url\(["']?([^"')]+)/);
    return m ? abs(m[1]) : '';
  };
  const leavesOf = (item) => {
    const out = [];
    const rec = (el, path, depth) => {
      if (depth > 30 || out.length > 120) return;
      const tag = el.tagName.toUpperCase();
      if (SKIP.has(tag) && tag !== 'BUTTON') return;
      const p = path + '/' + el.tagName.toLowerCase() + (classSig(el, 2) ? '.' + classSig(el, 2) : '');
      const icon = el.previousElementSibling && !textOf(el.previousElementSibling) ? el.previousElementSibling.getAttribute('class') : '';
      const inner = el.firstElementChild && !textOf(el.firstElementChild) ? el.firstElementChild.getAttribute('class') : '';
      const hint = [el.getAttribute('class'), icon, inner, el.getAttribute('itemprop'), el.getAttribute('data-testid'), el.getAttribute('aria-label'), el.getAttribute('title')].filter(Boolean).join(' ');
      // Text cut short on screen (ellipsis, line clamp) is the only case where a title attribute says it better.
      const clipped = el.scrollWidth > el.clientWidth + 1 || el.scrollHeight > el.clientHeight + 1;
      if (tag === 'A' && realHref(el)) out.push({kind: 'a', path: p, clipped, href: realHref(el), text: textOf(el).slice(0, 300), wraps: [...el.querySelectorAll('*')].filter(d => ownText(d)).length >= 2, title: clean(el.getAttribute('title') || el.getAttribute('aria-label')), hint, pic: !!el.querySelector('img,picture,video')});
      if (tag === 'IMG' || tag === 'VIDEO' || (el.style && /url\(/.test(el.style.backgroundImage || ''))) {
        const b = box(el), src = picOf(el);
        if (src && !/^data:/.test(src)) out.push({kind: 'img', path: p, src, alt: clean(el.getAttribute('alt')), area: b.width * b.height, w: b.width, h: b.height});
      }
      if (tag === 'TIME') out.push({kind: 'time', path: p, text: textOf(el), datetime: el.getAttribute('datetime') || ''});
      const own = /^<[a-z][^>]*>.*<\/[a-z]+>/i.test(ownText(el)) ? '' : ownText(el);   // markup kept as text is a placeholder, not words
      // A run of text with inline markup inside (links, emphasis, emoji) reads as one value.
      const inline = own && [...el.children].every(c => INLINE.test(c.tagName) || /^inline/.test(getComputedStyle(c).display));
      const value = inline ? textOf(el) : own;
      const st = own ? getComputedStyle(el) : null;
      const font = st ? parseFloat(st.fontSize) * (+st.fontWeight >= 600 ? 1.25 : 1) : 0;
      if (own) out.push({kind: 'text', path: p, font, clipped, text: value.slice(0, 300), title: clean(el.getAttribute('title') || (tag === 'A' ? '' : el.getAttribute('aria-label'))), hint, heading: /^H[1-6]$/.test(tag), anchor: tag === 'A'});
      if (inline && tag !== 'A') { for (const c of el.querySelectorAll('a[href],img,time')) rec(c, p, depth + 1); return; }
      // Counts often sit in buttons (like, repost), which the list scan skips.
      for (const c of [...(el.shadowRoot ? el.shadowRoot.children : []), ...el.children]) if (!SKIP.has(c.tagName.toUpperCase()) || c.tagName === 'BUTTON') rec(c, p, depth + 1);
    };
    rec(item, '', 0);
    // A block wrapped by its link: treat the wrapper as the block's anchor.
    const up = item.parentElement && item.parentElement.closest('a[href]');
    if (up && realHref(up)) out.push({kind: 'a', path: '^a', href: realHref(up), text: textOf(up).slice(0, 300), title: clean(up.getAttribute('title')), hint: '', pic: true});
    return out;
  };
  const rows = [];
  let columns_debug = null;
  if (listItems.length) {
    const per = listItems.slice(0, 400).map(leavesOf);
    const cols = new Map();
    per.forEach((leaves, i) => {
      const seen = new Map();
      for (const l of leaves) {
        // Two leaves on the same path in one block (title and subtitle) stay two columns.
        const base = l.kind + ' ' + l.path, nth = seen.get(base) || 0;
        seen.set(base, nth + 1);
        if (nth > 2) continue;
        const k = base + (nth ? '#' + nth : '');
        if (!cols.has(k)) cols.set(k, {key: k, kind: l.kind, path: l.path, vals: new Array(per.length).fill(null)});
        cols.get(k).vals[i] = l;
      }
    });
    const N = per.length;
    // A title attribute stands in for the visible text only when the text is that attribute cut short.
    const fullText = (x) => { const t = x.text || x.alt || ''; const a = x.title || ''; return a.length > t.length && (!t || x.clipped || /(\.\.\.|…)$/.test(t)) ? a : t; };
    const stats = [...cols.values()].map(c => {
      const v = c.vals.filter(Boolean);
      const texts = v.map(fullText);
      return Object.assign(c, {cover: v.length / N, uniq: new Set(texts).size / Math.max(v.length, 1),
        avgLen: texts.reduce((a, t) => a + t.length, 0) / Math.max(v.length, 1), texts,
        timeFrac: texts.filter(t => TIME.test(t) && t.length < 40).length / Math.max(v.length, 1),
        durFrac: texts.filter(t => DURATION.test(t)).length / Math.max(v.length, 1),
        numFrac: texts.filter(t => COUNT.test(t) && t.length < 16).length / Math.max(v.length, 1),
        hint: (v[0] && v[0].hint) || ''});
    }).filter(c => c.cover >= 0.35);
    const pick = (list, f) => { let top = null, s = 0; for (const c of list) { const v = f(c); if (v > s) { s = v; top = c; } } return top; };
    const picCols = stats.filter(c => c.kind === 'img').map(c => Object.assign(c, {avgArea: c.vals.filter(Boolean).reduce((a, v) => a + v.area, 0) / Math.max(c.vals.filter(Boolean).length, 1)}));
    const picture = pick(picCols.filter(c => c.avgArea >= 70 * 70), c => c.cover * c.avgArea);
    const square = (c) => { const v = c.vals.filter(Boolean); const r = v.reduce((a, x) => a + (x.h ? x.w / x.h : 0), 0) / Math.max(v.length, 1); return r > 0.8 && r < 1.25; };
    const avatar = pick(picCols.filter(c => c !== picture && c.avgArea >= 16 * 16 && (c.avgArea < 70 * 70 || (square(c) && picture && c.avgArea < picture.avgArea * 0.7))), c => c.cover);
    const under = (a, c) => !!c && (c.path === a.path || c.path.startsWith(a.path + '/'));
    const depth = (h) => { try { return new URL(h).pathname.split('/').filter(Boolean).length; } catch (e) { return 0; } };
    const tagFrac = (c) => c.texts.filter(t => /^[#＃]/.test(t)).length / Math.max(c.texts.length, 1);
    const isTitleish = (c) => c.timeFrac < 0.5 && c.durFrac < 0.5 && c.numFrac < 0.5 && c.avgLen >= 4 && tagFrac(c) < 0.5;
    const fonts = stats.filter(c => c.kind === 'text').map(c => (c.vals.find(Boolean) || {}).font || 0).filter(Boolean);
    const midFont = fonts.length ? fonts.sort((a, b) => a - b)[fonts.length >> 1] : 14;
    const fontOf = (c) => { if (c.kind === 'text') return (c.vals.find(Boolean) || {}).font || midFont; const t = stats.find(x => x.kind === 'text' && x.path === c.path); return t ? fontOf(t) : midFont; };
    // A link wrapped round the whole card reads as everything in it run together, not as a title.
    const wrapping = (c) => c.kind === 'a' && c.vals.filter(v => v && v.wraps).length > c.vals.filter(Boolean).length / 2;
    const titleCol = pick(stats.filter(c => (c.kind === 'text' || c.kind === 'a') && isTitleish(c) && !wrapping(c) && c.uniq >= 0.5), c => {
      const v = c.vals.find(Boolean) || {};
      const big = Math.min(Math.pow(fontOf(c) / midFont, 2), 4);
      return c.cover * c.uniq * Math.min(c.avgLen, 40) * (c.avgLen > 120 ? 0.6 : 1) * (v.heading ? 1.6 : 1) * (v.title ? 1.3 : 1) * (c.kind === 'a' ? 1.3 : 1) * (/title|headline|name|subject|caption/i.test(c.hint) ? 1.5 : 1) * big;
    });
    const linkSeg = (h) => { try { return new URL(h).pathname.split('/').filter(Boolean)[0] || ''; } catch (e) { return ''; } };
    const authorCol = pick(stats.filter(c => (c.kind === 'text' || c.kind === 'a') && c !== titleCol && tagFrac(c) < 0.5 && c.timeFrac < 0.3 && c.numFrac < 0.3 && c.durFrac < 0.3 && c.avgLen >= 2 && c.avgLen <= 40), c => {
      let s = c.cover * (c.kind === 'a' ? 2 : 1) * (HINT_AUTHOR.test(c.hint) ? 3 : 1);
      // The name printed beside a small round picture is whoever posted.
      if (avatar && c.path.split('/').slice(0, -1).join('/') === avatar.path.split('/').slice(0, -1).join('/')) s *= 3;
      if (c.kind === 'a') {
        // People's pages share one path prefix (/user/, /@, /space/...), different from where the title goes.
        const segs = c.vals.filter(Boolean).map(v => linkSeg(v.href));
        const common = segs.length && segs.filter(x => x === segs[0]).length / segs.length;
        const ts = titleCol && titleCol.kind === 'a' ? titleCol.vals.filter(Boolean).map(v => linkSeg(v.href)) : [];
        if (common >= 0.6 && (!ts.length || segs[0] !== ts[0])) s *= 2;
        if (under(c, picture)) s *= 0.2;
      }
      if (c.uniq < 0.15) s *= 0.2;
      return s;
    });
    // The block's own link is the one round its main picture or its title, not the one round the poster's face,
    // a counter (its words a number: stars, replies) or a media file.
    const MEDIA = /\.(jpe?g|png|gif|webp|avif|mp4|webm|mp3)(\?|$)/i;
    // A column of links that are mostly media files is never the block's link, however it scores.
    const mediaCol = (c) => { const hs = c.vals.filter(Boolean).map(v => v.href); return hs.filter(h => MEDIA.test(h)).length > hs.length / 2; };
    const link = pick(stats.filter(c => c.kind === 'a' && !mediaCol(c)), c => {
      const hs = c.vals.filter(Boolean).map(v => v.href);
      return c.cover * (0.2 + c.uniq) * (c.path === '^a' ? 2 : 1) * (under(c, picture) ? 3 : 1) * (under(c, titleCol) || c.path === (titleCol && titleCol.path) ? 2.5 : 1) *
        (under(c, avatar) || under(c, authorCol) || tagFrac(c) >= 0.5 ? 0.3 : 1) * (1 + Math.min(hs.reduce((a, h) => a + depth(h), 0) / Math.max(hs.length, 1), 4) / 4) *
        (c.numFrac >= 0.5 ? 0.2 : 1);
    });
    const deepest = (i) => per[i].filter(l => l.kind === 'a' && !MEDIA.test(l.href)).sort((x, y) => depth(y.href) - depth(x.href) || y.href.length - x.href.length)[0];
    const linkHref = (i) => link && link.vals[i] ? link.vals[i].href : ((deepest(i) || {}).href || firstLink(listItems[i]));
    const timeCol = pick(stats.filter(c => c.kind === 'time' || c.timeFrac >= 0.5), c => c.cover * (c.kind === 'time' && c.vals.some(v => v && v.datetime) ? 3 : 1) * (c.kind === 'time' ? 1 : c.timeFrac + 0.1));
    const clockish = (c) => /date|time|clock|stamp/i.test(c.hint) && !/duration|length/i.test(c.hint);
    const durCol = pick(stats.filter(c => c.kind === 'text' && c.durFrac >= 0.6 && !clockish(c) && !(timeCol && c.path === timeCol.path)), c => c.cover);
    const countCols = stats.filter(c => c.kind === 'text' && c.numFrac >= 0.6 && c.timeFrac < 0.5 && c !== timeCol && c !== durCol && !(timeCol && c.path === timeCol.path) && !clockish(c)).slice(0, 6);
    const textCol = pick(stats.filter(c => c.kind === 'text' && c !== titleCol && c !== authorCol && c.avgLen > 25 && isTitleish(c)), c => c.cover * c.avgLen);
    const labelOf = (c, i) => {
      const v = c.vals[i];
      const m = v && v.text.match(COUNT);
      if (m && m[3]) return clean(m[3]);
      const h = (v && (v.title || v.hint)) || c.hint;
      const w = h.match(HINT_COUNT);
      return w ? w[0].toLowerCase() : 'n' + (countCols.indexOf(c) + 1);
    };
    const val = (c, i) => { const v = c && c.vals[i]; return v ? fullText(v) : ''; };
    const seen = new Set();
    for (let i = 0; i < N && rows.length < MAX_ROWS; i++) {
      const href = linkHref(i);
      let t = val(titleCol, i);
      const big = per[i].filter(l => l.kind === 'img' && l.area >= 80 * 80).sort((a, b) => b.area - a.area)[0];
      const pic = picture && picture.vals[i] ? picture.vals[i] : big;
      // Posts without a title: their longest run of words stands in.
      if (!t) { const body = per[i].filter(l => l.kind === 'text' && l.text.length >= 15 && !/^[#＃]/.test(l.text)).sort((a, b) => b.text.length - a.text.length)[0]; if (body) t = body.text; }
      if (!t && pic) t = pic.alt;
      if (!t && !pic) continue;
      if (href && seen.has(href)) continue;
      seen.add(href);
      const counts = {};
      for (const c of countCols) if (c.vals[i]) counts[labelOf(c, i)] = c.vals[i].text.match(COUNT) ? c.vals[i].text.match(COUNT).slice(1, 3).filter(Boolean).join('') : c.vals[i].text;
      const tv = timeCol && timeCol.vals[i];
      const row = {link: href, title: t.slice(0, 300)};
      if (pic) row.picture = pic.src;
      if (authorCol && authorCol.vals[i]) row.author = val(authorCol, i).slice(0, 80);
      if (avatar && avatar.vals[i]) row.avatar = avatar.vals[i].src;
      if (tv) row.time = tv.datetime || (tv.text.match(TIME) || [tv.text])[0];
      if (durCol && durCol.vals[i]) row.duration = durCol.vals[i].text;
      if (Object.keys(counts).length) row.counts = counts;
      if (textCol && textCol.vals[i] && textCol.vals[i].text !== t) row.text = textCol.vals[i].text.slice(0, 300);
      rows.push(row);
    }
    if (opts.debug) columns_debug = per.slice(0, 2).map(ls => ls.map(l => [l.kind, l.path.split('/').slice(-2).join('/'), (l.text || l.src || l.href || '').slice(0, 60), l.title || '', l.area || l.font || '']));
  }

  // ---------- the main content of an item page ----------
  const ldMain = ld.find(o => types(o).some(t => /VideoObject|Movie|Episode|Clip/.test(t))) ||
                 ld.find(o => types(o).some(t => /Article|NewsArticle|BlogPosting|Report|Review/.test(t))) ||
                 ld.find(o => types(o).some(t => /SocialMediaPosting|DiscussionForumPosting|Comment|QAPage|Question|Recipe|Product|ImageObject|MusicRecording|Event/.test(t))) || null;
  const BLOCK = /^(P|PRE|BLOCKQUOTE|LI|H1|H2|H3|H4|FIGCAPTION|TD|DD)$/;
  const scores = new Map();
  walk(document.body || document.documentElement, (el) => {
    const tag = el.tagName.toUpperCase();
    if (SKIP.has(tag)) return false;
    if (/^(NAV|FOOTER|ASIDE)$/.test(tag) || /^(navigation|contentinfo|complementary|dialog)$/.test(el.getAttribute('role') || '')) return false;
    const own = ownText(el);
    const isBlock = BLOCK.test(tag) || own.length >= 25;
    if (!isBlock) return;
    const t = BLOCK.test(tag) ? textOf(el) : own;
    if (t.length < 25) return;
    let linkLen = 0; for (const a of el.querySelectorAll('a')) linkLen += textOf(a).length;
    const s = (1 + t.split(/[,，、。.;；!！?？]/).length + Math.min(Math.floor(t.length / 100), 3)) * (1 - Math.min(linkLen / Math.max(t.length, 1), 0.9));
    let p = el.parentElement, lvl = 0;
    while (p && lvl < 3) { scores.set(p, (scores.get(p) || 0) + s / (lvl === 0 ? 1 : lvl === 1 ? 2 : lvl * 3)); p = p.parentElement; lvl++; }
    if (BLOCK.test(tag)) return false;
  });
  let root = null, top = 0;
  for (const [el, s] of scores) {
    let linkLen = 0; for (const a of el.querySelectorAll('a')) linkLen += textOf(a).length;
    const len = textOf(el).length || 1;
    const v = s * (1 - Math.min(linkLen / len, 0.95)) * (inChrome(el) ? 0.2 : 1);
    if (v > top) { top = v; root = el; }
  }
  // Siblings of the winner that also scored well belong to the same text (Readability's sibling join, simplified).
  const parts = [];
  if (root) {
    const pool = root.parentElement ? kids(root.parentElement) : [root];
    const keep = pool.filter(s => s === root || (scores.get(s) || 0) >= Math.max(10, (scores.get(root) || 0) * 0.2));
    let total = 0;
    for (const r of keep) {
      walk(r, (el) => {
        if (total > MAX_TEXT) return false;
        const tag = el.tagName.toUpperCase();
        if (SKIP.has(tag) || /^(NAV|FOOTER|ASIDE|FORM)$/.test(tag)) return false;
        if (el !== r && !shown(el)) return false;
        if (BLOCK.test(tag)) { const t = textOf(el); if (t) { parts.push((/^H[1-4]$/.test(tag) ? '## ' : '') + t); total += t.length; } return false; }
        const own = ownText(el);
        if (own.length >= 25) { parts.push(own); total += own.length; }
      });
    }
  }
  let text = parts.filter((p, i) => p !== parts[i - 1]).join('\n\n').slice(0, MAX_TEXT);
  const pickLd = (k) => { const v = ldMain && ldMain[k]; if (!v) return ''; if (typeof v === 'string' || typeof v === 'number') return String(v); if (Array.isArray(v)) return v.map(x => typeof x === 'string' ? x : (x && (x.name || x.url || x.contentUrl)) || '').filter(Boolean)[0] || ''; return v.name || v.url || v.contentUrl || ''; };
  const h1 = document.querySelector('h1');
  const timeEl = (root && root.querySelector('time[datetime]')) || document.querySelector('main time[datetime], article time[datetime]') || document.querySelector('time[datetime]');
  const authorEl = document.querySelector('[rel=author],[itemprop=author],[class*=author i] a,[class*=byline i]');
  const counts = {};
  for (const s of [].concat(ldMain && ldMain.interactionStatistic || [])) {
    if (!s || typeof s !== 'object') continue;
    const t = String(s.interactionType && (s.interactionType['@type'] || s.interactionType) || '').split(/[/#]/).pop().replace(/Action$/, '');
    if (t && s.userInteractionCount != null) counts[t.toLowerCase()] = String(s.userInteractionCount);
  }
  if (ldMain && ldMain.aggregateRating) counts.rating = String(ldMain.aggregateRating.ratingValue || '');
  const description = meta['og:description'] || meta['twitter:description'] || meta.description || pickLd('description');
  if (text.length < 140 && description.length > text.length) text = description;
  const video = meta['og:video:secure_url'] || meta['og:video:url'] || meta['og:video'] || meta['twitter:player'] || pickLd('embedUrl') || pickLd('contentUrl') || (document.querySelector('video') ? 'video element' : '');
  const main = {
    title: meta['og:title'] || meta['twitter:title'] || pickLd('headline') || pickLd('name') || (h1 ? textOf(h1) : '') || title,
    author: pickLd('author') || meta.author || meta['article:author'] || (authorEl ? textOf(authorEl).slice(0, 80) : ''),
    published: pickLd('datePublished') || pickLd('uploadDate') || meta['article:published_time'] || meta['og:article:published_time'] || (timeEl ? timeEl.getAttribute('datetime') : ''),
    picture: abs(meta['og:image:secure_url'] || meta['og:image'] || meta['twitter:image'] || pickLd('thumbnailUrl') || pickLd('image')),
    video: video ? (video === 'video element' ? video : abs(video)) : '',
    duration: pickLd('duration') || meta['og:video:duration'] || meta['video:duration'] || '',
    counts,
    site: meta['og:site_name'] || meta['application-name'] || location.hostname,
    type: meta['og:type'] || (ldMain ? types(ldMain).join(',') : ''),
    lang: document.documentElement.getAttribute('lang') || '',
    description: description.slice(0, 2000),
    text,
  };

  // ---------- what kind of page this is ----------
  const listTyped = ld.some(o => types(o).some(t => /ProfilePage|CollectionPage|SearchResultsPage|ItemList/.test(t)));
  // og:type "article" is set on archives and home pages too; trust it when the address names one thing.
  const oneThing = /\/[^/]*\d{6,}|\/[^/?#]*[\w%]+-[\w%]+-[\w%]+-[\w%]+[^/]*\/?$/.test(location.pathname);
  const itemTyped = !listTyped && (!!ldMain || /^(video|music)/.test(meta['og:type'] || '') ||
                                   (/^(article|book)/.test(meta['og:type'] || '') && (oneThing || text.length >= 1000)));
  // A page that names itself an article, video or post is one, whatever lists sit beside it (replies, related).
  // A big player on screen means the page is that one video, whatever else is listed beside it.
  const player = [...document.querySelectorAll('video, iframe[src*=player], iframe[src*=embed]')].some(v => { const b = box(v); return b.width * b.height >= VW * VH * 0.2 && b.top < VH; });
  let kind = 'page';
  if (itemTyped || (player && !listTyped)) kind = 'item';
  else if (rows.length >= 5 || (listTyped && rows.length >= 3)) kind = 'list';
  else if (text.length >= 500) kind = 'item';
  else if (rows.length >= 3) kind = 'list';
  if (kind !== 'list' || opts.article) {
    // Readability reads a copy, so the page itself is never changed; its HTML is turned back into paragraphs
    // in a parsed document, which loads nothing.
    const BLOCKS = /^(P|DIV|SECTION|ARTICLE|LI|UL|OL|H[1-6]|PRE|BLOCKQUOTE|FIGCAPTION|FIGURE|TABLE|TR|DL|DT|DD|HR|BR)$/;
    // Not aside: taken out first, it left BBC's article split and Readability kept only its last third.
    const STRIP = 'nav,footer,form,iframe,[role=navigation],[role=contentinfo],[role=complementary],[role=search],' +
                  '[role=dialog],[aria-modal=true],[role=doc-endnotes],[role=doc-bibliography],[role=doc-noteref],' +
                  '[role=doc-backlink],sup.reference,.references,.reflist,.mw-editsection,.infobox,.navbox,.noprint';
    const paras = [];
    let line = '';
    const flush = () => { const t = clean(line); if (t && t !== '##') paras.push(t); line = ''; };
    const rec = (n) => {
      if (n.nodeType === 3) { line += n.nodeValue; return; }
      if (n.nodeType !== 1 || /^(SCRIPT|STYLE|NOSCRIPT|TEMPLATE)$/.test(n.tagName.toUpperCase())) return;
      const block = BLOCKS.test(n.tagName.toUpperCase());
      if (block) flush();
      if (/^H[1-4]$/i.test(n.tagName)) line += '## ';
      for (const c of n.childNodes) rec(c);
      if (block) flush();
    };
    try {
      // Page chrome, reference lists and fact boxes are taken out of the copy first, as Firecrawl's excluded tags.
      const copy = document.cloneNode(true);
      for (const el of copy.querySelectorAll(STRIP)) el.remove();
      const article = new Readability(copy).parse();
      if (article && article.content) rec(new DOMParser().parseFromString(article.content, 'text/html').body);
    } catch (e) {}
    flush();
    const read = paras.join('\n\n');
    if (read.length >= 140 && read.length >= 0.3 * allText.length) text = read;
    // A related-links or references heading in the second half ends the article; credits after it go too.
    const RELATED = /^(## )?(相关阅读|相关报道|相关文章|相关新闻|延伸阅读|推荐阅读|猜你喜欢|相關閱讀|相關報導|参见|參見|参考文献|參考文獻|参考资料|參考資料|外部链接|外部連結|注释|註釋|related( articles| stories| reading| posts)?|read more|more stories|see also|references|external links|further reading|notes|you (may|might) also like|関連記事|関連項目|脚注|관련 기사)[:：]?$/i;
    const CREDIT = /^(责任编辑|責任編輯|编辑|編輯|来源|來源|校对|审核)[:：]\s*\S{1,20}$/;
    const kept = text.split('\n\n');
    const tail = kept.findIndex((p, i) => i >= kept.length / 2 && RELATED.test(p));
    if (tail > 0) kept.length = tail;
    while (kept.length > 1 && CREDIT.test(kept[kept.length - 1])) kept.pop();
    text = main.text = kept.join('\n\n').slice(0, MAX_TEXT);
  }
  const empty = bodyText.length < 120 && rows.length === 0 && !text;
  if (!wall.kind && empty) { wall.kind = 'empty'; wall.evidence = 'visible text ' + bodyText.length + ' chars'; }

  // ---------- what the site offers a visitor: its search and its hot lists ----------
  const sameSite = (u) => { try { const a = new URL(u).hostname.split('.').slice(-2).join('.'); return a === location.hostname.split('.').slice(-2).join('.'); } catch (e) { return false; } };
  const discovery = {opensearch: [], searchaction: [], forms: [], feeds: links.feeds || [], trends: [], inbox: []};
  for (const l of document.querySelectorAll('link[rel~="search" i][href]')) {
    if (/opensearchdescription/i.test(l.getAttribute('type') || '')) discovery.opensearch.push(abs(l.getAttribute('href')));
  }
  for (const o of ld) {
    if (!types(o).includes('WebSite')) continue;
    for (const a of [].concat(o.potentialAction || [])) {
      const t = a && ((a.target && (a.target.urlTemplate || a.target)) || a.urlTemplate);
      if (typeof t === 'string') discovery.searchaction.push(t);
    }
  }
  // Chromium's rule for a searchable form: GET, one text box, no password, text area or file.
  for (const f of document.querySelectorAll('form')) {
    if ((f.getAttribute('method') || 'get').toLowerCase() !== 'get' || f.querySelector('input[type=password],input[type=file],textarea')) continue;
    const texts = [...f.querySelectorAll('input')].filter(i => ['', 'text', 'search'].includes((i.getAttribute('type') || '').toLowerCase()) && i.name);
    if (texts.length !== 1) continue;
    const hidden = [...f.querySelectorAll('input[type=hidden][name]')].slice(0, 8).map(i => [i.name, i.value || '']);
    discovery.forms.push({action: abs(f.getAttribute('action') || here), input: texts[0].name, hidden});
  }
  const TREND = /热门|热榜|排行|榜|热搜|trending|popular|explore|discover|rank|ranking|\btop\b|ランキング|人気|인기|랭킹|популярн|тренд/i;
  // Where a signed-in account's messages, notifications or mail are: links named so, or with such a path.
  const INBOX = /消息|私信|通知|提醒|站内信|收件箱|邮件|信箱|訊息|私訊|郵件|^messages?$|inbox|notifications?|^dms?$|^mail$|メッセージ|お知らせ|受信|메시지|알림|쪽지|nachrichten|benachrichtigungen|posteingang|mensajes|notificaciones|bandeja|mensagens|notificações|caixa de entrada|сообщения|уведомления|входящие/i;
  const INBOX_PATH = /\/(messages?|inbox|notifications?|direct|dms?|mail|msg|notice)(\/|$)/i;
  const seenLinks = new Set();
  for (const a of document.querySelectorAll('a[href]')) {
    const h = realHref(a);
    if (!h || seenLinks.has(h) || !sameSite(h)) continue;
    const t = clean(a.innerText || a.getAttribute('aria-label') || a.getAttribute('title')).slice(0, 40);
    let path = ''; try { path = new URL(h).pathname; } catch (e) {}
    if (discovery.trends.length < 20 && (TREND.test(t) || TREND.test(path))) { discovery.trends.push({href: h, text: t}); seenLinks.add(h); }
    else if (discovery.inbox.length < 6 && (INBOX.test(t) || INBOX_PATH.test(path))) { discovery.inbox.push({href: h, text: t}); seenLinks.add(h); }
  }
  const ldText = [...document.querySelectorAll('script[type="application/ld+json"]')].slice(0, 10).map(s => (s.textContent || '').slice(0, 100000));

  return {
    url: here, title, kind, wall,
    meta: Object.entries(meta), ld: ldText, canonical: links.canonical || '', oembed: (links.oembed || [])[0] || '', text,
    discovery,
    main,
    rows,
    facts: {meta: Object.keys(meta).length, ld: ld.map(o => types(o).join(',')).slice(0, 12), microdata: microdata.slice(0, 5), links},
    debug: columns_debug,
    listParents: opts.debug ? listParents.map(p => sig(p).slice(0, 60) + ' ' + kids(p).length) : undefined,
    candidates: opts.debug ? candidates.filter(c => typeof opts.debug !== 'string' || sig(c.parent).includes(opts.debug)).slice(0, 8).map(c => [sig(c.parent).slice(0, 50), c.key.slice(0, 40), c.items.length, c.n, Math.round(c.score), c.nested, c.split || 0, listParents.length]) : undefined,
    stats: {elements: count, textChars: bodyText.length, scrollHeight: document.documentElement.scrollHeight},
  };
}
