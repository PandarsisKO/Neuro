// The shipped app → MV3 worker → popup → existing walker, with Chrome/Reddit/app I/O faked.
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync, writeFileSync} from 'node:fs';
import {webcrypto} from 'node:crypto';
import {JSDOM} from 'jsdom';
const root = new URL('../../', import.meta.url);
const read = p => readFileSync(new URL(p, root), 'utf8');
const event = () => ({listeners:[], addListener(fn){this.listeners.push(fn);}});
const data = {appUrl:'http://localhost:8000', token:'test-token', lastProject:'other'};
const tabs = new Map([[1,{id:1,url:'http://localhost:8000/',windowId:7,active:true}]]);
let feedStatus = 200, loadedPage = null;
let created = 0, scriptReads = 0, proposals = [], external, internal, readGate = null;
const changed = event();
const chrome = {
  runtime:{getManifest:()=>({version:'1.11.4'}), onInstalled:event(), onStartup:event(),
    onMessageExternal:{addListener:fn=>{external=fn;}}, onMessage:{addListener:fn=>{internal=fn;}},
    sendMessage(msg,cb){internal(msg,{},cb);}},
  storage:{onChanged:changed, local:{
    async get(keys){if(keys==null)return {...data}; return Object.fromEntries((Array.isArray(keys)?keys:[keys]).filter(k=>k in data).map(k=>[k,data[k]]));},
    async set(obj){const changes={}; for(const [k,v] of Object.entries(obj)){changes[k]={oldValue:data[k],newValue:structuredClone(v)};data[k]=structuredClone(v);}
      for(const fn of changed.listeners) fn(changes,'local');},
    async remove(keys){for(const k of Array.isArray(keys)?keys:[keys]) delete data[k];}
  }},
  tabs:{onUpdated:event(),onRemoved:event(),onActivated:event(),
    async query(q){return [...tabs.values()].filter(t=>!q.active||t.active);},
    async get(id){if(!tabs.has(id))throw Error('closed');return tabs.get(id);},
    async create(obj){created++;for(const t of tabs.values())t.active=false;const t={...obj,id:100+created,status:'complete'};tabs.set(t.id,t);return t;},
    async update(id,obj){if(obj.active)for(const t of tabs.values())t.active=false;Object.assign(tabs.get(id),obj);return tabs.get(id);}
  },
  action:{async setBadgeText(){},async setTitle(){},async setBadgeBackgroundColor(){}},
  alarms:{onAlarm:event(),create(){},clear(){}},
  scripting:{async executeScript(opts){scriptReads++;if(readGate)await readGate;
    if (opts.func.name === 'readLoadedFeed') return [{result:loadedPage.window.eval('(' + opts.func.toString() + ')(' + JSON.stringify(opts.args[0]) + ')')}];
    if (feedStatus !== 200) return [{result:{status:feedStatus,json:null}}];
    return [{result:{status:200,json:{data:{children:[{kind:'t3',data:{id:'abc123',title:'Owner experience',selftext:'My experience',permalink:'/r/quickbooks/comments/abc123/owner/',created_utc:Date.now()/1000}},{kind:'t3',data:{id:'old456',title:'Old post',permalink:'/r/quickbooks/comments/old456/old/',created_utc:1}}],after:null}}}}];}}
};
const fetch = async (url, opts={}) => {
  if(url.endsWith('/api/projects'))return {ok:true,json:async()=>[{id:'project-one',name:'Business <research>'},{id:'other',name:'Other'}]};
  if(url.endsWith('/api/community/proposals')){proposals.push(JSON.parse(opts.body));return {ok:true,json:async()=>({proposed:1,collection_id:'review-one'})};}
  if(url.endsWith('/api/capture/pending'))return {ok:true,json:async()=>({items:[]})};
  if(url.endsWith('/api/extension/heartbeat'))return {ok:true,json:async()=>({})};
  throw Error('Unexpected fetch '+url);
};
function bootWorker(){
  const ctx=vm.createContext({chrome,fetch,URL,Map,Set,crypto:webcrypto,console,Date,setTimeout,clearTimeout,FormData,Blob});ctx.self=ctx;
  ctx.importScripts=(...files)=>files.forEach(f=>vm.runInContext(read('extension/'+f),ctx));
  vm.runInContext(read('extension/background.js'),ctx);return ctx;
}
let worker=bootWorker();
assert.equal(vm.runInContext("NSC.subredditUrl('https://www.reddit.com/r/go/')",worker),'https://www.reddit.com/r/go/','preserve legacy short subreddit names');
const sender={url:'http://localhost:8000/#p/project-one/sources',tab:tabs.get(1)};
const task={type:'prepare-subreddit-scan',url:'https://old.reddit.com/r/QuickBooks/',projectId:'project-one',maxAgeDays:90,want:12};
const send=(msg,s=sender)=>new Promise(resolve=>external(msg,s,resolve));
const call=msg=>new Promise(resolve=>internal(msg,{},resolve));
const [first,duplicate]=await Promise.all([send(task),send(task)]);
assert.equal(first.ok,true);assert.equal(first.tab_id,duplicate.tab_id);assert.equal(created,1);
assert.equal(scriptReads,0);assert.equal(proposals.length,0,'preparation does not scan or rank');
const tabId=first.tab_id, key=`cscan:${tabId}`;
assert.equal(data[key].project_name,'Business <research>','project name comes from authenticated app');
assert.equal(data[key].url,'https://www.reddit.com/r/quickbooks/');
for(const [msg,s] of [[task,{...sender,url:'http://localhost:9000/'}],[task,{...sender,url:'https://evil.test/'}],
  [{...task,url:'https://reddit.com.evil.test/r/test/'},sender],[{...task,projectId:'missing'},sender],
  [{...task,url:'https://www.reddit.com/r/quickbooks/comments/abc/x/'},sender],[{...task,want:201},sender],
  [{...task,maxAgeDays:14},sender],[{...task,url:'javascript:alert(1)'},sender]]) {
  assert.ok((await send(msg,s)).error);assert.equal(created,1);
}
const revised = await send({...task,want:15});
assert.equal(revised.tab_id,tabId);assert.equal(data[key].want,15,'explicit re-prepare updates settings');
await send(task);
worker=bootWorker(); // MV3 restarted: the same prepared task survives, without another tab or scan.
assert.equal((await send(task)).tab_id,tabId);assert.equal(created,1);

const dom=new JSDOM(read('extension/popup.html'),{url:'https://extension.test/popup.html',runScripts:'outside-only'});
const w=dom.window;w.chrome=chrome;w.fetch=fetch;
for(const f of ['thread-capture.js','community-adapters.js','popup.js'])w.eval(read('extension/'+f));
const $=s=>w.document.querySelector(s);
const until=async fn=>{for(let n=0;n<100;n++){if(fn())return;await new Promise(r=>setTimeout(r,5));}throw Error('UI did not settle');};
await until(()=>$('#pageProject').value==='project-one'&&!$('#subredditScan').disabled);
assert.equal($('#pageProject').disabled,true,'prepared project cannot drift to lastProject');
assert.equal($('#subredditAge').value,'90');assert.equal($('#subredditWant').value,'12');
assert.equal($('#subredditScan').textContent,'Start prepared scan');
assert.match($('#preparedScan').textContent,/Business <research>/);assert.equal($('#preparedScan research'),null);
assert.equal($('#main').firstElementChild.id,'subredditCard','the next task is at the top');
assert.match($('#subredditMsg').textContent,/nothing has been scanned/);
$('#subredditWant').value='8';
await w.eval('renderCommunity()');
assert.equal($('#subredditWant').value,'8','refresh preserves deliberate edits');
if(process.argv[2]) {
  for(const select of w.document.querySelectorAll('select'))for(const option of select.options)option.toggleAttribute('selected',option.selected);
  for(const input of w.document.querySelectorAll('input'))input.setAttribute('value',input.value);
  writeFileSync(process.argv[2],dom.serialize());
}
assert.ok((await call({type:'cscan-start',tabId,projectId:'other',maxAgeDays:90,want:8})).error);
assert.equal(scriptReads,0);
tabs.get(tabId).url='https://smbmarket.com/dashboard/community/';
await w.eval('renderCommunity()');
assert.equal($('#subredditScan').disabled,true);assert.equal($('#dismissPrepared').hidden,false);
assert.match($('#subredditMsg').textContent,/tab changed/);
tabs.get(tabId).url='https://www.reddit.com/r/automation/';
assert.ok((await call({type:'cscan-start',tabId,projectId:'project-one',maxAgeDays:90,want:8})).error);
tabs.get(tabId).url=task.url;
const expires=data[key].expires_at;data[key].expires_at=Date.now()-1;
assert.ok((await call({type:'cscan-start',tabId,projectId:'project-one',maxAgeDays:90,want:8})).error);
data[key].expires_at=expires;
await w.eval('renderCommunity()');
// The popup's actual button runs the existing walker, and only now sends the listing for ranking/review.
let releaseRead; readGate = new Promise(resolve=>{releaseRead=resolve;});
$('#subredditScan').click();
await until(()=>scriptReads===1);
assert.equal((await send(task)).tab_id,tabId,'a running scan is reused, not replaced');
assert.equal(created,1);
assert.equal((await call({type:'cscan-dismiss-prepared',tabId})).ok,false,'dismiss cannot stop running work');
releaseRead(); readGate=null;
await until(()=>data[key].status==='proposed');
await until(()=>$('#subredditMsg a')?.textContent==='Review posts in Neuro');
assert.equal($('#subredditMsg a').href,'http://localhost:8000/#p/project-one/sources');
assert.equal(scriptReads,1);assert.equal(proposals.length,1);
assert.equal(proposals[0].items.length,1,'JSON timestamps are seconds; older posts respect the cutoff');assert.equal(proposals[0].project_id,'project-one');assert.equal(proposals[0].max_videos,8);
assert.equal((await call({type:'cscan-dismiss-prepared',tabId})).ok,false,'cannot delete a finished scan as a prepared step');
await send({...task,projectId:'other'});
assert.equal(created,2,'another project gets a separate task; finished results are preserved');
assert.equal((await call({type:'cscan-dismiss-prepared',tabId:102})).ok,true);
assert.equal(data['cscan:102'],undefined);
// Live regression: a signed-in Reddit page renders posts while /new.json answers HTTP 403.
feedStatus=403; tabs.get(tabId).active=true;tabs.get(102).active=false;
const options={type:'cscan-start',tabId,projectId:'project-one',maxAgeDays:365,want:8};
assert.ok((await call({...options,listingMode:'loaded'})).error,'loaded recovery requires a failed task');
await call(options);await until(()=>data[key].status==='failed');
assert.equal(data[key].reason,'feed_unreadable');assert.match(data[key].errors[0],/HTTP 403/);
await w.eval('renderCommunity()');
assert.equal($('#subredditLoaded').hidden,false);assert.equal($('#pageProject').value,'project-one');
assert.equal($('#pageProject').disabled,true);assert.equal($('#subredditAge').value,'365');assert.equal($('#subredditWant').value,'8');
assert.match($('#subredditMsg').textContent,/even while signed in/);assert.doesNotMatch($('#subredditMsg').textContent,/are you signed in/);
assert.match($('#subredditMsg').textContent,/does not cover the full time window/);
if(process.argv[3])writeFileSync(process.argv[3],dom.serialize());
const at=new Date().toISOString().replace('Z','000+0000');
const card=(id,attrs='',body='')=>`<shreddit-post id="t3_${id}" permalink="/r/QuickBooks/comments/${id}/title/" post-title="Owner &amp; business" created-timestamp="${at}" author="owner" score="0" comment-count="12" ${attrs}><div slot="text-body">${body}</div></shreddit-post>`;
loadedPage=new JSDOM(card('abc123','','Rendered excerpt')+card('abc123')+card('ad123','promoted')+card('other','permalink="https://evil.test/r/quickbooks/comments/other/title/"')+card('old123').replace(at,'2020-01-01T00:00:00Z')+card('unknown').replace(`created-timestamp="${at}"`,''),{url:task.url,runScripts:'outside-only'});
// Test the real injected function directly, including same-subreddit provenance, ads and own permalink.
const reader=vm.runInContext("NSC.all.find(a=>a.key==='reddit').readLoadedFeed.toString()",worker);
const snapshot=()=>loadedPage.window.eval('('+reader+')('+JSON.stringify(task.url)+')');
loadedPage.window.document.querySelector('#t3_other').setAttribute('permalink','https://evil.test/r/quickbooks/comments/other/title/');
assert.equal(snapshot().items.length,3,'dedupe and exclude promoted/foreign posts');
assert.equal(snapshot().items[0].body,'Rendered excerpt');assert.equal(snapshot().items[0].score,0);
assert.equal(snapshot().items[0].url,'https://www.reddit.com/r/QuickBooks/comments/abc123/title/');
assert.ok(loadedPage.window.eval('('+reader+')("https://www.reddit.com/r/other/")').error);
assert.ok((await call({...options,projectId:'other',listingMode:'loaded'})).error);
assert.ok((await call({...options,want:201,listingMode:'loaded'})).error);
const before=proposals.length;
$('#subredditLoaded').click();await until(()=>data[key].status==='proposed');
await w.eval('renderCommunity()');
assert.equal(proposals.length,before+1);assert.equal(proposals.at(-1).items.length,1,'exclude old and undated posts within a dated window');
assert.equal(proposals.at(-1).project_id,'project-one');assert.equal(proposals.at(-1).max_videos,8);
assert.equal(data[key].listing_method,'rendered');assert.equal(data[key].skipped_old,1);assert.equal(data[key].skipped_undated,1);
assert.match($('#subredditMsg').textContent,/Loaded posts only/);assert.match($('#subredditMsg').textContent,/partial listing/);
assert.equal($('#subredditLoaded').hidden,true);
// No posts / changed page never enqueue a misleading empty review; recovery remains available.
await call(options);await until(()=>data[key].status==='failed');
loadedPage.window.document.body.innerHTML='';
await call({...options,listingMode:'loaded'});await until(()=>data[key].status==='failed');
assert.equal(data[key].reason,'no_loaded_posts');assert.equal(proposals.length,before+1);
await w.eval('renderCommunity()');assert.equal($('#subredditLoaded').hidden,false);
assert.match($('#subredditMsg').textContent,/no loaded posts match/);
loadedPage.window.close();dom.window.close();console.log('Reddit extension handoff workflow PASS');
