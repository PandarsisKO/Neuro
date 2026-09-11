const $ = s => document.querySelector(s);
let cfg = {}, result = null;

let WANTED = null;   // the app's waiting capture request for the current tab, if any

function canon(u) {
  try { const x = new URL(u); x.hash = ''; x.search = ''; return (x.origin + x.pathname).replace(/^https?:\/\/(www\.|old\.|new\.)?/, 'https://').replace(/\/$/, ''); } catch (e) { return u; }
}

async function load() {
  cfg = await chrome.storage.local.get(['appUrl', 'token', 'lastProject']);
  if (cfg.appUrl && cfg.token) {
    $('#setup').style.display = 'none'; $('#main').style.display = ''; $('#cfg').textContent = cfg.appUrl;
    try {
      const ps = await api('/api/projects');
      $('#pageProject').innerHTML = ps.map(p => `<option value="${p.id}" ${p.id === cfg.lastProject ? 'selected' : ''}>${esc(p.name)}</option>`).join('') || '<option value="">(create a project in the app first)</option>';
    } catch (e) { $('#pageMsg').textContent = 'Could not load projects: ' + e.message; }
    try {
      // B1: does the app want THIS page? (one click, the project and reason already known)
      await api('/api/extension/heartbeat', { method: 'POST', body: JSON.stringify({ version: chrome.runtime.getManifest().version }) });
      const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
      const p = await api('/api/capture/pending');
      const items = p.items || [];
      WANTED = items.find(i => canon(i.canonical_url || i.url || '') === canon(tab.url)) || null;
      if (WANTED) {
        $('#wanted').style.display = '';
        $('#wantedWhy').innerHTML = `Project: <b>${esc(WANTED.project_name || '')}</b>${WANTED.reason ? `<br>${esc(WANTED.reason)}` : ''}`;
        if (WANTED.project_id) $('#pageProject').value = WANTED.project_id;
      }
      const others = items.filter(i => i !== WANTED);
      if (others.length) {
        $('#queue').style.display = '';
        $('#queue').innerHTML = `${others.length} more page${others.length === 1 ? '' : 's'} waiting for your browser — next: <a href="${esc(others[0].canonical_url || others[0].url)}" target="_blank">${esc(others[0].title || others[0].canonical_url || others[0].url)}</a>`;
      }
      chrome.runtime.sendMessage({ type: 'refresh-pending' }, () => void chrome.runtime.lastError);
    } catch (e) { /* no capture context: the ordinary buttons still work */ }
  }
}

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

// A shortfall against Reddit's comment count is usually deleted/removed comments (still counted); only a large one, or
// unexpanded branches, means the page really did not load everything. Never shown in red: a capture is a success.
function partialNote(cap) {
  if (!cap || cap.captured == null || cap.expected == null) return '';
  const missing = Math.max(0, cap.expected - cap.captured), more = cap.load_more_remaining || 0;
  if (!more && missing <= Math.max(5, Math.floor(cap.expected * 0.1))) return missing ? ` <span class="muted">(Reddit counts ${cap.expected}; the difference is usually deleted comments.)</span>` : '';
  return ` <span class="warn">Partial: ${cap.captured} of ~${cap.expected} comments were on the page${more ? ` (${more} “more replies” not expanded)` : ''}. Expand them and capture again to add the rest.</span>`;
}

async function pageCapture(tab) {
  const [{ result }] = await chrome.scripting.executeScript({ target: { tabId: tab.id }, func: () => ({ contract: 'page_capture/1', method: 'dom', url: location.href, title: document.title, html: document.documentElement.outerHTML }) });
  return result;
}

$('#captureWanted').onclick = async () => {
  if (!WANTED) return;
  $('#captureWanted').disabled = true; $('#wantedMsg').textContent = 'capturing…';
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    const payload = WANTED.adapter === 'reddit_thread' ? await redditCapture(tab) : await pageCapture(tab);
    if (!payload) throw new Error('nothing could be read from this page');
    const r = await api(`/api/capture/${WANTED.job_id}`, { method: 'POST', body: JSON.stringify(payload) });
    const cap = payload.capture || {};
    $('#wantedMsg').innerHTML = `<span class="ok">Captured${cap.captured != null ? ` ${cap.captured} comments` : ''} — the app is finishing it.</span>${partialNote(cap)}`;
    WANTED = null; $('#wanted').style.opacity = .6;
    chrome.runtime.sendMessage({ type: 'refresh-pending' }, () => void chrome.runtime.lastError);
  } catch (e) { $('#wantedMsg').innerHTML = `<span class="bad">${esc(e.message)}</span>`; $('#captureWanted').disabled = false; }
};

$('#sendPage').onclick = async () => {
  const pid = $('#pageProject').value; if (!pid) return;
  $('#sendPage').disabled = true; $('#pageMsg').textContent = 'capturing page…';
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    const host = new URL(tab.url).hostname.replace(/^www\./, '');
    if ((host === 'reddit.com' || host.endsWith('.reddit.com')) && /\/comments\//.test(new URL(tab.url).pathname)) {
      // a Reddit thread: Reddit refuses every non-browser reader, so the thread's JSON is read here, inside your own
      // browser session, and handed to the app — the app stores it exactly as it would a thread it read itself
      $('#pageMsg').textContent = 'reading the thread in your browser…';
      const payload = await redditCapture(tab);
      if (!payload || !payload.thread || !payload.thread.reddit_id) throw new Error('could not read the thread (are you logged in to Reddit?)');
      $('#pageMsg').textContent = 'sending…';
      const r = await api(`/api/projects/${pid}/ingest/thread`, { method: 'POST', body: JSON.stringify({ url: payload.canonical_url.replace(/\/\/(old|new)\.reddit\.com/, '//www.reddit.com'), capture: payload, title: tab.title }) });
      await chrome.storage.local.set({ lastProject: pid });
      const cap = payload.capture || {};
      $('#pageMsg').innerHTML = r.resolved_pending ? `<span class="ok">Captured — the app is finishing the thread it was waiting for.</span>${partialNote(cap)}` : `<span class="ok">Added “${esc(r.title)}” (${r.posts} posts, ${r.substantive} substantive).</span>${partialNote(cap)} See Sources → Communities in the app.`;
      $('#sendPage').disabled = false; return;
    }
    const MEDIA = ['instagram.com', 'tiktok.com', 'vimeo.com', 'loom.com', 'facebook.com', 'x.com', 'twitter.com', 'wistia.com'];
    if (MEDIA.some(h => host === h || host.endsWith('.' + h))) {
      // a video/post page: send the link plus this site's cookies so the app can download it as you
      $('#pageMsg').textContent = 'collecting this site\'s session…';
      let cookies = [];
      const base = host.split('.').slice(-2).join('.');
      for (const dom of new Set([host, base, '.' + base])) { try { cookies = cookies.concat(await chrome.cookies.getAll({ domain: dom })); } catch (e) {} }
      const seen = new Set(); cookies = cookies.filter(c => { const k = c.domain + '|' + c.name + '|' + c.path; if (seen.has(k)) return false; seen.add(k); return true; });
      const r = await api(`/api/projects/${pid}/ingest/with-session`, { method: 'POST', body: JSON.stringify({ url: tab.url, title: tab.title,
        cookies: cookies.map(c => ({ domain: c.domain, name: c.name, value: c.value, path: c.path, secure: c.secure, expirationDate: c.expirationDate })) }) });
      await chrome.storage.local.set({ lastProject: pid });
      $('#pageMsg').innerHTML = `<span class="ok">Queued this video${r.cookies ? ' with your session' : ''}.</span> Watch the app's Sources tab.`;
      $('#sendPage').disabled = false; return;
    }
    const [{ result: cap }] = await chrome.scripting.executeScript({ target: { tabId: tab.id }, func: () => ({ url: location.href, title: document.title, html: document.documentElement.outerHTML }) });
    $('#pageMsg').textContent = 'sending…';
    const r = await api(`/api/projects/${pid}/ingest/html`, { method: 'POST', body: JSON.stringify({ url: cap.url, title: cap.title, html: cap.html }) });
    await chrome.storage.local.set({ lastProject: pid });
    const vids = r.video_embeds || [];
    $('#pageMsg').innerHTML = `<span class="ok">Added “${esc(r.title)}” (${r.segments} sections).</span> Findings will be suggested in the app.`
      + (vids.length ? ` <b>This page embeds ${vids.length} video</b> (${esc(vids.map(v => v.replace(/^https?:\/\/(www\.)?/, '').slice(0, 34)).join(', '))}). The notes were free; a video is downloaded and transcribed. <button id="addVid" class="mini">Add the video${vids.length === 1 ? '' : 's'}</button>` : '');
    // 1.6.1 — his lesson's Loom video was dropped without trace by the page capture. The app records the embeds
    // now; adding them is a separate press because it spends, and the SESSION has to travel with it: a private
    // Loom refuses an anonymous download, which is why the cookies of every embed host go too.
    const add = document.getElementById('addVid');
    if (add) add.onclick = async () => {
      add.disabled = true; const note = document.createElement('span');
      $('#pageMsg').appendChild(note); note.textContent = ' collecting sessions…';
      try {
        const hosts = new Set([new URL(cap.url).hostname]);
        vids.forEach(v => { try { hosts.add(new URL(v).hostname); } catch (e) {} });
        let cookies = [];
        for (const h of hosts) {
          const b = h.split('.').slice(-2).join('.');
          for (const dom of new Set([h, b, '.' + b])) { try { cookies = cookies.concat(await chrome.cookies.getAll({ domain: dom })); } catch (e) {} }
        }
        const seen = new Set(); cookies = cookies.filter(c => { const k = c.domain + '|' + c.name + '|' + c.path; if (seen.has(k)) return false; seen.add(k); return true; });
        const q = await api(`/api/projects/${pid}/page-videos`, { method: 'POST', body: JSON.stringify({
          source_id: r.source_id,
          cookies: cookies.map(c => ({ domain: c.domain, name: c.name, value: c.value, path: c.path, secure: c.secure, expirationDate: c.expirationDate })) }) });
        note.innerHTML = q.queued ? ` <span class="ok">queued ${q.queued} — watch the app's Sources tab.</span>` : ` <span class="bad">${esc(q.why || 'nothing to add')}</span>`;
      } catch (e) { note.innerHTML = ` <span class="bad">${esc(e.message)}</span>`; add.disabled = false; }
    };
  } catch (e) { $('#pageMsg').innerHTML = `<span class="bad">${esc(e.message)}</span>`; }
  $('#sendPage').disabled = false;
};
$('#saveSetup').onclick = async () => {
  const appUrl = $('#appUrl').value.trim().replace(/\/$/, ''), token = $('#token').value.trim();
  if (!appUrl || !token) return;
  try {
    const r = await fetch(appUrl + '/api/stats', { headers: { Authorization: 'Bearer ' + token } });
    if (!r.ok) throw new Error(r.status === 401 ? 'wrong password' : 'app answered ' + r.status);
  } catch (e) { $('#setupMsg').textContent = 'Could not reach the app: ' + e.message; return; }
  await chrome.storage.local.set({ appUrl, token }); load();
};
$('#reset').onclick = async () => { await chrome.storage.local.remove(['appUrl', 'token']); $('#setup').style.display = ''; $('#main').style.display = 'none'; };

async function api(path, opts = {}) {
  const r = await fetch(cfg.appUrl + path, { ...opts, headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + cfg.token, ...(opts.headers || {}) } });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || r.statusText);
  return r.json();
}

$('#scan').onclick = async () => {
  $('#scan').disabled = true; $('#scanMsg').textContent = 'scanning…'; $('#result').style.display = 'none';
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  chrome.runtime.onMessage.addListener(onMsg);
  try { await chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ['scanner.js'] }); }
  catch (e) { $('#scanMsg').textContent = 'Cannot scan this page: ' + e.message; $('#scan').disabled = false; }
};

function onMsg(m) {
  if (m.type === 'progress') $('#scanMsg').textContent = `reading lesson pages… ${m.done}/${m.total}`;
  if (m.type === 'result') { chrome.runtime.onMessage.removeListener(onMsg); showResult(m); }
}

async function showResult(m) {
  result = m; $('#scan').disabled = false;
  const withV = m.lessons.filter(l => l.video_urls.length);
  // 1.6.0 — the old message named ONE cause ("are you logged in?") for every empty result, and on the course Kyle
  // reported it was the wrong one: he was logged in, on the course page, and the course simply cannot be listed
  // from a page. A message that guesses is worse than a message that says what it saw.
  const d = m.diagnosis || {};
  $('#scanMsg').textContent = withV.length ? ''
    : d.app_rendered ? `This course keeps one address for every lesson (${d.clickable_lessonish} lesson rows, no lesson links), so it cannot be listed from here. Open a lesson and use “Send this page” instead.`
    : !d.candidates ? 'No lesson links on this page — open the course home page that lists the lessons.'
    : `Found ${d.candidates} lesson page${d.candidates === 1 ? '' : 's'} but no video in any of them. If the videos only appear after you press play, open a lesson and use “Send this page”.`;
  $('#courseTitle').value = m.course.title;
  $('#lessons').innerHTML = m.lessons.map((l, i) => `<div class="les ${l.video_urls.length ? '' : 'nov'}"><input type="checkbox" data-i="${i}" ${l.video_urls.length ? 'checked' : 'disabled'}><div class="t">${esc(l.title)}${l.module ? ` <span class="m">· ${esc(l.module)}</span>` : ''}<div class="m">${l.video_urls.length ? l.video_urls.map(v => v.replace(/^https?:\/\/(www\.)?/, '').slice(0, 60)).join(', ') : 'no video found'}</div></div></div>`).join('');
  $('#summary').textContent = `${withV.length} of ${m.lessons.length} lessons have a video${m.truncated ? ' (first 120 pages only)' : ''}. Session cookies for this site and the video hosts will be sent so the app can download them.`;
  try {
    const ps = await api('/api/projects');
    $('#project').innerHTML = ps.map(p => `<option value="${p.id}">${esc(p.name)}</option>`).join('') || '<option value="">(create a project in the app first)</option>';
  } catch (e) { $('#summary').textContent = 'Could not load projects: ' + e.message; }
  $('#result').style.display = '';
}

$('#send').onclick = async () => {
  if (!result || !$('#project').value) return;
  $('#send').disabled = true; $('#sendMsg').textContent = 'collecting cookies…';
  const picked = [...document.querySelectorAll('#lessons input:checked')].map(cb => result.lessons[+cb.dataset.i]);
  const hosts = new Set([new URL(result.course.url).hostname]);
  picked.forEach(l => l.video_urls.forEach(v => { try { hosts.add(new URL(v).hostname); } catch (e) {} }));
  let cookies = [];
  for (const h of hosts) {
    const base = h.split('.').slice(-2).join('.');
    for (const dom of new Set([h, base, '.' + base])) {
      try { cookies = cookies.concat(await chrome.cookies.getAll({ domain: dom })); } catch (e) {}
    }
  }
  const seen = new Set(); cookies = cookies.filter(c => { const k = c.domain + '|' + c.name + '|' + c.path; if (seen.has(k)) return false; seen.add(k); return true; });
  $('#sendMsg').textContent = `sending ${picked.length} lessons…`;
  try {
    const r = await api(`/api/projects/${$('#project').value}/course-import`, { method: 'POST', body: JSON.stringify({
      course: { title: $('#courseTitle').value, url: result.course.url }, lessons: picked,
      cookies: cookies.map(c => ({ domain: c.domain, name: c.name, value: c.value, path: c.path, secure: c.secure, expirationDate: c.expirationDate })) }) });
    $('#sendMsg').innerHTML = `<span class="ok">Queued ${r.queued} videos.</span> Watch progress in the app's Sources tab.`;
  } catch (e) { $('#sendMsg').innerHTML = `<span class="bad">${esc(e.message)}</span>`; $('#send').disabled = false; }
};

const esc = s => (s ?? '').toString().replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
load();
