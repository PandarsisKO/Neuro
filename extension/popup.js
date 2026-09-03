const $ = s => document.querySelector(s);
let cfg = {}, result = null;

async function load() {
  cfg = await chrome.storage.local.get(['appUrl', 'token']);
  if (cfg.appUrl && cfg.token) { $('#setup').style.display = 'none'; $('#main').style.display = ''; $('#cfg').textContent = cfg.appUrl; }
}
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
  $('#scanMsg').textContent = withV.length ? '' : 'No videos found — are you on the course home page, and logged in?';
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
