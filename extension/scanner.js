// Runs inside the course page (content script, injected on demand). Finds lesson links and embedded players.
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
  const bad = /\/(login|logout|sign|account|settings|cart|checkout|privacy|terms|search|tag|category|author)\b|#|mailto:|javascript:/i;
  const good = /(lesson|lecture|module|unit|lessons|posts|classroom|courses\/.+\/|watch|video|episode|chapter|day|week|step|part)/i;
  document.querySelectorAll('a[href]').forEach(a => {
    const href = abs(a.getAttribute('href')); if (!href) return;
    let u; try { u = new URL(href); } catch (e) { return; }
    if (u.host !== host || bad.test(href) || u.href === ME || u.href === ME.split('#')[0]) return;
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
  if (!lessons.length && here.length) lessons.push({ title: document.title, page_url: ME, module: '', video_urls: here });

  const title = (document.querySelector('h1') && textOf(document.querySelector('h1'))) || document.title;
  chrome.runtime.sendMessage({ type: 'result', course: { title: title.slice(0, 150), url: ME }, lessons, truncated: cands.length > limit });
})();
