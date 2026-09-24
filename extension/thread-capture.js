// Neuro Search extension — the thread/page capture producers, shared by the popup (the button) and the
// background worker (S92: auto-capture when the app itself opened the tab, see background.js). Plain functions
// that take a tab and return the capture contract; the server normalizes, the browser only reads.
(() => {
// ---- B1: the capture contract — produced in the browser, normalized only by the server ----
// Reddit: the same-origin JSON the user's own session is served (complete tree + expected comment count) is the
// preferred producer; the rendered DOM is the fallback (B2 adds completeness counts to it).
async function redditCapture(tab) {
  const [{ result }] = await chrome.scripting.executeScript({ target: { tabId: tab.id }, func: async () => {
    const path = location.pathname.replace(/\/$/, '').replace(/\.json$/, '');
    const norm = id => (id || '').replace(/^t[13]_/, '');
    try {
      const r = await fetch(`${location.origin}${path}.json?raw_json=1&limit=500&depth=12`, { credentials: 'include', headers: { Accept: 'application/json' } });
      if (r.ok) {
        const listing = await r.json();
        const link = listing[0].data.children[0].data;
        const comments = [];
        const walk = (children, parent, depth) => { for (const ch of children || []) { if (ch.kind !== 't1') continue; const d = ch.data;
          comments.push({ reddit_id: d.id, parent_id: parent, depth, author: d.author, text: d.body || '', score: d.score, created_at: d.created_utc, edited: !!d.edited,
            deleted: d.body === '[deleted]' || d.body === '[removed]' || d.author === '[deleted]', permalink: 'https://www.reddit.com' + (d.permalink || '') });
          if (d.replies && d.replies.data) walk(d.replies.data.children, d.id, depth + 1); } };
        if (listing[1]) walk(listing[1].data.children, link.id, 1);
        return { contract: 'reddit_thread_capture/1', method: 'json', canonical_url: 'https://www.reddit.com' + link.permalink,
          thread: { reddit_id: link.id, subreddit: link.subreddit_name_prefixed || ('r/' + link.subreddit), title: link.title, author: link.author, body: link.selftext || '', score: link.score,
                    created_at: link.created_utc, edited: !!link.edited, deleted: link.author === '[deleted]' && !link.selftext, permalink: 'https://www.reddit.com' + link.permalink, expected_comments: link.num_comments },
          comments, capture: { status: comments.length >= (link.num_comments || 0) ? 'complete' : 'partial', captured: comments.length, expected: link.num_comments, method: 'json' } };
      }
    } catch (e) { /* fall through to the DOM */ }
    // rendered DOM (www.reddit.com's shreddit-comment elements, or old.reddit's .thing rows): what the page shows, with what it does not
    const post = document.querySelector('shreddit-post');
    const title = (post && post.getAttribute('post-title')) || document.title;
    const rid = norm((post && post.getAttribute('id')) || (location.pathname.match(/\/comments\/([a-z0-9]+)/) || [])[1]);
    const comments = [];
    for (const el of document.querySelectorAll('shreddit-comment')) {
      const body = el.querySelector('[slot="comment"]');
      comments.push({ reddit_id: norm(el.getAttribute('thingid')), parent_id: norm(el.getAttribute('parentid')) || rid, depth: +(el.getAttribute('depth') || 0) + 1,
        author: el.getAttribute('author'), text: body ? body.innerText.trim() : '', score: +(el.getAttribute('score') || 0) || null, created_at: null, edited: false,
        deleted: /^\[(deleted|removed)\]$/.test(body ? body.innerText.trim() : ''), permalink: location.origin + (el.getAttribute('permalink') || '') });
    }
    for (const el of document.querySelectorAll('.commentarea .thing.comment')) {
      const md = el.querySelector(':scope > .entry .md');
      const parentThing = el.parentElement && el.parentElement.closest('.thing');
      comments.push({ reddit_id: norm(el.getAttribute('data-fullname')), parent_id: parentThing ? norm(parentThing.getAttribute('data-fullname')) : rid, depth: 1,
        author: el.getAttribute('data-author'), text: md ? md.innerText.trim() : '', score: +((el.querySelector(':scope > .entry .score.unvoted') || {}).title || 0) || null,
        created_at: ((el.querySelector(':scope > .entry time') || {}).dateTime ? Date.parse(el.querySelector(':scope > .entry time').dateTime) / 1000 : null), edited: !!el.querySelector(':scope > .entry time.edited-timestamp'),
        deleted: el.classList.contains('deleted'), permalink: location.origin + (el.getAttribute('data-permalink') || '') });
    }
    const expected = post ? +(post.getAttribute('comment-count') || 0) : +(((document.querySelector('.commentarea .panestack-title') || {}).innerText || '').match(/\d+/) || [0])[0];
    const more = document.querySelectorAll('shreddit-comment-tree faceplate-partial, .morecomments, .morechildren').length;
    const selftext = post ? (post.querySelector('[slot="text-body"]') || {}).innerText || '' : ((document.querySelector('#siteTable .thing.link .md') || {}).innerText || '');
    return { contract: 'reddit_thread_capture/1', method: 'dom', canonical_url: location.origin + location.pathname,
      thread: { reddit_id: rid, subreddit: (location.pathname.match(/\/(r\/[^/]+)\//) || [])[1] || '', title, author: post ? post.getAttribute('author') : (document.querySelector('#siteTable .thing.link') || { getAttribute: () => null }).getAttribute('data-author'),
                body: selftext, score: post ? +(post.getAttribute('score') || 0) : null, created_at: post && post.getAttribute('created-timestamp') ? Date.parse(post.getAttribute('created-timestamp')) / 1000 : null,
                edited: false, deleted: false, permalink: location.origin + location.pathname, expected_comments: expected || null },
      comments, capture: { status: expected && comments.length >= expected && !more ? 'complete' : (expected ? 'partial' : 'unknown'), captured: comments.length, expected: expected || null, load_more_remaining: more, method: 'dom' } };
  } });
  return result;
}

async function pageCapture(tab) {
  const [{ result }] = await chrome.scripting.executeScript({ target: { tabId: tab.id }, func: () => ({ contract: 'page_capture/1', method: 'dom', url: location.href, title: document.title, html: document.documentElement.outerHTML }) });
  return result;
}

  // S95: the JSON half of redditCapture for a thread that is NOT the tab's own page — Reddit serves the same-origin
  // .json to the person's session from any reddit.com tab, so a pending capture needs no tab of its own.
  async function redditCaptureUrl(tab, url) {
    const [{ result }] = await chrome.scripting.executeScript({ target: { tabId: tab.id }, func: async (u) => {
      const norm = id => (id || '').replace(/^t[13]_/, '');
      try {
        const x = new URL(u); x.hash = ''; x.search = '';
        const path = x.pathname.replace(/\/$/, '').replace(/\.json$/, '');
        const r = await fetch(`https://www.reddit.com${path}.json?raw_json=1&limit=500&depth=12`, { credentials: 'include', headers: { Accept: 'application/json' } });
        if (!r.ok) return { error: 'HTTP ' + r.status };
        const listing = await r.json();
        const link = listing[0].data.children[0].data;
        const comments = [];
        const walk = (children, parent, depth) => { for (const ch of children || []) { if (ch.kind !== 't1') continue; const d = ch.data;
          comments.push({ reddit_id: d.id, parent_id: parent, depth, author: d.author, text: d.body || '', score: d.score, created_at: d.created_utc, edited: !!d.edited,
            deleted: d.body === '[deleted]' || d.body === '[removed]' || d.author === '[deleted]', permalink: 'https://www.reddit.com' + (d.permalink || '') });
          if (d.replies && d.replies.data) walk(d.replies.data.children, d.id, depth + 1); } };
        if (listing[1]) walk(listing[1].data.children, link.id, 1);
        return { contract: 'reddit_thread_capture/1', method: 'json', canonical_url: 'https://www.reddit.com' + link.permalink,
          thread: { reddit_id: link.id, subreddit: link.subreddit_name_prefixed || ('r/' + link.subreddit), title: link.title, author: link.author, body: link.selftext || '', score: link.score,
                    created_at: link.created_utc, edited: !!link.edited, deleted: link.author === '[deleted]' && !link.selftext, permalink: 'https://www.reddit.com' + link.permalink, expected_comments: link.num_comments },
          comments, capture: { status: comments.length >= (link.num_comments || 0) ? 'complete' : 'partial', captured: comments.length, expected: link.num_comments, method: 'json' } };
      } catch (e) { return { error: String(e) }; }
    }, args: [url] });
    return result;
  }
  self.NSThreadCapture = { redditCapture, pageCapture, redditCaptureUrl };
})();
