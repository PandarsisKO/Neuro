globalThis.state = { project: null, conv: null, chats: [], view: 'chats' };

// ---- theme (light by default; remembered per browser) ----
globalThis.applyTheme = function applyTheme(t) {
  if (t === 'dark') document.documentElement.setAttribute('data-theme', 'dark'); else document.documentElement.removeAttribute('data-theme');
  document.querySelectorAll('.themeBtn').forEach(b => b.textContent = t === 'dark' ? '☀️ Light' : '🌙 Dark');
  try { localStorage.setItem('ns_theme', t); } catch (e) {}
}
globalThis.toggleTheme = function toggleTheme() { applyTheme(document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark'); }
try { applyTheme(localStorage.getItem('ns_theme') || 'light'); } catch (e) { applyTheme('light'); }

// ================= routing =================
globalThis.UI_VERSION = '0.63.88';
globalThis.showVersion = function showVersion(server) {
  // next to every theme toggle: the page version, plus the server version when it differs (0.24.1)
  const t = server && server !== UI_VERSION ? `v${UI_VERSION} · server ${server}` : `v${UI_VERSION}`;
  document.querySelectorAll('.verTag').forEach(e => { e.textContent = t; e.style.color = server && server !== UI_VERSION ? 'var(--warn)' : ''; });
}
showVersion();
globalThis.staleClientVersion = null;
globalThis.showStaleClient = function showStaleClient(server) {
  globalThis.staleClientVersion = server;
  showVersion(server);
  let banner = $('#verBanner');
  if (!banner) {
    banner = document.createElement('div'); banner.className = 'banner'; banner.id = 'verBanner';
    banner.setAttribute('role', 'alert');
    banner.style.cssText = 'position:fixed;left:50%;transform:translateX(-50%);top:8px;z-index:999;max-width:720px;box-shadow:0 4px 16px rgba(0,0,0,.15)';
    banner.innerHTML = 'This page is out of date. Your saved work is safe. Reload the page to continue. <button type="button" id="reloadCurrentUI">Reload page</button>';
    document.body.appendChild(banner);
    $('#reloadCurrentUI').addEventListener('click', () => location.reload());
  }
}
globalThis.uiFetch = async function uiFetch(path, opts = {}) {
  if (staleClientVersion && path !== '/api/version') throw new Error('This page is out of date. Reload it to continue.');
  const headers = new Headers(opts.headers || {});
  headers.set('X-Neurosearch-UI-Version', UI_VERSION);
  const response = await fetch(path, { ...opts, headers });
  const server = response.headers.get('X-Neurosearch-Version');
  if (server && server !== UI_VERSION) {
    showStaleClient(server);
    if (path !== '/api/version') throw new Error('This page is out of date. Reload it to continue.');
  }
  return response;
}
globalThis.checkVersion = async function checkVersion() {
  try {
    const r = await uiFetch('/api/version', { cache: 'no-store' });
    if (!r.ok) return;
    const j = await r.json(); const v = j.version;
    if (!v) return;
    showVersion(v);
    if (j.fake_ai && !$('#fakeBanner')) {
      const f = document.createElement('div'); f.id = 'fakeBanner';
      f.style.cssText = 'position:fixed;left:0;right:0;bottom:0;z-index:98;background:#b45309;color:#fff;text-align:center;padding:6px;font-weight:700;letter-spacing:.02em';
      f.textContent = '⚠ FAKE AI MODE — no real model calls are being made (NEUROSEARCH_FAKE_AI=1). Answers, findings and plans are stand-ins.';
      document.body.appendChild(f);
    }
    if (v !== UI_VERSION) showStaleClient(v);
  } catch (e) { /* Offline is not a version verdict. Existing mismatch remains visible. */ }
}
checkVersion();
setInterval(() => { if (!document.hidden) checkVersion(); }, 30000);
window.addEventListener('focus', checkVersion);
document.addEventListener('visibilitychange', () => { if (!document.hidden) checkVersion(); });
globalThis.route = function route() {
  const h = location.hash.slice(1).split('/');
  if (h[0] === 'p' && h[1]) openProject(h[1], h[2] || 'chats', h[3] || null);
  else goHome();
}
window.addEventListener('hashchange', route);
globalThis.setHash = function setHash(view, conv) { const h = `#p/${state.project.id}/${view}` + (conv ? '/' + conv : ''); if (location.hash !== h) history.replaceState(null, '', h); }



export const moduleName = "state";
