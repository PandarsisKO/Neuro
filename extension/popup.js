const $ = s => document.querySelector(s);
let cfg = {}, result = null;

let WANTED = null;   // the app's waiting capture request for the current tab, if any

function authMessage(status) {
  if (status !== 401 && status !== 403) return null;
  return `Neuro Search rejected the saved app password (HTTP ${status}). Open Settings → Change app address / password and save it again.`;
}

function canon(u) {
  try { const x = new URL(u); x.hash = ''; x.search = ''; return (x.origin + x.pathname).replace(/^https?:\/\/(www\.|old\.|new\.)?/, 'https://').replace(/\/$/, ''); } catch (e) { return u; }
}

async function load() {
  cfg = await chrome.storage.local.get(['appUrl', 'token', 'lastProject']);
  if (cfg.appUrl && cfg.token) {
    $('#setup').style.display = 'none'; $('#main').style.display = ''; $('#cfg').textContent = cfg.appUrl;
    const savedAuthError = (await chrome.storage.local.get(['authError'])).authError;
    if (savedAuthError) $('#pageMsg').innerHTML = `<span class="bad">${esc(savedAuthError)}</span>`;
    try {
      const ps = await api('/api/projects');
      $('#pageProject').innerHTML = ps.map(p => `<option value="${p.id}" ${p.id === cfg.lastProject ? 'selected' : ''}>${esc(p.name)}</option>`).join('') || '<option value="">(create a project in the app first)</option>';
      await chrome.storage.local.remove(['authError', 'authErrorAt']);
      // The saved refusal was just recovered from.  Leaving its old copy visible implies the password is still
      // rejected even though the authenticated projects request succeeded.
      if (savedAuthError) $('#pageMsg').textContent = '';
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
    } catch (e) {
      // Offline/background polling is normally quiet, but an explicit auth refusal is actionable:
      // otherwise an expired token looks exactly like an app with no pending captures.
      if (e.authMessage) $('#pageMsg').textContent = e.authMessage;
    }
    refreshScan();
    refreshCapture();
  }
}

// ---- B1: the capture contract — produced in the browser, normalized only by the server ----
// The producers (redditCapture / pageCapture) live in thread-capture.js so the background worker can run them too.
const { redditCapture, pageCapture } = self.NSThreadCapture;

// A shortfall against Reddit's comment count is usually deleted/removed comments (still counted); only a large one, or
// unexpanded branches, means the page really did not load everything. Never shown in red: a capture is a success.
function partialNote(cap) {
  if (!cap || cap.captured == null || cap.expected == null) return '';
  const missing = Math.max(0, cap.expected - cap.captured), more = cap.load_more_remaining || 0;
  if (!more && missing <= Math.max(5, Math.floor(cap.expected * 0.1))) return missing ? ` <span class="muted">(Reddit counts ${cap.expected}; the difference is usually deleted comments.)</span>` : '';
  return ` <span class="warn">Partial: ${cap.captured} of ~${cap.expected} comments were on the page${more ? ` (${more} “more replies” not expanded)` : ''}. Expand them and capture again to add the rest.</span>`;
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
// ---- Send screenshot: mirrors the scan pattern above — the popup only starts the capture and renders whatever
// the background record (`capture:<tabId>`) says; the background owns the operation so it survives popup close.
let CAPTURE = null;
// 'captured' (repair round 3, gap #C): the brief durable-metadata-persisted-before-the-blob-write state --
// active exactly like 'capturing'/'uploading', so the button stays disabled and no stray click can start a
// second capture while this tab's record passes through it.
const CAPTURE_ACTIVE_UI = new Set(['capturing', 'captured', 'uploading']);
const CAPTURE_MODE_WORDS = { full_page: 'the full page', visible_only: 'the visible area', partial_page: 'part of the page' };
const CAPTURE_REASON_WORDS = { ceiling_pixels: 'the page was very tall — captured as far as the size limit allowed',
                                ceiling_folds: 'the page was very tall — captured as far as the fold/tile limit allowed',
                                ceiling_time: 'the page was very tall — captured as far as time allowed',
                                ceiling_axis: 'the page was very tall or narrow — captured as far as it could be assembled without corrupting the image',
                                fallback_after_error: 'the full page could not be assembled, so only the visible area was captured' };
// Failure-state copy (repair round): the tagged errors background.js can raise, in the user's own words — never
// DOM/mechanism jargon. `error` on a failed/upload_failed record is a message string; these are matched by
// substring since background.js's error messages ARE these sentences (see verifyTabIdentity in background.js).
const CAPTURE_FAILURE_WORDS = [
  [/no longer the active tab/i, 'Switch back to that tab and press Send screenshot again — it needs to be the tab you\'re looking at.'],
  [/navigated to a different (page|site)|different (page|site) mid-capture/i, 'The page navigated away while it was being captured, so nothing was sent.'],
  [/navigated away from a capturable page/i, 'The tab left the page before the capture could finish.'],
  [/browser or extension restarted/i, null],   // uses c.error verbatim — already in plain language
];

function screenshotFailureMessage(c) {
  for (const [re, words] of CAPTURE_FAILURE_WORDS) if (re.test(c.error || '')) return words || c.error;
  return c.error || 'could not capture this page';
}

async function refreshCapture() {
  if (!TAB) TAB = await currentTab();
  const r = await bg({ type: 'capture-get', tabId: TAB.id });
  CAPTURE = r.capture || null;
  renderCapture();
}

function renderCapture() {
  const c = CAPTURE;
  const sameTab = c && TAB && c.tab_id === TAB.id;
  $('#sendScreenshot').disabled = !!(c && sameTab && CAPTURE_ACTIVE_UI.has(c.status));
  $('#retryScreenshot').style.display = c && sameTab && c.status === 'upload_failed' ? '' : 'none';
  if (!c || !sameTab) { return; }
  if (c.status === 'capturing') { $('#screenshotMsg').textContent = c.fold ? `capturing… (tile ${c.fold})` : 'capturing…'; return; }
  if (c.status === 'captured') { $('#screenshotMsg').textContent = 'saving…'; return; }
  if (c.status === 'uploading') { $('#screenshotMsg').textContent = 'sending…'; return; }
  if (c.status === 'upload_failed') {
    $('#screenshotMsg').innerHTML = `<span class="bad">Could not send: ${esc(c.error || 'the app could not be reached')}.</span> <span class="muted">The captured image is kept — press Retry send.</span>`;
    return;
  }
  if (c.status === 'failed') { $('#screenshotMsg').innerHTML = `<span class="bad">${esc(screenshotFailureMessage(c))}</span>`; return; }
  if (c.status === 'done') {
    const res = c.result || {};
    const modeWord = CAPTURE_MODE_WORDS[res.mode] || 'the page';
    let msg = `<span class="ok">Captured ${modeWord} — sent to Neuro Search.</span>`;
    if (res.partial_reason) msg += ` <span class="warn">${esc(CAPTURE_REASON_WORDS[res.partial_reason] || 'stopped early')}.</span>`;
    else if (res.mode === 'visible_only') msg += ' <span class="muted">Only the visible area could be captured reliably for this page.</span>';
    msg += ' Findings will be suggested in the app.';
    $('#screenshotMsg').innerHTML = msg;
    return;
  }
}

chrome.storage.onChanged.addListener((changes, area) => {
  if (area !== 'local' || !TAB) return;
  if (changes[`capture:${TAB.id}`]) { CAPTURE = changes[`capture:${TAB.id}`].newValue || null; renderCapture(); }
});

$('#sendScreenshot').onclick = async () => {
  const pid = $('#pageProject').value; if (!pid) return;
  $('#sendScreenshot').disabled = true; $('#screenshotMsg').textContent = 'capturing…';
  TAB = await currentTab();
  const note = ($('#screenshotNote').value || '').trim() || null;
  const r = await bg({ type: 'capture-start', tabId: TAB.id, projectId: pid, note });
  if (r.error) { $('#screenshotMsg').innerHTML = `<span class="bad">${esc(r.error)}</span>`; $('#sendScreenshot').disabled = false; return; }
  await chrome.storage.local.set({ lastProject: pid });
  $('#screenshotNote').value = '';
  CAPTURE = r.capture; renderCapture();
};

// Retry send: resubmits the SAME already-captured bytes under the SAME capture_id (see background.js's
// retryCapture) — never recaptures the page, so it stays safe to press even more than once.
$('#retryScreenshot').onclick = async () => {
  if (!TAB) return;
  $('#retryScreenshot').disabled = true; $('#screenshotMsg').textContent = 'sending…';
  const r = await bg({ type: 'capture-retry', tabId: TAB.id });
  $('#retryScreenshot').disabled = false;
  if (r.error) { $('#screenshotMsg').innerHTML = `<span class="bad">${esc(r.error)}</span>`; return; }
  CAPTURE = r.capture; renderCapture();
};

// how long Save waits for the app to answer before giving up and saying so, rather than sitting there looking
// frozen forever. Chosen once, 2026-09-17: a hung server (the parent process surviving a crash and still
// holding the port -- see restart.command's own comment) makes fetch() hang far longer than any reasonable
// button-press patience, with no error, no timeout, and (before this fix) no way to back out of this screen at
// all -- confirmed live as a real defect, not a hypothetical one.
const SETUP_SAVE_TIMEOUT_MS = 8000;

$('#saveSetup').onclick = async () => {
  const appUrl = $('#appUrl').value.trim().replace(/\/$/, ''), token = $('#token').value.trim();
  if (!appUrl || !token) return;
  $('#saveSetup').disabled = true; $('#setupMsg').textContent = 'Checking…';
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), SETUP_SAVE_TIMEOUT_MS);
  try {
    const r = await fetch(appUrl + '/api/stats', { headers: { Authorization: 'Bearer ' + token }, signal: controller.signal });
    if (!r.ok) throw new Error(r.status === 401 ? 'wrong password' : 'app answered ' + r.status);
  } catch (e) {
    $('#setupMsg').textContent = e.name === 'AbortError'
      ? "The app didn't answer within a few seconds — it may be down or the port may be stuck (try restart.command), or the address may be wrong."
      : 'Could not reach the app: ' + e.message;
    return;
  } finally {
    clearTimeout(timer); $('#saveSetup').disabled = false;
  }
  await chrome.storage.local.set({ appUrl, token }); load();
};
// Change app address / password: show the setup form pre-filled with the CURRENT values, without touching
// storage yet -- the old config stays live and Cancel can always get back to it. Storage is only overwritten on
// a successful Save (above). Before this, reset wiped storage immediately, so a Save that then failed (or hung
// -- see SETUP_SAVE_TIMEOUT_MS above) left no way back into the app at all; confirmed live as a real defect.
$('#reset').onclick = () => {
  $('#appUrl').value = cfg.appUrl || ''; $('#token').value = cfg.token || ''; $('#setupMsg').textContent = '';
  $('#cancelSetup').style.display = cfg.appUrl && cfg.token ? '' : 'none';
  $('#setup').style.display = ''; $('#main').style.display = 'none';
};
$('#cancelSetup').onclick = () => { $('#setupMsg').textContent = ''; $('#setup').style.display = 'none'; $('#main').style.display = ''; };

async function api(path, opts = {}) {
  const r = await fetch(cfg.appUrl + path, { ...opts, headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + cfg.token, ...(opts.headers || {}) } });
  if (!r.ok) {
    const e = new Error(authMessage(r.status) || (await r.json().catch(() => ({}))).error || r.statusText);
    e.status = r.status;
    e.authMessage = authMessage(r.status);
    throw e;
  }
  return r.json();
}

// ---- 1.7.0 (mission CS): the popup is a VIEW of a scan, not its owner. The background keeps the durable record
// (`scan:<tabId>` in chrome.storage.local) and the course tab does the traversal; this popup can be closed and
// reopened at any point and shows whatever is true now. Words here are the user's words — lessons, videos,
// "needs attention" — never strategies, DOM mechanics or cookies (progressive disclosure: the detail sits under
// a fold, and cookies are collected only at the moment of the explicit import press, as before).
let TAB = null, SCAN = null, SUMMARY = null;

async function currentTab() { const [tab] = await chrome.tabs.query({ active: true, currentWindow: true }); return tab; }
const bg = msg => new Promise(res => chrome.runtime.sendMessage(msg, r => { void chrome.runtime.lastError; res(r || {}); }));

async function refreshScan() {
  if (!TAB) TAB = await currentTab();
  const r = await bg({ type: 'scan-get', tabId: TAB.id });
  SCAN = r.scan || null; SUMMARY = r.summary || null;
  renderScan();
}

const ACTIVE = new Set(['finding', 'scanning']);
const plural = (n, w) => `${n} ${w}${n === 1 ? '' : 's'}`;
const OUTCOME_WORDS = { video_found: 'video ready', multiple_videos: 'several videos', document_found: 'document ready', no_video: 'no video or document on this lesson', needs_user_play: 'video appears only after you press play',
                        blocked: 'not readable with your access', scan_failed: 'could not be read', not_scanned: 'not reached' };
const DOC_WORDS = { gdrive: 'Google Drive file', gdocs: 'Google Doc', gsheets: 'Google Sheet', gslides: 'Google Slides', dropbox: 'Dropbox file', pdf: 'PDF', docx: 'Word document', doc: 'Word document', xlsx: 'spreadsheet', xls: 'spreadsheet', csv: 'spreadsheet', pptx: 'slides', epub: 'e-book', txt: 'text file', md: 'text file', rtf: 'document' };
const docWords = atts => { const n = {}; (atts || []).forEach(a => { const w = DOC_WORDS[a.kind] || 'document'; n[w] = (n[w] || 0) + 1; }); return Object.entries(n).map(([w, k]) => k > 1 ? `${k} ${w}s` : w).join(', '); };
const REASON_WORDS = { tab_closed: 'the tab was closed', origin_changed: 'the tab left the course site', navigated: 'the page was reloaded or navigated away', runner_silent: 'the page stopped responding',
                       browser_restarted: 'Chrome was restarted', cancelled: 'you stopped it', inject_failed: 'the page could not be read', runner_error: 'the scan hit an error' };

function renderScan() {
  const s = SCAN, sum = SUMMARY;
  const sameTab = s && TAB && s.tab_id === TAB.id;
  $('#scan').disabled = !!(s && sameTab && ACTIVE.has(s.status));
  $('#cancelScan').style.display = s && sameTab && ACTIVE.has(s.status) ? '' : 'none';
  if (!s || !sameTab) { $('#scanMsg').textContent = ''; $('#result').style.display = 'none'; return; }
  const lessonWord = n => plural(n, 'lesson');
  if (s.status === 'finding') { $('#scanMsg').textContent = 'Finding lessons…'; $('#result').style.display = 'none'; return; }
  if (s.status === 'scanning') {
    const last = s.lessons[s.lessons.length - 1];
    const line1 = s.expected ? `${lessonWord(s.expected)} found` : 'Lessons found';
    const line2 = last ? `Reading ${Math.min(s.lessons.length + 1, s.expected || s.lessons.length + 1)} of ${s.expected || '?'}${last.title ? `: ${last.title}` : ''}` : 'Reading the first lesson…';
    $('#scanMsg').innerHTML = `${esc(line1)}<br>${esc(line2)}<br>${esc(plural(sum.video_found + sum.multiple_videos, 'video'))}${sum.document_found ? esc(` and ${plural(sum.document_found, 'document')}`) : ''} found so far`;
    $('#result').style.display = 'none'; return;
  }
  // finished, in one of: done · partial · cancelled · interrupted · failed
  const d = s.diagnosis || {};
  let head;
  if (s.status === 'failed') head = `<span class="bad">The scan could not run${s.errors && s.errors[0] ? ` — ${esc(s.errors[0])}` : ''}.</span>`;
  else if (!s.lessons.length) {
    // 1.6.0's rule, kept: name what was seen, never guess "are you logged in?"
    head = d.strategy === 'none' && !d.links && !d.controls && !d.modules ? 'No lessons found on this page — open the course home page that lists the lessons.'
         : d.strategy === 'interactive' ? `Found ${plural(d.controls || d.modules, d.controls ? 'lesson' : 'module')} but could not open any of them.`
         : `Found ${plural(d.links, 'lesson page')} but no video in any of them. If the videos only appear after you press play, open a lesson and use “Send this page”.`;
  } else {
    const total = Math.max(s.expected || 0, s.lessons.length);
    head = `<b>${sum.ready} of ${lessonWord(total)} ready</b>`;
    if (sum.attention) head += `<br>${sum.attention} need${sum.attention === 1 ? 's' : ''} attention`;
    if (sum.unread) head += `<br>${sum.unread} could not be read`;
    if (s.status === 'partial' && s.reason && s.reason !== 'cancelled') head += `<br><span class="warn">Stopped early: ${esc(REASON_WORDS[s.reason] || s.reason)}. What was read is kept.</span>`;
    if (s.status === 'cancelled') head += `<br><span class="muted">Stopped by you. What was read is kept.</span>`;
    if (s.status === 'interrupted') head += `<br><span class="warn">Interrupted: ${esc(REASON_WORDS[s.reason] || s.reason)}.</span>`;
  }
  $('#scanMsg').innerHTML = head;
  if (!s.lessons.length) { $('#result').style.display = 'none'; return; }
  $('#courseTitle').value = (s.course && s.course.title) || s.title || '';
  const dupOf = {}; Object.entries(s.duplicates || {}).forEach(([k, idxs]) => idxs.forEach(i => { dupOf[i] = idxs.length; }));
  $('#lessons').innerHTML = s.lessons.map((l, i) => {
    const ok = l.outcome === 'video_found' || l.outcome === 'multiple_videos' || l.outcome === 'document_found';
    const docs = docWords(l.attachments);
    let what = ok ? (l.media || []).map(m => m.provider === 'direct' ? 'video file' : m.provider).join(', ') : OUTCOME_WORDS[l.outcome] || l.outcome;
    if (docs) what = what && l.outcome !== 'document_found' ? `${what} + ${docs}` : docs;
    return `<div class="les ${ok ? '' : 'nov'}"><input type="checkbox" data-i="${i}" ${ok ? 'checked' : 'disabled'}><div class="t">${esc(l.title)}${l.module && l.module !== l.title ? ` <span class="m">· ${esc(l.module)}</span>` : ''}<div class="m">${esc(what)}${dupOf[i] ? ` · same video as ${dupOf[i] - 1} other lesson${dupOf[i] > 2 ? 's' : ''}` : ''}${l.detail && !ok ? ` — ${esc(l.detail)}` : ''}</div></div></div>`;
  }).join('');
  const dupCount = Object.keys(s.duplicates || {}).length;
  const nDocs = s.lessons.reduce((n, l) => n + (l.attachments || []).length, 0);
  $('#summary').textContent = `${sum.video_found + sum.multiple_videos} of ${s.lessons.length} lessons have a video${nDocs ? `, ${plural(nDocs, 'linked document')} (PDFs, worksheets)` : ''}${dupCount ? ` (${plural(dupCount, 'video')} shared between lessons — downloaded once)` : ''}. Your session for this site and the video hosts is sent only when you press Send; documents are fetched by the app without it.`;
  $('#result').style.display = '';
  loadProjectsInto('#project');
}

async function loadProjectsInto(sel) {
  try {
    const ps = await api('/api/projects');
    $(sel).innerHTML = ps.map(p => `<option value="${p.id}" ${p.id === cfg.lastProject ? 'selected' : ''}>${esc(p.name)}</option>`).join('') || '<option value="">(create a project in the app first)</option>';
  } catch (e) { $('#summary').textContent = 'Could not load projects: ' + e.message; }
}

$('#scan').onclick = async () => {
  $('#scan').disabled = true; $('#scanMsg').textContent = 'Finding lessons…'; $('#result').style.display = 'none';
  TAB = await currentTab();
  const r = await bg({ type: 'scan-start', tabId: TAB.id });
  if (r.error) { $('#scanMsg').innerHTML = `<span class="bad">${esc(r.error)}</span>`; $('#scan').disabled = false; }
  await refreshScan();
};
$('#cancelScan').onclick = async () => { if (!TAB) return; $('#cancelScan').disabled = true; await bg({ type: 'scan-cancel', tabId: TAB.id }); $('#cancelScan').disabled = false; await refreshScan(); };

chrome.storage.onChanged.addListener((changes, area) => {
  if (area !== 'local' || !TAB) return;
  if (changes[`scan:${TAB.id}`]) { SCAN = changes[`scan:${TAB.id}`].newValue || null; bg({ type: 'scan-get', tabId: TAB.id }).then(r => { SUMMARY = r.summary; renderScan(); }); }
});

$('#send').onclick = async () => {
  if (!SCAN || !$('#project').value) return;
  $('#send').disabled = true; $('#sendMsg').textContent = 'collecting your session…';
  const picked = [...document.querySelectorAll('#lessons input:checked')].map(cb => SCAN.lessons[+cb.dataset.i]);
  // cookies: only now, only for the course host and the hosts of the videos actually picked
  const hosts = new Set([new URL(SCAN.url).hostname]);
  picked.forEach(l => (l.video_urls || []).forEach(v => { try { hosts.add(new URL(v).hostname); } catch (e) {} }));
  let cookies = [];
  for (const h of hosts) {
    const base = h.split('.').slice(-2).join('.');
    for (const dom of new Set([h, base, '.' + base])) { try { cookies = cookies.concat(await chrome.cookies.getAll({ domain: dom })); } catch (e) {} }
  }
  const seen = new Set(); cookies = cookies.filter(c => { const k = c.domain + '|' + c.name + '|' + c.path; if (seen.has(k)) return false; seen.add(k); return true; });
  $('#sendMsg').textContent = `sending ${plural(picked.length, 'lesson')}…`;
  try {
    const r = await api(`/api/projects/${$('#project').value}/course-import`, { method: 'POST', body: JSON.stringify({
      course: { title: $('#courseTitle').value, url: SCAN.url },
      lessons: picked.map(l => ({ title: l.title, module: l.module, page_url: l.page_url, video_urls: l.video_urls, outcome: l.outcome, ordinal: l.ordinal, attachments: l.attachments || [] })),
      cookies: cookies.map(c => ({ domain: c.domain, name: c.name, value: c.value, path: c.path, secure: c.secure, expirationDate: c.expirationDate })) }) });
    await chrome.storage.local.set({ lastProject: $('#project').value });
    const bits = [`<span class="ok">Queued ${plural(r.queued, 'video')}${r.documents ? ` and ${plural(r.documents, 'document')}` : ''}.</span>`];
    if (r.already_present && r.already_present.length) bits.push(`${plural(r.already_present.length, 'item')} already in your library — not downloaded again.`);
    if (r.shared && r.shared.length) bits.push(`${plural(r.shared.length, 'video')} shared by more than one lesson — downloaded once.`);
    bits.push('Watch progress in the app\'s Sources tab.');
    $('#sendMsg').innerHTML = bits.join(' ');
  } catch (e) { $('#sendMsg').innerHTML = `<span class="bad">${esc(e.message)}</span>`; $('#send').disabled = false; }
};

const esc = s => (s ?? '').toString().replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
load();
