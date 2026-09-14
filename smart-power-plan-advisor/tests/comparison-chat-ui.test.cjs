const test=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const crypto=require('node:crypto').webcrypto;
const flush=()=>new Promise(resolve=>setImmediate(resolve));
class Element {
  constructor(){this.children=[];this.handlers={};this.value='';this.disabled=false;this.hidden=false;this.textContent='';}
  setAttribute(name,value){this[name]=value;}
  focus(options){this.focused=options;this.disabledWhenFocused=this.disabled;}
  scrollIntoView(){throw new Error('Must not scroll the document');}
  scrollTo(options){this.scrolled=options;}
  addEventListener(name,fn){this.handlers[name]=fn;}
  append(...items){this.children.push(...items);}
  replaceChildren(...items){this.children=items;}
  fire(name){return this.handlers[name]?.({preventDefault(){},key:'',shiftKey:false,isComposing:false});}
}
function view(version=0,id='original'){
 return {session_id:'session',version,token:'token',result:{id},state:{request:{zip_code:'75201',monthly_kwh:Array(12).fill('1800'),recommendation_options:{}},overrides:[]},history:[],active:version,attempts:[],pending:null,needs_migration:false};
}
function setup(handler){
 const ids=new Set([...fs.readFileSync('frontend/index.html','utf8').matchAll(/id="([^"]+)"/g)].map(match=>match[1]));
 const nodes=new Map();const get=id=>{if(!ids.has(id))return null;if(!nodes.has(id))nodes.set(id,new Element());return nodes.get(id);};
 let context;const rendered=[];const requests=[];
 const memory=new Map();
 context=vm.createContext({document:{getElementById:get,createElement:()=>new Element()},crypto,
   localStorage:{getItem:k=>memory.get(k)||null,setItem:(k,v)=>memory.set(k,v)},
   URLSearchParams,location:{search:''},history:{replaceState(){}},
   render(data){rendered.push(data);context.comparisonChat.attach(data);},
   fetch:async(url,options)=>{requests.push({url,...options});return handler(url,options);}});
 vm.runInContext(fs.readFileSync('frontend/comparison-chat.js','utf8'),context);
 context.comparisonChat.attach({id:'original'});
 return {get,context,rendered,requests};
}
const ok=data=>({ok:true,status:200,json:async()=>data});
const error=status=>({ok:false,status,json:async()=>({detail:'Request failed'})});
test('successful scenario renders server results and saves state',async()=>{
 const app=setup(async(url)=>ok(url.endsWith('/messages')?view(1,'new'):view()));
 await flush();
 app.get('scenario-input').value='36 months';app.get('scenario-form').fire('submit');await flush();
 assert.equal(app.rendered.at(-1).id,'new');
 assert.equal(app.get('scenario-input').value,'');
 assert.match(app.get('scenario-state').textContent,/Scenario 1/);
});
test('network failure preserves results and retry reuses exactly the same request',async()=>{
 let fail=true;
 const app=setup(async(url)=>{if(url.endsWith('/messages')&&fail){fail=false;throw new Error('offline');}return ok(view());});
 await flush();
 app.get('scenario-input').value='why';app.get('scenario-form').fire('submit');await flush();
 assert.equal(app.get('scenario-retry').hidden,false);
 const body=app.requests.at(-1).body;
 app.get('scenario-retry').fire('click');await flush();
 assert.equal(app.requests.at(-1).body,body);
 assert.equal(app.get('scenario-retry').hidden,true);
});
test('overlapping submits are blocked and a detached response cannot restore results',async()=>{
 let release;
 const app=setup(async(url)=>url.endsWith('/messages')?new Promise(r=>release=r):ok(view()));
 await flush();
 app.get('scenario-input').value='why';app.get('scenario-form').fire('submit');await flush();
 app.get('scenario-form').fire('submit');
 assert.equal(app.requests.filter(r=>r.url.endsWith('/messages')).length,1);
 app.context.comparisonChat.detach();release(ok(view(1,'late')));await flush();
 assert.equal(app.get('comparison-chat').hidden,true);
 assert.equal(app.rendered.length,0);
});
test('expired session offers restart and conflict offers reload',async()=>{
 for(const status of [410,409]){
  const app=setup(async(url)=>url.endsWith('/messages')?error(status):ok(view()));
  await flush();app.get('scenario-input').value='why';app.get('scenario-form').fire('submit');await flush();
  assert.equal(app.get('scenario-state-panel').hidden,false);
  assert.equal(app.get('scenario-retry').hidden,status!==410);
  assert.equal(app.get('scenario-send').disabled,status===410);
  if(status===409)assert.match(app.get('scenario-status').textContent,/Reload chat/);
 }
});

test('assistant answers expand inline without duplicating full text in status',async()=>{
 const data=view();data.status='updated';data.message='Long detailed explanation. '.repeat(30);data.attempts=[{user:'Try 36 months',status:'updated',message:data.message}];
 const app=setup(async()=>ok(data));await flush();
 const bubble=app.get('scenario-messages').children[0].children[1];
 const [label,preview,full,toggle]=bubble.children;
 assert.equal(label.textContent,'Comparison updated');assert.equal(full.hidden,true);
 assert.equal(toggle.textContent,'Show more');assert.equal(toggle['aria-expanded'],'false');
 toggle.fire('click');assert.equal(full.hidden,false);assert.equal(preview.hidden,true);assert.equal(toggle.textContent,'Show less');
 toggle.fire('click');assert.equal(full.hidden,true);assert.equal(preview.hidden,false);
 assert.equal(app.get('scenario-status').textContent,'Results updated below.');
 assert.equal(app.get('scenario-reload').hidden,true);
});

test('catalog and TXU comparisons expose Explore alternatives including rough-only results',async()=>{
 for(const mode of ['catalog','txu']){
  const app=setup(async()=>ok(view()));
  app.context.comparisonChat.attach({id:'original',data_mode:mode,recommendations:[],rough_estimates:[{plan_id:'rough'}]});
  assert.equal(app.get('comparison-chat').hidden,false);
  assert.equal(app.get('scenario-state-panel').hidden,false);
  await flush();
  assert.ok(app.requests.some(r=>r.url==='/api/comparison-chat'));
 }
});


test('automatic initialization retries failures without changing results',async()=>{
 let fail=true;
 const app=setup(async()=>{if(fail)throw new Error('offline');return ok(view());});
 assert.equal(app.get('scenario-send').disabled,true);
 await flush();
 assert.equal(app.rendered.length,0);
 assert.equal(app.requests.length,1);
 assert.equal(app.get('scenario-retry').hidden,false);
 fail=false;await app.get('scenario-retry').fire('click');await flush();
 assert.equal(app.get('scenario-send').disabled,false);
 assert.equal(app.requests.length,2);
});

test('reattaching a saved comparison restores chat without creating another session',async()=>{
 const app=setup(async()=>ok(view()));await flush();
 app.context.comparisonChat.attach({id:'original'});await flush();
 assert.equal(app.requests.length,2);
 assert.equal(app.requests[1].method,'GET');
 assert.equal(app.get('scenario-original').hidden,false);
 const html=fs.readFileSync('frontend/index.html','utf8');
 assert.doesNotMatch(html,/id="scenario-start"/);
 assert.match(html,/<details id="scenario-state-panel">/);
});

test('initialization response is ignored after comparison is detached',async()=>{
 let release;
 const app=setup(()=>new Promise(resolve=>release=resolve));
 app.context.comparisonChat.detach();release(ok(view()));await flush();
 assert.equal(app.rendered.length,0);
 assert.equal(app.get('comparison-chat').hidden,true);
});


test('turn limit offers restart instead of retrying the exhausted request',async()=>{
 const app=setup(async(url)=>url.endsWith('/messages')?{ok:false,status:429,json:async()=>({detail:{code:'conversation_limit',message:'Restart chat'}})}:ok(view()));
 await flush();app.get('scenario-input').value='why';app.get('scenario-form').fire('submit');await flush();
 assert.equal(app.get('scenario-send').disabled,true);
 assert.equal(app.get('scenario-retry').hidden,false);
 await app.get('scenario-retry').fire('click');await flush();
 assert.equal(app.requests.at(-1).url,'/api/comparison-chat');
 assert.equal(app.get('scenario-send').disabled,false);
});

test('answer preview preserves the question response and source links reject unsafe URLs',async()=>{
 const data=view();data.attempts=[{user:'credits?',status:'explained',message:'Credit is $40. Saver is recommended at $100 over 12 months.',evidence_refs:[{label:'EFL',page:1,quote:'Credit terms',url:'/document.pdf'},{label:'Bad',quote:'Untrusted',url:'javascript:alert(1)'}]}];
 const app=setup(async()=>ok(data));await flush();
 const [label,preview,full]=app.get('scenario-messages').children[0].children[1].children;
 assert.match(preview.textContent,/^Credit is/);
 const sources=full.children.filter(node=>node.className==='scenario-source');
 assert.equal(sources[0].children[0].href,'/document.pdf');
 assert.equal(sources[1].children.length,0);
});


test('settings default collapsed; replies preserve expansion and scroll only newest answer',async()=>{
 const first=view();first.attempts=[{user:'why',status:'explained',message:'Earlier answer'}];
 const next=view(1,'new');next.attempts=[...first.attempts,{user:'credits?',status:'clarify',message:'Which plan?'}];
 const app=setup(async url=>ok(url.endsWith('/messages')?next:first));await flush();
 assert.equal(app.get('scenario-state-panel').open,false);
 assert.equal(app.get('scenario-messages').children[0].children[1].scrolled,undefined);
 app.get('scenario-state-panel').open=true;
 app.get('scenario-input').value='credits?';app.get('scenario-form').fire('submit');await flush();
 const entries=app.get('scenario-messages').children;
 assert.equal(entries[0].children[1].scrolled,undefined);
 assert.equal(entries[1].children[1].scrolled,undefined);
 assert.equal(app.get('scenario-messages').scrolled.top,app.get('scenario-messages').scrollHeight);
 assert.equal(app.get('scenario-messages').scrolled.behavior,'smooth');
 assert.equal(app.get('scenario-state-panel').open,true);
 app.context.comparisonChat.attach({id:'original'});await flush();
 assert.equal(app.get('scenario-state-panel').open,false);
 assert.equal(app.get('scenario-messages').children[0].children[1].scrolled,undefined);
});

test('latest-answer scrolling honors reduced motion',async()=>{
 const data=view();data.attempts=[{user:'enroll',status:'unsupported',message:'Cannot enroll'}];
 const app=setup(async()=>ok(data));await flush();
 app.context.matchMedia=()=>({matches:true});
 app.get('scenario-input').value='enroll';app.get('scenario-form').fire('submit');await flush();
 assert.equal(app.get('scenario-messages').scrolled.behavior,'auto');
});


test('same comparison replies scroll internally without rebuilding results',async()=>{
 const data=view();data.attempts=[{user:'why',status:'explained',message:'Answer'}];
 const app=setup(async()=>ok(data));await flush();
 const messages=app.get('scenario-messages');messages.scrollHeight=900;
 assert.equal(messages.scrolled,undefined);
 app.get('scenario-input').value='why';app.get('scenario-form').fire('submit');await flush();
 assert.equal(app.rendered.length,0);
 assert.equal(messages.scrolled.top,900);
});


test('formatted answers preserve amounts as safe text and focus reenabled composer',async()=>{
 const data=view();data.attempts=[{user:'credits?',status:'explained',message:'Saver: Credit is $125.50. First-year modeled amounts: month 1: $0.00; month 2: $125.50. <img src=x onerror=alert(1)>'}];
 const app=setup(async()=>ok(data));await flush();
 assert.equal(app.get('scenario-input').focused,undefined);
 app.get('scenario-input').value='credits?';app.get('scenario-form').fire('submit');await flush();
 const full=app.get('scenario-messages').children[0].children[1].children[2];
 const list=full.children.find(node=>node.className==='scenario-detail-list');
 assert.ok(list);assert.equal(list.children.length,2);
 function content(node){return node.textContent+node.children.map(content).join('');}
 assert.match(content(full),/125\.50/);assert.match(content(full),/<img src=x onerror=alert\(1\)>/);
 assert.equal(app.get('scenario-input').focused.preventScroll,true);
 assert.equal(app.get('scenario-input').disabledWhenFocused,false);
});

test('clarification and unsupported replies refocus, but detached replies do not',async()=>{
 for(const status of ['clarify','unsupported','invalid','no_matches']) {
  const data=view();data.status=status;data.attempts=[{user:'question',status,message:'Reply'}];
  const app=setup(async()=>ok(data));await flush();
  app.get('scenario-input').value='question';app.get('scenario-form').fire('submit');await flush();
  assert.equal(app.get('scenario-input').focused.preventScroll,true);
 }
 let release;const app=setup(async url=>url.endsWith('/messages')?new Promise(r=>release=r):ok(view()));await flush();
 app.get('scenario-input').value='question';app.get('scenario-form').fire('submit');await flush();
 app.context.comparisonChat.detach();release(ok(view()));await flush();
 assert.equal(app.get('scenario-input').focused,undefined);
});
