// Executes the shipped extension auth paths against controlled HTTP outcomes.
// This is intentionally a narrow Chrome mock: it proves the popup turns an
// explicit 401/403 into actionable copy, and the background persists that
// refusal for the popup while ordinary server failures remain quiet.

import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import vm from 'node:vm';

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.join(here, '..', '..');
const popup = readFileSync(path.join(root, 'extension', 'popup.js'), 'utf8');
const background = readFileSync(path.join(root, 'extension', 'background.js'), 'utf8');
const command = process.argv[2];

function slice(source, startMarker, endMarker, label) {
  const start = source.indexOf(startMarker);
  const end = source.indexOf(endMarker, start);
  if (start === -1 || end === -1) {
    console.error(`extension auth harness could not extract ${label}; update this test with the shipped source`);
    process.exit(3);
  }
  return source.slice(start, end).trim();
}

function response(status) {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: `HTTP ${status}`,
    json: async () => ({ error: `server ${status}` }),
  };
}

async function popupApi(status) {
  const authSrc = slice(popup, 'function authMessage(status)', 'function canon(', 'popup authMessage');
  const apiSrc = slice(popup, 'async function api(path, opts = {})', '// ---- 1.7.0', 'popup api');
  const sandbox = { cfg: { appUrl: 'http://app.test', token: 'wrong' }, fetch: async () => response(status), Error, Promise };
  vm.createContext(sandbox);
  vm.runInContext(`${authSrc}\n${apiSrc}\nglobalThis.__api = api;`, sandbox);
  try {
    await sandbox.__api('/api/projects');
    return { threw: false };
  } catch (e) {
    return { threw: true, status: e.status, authMessage: e.authMessage || null, message: e.message };
  }
}

async function popupRecovery() {
  const loadSrc = slice(popup, 'async function load()', '// ---- B1:', 'popup load');
  const elements = Object.fromEntries(['setup', 'main', 'cfg', 'pageMsg', 'pageProject', 'wanted', 'wantedWhy', 'queue'].map(id => [id, {
    style: {}, textContent: '', innerHTML: '', value: '',
  }]));
  const store = { appUrl: 'http://app.test', token: 'recovered', lastProject: 'p1', authError: 'saved refusal', authErrorAt: 1 };
  const chrome = { storage: { local: {
    get: async keys => Array.isArray(keys) ? Object.fromEntries(keys.map(k => [k, store[k]])) : { ...store },
    remove: async keys => { for (const key of keys) delete store[key]; },
  } }, runtime: { getManifest: () => ({ version: 'test' }), sendMessage: (_msg, callback) => callback && callback(), lastError: null },
  tabs: { query: async () => [{ id: 7, url: 'https://course.test/page' }] } };
  const sandbox = {
    cfg: {}, WANTED: null, chrome, Promise, JSON, URL,
    $: selector => elements[selector.slice(1)], esc: value => String(value),
    api: async path => path === '/api/projects' ? [{ id: 'p1', name: 'Project one' }] : path === '/api/capture/pending' ? { items: [] } : {},
    refreshScan: async () => {}, refreshCapture: async () => {},
  };
  vm.createContext(sandbox);
  vm.runInContext(`${loadSrc}\nglobalThis.__load = load;`, sandbox);
  await sandbox.__load();
  return { storedAuthError: store.authError || null, pageMessage: elements.pageMsg.textContent };
}

async function backgroundPath(status, form = false) {
  const cfgSrc = slice(background, 'async function cfg()', 'async function api(path, opts = {})', 'background cfg');
  const apiSrc = slice(background, 'async function api(path, opts = {})', 'function canon(', 'background api');
  const calls = [];
  const store = { appUrl: 'http://app.test', token: 'wrong' };
  const chrome = { storage: { local: {
    get: async keys => {
      if (Array.isArray(keys)) return Object.fromEntries(keys.map(k => [k, store[k]]));
      return { ...store };
    },
    set: async value => { calls.push(value); Object.assign(store, value); },
  } } };
  const sandbox = { chrome, fetch: async () => response(status), Error, Promise, JSON, Date };
  vm.createContext(sandbox);
  vm.runInContext(`${cfgSrc}\n${apiSrc}\nglobalThis.__api = ${form ? 'apiForm' : 'api'};`, sandbox);
  try {
    await sandbox.__api('/api/capture/pending', form ? {} : {});
    return { threw: false, writes: calls };
  } catch (e) {
    return { threw: true, status: e.status, auth: !!e.auth, message: e.message, writes: calls };
  }
}

async function backgroundPoll(status) {
  const cfgSrc = slice(background, 'async function cfg()', 'async function api(path, opts = {})', 'background cfg');
  const apiSrc = slice(background, 'async function api(path, opts = {})', 'function canon(', 'background api');
  const refreshSrc = slice(background, 'async function refreshPending()', 'async function paintAll(', 'refreshPending');
  const writes = [];
  const store = { appUrl: 'http://app.test', token: 'wrong' };
  const chrome = { storage: { local: {
    get: async keys => Array.isArray(keys) ? Object.fromEntries(keys.map(k => [k, store[k]])) : { ...store },
    set: async value => { writes.push(value); Object.assign(store, value); },
  } } };
  const sandbox = { chrome, fetch: async () => response(status), Error, Promise, JSON, Date, VERSION: 'test', paintAll: async () => {} };
  vm.createContext(sandbox);
  vm.runInContext(`${cfgSrc}\n${apiSrc}\n${refreshSrc}\nglobalThis.__refresh = refreshPending;`, sandbox);
  await sandbox.__refresh();
  return { writes };
}

let result;
switch (command) {
  case 'popup-401': result = await popupApi(401); break;
  case 'popup-403': result = await popupApi(403); break;
  case 'popup-500': result = await popupApi(500); break;
  case 'popup-recovery': result = await popupRecovery(); break;
  case 'background-401': result = await backgroundPath(401); break;
  case 'form-403': result = await backgroundPath(403, true); break;
  case 'poll-401': result = await backgroundPoll(401); break;
  case 'poll-500': result = await backgroundPoll(500); break;
  default:
    console.error(`unknown command: ${command}`);
    process.exit(2);
}
console.log(JSON.stringify(result));
