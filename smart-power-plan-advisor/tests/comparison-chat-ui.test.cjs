const test=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const crypto=require('node:crypto').webcrypto;
const flush=()=>new Promise(resolve=>setImmediate(resolve));
class Element {
  constructor(){this.children=[];this.handlers={};this.value='';this.disabled=false;this.hidden=false;this.textContent='';}
  setAttribute(name,value){this[name]=value;}
  focus(){}
  addEventListener(name,fn){this.handlers[name]=fn;}
  append(...items){this.children.push(...items);}
  replaceChildren(...items){this.children=items;}
  fire(name){return this.handlers[name]?.({preventDefault(){},key:'',shiftKey:false,isComposing:false});}
}
function view(version=0,id='original'){
 return {session_id:'session',version,token:'token',result:{id},state:{request:{zip_code:'75201',monthly_kwh:Array(12).fill('1800'),recommendation_options:{}},overrides:[]},history:[],active:version,attempts:[],pending:null,needs_migration:false};
}
function setup(handler){
 const nodes=new Map();const get=id=>{if(!nodes.has(id))nodes.set(id,new Element());return nodes.get(id);};
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
 await app.get('scenario-start').fire('click');
 app.get('scenario-input').value='36 months';app.get('scenario-form').fire('submit');await flush();
 assert.equal(app.rendered.at(-1).id,'new');
 assert.equal(app.get('scenario-input').value,'');
 assert.match(app.get('scenario-state').textContent,/Scenario 1/);
});
test('network failure preserves results and retry reuses exactly the same request',async()=>{
 let fail=true;
 const app=setup(async(url)=>{if(url.endsWith('/messages')&&fail){fail=false;throw new Error('offline');}return ok(view());});
 await app.get('scenario-start').fire('click');
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
 await app.get('scenario-start').fire('click');
 app.get('scenario-input').value='why';app.get('scenario-form').fire('submit');await flush();
 app.get('scenario-form').fire('submit');
 assert.equal(app.requests.filter(r=>r.url.endsWith('/messages')).length,1);
 app.context.comparisonChat.detach();release(ok(view(1,'late')));await flush();
 assert.equal(app.get('comparison-chat').hidden,true);
 assert.equal(app.rendered.at(-1).id,'original');
});
test('expired session offers restart and conflict offers reload',async()=>{
 for(const status of [410,409]){
  const app=setup(async(url)=>url.endsWith('/messages')?error(status):ok(view()));
  await app.get('scenario-start').fire('click');app.get('scenario-input').value='why';app.get('scenario-form').fire('submit');await flush();
  assert.equal(app.get('scenario-start').disabled,false);
  assert.equal(app.get('scenario-retry').hidden,true);
  assert.equal(app.get('scenario-send').disabled,status===410);
  if(status===409)assert.match(app.get('scenario-status').textContent,/Reload chat/);
 }
});

test('assistant answers expand inline without duplicating full text in status',async()=>{
 const data=view();data.status='updated';data.message='Long detailed explanation. '.repeat(30);data.attempts=[{user:'Try 36 months',status:'updated',message:data.message}];
 const app=setup(async()=>ok(data));await app.get('scenario-start').fire('click');
 const bubble=app.get('scenario-messages').children[0].children[1];
 const [label,preview,full,toggle]=bubble.children;
 assert.equal(label.textContent,'Comparison updated');assert.equal(full.hidden,true);
 assert.equal(toggle.textContent,'Show more');assert.equal(toggle['aria-expanded'],'false');
 toggle.fire('click');assert.equal(full.hidden,false);assert.equal(preview.hidden,true);assert.equal(toggle.textContent,'Show less');
 toggle.fire('click');assert.equal(full.hidden,true);assert.equal(preview.hidden,false);
 assert.equal(app.get('scenario-status').textContent,'Results updated below.');
 assert.equal(app.get('scenario-reload').hidden,true);
});
