/* Comparison chat owns its state; only successful server snapshots replace results. */
(() => {
  const $ = id => document.getElementById(id);
  let session=null, comparison=null, generation=0, working=false, painting=false, retry=null, conflict=false;
  const panel=$('comparison-chat');
  const message=$('scenario-status');
  function controls() {
    for (const id of ['scenario-send','scenario-input','scenario-original','scenario-previous','scenario-reload']) $(id).disabled=working || !session;
    $('scenario-retry').hidden=working || !comparison || (!!session && !retry);
    $('scenario-retry').textContent=session ? 'Retry last request' : 'Retry chat';
    $('scenario-reload').hidden=!conflict;
    $('scenario-original').hidden=false;
    $('scenario-previous').hidden=false;
    $('scenario-state-panel').hidden=false;
    for (const id of ['scenario-suggest-contract','scenario-suggest-credit','scenario-suggest-why']) $(id).disabled=working || !session;
  }
  function remember() {
    if (!session) return;
    try { localStorage.setItem('comparison-chat:'+comparison.id,JSON.stringify({id:session.session_id,token:session.token})); } catch (_) { /* Chat still works without local storage. */ }
  }
  async function api(path, body, token) {
    const response=await fetch('/api/comparison-chat'+path,{method:body?'POST':'GET',headers:{'Content-Type':'application/json',...(token?{'X-Scenario-Token':token}:{})},...(body?{body:JSON.stringify(body)}:{})});
    const data=await response.json();
    if (!response.ok) { const error=new Error(typeof data.detail==='string'?data.detail:(data.detail?.message || 'Invalid request. Check your message and try again.'));error.status=response.status;error.code=data.detail?.code;throw error; }
    return data;
  }
  function answerText(parent, text) {
    // Text nodes only: plan names, messages and excerpts are untrusted content.
    const label=text.match(/^([^:]{1,70}):\s*/);
    if(label) {
      const strong=document.createElement('strong');strong.textContent=label[1]+': ';
      const rest=document.createElement('span');rest.textContent=text.slice(label[0].length);
      parent.append(strong,rest);
    } else parent.textContent=text;
  }
  function formatAnswer(parent, text) {
    for(const block of text.split(/\n+|(?<=[.!?])\s+(?=[A-Z])/).map(s=>s.trim()).filter(Boolean)) {
      if(block.includes(';')) {
        const heading=block.match(/^([^:]{1,70}):\s*(.*)$/);
        let details=block;
        if(heading && !/^month\s+\d+$/i.test(heading[1]) && heading[2].includes(';')) {
          const title=document.createElement('p');title.className='scenario-detail-heading';
          title.textContent=heading[1];parent.append(title);details=heading[2];
        }
        const list=document.createElement('ul');list.className='scenario-detail-list';
        for(const item of details.split(';').map(s=>s.trim()).filter(Boolean)) {
          const row=document.createElement('li');answerText(row,item);list.append(row);
        }
        parent.append(list);
      } else {
        const paragraph=document.createElement('p');answerText(paragraph,block);parent.append(paragraph);
      }
    }
  }
  function show(data, scrollToAnswer=false) {
    const resultChanged=comparison?.id !== data.result.id;
    session={...data,token:data.token || session?.token};
    comparison=data.result;
    $('scenario-messages').replaceChildren();
    for (const attempt of data.attempts) {
      const entry=document.createElement('div');entry.className='scenario-entry';
      const user=document.createElement('p');user.className='scenario-user';user.textContent=attempt.user;
      const bubble=document.createElement('div');bubble.className='scenario-answer';
      const label=document.createElement('p');label.className='scenario-outcome';
      label.textContent=({updated:'Comparison updated',clarify:'Clarification needed',no_matches:'No matching plans',invalid:'Changes not applied',unsupported:'Request not supported',restored:'Scenario restored',explained:'Plan advisor'})[attempt.status] || 'Plan advisor';
      const preview=document.createElement('p');preview.className='scenario-preview';
      preview.textContent=attempt.message;
      const full=document.createElement('div');full.className='scenario-full';formatAnswer(full,attempt.message);full.hidden=true;
      full.id='scenario-answer-'+$('scenario-messages').children.length;
      const toggle=document.createElement('button');toggle.type='button';toggle.className='text-link';toggle.textContent='Show more';
      toggle.setAttribute('aria-expanded','false');toggle.setAttribute('aria-controls',full.id);
      toggle.addEventListener('click',()=>{
        full.hidden=!full.hidden;preview.hidden=!full.hidden;
        toggle.textContent=full.hidden?'Show more':'Show less';toggle.setAttribute('aria-expanded',String(!full.hidden));
      });
      if(attempt.evidence_refs?.length) {
        const heading=document.createElement('p');heading.className='scenario-detail-heading';heading.textContent='Sources';full.append(heading);
      }
      for(const ref of attempt.evidence_refs || []) {
        const source=document.createElement('p');source.className='scenario-source';
        source.textContent=(ref.label || 'Source')+(ref.page ? `, page ${ref.page}` : '')+': '+(ref.quote || 'Saved source record');
        if(ref.url && (/^https?:\/\//i.test(ref.url) || /^\/(?!\/)/.test(ref.url)) && !ref.url.includes('\\')) {
          const link=document.createElement('a');link.href=ref.url;link.textContent='View source';link.target='_blank';link.rel='noopener noreferrer';source.append(link);
        }
        full.append(source);
      }
      bubble.append(label,preview,full,toggle);entry.append(user,bubble);$('scenario-messages').append(entry);
    }
    for (const failure of data.failures || []) { const note=document.createElement('p');note.className='note';note.textContent='Previous attempt: '+failure.message;$('scenario-messages').append(note); }
    const state=data.state;
    const prefs=state.request.recommendation_options;
    const names=new Map((data.available_plans || []).map(p=>[p.id,p.name]));
    $('scenario-state').textContent=[`Scenario ${data.active}. Comparison period: ${prefs.comparison_horizon || prefs.max_contract_months || 12} months`,
      `Maximum contract: ${prefs.max_contract_months ?? 'none'}; exact contract: ${prefs.exact_contract_months ?? 'any'}`,
      `Exclude credit plans: ${prefs.exclude_bill_credit_plans ? 'yes' : 'no'}`,
      `Renewal increase: ${prefs.renewal_escalation_pct ?? 5}%; renewal credits: ${prefs.renewal_credit_policy || 'retain'}`,
      `Baseline: ${names.get(prefs.baseline_plan_id) || 'none'}; switching costs: ${prefs.switching_cost ?? 'unknown'}`,
      `January to December usage (kWh): ${state.request.monthly_kwh.join(', ')}`,
      'Hypothetical overrides: '+(state.overrides.length ? state.overrides.map(o=>`${names.get(o.plan_id) || o.plan_id}: ${o.field.replaceAll('_',' ')} = ${o.value ?? 'no boundary'} ${o.unit.replaceAll('_',' ')} (${o.period})`).join('; ') : 'none'),
      'Editing the main comparison form starts a fresh comparison; chat-only filters and overrides are not submitted by that form.'
    ].join('\n');
    message.textContent=({updated:'Results updated below.',clarify:'Please answer the clarification in chat.',no_matches:'Previous results are unchanged.',invalid:'Previous results are unchanged.',restored:'Scenario restored.',explained:''})[data.status] ?? (data.needs_migration?'This comparison uses older pricing. Explicit migration is required before changing assumptions.':'Chat restored. Ask about this comparison.');
    painting=true;
    try { if(resultChanged) render(data.result); } finally { painting=false; }
    const options=state.request.recommendation_options;
    $('zip-code').value=state.request.zip_code;
    $('usage').value=state.request.monthly_kwh.join(', ');
    $('max-contract').value=options.max_contract_months ?? '';
    $('renewal-escalation').value=options.renewal_escalation_pct ?? 5;
    $('renewal-credits').value=options.renewal_credit_policy || 'retain';
    $('usage-provenance').value=options.usage_provenance || 'unknown';
    $('switching-cost').value=options.switching_cost ?? '';
    history.replaceState(null,'','/?comparison='+encodeURIComponent(comparison.id));
    conflict=false;remember();controls();
    if(scrollToAnswer) {
      const messages=$('scenario-messages');
      messages.scrollTo({top:messages.scrollHeight,behavior:globalThis.matchMedia?.('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth'});
    }
  }
  async function load(saved) {
    const epoch=++generation;working=true;controls();
    try {
      const data=await api('/'+saved.id,null,saved.token);
      if (epoch!==generation)return;
      session={token:saved.token};show(data);
    } catch(error) { if(epoch===generation){message.textContent=error.message;session=null;} }
    finally {if(epoch===generation){working=false;controls();}}
  }
  globalThis.comparisonChat={
    park() {
      document.querySelector('.comparison-workspace').append(panel);
    },
    place() {
      const summary=document.querySelector('#results > .recommendation-summary');
      if(summary)summary.insertAdjacentElement('afterend',panel);
      else document.getElementById('results').prepend(panel);
    },
    attach(data) {
      if(painting)return;
      generation++;working=false;session=null;retry=null;conflict=false;comparison=data;panel.hidden=false;
      $('scenario-state-panel').open=false;
      $('scenario-messages').replaceChildren();$('scenario-state').textContent='Loading scenario settings...';message.textContent='';controls();
      try {const saved=JSON.parse(localStorage.getItem('comparison-chat:'+data.id));if(saved?.id && saved?.token){void load(saved);return;}}catch(_){}
      void start();
    },
    detach() {generation++;session=null;comparison=null;working=false;retry=null;panel.hidden=true;controls();}
  };
  async function start() {
    if(working || !comparison)return;
    const epoch=++generation;working=true;retry=null;controls();message.textContent='Opening conversation...';
    try {const data=await api('',{comparison_id:comparison.id});if(epoch===generation)show(data);}
    catch(error){if(epoch===generation)message.textContent=error.message;}
    finally{if(epoch===generation){working=false;controls();}}
  }
  function requestId() {
    if (crypto.randomUUID) return crypto.randomUUID();
    const bytes=crypto.getRandomValues(new Uint8Array(16));
    bytes[6]=(bytes[6]&15)|64;bytes[8]=(bytes[8]&63)|128;
    const hex=Array.from(bytes,b=>b.toString(16).padStart(2,'0')).join('');
    return `${hex.slice(0,8)}-${hex.slice(8,12)}-${hex.slice(12,16)}-${hex.slice(16,20)}-${hex.slice(20)}`;
  }
  async function send(text, reuse=false) {
    if(working || !session)return;
    const epoch=++generation;working=true;let answered=false;
    const body=reuse?retry:{request_id:requestId(),version:session.version,message:text};
    retry=body;controls();message.textContent='Evaluating scenario...';
    try {
      const data=await api('/'+session.session_id+'/messages',body,session.token);
      if(epoch!==generation)return;
      retry=null;show(data,true);$('scenario-input').value='';answered=true;
    } catch(error) {
      if(epoch!==generation)return;
      message.textContent=error.message;
      if([404,410].includes(error.status) || error.code==='conversation_limit'){session=null;retry=null;}
      if(error.status===409){retry=null;conflict=true;message.textContent+=' Use Reload chat to recover the latest scenario.';}
    } finally {if(epoch===generation){working=false;controls();if(answered && session && !panel.hidden) $('scenario-input').focus({preventScroll:true});}}
  }
  $('scenario-form').addEventListener('submit',event=>{event.preventDefault();const text=$('scenario-input').value.trim();if(text)void send(text);});
  $('scenario-input').addEventListener('keydown',event=>{if(event.key==='Enter' && !event.shiftKey && !event.isComposing){event.preventDefault();const text=$('scenario-input').value.trim();if(text)void send(text);}});
  $('scenario-original').addEventListener('click',()=>send('reset'));
  $('scenario-previous').addEventListener('click',()=>send('previous'));
  $('scenario-retry').addEventListener('click',()=>session ? send('',true) : start());
  $('scenario-reload').addEventListener('click',()=>{retry=null;if(session)void load({id:session.session_id,token:session.token});});
  for (const [id,text] of [['scenario-suggest-contract','Compare over 36 months, with a maximum 36-month contract.'],['scenario-suggest-credit','Avoid plans with bill credits.'],['scenario-suggest-why','Why']]) $(id).addEventListener('click',()=>{ $('scenario-input').value=text; $('scenario-input').focus(); });
  // app.js may finish its initial request before this deferred script registers.
  const id=new URLSearchParams(location.search).get('comparison');
  if(id && $('results').children.length) request('/api/comparisons/'+encodeURIComponent(id)).then(data=>{if(!comparison)globalThis.comparisonChat.attach(data);}).catch(()=>{});
})();
