// Neuro Search — course scanner library (extension 1.7.0, mission CS, docs/COURSE-SCANNER-2026-09-15.md; card rows 1.9.4).
//
// Plain script, no imports: it runs as a content script in the course tab (injected before scanner.js) AND under
// node/jsdom in tests/js/run.mjs, which is why every function takes the window/document it works on instead of
// touching globals. `NSScan.run` is the whole pipeline; scanner.js is only the bridge to the extension.
//
// What this is for, in one line: the user's own logged-in browser is the legitimate reader of a course, so the
// scanner operates the course's OWN navigation, reads what renders, and gives every lesson an explicit outcome.
// What it never does: click anything it has not positively identified as course navigation, press Play, read or
// send cookies (import does that, separately, on the user's press), or bypass anything.
(function () {
  'use strict';

  // ------------------------------------------------------------------ media identity (what counts as "a video")
  // Stable identities only: a Loom/Vimeo/YouTube/Wistia/Vidyard id names the same video tomorrow. A direct .mp4 /
  // .m3u8 / CDN address is kept as evidence with `ephemeral: true` — it can be downloaded now, but it is NOT an
  // identity to dedupe or remember by (signed delivery URLs change on every visit).
  const PLAYER = /loom\.com\/(embed|share)\/|player\.vimeo\.com\/video\/|vimeo\.com\/\d+|fast\.wistia\.(net|com)\/embed|wistia\.com\/medias\/|youtube(-nocookie)?\.com\/embed\/|youtu\.be\/|youtube\.com\/watch|vidyard\.com|bunny|mediadelivery\.net|stream\.mux\.com|\.m3u8|\.mp4/i;
  const IDENTITY = [
    ['loom', /loom\.com\/(?:embed|share)\/([a-f0-9]{32})/i, id => `https://www.loom.com/share/${id}`],
    ['vimeo', /player\.vimeo\.com\/video\/(\d+)(?:\?(?:[^#]*&)?h=([A-Za-z0-9]+))?/i, (id, h) => `https://vimeo.com/${id}` + (h ? `/${h}` : '')],
    ['vimeo', /(?:^|\/\/)(?:www\.)?vimeo\.com\/(\d+)(?:\/([A-Za-z0-9]+))?/i, (id, h) => `https://vimeo.com/${id}` + (h ? `/${h}` : '')],
    ['youtube', /youtube(?:-nocookie)?\.com\/embed\/([A-Za-z0-9_-]{11})/i, id => `https://www.youtube.com/watch?v=${id}`],
    ['youtube', /youtu\.be\/([A-Za-z0-9_-]{11})/i, id => `https://www.youtube.com/watch?v=${id}`],
    ['youtube', /youtube\.com\/watch\?(?:[^#]*&)?v=([A-Za-z0-9_-]{11})/i, id => `https://www.youtube.com/watch?v=${id}`],
    ['wistia', /wistia\.(?:com|net)\/(?:medias|embed\/iframe|embed\/medias)\/([a-z0-9]{10})/i, id => `https://fast.wistia.net/embed/iframe/${id}`],
    ['vidyard', /vidyard\.com\/(?:embed|share|watch)\/([A-Za-z0-9_-]{8,})/i, id => `https://share.vidyard.com/watch/${id}`],
  ];
  function mediaIdentity(url) {
    if (!url) return null;
    for (const [provider, re, canon] of IDENTITY) {
      const m = url.match(re);
      if (m) return { provider, id: m[1], url: canon(m[1], m[2]), ephemeral: false };
    }
    if (PLAYER.test(url)) {
      // measured only as "a thing yt-dlp may download right now": key by host+path, never by query
      let u; try { u = new URL(url); } catch (e) { return null; }
      if (/\.(js|css|png|jpe?g|svg|webp|gif|json|woff2?)(\?|$)/i.test(u.pathname)) return null;
      return { provider: 'direct', id: u.host + u.pathname, url: u.href, ephemeral: true };
    }
    return null;
  }
  const mediaKey = m => m.provider + ':' + m.id;

  // ------------------------------------------------------------------ Strategy C: players on a rendered document
  // opts.rendered: only what is RENDERED (iframes, video, data attributes, links) — the mode for an app-rendered
  // lesson, where the page's own state blob lists every lesson's video and a regex over the source would credit
  // all of them to whichever lesson is open. opts.root: scope to one element (the course's `main`).
  function findPlayers(doc, base, opts) {
    const o = opts || {}; const root = o.root || doc;
    const byKey = new Map();
    const add = (u, via) => {
      if (!u) return;
      try { u = new URL(u, base).href; } catch (e) { return; }
      const m = mediaIdentity(u.split('#')[0]);
      if (m && !byKey.has(mediaKey(m))) byKey.set(mediaKey(m), { ...m, via });
    };
    root.querySelectorAll('iframe[src],iframe[data-src]').forEach(el => add(el.getAttribute('src') || el.getAttribute('data-src'), 'iframe'));
    root.querySelectorAll('video[src],video source[src]').forEach(el => add(el.getAttribute('src'), 'video'));
    root.querySelectorAll('a[href]').forEach(el => add(el.getAttribute('href'), 'link'));
    root.querySelectorAll('[data-video-url],[data-url],[data-embed-url],[data-loom-url],[data-vimeo-id],[data-wistia-id]').forEach(el => {
      for (const a of ['data-video-url', 'data-url', 'data-embed-url', 'data-loom-url']) add(el.getAttribute(a), 'data');
      if (el.getAttribute('data-vimeo-id')) add('https://vimeo.com/' + el.getAttribute('data-vimeo-id'), 'data');
      if (el.getAttribute('data-wistia-id')) add('https://fast.wistia.net/embed/iframe/' + el.getAttribute('data-wistia-id'), 'data');
    });
    if (!o.rendered) {
      // players hidden in inline scripts / JSON (Kajabi, Teachable, Skool): stable identities only — an inline
      // CDN manifest is never promoted to a lesson's video by a regex over the page source
      const html = (doc.documentElement ? doc.documentElement.innerHTML : '').replace(/\\\//g, '/').replace(/&amp;/g, '&');
      for (const m of html.matchAll(/https?:\/\/[^"'\s<>\\)]+/g)) {
        const ident = mediaIdentity(m[0]);
        if (ident && !ident.ephemeral && !byKey.has(mediaKey(ident))) byKey.set(mediaKey(ident), { ...ident, via: 'inline' });
      }
    }
    return [...byKey.values()];
  }
  const renderedPlayers = (doc, base) => findPlayers(doc, base, { rendered: true, root: doc.querySelector('main') || doc.body });

  // ------------------------------------------------------------------ attachments: the DOCUMENTS a lesson links
  // CS7 (live Acquisition Ace): a course's written material — checklists, worksheets, a deal calculator — is not on
  // the lesson page, it is LINKED from it (nine PDFs behind Google Drive share links), and a lesson can be nothing
  // but that link. Recorded here as identities, never fetched here: the app fetches the file through its own
  // network boundary on import (`ingest_document_url`), with no cookies — a document host is not a video host.
  // Stable identities only: a Drive/Docs/Sheets/Slides id, a Dropbox path, or a direct address with a document
  // extension. The link's own text is usually a button ("Download Resource"): a title is taken from it only when
  // it names the file; otherwise the importer names the document after its lesson.
  const DOC_EXT = /\.(pdf|docx?|xlsx?|csv|pptx|epub|rtf|txt|md)(?:[?#]|$)/i;
  const DOC_IDENTITY = [
    ['gdrive', /drive\.google\.com\/(?:file\/d\/|open\?id=|uc\?(?:[^#]*&)?id=)([A-Za-z0-9_-]{10,})/i, id => `https://drive.google.com/file/d/${id}/view`],
    ['gdocs', /docs\.google\.com\/document\/d\/([A-Za-z0-9_-]{10,})/i, id => `https://docs.google.com/document/d/${id}`],
    ['gsheets', /docs\.google\.com\/spreadsheets\/d\/([A-Za-z0-9_-]{10,})/i, id => `https://docs.google.com/spreadsheets/d/${id}`],
    ['gslides', /docs\.google\.com\/presentation\/d\/([A-Za-z0-9_-]{10,})/i, id => `https://docs.google.com/presentation/d/${id}`],
  ];
  const GENERIC_LINK_TEXT = /^(?:\W|download|open|view|get|click|here|tap|resource|file|document|the|your|pdf|link|attachment|included|with|membership|to|and|now|it|this)*$/i;
  function documentIdentity(url) {
    if (!url) return null;
    for (const [provider, re, canon] of DOC_IDENTITY) {
      const m = url.match(re);
      if (m) return { provider, id: m[1], url: canon(m[1]) };
    }
    let u; try { u = new URL(url); } catch (e) { return null; }
    if (/(^|\.)dropbox\.com$/i.test(u.host) && /^\/(s|scl\/fi)\//.test(u.pathname)) return { provider: 'dropbox', id: u.pathname, url: u.origin + u.pathname };
    if (DOC_EXT.test(u.pathname)) return { provider: 'file', id: u.host + u.pathname, url: u.href.split('#')[0], ext: (u.pathname.match(DOC_EXT) || [])[1] };
    return null;
  }
  const docKey = d => d.provider + ':' + d.id;
  function findAttachments(doc, base, opts) {
    const root = (opts && opts.root) || doc.querySelector('main') || doc.body;
    const byKey = new Map();
    root.querySelectorAll('a[href]').forEach(a => {
      if (inChrome(a)) return;
      let u; try { u = new URL(a.getAttribute('href'), base).href; } catch (e) { return; }
      const d = documentIdentity(u); if (!d || byKey.has(docKey(d))) return;
      let title = '';
      if (d.ext) { const f = decodeURIComponent(d.id.split('/').pop() || ''); if (f) title = f.slice(0, 120); }
      // a short, specific label names the file ("Deal Calculator.xlsx"); a button's text does not ("download
      // Download Resource Included with your membership north_east verified…", live — icon ligatures included)
      if (!title) { const t = wordsOf(a, 160); if (t && t.length <= 60 && !GENERIC_LINK_TEXT.test(t.replace(/[^a-z]+/gi, ' ').trim())) title = t; }
      byKey.set(docKey(d), { provider: d.provider, id: d.id, url: d.url, title, kind: d.ext ? d.ext.toLowerCase() : d.provider });
    });
    return [...byKey.values()];
  }

  // ------------------------------------------------------------------ text helpers
  const textOf = el => (el && el.textContent || '').replace(/\s+/g, ' ').trim();
  const norm = s => (s || '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();
  // text with a space at every node boundary (textContent glues "bonus" + "Sign in" into one word)
  function wordsOf(el, limit) {
    const doc = el.ownerDocument, out = []; let n = 0;
    const w = doc.createTreeWalker(el, 4 /* SHOW_TEXT */);
    for (let t = w.nextNode(); t && n < (limit || 4000); t = w.nextNode()) { const s = t.textContent.trim(); if (s) { out.push(s); n += s.length; } }
    return out.join(' ');
  }
  // CS5 (live SMB Market): a module/lesson row's own text can be glued across element boundaries by plain
  // textContent (a "6 lessons" span directly followed by a "New" badge span, no whitespace between them, breaks
  // LESSON_TEXT/MODULE_TEXT's trailing \b) -- the same class of problem wordsOf() already solves for BLOCKED_TEXT.
  // Used wherever a row/card is matched against LESSON_TEXT/MODULE_TEXT/DANGER, general behaviour, not SMB-specific.
  const rowText = el => wordsOf(el, 300);

  // ------------------------------------------------------------------ Strategy A: lesson LINKS on this page
  // 1.6.0's classifier, kept verbatim in behaviour (gate: tests/test_s32_course_scanner.py): a lesson word must be
  // a WORD; navigation landmarks are excluded structurally; a link under the course path is not a lesson by location.
  const BAD_LINK = /\/(login|logout|sign|account|settings|cart|checkout|privacy|terms|search|tag|category|author|calendar|partners|community|pricing|support|help|profile|billing)\b|#|mailto:|javascript:/i;
  const GOOD_LINK = /(?:^|[^a-z])(lessons?|lectures?|modules?|units?|posts?|watch|videos?|episodes?|chapters?|parts?|days?|weeks?|steps?)(?:[^a-z]|$)|courses\/[^/]+\//i;
  // landmark tags/roles are trustworthy at any distance; a class-name heuristic ("sidebar"/"navbar"/"breadcrumb")
  // is not -- a component library's own layout wrapper (e.g. shadcn/ui's `group/sidebar-wrapper`, found live on
  // SMB Market) can carry that substring on a div wrapping the WHOLE app, nav AND main content both, many levels
  // up. Trust the class heuristic only within a short climb (same bound siblingGroups uses for containers),
  // never all the way to <body> -- otherwise one page-root wrapper hides every real control on the page.
  const CHROME_LANDMARK = 'nav,aside,header,footer,[role=navigation],[role=banner],[role=contentinfo]';
  const CHROME_CLASS = '[class*=sidebar],[class*=navbar],[class*=breadcrumb]';
  const CHROME = CHROME_LANDMARK + ',' + CHROME_CLASS;   // kept for callers/tests that want the combined selector
  function inChrome(el, limit) {
    if (el && el.closest && el.closest(CHROME_LANDMARK)) return true;
    let e = el;
    for (let i = 0; i < (limit || 6) && e && e.nodeType === 1; i++, e = e.parentElement) {
      if (e.matches && e.matches(CHROME_CLASS)) return true;
    }
    return false;
  }
  function nearestModule(el, doc) {
    let e = el;
    for (let i = 0; i < 6 && e; i++) {
      e = e.parentElement; if (!e) break;
      const h = e.querySelector('h1,h2,h3,h4,[class*=module],[class*=section-title],[class*=category-title]');
      if (h && h !== el && !h.contains(el)) return textOf(h).slice(0, 80);
    }
    return '';
  }
  function classifyLinks(doc, here) {
    const ME = here.split('#')[0]; let host; try { host = new URL(here).host; } catch (e) { host = ''; }
    const seen = new Set(); const cands = [];
    doc.querySelectorAll('a[href]').forEach(a => {
      let u; try { u = new URL(a.getAttribute('href'), here); } catch (e) { return; }
      if (u.host !== host || BAD_LINK.test(u.href) || u.href.split('#')[0] === ME) return;
      if (inChrome(a)) return;
      const key = u.origin + u.pathname; if (seen.has(key)) return;
      const t = textOf(a); if (!t || t.length > 140) return;
      if (!GOOD_LINK.test(u.pathname) && !GOOD_LINK.test(t)) return;
      seen.add(key);
      cands.push({ title: t.slice(0, 120), page_url: u.href, module: nearestModule(a, doc) });
    });
    return cands;
  }

  // ------------------------------------------------------------------ Strategy B: lesson CONTROLS (positive identification)
  // A control is a lesson because of what it IS, not because of what it is not: several siblings in one container
  // that all read "<ordinal>. <title>[ <duration>]" — the repeated structure a course list has and a toolbar never
  // has. Module cards are the same idea one level up: siblings reading "<title> N lessons". The denylist below is a
  // SECOND barrier for the one case a container is mixed, never the first.
  // CS5 (live SMB Market): the ordinal digit and its "." can render as separate text nodes ("1", then ".") --
  // rowText()'s TreeWalker join inserts a space between them ("1 . Title"), which a rigid \d[.)] adjacency
  // rejects. \s* between the ordinal and its punctuation tolerates that without weakening the anchor (still
  // digits-then-punctuation at the very start of the row, never matching arbitrary numbers mid-title).
  const LESSON_TEXT = /^(\d{1,3})\s*[.)]\s+(.{2,140}?)(?:\s*(\d{1,3})\s*(?:m|min|mins|minutes)\b\s*)?$/i;
  const MODULE_TEXT = /^(.{2,120}?)\s*(\d{1,3})\s*lessons?\b/i;
  const DANGER = /\b(buy|purchase|checkout|cart|pay|billing|subscribe|enrol|enroll|upgrade|unlock|log ?out|sign ?out|sign ?in|log ?in|delete|remove|submit|post|reply|comment|save|complete|mark|quiz|certificate|download|share|report|next|prev|previous|start course|resume|continue)\b/i;
  const CONTROL_SEL = 'button,[role=button],[role=tab],[role=option],[role=menuitem],[role=treeitem],li[tabindex],div[tabindex]';

  function isDangerous(el, text) {
    // `text`: what to judge by wording. A control row IS its text; a card row is judged by its TITLE (a card's
    // blurb is prose that may say "complete", "next" or "share" as ordinary language, never as an action).
    const t = text != null ? text : rowText(el);
    if (el.matches && el.matches('a[href]')) {
      const href = el.getAttribute('href') || '';
      if (/^(mailto:|tel:|javascript:)/i.test(href)) return 'link-scheme';
      try { const u = new URL(href, el.ownerDocument.location.href); if (u.host !== el.ownerDocument.location.host) return 'external-link'; } catch (e) { return 'bad-link'; }
    }
    if (el.matches && el.matches('[type=submit],form button:not([type=button]),form [role=button]')) return 'form-submit';
    if (inChrome(el)) return 'site-chrome';
    // a real lesson/module TITLE is natural-language content and can legitimately contain a denylist word as
    // ordinary business vocabulary (found live on SMB Market: a module titled "Your Buy Box and Buyer Profile"
    // rejected over "buy") -- the denylist is a second barrier for a MIXED container, so anything that already
    // positively matches the lesson or module shape is exempt from it; only a shape-less row (an actual
    // toolbar/action control) is judged on wording alone.
    if (DANGER.test(t) && !LESSON_TEXT.test(t) && !MODULE_TEXT.test(t)) return 'danger-word';
    // A numbered row can still BE a disguised action slipped into the list ("2. Purchase the full course",
    // "3. Take quiz") rather than a lesson that merely mentions one of these words. Found live on SMB Market:
    // three genuine M&A lesson titles talk ABOUT a purchase price/agreement as course content -- "How to
    // Determine Your Purchase Price", "The Purchase Agreement Explained", "How to Quantify the Purchase Price
    // of a Business" -- and none of them OPEN with the word; a bare CTA does ("Purchase the full course"), or
    // is itself just the verb + a one-word object ("Take quiz"). Leading position (or, for a two-word row, the
    // word appearing at all) is what separates a title merely mentioning the topic from a row that IS the action,
    // a general and non-SMB-specific signal; it only narrows this already-narrow word list, never the main
    // denylist above.
    const lm = t.match(LESSON_TEXT);
    if (lm) {
      const title = lm[2].trim();
      const words = title.split(/\s+/).filter(Boolean);
      const NARROW = /^(quiz|certificate|purchase|checkout)$/i;
      const opensWithDanger = NARROW.test(words[0] || '');
      const shortAndDangerous = words.length <= 2 && /\b(quiz|certificate|purchase|checkout)\b/i.test(title);
      if (opensWithDanger || shortAndDangerous) return 'danger-word';
    }
    return null;
  }

  // Group candidate controls by the LOWEST ancestor that holds at least `min` of them (bounded climb): the direct
  // parent for a flat list, one wrapper up for li > button or section > button. Keep groups of >= min rows.
  function siblingGroups(doc, re, min) {
    const all = [];
    doc.querySelectorAll(CONTROL_SEL).forEach(el => {
      if (el.closest('a[href]') && !el.matches('a[href]')) return;      // a control inside a link is the link's
      if (el.querySelector('a[href]')) return;                           // a wrapper around a link is not a control
      const t = rowText(el); if (!t || t.length > 200 || !re.test(t)) return;
      all.push(el);
    });
    // one control per visual row: if a wrapper and its inner button both matched, keep the innermost
    const rows = all.filter(el => !all.some(o => o !== el && el.contains(o)));
    const byContainer = new Map();
    for (const el of rows) {
      let c = el.parentElement, found = null;
      for (let i = 0; i < 5 && c; i++, c = c.parentElement) {
        if (rows.filter(r => c.contains(r)).length >= min) { found = c; break; }
      }
      if (!found) continue;
      if (!byContainer.has(found)) byContainer.set(found, []);
      byContainer.get(found).push(el);
    }
    const groups = [];
    for (const [container, els] of byContainer) if (els.length >= min && !inChrome(container)) groups.push({ container, rows: els });
    return groups.sort((a, b) => b.rows.length - a.rows.length);
  }

  // ------------------------------------------------------------------ Strategy B, second shape: lesson CARDS
  // CS6 (live Acquisition Ace, courses.benkelly.co): a course whose lesson rows are plain <div>s — no button, no
  // role, no tabindex, no link, no ordinal — each holding ONE heading (the title), a blurb and a "Duration 5:00"
  // badge, laid out under "Chapter NN · Title  NN Lessons Total" headers; a framework click handler on the div
  // opens the lesson (the URL moves, the whole <main> is replaced, a Loom iframe renders). Nothing in the
  // control shape above sees it: CONTROL_SEL never matches a bare div and LESSON_TEXT wants "<ordinal>. <title>".
  // Positive identification, same principle as the control shape: a CARD is the ancestor of a heading whose
  // parent holds >= 2 siblings that each hold exactly one heading (the repeated structure a lesson list has),
  // and a card GROUP is a lesson list only when its rows carry durations (at least half of them) or the group
  // sits under a module/chapter header ("Chapter 05 · Conclusion 10 Lessons Total" — the ordinal-less bonus
  // rows are lessons because their chapter says so). A card that contains a link or a control belongs to the
  // other shapes (its click target is ambiguous), and a card is judged for danger by its title alone.
  // Ordinals are page order (the site has none); durations parse "m:ss" (rounded up) or "N min".
  const CARD_HEAD = 'h2,h3,h4,h5';
  const CARD_DURATION = /(?:^|\s)(\d{1,3}):(\d{2})(?=\s|$)|(?:^|\s)(\d{1,3})\s*(?:m|min|mins|minutes)(?=\s|$)/i;
  const CHAPTER_HEAD = /\b(chapter|module|section|unit|week|part|day)\s*\d{1,3}\b/i;
  function cardDuration(t) {
    const m = t.match(CARD_DURATION); if (!m) return null;
    if (m[3]) return +m[3];
    return Math.max(1, +m[1] + (+m[2] > 0 ? 1 : 0));
  }
  function cardModule(container) {
    // the header this card list sits under: the container's own previous sibling, or its parent's. `module` is
    // true only for a header that SAYS it is one ("<title> N lessons", "Chapter 05 · …"); a plain heading is
    // kept as the module title but proves nothing about the cards below it.
    for (const c of [container, container.parentElement]) {
      if (!c) break;
      let p = c.previousElementSibling;
      for (let i = 0; i < 2 && p; i++, p = p.previousElementSibling) {
        const t = wordsOf(p, 200); if (!t) continue;
        const m = t.match(MODULE_TEXT); if (m) return { title: m[1].trim().slice(0, 120), module: true };
        if (CHAPTER_HEAD.test(t) && t.length <= 160) return { title: t.slice(0, 120), module: true };
        if (p.matches && p.matches(CARD_HEAD) && t.length <= 160) return { title: t.slice(0, 120), module: false };
      }
    }
    return { title: '', module: false };
  }
  function cardRows(doc) {
    const root = doc.querySelector('main') || doc.body;
    const oneHead = el => el.nodeType === 1 && el.querySelectorAll(CARD_HEAD).length === 1;
    const byContainer = new Map();
    root.querySelectorAll(CARD_HEAD).forEach(h => {
      const title = textOf(h); if (title.length < 2 || title.length > 140 || inChrome(h)) return;
      let e = h.parentElement, card = null;
      for (let i = 0; i < 4 && e && e !== root; i++, e = e.parentElement) {
        const p = e.parentElement; if (!p) break;
        const sibs = [...p.children].filter(oneHead);
        if (sibs.length >= 2 && sibs.includes(e)) { card = e; break; }
      }
      if (!card) return;
      if (card.querySelector('a[href],' + CONTROL_SEL) || card.closest('a[href]')) return;
      if (card.matches && card.matches(CONTROL_SEL)) return;                 // a control is the control shape's
      const c = card.parentElement;
      if (!byContainer.has(c)) byContainer.set(c, []);
      byContainer.get(c).push({ el: card, title: title.slice(0, 140), duration_min: cardDuration(wordsOf(card, 300)) });
    });
    const out = [];
    for (const [container, rows] of byContainer) {
      if (rows.length < 2 || inChrome(container)) continue;
      const head = cardModule(container);
      const timed = rows.filter(r => r.duration_min != null).length;
      if (timed * 2 < rows.length && !head.module) continue;
      for (const r of rows) out.push({ ...r, module: head.title, danger: isDangerous(r.el, r.title) });
    }
    // page order, ordinals by position; danger is a per-row verdict, never a group one
    out.sort((a, b) => (a.el.compareDocumentPosition(b.el) & 4) ? -1 : 1);
    return out.filter(r => !r.danger).map((r, i) => ({ ...r, ordinal: i + 1, shape: 'card' }));
  }

  // every lesson row on the page, whatever group it sits in (an accordion shows several modules' rows at once)
  function allLessonRows(doc) {
    const out = [];
    for (const g of siblingGroups(doc, LESSON_TEXT, 2)) for (const el of g.rows) {
      const m = rowText(el).match(LESSON_TEXT); const l = { el, ordinal: +m[1], title: m[2].trim(), duration_min: m[3] ? +m[3] : null, danger: isDangerous(el) };
      if (!l.danger) out.push(l);
    }
    return out.length ? out : cardRows(doc);
  }
  function findLessonStructure(doc) {
    const lessonGroups = siblingGroups(doc, LESSON_TEXT, 2).map(g => ({
      container: g.container,
      lessons: g.rows.map(el => { const m = rowText(el).match(LESSON_TEXT); return { el, ordinal: +m[1], title: m[2].trim(), duration_min: m[3] ? +m[3] : null, danger: isDangerous(el) }; })
                     .filter(l => !l.danger)
                     .sort((a, b) => a.ordinal - b.ordinal),
    })).filter(g => g.lessons.length >= 2);
    const moduleGroups = siblingGroups(doc, MODULE_TEXT, 2).map(g => ({
      container: g.container,
      modules: g.rows.map(el => { const m = rowText(el).match(MODULE_TEXT); return { el, title: m[1].trim().slice(0, 120), lesson_count: +m[2], danger: isDangerous(el) }; })
                     .filter(x => !x.danger),
    })).filter(g => g.modules.length >= 2);
    // the module heading a lesson list sits under: nearest preceding h1-h3 inside main, else the page title
    let lessons = lessonGroups[0] ? lessonGroups[0].lessons : [];
    const modules = moduleGroups[0] ? moduleGroups[0].modules : [];
    let cards = 0;
    if (lessons.length < 2 && modules.length < 2) { const cr = cardRows(doc); if (cr.length >= 2) { lessons = cr; cards = cr.length; } }
    return { lessons, modules, cards, lesson_groups: lessonGroups.length, module_groups: moduleGroups.length,
             expected_from_modules: modules.reduce((n, m) => n + (m.lesson_count || 0), 0) };
  }

  // A control that takes the user BACK to the module list: a breadcrumb item that is not the current (last) crumb,
  // is a button or a same-document link, and is not dangerous. Never history.back(): a one-address course would
  // leave the page.
  function findBackControl(doc, startUrl) {
    const crumbs = [...doc.querySelectorAll('[data-slot=breadcrumb-link],[data-slot=breadcrumb-item] button,[data-slot=breadcrumb-item] a,nav[aria-label*=breadcrumb i] a,nav[aria-label*=breadcrumb i] button,ol[class*=breadcrumb] a,ol[class*=breadcrumb] button,[class*=breadcrumb] button,[class*=breadcrumb] a[href]')];
    const usable = crumbs.filter(el => {
      if (el.matches('a[href]')) { try { return new URL(el.getAttribute('href'), startUrl).href.split('#')[0] === startUrl.split('#')[0]; } catch (e) { return false; } }
      return true;
    });
    // the LAST usable crumb is the level just above the current view (its module list); the first is the
    // site root ("All Courses"), which would leave the course. A `[aria-current]` crumb is the view itself.
    // The lesson LIST page shows "All Courses" alone (found live), and clicking it leaves the course; a lesson
    // view shows "All Courses › <course> › <current>". Prefer a crumb with something AFTER it (a separator, the
    // current crumb): that is a level inside the trail. A trail whose only crumb is a lone button (an SMB-shaped
    // "Learning" link with the current name outside the trail) keeps working: it is the fallback, not refused.
    const up = usable.filter(el => !el.hasAttribute('aria-current'));
    const inner = up.filter(el => !!((el.closest('li,[data-slot=breadcrumb-item]') || el).nextElementSibling));
    const pick = inner.length ? inner : up;
    return pick.length ? pick[pick.length - 1] : null;
  }

  // ------------------------------------------------------------------ settle + change verdict (CS0 outputs)
  // CS0 outputs (docs/COURSE-SCANNER-2026-09-15.md): SMB's lesson view settled ≈130 ms after the click with
  // player scaffolding stable by ≈1.4 s; a 500 ms quiet window + iframe-set stability catches that with room, and
  // the 6 s cap is wall-clock so a throttled background tab only slows the scan. grace_ms is the one extra wait a
  // lesson with NO player gets before it is called no_video (lazy embeds) — never paid on a lesson that has one.
  const SETTLE = { min_ms: 250, quiet_ms: 500, cap_ms: 6000, sample_ms: 100, grace_ms: 1500 };
  function playersSig(doc) { return renderedPlayers(doc, doc.location ? doc.location.href : 'https://x/').map(mediaKey).sort().join('|'); }
  function headingOf(doc) {
    const main = doc.querySelector('main') || doc.body;
    const h = main.querySelector('h1,h2'); return textOf(h).slice(0, 200);
  }
  function signature(doc, win) {
    return { heading: headingOf(doc), players: playersSig(doc), url: (doc.location && doc.location.href) || '',
             resources: win && win.performance && win.performance.getEntriesByType ? win.performance.getEntriesByType('resource').length : 0,
             iframes: doc.querySelectorAll('iframe').length };
  }
  function settle(win, doc, opts) {
    const o = { ...SETTLE, ...(opts || {}) };
    // observe the document, not <main>: a router that replaces the <main> element on every route (found live on
    // Acquisition Ace) leaves an observer bound to the old node deaf, and "quiet" would be declared at min_ms
    const root = doc.body || doc.documentElement;
    const t0 = Date.now(); let mutations = 0, lastMut = Date.now();
    let mo = null;
    if (win.MutationObserver) { mo = new win.MutationObserver(ms => { mutations += ms.length; lastMut = Date.now(); }); mo.observe(root, { subtree: true, childList: true, attributes: true }); }
    let prevIfr = doc.querySelectorAll('iframe').length, stableIfr = 0;
    return new Promise(resolve => {
      const tick = () => {
        const now = Date.now(); const ifr = doc.querySelectorAll('iframe').length;
        stableIfr = ifr === prevIfr ? stableIfr + 1 : 0; prevIfr = ifr;
        const quiet = now - lastMut >= o.quiet_ms && stableIfr >= 2;
        if ((now - t0 >= o.min_ms && quiet) || now - t0 >= o.cap_ms) {
          if (mo) mo.disconnect();
          return resolve({ ms: now - t0, mutations, capped: now - t0 >= o.cap_ms && !quiet });
        }
        win.setTimeout(tick, o.sample_ms);
      };
      win.setTimeout(tick, o.sample_ms);
    });
  }
  // Multi-signal: any one of heading / player set / new resources / url is enough to call the lesson "shown";
  // none of them changing is the only way to `content_unchanged`. Mutation counts are diagnostic, never a verdict.
  function changed(before, after) {
    const signals = [];
    if (before.heading !== after.heading) signals.push('heading');
    if (before.players !== after.players) signals.push('players');
    if (after.resources > before.resources) signals.push('resources');
    if (before.url !== after.url) signals.push('url');
    return { changed: signals.length > 0, signals };
  }

  // ------------------------------------------------------------------ outcome contract
  // document_found (CS7): no player, but the lesson links at least one document — a lesson whose content IS a
  // file. A lesson with a player AND documents stays video_found; its documents ride on the record.
  const OUTCOMES = ['video_found', 'multiple_videos', 'document_found', 'no_video', 'needs_user_play', 'blocked', 'scan_failed', 'not_scanned'];
  const BLOCKED_TEXT = /\b(sign in to (view|watch|continue)|log in to (view|watch|continue)|upgrade to (access|unlock|watch)|subscribe to (unlock|watch)|this content is locked|members only|purchase to unlock|not enrolled)\b/i;
  const PLAYER_SHELL = '[class*=player],[data-player],.plyr,.video-js,[class*=video-container],[data-testid*=player]';
  function outcomeFor(doc, players, attachments) {
    const main = doc.querySelector('main') || doc.body;
    if (players.length === 1) return 'video_found';
    if (players.length > 1) return 'multiple_videos';
    if (BLOCKED_TEXT.test(wordsOf(main, 4000))) return 'blocked';
    if (attachments && attachments.length) return 'document_found';
    if (main.querySelector(PLAYER_SHELL)) return 'needs_user_play';
    return 'no_video';
  }

  // Duplicate media across lessons: acquired once, remembered per lesson. Returns {key: [lesson indexes]} for
  // every media identity referenced by more than one lesson. Ephemeral (signed) URLs are never grouped.
  function duplicates(lessons) {
    const idx = new Map();
    lessons.forEach((l, i) => (l.media || []).forEach(m => { if (m.ephemeral) return; const k = mediaKey(m); if (!idx.has(k)) idx.set(k, []); idx.get(k).push(i); }));
    const out = {}; for (const [k, v] of idx) if (v.length > 1) out[k] = v;
    return out;
  }

  // ------------------------------------------------------------------ platform adapter seam (empty until earned)
  // { name, match(doc) -> bool, lessons?(doc) -> same shape as findLessonStructure().lessons, back?(doc) -> el }
  const adapters = [];

  // ------------------------------------------------------------------ the pipeline
  // bridge: { emit(event, payload) -> Promise, cancelled() -> Promise<bool>, fetch(url) -> Promise<Response> }
  // Everything the extension needs to know arrives as events: 'lessons-found' {expected, strategy},
  // 'lesson' {index, record}, 'done' {summary}. The return value is the same summary, for tests.
  async function activate(win, el) {
    try { el.scrollIntoView && el.scrollIntoView({ block: 'center' }); } catch (e) { /* jsdom */ }
    el.click();
  }
  function activateHard(win, el) {
    // second attempt for frameworks that listen to pointer events rather than click
    const E = win.PointerEvent || win.MouseEvent;
    for (const type of ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click']) {
      try { el.dispatchEvent(new E(type, { bubbles: true, cancelable: true, composed: true })); } catch (e) { /* ignore */ }
    }
  }
  function findRow(doc, lesson) {
    // controls are re-rendered by SPAs; find the row again by ordinal + title, never by a stale node
    const want = norm(lesson.title);
    if (lesson.shape === 'card') {
      const cards = cardRows(doc).filter(r => norm(r.title) === want);
      const hit = cards.find(r => r.ordinal === lesson.ordinal) || cards[0];
      return hit ? hit.el : (lesson.el && lesson.el.isConnected ? lesson.el : null);
    }
    const rows = [...doc.querySelectorAll(CONTROL_SEL)].filter(el => { const m = rowText(el).match(LESSON_TEXT); return m && +m[1] === lesson.ordinal && norm(m[2]) === want; });
    return rows.find(el => !rows.some(o => o !== el && el.contains(o))) || (lesson.el && lesson.el.isConnected ? lesson.el : null);
  }
  function lessonRecord(lesson, moduleTitle, page_url, players, outcome, extra) {
    const x = extra || {};
    return { title: lesson.title, module: lesson.module || moduleTitle || '', page_url, ordinal: lesson.ordinal, duration_min: lesson.duration_min || null,
             outcome, media: players, video_urls: players.map(p => p.url), attachments: x.attachments || [], ...x };
  }

  async function run(win, bridge, opts) {
    const doc = win.document; const o = { limit: 200, fetch_workers: 4, settle: {}, ...(opts || {}) };
    const startUrl = doc.location.href;
    const diagnosis = { strategy: null, links: 0, controls: 0, modules: 0, on_page_players: 0, activated: 0, unchanged: 0,
                        expanded_modules: 0, blocked_signals: 0, cancelled: false, back_control: false, adapter: null };
    const lessons = []; let expected = 0;
    const emitLesson = async rec => { lessons.push(rec); await bridge.emit('lesson', { index: lessons.length - 1, record: rec }); };
    const cancelled = async () => { const c = await bridge.cancelled(); if (c) diagnosis.cancelled = true; return c; };
    const finish = async (status) => {
      const summary = { status, strategy: diagnosis.strategy, course: { title: (textOf(doc.querySelector('h1')) || doc.title || '').slice(0, 150), url: startUrl },
                        expected, lessons, duplicates: duplicates(lessons), diagnosis };
      await bridge.emit('done', summary); return summary;
    };

    // --- what the page the user is looking at already shows: this always counts (1.6.0 rule, kept)
    const here = findPlayers(doc, startUrl); diagnosis.on_page_players = here.length;

    // --- Strategy A: linked lessons
    const cands = classifyLinks(doc, startUrl); diagnosis.links = cands.length;
    const structure = (adapters.find(a => { try { return a.match(doc); } catch (e) { return false; } }) || null);
    if (structure) diagnosis.adapter = structure.name;
    const st = structure && structure.lessons ? { lessons: structure.lessons(doc), modules: [], expected_from_modules: 0 } : findLessonStructure(doc);
    diagnosis.controls = st.lessons.length; diagnosis.modules = st.modules.length; diagnosis.cards = st.cards || 0;

    if (cands.length >= 2 && st.lessons.length < 2) {
      diagnosis.strategy = 'linked'; expected = Math.min(cands.length, o.limit);
      await bridge.emit('lessons-found', { expected, strategy: 'linked' });
      const queue = cands.slice(0, o.limit); const results = new Array(queue.length);
      await Promise.all(Array.from({ length: o.fetch_workers }, async () => {
        while (queue.length) {
          if (await cancelled()) return;
          const c = queue.shift(); const idx = cands.indexOf(c);
          try {
            const r = await bridge.fetch(c.page_url);
            if (r.status === 401 || r.status === 403) { results[idx] = lessonRecord({ title: c.title, ordinal: idx + 1 }, c.module, c.page_url, [], 'blocked', { detail: 'http ' + r.status }); continue; }
            const html = await r.text();
            const d = new win.DOMParser().parseFromString(html, 'text/html');
            const players = findPlayers(d, c.page_url); const atts = findAttachments(d, c.page_url);
            const h1 = d.querySelector('h1'); const t = h1 ? textOf(h1) : '';
            results[idx] = lessonRecord({ title: (t && t.length < 140 ? t : c.title), ordinal: idx + 1 }, c.module, c.page_url, players, outcomeFor(d, players, atts), { attachments: atts });
          } catch (e) { results[idx] = lessonRecord({ title: c.title, ordinal: idx + 1 }, c.module, c.page_url, [], 'scan_failed', { detail: String(e).slice(0, 200) }); }
        }
      }));
      if (here.length) { const known = new Set(results.filter(Boolean).flatMap(r => r.media.map(mediaKey))); const fresh = here.filter(p => !known.has(mediaKey(p))); if (fresh.length) await emitLesson(lessonRecord({ title: doc.title, ordinal: 0 }, 'this page', startUrl, fresh, outcomeFor(doc, fresh))); }
      for (let i = 0; i < cands.length && i < o.limit; i++) await emitLesson(results[i] || lessonRecord({ title: cands[i].title, ordinal: i + 1 }, cands[i].module, cands[i].page_url, [], 'not_scanned'));
      return finish(diagnosis.cancelled ? 'cancelled' : 'done');
    }

    // --- Strategy B: interactive SPA course
    if (st.lessons.length >= 2 || st.modules.length >= 2) {
      diagnosis.strategy = 'interactive';
      const modules = st.modules.length >= 2 && st.lessons.length < 2 ? st.modules : [null];
      expected = st.expected_from_modules || st.lessons.length;
      await bridge.emit('lessons-found', { expected, strategy: 'interactive' });
      const homeSig = signature(doc, win);
      let backEl = null;
      for (let mi = 0; mi < modules.length; mi++) {
        if (await cancelled()) break;
        const mod = modules[mi];
        let moduleTitle = mod ? mod.title : (textOf(doc.querySelector('main h1, main h2')) || '');
        let rows;
        if (mod) {
          // Is the module card still on the page (an accordion, or a list that stays put), or did opening the
          // previous module replace the list (SMB)? Only the second needs a way back.
          let again = findLessonStructure(doc);
          let card = again.modules.find(m => norm(m.title) === norm(mod.title));
          if (!card && mi > 0) {
            backEl = (structure && structure.back && structure.back(doc)) || findBackControl(doc, startUrl);
            diagnosis.back_control = !!backEl;
            if (!backEl) { for (let k = mi; k < modules.length; k++) await emitLesson(lessonRecord({ title: modules[k].title, ordinal: 0 }, modules[k].title, startUrl, [], 'not_scanned', { detail: 'no way back to the module list' })); break; }
            await activate(win, backEl); await settle(win, doc, o.settle);
            again = findLessonStructure(doc); card = again.modules.find(m => norm(m.title) === norm(mod.title));
            if (!card) { for (let k = mi; k < modules.length; k++) await emitLesson(lessonRecord({ title: modules[k].title, ordinal: 0 }, modules[k].title, startUrl, [], 'not_scanned', { detail: 'module list did not come back' })); break; }
          }
          if (card) mod.el = card.el;
          const rowKey = l => l.ordinal + '|' + norm(l.title);
          const rowsBefore = new Set(allLessonRows(doc).map(rowKey));
          const s0 = signature(doc, win); await activate(win, mod.el); await settle(win, doc, o.settle); diagnosis.activated++;
          let rowsNow = allLessonRows(doc); let fresh = rowsNow.filter(l => !rowsBefore.has(rowKey(l)));
          if (!changed(s0, signature(doc, win)).changed && !fresh.length) { activateHard(win, mod.el); await settle(win, doc, o.settle); rowsNow = allLessonRows(doc); fresh = rowsNow.filter(l => !rowsBefore.has(rowKey(l))); }
          if (!changed(s0, signature(doc, win)).changed && !fresh.length) { diagnosis.unchanged++; for (let k = 0; k < (mod.lesson_count || 0); k++) await emitLesson(lessonRecord({ title: `${mod.title} · lesson ${k + 1}`, ordinal: k + 1 }, mod.title, startUrl, [], 'scan_failed', { detail: 'module did not open (content unchanged)' })); continue; }
          diagnosis.expanded_modules++;
          // the module's lessons are the rows that APPEARED when it opened; a view that replaced the whole list
          // (nothing survived) is the same thing — every row is new
          rows = fresh.length ? fresh : rowsNow;
          rows.sort((a, b) => a.ordinal - b.ordinal);
        } else {
          rows = (structure && structure.lessons ? structure.lessons(doc) : findLessonStructure(doc).lessons);
        }
        if (!rows.length) { if (mod) for (let k = 0; k < (mod.lesson_count || 0); k++) await emitLesson(lessonRecord({ title: `${mod.title} · lesson ${k + 1}`, ordinal: k + 1 }, mod.title, startUrl, [], 'scan_failed', { detail: 'module opened but no lesson rows were found' })); continue; }
        if (mod && mod.lesson_count && rows.length !== mod.lesson_count) diagnosis.count_mismatch = (diagnosis.count_mismatch || 0) + 1;
        for (const lesson of rows) {
          if (await cancelled()) break;
          let el = findRow(doc, lesson);
          if (!el && signature(doc, win).heading !== homeSig.heading) {
            // a lesson view that REPLACED the list (one address per lesson, the list only on the course page):
            // go back the way a module does, then look for the row again. Never from the list itself — there
            // the only crumb is the site root, and "back" would leave the course.
            const b = (structure && structure.back && structure.back(doc)) || findBackControl(doc, startUrl);
            if (b) { diagnosis.back_control = true; await activate(win, b); await settle(win, doc, o.settle); el = findRow(doc, lesson); }
          }
          if (!el) { await emitLesson(lessonRecord(lesson, moduleTitle, startUrl, [], 'scan_failed', { detail: 'lesson row vanished before it could be opened' })); continue; }
          const s0 = signature(doc, win);
          const alreadyShown = norm(s0.heading).includes(norm(lesson.title)) && s0.players;
          if (!alreadyShown) {
            await activate(win, el); await settle(win, doc, o.settle); diagnosis.activated++;
            let s1 = signature(doc, win);
            if (!changed(s0, s1).changed) { activateHard(win, el); await settle(win, doc, o.settle); s1 = signature(doc, win); }
            if (!changed(s0, s1).changed) { diagnosis.unchanged++; await emitLesson(lessonRecord(lesson, moduleTitle, startUrl, [], 'scan_failed', { detail: 'activated, but the page did not change (heading, players, resources all the same)' })); continue; }
          }
          let players = renderedPlayers(doc, startUrl);
          if (!players.length) {
            // a player that arrives AFTER the page has gone quiet (lazy embed, player script): one bounded grace
            // wait, polling for a player, before calling it no_video
            const grace = o.settle.grace_ms != null ? o.settle.grace_ms : SETTLE.grace_ms;
            const t0 = Date.now(); while (Date.now() - t0 < grace && !players.length) { await new Promise(r => win.setTimeout(r, o.settle.sample_ms || SETTLE.sample_ms)); players = renderedPlayers(doc, startUrl); }
          }
          const atts = findAttachments(doc, startUrl);
          const outcome = outcomeFor(doc, players, atts); if (outcome === 'blocked') diagnosis.blocked_signals++;
          if (atts.length) diagnosis.attachments = (diagnosis.attachments || 0) + atts.length;
          const shownAt = (doc.location && doc.location.href) || startUrl;
          await emitLesson(lessonRecord(lesson, moduleTitle, shownAt, players, outcome, { heading: headingOf(doc).slice(0, 140), attachments: atts }));
        }
      }
      // restore: back to where the user started (the module list, or the lesson that was showing)
      try {
        const b = (structure && structure.back && structure.back(doc)) || findBackControl(doc, startUrl);
        if (b && homeSig.heading !== signature(doc, win).heading) { await activate(win, b); await settle(win, doc, o.settle); }
      } catch (e) { /* restoration is best effort */ }
      return finish(diagnosis.cancelled ? 'cancelled' : 'done');
    }

    // --- nothing to operate: say what was seen
    diagnosis.strategy = 'none';
    if (here.length) { expected = 1; await bridge.emit('lessons-found', { expected: 1, strategy: 'none' }); await emitLesson(lessonRecord({ title: doc.title, ordinal: 0 }, 'this page', startUrl, here, outcomeFor(doc, here))); }
    else await bridge.emit('lessons-found', { expected: 0, strategy: 'none' });
    return finish('done');
  }

  globalThis.NSScan = { PLAYER, mediaIdentity, mediaKey, findPlayers, documentIdentity, findAttachments, classifyLinks, findLessonStructure, cardRows, findBackControl, isDangerous,
                        settle, signature, changed, outcomeFor, duplicates, adapters, run, OUTCOMES, SETTLE,
                        _re: { LESSON_TEXT, MODULE_TEXT, DANGER, BAD_LINK, GOOD_LINK, CHROME, CARD_DURATION, CHAPTER_HEAD } };
})();
