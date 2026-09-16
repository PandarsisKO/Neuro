// Neuro Search — send-screenshot durable blob retention (extension 1.9.0, repair round, docs/SEND-SCREENSHOT-2026-09-16.md).
//
// Service-worker-only (never page-injected via chrome.scripting.executeScript, unlike capture-lib.js) — IndexedDB
// in a service worker is a first-class API; there is no reason to route it through the page's isolated world.
// Blobs are keyed directly by capture_id (not a separately generated key) since capture_id is already the
// extension's own stable identity for "this press of Send screenshot" end to end.
//
// Durability ordering (see background.js's runCapture/uploadCapture): pixels are captured, put() here BEFORE the
// record's status becomes 'uploading', and only deleted after a successful upload. A failed upload leaves the
// blob in place so capture-retry can resubmit the SAME bytes under the SAME capture_id without recapturing.
//
// Retention is bounded (product decision, repair round 2): TTL 2 hours, max 5 retained blobs, max 200MB combined,
// oldest-evicted-first. pruneExpired's POLICY (what to keep/evict, given a list of {captureId, storedAt, bytes})
// is the pure function nsBlobRetentionPlan below — testable under plain node/jsdom without a real IndexedDB, and
// exposed on NSCaptureBlobStore exactly like capture-lib.js exposes NSCaptureLib.

const NS_BLOB_DB_NAME = 'ns-capture-blobs';
const NS_BLOB_STORE = 'blobs';
const NS_BLOB_TTL_MS = 2 * 60 * 60 * 1000;      // 2 hours
const NS_BLOB_MAX_COUNT = 5;
const NS_BLOB_MAX_BYTES = 200 * 1024 * 1024;    // 200MB combined

// entries: [{captureId, storedAt, bytes}]. Returns { keep: [...captureId], evict: [...captureId] }.
// Expired-by-TTL entries are evicted regardless of count/size bounds; among what remains, oldest-stored goes
// first until BOTH the count and the combined-byte bound are satisfied.
function nsBlobRetentionPlan(entries, nowMs, policy) {
  const ttlMs = policy.ttlMs, maxCount = policy.maxCount, maxBytes = policy.maxBytes;
  const expired = entries.filter(e => nowMs - e.storedAt > ttlMs);
  const notExpired = entries.filter(e => nowMs - e.storedAt <= ttlMs);
  const sorted = notExpired.slice().sort((a, b) => a.storedAt - b.storedAt);   // oldest first
  const evict = expired.map(e => e.captureId);
  let count = sorted.length;
  let bytes = sorted.reduce((s, e) => s + (e.bytes || 0), 0);
  let i = 0;
  while (i < sorted.length && (count > maxCount || bytes > maxBytes)) {
    evict.push(sorted[i].captureId);
    bytes -= sorted[i].bytes || 0;
    count -= 1;
    i += 1;
  }
  const evictSet = new Set(evict);
  const keep = entries.filter(e => !evictSet.has(e.captureId)).map(e => e.captureId);
  return { keep, evict };
}

(function (root) {
  function openDb() {
    return new Promise((resolve, reject) => {
      const req = indexedDB.open(NS_BLOB_DB_NAME, 1);
      req.onupgradeneeded = () => {
        const db = req.result;
        if (!db.objectStoreNames.contains(NS_BLOB_STORE)) db.createObjectStore(NS_BLOB_STORE, { keyPath: 'captureId' });
      };
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
  }

  async function put(captureId, blob) {
    const db = await openDb();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(NS_BLOB_STORE, 'readwrite');
      tx.objectStore(NS_BLOB_STORE).put({ captureId, blob, bytes: blob.size, storedAt: Date.now() });
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
    });
  }

  async function get(captureId) {
    const db = await openDb();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(NS_BLOB_STORE, 'readonly');
      const req = tx.objectStore(NS_BLOB_STORE).get(captureId);
      req.onsuccess = () => resolve(req.result ? req.result.blob : null);
      req.onerror = () => reject(req.error);
    });
  }

  async function del(captureId) {
    const db = await openDb();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(NS_BLOB_STORE, 'readwrite');
      tx.objectStore(NS_BLOB_STORE).delete(captureId);
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
    });
  }

  async function listEntries() {
    const db = await openDb();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(NS_BLOB_STORE, 'readonly');
      const req = tx.objectStore(NS_BLOB_STORE).getAll();
      req.onsuccess = () => resolve((req.result || []).map(r => ({ captureId: r.captureId, storedAt: r.storedAt, bytes: r.bytes })));
      req.onerror = () => reject(req.error);
    });
  }

  async function pruneExpired(ttlMs = NS_BLOB_TTL_MS, maxCount = NS_BLOB_MAX_COUNT, maxBytes = NS_BLOB_MAX_BYTES) {
    const entries = await listEntries();
    const { evict } = nsBlobRetentionPlan(entries, Date.now(), { ttlMs, maxCount, maxBytes });
    for (const id of evict) await del(id);
    return { evicted: evict.length, evictedIds: evict };
  }

  root.NSCaptureBlobStore = {
    put, get, delete: del, pruneExpired, listEntries, nsBlobRetentionPlan,
    NS_BLOB_TTL_MS, NS_BLOB_MAX_COUNT, NS_BLOB_MAX_BYTES,
  };
})(typeof self !== 'undefined' ? self : this);
