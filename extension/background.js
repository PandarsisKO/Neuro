// Neuro Search extension — background (MV3 service worker).
// Two small jobs, both against the user's OWN Neuro Search server and nothing else:
//   1. a heartbeat every few minutes so the app can say "extension ready / last seen N min ago / not detected";
//   2. the list of pages the app is waiting for the browser to capture, so the toolbar badge lights on such a tab
//      ("Neuro Search wants this page"). Nothing is captured without the user pressing the button in the popup.
const ALARM = 'neurosearch-heartbeat';
const VERSION = chrome.runtime.getManifest().version;

async function cfg() { return chrome.storage.local.get(['appUrl', 'token']); }

async function api(path, opts = {}) {
  const c = await cfg();
  if (!c.appUrl || !c.token) return null;
  const r = await fetch(c.appUrl + path, { ...opts, headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + c.token, ...(opts.headers || {}) } });
  if (!r.ok) throw new Error('app answered ' + r.status);
  return r.json();
}

function canon(u) {
  try { const x = new URL(u); x.hash = ''; x.search = ''; return (x.origin + x.pathname).replace(/^https?:\/\/(www\.|old\.|new\.)?/, 'https://').replace(/\/$/, ''); } catch (e) { return u; }
}

async function refreshPending() {
  try {
    await api('/api/extension/heartbeat', { method: 'POST', body: JSON.stringify({ version: VERSION }) });
    const p = await api('/api/capture/pending');
    const items = (p && p.items) || [];
    await chrome.storage.local.set({ pending: items, pendingAt: Date.now() });
    await paintAll(items);
  } catch (e) { /* the app is unreachable: keep the last list, say nothing */ }
}

async function paintAll(items) {
  const tabs = await chrome.tabs.query({});
  for (const t of tabs) await paint(t, items);
}

async function paint(tab, items) {
  if (!tab || !tab.id || !tab.url) return;
  const list = items || (await chrome.storage.local.get('pending')).pending || [];
  const want = canon(tab.url);
  const hit = list.find(i => canon(i.canonical_url || i.url || '') === want);
  try {
    if (hit) {
      await chrome.action.setBadgeText({ tabId: tab.id, text: '●' });
      await chrome.action.setBadgeBackgroundColor({ tabId: tab.id, color: '#2f5bea' });
      await chrome.action.setTitle({ tabId: tab.id, title: `Neuro Search wants this page — ${hit.project_name || 'project'}` });
    } else if (list.length) {
      await chrome.action.setBadgeText({ tabId: tab.id, text: String(list.length) });
      await chrome.action.setBadgeBackgroundColor({ tabId: tab.id, color: '#8a94a6' });
      await chrome.action.setTitle({ tabId: tab.id, title: `Neuro Search — ${list.length} page${list.length === 1 ? '' : 's'} waiting for your browser` });
    } else {
      await chrome.action.setBadgeText({ tabId: tab.id, text: '' });
      await chrome.action.setTitle({ tabId: tab.id, title: 'Neuro Search' });
    }
  } catch (e) { /* tab vanished */ }
}

chrome.runtime.onInstalled.addListener(() => { chrome.alarms.create(ALARM, { periodInMinutes: 5 }); refreshPending(); });
chrome.runtime.onStartup.addListener(() => { chrome.alarms.create(ALARM, { periodInMinutes: 5 }); refreshPending(); });
chrome.alarms.onAlarm.addListener(a => { if (a.name === ALARM) refreshPending(); });
chrome.tabs.onUpdated.addListener((tabId, info, tab) => { if (info.status === 'complete' || info.url) paint(tab); });
chrome.tabs.onActivated.addListener(async ({ tabId }) => { try { paint(await chrome.tabs.get(tabId)); } catch (e) {} });
chrome.runtime.onMessage.addListener((msg, sender, reply) => {
  if (msg && msg.type === 'refresh-pending') { refreshPending().then(() => reply({ ok: true })); return true; }
});
