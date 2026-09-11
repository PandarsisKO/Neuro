// Runs inside the course page (content script, injected on demand). Finds lesson links and embedded players.
//
// 1.6.0 — measured against the page Kyle reported, smbmarket.com/dashboard/educational-hub/classroom/, in his own
// browser. It reported "No videos found — are you on the course home page, and logged in?" and listed two
// "lessons": `Partners` and `View calendar`. He was logged in and on the course page; three separate faults:
//
//   * `Partners` matched because the lesson pattern contained the bare substring `part`, and `/partners/` contains
//     it. The two calendar links matched because the pattern contains `classroom` and they sit UNDER the course
//     path — so "this link lives inside the course" was being read as "this link is a lesson". Every candidate on
//     that page was navigation: the site's own sidebar and a calendar link.
//   * Those two false positives then SILENCED the real result. The on-page fallback was
//     `if (!lessons.length && here.length)`, so the videos on the page the user is actually looking at were only
//     used when nothing else had been found at all.
//   * And that course cannot be crawled in the first place. Measured: the six course paths are
//     `<button class="group block w-full text-left">`, not links; every lesson renders at the SAME url; there are
//     zero `<video>` tags, zero iframes and no player url anywhere in the served html. So the honest answer for a
//     course like this is not "are you logged in" — it is "open the lesson and use Send this page".
(async () => {
  const PLAYER = /loom\.com\/(embed|share)\/|player\.vimeo\.com\/video\/|vimeo\.com\/\d+|fast\.wistia\.(net|com)\/embed|wistia\.com\/medias\/|youtube(-nocookie)?\.com\/embed\/|youtu\.be\/|youtube\.com\/watch|vidyard\.com|bunny|mediadelivery\.net|stream\.mux\.com|\.m3u8|\.mp4/i;
  const ME = location.href;
  const host = location.host;
  const abs = h => { try { return new URL(h, ME).href; } catch (e) { return null; } };

  function findVideos(doc, base) {
    const out = new Set();
    const add = u => { if (!u) return; try { u = new URL(u, base).href; } catch (e) { return; } if (PLAYER.test(u)) out.add(u.split('#')[0]); };
    doc.querySelectorAll('iframe[src], iframe[data-src], video source[src], video[src], a[href]').forEach(el => add(el.getAttribute('src') || el.getAttribute('data-src') || el.getAttribute('href')));
    doc.querySelectorAll('[data-video-url],[data-url],[data-embed-url],[data-loom-url],[data-vimeo-id],[data-wistia-id]').forEach(el => {
      for (const a of ['data-video-url', 'data-url', 'data-embed-url', 'data-loom-url']) add(el.getAttribute(a));
      if (el.getAttribute('data-vimeo-id')) out.add('https://vimeo.com/' + el.getAttribute('data-vimeo-id'));
      if (el.getAttribute('data-wistia-id')) out.add('https://fast.wistia.net/embed/iframe/' + el.getAttribute('data-wistia-id'));
    });
    // players hidden in inline scripts / JSON (common on Kajabi/Teachable/Skool)
    const html = (doc.documentElement ? doc.documentElement.innerHTML : '').replace(/\\\//g, '/').replace(/&amp;/g, '&');
    for (const m of html.matchAll(/https?:\/\/[^"'\s<>\\)]+/g)) {
      const u = m[0];
      if (PLAYER.test(u) && !/\.(js|css|png|jpg|svg)(\?|$)/i.test(u)) out.add(u.split('#')[0]);
    }
    return [...out];
  }

  function textOf(el) { return (el.textContent || '').replace(/\s+/g, ' ').trim(); }

  // 1. candidate lesson links on this page: same host, not nav/footer, look like lessons
  const seen = new Set();
  const cands = [];
  const bad = /\/(login|logout|sign|account|settings|cart|checkout|privacy|terms|search|tag|category|author|calendar|partners|community|pricing|support|help|profile|billing)\b|#|mailto:|javascript:/i;
  // A lesson word must be a WORD, not a substring: `part` inside "partners" is what put the site's own sidebar in
  // the list. `courses/<something>/` still counts because that shape really is a lesson address.
  const good = /(?:^|[^a-z])(lessons?|lectures?|modules?|units?|posts?|watch|videos?|episodes?|chapters?|parts?|days?|weeks?|steps?)(?:[^a-z]|$)|courses\/[^/]+\//i;
  // "This link is inside the course" is not evidence that it is a lesson. Navigation lives in these landmarks, and
  // excluding them is structural rather than a guess about words.
  const CHROME = 'nav,aside,header,footer,[role=navigation],[role=banner],[role=contentinfo],[class*=sidebar],[class*=navbar],[class*=breadcrumb]';
  document.querySelectorAll('a[href]').forEach(a => {
    const href = abs(a.getAttribute('href')); if (!href) return;
    let u; try { u = new URL(href); } catch (e) { return; }
    if (u.host !== host || bad.test(href) || u.href === ME || u.href === ME.split('#')[0]) return;
    if (a.closest(CHROME)) return;
    const key = u.origin + u.pathname; if (seen.has(key)) return;
    const t = textOf(a); if (!t || t.length > 140) return;
    if (!good.test(u.pathname) && !good.test(t)) return;
    seen.add(key);
    // module = nearest preceding heading
    let mod = '';
    let el = a;
    for (let i = 0; i < 6 && el; i++) { el = el.parentElement; if (!el) break; const h = el.querySelector('h1,h2,h3,h4,[class*=module],[class*=section-title],[class*=category-title]'); if (h && h !== a && !h.contains(a)) { mod = textOf(h).slice(0, 80); break; } }
    cands.push({ title: t.slice(0, 120), page_url: u.href, module: mod });
  });

  // 2. videos on this very page (single-lesson pages or all-on-one-page courses)
  const here = findVideos(document, ME);

  // 3. fetch each lesson page with the user's cookies and look for players
  const lessons = [];
  let done = 0;
  const limit = 120;
  const queue = cands.slice(0, limit);
  const workers = Array.from({ length: 4 }, async () => {
    while (queue.length) {
      const c = queue.shift();
      try {
        const r = await fetch(c.page_url, { credentials: 'include' });
        const html = await r.text();
        const doc = new DOMParser().parseFromString(html, 'text/html');
        const vids = findVideos(doc, c.page_url);
        const h1 = doc.querySelector('h1'); const t = h1 ? textOf(h1) : '';
        lessons.push({ ...c, title: (t && t.length < 140 ? t : c.title), video_urls: vids });
      } catch (e) { lessons.push({ ...c, video_urls: [], error: String(e) }); }
      done++;
      chrome.runtime.sendMessage({ type: 'progress', done, total: cands.length }).catch(() => {});
    }
  });
  await Promise.all(workers);
  // keep original order
  const order = new Map(cands.map((c, i) => [c.page_url, i]));
  lessons.sort((a, b) => order.get(a.page_url) - order.get(b.page_url));
  // The page the user is LOOKING AT always counts, whatever else was found: two bad candidates must never be able
  // to discard a real video that is on screen.
  if (here.length) {
    const known = new Set(lessons.flatMap(l => l.video_urls));
    const fresh = here.filter(v => !known.has(v));
    if (fresh.length) lessons.unshift({ title: document.title, page_url: ME, module: 'this page', video_urls: fresh });
  }

  // Is this an app-rendered course — one address, lessons as click handlers? Then there is nothing to crawl, and
  // saying "are you logged in?" sends the user to look for a problem they do not have. Measured on smbmarket:
  // six `<button>` cards reading "Getting Started 6 lessons", no per-lesson href anywhere.
  const clickable = [...document.querySelectorAll('button,[role=button],[role=tab],li')].filter(el => {
    if (el.closest('a[href]')) return false;
    const t = textOf(el);
    return t.length < 120 && /\b\d+\s*lessons?\b|^\s*\d+\.\s+\S|\b\d+\s*(m|min|mins|minutes)\b/i.test(t);
  }).length;
  const app_rendered = clickable >= 3 && !cands.length;

  const title = (document.querySelector('h1') && textOf(document.querySelector('h1'))) || document.title;
  chrome.runtime.sendMessage({ type: 'result', course: { title: title.slice(0, 150), url: ME }, lessons,
                              truncated: cands.length > limit,
                              diagnosis: { candidates: cands.length, on_page_videos: here.length,
                                           clickable_lessonish: clickable, app_rendered } });
})();
