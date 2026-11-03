// Exercise the shipped UI functions against the real Sources markup, without a server or Reddit.
import assert from 'node:assert/strict';
import { readFileSync, writeFileSync } from 'node:fs';
import { JSDOM } from 'jsdom';
const root = new URL('../../', import.meta.url);
const read = name => readFileSync(new URL(name, root), 'utf8');
const dom = new JSDOM(read('neurosearch/web/index.html'), {url:'http://localhost:8000/', runScripts:'outside-only'});
const w = dom.window, $ = s => w.document.querySelector(s);
w.$ = $;
w.state = {project:{id:'project-fixture', name:'Business <research>'}, view:'test'};
w.jobsTimer = null;
w.setTimeout = () => 0; // no background polling/network during this deterministic gate
w.POLL = {enter:() => true, leave:() => {}};
w.esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
for (const name of ['sources', 'research']) w.eval(read(`neurosearch/web/js/${name}.js`).replace(/^export const moduleName = .*;$/m, ''));
w.loadSpend = async () => null;
w.loadBacklog = () => {};
w.restoreJobHistories = () => {};
const sub = 'https://www.reddit.com/r/quickbooks/';
const failed = {id:'failed-fixture', kind:'explore', status:'failed', progress:0, finished_at:Date.now()/1000,
  message:'error: Reddit API credentials are required to catalog a subreddit (REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET)',
  payload:{kind:'subreddit', url:sub}};
let jobs = [failed, {...failed, id:'failed-second'}], catalogs = [];
w.api = async url => {
  if (url.includes('/jobs?')) return jobs;
  if (url === '/api/stats') return {};
  if (url.endsWith('/subreddit-catalogs')) return {items:catalogs};
  throw Error(`Unexpected API read: ${url}`);
};
w.post = async () => {throw Error('Recovery display must not enqueue work');};
await w.loadJobs();
assert.equal($('#jobs').querySelectorAll('.subreddit-recovery').length, 1, 'aggregate repeated failures');
assert.equal($('#jobs').querySelectorAll('.subreddit-recovery a').length, 1, 'dedupe subreddit links');
assert.equal($('#jobs .subreddit-recovery a').href, sub);
assert.match($('#jobs').textContent, /Business <research>/);
assert.equal($('#jobs .subreddit-recovery research'), null, 'escape project name');
assert.match($('#jobs').textContent, /Scan this subreddit/);
assert.match($('#jobs').textContent, /Start ingesting selected/);
assert.match($('#jobs').textContent, /Retry server scan/);
assert.match($('#jobs').textContent, /Reddit API credentials are required/, 'keep original diagnostic');
assert.equal($('#jobs .subreddit-recovery a').rel, 'noopener noreferrer');
const failureMarkup = $('#jobs').innerHTML;

// The recovery button sends a typed task over the existing extension connection; it does not queue an ingest.
w.api = async url => {
  assert.equal(url, '/api/capture/pending'); return {extension:{id:'connected-extension'}};
};
let handoff;
w.chrome = {runtime:{sendMessage(id,msg,reply){
  assert.equal(id,'connected-extension');handoff=msg;reply({ok:true,status:'prepared',project_name:'Business <research>'});
}}};
await w.prepareSubredditInChrome(sub,$('#jobs .subreddit-step button'));
assert.equal(handoff.type,'prepare-subreddit-scan');assert.equal(handoff.projectId,'project-fixture');
assert.equal(handoff.url,sub);assert.equal(handoff.maxAgeDays,365);assert.equal(handoff.want,20);
assert.match($('#jobs [role=status]').textContent,/press Start prepared scan/);
w.chrome = null;
await w.prepareSubredditInChrome(sub,$('#jobs .subreddit-step button'));
assert.match($('#jobs [role=status]').textContent,/Open Neuro in Chrome/);
w.api = async url => {
  if (url.includes('/jobs?')) return jobs;
  if (url === '/api/stats') return {};
  if (url.endsWith('/subreddit-catalogs')) return {items:catalogs};
  throw Error(`Unexpected API read: ${url}`);
};

// Ordinary failures and successful Reddit work keep their existing behavior.
jobs = [{...failed, kind:'ingest_url', payload:{url:'https://example.test/'}}];
await w.loadJobs();
assert.equal($('#jobs .subreddit-recovery'), null);
assert.match($('#jobs').textContent, /↻ Retry/);
jobs = [{...failed, status:'done'}];
await w.loadJobs();
assert.equal($('#jobs .subreddit-recovery'), null);

catalogs = [{id:'catalog', external_id:'quickbooks', url:sub, scan:{status:'blocked', error:failed.message}}];
await w.loadSubredditCatalogs();
assert.match($('#subredditCatalogs').textContent, /Scan this subreddit/);
assert.match($('#subredditCatalogs').textContent, /Reddit API credentials are required/);
catalogs = [];
await w.loadSubredditCatalogs();
assert.match($('#subredditCatalogs').textContent, /Paste a supported/);
assert.equal($('#subredditCatalogs .subreddit-recovery'), null);

$('#inUrls').value = sub;
w.post = async (url, body) => {
  assert.equal(url, '/api/classify');
  assert.equal(body.input, sub);
  return {items:[{kind:'subreddit', url:sub, label:'Subreddit detected', detail:'A reusable catalog', actions:[]}]};
};
await w.classifyInput();
assert.match($('#inDetect').textContent, /Scan this subreddit/, 'guidance before queueing');
assert.match($('#inDetect').textContent, /no Reddit API keys are needed/);
for (const url of ['javascript:alert(1)', 'https://reddit.com.evil.test/r/test/', 'https://example.test/r/test/',
  'https://www.reddit.com/r/test/comments/abc/title/', 'https://www.reddit.com/r/\"><img>']) {
  assert.equal(w.subredditRecovery([url]), '', `unsafe or non-container link: ${url}`);
}
assert.match(w.subredditRecovery(['https://old.reddit.com/r/QuickBooks/?sort=new']), /href="https:\/\/www.reddit.com\/r\/quickbooks\/"/);

// Optional static, isolated browser preview: the actual rendered failure markup and shipped CSS.
if (process.argv[2]) writeFileSync(process.argv[2], `<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Reddit recovery preview</title><style>${read('neurosearch/web/styles.css')}</style><main class="card"><h2>In progress</h2>${failureMarkup}</main>`);
dom.window.close();
console.log('Reddit recovery UI workflow PASS');
